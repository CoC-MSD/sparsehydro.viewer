"""Calibration execution, independent of Qt.

:func:`run_calibration` rebuilds everything from a serialisable payload, so it
can run in a separate process (see
:mod:`sparsehydro_viewer.services.calibration`) as well as inline in tests.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .catalog import ModelSpec, parameter_counts
from .data import Period
from .evaluation import Evaluator
from .objectives import ObjectiveSpec
from .solvers import SOLVERS, SolverSpec

Emit = Callable[[str, dict[str, Any]], None]


class CalibrationCancelled(Exception):
    """Raised inside a solver callback to stop a run."""


@dataclass
class CalibrationPayload:
    """Everything a worker needs to run one calibration."""

    run_id: str
    model: dict[str, Any]
    objectives: list[dict[str, Any]]
    solver: dict[str, Any]
    data: pd.DataFrame
    period: dict[str, Any]


def run_calibration(payload: CalibrationPayload, emit: Emit, should_stop: Callable[[], bool] = lambda: False) -> dict[str, Any]:
    """Run one calibration and return the result as plain data.

    Progress messages are ``emit("progress", {...})`` with keys
    ``generation``, ``n_evals``, ``pareto_F`` (minimisation form) and
    ``elapsed_s``.

    :param payload: Run configuration and data.
    :param emit: Message sink.
    :param should_stop: Polled at every progress report; returning ``True``
        stops the run with :class:`CalibrationCancelled`.
    :returns: Keys ``param_names``, ``objective_names``, ``minimize_flags``,
        ``pareto_X``, ``pareto_F``, ``fixed_values``, ``n_params_total``,
        ``elapsed_s``.
    """
    t0 = time.perf_counter()
    spec = ModelSpec.from_dict(payload.model)
    objectives = [ObjectiveSpec.from_dict(o) for o in payload.objectives]
    solver_spec = SolverSpec.from_dict(payload.solver)
    emit("status", {"text": "Preparing model"})
    ev = Evaluator(spec, payload.data, objectives, Period.from_dict(payload.period))
    names = ev.calibrated_names
    if not names:
        raise ValueError("No parameters are marked for calibration.")
    fixed = {n: v for n, v in ev.current_values().items() if n not in names}
    total, _ = parameter_counts(ev.model)
    emit("started", {"param_names": names, "objective_names": ev.objective_names,
                     "minimize_flags": ev.minimize_flags, "fixed_values": fixed, "n_params_total": total})

    def callback(info: dict[str, Any]) -> None:
        if should_stop():
            raise CalibrationCancelled()
        emit("progress", {
            "generation": int(info.get("generation", 0)),
            "n_evals": int(info.get("n_evals", 0)),
            "pareto_F": np.asarray(info.get("pareto_F", np.empty((0, len(names)))), dtype=float),
            "elapsed_s": time.perf_counter() - t0,
        })

    entry = SOLVERS.get(solver_spec.name)
    solver = SOLVERS.build(solver_spec, callback if entry.supports_callback else None)
    emit("status", {"text": f"Running {entry.label}"})
    result = solver.solve(ev.problem)
    X = np.atleast_2d(np.asarray(result.pareto_X, dtype=float))
    F = np.atleast_2d(np.asarray(result.pareto_F, dtype=float))
    if list(result.param_names) != names:  # defensive: reorder to the problem's order
        idx = [list(result.param_names).index(n) for n in names]
        X = X[:, idx]
    if F.shape[1] != len(ev.objective_names):
        # Scalar solvers report only the optimised objective; re-evaluate all of them.
        F = np.array([ev.problem.evaluate(x, penalty_weight=0.0) for x in X])
    return {
        "param_names": names,
        "objective_names": ev.objective_names,
        "minimize_flags": ev.minimize_flags,
        "pareto_X": X,
        "pareto_F": F,
        "fixed_values": fixed,
        "n_params_total": total,
        "elapsed_s": time.perf_counter() - t0,
    }


def process_main(payload: CalibrationPayload, queue: Any, stop_event: Any) -> None:
    """Entry point of a calibration worker process.

    Posts ``(run_id, kind, data)`` tuples to *queue*; the last one is
    ``finished``, ``failed`` or ``cancelled``.
    """
    import logging
    import traceback

    logging.basicConfig(level=logging.WARNING)
    run_id = payload.run_id

    def emit(kind: str, data: dict[str, Any]) -> None:
        queue.put((run_id, kind, data))

    try:
        result = run_calibration(payload, emit, should_stop=stop_event.is_set)
    except CalibrationCancelled:
        emit("cancelled", {})
    except Exception as exc:  # reported to the UI, which owns error display
        emit("failed", {"message": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
    else:
        emit("finished", result)


__all__ = ["CalibrationCancelled", "CalibrationPayload", "process_main", "run_calibration"]
