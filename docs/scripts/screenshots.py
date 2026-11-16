"""Generate the documentation screenshots by driving the application offscreen.

    python docs/scripts/screenshots.py [output folder]   (default: docs/_static/screenshots)

Uses the bundled three-week sample (``tests/data``), a throwaway settings file (the user's settings are not
touched), small calibrations and the light theme, then saves one PNG per workspace view. Run it whenever the
interface changes; the docs workflow runs it before building.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "_static" / "screenshots"
SAMPLE = ROOT / "tests" / "data" / "tc-nb-001_2022-05.csv"
SIZE = (1600, 980)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if "QT_QPA_FONTDIR" not in os.environ:  # the offscreen platform has no fonts of its own
    for fonts in (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu"),
                  Path("/usr/share/fonts")):
        if fonts.is_dir():
            os.environ["QT_QPA_FONTDIR"] = str(fonts)
            break
warnings.simplefilter("ignore")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_settings_dir = tempfile.mkdtemp(prefix="shv-docs-")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, _settings_dir)


def pump(seconds: float = 0.2) -> None:
    """Run the event loop for a while, including the deferred deletions a real event loop would perform
    (without them, replaced widgets linger and overlap the new ones in the capture)."""
    from PySide6.QtCore import QCoreApplication, QEvent

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.01)


def wait(predicate, timeout: float = 120.0, what: str = "") -> None:
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise TimeoutError(f"timed out waiting for {what}")
        QApplication.processEvents()
        time.sleep(0.02)
    pump(0.3)


def main() -> int:
    from PySide6.QtGui import QFont

    from sparsehydro_viewer import theme
    from sparsehydro_viewer.app import create_app
    from sparsehydro_viewer.core.calibration import CalibrationPayload, run_calibration
    from sparsehydro_viewer.core.catalog import ModelSpec
    from sparsehydro_viewer.core.data import DatasetSpec, Period, load_dataset
    from sparsehydro_viewer.core.events import EventConfig
    from sparsehydro_viewer.core.objectives import ObjectiveSpec
    from sparsehydro_viewer.core.runs import RunRecord
    from sparsehydro_viewer.core.solvers import SOLVERS, SolverSpec
    from sparsehydro_viewer.views.main_window import MainWindow

    OUT.mkdir(parents=True, exist_ok=True)
    app = create_app([])
    app.setFont(QFont("Segoe UI" if sys.platform == "win32" else "DejaVu Sans", 9))
    theme.apply(app, theme.LIGHT)
    win = MainWindow()
    win.resize(*SIZE)
    win.show()
    s = win.ctx.session
    pages = {p.title: i for i, p in enumerate(win.pages)}
    results = [0]
    win.ctx.controller.result.connect(lambda *_: results.__setitem__(0, results[0] + 1))

    def settle() -> None:
        """Wait for the live simulation of the current sliders, then let the layout settle."""
        seen = results[0]
        try:
            wait(lambda: results[0] > seen, timeout=20, what="live result")
        except TimeoutError:
            pass  # nothing changed since the last result
        pump(0.8)

    def shot(name: str, page: str | None = None) -> None:
        if page is not None:
            win.nav.setCurrentRow(pages[page])
        pump(0.8)
        win.grab().save(str(OUT / f"{name}.png"))
        print("wrote", name)

    # -- data: one site with rain and flow, a sewershed around it --------------------------------------
    frame = load_dataset(DatasetSpec("sample", path=str(SAMPLE)))
    cal, val = Period("2022-05-01", "2022-05-14"), Period("2022-05-14 00:05", "2022-05-21 23:55")
    s.add_dataset(DatasetSpec("TC-NB-001", path=str(SAMPLE), calibration=cal, validation=val), frame)
    wait(lambda: s.dataset is not None, what="dataset")
    site = s.dataset.site_iri
    s.update_node(site, geometry="POINT (-84.5120 39.1031)")
    zone = s.add_node("zone", "Mill Creek sewershed", geometry=(
        "POLYGON ((-84.540 39.085, -84.490 39.082, -84.478 39.112, -84.505 39.128, -84.538 39.118, -84.540 39.085))"))
    s.add_node("monitoring_site", "TC-NB-002", geometry="POINT (-84.4950 39.1180)")
    s.select_nodes([site])
    sites = win.pages[pages["Sites"]]
    sites.tabs.setCurrentIndex(0)
    sites.map.zoom_to([zone])
    shot("sites-map", "Sites")
    sites.tabs.setCurrentIndex(1)
    shot("sites-timeseries", "Sites")

    # -- working model: initial abstraction and two RTK triangles --------------------------------------
    spec = ModelSpec.from_dict({"kind": "rdii", "options": {"n_triangles": 2}, "label": "RDII (IA; 2 RTK)"})
    model = win.pages[pages["Model"]]
    win.nav.setCurrentRow(pages["Model"])
    s.set_model(spec)
    settle()
    shot("model", "Model")
    model.components_action.trigger()  # checks it and computes the trace
    settle()
    shot("model-components", "Model")
    model.components_action.trigger()

    # -- two small calibrations (inline, then recorded as runs) ---------------------------------------------
    objectives = [ObjectiveSpec("nash_sutcliffe"), ObjectiveSpec("pbias")]
    solver = SOLVERS.default()
    budget = ({"n_evaluations": 2500, "record_frequency": 2} if solver.name.startswith("platypus")
              else {"pop_size": 50, "n_gen": 50})
    for i, n in enumerate((1, 2)):
        m = ModelSpec.from_dict({"kind": "rdii", "options": {"n_triangles": n}, "label": f"RDII (IA; {n} RTK)"})
        history = []
        out = run_calibration(CalibrationPayload(f"doc{i}", m.to_dict(), [o.to_dict() for o in objectives],
                                                 SolverSpec(solver.name, budget).to_dict(), frame, cal.to_dict()),
                              lambda kind, d, h=history: h.append((d["generation"], d["n_evals"], d["pareto_F"]))
                              if kind == "progress" else None)
        s.add_run(RunRecord(f"doc{i}", f"{n} RTK triangle{'s' if n > 1 else ''}", "TC-NB-001", m, objectives,
                            SolverSpec(solver.name, budget), status="finished", history=history,
                            **{k: out[k] for k in ("param_names", "objective_names", "minimize_flags", "pareto_X",
                                                   "pareto_F", "fixed_values", "n_params_total")}))
    calib = win.pages[pages["Calibrate"]]
    win.nav.setCurrentRow(pages["Calibrate"])
    calib._select_row("doc1")
    calib.history.setChecked(True)
    shot("calibrate", "Calibrate")

    win.show_explore("doc1")
    shot("explore")

    compare = win.pages[pages["Compare"]]
    win.nav.setCurrentRow(pages["Compare"])
    wait(lambda: len([k for k in compare.ts._curves if k.startswith("run:")]) == 2, what="compare hydrographs")
    compare.primary()
    wait(lambda: len(compare._scores) == 2, timeout=180, what="scores")
    shot("compare", "Compare")

    # -- events: two configurations, per event and pooled -------------------------------------------
    events = win.pages[pages["Events"]]
    win.nav.setCurrentRow(pages["Events"])
    # (not the Nash cascade next to the gamma UH: a Nash cascade is a gamma distribution, the fits coincide)
    events.set_configs([EventConfig.for_uh("gamma-uh", pooled=True), EventConfig.for_uh("triangle-uh")])
    events.run_analysis()
    wait(lambda: events.analysis is not None, timeout=300, what="events")
    events._step(1)
    shot("events", "Events")
    events.tabs.setCurrentIndex(3)
    shot("events-comparison", "Events")

    # -- assess the working model (its default values fit this sample better than the short calibrations) ---
    s.set_model(spec)
    settle()
    assess = win.pages[pages["Assess"]]
    win.nav.setCurrentRow(pages["Assess"])
    assess.primary()
    wait(lambda: "MSDGC" in assess.status_text(), timeout=180, what="assessment")
    shot("assess", "Assess")

    s.set_dirty(False)
    win.ctx.calibration.shutdown()
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
