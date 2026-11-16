"""Background jobs on a thread pool, with progress, cancellation and a job list.

Light work (loading files, event detection, re-simulating Pareto sets) runs
here.  Calibration runs in a separate process instead; see
:mod:`sparsehydro_viewer.services.calibration`.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)


class CancelToken:
    """Cooperative cancellation flag passed to job functions."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def __call__(self) -> bool:  # usable as a ``should_stop`` callable
        return self._event.is_set()


class JobContext:
    """Handed to job functions: progress reporting and cancellation."""

    def __init__(self, job: Job) -> None:
        self._job = job

    @property
    def token(self) -> CancelToken:
        return self._job.token

    @property
    def cancelled(self) -> bool:
        return self._job.token.cancelled

    def progress(self, text: str, fraction: float | None = None) -> None:
        self._job.signals.progress.emit(self._job.info.id, text, -1.0 if fraction is None else float(fraction))


class _Signals(QObject):
    progress = Signal(int, str, float)
    finished = Signal(int, object)
    failed = Signal(int, str, str)


@dataclass
class JobInfo:
    id: int
    label: str
    state: str = "queued"  # queued | running | finished | failed | cancelled
    text: str = ""
    fraction: float = -1.0
    started: float = field(default_factory=time.time)


class Job(QRunnable):
    def __init__(self, info: JobInfo, fn: Callable[[JobContext], Any]) -> None:
        super().__init__()
        self.info = info
        self.fn = fn
        self.token = CancelToken()
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.fn(JobContext(self))
        except Exception as exc:
            self.signals.failed.emit(self.info.id, f"{type(exc).__name__}: {exc}", traceback.format_exc())
        else:
            self.signals.finished.emit(self.info.id, result)


class JobManager(QObject):
    """Submit callables to a thread pool and observe them.

    Results and errors are delivered on the GUI thread through the callbacks
    passed to :meth:`submit` and through the manager's signals (used by the
    job dock).
    """

    jobAdded = Signal(int)
    jobChanged = Signal(int)

    def __init__(self, parent: QObject | None = None, max_threads: int | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        if max_threads:
            self.pool.setMaxThreadCount(max_threads)
        self._jobs: dict[int, Job] = {}
        self._callbacks: dict[int, tuple[Callable[[Any], None] | None, Callable[[str], None] | None]] = {}
        self._next = 1

    def submit(self, label: str, fn: Callable[[JobContext], Any], *,
               on_done: Callable[[Any], None] | None = None,
               on_error: Callable[[str], None] | None = None) -> Job:
        info = JobInfo(self._next, label)
        self._next += 1
        job = Job(info, fn)
        job.signals.progress.connect(self._on_progress)
        job.signals.finished.connect(self._on_finished)
        job.signals.failed.connect(self._on_failed)
        self._jobs[info.id] = job
        self._callbacks[info.id] = (on_done, on_error)
        info.state = "running"
        self.jobAdded.emit(info.id)
        self.pool.start(job)
        return job

    def jobs(self) -> list[JobInfo]:
        return [j.info for j in self._jobs.values()]

    def info(self, job_id: int) -> JobInfo:
        return self._jobs[job_id].info

    def cancel(self, job_id: int) -> None:
        job = self._jobs.get(job_id)
        if job and job.info.state == "running":
            job.token.cancel()
            job.info.text = "cancelling..."
            self.jobChanged.emit(job_id)

    def wait(self, msecs: int = 30000) -> bool:
        return self.pool.waitForDone(msecs)

    # -- slots -------------------------------------------------------------

    def _on_progress(self, job_id: int, text: str, fraction: float) -> None:
        info = self._jobs[job_id].info
        info.text, info.fraction = text, fraction
        self.jobChanged.emit(job_id)

    def _on_finished(self, job_id: int, result: Any) -> None:
        job = self._jobs[job_id]
        job.info.state = "cancelled" if job.token.cancelled else "finished"
        job.info.text, job.info.fraction = "", 1.0
        self.jobChanged.emit(job_id)
        on_done, _ = self._callbacks.pop(job_id, (None, None))
        if on_done is not None and not job.token.cancelled:
            on_done(result)

    def _on_failed(self, job_id: int, message: str, tb: str) -> None:
        job = self._jobs[job_id]
        cancelled = job.token.cancelled
        job.info.state = "cancelled" if cancelled else "failed"
        job.info.text = "" if cancelled else message
        self.jobChanged.emit(job_id)
        if not cancelled:
            log.error("%s failed: %s\n%s", job.info.label, message, tb)
        _, on_error = self._callbacks.pop(job_id, (None, None))
        if on_error is not None and not cancelled:
            on_error(message)
