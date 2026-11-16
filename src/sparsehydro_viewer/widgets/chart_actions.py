"""Chart actions shared by the application toolbar.

:class:`ChartActions` is one set of navigation actions (pan, zoom box, fit,
auto Y, export) that is re-bound to whichever :class:`TimeseriesPlot` the
current page reports as active, so every page uses the same toolbar buttons.

:class:`PeriodActions` are the calibration/validation period tools of one
plot; a page offers them as contextual toolbar actions.  They do not own the
periods: they emit :attr:`PeriodActions.periodEdited` /
:attr:`PeriodActions.periodCleared`, the page writes the session, and the
session pushes the result back with :meth:`TimeseriesPlot.set_period`.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMenu, QWidget

from ..resources import icon
from .timeseries_plot import PERIOD_COLORS, PERIOD_LABELS, TimeseriesPlot

PERIOD_KEYS = ("calibration", "validation")


def _action(parent: QObject, text: str, tip: str, icon_name: str, color: str | None = None,
            shortcut: str | None = None, checkable: bool = False) -> QAction:
    act = QAction(icon(icon_name, color), text, parent)
    act.setToolTip(f"{tip}  [{shortcut}]" if shortcut else tip)
    act.setStatusTip(tip)
    act.setCheckable(checkable)
    if shortcut:
        act.setShortcut(QKeySequence(shortcut))
    return act


class ChartActions(QObject):
    """Navigation actions bound to the active chart (or disabled when there is none)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._window = parent
        self.plot: TimeseriesPlot | None = None
        self.pan = _action(self, "Pan", "Pan: drag to move along time; the mouse wheel zooms", "pan",
                           shortcut="P", checkable=True)
        self.zoom = _action(self, "Zoom box", "Zoom box: drag a rectangle to zoom in", "zoom-box",
                            shortcut="Z", checkable=True)
        self.fit = _action(self, "Fit all", "Fit all: show the whole record", "fit-all", shortcut="F")
        self.auto_y = _action(self, "Auto Y", "Auto Y: rescale the flow axis to the visible data "
                                              "(off: zoom y freely)", "auto-y", checkable=True)
        self.export = _action(self, "Export chart...", "Export the chart as a PNG image", "export")
        self.auto_y.setChecked(True)
        self.pan.setChecked(True)
        self.pan.triggered.connect(lambda: self._set_mode("pan"))
        self.zoom.triggered.connect(lambda: self._set_mode("zoom"))
        self.fit.triggered.connect(lambda: self.plot and self.plot.auto_range())
        self.auto_y.toggled.connect(lambda on: self.plot and self.plot.set_auto_y(on))
        self.export.triggered.connect(self._export)
        self.bind(None)

    def actions(self) -> list[QAction]:
        return [self.pan, self.zoom, self.fit, self.auto_y, self.export]

    def bind(self, plot: TimeseriesPlot | None) -> None:
        """Make the actions act on *plot* (``None`` disables them)."""
        if self.plot is not None:
            try:
                self.plot.modeChanged.disconnect(self._mode_changed)
            except (RuntimeError, TypeError):
                pass
        self.plot = plot
        for a in self.actions():
            a.setEnabled(plot is not None)
        # The map uses the same tools, but has no y axis to rescale.
        self.auto_y.setEnabled(plot is not None and getattr(plot, "supports_auto_y", True))
        if plot is not None:
            plot.modeChanged.connect(self._mode_changed)
            self._mode_changed(plot.mode)
            self.auto_y.blockSignals(True)
            self.auto_y.setChecked(plot.auto_y)
            self.auto_y.blockSignals(False)

    def _set_mode(self, mode: str) -> None:
        if self.plot is not None:
            self.plot.set_mode(mode)
        else:
            self._mode_changed("pan")

    def _mode_changed(self, mode: str) -> None:
        self.pan.setChecked(mode == "pan")
        self.zoom.setChecked(mode == "zoom")

    def _export(self) -> None:
        if self.plot is None:
            return
        path, _ = QFileDialog.getSaveFileName(self._window, "Export chart", "chart.png", "PNG image (*.png)")
        if path:
            self.plot.export_png(path)


class PeriodActions(QObject):
    """Calibration/validation period tools for one plot."""

    periodEdited = Signal(str, float, float)
    periodCleared = Signal(str)

    def __init__(self, plot: TimeseriesPlot, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.plot = plot
        self._pending: str | None = None
        self.select: dict[str, QAction] = {}
        self.zoom_to: dict[str, QAction] = {}
        for key in PERIOD_KEYS:
            label = PERIOD_LABELS[key]
            act = _action(self, f"Select {label.lower()}",
                          f"Select the {label.lower()} period: drag across the chart. Afterwards drag the "
                          "shaded region or its edges to adjust it.", "select-range", PERIOD_COLORS[key],
                          shortcut="C" if key == "calibration" else "V", checkable=True)
            act.triggered.connect(lambda checked=False, k=key: self._start_select(k, checked))
            self.select[key] = act
            z = _action(self, f"Zoom to {label.lower()}", f"Zoom the chart to the {label.lower()} period",
                        "zoom-period", PERIOD_COLORS[key])
            z.triggered.connect(lambda _=False, k=key: self._zoom_period(k))
            self.zoom_to[key] = z
        self.visible_to_calibration = _action(
            self, "Visible → calibration", "Set the calibration period to the visible time range",
            "visible-to-period", PERIOD_COLORS["calibration"])
        self.visible_to_calibration.triggered.connect(self._visible_to_calibration)
        self.clear = _action(self, "Clear period", "Clear the calibration or validation period", "clear")
        menu = QMenu()
        for key in PERIOD_KEYS:
            a = menu.addAction(icon("select-range", PERIOD_COLORS[key]), f"Clear {PERIOD_LABELS[key].lower()} period")
            a.triggered.connect(lambda _=False, k=key: self.periodCleared.emit(k))
        self.clear.setMenu(menu)  # the application toolbar shows it as an instant pop-up
        self._menu = menu  # QAction does not take ownership of its menu
        plot.rangeSelected.connect(self._range_selected)
        plot.periodChanged.connect(self.periodEdited)
        plot.modeChanged.connect(self._mode_changed)

    def actions(self) -> list[QAction | None]:
        """Actions for the toolbar (``None`` is a separator)."""
        return [self.select["calibration"], self.select["validation"], None,
                self.zoom_to["calibration"], self.zoom_to["validation"], self.visible_to_calibration, self.clear]

    def _start_select(self, key: str, checked: bool) -> None:
        if checked:
            self._pending = key
            for k, a in self.select.items():
                a.setChecked(k == key)
            self.plot.set_mode("select")
        else:
            self._pending = None
            self.plot.set_mode("pan")

    def _mode_changed(self, mode: str) -> None:
        if mode != "select":
            self._pending = None
            for a in self.select.values():
                a.setChecked(False)

    def _range_selected(self, t0: float, t1: float) -> None:
        key = self._pending
        # One selection per click of the tool: back to panning so a stray drag cannot reset it.
        self.plot.set_mode("pan")
        if key is not None:
            self.periodEdited.emit(key, t0, t1)

    def _zoom_period(self, key: str) -> None:
        r = self.plot.period(key)
        if r is not None:
            self.plot.zoom_to(*r)

    def _visible_to_calibration(self) -> None:
        x0, x1 = self.plot.x_range()
        dr = self.plot.data_range()
        if dr is not None:
            x0, x1 = max(x0, dr[0]), min(x1, dr[1])
        if x1 > x0:
            self.periodEdited.emit("calibration", x0, x1)


__all__ = ["PERIOD_KEYS", "ChartActions", "PeriodActions"]
