"""Calibration run records: what was run, and what came out.

A :class:`RunRecord` holds the full configuration (so a run can be repeated or
re-simulated) and the Pareto set in minimisation form, mirroring
:class:`sparsehydro.calibration.CalibrationResult`.  Arrays are stored beside
the project file in ``runs/<id>.npz``.
"""

from __future__ import annotations

import io
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

#: Reports kept at most when a run is saved (first, last and evenly spaced ones), so project files stay bounded.
MAX_STORED_REPORTS = 200


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class RunRecord:
    """One calibration run (or a set of manually pinned candidates).

    :ivar pareto_X: ``(m, len(param_names))`` solutions (calibrated parameters only).
    :ivar pareto_F: ``(m, len(objective_names))`` objectives, minimisation form.
    :ivar history: Per-report ``(generation, n_evals, F)`` snapshots of the front.
    :ivar history_params: Parameter sets of each report's front (same order as *history*; ``None`` for a
        report without them: older projects, solvers that do not report them).
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
    history_params: list[np.ndarray | None] = field(default_factory=list)

    # -- history ------------------------------------------------------------

    def add_report(self, generation: int, n_evals: int, F: np.ndarray, X: np.ndarray | None = None) -> None:
        """Append a progress report: the current front's objectives and, when given, its parameter sets."""
        F = np.atleast_2d(np.asarray(F, dtype=float))
        if X is not None:
            X = np.atleast_2d(np.asarray(X, dtype=float))
            if len(X) != len(F):
                X = None
        while len(self.history_params) < len(self.history):  # reports appended to history directly
            self.history_params.append(None)
        self.history.append((int(generation), int(n_evals), F))
        self.history_params.append(X)

    def history_X(self, report: int) -> np.ndarray | None:
        """Parameter sets of report *report* (position in :attr:`history`), or ``None`` when not stored."""
        return self.history_params[report] if 0 <= report < len(self.history_params) else None

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

    def solution_values(self, index: int, generation: int | None = None) -> dict[str, float]:
        """All scalar parameter values of solution *index* (fixed ones included): of the final front, or of
        the front of report *generation*."""
        if generation is None:
            x = self.pareto_X[index]
        else:
            X = self.history_X(generation)
            if X is None:
                raise ValueError(f"report {generation + 1} of {self.label} has no stored parameter sets")
            x = X[index]
        out = dict(self.fixed_values)
        out.update(dict(zip(self.param_names, map(float, x))))
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

    def stored_reports(self) -> list[int]:
        """Positions of the reports written to disk: all, or the first, last and evenly spaced ones beyond
        :data:`MAX_STORED_REPORTS`."""
        n = len(self.history)
        if n <= MAX_STORED_REPORTS:
            return list(range(n))
        return sorted(set(np.linspace(0, n - 1, MAX_STORED_REPORTS).round().astype(int).tolist()))

    def save_arrays(self, path: Path) -> None:
        keep = self.stored_reports()
        history = [self.history[i] for i in keep]
        params = [self.history_X(i) for i in keep]
        gens = np.array([h[0] for h in history], dtype=int)
        evals = np.array([h[1] for h in history], dtype=int)
        sizes = np.array([len(h[2]) for h in history], dtype=int)
        width = len(self.objective_names)
        stacked = np.concatenate([np.asarray(h[2], float).reshape(-1, width) for h in history]) \
            if history else np.empty((0, width))
        n_par = len(self.param_names)
        x_sizes = np.array([0 if x is None else len(x) for x in params], dtype=int)
        x_stacked = np.concatenate([np.asarray(x, float).reshape(-1, n_par) for x in params if x is not None]) \
            if x_sizes.sum() else np.empty((0, n_par))
        np.savez_compressed(path, pareto_X=self.pareto_X, pareto_F=self.pareto_F,
                            hist_gen=gens, hist_evals=evals, hist_sizes=sizes, hist_F=stacked,
                            hist_xsizes=x_sizes, hist_X=x_stacked)

    def arrays_blob(self) -> bytes:
        """Pareto set and history as one compressed blob (project database)."""
        buf = io.BytesIO()
        self.save_arrays(buf)  # type: ignore[arg-type]
        return buf.getvalue()

    @classmethod
    def from_meta(cls, d: dict[str, Any], arrays: Path | bytes | None = None) -> RunRecord:
        """Rebuild a run from its metadata and arrays (an ``.npz`` path or a blob from :meth:`arrays_blob`)."""
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
        source = io.BytesIO(arrays) if isinstance(arrays, bytes) else arrays
        if source is not None and (isinstance(source, io.BytesIO) or source.exists()):
            with np.load(source) as z:
                rec.pareto_X, rec.pareto_F = z["pareto_X"], z["pareto_F"]
                offs = np.concatenate([[0], np.cumsum(z["hist_sizes"])])
                rec.history = [(int(g), int(e), z["hist_F"][offs[i]:offs[i + 1]])
                               for i, (g, e) in enumerate(zip(z["hist_gen"], z["hist_evals"]))]
                if "hist_X" in z.files:  # projects saved before parameter sets were kept have none
                    xo = np.concatenate([[0], np.cumsum(z["hist_xsizes"])])
                    rec.history_params = [z["hist_X"][xo[i]:xo[i + 1]] if z["hist_xsizes"][i] else None
                                          for i in range(len(rec.history))]
                else:
                    rec.history_params = [None] * len(rec.history)
        if rec.status in ("queued", "running"):
            rec.status = "cancelled"  # the app closed while it was running
        return rec


__all__ = ["MAX_STORED_REPORTS", "RunRecord", "RunStatus", "new_id"]
