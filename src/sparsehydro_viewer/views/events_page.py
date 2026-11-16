"""Events workspace: storm events on the whole record, and fits of one or more model configurations.

The hydrograph always shows the whole record with the global events shaded;
choosing an event (list, Previous/Next, comparison table or a double-click on
its span) zooms the chart to it and "Show all" returns to the full record.
Each configuration (a unit hydrograph on rain, or the working model) is fitted
per event, pooled (one parameter set for every event), or both; their
predictions are overlaid (pooled dashed) and compared event by event.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.catalog import uh_label
from ..core.data import epoch_seconds
from ..core.events import MODES, EventAnalysis, EventConfig, EventOverrides, event_options, run_event_analysis
from ..core.uh import KernelCurve
from ..widgets import OptionForm, TimeseriesPlot
from ..widgets.legend import ToggleLegend
from .common import draw_working, num_item, page_header, text_item
from .context import AppContext
from .shell.page import Page

SORTS = {"Start time": ("start", False), "Total rain (largest first)": ("total_rain", True),
         "Peak flow (largest first)": ("peak_flow", True), "NSE (worst first)": ("nse", False)}
TAB_HYDROGRAPH, TAB_UH, TAB_WEIGHTS, TAB_COMPARE = range(4)
ALL_MODELS = "All models"


def config_color(index: int) -> str:
    """Colour of the configuration at *index* of the list: its hydrographs, unit hydrographs and table columns."""
    return theme.series_color(index)


def swatch(color: str, *, dashed: bool = False) -> QIcon:
    """A small line sample in *color* (dashed for pooled fits), for lists and table headers."""
    pm = QPixmap(22, 12)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setPen(pg.mkPen(QColor(color), width=3, style=Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
    painter.drawLine(1, 6, 21, 6)
    painter.end()
    return QIcon(pm)


def series_name(label: str, mode: str, component: str = "") -> str:
    """Name of a configuration's curve, the same in every chart, table and legend of the page."""
    return f"{label} ({MODES[mode]})" + (f": {component}" if component else "")


class EventsPage(Page):
    title = "Events"
    icon_name = "nav-events"
    primary_text = "Detect and fit"
    primary_tip = "Detect storm events and fit every listed model configuration (per event and/or pooled)"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        s = ctx.session
        self.options = OptionForm()
        self.options.set_specs(tuple(o for o in event_options() if o.name != "uh"))
        self.status = QLabel("Not run yet.")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        ob = QGroupBox("Detection and fitting")
        ol = QVBoxLayout(ob)
        ol.addWidget(self.options)
        ol.addWidget(self.status)

        # -- configurations --------------------------------------------------------
        self.configs = QTableWidget(0, 3)
        self.configs.setHorizontalHeaderLabels(["Model", "Per event", "Pooled"])
        self.configs.verticalHeader().setVisible(False)
        hh = self.configs.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.configs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.configs.setMaximumHeight(150)
        self.configs.setToolTip("Models fitted to the events. Per event: one parameter set per global event. "
                                "Pooled: one parameter set for all events. Double-click a name to rename it. "
                                "The colour beside a name is the colour of that model's hydrographs and unit "
                                "hydrographs (solid: per event, dashed: pooled).")
        self.configs.setAccessibleName("Model configurations to fit")
        self.configs.itemChanged.connect(self._configs_edited)
        self.uh_choice = QComboBox()
        rain_uhs = next(o for o in event_options() if o.name == "uh")  # UHs fitted directly on rain
        for k in rain_uhs.choices:
            self.uh_choice.addItem(uh_label(k), k)
        self.uh_choice.setCurrentIndex(max(self.uh_choice.findData(rain_uhs.default), 0))
        self.uh_choice.setToolTip("Unit hydrograph to add, fitted directly on rain with its own amplitude")
        add_uh = QPushButton("Add")
        add_uh.setToolTip("Add the chosen unit hydrograph as a configuration")
        add_uh.clicked.connect(self._add_uh)
        add_wm = QPushButton("Add working model")
        add_wm.setToolTip("Add the working model (its structure, bounds and current values as the start)")
        add_wm.clicked.connect(self._add_working_model)
        remove = QPushButton("Remove")
        remove.setToolTip("Remove the selected configurations")
        remove.clicked.connect(self._remove_configs)
        cb = QGroupBox("Models to fit")
        cl = QVBoxLayout(cb)
        cl.addWidget(self.configs)
        r = QHBoxLayout()
        r.addWidget(self.uh_choice, 1)
        r.addWidget(add_uh)
        cl.addLayout(r)
        r = QHBoxLayout()
        r.addWidget(add_wm)
        r.addWidget(remove)
        cl.addLayout(r)

        # -- events list -------------------------------------------------------------
        self.group = QComboBox()
        self.group.addItems(["All", "Season", "Quarter"])
        self.group.setToolTip("Group the events by season or quarter")
        self.filter = QComboBox()
        self.filter.setToolTip("Show only the events of this group")
        self.sort = QComboBox()
        self.sort.addItems(list(SORTS))
        self.sort.setToolTip("Order of the event list")
        self.group.currentIndexChanged.connect(self._group_changed)
        self.filter.currentIndexChanged.connect(self._fill_list)
        self.sort.currentIndexChanged.connect(self._fill_list)
        self.events = QListWidget()
        self.events.setAccessibleName("Global events")
        self.events.setToolTip("Select an event to zoom the charts to it")
        self.events.currentItemChanged.connect(lambda *_: self._show_event())
        self.events.currentItemChanged.connect(lambda *_: self.contextChanged.emit())
        self.prev_action = self.action("Previous event", "Zoom to the previous event in the list", "prev",
                                       lambda: self._step(-1), shortcut="Left")
        self.next_action = self.action("Next event", "Zoom to the next event in the list", "next",
                                       lambda: self._step(1), shortcut="Right")
        self.show_all_action = self.action("Show all", "Show the whole record", "fit-all", self._show_all,
                                           shortcut="Home")
        self.exclude_action = self.action("Exclude event", "Exclude the selected global event from fitting "
                                                           "(stored in the project) and refit", "exclude",
                                          self._exclude)
        self.restore_action = self.action("Restore excluded events", "Bring back all excluded events and refit",
                                          "restore", self._restore)
        self.send_action = self.action("Use as working model",
                                       "Make the selected configuration the working model with its fitted values "
                                       "(the pooled set, or the selected event's set when fitted per event only)",
                                       "load-sliders", self._send_to_working_model)
        eb = QGroupBox("Global events")
        el = QVBoxLayout(eb)
        r = QHBoxLayout()
        r.addWidget(self.group)
        r.addWidget(self.filter, 1)
        el.addLayout(r)
        el.addWidget(self.sort)
        el.addWidget(self.events, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(ob)
        ll.addWidget(cb)
        ll.addWidget(eb, 1)
        left.setMinimumWidth(300)
        left.setMaximumWidth(420)

        # -- views ---------------------------------------------------------------
        self.tabs = QTabWidget()
        self.fit_plot = TimeseriesPlot()
        self.fit_plot.setToolTip("Whole record with the global events shaded; double-click an event to zoom to it")
        self.fit_plot.flow_plot.scene().sigMouseClicked.connect(self._chart_clicked)
        self.uh_plot = pg.PlotWidget()
        self.uh_plot.setLabel("bottom", "Time since excess [h]")
        self.uh_plot.setLabel("left", "Ordinate [1/h]")
        self.uh_plot.showGrid(x=True, y=True, alpha=0.15)
        theme.plain_axes(self.uh_plot)
        self.uh_legend = self.uh_plot.addLegend(offset=(-10, 10), labelTextColor=theme.current().plot_fg)
        self.uh_toggle = ToggleLegend(self.uh_legend, self)  # click a legend symbol to hide or show a shape
        self.uh_model = QComboBox()
        self.uh_model.setAccessibleName("Model whose unit hydrographs are shown")
        self.uh_model.setToolTip("Show the unit hydrographs of every fitted model, or of one")
        self.uh_model.addItem(ALL_MODELS)
        self.uh_model.currentIndexChanged.connect(lambda *_: self._show_event())
        self.uh_note = QLabel()
        self.uh_note.setObjectName("hint")
        self.uh_note.setWordWrap(True)
        self.uh_stats = QTableWidget(0, 0)
        self.uh_stats.setAccessibleName("Unit hydrograph shape statistics by model")
        self.uh_stats.verticalHeader().setVisible(False)
        self.uh_stats.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.uh_stats.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        uh_top = QWidget()
        ut = QVBoxLayout(uh_top)
        ut.setContentsMargins(4, 4, 4, 0)
        r = QHBoxLayout()
        lab = QLabel("Model")
        lab.setBuddy(self.uh_model)
        r.addWidget(lab)
        r.addWidget(self.uh_model)
        r.addWidget(self.uh_note, 1)
        ut.addLayout(r)
        ut.addWidget(self.uh_plot, 1)
        self.uh_tab = QSplitter(Qt.Orientation.Vertical)
        self.uh_tab.addWidget(uh_top)
        self.uh_tab.addWidget(self.uh_stats)
        self.uh_tab.setStretchFactor(0, 4)
        self.uh_tab.setStretchFactor(1, 1)
        self.weight_plot = TimeseriesPlot(flow_label="Weight")
        self.compare = QTableWidget(0, 0)
        self.compare.verticalHeader().setVisible(False)
        self.compare.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.compare.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.compare.setAccessibleName("NSE of every configuration by event")
        self.compare.setToolTip("NSE over each global event's span; select a row to zoom to that event")
        self.compare.itemSelectionChanged.connect(self._compare_selected)
        self.tabs.addTab(self.fit_plot, "1  Hydrograph")
        self.tabs.addTab(self.uh_tab, "2  UH shapes")
        self.tabs.addTab(self.weight_plot, "3  Weights")
        self.tabs.addTab(self.compare, "4  Comparison")
        self.tabs.currentChanged.connect(lambda *_: self._show_event())
        self.tabs.currentChanged.connect(lambda *_: self.contextChanged.emit())  # active chart follows the tab
        self.fit_plot.flow_plot.setXLink(self.weight_plot.flow_plot)

        self.details = QTableWidget(0, 2)
        self.details.setHorizontalHeaderLabels(["Field", "Value"])
        self.details.verticalHeader().setVisible(False)
        self.details.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.details.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.details.setAccessibleName("Event details")
        db = QGroupBox("Event details")
        dl = QVBoxLayout(db)
        dl.addWidget(self.details)
        db.setMaximumWidth(340)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.addWidget(db)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Events", "Detect storm events and fit one or more models per event and pooled. "
                                            "←/→ move between events, Home shows the whole record, "
                                            "1-4 switch views."))
        lay.addWidget(split, 1)

        for i in range(4):
            sc = QShortcut(QKeySequence(str(i + 1)), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda i=i: self.tabs.setCurrentIndex(i))

        self.analysis: EventAnalysis | None = None
        self._table = pd.DataFrame()
        self._configs: list[EventConfig] = []
        self._zoomed = False
        self._kernels: dict[tuple[int, str, int | None], list[KernelCurve]] = {}  # of the current analysis
        s.projectChanged.connect(self._project_changed)
        s.datasetChanged.connect(self._dataset_changed)
        s.datasetChanged.connect(self.contextChanged)
        self._group_changed()
        self.watch_working_model()

    def working_model_changed(self, res) -> None:
        """The working model's hydrograph over the fitted configurations."""
        draw_working(self.fit_plot, res, self.ctx.session, show=self.analysis is not None)

    # ------------------------------------------------------------------ shell

    def primary(self) -> None:
        self.run_analysis()

    def primary_enabled(self) -> bool:
        return self.ctx.session.dataset is not None and not self.stop_enabled()

    def context_actions(self):
        return [self.prev_action, self.next_action, self.show_all_action, None, self.exclude_action,
                self.restore_action, None, self.send_action]

    def active_chart(self):
        return {TAB_HYDROGRAPH: self.fit_plot, TAB_WEIGHTS: self.weight_plot}.get(self.tabs.currentIndex())

    def status_text(self) -> str:
        gid = self._current_id()
        return f"event #{gid}" if gid is not None and self._zoomed else ""

    # ------------------------------------------------------------------ configurations

    @property
    def event_configs(self) -> list[EventConfig]:
        return list(self._configs)

    def set_configs(self, configs: list[EventConfig]) -> None:
        self._configs = list(configs)
        self.ctx.session.set_ui("event_configs", [c.to_dict() for c in self._configs])
        self._fill_configs()

    def _fill_configs(self) -> None:
        self.configs.blockSignals(True)
        self.configs.setRowCount(len(self._configs))
        for i, c in enumerate(self._configs):
            name = QTableWidgetItem(c.label)
            name.setIcon(swatch(config_color(i)))
            name.setToolTip(("Unit hydrograph on rain" if c.uh else "Composed model")
                            + "; drawn in this colour in every chart of the page")
            self.configs.setItem(i, 0, name)
            for col, on in ((1, c.per_event), (2, c.pooled)):
                it = QTableWidgetItem()
                it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                self.configs.setItem(i, col, it)
        self.configs.blockSignals(False)

    def _configs_edited(self, item: QTableWidgetItem) -> None:
        c = self._configs[item.row()]
        if item.column() == 0:
            c.label = item.text().strip() or c.label
        elif item.column() == 1:
            c.per_event = item.checkState() == Qt.CheckState.Checked
        else:
            c.pooled = item.checkState() == Qt.CheckState.Checked
        self.set_configs(self._configs)

    def _unique(self, label: str) -> str:
        names = {c.label for c in self._configs}
        out, i = label, 2
        while out in names:
            out, i = f"{label} ({i})", i + 1
        return out

    def _add_uh(self) -> None:
        key = self.uh_choice.currentData()
        if key:
            c = EventConfig.for_uh(key)
            c.label = self._unique(c.label)
            self.set_configs([*self._configs, c])

    def _add_working_model(self) -> None:
        s = self.ctx.session
        spec = s.working_spec()
        c = EventConfig(self._unique(spec.display_label or "Working model"), model=spec.to_dict())
        self.set_configs([*self._configs, c])

    def _remove_configs(self) -> None:
        rows = {i.row() for i in self.configs.selectedIndexes()}
        if rows:
            self.set_configs([c for i, c in enumerate(self._configs) if i not in rows])

    def _selected_config(self) -> int:
        rows = sorted({i.row() for i in self.configs.selectedIndexes()})
        return rows[0] if rows else 0

    def _send_to_working_model(self) -> None:
        a = self.analysis
        if a is None or not a.fits:
            QMessageBox.information(self, "Events", "Fit the events first.")
            return
        idx = self._selected_config()
        label = self._configs[idx].label if idx < len(self._configs) else None
        fit = next((f for f in a.fits if f.config.label == label), a.fits[0])
        values = fit.parameters("pooled") or fit.parameters("per_event", self._current_id())
        if not values:
            QMessageBox.information(self, "Events", f"{fit.config.label} has no fitted values for this event.")
            return
        self.ctx.session.set_model(fit.config.model_spec(), values)
        self.status.setText(f"Working model: {fit.config.label} with its fitted values.")

    # ------------------------------------------------------------------ overrides

    def _overrides(self) -> EventOverrides:
        name = self.ctx.session.dataset_name or ""
        return EventOverrides.from_dict(self.ctx.session.ui("event_overrides", {}).get(name))

    def _save_overrides(self, ov: EventOverrides) -> None:
        name = self.ctx.session.dataset_name or ""
        all_ov = dict(self.ctx.session.ui("event_overrides", {}))
        all_ov[name] = ov.to_dict()
        self.ctx.session.set_ui("event_overrides", all_ov)

    def _exclude(self) -> None:
        gid = self._current_id()
        if gid is None:
            return
        ov = self._overrides()
        if gid not in ov.deleted_global_ids:
            ov.deleted_global_ids.append(gid)
            self._save_overrides(ov)
            self.run_analysis()

    def _restore(self) -> None:
        ov = self._overrides()
        if ov.deleted_global_ids:
            ov.deleted_global_ids.clear()
            self._save_overrides(ov)
            self.run_analysis()

    # ------------------------------------------------------------------ analysis

    def _project_changed(self) -> None:
        s = self.ctx.session
        self.options.set_values(s.ui("event_options", {}))
        self._configs = [EventConfig.from_dict(d) for d in s.ui("event_configs", [])]
        self._fill_configs()
        self._dataset_changed()

    def _dataset_changed(self) -> None:
        self.analysis = None
        self._kernels.clear()
        self._fill_uh_models()
        self.uh_plot.clear()
        self.uh_legend.clear()
        self.uh_toggle.clear()
        self.uh_stats.setRowCount(0)
        self._table = pd.DataFrame()
        self.events.clear()
        self.compare.setRowCount(0)
        self.status.setText("Not run yet for this dataset.")

    def run_analysis(self) -> None:
        s = self.ctx.session
        frame = s.frame()
        if frame is None:
            QMessageBox.information(self, "Events", "Load a dataset first.")
            return
        if not self._configs:
            self._add_uh()
        configs = [EventConfig.from_dict(c.to_dict()) for c in self._configs if c.per_event or c.pooled]
        if not configs:
            QMessageBox.information(self, "Events", "Tick Per event or Pooled for at least one model.")
            return
        opts = self.options.values()
        s.set_ui("event_options", opts)
        ov = self._overrides()
        self.status.setText("Detecting events and fitting...")

        def work(ctx):
            def progress(i: int, n: int, text: str) -> None:
                ctx.progress(text, i / n if n else None)

            return run_event_analysis(frame, opts, ov, should_stop=ctx.token, progress=progress, configs=configs)

        def done(a: EventAnalysis) -> None:
            self.analysis = a
            self._kernels.clear()
            self._fill_uh_models()
            self._table = a.event_table()
            n_ex = len(ov.deleted_global_ids)
            errors = [f"{f.config.label}: {f.error}" for f in a.fits if f.error]
            self.status.setText(f"{len(a.global_events)} global events, {len(a.sub_events)} sub-events, "
                                f"{len(a.fits) - len(errors)} of {len(a.fits)} models fitted"
                                + (f"; {n_ex} excluded" if n_ex else "")
                                + ("\nFailed: " + "; ".join(errors) if errors else ""))
            self._draw_record()
            self._fill_compare()
            self._fill_list()

        def failed(msg: str) -> None:
            self.status.setText(f"Failed: {msg}")

        self.submit_job("Detect and fit events", work, on_done=done, on_error=failed)

    # ------------------------------------------------------------------ list

    def _group_changed(self) -> None:
        mode = self.group.currentText()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("All")
        if mode == "Season":
            self.filter.addItems(["Winter", "Spring", "Summer", "Fall"])
        elif mode == "Quarter":
            self.filter.addItems(["Q1", "Q2", "Q3", "Q4"])
        self.filter.setEnabled(mode != "All")
        self.filter.blockSignals(False)
        self._fill_list()

    def _fill_list(self) -> None:
        t = self._table
        current = self._current_id()
        self.events.blockSignals(True)
        self.events.clear()
        if t.empty:
            self.events.blockSignals(False)
            return
        f = self.filter.currentText()
        if self.group.currentText() == "Season" and f != "All":
            t = t[t["season"] == f]
        elif self.group.currentText() == "Quarter" and f != "All":
            t = t[t["quarter"] == f]
        col, desc = SORTS[self.sort.currentText()]
        t = t.sort_values(col, ascending=not desc, na_position="last", kind="stable")
        for _, row in t.iterrows():
            nse = "" if pd.isna(row["nse"]) else f"  NSE {row['nse']:.2f}"
            it = QListWidgetItem(f"#{row['global_id']}  {row['start']:%Y-%m-%d %H:%M}  "
                                 f"{row['total_rain']:.2f} in{nse}")
            it.setData(Qt.ItemDataRole.UserRole, int(row["global_id"]))
            if not row["fitted"]:
                it.setForeground(Qt.GlobalColor.gray)
                it.setToolTip("Not fitted per event")
            self.events.addItem(it)
        self.events.blockSignals(False)
        for i in range(self.events.count()):
            if self.events.item(i).data(Qt.ItemDataRole.UserRole) == current:
                self.events.setCurrentRow(i)
                break

    def _current_id(self) -> int | None:
        it = self.events.currentItem()
        return None if it is None else int(it.data(Qt.ItemDataRole.UserRole))

    def select_event(self, gid: int) -> None:
        for i in range(self.events.count()):
            if self.events.item(i).data(Qt.ItemDataRole.UserRole) == gid:
                if self.events.currentRow() == i:
                    self._show_event()
                else:
                    self.events.setCurrentRow(i)
                return

    def _step(self, d: int) -> None:
        n = self.events.count()
        if n:
            row = self.events.currentRow()
            self.events.setCurrentRow(0 if row < 0 and d > 0 else min(max(row + d, 0), n - 1))
            if not self._zoomed:
                self._show_event()

    def _show_all(self) -> None:
        self._zoomed = False
        if self.analysis is not None:
            self._draw_spans()
            full = self.fit_plot.data_range()
            if full is not None:
                self.fit_plot.zoom_to(*full)
        self.contextChanged.emit()

    def _chart_clicked(self, ev) -> None:
        a = self.analysis
        if a is None or not ev.double():
            return
        vb = self.fit_plot.flow_plot.vb
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        x = pd.Timestamp(vb.mapSceneToView(ev.scenePos()).x(), unit="s")
        for g in a.global_events:
            if pd.Timestamp(g.window_start_datetime) <= x <= pd.Timestamp(g.window_end_datetime):
                self.select_event(int(g.global_id))
                return

    def _compare_selected(self) -> None:
        rows = {i.row() for i in self.compare.selectedIndexes()}
        if len(rows) != 1:
            return
        it = self.compare.item(rows.pop(), 0)
        gid = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
        if gid is not None:
            self.select_event(int(gid))

    # ------------------------------------------------------------------ views

    def _draw_record(self) -> None:
        """Draw the whole record once per analysis: data, smoothing, every fit, peaks, weights."""
        a = self.analysis
        th = theme.current()
        d = a.data
        t = epoch_seconds(d["datetime"])
        self._zoomed = False
        self.fit_plot.clear_curves()
        self.fit_plot.set_data(t, d["rain"].to_numpy(), d["stormflow"].to_numpy(), "Observed storm flow")
        sg_t = pd.to_datetime(pd.Series(a.savgol.datetime))
        self.fit_plot.set_curve("savgol", epoch_seconds(sg_t), np.asarray(a.savgol.smoothed), color=th.muted,
                                width=1.2, name="Smoothed (variable SavGol)")
        i = 0
        for fit in a.fits:
            for mode in fit.config.modes:
                pred = fit.predicted(mode)
                if pred is None:
                    continue
                self.fit_plot.set_curve(f"fit:{fit.config.label}:{mode}", epoch_seconds(pred["datetime"]),
                                        pred["Q_pred"].to_numpy(), color=config_color(i), width=1.8,
                                        dashed=mode == "pooled", name=series_name(fit.config.label, mode))
            i += 1
        primary = [s for s in a.sub_events if not s.is_bimodal]
        bimodal = [s for s in a.sub_events if s.is_bimodal]
        if primary:
            self.fit_plot.set_markers("peaks", epoch_seconds([s.peak_datetime for s in primary]),
                                      [s.peak_flow for s in primary], color="#D55E00", symbol="star", size=12,
                                      name="Peaks")
        if bimodal:
            self.fit_plot.set_markers("bimodal", epoch_seconds([s.peak_datetime for s in bimodal]),
                                      [s.peak_flow for s in bimodal], color="#E69F00", symbol="t",
                                      name="Bimodal peaks")
        w = a.weights()
        pw, tw = a.options["peak_weight"], a.options["tail_weight"]
        self.weight_plot.clear_curves()
        self.weight_plot.set_data(t, d["rain"].to_numpy(), None)
        self.weight_plot.set_curve("w", t, w, color=th.accent, width=1.6, name="Fit weight")
        flow = d["stormflow"].to_numpy(float)
        peak = np.nanmax(flow) if len(flow) else 0.0
        if peak > 0:
            self.weight_plot.set_curve("flow", t, flow / peak * max(pw, tw, 1.0), color=th.observed, width=1,
                                       dashed=True, name="Storm flow (scaled)")
        self.working_model_changed(self.ctx.controller.last)
        self._draw_spans()

    def _draw_spans(self) -> None:
        a = self.analysis
        if a is None:
            return
        cur = self._current_id() if self._zoomed else None
        highlight = pg.mkColor(theme.current().accent)
        highlight.setAlpha(60)
        spans = []
        for g in a.global_events:
            t0, t1 = epoch_seconds([g.start_datetime, g.end_datetime])
            spans.append((t0, t1, highlight.name(pg.QtGui.QColor.NameFormat.HexArgb))
                         if int(g.global_id) == cur else (t0, t1))
        for plot in (self.fit_plot, self.weight_plot):
            plot.set_spans(spans)

    def _show_event(self) -> None:
        a = self.analysis
        if a is None:
            return
        gid = self._current_id()
        self._fill_details(gid)
        view = self.tabs.currentIndex()
        if view == TAB_UH:
            self._show_uh(a, gid)
        if gid is None:
            return
        self._zoomed = True
        self._draw_spans()
        w0, w1 = a.window(gid)
        t0, t1 = epoch_seconds([w0, w1])
        self.fit_plot.zoom_to(t0, t1)
        self.contextChanged.emit()

    def _fill_uh_models(self) -> None:
        """Offer every fitted configuration in the UH tab's model selector, keeping the choice."""
        a = self.analysis
        current = self.uh_model.currentText()
        self.uh_model.blockSignals(True)
        self.uh_model.clear()
        self.uh_model.addItem(ALL_MODELS)
        for i, fit in enumerate(a.fits if a is not None else []):
            if not fit.error:
                self.uh_model.addItem(swatch(config_color(i)), fit.config.label)
        self.uh_model.setCurrentIndex(max(self.uh_model.findText(current), 0))
        self.uh_model.blockSignals(False)

    def _kernel(self, a: EventAnalysis, index: int, mode: str, gid: int | None) -> list[KernelCurve]:
        key = (index, mode, None if mode == "pooled" else gid)
        if key not in self._kernels:
            try:
                self._kernels[key] = a.fits[index].kernels(mode, gid, a.dt_hours)
            except Exception:  # noqa: BLE001 - a model whose shapes cannot be built is listed as having none
                self._kernels[key] = []
        return self._kernels[key]

    def _show_uh(self, a: EventAnalysis, gid: int | None) -> None:
        """Unit hydrographs of every fitted model: one colour per model (as in the hydrograph), solid for the
        per-event fit of the current event and dashed for the pooled fit; a model's other events are faint
        lines of its colour. The legend and the table name the model, the fit and the component."""
        self.uh_plot.clear()
        self.uh_legend.clear()
        self.uh_toggle.clear()
        chosen = self.uh_model.currentText()
        horizon = 2.0
        rows: list[tuple[str, str, str, str, bool, KernelCurve]] = []  # model, fit, component, colour, dashed
        without: list[str] = []
        for i, fit in enumerate(a.fits):
            if fit.error or (chosen != ALL_MODELS and fit.config.label != chosen):
                continue
            color = config_color(i)
            drew = False
            for mode in fit.config.modes:
                dashed = mode == "pooled"
                style = Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine
                faint = []
                if mode == "per_event":  # the same model's other events, behind
                    col = pg.mkColor(color)
                    col.setAlpha(70)
                    for other in fit.event_ids():
                        if other == gid:
                            continue
                        for c in _main(self._kernel(a, i, mode, other)):
                            faint.append(self.uh_plot.plot(np.r_[0, c.t_hours], np.r_[0, c.ordinates],
                                                           pen=pg.mkPen(col, width=1)))
                            if gid is None:
                                horizon = max(horizon, c.time_to_mass(0.995))
                curves = self._kernel(a, i, mode, gid) if (dashed or gid is not None) else []
                multi = len(curves) > 1
                totals: dict[str, float] = {}
                for c in curves:
                    if c.group and not c.label.endswith("combined"):
                        totals[c.group] = totals.get(c.group, 0.0) + c.weight
                first = True
                for c in curves:
                    member = multi and bool(c.group) and not c.label.endswith("combined")
                    # Members of an RDII group are drawn as their share of the combined curve, so they add up.
                    y = c.ordinates * c.weight / (totals.get(c.group) or 1.0) if member else c.ordinates
                    name = series_name(fit.config.label, mode, c.label)
                    item = self.uh_plot.plot(np.r_[0, c.t_hours], np.r_[0, y], name=name,
                                             pen=pg.mkPen(color, width=1.4 if member else 2.6, style=style))
                    item.setZValue(10)
                    self.uh_toggle.register(name, item, *(faint if first else []))
                    first = False
                    horizon = max(horizon, c.time_to_mass(0.995))
                    rows.append((fit.config.label, MODES[mode], c.label, color, dashed, c))
                if not curves and faint:  # no event chosen: the faint lines are the model's entry
                    name = f"{fit.config.label} ({MODES[mode]}): all events"
                    self.uh_legend.addItem(faint[0], name)
                    self.uh_toggle.register(name, *faint)
                drew = drew or bool(curves) or bool(faint)
            if not drew:
                without.append(fit.config.label)
        self.uh_plot.setXRange(0, horizon * 1.1, padding=0)
        self.uh_plot.enableAutoRange(axis="y")
        note = ("Solid: fitted to the current event; dashed: pooled; faint: the model's other events."
                if gid is not None else "Select an event to highlight its per-event shapes.")
        if without:
            note += " No unit hydrograph to show for: " + ", ".join(without) + "."
        self.uh_note.setText(note)
        keys = list(rows[0][5].stats()) if rows else []
        self.uh_stats.clear()
        self.uh_stats.setColumnCount(3 + len(keys))
        self.uh_stats.setHorizontalHeaderLabels(["Model", "Fit", "Unit hydrograph", *keys])
        self.uh_stats.setRowCount(len(rows))
        for r, (label, mode_text, component, color, dashed, c) in enumerate(rows):
            first_item = text_item(label)
            first_item.setIcon(swatch(color, dashed=dashed))
            self.uh_stats.setItem(r, 0, first_item)
            self.uh_stats.setItem(r, 1, text_item(mode_text))
            self.uh_stats.setItem(r, 2, text_item(component or "unit hydrograph"))
            for k, v in enumerate(c.stats().values(), start=3):
                self.uh_stats.setItem(r, k, num_item(float(v), "{:.3g}"))

    def _fill_compare(self) -> None:
        a = self.analysis
        table = a.comparison_table()
        cols = list(table.columns)
        self.compare.clear()
        self.compare.setColumnCount(len(cols))
        self.compare.setHorizontalHeaderLabels(["Event"] + [f"NSE {c}" for c in cols[1:]])
        styles = {series_name(f.config.label, m): (config_color(i), m == "pooled")
                  for i, f in enumerate(a.fits) for m in f.config.modes}
        for j, c in enumerate(cols[1:], start=1):  # the column's colour and line style, as in the charts
            if c in styles:
                self.compare.horizontalHeaderItem(j).setIcon(swatch(styles[c][0], dashed=styles[c][1]))
        self.compare.setRowCount(len(table))
        for i, row in enumerate(table.itertuples(index=False)):
            gid = row[0]
            first = text_item("Mean" if gid == "mean" else f"#{gid}")
            if gid != "mean":
                first.setData(Qt.ItemDataRole.UserRole, int(gid))
            self.compare.setItem(i, 0, first)
            values = [v for v in row[1:]]
            best = np.nanmax(values) if values and not all(pd.isna(v) for v in values) else None
            for j, v in enumerate(values, start=1):
                item = num_item(float(v), "{:.3f}") if not pd.isna(v) else text_item("")
                if best is not None and not pd.isna(v) and v == best and len(values) > 1:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                    item.setToolTip("Best for this event")
                self.compare.setItem(i, j, item)
        self.compare.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def _fill_details(self, gid: int | None) -> None:
        a = self.analysis
        if a is None or gid is None or self._table.empty:
            self.details.setRowCount(0)
            return
        row = self._table[self._table["global_id"] == gid]
        if row.empty:
            return
        r = row.iloc[0]
        rows: list[tuple[str, object]] = [
            ("Global event", f"#{gid}"), ("Start", f"{r['start']:%Y-%m-%d %H:%M}"),
            ("End", f"{r['end']:%Y-%m-%d %H:%M}"), ("Season", r["season"]), ("Sub-events", int(r["n_sub"])),
            ("Total rain [in]", float(r["total_rain"])), ("Peak flow", float(r["peak_flow"])),
        ]
        table = a.comparison_table()
        match = table[table["global_id"] == gid]
        if not match.empty:
            rows += [(f"NSE {c}", float(match.iloc[0][c])) for c in table.columns[1:]]
        for fit in a.fits:
            for mode in fit.config.modes:
                rows += [(f"{series_name(fit.config.label, mode)} {k}", v)
                         for k, v in fit.parameters(mode, gid).items()]
        self.details.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.details.setItem(i, 0, text_item(k))
            self.details.setItem(i, 1, num_item(v) if isinstance(v, float | int) else text_item(str(v)))


def _main(curves: list[KernelCurve]) -> list[KernelCurve]:
    """The curves that stand for a model's response: the combined curve of each RDII group, and every
    unit hydrograph outside a group."""
    grouped = {c.group for c in curves if c.group and c.label.endswith("combined")}
    return [c for c in curves if c.label.endswith("combined") or c.group not in grouped]
