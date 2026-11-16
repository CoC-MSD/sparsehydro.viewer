"""Map of project nodes: sites as points, zones as polygons (Web Mercator).

Exactly one interaction mode is active (:meth:`MapView.set_mode`):

* ``select`` (default) and ``lasso``: click a feature to select it, Ctrl+click to add or remove it; drag a
  rectangle (``select``) or draw a free shape (``lasso``) to select what is inside. Sites win over the zones
  beneath them; hold Alt to pick zones only. Esc clears the selection.
* ``pan``: drag to move the map. ``zoom``: drag a rectangle to zoom into it.
* ``move``: drag a site to move it (:attr:`MapView.pointMoved`); click empty map to place the selected site
  (:attr:`MapView.placeRequested`).
* ``draw``: click to add polygon vertices, double-click (or Enter) to finish (:attr:`MapView.polygonDrawn`).

In every mode the wheel zooms and the middle button pans; Esc leaves ``move``/``draw``/``pan``/``zoom`` for
``select``. The map offers the same navigation interface as the time-series charts (``set_mode``,
``auto_range``, ``export_png``, ``cursorMoved``), so the application toolbar's chart tools act on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsRectItem, QLabel, QWidget

from .. import theme
from ..core.geometry import (
    from_mercator,
    geometry_points,
    ground_scale,
    parse_point,
    parse_polygons,
    to_mercator,
)

PICK_PX = 10  # click tolerance in pixels
MAX_DRAWN_VERTICES = 4000  # rings longer than this are thinned for drawing (stored at full precision)
MODES = ("select", "lasso", "pan", "zoom", "move", "draw")
_CURSORS = {"select": Qt.CursorShape.ArrowCursor, "lasso": Qt.CursorShape.CrossCursor,
            "pan": Qt.CursorShape.OpenHandCursor, "zoom": Qt.CursorShape.CrossCursor,
            "move": Qt.CursorShape.SizeAllCursor, "draw": Qt.CursorShape.CrossCursor}


@dataclass
class MapFeature:
    """Something to draw: a point (site) or a polygon (zone)."""

    iri: str
    label: str
    geometry: str | None
    color: str
    kind: str = "site"  # "site" | "zone"
    tooltip: str = ""


class _ScaleBar(QWidget):
    """Ground-distance scale bar drawn over the bottom-left corner of the map."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.px, self.text = 0, ""
        self.resize(220, 34)

    def set_scale(self, metres_per_px: float) -> None:
        if not math.isfinite(metres_per_px) or metres_per_px <= 0:
            self.px, self.text = 0, ""
        else:
            target = metres_per_px * 120
            exp = 10 ** math.floor(math.log10(target))
            nice = max(m * exp for m in (1, 2, 5) if m * exp <= target)
            self.px = int(nice / metres_per_px)
            self.text = f"{nice / 1000:g} km" if nice >= 1000 else f"{nice:g} m"
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        if not self.px:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        th = theme.current()
        p.setPen(QPen(QColor(th.plot_fg), 2))
        y = self.height() - 8
        p.drawLine(8, y, 8 + self.px, y)
        p.drawLine(8, y - 5, 8, y)
        p.drawLine(8 + self.px, y - 5, 8 + self.px, y)
        p.drawText(10, y - 7, self.text)


class _MapViewBox(pg.ViewBox):
    def __init__(self) -> None:
        super().__init__(lockAspect=True, enableMenu=False)
        self.owner: MapView | None = None  # set by MapView after its own construction

    def mouseClickEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton and self.owner is not None:
            ev.accept()
            self.owner._clicked(self.mapSceneToView(ev.scenePos()), ev.modifiers(), ev.double())
        else:
            super().mouseClickEvent(ev)

    def mouseDragEvent(self, ev, axis=None) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton and self.owner is not None and self.owner._drag(ev, self):
            return
        super().mouseDragEvent(ev, axis)


class MapView(pg.PlotWidget):
    selectionChanged = Signal(list)  # iris
    pointMoved = Signal(str, float, float)  # iri, lon, lat
    placeRequested = Signal(float, float)  # lon, lat
    polygonDrawn = Signal(list)  # [(lon, lat), ...]
    modeChanged = Signal(str)
    #: Mouse over the map: Web Mercator x, y (NaN, NaN when it leaves); see :meth:`format_cursor`.
    cursorMoved = Signal(float, float)
    #: The map has no y axis to rescale; the toolbar disables Auto Y.
    supports_auto_y = False
    auto_y = False

    def __init__(self, parent: QWidget | None = None) -> None:
        vb = _MapViewBox()
        super().__init__(parent, viewBox=vb)
        vb.owner = self
        self.vb = vb
        th = theme.current()
        self.setBackground(th.plot_bg)
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.features: dict[str, MapFeature] = {}
        self.selection: list[str] = []
        self.mode = "select"
        self._points = pg.ScatterPlotItem(hoverable=True, tip=self._tip)
        self._points.setZValue(10)
        self.addItem(self._points)
        self._sel_points = pg.ScatterPlotItem()
        self._sel_points.setZValue(11)
        self.addItem(self._sel_points)
        self._labels: list[pg.TextItem] = []
        self._zones: dict[str, QGraphicsPathItem] = {}
        self._xy: dict[str, tuple[float, float]] = {}
        self._band: QGraphicsRectItem | None = None
        self._dragging: str | None = None
        self._drag_marker: pg.ScatterPlotItem | None = None
        self._draft: list[tuple[float, float]] = []
        self._draft_item: pg.PlotDataItem | None = None
        self._lasso: list[tuple[float, float]] = []
        self._lasso_item: pg.PlotDataItem | None = None
        self.scene().sigMouseMoved.connect(self._mouse_moved)
        self.scale_bar = _ScaleBar(self)
        self.attribution = QLabel(self)
        self.attribution.setObjectName("hint")
        self.attribution.hide()
        self.empty_hint = QLabel(self)
        self.empty_hint.setObjectName("hint")
        self.empty_hint.setWordWrap(True)
        self.vb.sigRangeChanged.connect(lambda *_: self._update_scale())
        self.tiles = None
        self.vb.setRange(QRectF(-2e7, -1e7, 4e7, 2e7), padding=0)

    # ------------------------------------------------------------------ content

    def set_features(self, features: list[MapFeature]) -> None:
        self.features = {f.iri: f for f in features}
        th = theme.current()
        spots, self._xy = [], {}
        for item in self._labels:
            self.removeItem(item)
        self._labels = []
        for item in self._zones.values():
            self.removeItem(item)
        self._zones = {}
        for f in features:
            if f.kind == "zone":
                polygons = parse_polygons(f.geometry)
                if polygons:
                    path = QPainterPath()
                    path.setFillRule(Qt.FillRule.OddEvenFill)  # holes stay empty
                    for rings in polygons:
                        for ring in rings:
                            ring = ring[:: max(1, len(ring) // MAX_DRAWN_VERTICES)]  # drawing only
                            rx, ry = to_mercator([p[0] for p in ring], [p[1] for p in ring])
                            path.addPolygon(QPolygonF([QPointF(x, y) for x, y in zip(rx, ry)]))
                            path.closeSubpath()
                    outer = max((p[0] for p in polygons), key=len)  # label the largest part
                    xs, ys = to_mercator([p[0] for p in outer], [p[1] for p in outer])
                    item = QGraphicsPathItem(path)
                    fill = QColor(f.color)
                    fill.setAlpha(45)
                    item.setBrush(QBrush(fill))
                    pen = QPen(QColor(f.color), 2)
                    pen.setCosmetic(True)
                    item.setPen(pen)
                    item.setZValue(1)
                    item.setToolTip(f.tooltip or f.label)
                    self.addItem(item)
                    self._zones[f.iri] = item
                    cx, cy = float(np.mean(xs)), float(np.mean(ys))
                    self._xy[f.iri] = (cx, cy)
                    self._label(f.label, cx, cy, th.muted)
                continue
            p = parse_point(f.geometry)
            if p is None:
                continue
            x, y = to_mercator(*p)
            self._xy[f.iri] = (x, y)
            spots.append({"pos": (x, y), "data": f.iri, "brush": pg.mkBrush(f.color), "size": 13,
                          "pen": pg.mkPen(th.plot_bg, width=1.5), "symbol": "o"})
            self._label(f.label, x, y, th.plot_fg)
        self._points.setData(spots)
        self._draw_selection()
        missing = [f.label for f in features if f.kind == "site" and parse_point(f.geometry) is None]
        self.empty_hint.setText(
            "" if not missing else f"{len(missing)} site(s) without a location: select one, turn on Edit "
                                   "locations and click the map to place it.")
        self.empty_hint.setVisible(bool(missing))
        self._place_overlays()

    def _label(self, text: str, x: float, y: float, color: str) -> None:
        t = pg.TextItem(text, color=color, anchor=(-0.1, 1.1))
        t.setPos(x, y)
        t.setZValue(12)
        self.addItem(t, ignoreBounds=True)
        self._labels.append(t)

    def _tip(self, x, y, data) -> str:
        f = self.features.get(data)
        if f is None:
            return ""
        lon, lat = from_mercator(x, y)
        return f"{f.label}\n{f.tooltip}\n{lat:.5f}, {lon:.5f}".replace("\n\n", "\n")

    # ------------------------------------------------------------------ selection

    def set_selection(self, iris: list[str]) -> None:
        self.selection = [i for i in iris if i in self.features]
        self._draw_selection()

    def _draw_selection(self) -> None:
        th = theme.current()
        pts = [self._xy[i] for i in self.selection if i in self._xy and self.features[i].kind == "site"]
        self._sel_points.setData([p[0] for p in pts], [p[1] for p in pts], size=22, brush=None,
                                 pen=pg.mkPen(th.selection, width=2.5))
        for iri, item in self._zones.items():
            pen = QPen(QColor(th.selection if iri in self.selection else self.features[iri].color),
                       3 if iri in self.selection else 2)
            pen.setCosmetic(True)
            item.setPen(pen)

    def _select(self, iris: list[str], modifiers) -> None:
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            sel = list(self.selection)
            for i in iris:
                if i in sel:
                    sel.remove(i)
                else:
                    sel.append(i)
        else:
            sel = list(iris)
        self.selection = sel
        self._draw_selection()
        self.selectionChanged.emit(list(sel))

    def pick(self, x: float, y: float, *, zones_only: bool = False) -> str | None:
        """Site within :data:`PICK_PX` pixels of view point ``(x, y)``, else a zone containing it."""
        if not zones_only:
            px = self.vb.viewPixelSize()[0] or 1.0
            best, best_d = None, PICK_PX * px
            for iri, (fx, fy) in self._xy.items():
                if self.features[iri].kind != "site":
                    continue
                d = math.hypot(fx - x, fy - y)
                if d <= best_d:
                    best, best_d = iri, d
            if best is not None:
                return best
        for iri, item in self._zones.items():
            if item.path().contains(QPointF(x, y)):
                return iri
        return None

    def features_inside(self, shape: QRectF | QPolygonF, *, zones_only: bool = False) -> list[str]:
        """Sites inside *shape* (view coordinates); with *zones_only*, the zones whose centre is inside."""
        if isinstance(shape, QRectF):
            def inside(x: float, y: float) -> bool:
                return shape.contains(QPointF(x, y))
        else:
            def inside(x: float, y: float) -> bool:
                return shape.containsPoint(QPointF(x, y), Qt.FillRule.OddEvenFill)
        kind = "zone" if zones_only else "site"
        return [i for i, (x, y) in self._xy.items() if self.features[i].kind == kind and inside(x, y)]

    # ------------------------------------------------------------------ modes

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(mode)
        self._cancel_draft()
        self._cancel_band()
        self.mode = mode
        self.vb.setMouseMode(pg.ViewBox.RectMode if mode == "zoom" else pg.ViewBox.PanMode)
        self.viewport().setCursor(_CURSORS[mode])
        self.modeChanged.emit(mode)

    def _clicked(self, p: QPointF, modifiers, double: bool) -> None:
        x, y = p.x(), p.y()
        if self.mode == "draw":
            if double:
                self.finish_polygon()
            else:
                self._draft.append((x, y))
                self._draw_draft()
            return
        if self.mode in ("pan", "zoom"):
            return
        zones_only = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        hit = self.pick(x, y, zones_only=zones_only)
        if self.mode == "move" and hit is None:
            lon, lat = from_mercator(x, y)
            self.placeRequested.emit(float(lon), float(lat))
            return
        self._select([hit] if hit else [], modifiers)

    def _drag(self, ev, vb: pg.ViewBox) -> bool:
        """Handle a left drag; ``False`` lets the view box pan (``pan``) or zoom to a rectangle (``zoom``)."""
        p = vb.mapSceneToView(ev.scenePos())
        if self.mode in ("pan", "zoom"):
            return False
        if self.mode == "move":
            if ev.isStart():
                start = vb.mapSceneToView(ev.buttonDownScenePos())
                hit = self.pick(start.x(), start.y())
                self._dragging = hit if hit and self.features[hit].kind == "site" else None
                if self._dragging:
                    self._drag_marker = pg.ScatterPlotItem(size=16, brush=pg.mkBrush(theme.current().selection))
                    self.addItem(self._drag_marker)
            if self._dragging is None:
                return False
            ev.accept()
            self._drag_marker.setData([p.x()], [p.y()])  # type: ignore[union-attr]
            if ev.isFinish():
                self.removeItem(self._drag_marker)
                self._drag_marker = None
                lon, lat = from_mercator(p.x(), p.y())
                iri, self._dragging = self._dragging, None
                self.pointMoved.emit(iri, float(lon), float(lat))
            return True
        zones_only = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
        if self.mode == "select":
            ev.accept()
            start = vb.mapSceneToView(ev.buttonDownScenePos())
            rect = QRectF(start, p).normalized()
            if self._band is None:
                self._band = QGraphicsRectItem()
                c = QColor(theme.current().accent)
                c.setAlpha(40)
                self._band.setBrush(c)
                pen = QPen(QColor(theme.current().accent))
                pen.setCosmetic(True)
                self._band.setPen(pen)
                self.addItem(self._band, ignoreBounds=True)
            self._band.setRect(rect)
            if ev.isFinish():
                self._cancel_band()
                self._select(self.features_inside(rect, zones_only=zones_only), ev.modifiers())
            return True
        if self.mode == "lasso":
            ev.accept()
            if ev.isStart() or not self._lasso:
                start = vb.mapSceneToView(ev.buttonDownScenePos())
                self._lasso = [(start.x(), start.y())]
            self._lasso.append((p.x(), p.y()))
            if self._lasso_item is None:
                self._lasso_item = pg.PlotDataItem(pen=pg.mkPen(theme.current().accent, width=2,
                                                                style=Qt.PenStyle.DashLine))
                self.addItem(self._lasso_item, ignoreBounds=True)
            xs = [q[0] for q in self._lasso] + [self._lasso[0][0]]
            ys = [q[1] for q in self._lasso] + [self._lasso[0][1]]
            self._lasso_item.setData(xs, ys)
            if ev.isFinish():
                shape = QPolygonF([QPointF(x, y) for x, y in self._lasso])
                self._cancel_band()
                self._select(self.features_inside(shape, zones_only=zones_only), ev.modifiers())
            return True
        return False

    def select_lasso(self, points: list[tuple[float, float]], *, zones_only: bool = False, add: bool = False) -> None:
        """Select what lies inside the polygon *points* (view coordinates), as a lasso drag would."""
        shape = QPolygonF([QPointF(x, y) for x, y in points])
        mods = Qt.KeyboardModifier.ControlModifier if add else Qt.KeyboardModifier.NoModifier
        self._select(self.features_inside(shape, zones_only=zones_only), mods)

    def _cancel_band(self) -> None:
        if self._band is not None:
            self.removeItem(self._band)
            self._band = None
        if self._lasso_item is not None:
            self.removeItem(self._lasso_item)
            self._lasso_item = None
        self._lasso = []

    def _draw_draft(self) -> None:
        if self._draft_item is None:
            self._draft_item = pg.PlotDataItem(pen=pg.mkPen(theme.current().accent, width=2,
                                                            style=Qt.PenStyle.DashLine),
                                               symbol="o", symbolSize=7, symbolBrush=theme.current().accent)
            self.addItem(self._draft_item)
        xs = [p[0] for p in self._draft]
        ys = [p[1] for p in self._draft]
        self._draft_item.setData(xs, ys)

    def finish_polygon(self) -> None:
        pts = self._draft
        self._cancel_draft()
        if len(pts) >= 3:
            lon, lat = from_mercator([p[0] for p in pts], [p[1] for p in pts])
            self.polygonDrawn.emit([(float(a), float(b)) for a, b in zip(lon, lat)])
        self.set_mode("select")

    def _cancel_draft(self) -> None:
        if self._draft_item is not None:
            self.removeItem(self._draft_item)
            self._draft_item = None
        self._draft = []

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if self.mode == "draw" and ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish_polygon()
        elif ev.key() == Qt.Key.Key_Escape and self.mode in ("select", "lasso"):
            self._select([], Qt.KeyboardModifier.NoModifier)  # Esc clears the selection
        elif ev.key() == Qt.Key.Key_Escape:
            self.set_mode("select")
        else:
            super().keyPressEvent(ev)

    # ------------------------------------------------------------------ chart interface (toolbar tools)

    def auto_range(self) -> None:
        """Fit all features (the toolbar's Fit all)."""
        self.zoom_to()

    def set_auto_y(self, _on: bool) -> None:
        """Not applicable to a map (kept for the toolbar's chart interface)."""

    def export_png(self, path: str, width: int = 2000) -> None:
        img = self.grab()
        if img.width() and img.width() < width:
            img = img.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        img.save(path)

    def _mouse_moved(self, pos) -> None:
        if self.sceneBoundingRect().contains(pos):
            p = self.vb.mapSceneToView(pos)
            self.cursorMoved.emit(float(p.x()), float(p.y()))
        else:
            self.cursorMoved.emit(float("nan"), float("nan"))

    def format_cursor(self, x: float, y: float) -> str:
        """Status-bar readout: latitude and longitude under the mouse, and the selection size."""
        lon, lat = from_mercator(x, y)
        ns = "N" if lat >= 0 else "S"
        ew = "E" if lon >= 0 else "W"
        sel = f"   {len(self.selection)} selected" if self.selection else ""
        return f"{abs(float(lat)):.5f}° {ns}, {abs(float(lon)):.5f}° {ew}{sel}"

    # ------------------------------------------------------------------ view

    def zoom_to(self, iris: list[str] | None = None) -> None:
        """Fit the view to *iris* (all located features when ``None`` or empty)."""
        pts = []
        for iri, f in self.features.items():
            if iris and iri not in iris:
                continue
            pts += geometry_points(f.geometry)
        if not pts:
            return
        xs, ys = to_mercator([p[0] for p in pts], [p[1] for p in pts])
        x0, x1, y0, y1 = float(np.min(xs)), float(np.max(xs)), float(np.min(ys)), float(np.max(ys))
        pad = max(x1 - x0, y1 - y0, 400.0) * 0.15
        self.vb.setRange(QRectF(x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad), padding=0)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        if "scale_bar" in self.__dict__:  # the base class resizes during its own construction
            self._place_overlays()

    def _place_overlays(self) -> None:
        h = self.height()
        self.scale_bar.move(6, h - self.scale_bar.height() - 4)
        self.attribution.adjustSize()
        self.attribution.move(self.width() - self.attribution.width() - 8, h - self.attribution.height() - 4)
        self.empty_hint.setFixedWidth(max(200, self.width() - 40))
        self.empty_hint.adjustSize()
        self.empty_hint.move(12, 8)
        self._update_scale()

    def _update_scale(self) -> None:
        (x0, x1), (y0, y1) = self.vb.viewRange()
        width = max(1.0, self.vb.width())
        self.scale_bar.set_scale((x1 - x0) / width * ground_scale((y0 + y1) / 2))

    # ------------------------------------------------------------------ basemap

    def set_basemap(self, enabled: bool, cache_dir=None, url: str | None = None, attribution: str = "",
                    user_agent: str = "sparsehydro-viewer") -> None:
        """Show (or remove) online tiles; nothing is requested unless *enabled*."""
        from .tile_layer import DEFAULT_URL, TileLayer

        if self.tiles is not None:
            self.tiles.remove()
            self.tiles = None
        self.attribution.setVisible(enabled)
        if enabled:
            self.tiles = TileLayer(self, cache_dir, url or DEFAULT_URL, user_agent)
            self.attribution.setText(attribution)
            self._place_overlays()


__all__ = ["MapFeature", "MapView"]
