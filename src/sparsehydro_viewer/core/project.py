"""Project persistence: one SQLite file (``*.shproj``).

A :class:`Project` holds the user's setup in memory (datasets and their
periods, models, objectives, solver, runs, UI state) and a
:class:`~.store.ProjectStore` working copy that holds the database content
(sites, sensors, zones, attributes, locations and the time series
themselves).  :meth:`Project.save` writes the setup into the store and the
store to disk; :meth:`Project.load` does the reverse.

Projects saved by earlier versions as a folder (``project.json`` plus
``runs/*.npz``) are imported on open: their datasets are read from the
original files into the database, and the project is saved as a ``.shproj``
on the next Save.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .catalog import ModelSpec
from .data import DatasetSpec, load_dataset
from .migration import UH_SCHEMA
from .objectives import DEFAULT_OBJECTIVES, ObjectiveSpec
from .runs import RunRecord
from .solvers import SOLVERS, SolverSpec
from .store import ProjectStore, StoreError

SUFFIX = ".shproj"
#: Observed properties of the series a dataset reads (seeded in the project database).
PROP_RAIN = "wsys:prop/rainfall_depth"
PROP_TEMPERATURE = "wsys:prop/temperature"
LEGACY_FILE = "project.json"
FORMAT_VERSION = 1


@dataclass
class Project:
    """Everything the user has set up and run, plus the project database."""

    name: str = "Untitled"
    path: Path | None = None
    datasets: list[DatasetSpec] = field(default_factory=list)
    models: list[ModelSpec] = field(default_factory=list)
    objectives: list[ObjectiveSpec] = field(default_factory=lambda: list(DEFAULT_OBJECTIVES))
    solver: SolverSpec = field(default_factory=lambda: SOLVERS.default())
    runs: list[RunRecord] = field(default_factory=list)
    ui_state: dict[str, Any] = field(default_factory=dict)
    store: ProjectStore = field(default_factory=ProjectStore.memory, repr=False, compare=False)
    #: Set when the project was imported from a legacy folder (it has no ``.shproj`` yet).
    imported_from: Path | None = None
    #: Datasets whose source files could not be read during a legacy import, and anything the
    #: step-based -> hours-based unit hydrograph conversion could not do.
    import_warnings: list[str] = field(default_factory=list)
    #: ``True`` when opening converted step-based unit hydrograph parameters (see :mod:`.migration`).
    migrated: bool = False

    @property
    def folder(self) -> Path | None:
        """Folder of the project file (relative dataset source paths are resolved against it)."""
        return self.path.parent if self.path else None

    # -- lookup ---------------------------------------------------------------

    def dataset(self, name: str) -> DatasetSpec:
        for d in self.datasets:
            if d.name == name:
                return d
        raise KeyError(name)

    def run(self, run_id: str) -> RunRecord:
        for r in self.runs:
            if r.id == run_id:
                return r
        raise KeyError(run_id)

    def unique_dataset_name(self, base: str) -> str:
        names = {d.name for d in self.datasets}
        if base not in names:
            return base
        i = 2
        while f"{base} ({i})" in names:
            i += 1
        return f"{base} ({i})"

    def upsert_dataset(self, spec: DatasetSpec) -> None:
        for i, d in enumerate(self.datasets):
            if d.name == spec.name:
                self.datasets[i] = spec
                return
        self.datasets.append(spec)

    # -- data ------------------------------------------------------------------

    def add_dataset(self, spec: DatasetSpec, frame: pd.DataFrame) -> DatasetSpec:
        """Store *frame* in the database (a site with rain gauge and flow meter) and register *spec*."""
        if not spec.stored:
            source = spec.kind.upper() + (f": {Path(spec.path).name}" if spec.path else "")
            ids = self.store.import_frame(spec.name, frame, source_system=source, site_iri=spec.site_iri)
            spec.site_iri, spec.rain_stream, spec.flow_stream = ids["site"], ids["rain"], ids["flow"]
            spec.temperature_stream = ids.get("temperature")
        self.upsert_dataset(spec)
        return spec

    # -- input series of a dataset (which rain gauge, which temperature) ----------------------------

    def dataset_inputs(self, name: str) -> dict[str, dict | None]:
        """What dataset *name* reads: ``{"rain": entry, "flow": entry, "temperature": entry | None}`` with the
        entries of :meth:`ProjectStore.series_catalog` (``None`` for a series that is not set or is gone)."""
        spec = self.dataset(name)
        catalog = {e["iri"]: e for e in self.store.series_catalog()}
        return {"rain": catalog.get(spec.rain_stream or ""), "flow": catalog.get(spec.flow_stream or ""),
                "temperature": catalog.get(spec.temperature_stream or "")}

    def inputs_text(self, name: str) -> str:
        """One line naming the dataset's rain and temperature series and their sites."""
        try:
            inputs = self.dataset_inputs(name)
            site = self.dataset(name).site_iri
        except KeyError:
            return ""

        def one(entry: dict | None, none: str) -> str:
            if entry is None:
                return none
            elsewhere = f" @ {entry['site_label']}" if entry["site_iri"] != site and entry["site_label"] else ""
            return f"{entry['label']}{elsewhere}"

        return f"rain: {one(inputs['rain'], 'not stored')}; temperature: {one(inputs['temperature'], 'none')}"

    def set_dataset_inputs(self, name: str, *, rain_stream: str | None = None,
                           temperature_stream: str | None = "") -> None:
        """Change the rain gauge and/or temperature series of dataset *name*.

        :param rain_stream: Datastream to read rain from (``None``: unchanged). It may belong to another site.
        :param temperature_stream: Datastream to read temperature from, ``None`` for no temperature, or
            ``""`` (default) to leave it unchanged.
        :raises ValueError: If the series is not of the right kind, or rain and flow do not overlap in time.
        """
        spec = self.dataset(name)
        if not spec.stored:
            raise ValueError(f"{name} is not stored in the project; import it first")
        props = {e["iri"]: e for e in self.store.series_catalog()}
        rain = spec.rain_stream if rain_stream is None else rain_stream
        temp = spec.temperature_stream if temperature_stream == "" else temperature_stream
        for stream, prop, what in ((rain, PROP_RAIN, "rain"), (temp, PROP_TEMPERATURE, "temperature")):
            if stream is not None and (stream not in props or props[stream]["observed_property"] != prop):
                raise ValueError(f"{stream!r} is not a {what} series of this project")
        frame = self.store.frame(rain, spec.flow_stream, temp)  # type: ignore[arg-type]
        if len(frame) < 3:
            raise ValueError(f"{props[rain]['label']} and the flow record of {name} do not overlap in time")
        spec.rain_stream, spec.temperature_stream = rain, temp
        # USES_GAGE: the dataset's site takes rain or temperature from a sensor's series at another site.
        if spec.site_iri:
            self.store.remove_edges(spec.site_iri, "USES_GAGE")
            for other in self.datasets:
                if other.site_iri != spec.site_iri:
                    continue
                for stream in (other.rain_stream, other.temperature_stream):
                    gauge_site = props.get(stream or "", {}).get("site_iri")
                    if gauge_site and gauge_site != spec.site_iri:
                        self.store.add_edge(spec.site_iri, gauge_site, "USES_GAGE", {"datastream": stream})

    def frame(self, name: str) -> pd.DataFrame:
        """Standard frame of dataset *name*, from the database (or, if never imported, from its source file)."""
        spec = self.dataset(name)
        if spec.stored:
            return self.store.frame(spec.rain_stream, spec.flow_stream, spec.temperature_stream)  # type: ignore[arg-type]
        return load_dataset(spec)

    # -- persistence ------------------------------------------------------------

    def save(self, path: str | Path | None = None) -> Path:
        """Write the project to *path* (default: where it was opened from); returns the file path."""
        if path is not None:
            path = Path(path)
            self.path = path if path.suffix.lower() == SUFFIX else path.with_suffix(SUFFIX)
        if self.path is None:
            raise ValueError("project has no file; pass a path to save()")
        base = self.path.parent
        st = self.store
        st.replace_rows("site_dataset", [
            (d.name, d.site_iri, d.rain_stream, d.flow_stream, d.temperature_stream,
             json.dumps(d.to_dict(base))) for d in self.datasets])
        st.replace_rows("model_spec", [(m.label or f"model {i + 1}", json.dumps(m.to_dict()))
                                       for i, m in enumerate(self.models)])
        st.replace_rows("run_array", [])
        st.replace_rows("run", [(r.id, i, json.dumps(r.meta_dict(), default=str)) for i, r in enumerate(self.runs)])
        st.replace_rows("run_array", [(r.id, r.arrays_blob()) for r in self.runs if r.has_results or r.history])
        st.set_setting("name", self.name)
        st.set_setting("format", FORMAT_VERSION)
        st.set_setting("uh_schema", UH_SCHEMA)
        st.set_setting("objectives", [o.to_dict() for o in self.objectives])
        st.set_setting("solver", self.solver.to_dict())
        st.set_setting("ui_state", self.ui_state)
        st.save_to(self.path)
        self.imported_from = None
        return self.path

    @classmethod
    def load(cls, path: str | Path) -> Project:
        """Open a ``.shproj`` file, or import a legacy project folder (or its ``project.json``)."""
        path = Path(path)
        if path.is_dir() or path.name == LEGACY_FILE:
            return cls._import_legacy(path if path.is_dir() else path.parent)
        store = ProjectStore.open(path)
        base = path.parent
        datasets = [DatasetSpec.from_dict(json.loads(r["spec"]), base) for r in store.rows("site_dataset")]
        runs = []
        arrays = {r["run_id"]: r["data"] for r in store.rows("run_array")}
        for r in store.rows("run", order="position"):
            runs.append(RunRecord.from_meta(json.loads(r["meta"]), arrays.get(r["id"])))
        project = cls(
            name=store.setting("name", path.stem), path=path, datasets=datasets,
            models=[ModelSpec.from_dict(json.loads(r["spec"])) for r in store.rows("model_spec")],
            objectives=[ObjectiveSpec.from_dict(x) for x in store.setting("objectives", [])] or list(DEFAULT_OBJECTIVES),
            solver=SolverSpec.from_dict(store.setting("solver")) if store.setting("solver") else SOLVERS.default(),
            runs=runs, ui_state=store.setting("ui_state", {}), store=store,
        )
        if int(store.setting("uh_schema", 1)) < UH_SCHEMA:
            project._migrate_uh()
        project._use_installed_solver()
        return project

    def _use_installed_solver(self) -> None:
        """Switch the project's solver to one installed here (e.g. a project from a pip installation opened with
        the Windows installer, which has pymoo's NSGA-II instead of Platypus). Runs keep their record."""
        self.solver, note = SOLVERS.usable(self.solver)
        if note:
            self.import_warnings.append(f"Optimizer: {note}.")

    def _migrate_uh(self) -> None:
        """Convert step-based unit hydrograph parameters (projects saved before the hours-based library)."""
        from .migration import migrate_project

        self.import_warnings += migrate_project(self)
        self.migrated = True

    @classmethod
    def _import_legacy(cls, folder: Path) -> Project:
        d = json.loads((folder / LEGACY_FILE).read_text(encoding="utf-8"))
        if int(d.get("format", 1)) > FORMAT_VERSION:
            raise StoreError(f"{folder} was written by a newer sparsehydro-viewer (format {d['format']})")
        project = cls(
            name=d.get("name", folder.name),
            models=[ModelSpec.from_dict(x) for x in d.get("models", [])],
            objectives=[ObjectiveSpec.from_dict(x) for x in d.get("objectives", [])] or list(DEFAULT_OBJECTIVES),
            solver=SolverSpec.from_dict(d["solver"]) if d.get("solver") else SOLVERS.default(),
            runs=[RunRecord.from_meta(x, folder / "runs" / f"{x['id']}.npz") for x in d.get("runs", [])],
            ui_state=d.get("ui_state", {}), imported_from=folder,
        )
        for x in d.get("datasets", []):
            spec = DatasetSpec.from_dict(x, folder)
            try:
                project.add_dataset(spec, load_dataset(spec))
            except Exception as exc:  # keep the spec; the series can be re-imported later
                project.import_warnings.append(f"{spec.name}: {exc}")
                project.upsert_dataset(spec)
        project._migrate_uh()  # folder projects all predate hours-based unit hydrographs
        project._use_installed_solver()
        return project

    @staticmethod
    def is_project_path(path: str | Path) -> bool:
        """``True`` for a ``.shproj`` file or a legacy project folder / ``project.json``."""
        p = Path(path)
        if p.is_file() and p.suffix.lower() == SUFFIX:
            return True
        return (p / LEGACY_FILE).exists() if p.is_dir() else p.name == LEGACY_FILE and p.exists()


__all__ = ["FORMAT_VERSION", "LEGACY_FILE", "SUFFIX", "Project"]
