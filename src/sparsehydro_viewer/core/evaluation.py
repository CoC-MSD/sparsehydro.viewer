"""Fast repeated evaluation of one model on one period.

:class:`Evaluator` wraps a :class:`sparsehydro.calibration.CalibrationProblem`
so that objective values are computed by exactly the code the optimisers use;
it adds the simulated series and the constraint values, which the problem does
not return.  It is used by the parameter sliders (live feedback), by Explore
(re-simulating Pareto solutions) and by Compare (validation scores).
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .catalog import CATALOG, ModelSpec, flat_names
from .data import Period, dt_hours, slice_period
from .objectives import OBJECTIVES, ObjectiveSpec

_SAFE_PROBLEM: type | None = None


def nan_safe_problem_class() -> type:
    """``CalibrationProblem`` whose undefined objective values count as the worst value.

    Objectives such as KGE and Lin's CCC are undefined (NaN) when a trial solution predicts a constant
    flow, e.g. all zeros. sparsehydro 1.0.0a1 passes the NaN to the optimiser, which then cannot rank the
    solution; here it receives the same failure value the library uses when an objective raises. This
    belongs in the library and is dropped when the viewer moves to the refactored sparsehydro.
    """
    global _SAFE_PROBLEM
    if _SAFE_PROBLEM is None:
        from sparsehydro.calibration import CalibrationProblem

        class NanSafeCalibrationProblem(CalibrationProblem):
            def _score(self, i, obj, predicted, clean):  # type: ignore[override]
                val = super()._score(i, obj, predicted, clean)
                return val if np.isfinite(val) else 1e12

            def make_copy(self):  # the library's copy builds a plain CalibrationProblem
                cp = super().make_copy()
                cp.__class__ = type(self)
                return cp

        _SAFE_PROBLEM = NanSafeCalibrationProblem
    return _SAFE_PROBLEM


@dataclass(frozen=True)
class Evaluation:
    """Result of one evaluation.

    :ivar values: Parameter values used (all scalars, by name).
    :ivar predicted: Simulated flow aligned with :attr:`Evaluator.datetime`.
    :ivar objectives: Objective values in natural (display) form.
    :ivar F: Objective values in minimisation form, as optimisers see them.
    :ivar constraints: Inequality constraints ``g`` (feasible when ``g <= 0``).
    """

    values: dict[str, float]
    predicted: np.ndarray
    objectives: dict[str, float]
    F: np.ndarray
    constraints: dict[str, float]

    @property
    def feasible(self) -> bool:
        return all(g <= 0.0 for g in self.constraints.values())


class Evaluator:
    """Prepared model + objectives for one dataset period.

    :param spec: Model specification.
    :param data: Standardised dataset frame.
    :param objectives: Objectives to evaluate.
    :param period: Period to evaluate over (open = whole record).
    """

    def __init__(self, spec: ModelSpec, data: pd.DataFrame, objectives: Sequence[ObjectiveSpec],
                 period: Period | None = None) -> None:
        if not objectives:
            raise ValueError("at least one objective is required")
        self.spec = spec
        self.objective_specs = list(objectives)
        frame = slice_period(data, period or Period())
        if len(frame) < 3:
            raise ValueError("the selected period contains fewer than 3 time steps")
        self.datetime = frame["datetime"].to_numpy()
        self.rain = frame["rain"].to_numpy(dtype=float)
        self.observed = frame["stormflow"].to_numpy(dtype=float)
        #: Other forcing columns of the dataset (e.g. ``temperature_c``), for plotting next to the flow.
        self.inputs = {c: frame[c].to_numpy(dtype=float) for c in frame.columns
                       if c not in ("datetime", "rain", "stormflow") and pd.api.types.is_numeric_dtype(frame[c])}
        self.dt_hours = dt_hours(frame)
        self.built = CATALOG.build(spec, strict=False)
        self.model = self.built.model
        self.predicted_key = self.built.output_key
        self.model.validate()
        with warnings.catch_warnings():
            # sparsehydro warns about too-slow unit hydrograph bounds on every problem it builds; the viewer
            # reports them once, by process and slider (see slow_responses), instead of on the console.
            warnings.filterwarnings("ignore", message=r".*response needs .* h to deliver half its volume")
            self.problem = nan_safe_problem_class()(
                self.model,
                CATALOG.prepare_frame(frame),
                objectives=[OBJECTIVES.build(o) for o in self.objective_specs],
                column_map={"observed": "stormflow", "predicted": self.predicted_key},
            )
        from .diagnostics import slow_responses

        self.slow_responses = slow_responses(self.built, len(frame) * self.dt_hours)
        self._minimize = np.array(self.problem.minimize_flags, dtype=bool)
        self._names = flat_names(self.model)

    # ------------------------------------------------------------------

    @property
    def parameter_names(self) -> list[str]:
        """Every flat parameter (scalars and vector elements ``name[i]``)."""
        return list(self._names)

    @property
    def calibrated_names(self) -> list[str]:
        return self.problem.param_names

    @property
    def objective_names(self) -> list[str]:
        return self.problem.objective_names

    @property
    def minimize_flags(self) -> list[bool]:
        return list(self.problem.minimize_flags)

    def current_values(self) -> dict[str, float]:
        return {n: float(self.model.read_flat_parameter(n)) for n in self.parameter_names}

    def to_display(self, F: np.ndarray) -> np.ndarray:
        """Convert minimisation-form objectives to natural form (works on 1-D or 2-D)."""
        F = np.asarray(F, dtype=float)
        return np.where(self._minimize, F, -F)

    # ------------------------------------------------------------------

    def evaluate(self, values: dict[str, float] | None = None) -> Evaluation:
        """Apply *values* (any subset of scalar parameters) and evaluate.

        Fixed parameters are applied too, so a slider on a non-calibrated
        parameter still changes the simulation.

        :param values: Parameter values by name.
        :returns: Simulated series, objectives and constraints.
        """
        for name, val in (values or {}).items():
            self.model.apply_flat_parameter(name, float(val))
        x = np.array([self.model.read_flat_parameter(n) for n in self.problem.param_names], dtype=float)
        F = self.problem.evaluate(x, penalty_weight=0.0)
        predicted = np.asarray(self.model.predict_arrays()[self.predicted_key], dtype=float)
        names = list(self.model.inequality_constraint_names)
        g = list(self.model.inequality_constraints()) if names else []
        # Undefined objectives reach the optimiser as the failure value; show them as undefined.
        disp = np.where(np.abs(F) >= 1e12, np.nan, self.to_display(F))
        return Evaluation(
            values=self.current_values(),
            predicted=predicted.copy(),
            objectives=dict(zip(self.objective_names, map(float, disp))),
            F=F.copy(),
            constraints=dict(zip(names, map(float, g))),
        )

    def trace(self) -> dict[str, np.ndarray]:
        """Outputs, components and internal states at the current parameter values (see :mod:`.trace`).

        Runs the model once more; call it only when a view shows the trace.
        """
        if not hasattr(self.model, "predict_trace"):
            return {}
        out = self.model.predict_trace()
        return {k: np.asarray(v) for k, v in out.items() if k != "datetime"}

    def trace_fields(self):
        from .trace import trace_fields

        return trace_fields(self.model)

    def evaluate_vector(self, param_names: Sequence[str], x: Iterable[float]) -> Evaluation:
        """Evaluate a solution vector from a calibration result."""
        return self.evaluate(dict(zip(param_names, map(float, x))))

    def simulate_many(self, param_names: Sequence[str], X: np.ndarray) -> np.ndarray:
        """Simulate each row of *X*; returns an array ``(n_rows, n_time)``.

        The model's current parameter values are restored afterwards.
        """
        saved = self.current_values()
        out = np.empty((len(X), len(self.datetime)), dtype=float)
        try:
            for i, row in enumerate(np.atleast_2d(X)):
                out[i] = self.evaluate_vector(param_names, row).predicted
        finally:
            self.evaluate(saved)
        return out


__all__ = ["Evaluation", "Evaluator"]
