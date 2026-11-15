"""Fast repeated evaluation of one model on one period.

:class:`Evaluator` wraps a :class:`sparsehydro.calibration.CalibrationProblem`
so that objective values are computed by exactly the code the optimisers use;
it adds the simulated series and the constraint values, which the problem does
not return.  It is used by the parameter sliders (live feedback), by Explore
(re-simulating Pareto solutions) and by Compare (validation scores).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .catalog import CATALOG, ModelSpec, flat_names
from .data import Period, dt_hours, slice_period
from .objectives import OBJECTIVES, ObjectiveSpec


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
        from sparsehydro.calibration import CalibrationProblem

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
        self.dt_hours = dt_hours(frame)
        self.built = CATALOG.build(spec, strict=False)
        self.model = self.built.model
        self.predicted_key = self.built.output_key
        self.model.validate()
        self.problem = CalibrationProblem(
            self.model,
            CATALOG.prepare_frame(frame),
            objectives=[OBJECTIVES.build(o) for o in self.objective_specs],
            column_map={"observed": "stormflow", "predicted": self.predicted_key},
        )
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
        disp = self.to_display(F)
        return Evaluation(
            values=self.current_values(),
            predicted=predicted.copy(),
            objectives=dict(zip(self.objective_names, map(float, disp))),
            F=F.copy(),
            constraints=dict(zip(names, map(float, g))),
        )

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
