"""Live model evaluation for the parameter sliders.

A dedicated worker thread owns the :class:`~sparsehydro_viewer.core.Evaluator`
instances (calibration and, when configured, validation periods).  Requests
are coalesced: while one evaluation runs, only the most recent pending request
is kept, so dragging a slider never builds up a backlog.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import pandas as pd
from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.catalog import ModelSpec
from ..core.data import Period
from ..core.evaluation import Evaluation, Evaluator
from ..core.objectives import ObjectiveSpec
from ..core.uh import KernelCurve, kernel_curves

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveResult:
    """What the views need after one slider move."""

    calibration: Evaluation
    validation: Evaluation | None
    datetime: Any
    observed: Any
    rain: Any
    kernels: list[KernelCurve]
    dt_hours: float
    generation: int
    #: Components and states for the calibration period (only while a view asks for them).
    trace: dict | None = None
    trace_fields: list | None = None
    output_key: str = ""
    #: Unit hydrographs whose bounds allow responses too slow for the calibration period.
    slow_responses: tuple = ()
    #: Other forcing series of the dataset over the calibration period (e.g. temperature).
    inputs: dict | None = None


@dataclass
class _Config:
    spec: ModelSpec
    data: pd.DataFrame
    objectives: list[ObjectiveSpec]
    calibration: Period
    validation: Period


class _Worker(QObject):
    ready = Signal(object)
    failed = Signal(str)
    configured = Signal(list, list)  # objective names, minimise flags

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._pending_values: dict[str, float] | None = None
        self._pending_config: _Config | None = None
        self._cal: Evaluator | None = None
        self._val: Evaluator | None = None
        self._generation = 0
        self._last_values: dict[str, float] = {}
        self.want_trace = False

    def post(self, values: dict[str, float] | None, config: _Config | None, *, rerun: bool = False) -> None:
        with self._lock:
            if config is not None:
                self._pending_config = config
                self._generation += 1
            if values is not None:
                self._pending_values = dict(values)
            elif rerun and self._pending_values is None:
                self._pending_values = dict(self._last_values)

    @Slot()
    def process(self) -> None:
        while True:
            with self._lock:
                config, self._pending_config = self._pending_config, None
                values, self._pending_values = self._pending_values, None
                generation = self._generation
            if config is None and values is None:
                return
            try:
                if config is not None:
                    self._cal = Evaluator(config.spec, config.data, config.objectives, config.calibration)
                    self._val = None
                    if not config.validation.is_open:
                        try:
                            self._val = Evaluator(config.spec, config.data, config.objectives, config.validation)
                        except ValueError as exc:
                            log.warning("validation period ignored: %s", exc)
                    self.configured.emit(self._cal.objective_names, self._cal.minimize_flags)
                if self._cal is None:
                    continue
                if config is not None:  # a new model: forget the previous model's parameter names
                    self._last_values = {}
                if values is not None:
                    self._last_values.update(values)
                cal = self._cal.evaluate(values)
                val = self._val.evaluate(values) if self._val is not None else None
                curves = kernel_curves(self._cal.built, self._cal.dt_hours)
                if config is not None or getattr(self, "_fields", None) is None:
                    self._fields = self._cal.trace_fields()  # metadata only: cheap, listed before any trace runs
                trace, fields = None, list(self._fields)
                if self.want_trace:
                    try:
                        trace = self._cal.trace()
                    except Exception as exc:  # a model without a working trace still evaluates
                        log.warning("trace unavailable: %s", exc)
                self.ready.emit(LiveResult(cal, val, self._cal.datetime, self._cal.observed, self._cal.rain,
                                           curves, self._cal.dt_hours, generation, trace, fields,
                                           self._cal.predicted_key, tuple(self._cal.slow_responses),
                                           dict(self._cal.inputs)))
            except Exception as exc:
                log.exception("live evaluation failed")
                self.failed.emit(f"{type(exc).__name__}: {exc}")


class LiveEvaluationService(QObject):
    """Evaluate the working model off the GUI thread.

    Call :meth:`configure` when the model structure, dataset, periods or
    objectives change and :meth:`request` for every parameter change.
    """

    evaluated = Signal(object)  # LiveResult
    failed = Signal(str)
    configured = Signal(list, list)
    _kick = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._thread.setObjectName("live-evaluation")
        self._worker = _Worker()
        self._worker.moveToThread(self._thread)
        self._kick.connect(self._worker.process)
        self._worker.ready.connect(self.evaluated)
        self._worker.failed.connect(self.failed)
        self._worker.configured.connect(self.configured)
        self._thread.start()
        self.last: LiveResult | None = None
        self.evaluated.connect(self._remember)

    def _remember(self, result: LiveResult) -> None:
        self.last = result

    def configure(self, spec: ModelSpec, data: pd.DataFrame, objectives: list[ObjectiveSpec],
                  calibration: Period, validation: Period, values: dict[str, float]) -> None:
        self._worker.post(values, _Config(spec, data, list(objectives), calibration, validation))
        self._kick.emit()

    def request(self, values: dict[str, float]) -> None:
        self._worker.post(values, None)
        self._kick.emit()

    def set_trace(self, enabled: bool) -> None:
        """Compute components and states with every evaluation (re-evaluates now when switched on)."""
        if enabled == self._worker.want_trace:
            return
        self._worker.want_trace = enabled
        if enabled:
            self._worker.post(None, None, rerun=True)
            self._kick.emit()

    @property
    def trace_enabled(self) -> bool:
        return self._worker.want_trace

    def shutdown(self) -> None:
        self._thread.quit()
        self._thread.wait(3000)
