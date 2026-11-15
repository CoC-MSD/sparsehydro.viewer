"""Toolbar for a :class:`TimeseriesPlot`: navigation modes, period selection and export."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QFileDialog, QToolBar, QToolButton, QWidget

from ..resources import icon
from .timeseries_plot import PERIOD_COLORS, PERIOD_LABELS, TimeseriesPlot

PERIOD_KEYS = ("calibration", "validation")


class ChartToolbar(QToolBar):
    """Interaction toolbar (icons with tooltips; shortcuts work while the chart has focus).

    Navigation (always): Pan, Zoom box, Fit all, Auto Y, Export PNG.
    With ``periods=True`` also: drag-select the calibration or validation
    period, zoom to either, set calibration to the visible range, clear.

    The toolbar does not own the periods: it emits :attr:`periodEdited`
    (key, t0, t1) or :attr:`periodCleared` (key), the owner writes them to the
    session, and the session pushes them back to the plot through
    :meth:`TimeseriesPlot.set_period`.  Region drags on the plot are forwarded
    the same way.
    """

    periodEdited = Signal(str, float, float)
    periodCleared = Signal(str)

    def __init__(self, plot: TimeseriesPlot, parent: QWidget | None = None, *, periods: bool = False) -> None:
        super().__init__(parent)
        self.plot = plot
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setIconSize(QSize(20, 20))
        self._pending_period: str | None = None

        self.modes = QActionGroup(self)
        self.modes.setExclusive(True)
        self.pan = self._mode_action("Pan", "pan", "P", "Pan: drag to move along time; mouse wheel zooms", "pan")
        self.zoom = self._mode_action("Zoom box", "zoom", "Z", "Zoom box: drag a rectangle to zoom in", "zoom-box")
        self.select: dict[str, QAction] = {}
        if periods:
            for key in PERIOD_KEYS:
                label = PERIOD_LABELS[key]
                act = self._mode_action(
                    f"Select {label.lower()}", "select", label[0],
                    f"Select {label.lower()} period: drag across the chart. Afterwards drag the shaded "
                    "region or its edges to adjust it.", "select-range", PERIOD_COLORS[key])
                act.setData(key)
                self.select[key] = act
        self.pan.setChecked(True)
        self.addSeparator()
        self._action("Fit all", self.plot.auto_range, "F", "Fit all: show the whole record", "fit-all")
        self.zoom_to: dict[str, QAction] = {}
        if periods:
            for key in PERIOD_KEYS:
                self.zoom_to[key] = self._action(
                    f"Zoom to {PERIOD_LABELS[key].lower()}", lambda k=key: self._zoom_period(k), None,
                    f"Zoom to the {PERIOD_LABELS[key].lower()} period", "zoom-period", PERIOD_COLORS[key])
            self._action("Visible → calibration", self._visible_to_calibration, None,
                         "Set the calibration period to the visible time range", "visible-to-period",
                         PERIOD_COLORS["calibration"])
            clear = QToolButton(self)
            clear.setIcon(icon("clear"))
            clear.setToolTip("Clear a period")
            clear.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            for key in PERIOD_KEYS:
                a = QAction(icon("select-range", PERIOD_COLORS[key]), f"Clear {PERIOD_LABELS[key].lower()} period",
                            clear)
                a.triggered.connect(lambda _=False, k=key: self.periodCleared.emit(k))
                clear.addAction(a)
            self.addWidget(clear)
        self.addSeparator()
        self.auto_y = self._action("Auto Y", self.plot.set_auto_y, None,
                                   "Auto Y: rescale the flow axis to the visible data (off: zoom y freely)", "auto-y")
        self.auto_y.setCheckable(True)
        self.auto_y.setChecked(True)
        self._action("Export PNG...", self._export, None, "Export the chart as a PNG image", "export")

        plot.rangeSelected.connect(self._range_selected)
        plot.periodChanged.connect(self.periodEdited)
        plot.modeChanged.connect(self._mode_changed)

    # ------------------------------------------------------------------ helpers

    def _register_shortcut(self, act: QAction, key: str | None) -> None:
        if key:
            act.setShortcut(QKeySequence(key))
            act.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            self.plot.addAction(act)  # active while the chart has focus
            act.setToolTip(f"{act.toolTip()}  [{key}]")

    def _mode_action(self, text: str, mode: str, key: str | None, tip: str, icon_name: str,
                     color: str | None = None) -> QAction:
        act = QAction(icon(icon_name, color), text, self)
        act.setCheckable(True)
        act.setToolTip(tip)
        act.triggered.connect(lambda _=False, a=act, m=mode: self._activate(a, m))
        self.modes.addAction(act)
        self.addAction(act)
        self._register_shortcut(act, key)
        return act

    def _action(self, text: str, slot, key: str | None, tip: str, icon_name: str,
                color: str | None = None) -> QAction:
        act = QAction(icon(icon_name, color), text, self)
        act.setToolTip(tip)
        act.triggered.connect(slot)
        self.addAction(act)
        self._register_shortcut(act, key)
        return act

    # ------------------------------------------------------------------ behaviour

    def _activate(self, act: QAction, mode: str) -> None:
        act.setChecked(True)
        self._pending_period = act.data() if mode == "select" else None
        self.plot.set_mode(mode)

    def _mode_changed(self, mode: str) -> None:
        if mode == "pan" and not self.pan.isChecked():
            self.pan.setChecked(True)

    def _range_selected(self, t0: float, t1: float) -> None:
        key = self._pending_period
        if key is not None:
            self.periodEdited.emit(key, t0, t1)
        # One selection per click of the tool: go back to panning so a stray drag cannot reset it.
        self._activate(self.pan, "pan")

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

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export chart", "chart.png", "PNG image (*.png)")
        if path:
            self.plot.export_png(path)
