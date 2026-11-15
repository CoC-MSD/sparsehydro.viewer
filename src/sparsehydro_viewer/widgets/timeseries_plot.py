"""Rain-over-flow time series plot with linked axes and overlays."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from .. import theme


def _pen(color: str, width: float = 1.5, style: Qt.PenStyle = Qt.PenStyle.SolidLine) -> pg.QtGui.QPen:
    p = pg.mkPen(color, width=width)
    p.setStyle(style)
    p.setCosmetic(True)
    return p


#: Interaction modes of :meth:`TimeseriesPlot.set_mode`.
MODES = ("pan", "zoom", "select")

#: Colours of the period regions (fill alpha is applied separately).
PERIOD_COLORS = {"calibration": "#0b6bcb", "validation": "#E69F00"}
PERIOD_LABELS = {"calibration": "Calibration", "validation": "Validation"}


class _TimeViewBox(pg.ViewBox):
    """ViewBox whose left-drag can be redirected to a range-selection handler."""

    def __init__(self) -> None:
        super().__init__()
        self.drag_handler = None  # callable(x0, x1, finished) or None

    def mouseDragEvent(self, ev, axis=None) -> None:  # noqa: N802 (Qt naming)
        if self.drag_handler is not None and ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            x0 = self.mapSceneToView(ev.buttonDownScenePos()).x()
            x1 = self.mapSceneToView(ev.scenePos()).x()
            self.drag_handler(min(x0, x1), max(x0, x1), ev.isFinish())
            return
        super().mouseDragEvent(ev, axis)


class TimeseriesPlot(pg.GraphicsLayoutWidget):
    """Hyetograph (inverted, top) above a flow panel sharing the time axis.

    Time is passed as float seconds since the epoch (see
    :func:`sparsehydro_viewer.core.data.epoch_seconds`).

    Interaction modes (:meth:`set_mode`): ``"pan"`` drags along time,
    ``"zoom"`` drags a box to zoom, ``"select"`` drags a time range and emits
    :attr:`rangeSelected`.  Period regions (:meth:`set_period`) are draggable
    and emit :attr:`periodChanged` when moved or resized.
    """

    regionChanged = Signal(float, float)
    rangeSelected = Signal(float, float)
    periodChanged = Signal(str, float, float)
    modeChanged = Signal(str)

    def __init__(self, parent=None, *, rain: bool = True, flow_label: str = "Flow [cfs]") -> None:
        super().__init__(parent)
        t = theme.current()
        self.setBackground(t.plot_bg)
        self.ci.setSpacing(0)
        self.rain_plot: pg.PlotItem | None = None
        self._mode = "pan"
        self._preview: list[pg.LinearRegionItem] = []
        self._periods: dict[str, pg.LinearRegionItem] = {}
        self._period_mirrors: dict[str, pg.LinearRegionItem] = {}
        self.auto_y = True
        if rain:
            self.rain_plot = self.addPlot(row=0, col=0, viewBox=_TimeViewBox(),
                                          axisItems={"bottom": pg.DateAxisItem(utcOffset=0)})
            self.rain_plot.invertY(True)
            self.rain_plot.setLabel("left", "Rain [in]")
            self.rain_plot.hideAxis("bottom")
            self.rain_plot.setMaximumHeight(130)
            self.rain_plot.setMouseEnabled(x=True, y=False)
            self.rain_plot.getAxis("left").setWidth(60)
        # Naive timestamps are passed as UTC seconds; offset 0 shows them as recorded.
        self.flow_plot: pg.PlotItem = self.addPlot(row=1, col=0, viewBox=_TimeViewBox(),
                                                   axisItems={"bottom": pg.DateAxisItem(utcOffset=0)})
        self.flow_plot.setLabel("left", flow_label)
        self.flow_plot.getAxis("left").setWidth(60)
        self.flow_plot.showGrid(x=True, y=True, alpha=0.15)
        self.flow_plot.setMouseEnabled(x=True, y=False)
        if self.rain_plot is not None:
            self.rain_plot.setXLink(self.flow_plot)
        self.legend = self.flow_plot.addLegend(offset=(-10, 10), labelTextColor=t.plot_fg)
        for p in self._plots():
            theme.plain_axes(p)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode="peak")
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._bands: dict[str, pg.FillBetweenItem] = {}
        self._spans: list[pg.LinearRegionItem] = []
        self._region: pg.LinearRegionItem | None = None
        self._rain_item: pg.PlotDataItem | None = None
        self._obs_item: pg.PlotDataItem | None = None
        self._t: np.ndarray | None = None

    def _plots(self) -> list[pg.PlotItem]:
        return [p for p in (self.rain_plot, self.flow_plot) if p is not None]

    # ------------------------------------------------------------------ data

    def set_data(self, t: np.ndarray, rain: np.ndarray | None, observed: np.ndarray | None,
                 observed_label: str = "Observed") -> None:
        th = theme.current()
        self._t = np.asarray(t, dtype=float)
        if self.rain_plot is not None:
            if self._rain_item is not None:
                self.rain_plot.removeItem(self._rain_item)
                self._rain_item = None
            if rain is not None:
                fill = QColor(th.rain)
                fill.setAlpha(170)
                self._rain_item = self.rain_plot.plot(self._t, np.asarray(rain, float), pen=_pen(th.rain, 1.0),
                                                      fillLevel=0.0, brush=fill)
        if self._obs_item is not None:
            self.flow_plot.removeItem(self._obs_item)
            self.legend.removeItem(self._obs_item)
            self._obs_item = None
        if observed is not None:
            self._obs_item = self.flow_plot.plot(self._t, np.asarray(observed, float), pen=_pen(th.observed, 1.2),
                                                 name=observed_label)
        self.auto_range()

    def set_curve(self, key: str, t: np.ndarray | None, y: np.ndarray | None, *, color: str, width: float = 1.6,
                  dashed: bool = False, name: str | None = None) -> None:
        """Add or replace an overlay; ``y=None`` removes it."""
        if y is None:
            self.remove_curve(key)
            return
        t = self._t if t is None else np.asarray(t, float)
        pen = _pen(color, width, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine)
        item = self._curves.get(key)
        if item is None:
            item = self.flow_plot.plot(t, np.asarray(y, float), pen=pen, name=name)
            self._curves[key] = item
        else:
            item.setData(t, np.asarray(y, float))
            item.setPen(pen)

    def set_markers(self, key: str, t: np.ndarray, y: np.ndarray, *, color: str, symbol: str = "t",
                    size: float = 11, name: str | None = None) -> None:
        """Add or replace a set of point markers (e.g. detected peaks)."""
        self.remove_curve(key)
        item = self.flow_plot.plot(np.asarray(t, float), np.asarray(y, float), pen=None, symbol=symbol,
                                   symbolSize=size, symbolBrush=color, symbolPen=pg.mkPen(theme.current().plot_bg),
                                   name=name)
        self._curves[key] = item

    def remove_curve(self, key: str) -> None:
        item = self._curves.pop(key, None)
        if item is not None:
            self.flow_plot.removeItem(item)
            self.legend.removeItem(item)

    def clear_curves(self) -> None:
        for k in list(self._curves):
            self.remove_curve(k)
        for k in list(self._bands):
            self.remove_band(k)

    def set_band(self, key: str, t: np.ndarray | None, lower: np.ndarray, upper: np.ndarray, color: str) -> None:
        self.remove_band(key)
        t = self._t if t is None else np.asarray(t, float)
        lo = pg.PlotDataItem(t, np.asarray(lower, float), pen=None)
        hi = pg.PlotDataItem(t, np.asarray(upper, float), pen=None)
        c = QColor(color)
        c.setAlpha(60)
        band = pg.FillBetweenItem(lo, hi, brush=c)
        band.setZValue(-5)
        # The fill's path starts empty at the origin; letting it into auto-range would stretch x back to 1970.
        self.flow_plot.addItem(band, ignoreBounds=True)
        self._bands[key] = band

    def remove_band(self, key: str) -> None:
        band = self._bands.pop(key, None)
        if band is not None:
            self.flow_plot.removeItem(band)

    def set_spans(self, spans: list[tuple[float, float] | tuple[float, float, str]], color: str | None = None) -> None:
        """Shade time spans (events, periods) on every panel; a span may carry its own colour."""
        for s in self._spans:
            for p in self._plots():
                if s in p.items:
                    p.removeItem(s)
        self._spans = []
        default = color or theme.current().event_fill
        for span in spans:
            t0, t1 = span[0], span[1]
            brush = QColor(span[2] if len(span) > 2 else default)
            for p in self._plots():
                r = pg.LinearRegionItem((t0, t1), movable=False, brush=brush, pen=pg.mkPen(None))
                r.setZValue(-10)
                p.addItem(r)
                self._spans.append(r)

    # ------------------------------------------------------------------ interaction

    def enable_region(self, t0: float, t1: float) -> pg.LinearRegionItem:
        """Show a draggable region on the flow panel (emits :attr:`regionChanged`)."""
        if self._region is None:
            c = QColor(theme.current().accent)
            c.setAlpha(40)
            self._region = pg.LinearRegionItem((t0, t1), brush=c)
            self._region.setZValue(10)
            self._region.sigRegionChangeFinished.connect(
                lambda r: self.regionChanged.emit(*map(float, r.getRegion())))
            self.flow_plot.addItem(self._region)
        else:
            self._region.setRegion((t0, t1))
        return self._region

    def disable_region(self) -> None:
        if self._region is not None:
            self.flow_plot.removeItem(self._region)
            self._region = None

    # ------------------------------------------------------------------ interaction modes

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        """Switch between ``"pan"``, ``"zoom"`` (drag a box) and ``"select"`` (drag a time range)."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self._mode = mode
        for p in self._plots():
            vb: _TimeViewBox = p.getViewBox()
            vb.drag_handler = self._select_drag if mode == "select" else None
            vb.setMouseMode(pg.ViewBox.RectMode if mode == "zoom" else pg.ViewBox.PanMode)
        cursor = {"pan": Qt.CursorShape.OpenHandCursor, "zoom": Qt.CursorShape.CrossCursor,
                  "select": Qt.CursorShape.IBeamCursor}[mode]
        self.viewport().setCursor(cursor)
        self.modeChanged.emit(mode)

    def _select_drag(self, x0: float, x1: float, finished: bool) -> None:
        """Rubber-band a time range across both panels; emit it when the drag ends."""
        if not self._preview:
            c = QColor(theme.current().accent)
            c.setAlpha(50)
            for p in self._plots():
                r = pg.LinearRegionItem((x0, x1), movable=False, brush=c, pen=pg.mkPen(theme.current().accent))
                r.setZValue(20)
                p.addItem(r, ignoreBounds=True)
                self._preview.append(r)
        for r in self._preview:
            r.setRegion((x0, x1))
        if finished:
            for r, p in zip(self._preview, self._plots()):
                p.removeItem(r)
            self._preview = []
            if x1 > x0:
                self.rangeSelected.emit(float(x0), float(x1))

    # ------------------------------------------------------------------ period regions

    def set_period(self, key: str, t0: float | None, t1: float | None) -> None:
        """Show (or with ``None`` bounds, remove) a draggable, labelled period region."""
        if t0 is None or t1 is None:
            self.remove_period(key)
            return
        region = self._periods.get(key)
        if region is None:
            color = PERIOD_COLORS.get(key, theme.current().accent)
            fill = QColor(color)
            fill.setAlpha(38)
            hover = QColor(color)
            hover.setAlpha(70)
            region = pg.LinearRegionItem((t0, t1), brush=fill, hoverBrush=hover, pen=pg.mkPen(color, width=2),
                                         hoverPen=pg.mkPen(color, width=3), swapMode="block")
            region.setZValue(-8)
            pg.InfLineLabel(region.lines[0], text=PERIOD_LABELS.get(key, key), position=0.96,
                            anchor=(0, 1), color=color)
            region.sigRegionChangeFinished.connect(
                lambda r, k=key: self.periodChanged.emit(k, *map(float, r.getRegion())))
            region.sigRegionChanged.connect(lambda r, k=key: self._sync_mirror(k))
            self.flow_plot.addItem(region, ignoreBounds=True)
            self._periods[key] = region
            if self.rain_plot is not None:
                mirror = pg.LinearRegionItem((t0, t1), movable=False, brush=fill, pen=pg.mkPen(None))
                mirror.setZValue(-8)
                self.rain_plot.addItem(mirror, ignoreBounds=True)
                self._period_mirrors[key] = mirror
        region.blockSignals(True)
        region.setRegion((t0, t1))
        region.blockSignals(False)
        self._sync_mirror(key)

    def _sync_mirror(self, key: str) -> None:
        mirror = self._period_mirrors.get(key)
        if mirror is not None and key in self._periods:
            mirror.setRegion(self._periods[key].getRegion())

    def remove_period(self, key: str) -> None:
        region = self._periods.pop(key, None)
        if region is not None:
            self.flow_plot.removeItem(region)
        mirror = self._period_mirrors.pop(key, None)
        if mirror is not None and self.rain_plot is not None:
            self.rain_plot.removeItem(mirror)

    def period(self, key: str) -> tuple[float, float] | None:
        r = self._periods.get(key)
        return None if r is None else tuple(map(float, r.getRegion()))  # type: ignore[return-value]

    # ------------------------------------------------------------------ view

    def x_range(self) -> tuple[float, float]:
        (x0, x1), _ = self.flow_plot.viewRange()
        return float(x0), float(x1)

    def data_range(self) -> tuple[float, float] | None:
        if self._t is None or not len(self._t):
            return None
        return float(self._t[0]), float(self._t[-1])

    def zoom_to(self, t0: float, t1: float) -> None:
        self.flow_plot.setXRange(t0, t1, padding=0.02)
        self._fit_y()

    def auto_range(self) -> None:
        self.flow_plot.enableAutoRange(axis="x")
        self._fit_y()

    def set_auto_y(self, on: bool) -> None:
        """Rescale y to the visible data whenever x changes (on), or keep y fixed and allow y zoom (off)."""
        self.auto_y = on
        for p in self._plots():
            p.setMouseEnabled(x=True, y=not on)
            if on:
                p.enableAutoRange(axis="y")
                p.setAutoVisible(y=True)
            else:
                p.disableAutoRange(axis="y")

    def _fit_y(self) -> None:
        if not self.auto_y:
            return
        for p in self._plots():
            p.enableAutoRange(axis="y")
            p.setAutoVisible(y=True)

    def export_png(self, path: str, width: int = 2000) -> None:
        """Save the plot (both panels) as a PNG image."""
        from pyqtgraph.exporters import ImageExporter

        exporter = ImageExporter(self.ci)
        exporter.parameters()["width"] = width
        exporter.export(path)
