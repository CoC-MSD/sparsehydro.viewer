"""Objects shared by all pages, and the session -> live evaluation wiring."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.simulate import SimulationCache
from ..services import CalibrationService, JobManager, LiveEvaluationService, LiveResult
from ..session import Session

log = logging.getLogger(__name__)


class LiveController(QObject):
    """Keeps the live evaluator in step with the session.

    Structural changes (dataset, periods, model, bounds, calibrate flags,
    objectives) rebuild the evaluator; value changes only re-evaluate.
    """

    result = Signal(object)
    unavailable = Signal(str)

    def __init__(self, session: Session, live: LiveEvaluationService) -> None:
        super().__init__(session)
        self.session = session
        self.live = live
        self.last: LiveResult | None = None
        self._reconfigure_timer = QTimer(self)
        self._reconfigure_timer.setSingleShot(True)
        self._reconfigure_timer.setInterval(50)
        self._reconfigure_timer.timeout.connect(self._configure)
        for sig in (session.datasetChanged, session.periodsChanged, session.modelChanged, session.parametersEdited,
                    session.objectivesChanged, session.projectChanged):
            sig.connect(self._reconfigure_timer.start)
        session.valuesChanged.connect(self._values)
        live.evaluated.connect(self._evaluated)
        live.failed.connect(self.unavailable)
        self.unavailable.connect(self._forget)

    def _configure(self) -> None:
        s = self.session
        frame = None
        try:
            frame = s.frame()
        except Exception as exc:
            self.unavailable.emit(f"Dataset could not be loaded: {exc}")
            return
        if frame is None:
            self.unavailable.emit("Load a dataset to see the model's response.")
            return
        ds = s.dataset
        assert ds is not None
        self.live.configure(s.model_spec, frame, s.objectives, ds.calibration, ds.validation, dict(s.values))

    def _values(self, values: dict) -> None:
        if self.session.dataset is not None and not self._reconfigure_timer.isActive():
            self.live.request(values)

    def _forget(self, _msg: str = "") -> None:
        self.last = None  # nothing to draw for the working model until it evaluates again

    def _evaluated(self, res: LiveResult) -> None:
        self.last = res
        self.result.emit(res)


@dataclass
class AppContext:
    session: Session
    jobs: JobManager
    calibration: CalibrationService
    live: LiveEvaluationService
    controller: LiveController
    #: Simulated series of solutions, shared by Explore and Compare (see :mod:`..core.simulate`).
    sim_cache: SimulationCache = field(default_factory=SimulationCache)

    def __post_init__(self) -> None:
        self.session.runUpdated.connect(self.sim_cache.drop_run)
        self.session.projectChanged.connect(self.sim_cache.clear)
        self.session.datasetDataChanged.connect(lambda _name: self.sim_cache.clear())  # different rain: redo
