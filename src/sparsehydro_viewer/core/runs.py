"""Calibration run records: what was run, and what came out.

A :class:`RunRecord` holds the full configuration (so a run can be repeated or
re-simulated) and the Pareto set in minimisation form, mirroring
:class:`sparsehydro.calibration.CalibrationResult`.  Arrays are stored beside
the project file in ``runs/<id>.npz``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np

from .catalog import ModelSpec
from .objectives import ObjectiveSpec
from .solvers import SolverSpec

RunStatus = Literal["queued", "running", "finished", "failed", "cancelled", "manual"]


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class RunRecord:
    """One calibration run (or a set of manually pinned candidates).

    :ivar pareto_X: ``(m, len(param_names))`` solutions (calibrated parameters only).
    :ivar pareto_F: ``(m, len(objective_names))`` objectives, minimisation form.
    :ivar history: Per-report ``(generation, n_evals, F)`` snapshots of the front.
    :ivar fixed_values: Values of non-calibrated parameters during the run.
    :ivar n_params_total: Total scalar + vector parameters of the model.
    """

    id: str
    label: str
    dataset: str
    model: ModelSpec
    objectives: list[ObjectiveSpec]
    solver: SolverSpec | None
    status: RunStatus = "queued"
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    elapsed_s: float = 0.0
    message: str = ""
    param_names: list[str] = field(default_factory=list)
    objective_names: list[str] = field(default_factory=list)
    minimize_flags: list[bool] = field(default_factory=list)
    fixed_values: dict[str, float] = field(default_factory=dict)
    n_params_total: int = 0
    pareto_X: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))
    pareto_F: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))
    history: list[tuple[int, int, np.ndarray]] = field(default_factory=list)

    # -- derived ------------------------------------------------------------

    @property
    def n_solutions(self) -> int:
        return int(self.pareto_X.shape[0]) if self.pareto_X.ndim == 2 else 0

    @property
    def n_params_calibrated(self) -> int:
        return len(self.param_names)

    @property
    def has_results(self) -> bool:
        return self.n_solutions > 0

    def display_F(self) -> np.ndarray:
        """Objectives in natural form (maximised objectives un-negated)."""
        if not self.has_results:
            return np.empty((0, len(self.objective_names)))
        flags = np.asarray(self.minimize_flags, dtype=bool)
        return np.where(flags, self.pareto_F, -self.pareto_F)

    def solution_values(self, index: int) -> dict[str, float]:
        """All scalar parameter values of solution *index* (fixed ones included)."""
        out = dict(self.fixed_values)
        out.update(dict(zip(self.param_names, map(float, self.pareto_X[index]))))
        return out

    def knee_index(self) -> int:
        """Solution closest to the ideal point after min-max normalisation."""
        if not self.has_results:
            raise ValueError("run has no solutions")
        F = self.pareto_F
        if F.shape[0] == 1:
            return 0
        lo, hi = F.min(axis=0), F.max(axis=0)
        span = np.where(hi > lo, hi - lo, 1.0)
        return int(np.argmin(np.linalg.norm((F - lo) / span, axis=1)))

    def best_index(self, objective: str) -> int:
        j = self.objective_names.index(objective)
        return int(np.argmin(self.pareto_F[:, j]))

    # -- serialisation ------------------------------------------------------

    def meta_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "dataset": self.dataset, "model": self.model.to_dict(),
            "objectives": [o.to_dict() for o in self.objectives],
            "solver": self.solver.to_dict() if self.solver else None,
            "status": self.status, "created": self.created, "elapsed_s": self.elapsed_s, "message": self.message,
            "param_names": self.param_names, "objective_names": self.objective_names,
            "minimize_flags": self.minimize_flags, "fixed_values": self.fixed_values,
            "n_params_total": self.n_params_total,
        }

    def save_arrays(self, path: Path) -> None:
        gens = np.array([h[0] for h in self.history], dtype=int)
        evals = np.array([h[1] for h in self.history], dtype=int)
        sizes = np.array([len(h[2]) for h in self.history], dtype=int)
        width = len(self.objective_names)
        stacked = np.concatenate([np.asarray(h[2], float).reshape(-1, width) for h in self.history]) \
            if self.history else np.empty((0, width))
        np.savez_compressed(path, pareto_X=self.pareto_X, pareto_F=self.pareto_F,
                            hist_gen=gens, hist_evals=evals, hist_sizes=sizes, hist_F=stacked)

    @classmethod
    def from_meta(cls, d: dict[str, Any], arrays: Path | None = None) -> RunRecord:
        rec = cls(
            id=d["id"], label=d.get("label", d["id"]), dataset=d.get("dataset", ""),
            model=ModelSpec.from_dict(d["model"]),
            objectives=[ObjectiveSpec.from_dict(o) for o in d.get("objectives", [])],
            solver=SolverSpec.from_dict(d["solver"]) if d.get("solver") else None,
            status=d.get("status", "finished"), created=d.get("created", ""), elapsed_s=d.get("elapsed_s", 0.0),
            message=d.get("message", ""), param_names=list(d.get("param_names", [])),
            objective_names=list(d.get("objective_names", [])), minimize_flags=list(d.get("minimize_flags", [])),
            fixed_values={k: float(v) for k, v in d.get("fixed_values", {}).items()},
            n_params_total=int(d.get("n_params_total", 0)),
        )
        if arrays is not None and arrays.exists():
            with np.load(arrays) as z:
                rec.pareto_X, rec.pareto_F = z["pareto_X"], z["pareto_F"]
                offs = np.concatenate([[0], np.cumsum(z["hist_sizes"])])
                rec.history = [(int(g), int(e), z["hist_F"][offs[i]:offs[i + 1]])
                               for i, (g, e) in enumerate(zip(z["hist_gen"], z["hist_evals"]))]
        if rec.status in ("queued", "running"):
            rec.status = "cancelled"  # the app closed while it was running
        return rec


__all__ = ["RunRecord", "RunStatus", "new_id"]
