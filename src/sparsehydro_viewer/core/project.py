"""Project persistence.

A project is a folder::

    my-site/
      project.json         datasets, model specs, run metadata, UI state
      runs/<run id>.npz    Pareto sets and convergence history

Dataset paths inside the project folder are stored relative to it, so a
project can be moved or shared together with its data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .catalog import ModelSpec
from .data import DatasetSpec
from .objectives import DEFAULT_OBJECTIVES, ObjectiveSpec
from .runs import RunRecord
from .solvers import SolverSpec

PROJECT_FILE = "project.json"
FORMAT_VERSION = 1


@dataclass
class Project:
    """Everything the user has set up and run."""

    name: str = "Untitled"
    folder: Path | None = None
    datasets: list[DatasetSpec] = field(default_factory=list)
    models: list[ModelSpec] = field(default_factory=list)
    objectives: list[ObjectiveSpec] = field(default_factory=lambda: list(DEFAULT_OBJECTIVES))
    solver: SolverSpec = field(default_factory=lambda: SolverSpec("nsga2"))
    runs: list[RunRecord] = field(default_factory=list)
    ui_state: dict[str, Any] = field(default_factory=dict)

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

    # -- persistence ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        base = self.folder
        return {
            "format": FORMAT_VERSION,
            "name": self.name,
            "datasets": [d.to_dict(base) for d in self.datasets],
            "models": [m.to_dict() for m in self.models],
            "objectives": [o.to_dict() for o in self.objectives],
            "solver": self.solver.to_dict(),
            "runs": [r.meta_dict() for r in self.runs],
            "ui_state": self.ui_state,
        }

    def save(self, folder: str | Path | None = None) -> Path:
        """Write ``project.json`` and run arrays; returns the project folder."""
        if folder is not None:
            self.folder = Path(folder)
        if self.folder is None:
            raise ValueError("project has no folder; pass one to save()")
        self.folder.mkdir(parents=True, exist_ok=True)
        runs_dir = self.folder / "runs"
        runs_dir.mkdir(exist_ok=True)
        for r in self.runs:
            if r.has_results or r.history:
                r.save_arrays(runs_dir / f"{r.id}.npz")
        keep = {f"{r.id}.npz" for r in self.runs}
        for f in runs_dir.glob("*.npz"):
            if f.name not in keep:
                f.unlink()
        tmp = self.folder / (PROJECT_FILE + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        tmp.replace(self.folder / PROJECT_FILE)
        return self.folder

    @classmethod
    def load(cls, folder: str | Path) -> Project:
        folder = Path(folder)
        if folder.is_file():
            folder = folder.parent
        d = json.loads((folder / PROJECT_FILE).read_text(encoding="utf-8"))
        if int(d.get("format", 1)) > FORMAT_VERSION:
            raise ValueError(f"{folder} was written by a newer sparsehydro-viewer (format {d['format']})")
        return cls(
            name=d.get("name", folder.name),
            folder=folder,
            datasets=[DatasetSpec.from_dict(x, folder) for x in d.get("datasets", [])],
            models=[ModelSpec.from_dict(x) for x in d.get("models", [])],
            objectives=[ObjectiveSpec.from_dict(x) for x in d.get("objectives", [])] or list(DEFAULT_OBJECTIVES),
            solver=SolverSpec.from_dict(d["solver"]) if d.get("solver") else SolverSpec("nsga2"),
            runs=[RunRecord.from_meta(x, folder / "runs" / f"{x['id']}.npz") for x in d.get("runs", [])],
            ui_state=d.get("ui_state", {}),
        )

    @staticmethod
    def is_project_folder(folder: str | Path) -> bool:
        return (Path(folder) / PROJECT_FILE).exists()


__all__ = ["FORMAT_VERSION", "PROJECT_FILE", "Project"]
