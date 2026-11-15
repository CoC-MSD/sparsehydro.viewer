"""The application's standard status bar.

Fixed zones, left to right:

1. **Message** - transient hints, action tips and errors (``showMessage``).
2. **Context** - project, dataset, working model and parameter counts, plus
   page-specific text.
3. **Cursor** - time and value under the mouse on the active chart.
4. **Activity** - what is running, with one global progress bar.
"""

from __future__ import annotations

import math

import pandas as pd
from PySide6.QtWidgets import QFrame, QLabel, QStatusBar, QWidget

from ...services import CalibrationService, JobManager
from ...widgets.timeseries_plot import TimeseriesPlot
from .activity import ActivityIndicator


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


class StandardStatusBar(QStatusBar):
    def __init__(self, jobs: JobManager, calibration: CalibrationService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("standardStatusBar")
        self.context = QLabel()
        self.context.setObjectName("statusContext")
        self.cursor = QLabel()
        self.cursor.setObjectName("statusCursor")
        self.cursor.setMinimumWidth(190)
        self.activity = ActivityIndicator(jobs, calibration)
        self.addPermanentWidget(self.context)
        self.addPermanentWidget(_divider())
        self.addPermanentWidget(self.cursor)
        self.addPermanentWidget(_divider())
        self.addPermanentWidget(self.activity)
        self._chart: TimeseriesPlot | None = None
        self.set_cursor(float("nan"), float("nan"))

    def set_context(self, text: str) -> None:
        self.context.setText(text)

    def bind_chart(self, plot: TimeseriesPlot | None) -> None:
        """Show the cursor readout of *plot* (the page's active chart)."""
        if plot is self._chart:
            return
        if self._chart is not None:
            try:
                self._chart.cursorMoved.disconnect(self.set_cursor)
            except (RuntimeError, TypeError):
                pass
        self._chart = plot
        if plot is not None:
            plot.cursorMoved.connect(self.set_cursor)
        self.set_cursor(float("nan"), float("nan"))

    def set_cursor(self, t: float, y: float) -> None:
        if math.isnan(t) or self._chart is None:
            self.cursor.setText("")
            return
        try:
            stamp = pd.to_datetime(t, unit="s").strftime("%Y-%m-%d %H:%M")
        except (ValueError, OverflowError):
            stamp = "-"
        self.cursor.setText(f"{stamp}   {y:.4g}")


__all__ = ["StandardStatusBar"]
