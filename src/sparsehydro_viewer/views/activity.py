"""Global activity indicator for the status bar.

Aggregates everything that is executing (thread-pool jobs such as loading,
event fitting and re-simulation, and calibration processes) into one label and
one progress bar.  The bar is determinate when every active item reports a
fraction and busy (indeterminate) otherwise; it hides when nothing runs.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QToolButton, QWidget

from ..services import CalibrationService, JobManager


class ActivityIndicator(QWidget):
    """Label + progress bar + cancel button; :attr:`clicked` asks to show the activity dock."""

    clicked = Signal()

    def __init__(self, jobs: JobManager, calibration: CalibrationService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.jobs = jobs
        self.calibration = calibration
        self.label = QLabel()
        self.label.setObjectName("hint")
        self.bar = QProgressBar()
        self.bar.setFixedWidth(220)
        self.bar.setMaximumHeight(14)
        self.bar.setTextVisible(False)
        self.details = QToolButton()
        self.details.setText("Details")
        self.details.setAutoRaise(True)
        self.details.setToolTip("Show the Activity panel (jobs and log)")
        self.details.clicked.connect(self.clicked)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.addWidget(self.label)
        lay.addWidget(self.bar)
        lay.addWidget(self.details)
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.mousePressEvent = lambda _e: self.clicked.emit()  # type: ignore[method-assign]
        # Coalesce bursts of progress signals into at most ~10 repaints per second.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self.refresh)
        for sig in (jobs.jobAdded, jobs.jobChanged, calibration.started, calibration.finished,
                    calibration.progress, calibration.status):
            sig.connect(self._schedule)
        self.refresh()

    def _schedule(self, *_args) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def items(self) -> list[tuple[str, float | None, str]]:
        """``(label, fraction or None, detail)`` for everything that is running or queued."""
        out: list[tuple[str, float | None, str]] = []
        for info in self.jobs.jobs():
            if info.state == "running":
                out.append((info.label, info.fraction if info.fraction >= 0 else None, info.text))
        for run in self.calibration.active_runs():
            frac, text = self.calibration.progress_info(run.id)
            out.append((f"Calibrating {run.label}", frac if run.status == "running" else None,
                        text if run.status == "running" else "queued"))
        return out

    def refresh(self) -> None:
        items = self.items()
        busy = bool(items)
        self.bar.setVisible(busy)
        self.details.setVisible(busy)
        if not busy:
            self.label.setText("Ready")
            return
        fracs = [f for _, f, _ in items]
        if any(f is None for f in fracs):
            self.bar.setRange(0, 0)  # indeterminate
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * sum(fracs) / len(fracs)))
        label, frac, text = items[0]
        main = f"{label}" + (f" — {text}" if text else "") + (f" ({frac:.0%})" if frac is not None else "")
        more = f"  (+{len(items) - 1} more)" if len(items) > 1 else ""
        self.label.setText(main + more)
        self.setToolTip("\n".join(f"{lbl}: {txt or ''}{f' {f:.0%}' if f is not None else ''}"
                                  for lbl, f, txt in items))
