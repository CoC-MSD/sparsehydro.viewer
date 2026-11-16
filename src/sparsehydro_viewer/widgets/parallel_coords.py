"""Brushable parallel coordinates for objectives and parameters.

Each row of the data matrix is a polyline across vertical axes.  Axes are
min-max normalised; axes with a "better" direction are oriented so that better
is always up, which makes good solutions read as high lines.

Interaction:

* drag vertically along an axis to brush a range (several axes combine with AND);
* click an axis without dragging to clear its brush;
* click a line to select that row;
* right-click an axis to invert, hide or move it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsRectItem, QMenu, QVBoxLayout, QWidget

from .. import theme
from .legend import ToggleLegend

AXIS_HIT = 0.18  # fraction of axis spacing that counts as "on the axis"


@dataclass
class AxisSpec:
    name: str
    label: str = ""
    better: str | None = None  # "min", "max" or None
    inverted: bool = False
    visible: bool = True
    kind: str = "parameter"  # "objective", "parameter", "count"

    @property
    def text(self) -> str:
        return self.label or self.name


@dataclass
class _State:
    axes: list[AxisSpec] = field(default_factory=list)
    order: list[int] = field(default_factory=list)  # indices into axes, visible only
    data: np.ndarray = field(default_factory=lambda: np.empty((0, 0)))
    groups: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int))
    group_labels: list[str] = field(default_factory=list)
    group_colors: list[str] = field(default_factory=list)
    lo: np.ndarray = field(default_factory=lambda: np.empty(0))
    hi: np.ndarray = field(default_factory=lambda: np.empty(0))
    brushes: dict[int, tuple[float, float]] = field(default_factory=dict)  # axis index -> normalised range


class _ViewBox(pg.ViewBox):
    def __init__(self, owner: ParallelCoordinates) -> None:
        super().__init__(enableMenu=False)
        self.owner = owner
        self.setMouseEnabled(False, False)
        self._drag_axis: int | None = None
        self._drag_start = 0.0

    def mouseDragEvent(self, ev, axis=None) -> None:  # noqa: N802 (Qt naming)
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        p = self.mapSceneToView(ev.scenePos())
        if ev.isStart():
            self._drag_axis = self.owner._axis_at(p.x())
            self._drag_start = self.mapSceneToView(ev.buttonDownScenePos()).y()
        if self._drag_axis is None:
            return
        y0, y1 = sorted((self._drag_start, p.y()))
        self.owner._set_brush(self._drag_axis, max(0.0, y0), min(1.0, y1), final=ev.isFinish())

    def mouseClickEvent(self, ev) -> None:  # noqa: N802
        p = self.mapSceneToView(ev.scenePos())
        axis = self.owner._axis_at(p.x())
        if ev.button() == Qt.MouseButton.RightButton and axis is not None:
            ev.accept()
            self.owner._axis_menu(axis, ev.screenPos().toPoint())
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            if axis is not None:
                self.owner._clear_brush(axis)
            else:
                self.owner._pick_line(p, add=bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier))


class ParallelCoordinates(QWidget):
    """Parallel coordinates plot.

    :attr:`selectionChanged` emits the row indices passing all brushes (all
    rows when nothing is brushed); :attr:`rowClicked` emits a clicked row.
    """

    selectionChanged = Signal(list)
    rowClicked = Signal(int)
    #: A clicked row and whether Ctrl was held (add to / remove from the selection).
    rowPicked = Signal(int, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vb = _ViewBox(self)
        self.view = pg.PlotWidget(viewBox=self.vb)
        self.view.hideAxis("left")
        self.view.hideAxis("bottom")
        self.legend = self.view.addLegend(offset=(-10, -10), labelTextColor=theme.current().plot_fg)
        #: Legend entries switch groups (runs), the selection and the slider line on and off.
        self.legend_toggle = ToggleLegend(self.legend, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.s = _State()
        self._highlight: list[int] = []
        self._primary: int | None = None
        self._extra: dict[str, float] | None = None
        self._extra_label = "current"
        self._brush_items: dict[int, QGraphicsRectItem] = {}

    # ------------------------------------------------------------------ API

    def set_data(self, axes: list[AxisSpec], data: np.ndarray, *, groups: np.ndarray | None = None,
                 group_labels: list[str] | None = None, group_colors: list[str] | None = None,
                 keep_brushes: bool = False) -> None:
        data = np.atleast_2d(np.asarray(data, dtype=float))
        if data.size and data.shape[1] != len(axes):
            raise ValueError(f"data has {data.shape[1]} columns for {len(axes)} axes")
        old = {a.name: (a.inverted, a.visible) for a in self.s.axes}
        old_brush = {self.s.axes[i].name: r for i, r in self.s.brushes.items()} if keep_brushes else {}
        old_order = [self.s.axes[i].name for i in self.s.order]
        for a in axes:
            if a.name in old:
                a.inverted, a.visible = old[a.name]
        self.s.axes = axes
        self.s.data = data if data.size else np.empty((0, len(axes)))
        n = self.s.data.shape[0]
        self.s.groups = np.zeros(n, dtype=int) if groups is None else np.asarray(groups, dtype=int)
        self.s.group_labels = group_labels or [""]
        self.s.group_colors = group_colors or [theme.series_color(0)]
        with np.errstate(all="ignore"):
            self.s.lo = np.nanmin(self.s.data, axis=0) if n else np.zeros(len(axes))
            self.s.hi = np.nanmax(self.s.data, axis=0) if n else np.ones(len(axes))
        names = [a.name for a in axes]
        kept = [names.index(nm) for nm in old_order if nm in names and axes[names.index(nm)].visible]
        rest = [i for i, a in enumerate(axes) if a.visible and i not in kept]
        self.s.order = kept + rest
        self.s.brushes = {names.index(k): v for k, v in old_brush.items() if k in names}
        self._highlight = [i for i in self._highlight if i < n]
        self._redraw()
        self.selectionChanged.emit(self.selected_rows())

    def set_highlight(self, rows: list[int], primary: int | None = None) -> None:
        """Draw *rows* as selected (each its own line); *primary* (default: the first) is drawn thickest."""
        self._highlight = list(dict.fromkeys(rows))
        self._primary = primary if primary in self._highlight else (self._highlight[0] if self._highlight else None)
        self._redraw()

    def set_extra_line(self, values: dict[str, float] | None, label: str = "current") -> None:
        """Overlay a line given by values per axis name (e.g. the slider point)."""
        self._extra = values
        self._extra_label = label
        self._redraw()

    def clear_brushes(self) -> None:
        self.s.brushes.clear()
        self._redraw()
        self.selectionChanged.emit(self.selected_rows())

    def selected_rows(self) -> list[int]:
        n = self.s.data.shape[0]
        if not self.s.brushes:
            return list(range(n))
        norm = self._normalised()
        ok = np.ones(n, dtype=bool)
        for i, (a, b) in self.s.brushes.items():
            ok &= (norm[:, i] >= a) & (norm[:, i] <= b)
        return np.flatnonzero(ok).tolist()

    def axis_order(self) -> list[str]:
        return [self.s.axes[i].name for i in self.s.order]

    # ------------------------------------------------------------------ geometry

    def _norm_col(self, values: np.ndarray, i: int) -> np.ndarray:
        lo, hi = self.s.lo[i], self.s.hi[i]
        span = hi - lo
        out = np.full_like(values, 0.5, dtype=float) if not np.isfinite(span) or span <= 0 else (values - lo) / span
        a = self.s.axes[i]
        flip = (a.better == "min") != a.inverted
        return 1.0 - out if flip else out

    def _normalised(self) -> np.ndarray:
        if not self.s.data.size:
            return self.s.data
        return np.column_stack([self._norm_col(self.s.data[:, i], i) for i in range(len(self.s.axes))])

    def _axis_at(self, x: float) -> int | None:
        k = int(round(x))
        if 0 <= k < len(self.s.order) and abs(x - k) <= AXIS_HIT:
            return self.s.order[k]
        return None

    # ------------------------------------------------------------------ drawing

    def _redraw(self) -> None:
        self.view.clear()
        self.legend.clear()
        self.legend_toggle.clear()
        self._brush_items.clear()

        def add(item, name: str | None):
            self.view.addItem(item)
            self.legend_toggle.register(name, item)
        th = theme.current()
        order = self.s.order
        m = len(order)
        if m == 0:
            return
        xs = np.arange(m, dtype=float)
        norm = self._normalised()
        sel = set(self.selected_rows())
        n = norm.shape[0] if norm.size else 0

        def polyline(rows: list[int]) -> tuple[np.ndarray, np.ndarray]:
            if not rows:
                return np.empty(0), np.empty(0)
            y = np.column_stack([norm[rows][:, order], np.full(len(rows), np.nan)]).ravel()
            x = np.tile(np.r_[xs, np.nan], len(rows))
            return x, y

        faded = [r for r in range(n) if r not in sel]
        if faded:
            c = QColor(th.muted)
            c.setAlpha(45)
            x, y = polyline(faded)
            self.view.addItem(pg.PlotDataItem(x, y, pen=pg.mkPen(c, width=1), connect="finite"))
        alpha = 200 if n < 60 else 120 if n < 400 else 60
        for g, label in enumerate(self.s.group_labels):
            rows = [r for r in range(n) if r in sel and self.s.groups[r] == g]
            if not rows:
                continue
            c = QColor(self.s.group_colors[g % len(self.s.group_colors)])
            c.setAlpha(alpha)
            x, y = polyline(rows)
            add(pg.PlotDataItem(x, y, pen=pg.mkPen(c, width=1.3), connect="finite", name=label or None),
                label or None)
        shown = [r for r in self._highlight if r < n]
        others = [r for r in shown if r != self._primary]
        if others:  # one item (one legend entry) for the rest of the selection, then the primary on top
            x, y = polyline(others)
            add(pg.PlotDataItem(x, y, pen=pg.mkPen(th.selection, width=2), connect="finite",
                                name=f"selected ({len(shown)})"), "selected")
        if self._primary is not None and self._primary < n:
            x, y = polyline([self._primary])
            add(pg.PlotDataItem(x, y, pen=pg.mkPen(th.selection, width=3.5), connect="finite",
                                symbol="o", symbolSize=6, symbolBrush=th.selection,
                                name="selected" if not others else "primary"),
                "selected" if not others else "primary")
        if self._extra:
            names = [a.name for a in self.s.axes]
            ys = [float(self._norm_col(np.array([self._extra[names[i]]]), i)[0]) if names[i] in self._extra
                  else np.nan for i in order]
            add(pg.PlotDataItem(xs, ys, pen=pg.mkPen(th.predicted, width=2.5, style=Qt.PenStyle.DashLine),
                                symbol="o", symbolSize=6, symbolBrush=th.predicted, connect="finite",
                                name=self._extra_label), self._extra_label)
        axis_pen = pg.mkPen(th.plot_fg, width=1)
        for k, i in enumerate(order):
            a = self.s.axes[i]
            self.view.addItem(pg.PlotDataItem([k, k], [0, 1], pen=axis_pen))
            top, bottom = self.s.hi[i], self.s.lo[i]
            if (a.better == "min") != a.inverted:
                top, bottom = bottom, top
            title = a.text + (" *" if a.kind == "objective" else "")
            self._label(title, k, 1.08, bold=True)
            self._label(_fmt(top), k, 1.02)
            self._label(_fmt(bottom), k, -0.04)
            if i in self.s.brushes:
                self._draw_brush(k, *self.s.brushes[i])
        self.vb.setRange(xRange=(-0.4, m - 0.6), yRange=(-0.1, 1.14), padding=0)

    def _label(self, text: str, x: float, y: float, bold: bool = False) -> None:
        item = pg.TextItem(text, color=theme.current().plot_fg, anchor=(0.5, 0.5))
        if bold:
            f = item.textItem.font()
            f.setBold(True)
            item.setFont(f)
        item.setPos(x, y)
        self.view.addItem(item)

    def _draw_brush(self, k: int, a: float, b: float) -> QGraphicsRectItem:
        th = theme.current()
        rect = QGraphicsRectItem(QRectF(QPointF(k - 0.08, a), QPointF(k + 0.08, b)))
        c = QColor(th.accent)
        c.setAlpha(70)
        rect.setBrush(c)
        rect.setPen(pg.mkPen(th.accent, width=1))
        self.view.addItem(rect)
        return rect

    # ------------------------------------------------------------------ interaction

    def _set_brush(self, axis: int, a: float, b: float, final: bool) -> None:
        if b - a < 1e-3:
            return
        self.s.brushes[axis] = (a, b)
        if final:
            self._redraw()
            self.selectionChanged.emit(self.selected_rows())
        else:
            k = self.s.order.index(axis)
            old = self._brush_items.pop(axis, None)
            if old is not None:
                self.view.removeItem(old)
            self._brush_items[axis] = self._draw_brush(k, a, b)

    def _clear_brush(self, axis: int) -> None:
        if self.s.brushes.pop(axis, None) is not None:
            self._redraw()
            self.selectionChanged.emit(self.selected_rows())

    def _pick_line(self, p: QPointF, add: bool = False) -> None:
        norm = self._normalised()
        if not norm.size:
            return
        order = self.s.order
        x = min(max(p.x(), 0.0), len(order) - 1.0)
        k0 = int(np.floor(x))
        k1 = min(k0 + 1, len(order) - 1)
        f = x - k0
        y = norm[:, order[k0]] * (1 - f) + norm[:, order[k1]] * f
        rows = self.selected_rows()
        if not rows:
            return
        d = np.abs(y[rows] - p.y())
        j = int(np.nanargmin(d))
        if d[j] < 0.05:
            self.rowClicked.emit(int(rows[j]))
            self.rowPicked.emit(int(rows[j]), add)

    def _axis_menu(self, axis: int, pos) -> None:
        a = self.s.axes[axis]
        menu = QMenu(self)
        inv = menu.addAction("Invert axis")
        hide = menu.addAction("Hide axis")
        k = self.s.order.index(axis)
        left = menu.addAction("Move left")
        right = menu.addAction("Move right")
        left.setEnabled(k > 0)
        right.setEnabled(k < len(self.s.order) - 1)
        menu.addSeparator()
        show_all = menu.addAction("Show all axes")
        clear = menu.addAction("Clear all brushes")
        act = menu.exec(pos)
        if act is inv:
            a.inverted = not a.inverted
            if axis in self.s.brushes:
                lo, hi = self.s.brushes[axis]
                self.s.brushes[axis] = (1 - hi, 1 - lo)
        elif act is hide:
            a.visible = False
            self.s.order.remove(axis)
            self.s.brushes.pop(axis, None)
        elif act is left:
            self.s.order[k - 1], self.s.order[k] = self.s.order[k], self.s.order[k - 1]
        elif act is right:
            self.s.order[k + 1], self.s.order[k] = self.s.order[k], self.s.order[k + 1]
        elif act is show_all:
            for i, ax in enumerate(self.s.axes):
                if not ax.visible:
                    ax.visible = True
                    self.s.order.append(i)
        elif act is clear:
            self.s.brushes.clear()
        else:
            return
        self._redraw()
        self.selectionChanged.emit(self.selected_rows())


def _fmt(v: float) -> str:
    if not np.isfinite(v):
        return ""
    return f"{v:.3g}"
