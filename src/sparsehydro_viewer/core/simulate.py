"""Simulate selected solutions of a calibration run for display (Explore and Compare).

One call returns everything a time-series chart needs for a selection: a line
per selected solution, the min-max band over a set of solutions (the
selection, a brush, or the whole Pareto set), and for the primary solution its
unit hydrograph curves, validation objectives and, on request, its individual
hydrographs. Simulated series are cached, so clicking back to a solution or
showing it on another page costs nothing.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from .data import Period, epoch_seconds
from .evaluation import Evaluator
from .runs import RunRecord
from .selection import SolutionRef
from .trace import flow_parts
from .uh import KernelCurve, kernel_curves

#: Lines drawn at most; beyond that a selection is shown by its band and its primary line.
MAX_LINES = 12
#: Solutions simulated at most for a band (evenly thinned beyond: a band over hundreds of solutions changes little).
MAX_BAND = 300


def _period_key(period: Period) -> tuple:
    return (period.start, period.end)


class SimulationCache:
    """Simulated series by ``(run, generation, index, period)``, least recently used first out. Thread-safe:
    simulations run on the job pool."""

    def __init__(self, capacity: int = 400) -> None:
        self.capacity = capacity
        self._items: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0

    def get(self, key: tuple) -> np.ndarray | None:
        with self._lock:
            y = self._items.get(key)
            if y is not None:
                self._items.move_to_end(key)
                self.hits += 1
            return y

    def put(self, key: tuple, y: np.ndarray) -> None:
        with self._lock:
            self._items[key] = y
            self._items.move_to_end(key)
            while len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def drop_run(self, run_id: str) -> None:
        with self._lock:
            for key in [k for k in self._items if k[0] == run_id]:
                del self._items[key]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class SolutionSeries:
    """What a chart draws for a selection of one run on one period."""

    run_id: str
    period: Period
    t: np.ndarray
    rain: np.ndarray
    observed: np.ndarray
    #: Simulated flow of each drawn solution (the primary first), at most :data:`MAX_LINES`.
    lines: dict[SolutionRef, np.ndarray] = field(default_factory=dict)
    primary: SolutionRef | None = None
    #: ``(lower, upper)`` envelope and what it covers (e.g. "Pareto range (24 solutions)").
    band: tuple[np.ndarray, np.ndarray] | None = None
    band_label: str = ""
    #: Number of selected solutions (may exceed the lines drawn).
    n_selected: int = 0
    curves: list[KernelCurve] = field(default_factory=list)
    validation: dict[str, float] | None = None
    #: Individual hydrographs ``(label, series)`` of the primary solution, when requested.
    parts: list[tuple[str, np.ndarray]] | None = None

    @property
    def predicted(self) -> np.ndarray | None:
        """The primary solution's simulated flow."""
        return self.lines.get(self.primary) if self.primary is not None else None


def solution_vector(run: RunRecord, ref: SolutionRef) -> np.ndarray:
    """Parameter vector (in ``run.param_names`` order) of a solution of the final front or of an earlier report."""
    if ref.generation is None:
        return np.asarray(run.pareto_X[ref.index], float)
    X = run.history_X(ref.generation)
    if X is None:
        raise ValueError(f"{run.label}: report {ref.generation + 1} has no stored parameter sets")
    return np.asarray(X[ref.index], float)


def simulate_solutions(run: RunRecord, frame, refs: list[SolutionRef], period: Period, *,
                       primary: SolutionRef | None = None, band_rows: list[int] | None = None,
                       band_label: str = "", validation: Period | None = None, components: bool = False,
                       cache: SimulationCache | None = None) -> SolutionSeries:
    """Simulate *refs* of *run* on *period*.

    :param refs: Selected solutions; the first :data:`MAX_LINES` (the primary always among them) get a line.
    :param primary: Solution the detail outputs (unit hydrographs, validation, components) describe;
        default: the first of *refs*.
    :param band_rows: Final-front indices whose min-max envelope is returned (thinned to :data:`MAX_BAND`).
    :param validation: Period on which the primary solution's objectives are also evaluated.
    :param components: Also return the primary solution's individual hydrographs.
    """
    ev = Evaluator(run.model, frame, run.objectives, period)
    ev.evaluate(run.fixed_values)
    pkey = _period_key(period)
    refs = [r for r in dict.fromkeys(refs) if r.run_id == run.id]
    primary = primary if primary in refs else (refs[0] if refs else None)
    drawn = ([primary] if primary is not None else []) + [r for r in refs if r != primary]
    drawn = drawn[:MAX_LINES]
    out = SolutionSeries(run.id, period, epoch_seconds(ev.datetime), np.asarray(ev.rain, float),
                         np.asarray(ev.observed, float), primary=primary, n_selected=len(refs),
                         band_label=band_label)

    def key(ref: SolutionRef) -> tuple:
        return (run.id, ref.generation, ref.index, pkey)

    missing = [r for r in drawn if cache is None or cache.get(key(r)) is None]
    if missing:
        sims = ev.simulate_many(run.param_names, np.vstack([solution_vector(run, r) for r in missing]))
        for r, y in zip(missing, sims):
            y = np.array(y, dtype=float)
            if cache is not None:
                cache.put(key(r), y)
            else:
                out.lines[r] = y
    for r in drawn:
        if r not in out.lines:
            out.lines[r] = cache.get(key(r))  # type: ignore[union-attr, assignment]
    out.lines = {r: out.lines[r] for r in drawn}  # primary first

    rows = sorted(set(int(i) for i in (band_rows or []) if 0 <= int(i) < run.n_solutions))
    if len(rows) > 1:
        if len(rows) > MAX_BAND:
            rows = [rows[i] for i in np.linspace(0, len(rows) - 1, MAX_BAND).round().astype(int)]
        band_key = (run.id, "band", hash(tuple(rows)), pkey)
        cached = cache.get(band_key) if cache is not None else None
        if cached is None:
            sims = ev.simulate_many(run.param_names, run.pareto_X[rows])
            cached = np.vstack([sims.min(axis=0), sims.max(axis=0)])
            if cache is not None:
                cache.put(band_key, cached)
        out.band = (cached[0], cached[1])

    if primary is not None:
        # Last, so the evaluator is left at the primary solution for the detail outputs below.
        res = ev.evaluate_vector(run.param_names, solution_vector(run, primary))
        out.curves = kernel_curves(ev.built, ev.dt_hours)
        if components:
            trace = ev.trace()
            trace.setdefault(ev.predicted_key, res.predicted)
            fields = ev.trace_fields()
            labels = {f.name: f.label for f in fields}
            out.parts = [(labels[n], y) for n, y in flow_parts(fields, trace, ev.predicted_key)]
        if validation is not None and not validation.is_open:
            try:
                vev = Evaluator(run.model, frame, run.objectives, validation)
                vev.evaluate(run.fixed_values)
                out.validation = vev.evaluate_vector(run.param_names, solution_vector(run, primary)).objectives
            except ValueError:
                out.validation = None
    return out


__all__ = ["MAX_BAND", "MAX_LINES", "SimulationCache", "SolutionSeries", "simulate_solutions", "solution_vector"]
