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
from .objectives import DEFAULT_OBJECTIVES, ObjectiveSpec
from .runs import RunRecord
from .solvers import SolverSpec
from .store import ProjectStore, StoreError

SUFFIX = ".shproj"
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
    solver: SolverSpec = field(default_factory=lambda: SolverSpec("nsga2"))
    runs: list[RunRecord] = field(default_factory=list)
    ui_state: dict[str, Any] = field(default_factory=dict)
    store: ProjectStore = field(default_factory=ProjectStore.memory, repr=False, compare=False)
    #: Set when the project was imported from a legacy folder (it has no ``.shproj`` yet).
    imported_from: Path | None = None
    #: Datasets whose source files could not be read during a legacy import.
    import_warnings: list[str] = field(default_factory=list)

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
        return cls(
            name=store.setting("name", path.stem), path=path, datasets=datasets,
            models=[ModelSpec.from_dict(json.loads(r["spec"])) for r in store.rows("model_spec")],
            objectives=[ObjectiveSpec.from_dict(x) for x in store.setting("objectives", [])] or list(DEFAULT_OBJECTIVES),
            solver=SolverSpec.from_dict(store.setting("solver")) if store.setting("solver") else SolverSpec("nsga2"),
            runs=runs, ui_state=store.setting("ui_state", {}), store=store,
        )

    @classmethod
    def _import_legacy(cls, folder: Path) -> Project:
        d = json.loads((folder / LEGACY_FILE).read_text(encoding="utf-8"))
        if int(d.get("format", 1)) > FORMAT_VERSION:
            raise StoreError(f"{folder} was written by a newer sparsehydro-viewer (format {d['format']})")
        project = cls(
            name=d.get("name", folder.name),
            models=[ModelSpec.from_dict(x) for x in d.get("models", [])],
            objectives=[ObjectiveSpec.from_dict(x) for x in d.get("objectives", [])] or list(DEFAULT_OBJECTIVES),
            solver=SolverSpec.from_dict(d["solver"]) if d.get("solver") else SolverSpec("nsga2"),
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
        return project

    @staticmethod
    def is_project_path(path: str | Path) -> bool:
        """``True`` for a ``.shproj`` file or a legacy project folder / ``project.json``."""
        p = Path(path)
        if p.is_file() and p.suffix.lower() == SUFFIX:
            return True
        return (p / LEGACY_FILE).exists() if p.is_dir() else p.name == LEGACY_FILE and p.exists()


__all__ = ["FORMAT_VERSION", "LEGACY_FILE", "SUFFIX", "Project"]
