"""Calibration / validation period editor (checkbox + start/end)."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QDateTime, Signal
from PySide6.QtWidgets import QCheckBox, QDateTimeEdit, QHBoxLayout, QLabel, QWidget

from ..core.data import Period


class PeriodEditor(QWidget):
    """:attr:`edited` fires when the user changes anything."""

    edited = Signal()

    def __init__(self, title: str, color: str) -> None:
        super().__init__()
        self.enabled = QCheckBox(title)
        self.enabled.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: 600; }}")
        self.enabled.setToolTip(f"Use a {title.lower()} period (unticked: the whole record)")
        self.start, self.end = QDateTimeEdit(), QDateTimeEdit()
        for e, end in ((self.start, "Start"), (self.end, "End")):
            e.setDisplayFormat("yyyy-MM-dd HH:mm")
            e.setCalendarPopup(True)
            e.editingFinished.connect(self.edited)
            e.setToolTip(f"{end} of the {title.lower()} period (or drag on the chart)")
            e.setAccessibleName(f"{title} {end.lower()}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.enabled)
        lay.addWidget(self.start, 1)
        lay.addWidget(QLabel("to"))
        lay.addWidget(self.end, 1)
        self.enabled.toggled.connect(self._sync)
        self.enabled.toggled.connect(lambda *_: self.edited.emit())
        self._sync(False)

    def _sync(self, on: bool) -> None:
        self.start.setEnabled(on)
        self.end.setEnabled(on)

    def set_range(self, t0: pd.Timestamp, t1: pd.Timestamp) -> None:
        for e in (self.start, self.end):
            e.setDateTimeRange(QDateTime(t0.to_pydatetime()), QDateTime(t1.to_pydatetime()))

    def set_period(self, p: Period, t0: pd.Timestamp, t1: pd.Timestamp) -> None:
        for w in (self.enabled, self.start, self.end):
            w.blockSignals(True)
        self.enabled.setChecked(not p.is_open)
        self._sync(not p.is_open)
        self.start.setDateTime(QDateTime(pd.Timestamp(p.start or t0).to_pydatetime()))
        self.end.setDateTime(QDateTime(pd.Timestamp(p.end or t1).to_pydatetime()))
        for w in (self.enabled, self.start, self.end):
            w.blockSignals(False)

    def period(self) -> Period:
        if not self.enabled.isChecked():
            return Period()
        fmt = "%Y-%m-%d %H:%M:%S"
        return Period(self.start.dateTime().toPython().strftime(fmt), self.end.dateTime().toPython().strftime(fmt))


__all__ = ["PeriodEditor"]
