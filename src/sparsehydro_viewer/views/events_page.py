"""Events workspace: detected storm events, one unit hydrograph per global event.

Views follow Hydrology-Viewer: Data fitting, UH shapes, Convolution and
Weights, for one event at a time or for the whole record ("Continuous").
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.catalog import UH_KEYS, uh_label
from ..core.data import epoch_seconds
from ..core.events import EVENT_OPTIONS, EventAnalysis, EventOverrides, run_event_analysis
from ..core.uh import kernel_curves
from ..widgets import OptionForm, TimeseriesPlot
from .common import num_item, page_header, text_item
from .context import AppContext
from .shell.page import Page

SORTS = {"Start time": ("start", False), "Total rain (largest first)": ("total_rain", True),
         "Peak flow (largest first)": ("peak_flow", True), "NSE (worst first)": ("nse", False)}


class EventsPage(Page):
    title = "Events"
    icon_name = "nav-events"
    primary_text = "Detect and fit"
    primary_tip = "Detect storm events and fit one unit hydrograph per global event"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        s = ctx.session
        uh_labels = {k: uh_label(k) for k in UH_KEYS}
        self.options = OptionForm(choice_labels=uh_labels)
        self.options.set_specs(EVENT_OPTIONS)
        run = QPushButton("Detect events and fit")
        run.setObjectName("primary")
        run.clicked.connect(self.run_analysis)
        self.status = QLabel("Not run yet.")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        ob = QGroupBox("Detection and fitting")
        ol = QVBoxLayout(ob)
        ol.addWidget(self.options)
        ol.addWidget(run)
        ol.addWidget(self.status)

        self.group = QComboBox()
        self.group.addItems(["All", "Season", "Quarter"])
        self.filter = QComboBox()
        self.sort = QComboBox()
        self.sort.addItems(list(SORTS))
        self.group.currentIndexChanged.connect(self._group_changed)
        self.filter.currentIndexChanged.connect(self._fill_list)
        self.sort.currentIndexChanged.connect(self._fill_list)
        self.events = QListWidget()
        self.events.currentItemChanged.connect(lambda *_: self._show_event())
        self.events.currentItemChanged.connect(lambda *_: self.contextChanged.emit())
        self.prev_action = self.action("Previous event", "Show the previous event in the list", "prev",
                                       lambda: self._step(-1), shortcut="Left")
        self.next_action = self.action("Next event", "Show the next event in the list", "next",
                                       lambda: self._step(1), shortcut="Right")
        self.exclude_action = self.action("Exclude event", "Exclude the selected global event from fitting "
                                                           "(stored in the project) and refit", "exclude",
                                          self._exclude)
        self.restore_action = self.action("Restore excluded events", "Bring back all excluded events and refit",
                                          "restore", self._restore)
        eb = QGroupBox("Global events")
        el = QVBoxLayout(eb)
        r = QHBoxLayout()
        r.addWidget(self.group)
        r.addWidget(self.filter, 1)
        el.addLayout(r)
        el.addWidget(self.sort)
        el.addWidget(self.events, 1)

        self.edits_note = QLabel(
            "Exclude or restore events with the toolbar. Adding, splitting and merging events, peak edits and "
            "smoothing pins need event-override support in sparsehydro's detection and will appear here when "
            "it is available.")
        self.edits_note.setObjectName("hint")
        self.edits_note.setWordWrap(True)
        tb = QGroupBox("Edits")
        tl = QVBoxLayout(tb)
        tl.addWidget(self.edits_note)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(ob)
        ll.addWidget(eb, 1)
        ll.addWidget(tb)
        left.setMinimumWidth(300)
        left.setMaximumWidth(400)

        # -- views ---------------------------------------------------------------
        self.continuous = QCheckBox("Continuous (whole record)")
        self.continuous.toggled.connect(lambda *_: self._show_event())
        self.tabs = QTabWidget()
        self.fit_plot = TimeseriesPlot()
        self.uh_plot = pg.PlotWidget()
        self.uh_plot.setLabel("bottom", "Time since excess [h]")
        self.uh_plot.setLabel("left", "Ordinate [1/h]")
        self.uh_plot.showGrid(x=True, y=True, alpha=0.15)
        theme.plain_axes(self.uh_plot)
        self.conv_plot = TimeseriesPlot()
        self.weight_plot = TimeseriesPlot(flow_label="Weight")
        self.tabs.addTab(self.fit_plot, "1  Data fitting")
        self.tabs.addTab(self.uh_plot, "2  UH shapes")
        self.tabs.addTab(self.conv_plot, "3  Convolution")
        self.tabs.addTab(self.weight_plot, "4  Weights")
        self.tabs.currentChanged.connect(lambda *_: self._show_event())
        self.tabs.currentChanged.connect(lambda *_: self.contextChanged.emit())  # active chart follows the tab

        self.details = QTableWidget(0, 2)
        self.details.setHorizontalHeaderLabels(["Field", "Value"])
        self.details.verticalHeader().setVisible(False)
        self.details.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.details.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        db = QGroupBox("Event details")
        dl = QVBoxLayout(db)
        dl.addWidget(self.details)
        db.setMaximumWidth(320)

        views = QWidget()
        vl = QVBoxLayout(views)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(self.continuous)
        vl.addWidget(self.tabs, 1)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(views)
        split.addWidget(db)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Events", "Detect storm events and fit one unit hydrograph per global event. "
                                            "←/→ move between events, 1-4 switch views."))
        lay.addWidget(split, 1)

        for i in range(4):
            sc = QShortcut(QKeySequence(str(i + 1)), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda i=i: self.tabs.setCurrentIndex(i))

        self.analysis: EventAnalysis | None = None
        self._table = pd.DataFrame()
        s.projectChanged.connect(self._project_changed)
        s.datasetChanged.connect(self._dataset_changed)
        s.datasetChanged.connect(self.contextChanged)
        self._group_changed()

    # ------------------------------------------------------------------ shell

    def primary(self) -> None:
        self.run_analysis()

    def primary_enabled(self) -> bool:
        return self.ctx.session.dataset is not None and not self.stop_enabled()

    def context_actions(self):
        return [self.prev_action, self.next_action, None, self.exclude_action, self.restore_action]

    def active_chart(self):
        return {0: self.fit_plot, 2: self.conv_plot, 3: self.weight_plot}.get(self.tabs.currentIndex())

    def status_text(self) -> str:
        gid = self._current_id()
        return f"event #{gid}" if gid is not None else ""

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
        self.options.set_values(self.ctx.session.ui("event_options", {}))
        self._dataset_changed()

    def _dataset_changed(self) -> None:
        self.analysis = None
        self._table = pd.DataFrame()
        self.events.clear()
        self.status.setText("Not run yet for this dataset.")

    def run_analysis(self) -> None:
        s = self.ctx.session
        frame = s.frame()
        if frame is None:
            QMessageBox.information(self, "Events", "Load a dataset first.")
            return
        opts = self.options.values()
        s.set_ui("event_options", opts)
        ov = self._overrides()
        self.status.setText("Detecting events and fitting...")

        def work(ctx):
            def progress(i: int, n: int, text: str) -> None:
                ctx.progress(text, i / n if n else None)

            return run_event_analysis(frame, opts, ov, should_stop=ctx.token, progress=progress)

        def done(a: EventAnalysis) -> None:
            self.analysis = a
            self._table = a.event_table()
            n_ex = len(ov.deleted_global_ids)
            self.status.setText(f"{len(a.global_events)} global events, {len(a.sub_events)} sub-events, "
                                f"{len(a.fitted_ids())} fitted" + (f"; {n_ex} excluded" if n_ex else ""))
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
                it.setToolTip("Not fitted")
            self.events.addItem(it)
        self.events.blockSignals(False)
        target = 0
        for i in range(self.events.count()):
            if self.events.item(i).data(Qt.ItemDataRole.UserRole) == current:
                target = i
        self.events.setCurrentRow(target)

    def _current_id(self) -> int | None:
        it = self.events.currentItem()
        return None if it is None else int(it.data(Qt.ItemDataRole.UserRole))

    def _step(self, d: int) -> None:
        n = self.events.count()
        if n:
            self.events.setCurrentRow(min(max(self.events.currentRow() + d, 0), n - 1))

    # ------------------------------------------------------------------ views

    def _window(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        a = self.analysis
        if a is None:
            return None
        if self.continuous.isChecked():
            return a.data["datetime"].iloc[0], a.data["datetime"].iloc[-1]
        gid = self._current_id()
        return None if gid is None else a.window(gid)

    def _show_event(self) -> None:
        a = self.analysis
        win = self._window()
        if a is None or win is None:
            return
        gid = self._current_id()
        self._fill_details(gid)
        view = self.tabs.currentIndex()
        if view == 0:
            self._show_fit(a, win)
        elif view == 1:
            self._show_uh(a, gid)
        elif view == 2:
            self._show_convolution(a, win)
        else:
            self._show_weights(a, win)

    def _slice(self, a: EventAnalysis, win) -> pd.DataFrame:
        d = a.data
        sel = (d["datetime"] >= win[0]) & (d["datetime"] <= win[1])
        return d.loc[sel]

    def _show_fit(self, a: EventAnalysis, win) -> None:
        th = theme.current()
        d = self._slice(a, win)
        t = epoch_seconds(d["datetime"])
        self.fit_plot.clear_curves()
        self.fit_plot.set_data(t, d["rain"].to_numpy(), d["stormflow"].to_numpy(), "Observed")
        sg_t = pd.to_datetime(pd.Series(a.savgol.datetime))
        sel = ((sg_t >= win[0]) & (sg_t <= win[1])).to_numpy()
        if sel.any():
            self.fit_plot.set_curve("savgol", epoch_seconds(sg_t[sel]), np.asarray(a.savgol.smoothed)[sel],
                                    color=th.accent, width=2, name="Smoothed (variable SavGol)")
        subs = [s for s in a.sub_events if s.end_datetime >= win[0] and s.start_datetime <= win[1]]
        self.fit_plot.set_spans([(epoch_seconds([s.start_datetime])[0], epoch_seconds([s.end_datetime])[0])
                                 for s in subs])
        if subs:
            primary = [s for s in subs if not s.is_bimodal]
            bimodal = [s for s in subs if s.is_bimodal]
            if primary:
                self.fit_plot.set_markers("peaks", epoch_seconds([s.peak_datetime for s in primary]),
                                          [s.peak_flow for s in primary], color="#D55E00", symbol="star",
                                          size=14, name="Peaks")
            if bimodal:
                self.fit_plot.set_markers("bimodal", epoch_seconds([s.peak_datetime for s in bimodal]),
                                          [s.peak_flow for s in bimodal], color="#E69F00", symbol="t",
                                          name="Bimodal peaks")

    def _show_uh(self, a: EventAnalysis, gid: int | None) -> None:
        th = theme.current()
        self.uh_plot.clear()
        horizon = 2.0
        for other in a.fitted_ids():
            m = a.fitted_model(other)
            if m is None:
                continue
            c = kernel_curves(m, a.dt_hours)[0]
            is_cur = other == gid
            horizon = max(horizon, c.time_to_mass(0.995)) if is_cur or gid is None else horizon
            col = pg.mkColor(th.predicted if is_cur else th.muted)
            if not is_cur:
                col.setAlpha(70)
            item = self.uh_plot.plot(np.r_[0, c.t_hours], np.r_[0, c.ordinates],
                                     pen=pg.mkPen(col, width=2.6 if is_cur else 1))
            item.setZValue(10 if is_cur else 0)
        self.uh_plot.setXRange(0, horizon * 1.1, padding=0)
        self.uh_plot.setTitle("Current event (highlighted) against all fitted events", color=th.muted)

    def _show_convolution(self, a: EventAnalysis, win) -> None:
        th = theme.current()
        d = self._slice(a, win)
        t = epoch_seconds(d["datetime"])
        self.conv_plot.clear_curves()
        self.conv_plot.set_data(t, d["rain"].to_numpy(), d["stormflow"].to_numpy(), "Observed")
        pred = a.predicted()
        ps = pred.loc[(pred["datetime"] >= win[0]) & (pred["datetime"] <= win[1])]
        self.conv_plot.set_curve("pred", epoch_seconds(ps["datetime"]), ps["Q_pred"].to_numpy(),
                                 color=th.predicted, width=2, name="Convolved prediction")

    def _show_weights(self, a: EventAnalysis, win) -> None:
        """Zonal fit weights: peak weight in rise-to-tail zones, tail weight elsewhere in sub-events."""
        th = theme.current()
        d = self._slice(a, win)
        t_all = d["datetime"].to_numpy()
        w = np.zeros(len(d))
        pw, tw = a.options["peak_weight"], a.options["tail_weight"]
        for s in a.sub_events:
            inside = (t_all >= np.datetime64(s.start_datetime)) & (t_all <= np.datetime64(s.end_datetime))
            w[inside] = np.maximum(w[inside], tw)
            peak = (t_all >= np.datetime64(s.rise_start_datetime)) & (t_all <= np.datetime64(s.tail_start_datetime))
            w[peak] = np.maximum(w[peak], pw)
        t = epoch_seconds(d["datetime"])
        self.weight_plot.clear_curves()
        self.weight_plot.set_data(t, d["rain"].to_numpy(), None)
        self.weight_plot.set_curve("w", t, w, color=th.accent, width=2, name="Weight")
        flow = d["stormflow"].to_numpy()
        peak_flow = np.nanmax(flow) if len(flow) else 0
        if peak_flow > 0:
            self.weight_plot.set_curve("flow", t, flow / peak_flow * max(pw, tw, 1.0), color=th.observed,
                                       width=1, dashed=True, name="Flow (scaled)")

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
            ("NSE", float(r["nse"])), ("Fitted", "yes" if r["fitted"] else "no"),
        ]
        rows += [(f"UH {k}", v) for k, v in a.parameters(gid).items()]
        self.details.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.details.setItem(i, 0, text_item(k))
            self.details.setItem(i, 1, num_item(v) if isinstance(v, float | int) else text_item(str(v)))
