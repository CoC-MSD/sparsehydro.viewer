"""Installation self-test: ``sparsehydro-viewer --self-test REPORT``.

Exercises what a frozen (PyInstaller) build most often gets wrong — modules
found only at run time (registries, extensions), compiled extensions, spawned
calibration workers, Qt plugins and SQLite — on synthetic data, and writes a
plain-text report. A windowed executable has no console, so the report goes
to a file; the exit code is 0 when every required check passes.

Optional components (e.g. the Platypus optimizers, which the default
installer leaves out for licensing reasons) are reported as unavailable
without failing the test.
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

#: Packages whose absence is reported but does not fail the self-test (one NSGA-II implementation is enough).
OPTIONAL_SOLVER_MODULES = {"platypus", "pymoo"}


def synthetic_frame(days: int = 6, step_min: int = 15) -> Any:
    """Rain bursts and a lagged, smoothed storm-flow response."""
    import numpy as np
    import pandas as pd

    n = days * 24 * 60 // step_min
    t = pd.date_range("2022-05-01", periods=n, freq=f"{step_min}min")
    rain = np.zeros(n)
    for start in (40, 200, 380):
        rain[start:start + 8] = 0.08
    k = np.exp(-np.arange(96) / 12.0)
    flow = 0.3 + np.convolve(rain, k / k.sum() * 40.0)[:n]
    return pd.DataFrame({"datetime": t, "rain": rain, "stormflow": flow, "flow": flow})


class _Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.failed = 0

    def check(self, name: str, fn: Callable[[], str], *, optional: bool = False) -> None:
        t0 = time.perf_counter()
        try:
            detail = fn()
            status = "ok"
        except ModuleNotFoundError as exc:
            if optional or exc.name in OPTIONAL_SOLVER_MODULES:
                status, detail = "unavailable", f"optional module {exc.name!r} not installed"
            else:
                status, detail = "FAIL", traceback.format_exc()
        except Exception:  # noqa: BLE001 - every failure is reported, none stops the test
            status, detail = "FAIL", traceback.format_exc()
        self.failed += status == "FAIL"
        self.lines.append(f"[{status:>11}] {name} ({time.perf_counter() - t0:.2f} s): {detail}".rstrip())


def _versions() -> str:
    import platform

    import numpy
    import pandas
    import pyqtgraph
    import PySide6
    import sparsehydro

    from . import __version__

    return (f"viewer {__version__}, sparsehydro {sparsehydro.__version__}, PySide6 {PySide6.__version__}, "
            f"pyqtgraph {pyqtgraph.__version__}, numpy {numpy.__version__}, pandas {pandas.__version__}, "
            f"Python {platform.python_version()} on {platform.platform()}")


def _extensions() -> str:
    from .core.extensions import load_extensions, report

    before = len(report().failed)  # the report is cumulative over the process
    rep = load_extensions()
    failed = rep.failed[before:]
    if failed:
        raise RuntimeError("; ".join(f"{label}: {err}" for label, err in failed))
    return f"{len(rep.loaded)} installed extensions loaded" + (f": {', '.join(rep.loaded)}" if rep.loaded else "")


def _components(frame) -> str:
    from .core.catalog import CATALOG, UH_KEYS, build_uh
    from .core.components import NEEDS_EXCESS

    data = CATALOG.prepare_frame(frame)
    done = []
    for key in UH_KEYS:
        if key in NEEDS_EXCESS:
            continue
        m = build_uh(key)
        m.initialize()
        m.validate()
        m.prepare(data)
        q = m.predict_arrays()["Q_pred"]
        if len(q) != len(data):
            raise AssertionError(f"{key}: {len(q)} values for {len(data)} steps")
        done.append(key)
    return f"{len(done)} unit hydrographs evaluated: {', '.join(done)}"


def _composed_models(frame) -> str:
    import numpy as np

    from .core.catalog import CATALOG, ModelSpec

    data = CATALOG.prepare_frame(frame)
    out = []
    for legacy in ({"kind": "rdii", "options": {"n_triangles": 2}}, {"kind": "abstraction-uh", "options": {}}):
        spec = ModelSpec.from_dict(legacy)
        model = CATALOG.instantiate(spec)
        model.prepare(data)
        q = np.asarray(model.predict_arrays()[CATALOG.predicted_key(spec)], float)
        trace = model.predict_trace()
        if not np.all(np.isfinite(q)):
            raise AssertionError(f"{legacy['kind']}: non-finite prediction")
        out.append(f"{legacy['kind']} ({len(trace)} traced fields)")
    return ", ".join(out)


def _multi_objective_available() -> str:
    from .core.solvers import SOLVERS

    names = [e.label for e in SOLVERS.entries() if e.multi_objective]
    if not names:
        raise RuntimeError("no multi-objective optimizer is installed (Platypus or pymoo)")
    return f"default {SOLVERS.get(SOLVERS.default().name).label}; available: {', '.join(names)}"


def _calibration_worker(frame, solver: str, options: dict[str, Any]) -> Callable[[], str]:
    """A tiny calibration in a spawned worker process, as the Calibrate page runs it."""

    def run() -> str:
        import multiprocessing as mp
        import queue as queue_mod

        from .core.calibration import CalibrationPayload, process_main
        from .core.catalog import ModelSpec
        from .core.objectives import ObjectiveSpec
        from .core.solvers import SOLVERS, SolverSpec

        entry = SOLVERS.get(solver)
        if not entry.available:
            raise ModuleNotFoundError(f"No module named {entry.requires!r}", name=entry.requires)
        SOLVERS.build(SolverSpec(solver, options))  # import errors surface here, in this process
        objectives = [ObjectiveSpec("rmse").to_dict()]
        if entry.multi_objective:
            objectives.append(ObjectiveSpec("nash_sutcliffe").to_dict())
        payload = CalibrationPayload("selftest", ModelSpec.from_dict({"kind": "gamma-uh", "options": {}}).to_dict(),
                                     objectives, SolverSpec(solver, options).to_dict(), frame, {})
        ctx = mp.get_context("spawn")
        q, stop = ctx.Queue(), ctx.Event()
        p = ctx.Process(target=process_main, args=(payload, q, stop), daemon=True)
        p.start()
        deadline = time.monotonic() + 180
        kinds = []
        try:
            while time.monotonic() < deadline:
                try:
                    _, kind, data = q.get(timeout=1.0)
                except queue_mod.Empty:
                    if not p.is_alive():
                        raise RuntimeError(f"worker exited with code {p.exitcode} after {kinds}") from None
                    continue
                kinds.append(kind)
                if kind == "finished":
                    return f"{entry.label}: {data['pareto_X'].shape[0]} solutions, {kinds.count('progress')} reports"
                if kind in ("failed", "cancelled"):
                    raise RuntimeError(data.get("traceback") or kind)
            raise TimeoutError("worker did not finish within 180 s")
        finally:
            if p.is_alive():
                p.terminate()
            p.join(5)

    return run


def _project_roundtrip(frame, folder: Path) -> str:
    import numpy as np

    from .core.data import DatasetSpec
    from .core.project import Project

    path = folder / "selftest.shproj"
    proj = Project()
    proj.add_dataset(DatasetSpec("selftest"), frame[["datetime", "rain", "stormflow"]].copy())
    proj.save(path)
    back = Project.load(path)
    got = back.frame("selftest")
    if not np.allclose(got["rain"].to_numpy(float), frame["rain"].to_numpy(float)):
        raise AssertionError("rain read back differs")
    if len(got) != len(frame):
        raise AssertionError(f"{len(got)} rows read back for {len(frame)}")
    return f"saved and reopened {path.name} ({path.stat().st_size // 1024} KiB)"


def _gis(folder: Path) -> str:
    """Write and read back a small layer in a projected CRS: exercises GDAL, its drivers and PROJ's data."""
    import struct

    import numpy as np

    from .core import gis

    if not gis.available():
        raise ModuleNotFoundError("No module named 'pyogrio'", name="pyogrio")
    import pyogrio.raw

    path = folder / "selftest.gpkg"
    ring = [(1400000.0, 400000.0), (1410000.0, 400000.0), (1410000.0, 410000.0), (1400000.0, 400000.0)]
    wkb = struct.pack("<BIII", 1, 3, 1, len(ring)) + b"".join(struct.pack("<dd", x, y) for x, y in ring)
    pyogrio.raw.write(str(path), np.array([wkb], dtype=object), [np.array(["zone"], dtype=object)], ["name"],
                      driver="GPKG", geometry_type="Polygon", crs="EPSG:3735", layer="zones")
    layer = gis.read_layer(path, "zones")
    if layer.kind != "zone" or layer.features[0].wkt is None:
        raise AssertionError(f"read back {layer.kind}")
    lon, lat = gis.parse_polygons(layer.features[0].wkt)[0][0][0]
    if not (-90 < lon < -80 and 35 < lat < 45):  # Ohio State Plane South -> Ohio
        raise AssertionError(f"reprojection gave {lon:.3f}, {lat:.3f}")
    import pyogrio

    return f"GeoPackage written and read, reprojected EPSG:3735 -> 4326 (GDAL {pyogrio.__gdal_version_string__})"


def _main_window() -> str:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from .app import create_app
    from .views.main_window import MainWindow

    app = create_app([])
    win = MainWindow()
    win.show()
    app.processEvents()
    pages = [p.title for p in win.pages]
    win.close()
    return f"{len(pages)} pages: {', '.join(pages)}"


def run_self_test(report: str | Path) -> int:
    """Run every check, write the report to *report* and return the exit code."""
    import tempfile

    r = _Report()
    r.check("versions", _versions)
    r.check("extensions", _extensions)
    frame = synthetic_frame()
    r.check("unit hydrographs", lambda: _components(frame))
    r.check("composed models and traces", lambda: _composed_models(frame))
    small = frame.iloc[:400].reset_index(drop=True)
    # One of the two NSGA-II implementations is enough: Platypus (pip installs) or pymoo (Windows installer).
    r.check("multi-objective optimizer installed", _multi_objective_available)
    r.check("calibration worker, NSGA-II (Platypus)",
            _calibration_worker(small, "platypus-nsga2", {"n_evaluations": 40, "record_frequency": 10}),
            optional=True)
    r.check("calibration worker, NSGA-II (pymoo)",
            _calibration_worker(small, "nsga2", {"pop_size": 8, "n_gen": 3}), optional=True)
    r.check("calibration worker, SciPy",
            _calibration_worker(small, "scipy", {"method": "Nelder-Mead", "maxiter": 20}))
    with tempfile.TemporaryDirectory() as tmp:
        r.check("project file", lambda: _project_roundtrip(frame, Path(tmp)))
        r.check("GIS import", lambda: _gis(Path(tmp)), optional=True)
    r.check("main window", _main_window)
    verdict = "PASSED" if not r.failed else f"FAILED ({r.failed} checks)"
    text = "\n".join([f"sparsehydro-viewer self-test: {verdict}", *r.lines, ""])
    Path(report).write_text(text, encoding="utf-8")
    return 1 if r.failed else 0


__all__ = ["run_self_test", "synthetic_frame"]
