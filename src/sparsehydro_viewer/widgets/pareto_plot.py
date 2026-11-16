"""Two-objective scatter of one or more Pareto sets with linked selection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QGraphicsRectItem, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from .legend import ToggleLegend


@dataclass
class ParetoLayer:
    """One set of points.

    :ivar key: Identifier returned in :attr:`ParetoPlot.pointClicked` (a run id).
    :ivar values: ``(n, m)`` objective values in natural form.
    :ivar names: Objective names for the columns of *values*.
    :ivar knee: Index of the knee solution, marked with a ring.
    :ivar alpha: Fill opacity 0-255 (overrides *faded*), e.g. to fade earlier generations by age.
    :ivar legend: Add a legend entry (off for all but one of a series of history layers).
    :ivar clickable: Emit :attr:`ParetoPlot.pointClicked` for its points.
    :ivar in_range: Count its points when fitting the axes (off for context such as earlier generations, whose
        early, poor points would otherwise squeeze the current front into a corner).
    """

    key: str
    label: str
    values: np.ndarray
    names: list[str]
    color: str
    knee: int | None = None
    size: float = 8.0
    faded: bool = False
    alpha: int | None = None
    legend: bool = True
    clickable: bool = True
    in_range: bool = True


class _RubberBandViewBox(pg.ViewBox):
    """ViewBox whose Shift+left-drag draws a selection rectangle instead of panning."""

    def __init__(self, owner: ParetoPlot) -> None:
        super().__init__()
        self.owner = owner
        self._band: QGraphicsRectItem | None = None

    def mouseDragEvent(self, ev, axis=None) -> None:  # noqa: N802 (Qt naming)
        if ev.button() != Qt.MouseButton.LeftButton or not (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            super().mouseDragEvent(ev, axis)
            return
        ev.accept()
        rect = QRectF(self.mapSceneToView(ev.buttonDownScenePos()), self.mapSceneToView(ev.scenePos())).normalized()
        if self._band is None:
            self._band = QGraphicsRectItem()
            c = QColor(theme.current().accent)
            c.setAlpha(40)
            self._band.setBrush(c)
            pen = pg.mkPen(theme.current().accent)
            pen.setCosmetic(True)
            self._band.setPen(pen)
            self.addItem(self._band, ignoreBounds=True)
        self._band.setRect(rect)
        if ev.isFinish():
            self.removeItem(self._band)
            self._band = None
            self.owner._range_selected(rect, bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier))


class ParetoPlot(QWidget):
    """Scatter of any two objectives; also shows the live (slider) point.

    The plot is passive about selection: it reports what the user did -
    :attr:`pointPicked` (a click; ``add`` with Ctrl), :attr:`rangeSelected`
    (a Shift-drag rectangle), :attr:`selectionCleared` (Esc) - and draws the
    selection it is given with :meth:`set_selection`.
    """

    pointClicked = Signal(str, int)
    #: Layer key, index within the layer, and whether Ctrl was held (add to / remove from the selection).
    pointPicked = Signal(str, int, bool)
    #: ``{layer key: [indices]}`` inside a Shift-drag rectangle, and whether Ctrl was held (add).
    rangeSelected = Signal(dict, bool)
    selectionCleared = Signal()

    def __init__(self, parent: QWidget | None = None, *, labels: dict[str, str] | None = None,
                 better: dict[str, str] | None = None) -> None:
        super().__init__(parent)
        self.labels = labels or {}
        self.better = better or {}
        self.x_combo, self.y_combo = QComboBox(), QComboBox()
        for combo, axis in ((self.x_combo, "horizontal"), (self.y_combo, "vertical")):
            combo.setToolTip(f"Objective on the {axis} axis")
            combo.setAccessibleName(f"Objective on the {axis} axis")
        row = QHBoxLayout()
        row.addWidget(QLabel("x"))
        row.addWidget(self.x_combo, 1)
        row.addWidget(QLabel("y"))
        row.addWidget(self.y_combo, 1)
        self.plot = pg.PlotWidget(viewBox=_RubberBandViewBox(self))
        self.plot.showGrid(x=True, y=True, alpha=0.15)
        self.plot.setToolTip("Click a solution to select it, Ctrl+click to add or remove one, Shift+drag to select "
                             "the solutions in a rectangle, Esc to clear")
        theme.plain_axes(self.plot)
        self.legend = self.plot.addLegend(offset=(-10, 10), labelTextColor=theme.current().plot_fg)
        #: Legend entries switch layers on and off (layers sharing a label together); kept across redraws.
        self.legend_toggle = ToggleLegend(self.legend, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(row)
        lay.addWidget(self.plot, 1)
        self._layers: list[ParetoLayer] = []
        self._selection: dict[str, list[int]] = {}
        self._primary: tuple[str, int] | None = None
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

    def set_selection(self, selection: dict[str, list[int]] | str, indices: list[int] | None = None, *,
                      primary: tuple[str, int] | None = None) -> None:
        """Mark selected points: ``{layer key: [indices]}`` (or one layer as ``key, indices``); *primary*
        ``(key, index)`` is ringed as the solution the detail views show."""
        if isinstance(selection, str):
            selection = {selection: list(indices or [])}
        self._selection = {k: list(v) for k, v in selection.items() if v}
        self._primary = primary
        self._redraw()

    def selection(self) -> dict[str, list[int]]:
        return {k: list(v) for k, v in self._selection.items()}

    def set_marker(self, objectives: dict[str, float] | None, label: str = "current") -> None:
        self._marker = objectives
        self._marker_label = label
        self._redraw()

    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        self.plot.clear()
        self.legend.clear()
        self.legend_toggle.clear()
        series: dict[str, list] = {}  # label -> items, the one shown in the legend first
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
            if layer.alpha is not None:
                c.setAlpha(int(layer.alpha))
            elif layer.faded:
                c.setAlpha(90)
            pen = pg.mkPen(th.plot_bg, width=0.5) if layer.alpha is None else pg.mkPen(None)
            sp = pg.ScatterPlotItem(x, y, size=layer.size, brush=c, pen=pen,
                                    data=np.arange(len(x)), hoverable=True,
                                    name=layer.label if layer.legend else None,
                                    tip=lambda x, y, data, _l=layer.label: f"{_l} #{data}\n{x:.4g}, {y:.4g}")
            if layer.clickable:
                # sigClicked emits (item, points, mouse_event); keep the key out of the positional slots.
                sp.sigClicked.connect(lambda _item, pts, *ev, _k=layer.key: self._clicked(_k, pts, *ev[:1]))
            self.plot.addItem(sp, ignoreBounds=not layer.in_range)
            group = series.setdefault(layer.label, [])
            group.insert(0, sp) if layer.legend else group.append(sp)
            if layer.knee is not None and 0 <= layer.knee < len(x):
                knee = pg.ScatterPlotItem([x[layer.knee]], [y[layer.knee]], size=layer.size + 9,
                                          brush=None, pen=pg.mkPen(layer.color, width=1.5))
                self.plot.addItem(knee)
                group.append(knee)
            idx = [i for i in self._selection.get(layer.key, []) if 0 <= i < len(x)]
            if idx:
                sel = pg.ScatterPlotItem(x[idx], y[idx], size=layer.size + 5, brush=th.selection,
                                         pen=pg.mkPen(th.plot_bg, width=1))
                sel.setZValue(20)
                self.plot.addItem(sel)
            if self._primary is not None and self._primary[0] == layer.key and 0 <= self._primary[1] < len(x):
                p = self._primary[1]
                ring = pg.ScatterPlotItem([x[p]], [y[p]], size=layer.size + 12, brush=None,
                                          pen=pg.mkPen(th.selection, width=2.5))
                ring.setZValue(21)
                self.plot.addItem(ring)
        if self._marker and xn in self._marker and yn in self._marker:
            star = pg.ScatterPlotItem([self._marker[xn]], [self._marker[yn]], size=18, symbol="star",
                                      brush=th.predicted, pen=pg.mkPen(th.plot_fg, width=1),
                                      name=self._marker_label)
            self.plot.addItem(star)
            series[self._marker_label] = [star]
        for label, items in series.items():
            self.legend_toggle.register(label, *items)

    def _clicked(self, key: str, points, ev=None) -> None:
        if len(points):
            i = int(points[0].data())
            mods = ev.modifiers() if ev is not None and hasattr(ev, "modifiers") else Qt.KeyboardModifier.NoModifier
            self.pointClicked.emit(key, i)
            self.pointPicked.emit(key, i, bool(mods & Qt.KeyboardModifier.ControlModifier))

    def points_in(self, rect: QRectF) -> dict[str, list[int]]:
        """Points of the clickable layers inside *rect* (in the plotted objectives' coordinates)."""
        xn, yn = self.x_combo.currentData(), self.y_combo.currentData()
        out: dict[str, list[int]] = {}
        for layer in self._layers:
            if not layer.clickable or xn not in layer.names or yn not in layer.names or layer.values.size == 0:
                continue
            x = layer.values[:, layer.names.index(xn)]
            y = layer.values[:, layer.names.index(yn)]
            inside = (x >= rect.left()) & (x <= rect.right()) & (y >= rect.top()) & (y <= rect.bottom())
            if inside.any():
                out[layer.key] = np.flatnonzero(inside).tolist()
        return out

    def _range_selected(self, rect: QRectF, add: bool) -> None:
        self.rangeSelected.emit(self.points_in(rect), add)

    def keyPressEvent(self, ev) -> None:  # noqa: N802 (Qt naming)
        if ev.key() == Qt.Key.Key_Escape:
            self.selectionCleared.emit()
        else:
            super().keyPressEvent(ev)
