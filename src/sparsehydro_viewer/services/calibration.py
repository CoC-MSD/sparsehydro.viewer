"""Calibration runs in worker processes.

Each run gets its own ``spawn`` process, so the interface stays responsive
whatever the solver does and cancellation always works: the worker is first
asked to stop at its next progress report and is terminated if it does not
exit in time (solvers without progress callbacks, such as SciPy's, can only
be stopped that way).
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import queue as queue_mod
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from ..core.calibration import CalibrationPayload, process_main
from ..core.runs import RunRecord

log = logging.getLogger(__name__)

TERMINATE_AFTER_MS = 4000


class _Worker:
    def __init__(self, ctx: Any, payload: CalibrationPayload) -> None:
        self.queue = ctx.Queue()
        self.stop = ctx.Event()
        self.process = ctx.Process(target=process_main, args=(payload, self.queue, self.stop), daemon=True,
                                   name=f"calibration-{payload.run_id}")
        self.done = False


class CalibrationService(QObject):
    """Starts, monitors and cancels calibration processes.

    Updates the :class:`RunRecord` in place and emits signals; the run list
    and Calibrate page listen to them.
    """

    progress = Signal(str)  # run id; record.history has grown
    started = Signal(str)
    finished = Signal(str)  # finished, failed or cancelled; see record.status
    status = Signal(str, str)

    def __init__(self, parent: QObject | None = None, max_parallel: int = 2) -> None:
        super().__init__(parent)
        self._ctx = mp.get_context("spawn")
        self._workers: dict[str, _Worker] = {}
        self._records: dict[str, RunRecord] = {}
        self._queue: list[tuple[RunRecord, CalibrationPayload]] = []
        self.max_parallel = max_parallel
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self._progress: dict[str, tuple[float | None, str]] = {}

    # ------------------------------------------------------------------ progress

    def progress_info(self, run_id: str) -> tuple[float | None, str]:
        """``(fraction or None if indeterminate, text)`` for an active run."""
        return self._progress.get(run_id, (None, "queued"))

    def active_runs(self) -> list[RunRecord]:
        return [self._records[r] for r in self._workers if r in self._records] + [r for r, _ in self._queue]

    @staticmethod
    def _fraction(record: RunRecord, generation: int, n_evals: int) -> tuple[float | None, str]:
        from ..core.options import resolve_options
        from ..core.solvers import SOLVERS

        if record.solver is None:
            return None, ""
        entry = SOLVERS.get(record.solver.name)
        opts = resolve_options(entry.options, record.solver.options)
        if "n_gen" in opts:
            total = max(1, int(opts["n_gen"]))
            return min(1.0, generation / total), f"generation {generation}/{total}"
        if "n_evaluations" in opts:
            total = max(1, int(opts["n_evaluations"]))
            return min(1.0, n_evals / total), f"{n_evals:,}/{total:,} evaluations"
        return None, "running"

    # ------------------------------------------------------------------

    def submit(self, record: RunRecord, payload: CalibrationPayload) -> None:
        record.status = "queued"
        self._records[record.id] = record
        self._queue.append((record, payload))
        self._start_queued()

    def cancel(self, run_id: str) -> None:
        self._queue = [(r, p) for r, p in self._queue if r.id != run_id]
        rec = self._records.get(run_id)
        w = self._workers.get(run_id)
        if w is None:
            if rec is not None and rec.status == "queued":
                rec.status = "cancelled"
                self.finished.emit(run_id)
            return
        w.stop.set()
        QTimer.singleShot(TERMINATE_AFTER_MS, lambda: self._terminate(run_id))

    def cancel_all(self) -> None:
        for rid in list(self._workers) + [r.id for r, _ in self._queue]:
            self.cancel(rid)

    def is_active(self, run_id: str) -> bool:
        return run_id in self._workers or any(r.id == run_id for r, _ in self._queue)

    @property
    def active_count(self) -> int:
        return len(self._workers) + len(self._queue)

    def shutdown(self) -> None:
        self._queue.clear()
        for rid in list(self._workers):
            self._terminate(rid)

    # ------------------------------------------------------------------

    def _start_queued(self) -> None:
        while self._queue and len(self._workers) < self.max_parallel:
            record, payload = self._queue.pop(0)
            w = _Worker(self._ctx, payload)
            self._workers[record.id] = w
            record.status = "running"
            self._progress[record.id] = (0.0 if self._fraction(record, 0, 0)[0] is not None else None, "starting")
            w.process.start()
            self.started.emit(record.id)
        if self._workers and not self._timer.isActive():
            self._timer.start()

    def _terminate(self, run_id: str) -> None:
        w = self._workers.get(run_id)
        if w is None:
            return
        if w.process.is_alive():
            w.process.terminate()
            w.process.join(1.0)
        self._finish(run_id, "cancelled", "")

    def _finish(self, run_id: str, status: str, message: str) -> None:
        w = self._workers.pop(run_id, None)
        rec = self._records.pop(run_id, None)
        self._progress.pop(run_id, None)
        if w is not None:
            w.done = True
            try:
                w.queue.close()
            except Exception:  # queue already closed by the child exiting
                pass
        if rec is not None:
            rec.status = status  # type: ignore[assignment]
            if message:
                rec.message = message
            self.finished.emit(run_id)
        self._start_queued()
        if not self._workers:
            self._timer.stop()

    def _poll(self) -> None:
        for run_id, w in list(self._workers.items()):
            rec = self._records[run_id]
            grew = False
            while True:
                try:
                    _, kind, data = w.queue.get_nowait()
                except queue_mod.Empty:
                    break
                except (EOFError, OSError):
                    break
                if kind == "status":
                    frac, _ = self._progress.get(run_id, (None, ""))
                    self._progress[run_id] = (frac, data["text"])
                    self.status.emit(run_id, data["text"])
                    grew = True
                elif kind == "started":
                    rec.param_names = list(data["param_names"])
                    rec.objective_names = list(data["objective_names"])
                    rec.minimize_flags = list(data["minimize_flags"])
                    rec.fixed_values = dict(data["fixed_values"])
                    rec.n_params_total = int(data["n_params_total"])
                elif kind == "progress":
                    rec.add_report(data["generation"], data["n_evals"], data["pareto_F"], data.get("pareto_X"))
                    rec.elapsed_s = float(data["elapsed_s"])
                    self._progress[run_id] = self._fraction(rec, int(data["generation"]), int(data["n_evals"]))
                    grew = True
                elif kind == "finished":
                    rec.pareto_X = np.asarray(data["pareto_X"], dtype=float)
                    rec.pareto_F = np.asarray(data["pareto_F"], dtype=float)
                    rec.elapsed_s = float(data["elapsed_s"])
                    self._finish(run_id, "finished", "")
                    break
                elif kind == "failed":
                    log.error("Calibration %s failed:\n%s", rec.label, data.get("traceback", ""))
                    self._finish(run_id, "failed", data["message"])
                    break
                elif kind == "cancelled":
                    self._finish(run_id, "cancelled", "")
                    break
            if grew and run_id in self._workers:
                self.progress.emit(run_id)
            if run_id in self._workers and not w.process.is_alive() and w.queue.empty():
                self._finish(run_id, "failed", f"worker exited unexpectedly (code {w.process.exitcode})")
