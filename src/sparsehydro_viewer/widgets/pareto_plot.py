"""Two-objective scatter of one or more Pareto sets with linked selection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme


@dataclass
class ParetoLayer:
    """One set of points.

    :ivar key: Identifier returned in :attr:`ParetoPlot.pointClicked` (a run id).
    :ivar values: ``(n, m)`` objective values in natural form.
    :ivar names: Objective names for the columns of *values*.
    :ivar knee: Index of the knee solution, marked with a ring.
    """

    key: str
    label: str
    values: np.ndarray
    names: list[str]
    color: str
    knee: int | None = None
    size: float = 8.0
    faded: bool = False


class ParetoPlot(QWidget):
    """Scatter of any two objectives; also shows the live (slider) point."""

    pointClicked = Signal(str, int)

    def __init__(self, parent: QWidget | None = None, *, labels: dict[str, str] | None = None,
                 better: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.labels = labels or {}
        self.better = better or {}
        self.x_combo, self.y_combo = QComboBox(), QComboBox()
        row = QHBoxLayout()
        row.addWidget(QLabel("x"))
        row.addWidget(self.x_combo, 1)
        row.addWidget(QLabel("y"))
        row.addWidget(self.y_combo, 1)
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        theme.plain_axes(self.plot)
        self.legend = self.plot.addLegend(offset=(-10, 10), labelTextColor=theme.current().plot_fg)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.plot, 1)
        self._layers: list[ParetoLayer] = []
        self._selection: tuple[str, list[int]] = ("", [])
        self._marker: dict[str, float] | None = None
        self._marker_label = "current"
        self._names: list[str] = []
        self.x_combo.currentIndexChanged.connect(self._redraw)
        self.y_combo.currentIndexChanged.connect(self._redraw)

    # ------------------------------------------------------------------

    def set_layers(self, layers: list[ParetoLayer]) -> None:
        self._layers = list(layers)
        names: list[str] = []
        for layer in layers:
            for n in layer.names:
                if n not in names:
                    names.append(n)
        if names != self._names:
            self._set_names(names)
        self._redraw()

    def set_objectives(self, names: list[str]) -> None:
        if names != self._names:
            self._set_names(names)
            self._redraw()

    def _set_names(self, names: list[str]) -> None:
        old_x, old_y = self.x_combo.currentData(), self.y_combo.currentData()
        self._names = names
        for combo in (self.x_combo, self.y_combo):
            combo.blockSignals(True)
            combo.clear()
            for n in names:
                combo.addItem(self._axis_label(n), n)
            combo.blockSignals(False)
        self.x_combo.setCurrentIndex(max(0, names.index(old_x)) if old_x in names else 0)
        self.y_combo.setCurrentIndex(names.index(old_y) if old_y in names else min(1, len(names) - 1))

    def _axis_label(self, name: str) -> str:
        arrow = {"max": " (higher is better)", "min": " (lower is better)"}.get(self.better.get(name, ""), "")
        return self.labels.get(name, name) + arrow

    def set_selection(self, key: str, indices: list[int]) -> None:
        self._selection = (key, list(indices))
        self._redraw()

    def set_marker(self, objectives: dict[str, float] | None, label: str = "current") -> None:
        self._marker = objectives
        self._marker_label = label
        self._redraw()

    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        self.plot.clear()
        self.legend.clear()
        xn, yn = self.x_combo.currentData(), self.y_combo.currentData()
        if xn is None or yn is None:
            return
        self.plot.setLabel("bottom", self._axis_label(xn))
        self.plot.setLabel("left", self._axis_label(yn))
        th = theme.current()
        for layer in self._layers:
            if xn not in layer.names or yn not in layer.names or layer.values.size == 0:
                continue
            x = layer.values[:, layer.names.index(xn)]
            y = layer.values[:, layer.names.index(yn)]
            c = QColor(layer.color)
            if layer.faded:
                c.setAlpha(90)
            sp = pg.ScatterPlotItem(x, y, size=layer.size, brush=c, pen=pg.mkPen(th.plot_bg, width=0.5),
                                    data=np.arange(len(x)), hoverable=True, name=layer.label,
                                    tip=lambda x, y, data, _l=layer.label: f"{_l} #{data}\n{x:.4g}, {y:.4g}")
            # sigClicked emits (item, points, mouse_event); keep the key out of the positional slots.
            sp.sigClicked.connect(lambda _item, pts, *_ev, _k=layer.key: self._clicked(_k, pts))
            self.plot.addItem(sp)
            if layer.knee is not None and 0 <= layer.knee < len(x):
                self.plot.addItem(pg.ScatterPlotItem([x[layer.knee]], [y[layer.knee]], size=layer.size + 9,
                                                     brush=None, pen=pg.mkPen(layer.color, width=1.5)))
            key, idx = self._selection
            if key == layer.key and idx:
                idx = [i for i in idx if 0 <= i < len(x)]
                self.plot.addItem(pg.ScatterPlotItem(x[idx], y[idx], size=layer.size + 5, brush=th.selection,
                                                     pen=pg.mkPen(th.plot_bg, width=1)))
        if self._marker and xn in self._marker and yn in self._marker:
            self.plot.addItem(pg.ScatterPlotItem([self._marker[xn]], [self._marker[yn]], size=18, symbol="star",
                                                 brush=th.predicted, pen=pg.mkPen(th.plot_fg, width=1),
                                                 name=self._marker_label))

    def _clicked(self, key: str, points) -> None:
        if len(points):
            self.pointClicked.emit(key, int(points[0].data()))
