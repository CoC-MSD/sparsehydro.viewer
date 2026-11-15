"""Unit hydrograph preview: curves plus shape statistics."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from .. import theme
from ..core.uh import KernelCurve, display_hours


class UHPreview(QWidget):
    """Unit-area UH curves in hours.

    The current model's curves are drawn solid; pinned curves (snapshots the
    user kept for comparison) dashed.
    """

    def __init__(self, parent: QWidget | None = None, *, show_table: bool = True) -> None:
        super().__init__(parent)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Time since excess [h]")
        self.plot.setLabel("left", "Ordinate [1/h]")
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        theme.plain_axes(self.plot)
        self.legend = self.plot.addLegend(offset=(-10, 10), labelTextColor=theme.current().plot_fg)
        self.table = QTableWidget(0, 0)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.plot)
        split.addWidget(self.table)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        self.table.setVisible(show_table)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)
        self._pinned: list[tuple[str, KernelCurve]] = []
        self._current: list[KernelCurve] = []
        self._fixed_horizon: float | None = None

    def set_curves(self, curves: list[KernelCurve]) -> None:
        self._current = list(curves)
        self._redraw()

    def pin_current(self, label: str) -> None:
        main = self._main_curve(self._current)
        if main is not None:
            self._pinned.append((label, main))
            self._redraw()

    def clear_pinned(self) -> None:
        self._pinned.clear()
        self._redraw()

    def set_horizon(self, hours: float | None) -> None:
        self._fixed_horizon = hours
        self._redraw()

    @staticmethod
    def _main_curve(curves: list[KernelCurve]) -> KernelCurve | None:
        if not curves:
            return None
        return curves[-1] if len(curves) > 1 else curves[0]

    def _redraw(self) -> None:
        self.plot.clear()
        self.legend.clear()
        all_curves = list(self._current) + [c for _, c in self._pinned]
        horizon = self._fixed_horizon or display_hours(all_curves) * 1.05
        th = theme.current()
        multi = len(self._current) > 1
        # Components are drawn as their share of the combined curve, so they add up to it.
        total_weight = sum(c.weight for c in self._current if c.label != "combined") or 1.0
        for i, c in enumerate(self._current):
            if not multi or c.label == "combined":
                y, color, width = c.ordinates, th.predicted, 2.4
            else:
                y, color, width = c.ordinates * c.weight / total_weight, theme.series_color(i), 1.3
            self.plot.plot(np.r_[0.0, c.t_hours], np.r_[0.0, y], pen=pg.mkPen(color, width=width),
                           name=c.label if multi else "current")
        for j, (label, c) in enumerate(self._pinned):
            pen = pg.mkPen(theme.series_color(j + 1), width=1.4, style=Qt.PenStyle.DashLine)
            self.plot.plot(np.r_[0.0, c.t_hours], np.r_[0.0, c.ordinates], pen=pen, name=label)
        self.plot.setXRange(0, horizon, padding=0)
        self.plot.enableAutoRange(axis="y")
        self._fill_table(all_curves, [c.label if multi else "current" for c in self._current]
                         + [lbl for lbl, _ in self._pinned])

    def _fill_table(self, curves: list[KernelCurve], labels: list[str]) -> None:
        if not curves:
            self.table.setRowCount(0)
            return
        keys = list(curves[0].stats())
        self.table.setColumnCount(len(keys) + 1)
        self.table.setHorizontalHeaderLabels(["curve"] + keys)
        self.table.setRowCount(len(curves))
        for r, (lbl, c) in enumerate(zip(labels, curves)):
            self.table.setItem(r, 0, QTableWidgetItem(lbl))
            for k, (_, v) in enumerate(c.stats().items(), start=1):
                it = QTableWidgetItem(f"{v:.3g}")
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, k, it)
