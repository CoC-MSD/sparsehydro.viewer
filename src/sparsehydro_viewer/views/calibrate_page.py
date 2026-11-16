"""Calibrate workspace: objectives, solver configuration, run queue and live convergence."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.calibration import CalibrationPayload
from ..core.catalog import CATALOG, parameter_counts
from ..core.diagnostics import front_history
from ..core.objectives import OBJECTIVES, ObjectiveSpec
from ..core.runs import RunRecord, new_id
from ..core.solvers import SOLVERS, SolverSpec
from ..widgets import OptionForm, ParetoLayer, ParetoPlot
from .common import num_item, objective_better, objective_labels, page_header, text_item
from .context import AppContext
from .shell.page import Page

RUN_COLUMNS = ["Run", "Model", "Params (cal/total)", "Solver", "Status", "Progress", "Reports", "Elapsed [s]",
               "Solutions"]


class CalibratePage(Page):
    title = "Calibrate"
    icon_name = "nav-calibrate"
    uses_working_model = True
    primary_text = "Run calibration"
    primary_tip = "Calibrate the working model with the chosen objectives and optimizer"

    def __init__(self, ctx: AppContext, show_explore=None) -> None:
        super().__init__(ctx)
        self.show_explore = show_explore
        self._editing_objectives = False
        s = ctx.session

        # -- objectives ---------------------------------------------------------
        self.obj_list = QListWidget()
        self.obj_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.obj_list.setToolTip("Tick the objectives to optimise; drag to reorder (order sets the axes and "
                                 "the SciPy objective index)")
        self.obj_form = OptionForm()
        self._obj_options: dict[str, dict] = {}
        self.obj_list.currentItemChanged.connect(self._obj_selected)
        self.obj_list.itemChanged.connect(lambda *_: self._objectives_edited())
        self.obj_list.model().rowsMoved.connect(lambda *_: self._objectives_edited())
        self.obj_form.changed.connect(self._obj_option_changed)
        ob = QGroupBox("Objectives")
        ol = QVBoxLayout(ob)
        ol.addWidget(self.obj_list, 1)
        ol.addWidget(self.obj_form)

        # -- solver ---------------------------------------------------------------
        self.solver = QComboBox()
        for e in SOLVERS.entries():
            self.solver.addItem(e.label, e.name)
            self.solver.setItemData(self.solver.count() - 1, e.description, Qt.ItemDataRole.ToolTipRole)
        self.solver.setToolTip("Optimization algorithm; multi-objective ones return a Pareto front, single-objective "
                               "ones one solution")
        self.solver.setAccessibleName("Optimizer")
        self.solver_desc = QLabel()
        self.solver_desc.setWordWrap(True)
        self.solver_desc.setObjectName("hint")
        self.solver_form = OptionForm()
        self.solver.currentIndexChanged.connect(self._solver_changed)
        self.solver_form.changed.connect(self._solver_edited)
        sb = QGroupBox("Optimizer")
        sl = QVBoxLayout(sb)
        sl.addWidget(self.solver)
        sl.addWidget(self.solver_desc)
        sl.addWidget(self.solver_form)
        sl.addStretch(1)

        # -- launch ---------------------------------------------------------------
        self.label = QLineEdit()
        self.label.setPlaceholderText("run label (optional)")
        self.label.setToolTip("Name of the next run (default: the model's name and a number)")
        self.label.setAccessibleName("Run label")
        self.run_btn = QPushButton("Run calibration")
        self.run_btn.setToolTip("Start a calibration of the working model in its own process  [toolbar Run]")
        self.obj_list.setAccessibleName("Objectives")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run)
        self.launch_hint = QLabel()
        self.launch_hint.setObjectName("hint")
        self.launch_hint.setWordWrap(True)
        lb = QGroupBox("Run")
        ll = QVBoxLayout(lb)
        ll.addWidget(self.launch_hint)
        r = QHBoxLayout()
        r.addWidget(self.label, 1)
        r.addWidget(self.run_btn)
        ll.addLayout(r)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(ob, 2)
        lv.addWidget(sb, 2)
        lv.addWidget(lb)
        left.setMinimumWidth(340)
        left.setMaximumWidth(460)

        # -- runs table + monitors -----------------------------------------------
        self.table = QTableWidget(0, len(RUN_COLUMNS))
        self.table.setHorizontalHeaderLabels(RUN_COLUMNS)
        self.table.setAccessibleName("Calibration runs")
        self.table.setToolTip("Select a run to monitor it; double-click to explore it")
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._monitor_selected)
        self.table.doubleClicked.connect(lambda *_: self._explore())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.use_settings_action = self.action(
            "Use run settings", "Load the selected run's model, objectives and optimizer settings into the editors",
            "use-settings", self._use_settings)
        self.explore_action = self.action("Explore run", "Open the selected run in Explore", "nav-explore",
                                          self._explore)
        self.delete_action = self.action("Delete runs", "Delete the selected runs", "delete", self._delete)
        runs_box = QGroupBox("Runs")
        rl = QVBoxLayout(runs_box)
        rl.addWidget(self.table, 1)

        self.conv = pg.PlotWidget()
        self.conv.setLabel("bottom", "Evaluations")
        self.conv.showGrid(x=True, y=True, alpha=0.15)
        theme.plain_axes(self.conv)
        self.conv_obj = QComboBox()
        self.conv_obj.setToolTip("Best value of an objective at each report, or the front's size or hypervolume "
                                 "(objectives scaled over the run's history; higher means a better, wider front)")
        self.conv_obj.setAccessibleName("Convergence measure")
        self.conv_obj.currentIndexChanged.connect(self._draw_monitor)
        self.conv_legend = self.conv.addLegend(offset=(-10, 10), labelTextColor=theme.current().plot_fg)
        conv_box = QGroupBox("Convergence")
        cl = QVBoxLayout(conv_box)
        cl.addWidget(self.conv_obj)
        cl.addWidget(self.conv, 1)
        self.front = ParetoPlot(labels=objective_labels(), better=objective_better())
        self.front_box = QGroupBox("Current front")
        fl = QVBoxLayout(self.front_box)
        fl.addWidget(self.front)
        mon = QSplitter()
        mon.addWidget(conv_box)
        mon.addWidget(self.front_box)

        # -- which run(s) the monitor shows, and the front's history ----------------
        self.monitor_box = QComboBox()
        self.monitor_box.setToolTip("Run shown in the convergence and front charts: the run selected in the table, "
                                    "a particular run, or every running run overlaid (one colour each)")
        self.monitor_box.setAccessibleName("Run shown in the monitor")
        self.monitor_box.currentIndexChanged.connect(self._draw_monitor)
        self.history = QCheckBox("Earlier generations")
        self.history.setToolTip("Draw the fronts of earlier reports behind the current one, fainter the older they "
                                "are (one run at a time)")
        self.history.toggled.connect(self._draw_monitor)
        self.generation = QSlider(Qt.Orientation.Horizontal)
        self.generation.setMinimum(1)
        self.generation.setToolTip("Report shown as the current front; drag back to replay the run's progress")
        self.generation.setAccessibleName("Report shown as the current front")
        self.generation.valueChanged.connect(self._draw_monitor)
        self.generation_label = QLabel()
        self.generation_label.setObjectName("hint")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show"))
        bar.addWidget(self.monitor_box, 2)
        bar.addSpacing(12)
        bar.addWidget(self.history)
        bar.addWidget(self.generation, 2)
        bar.addWidget(self.generation_label, 1)
        monitor = QWidget()
        ml = QVBoxLayout(monitor)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addLayout(bar)
        ml.addWidget(mon, 1)
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(runs_box)
        right.addWidget(monitor)
        right.setStretchFactor(0, 2)
        right.setStretchFactor(1, 3)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Calibrate", "Choose objectives and an optimizer, then run. Runs execute in "
                                               "separate processes; you can keep working and cancel at any time."))
        lay.addWidget(split, 1)

        self._monitor_id: str | None = None
        s.projectChanged.connect(self._load_from_session)
        s.runsChanged.connect(self._fill_monitor_box)
        for sig in (ctx.calibration.started, ctx.calibration.finished):
            sig.connect(lambda *_: self._fill_monitor_box())
        s.objectivesChanged.connect(self._sync_objectives)
        s.runsChanged.connect(self._fill_table)
        s.modelChanged.connect(self._update_hint)
        s.parametersEdited.connect(self._update_hint)
        s.datasetChanged.connect(self._update_hint)
        s.periodsChanged.connect(self._update_hint)
        s.modelRenamed.connect(self._update_hint)
        ctx.calibration.progress.connect(self._on_progress)
        ctx.calibration.status.connect(lambda rid, _text: self._on_run_changed(rid))
        ctx.calibration.started.connect(self._on_run_changed)
        ctx.calibration.finished.connect(self._on_finished)
        for sig in (ctx.calibration.started, ctx.calibration.finished):
            sig.connect(lambda *_: self.contextChanged.emit())
        self._load_from_session()

    # ------------------------------------------------------------------ objectives

    def _load_from_session(self) -> None:
        self._sync_objectives()
        spec, note = SOLVERS.usable(self.ctx.session.solver)
        if note:  # e.g. a run's settings name an optimizer that is not installed here
            self.ctx.session.set_solver(spec)
        self.solver.blockSignals(True)
        self.solver.setCurrentIndex(max(0, self.solver.findData(spec.name)))
        self.solver.blockSignals(False)
        entry = SOLVERS.get(self.solver.currentData())
        self.solver_desc.setText(entry.description + (f"\n\nNote: {note}." if note else ""))
        self.solver_form.set_specs(entry.options, spec.options)
        self._fill_table()
        self._fill_monitor_box()
        self._update_hint()

    def _sync_objectives(self) -> None:
        if self._editing_objectives:  # our own edit; the list already shows it
            return
        chosen = self.ctx.session.objectives
        self._obj_options = {o.name: dict(o.options) for o in chosen}
        self.obj_list.blockSignals(True)
        self.obj_list.clear()
        ordered = [o.name for o in chosen] + [e.name for e in OBJECTIVES.entries() if e.name not in
                                               {o.name for o in chosen}]
        for name in ordered:
            e = OBJECTIVES.get(name)
            arrow = "↑" if not e.minimize else "↓"
            it = QListWidgetItem(f"{e.label}  {arrow}")
            it.setData(Qt.ItemDataRole.UserRole, name)
            it.setToolTip(e.description + ("  (maximised)" if not e.minimize else "  (minimised)"))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            it.setCheckState(Qt.CheckState.Checked if name in self._obj_options else Qt.CheckState.Unchecked)
            self.obj_list.addItem(it)
        self.obj_list.blockSignals(False)
        self.obj_form.set_specs(())
        self._update_hint()

    def _obj_selected(self, item: QListWidgetItem | None) -> None:
        if item is None:
            self.obj_form.set_specs(())
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        self.obj_form.set_specs(OBJECTIVES.get(name).options, self._obj_options.get(name, {}))

    def _obj_option_changed(self) -> None:
        item = self.obj_list.currentItem()
        if item is not None:
            self._obj_options[item.data(Qt.ItemDataRole.UserRole)] = self.obj_form.values()
            self._objectives_edited()

    def _objectives_edited(self) -> None:
        specs = []
        for i in range(self.obj_list.count()):
            it = self.obj_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                name = it.data(Qt.ItemDataRole.UserRole)
                specs.append(ObjectiveSpec(name, self._obj_options.get(name, {})))
        s = self.ctx.session
        if [o.to_dict() for o in specs] != [o.to_dict() for o in s.objectives] and specs:
            self._editing_objectives = True
            try:
                s.set_objectives(specs)
            finally:
                self._editing_objectives = False
        self._update_hint()

    # ------------------------------------------------------------------ solver

    def _solver_changed(self) -> None:
        entry = SOLVERS.get(self.solver.currentData())
        self.solver_desc.setText(entry.description)
        current = self.ctx.session.solver
        self.solver_form.set_specs(entry.options, current.options if current.name == entry.name else {})
        self._solver_edited()

    def _solver_edited(self) -> None:
        self.ctx.session.set_solver(SolverSpec(self.solver.currentData(), self.solver_form.values()))
        self._update_hint()

    def _update_hint(self) -> None:
        s = self.ctx.session
        model = CATALOG.instantiate(s.model_spec)
        total, cal = parameter_counts(model)
        ds = s.dataset
        period = "no dataset" if ds is None else (
            "whole record" if ds.calibration.is_open else f"{ds.calibration.start} to {ds.calibration.end}")
        self.launch_hint.setText(
            f"Model: <b>{s.model_spec.display_label}</b>, {cal} of {total} parameters calibrated "
            f"(fixed ones keep their slider values). Objectives: {len(s.objectives)}. "
            f"Dataset: {ds.name if ds else '-'} ({period}).")
        self._can_run = ds is not None and cal > 0 and len(s.objectives) > 0
        self.run_btn.setEnabled(self._can_run)
        self.contextChanged.emit()

    # ------------------------------------------------------------------ shell

    def primary(self) -> None:
        self._run()

    def primary_enabled(self) -> bool:
        return getattr(self, "_can_run", False)

    def stop(self) -> None:
        """Cancel the selected runs that are active, or every active run when none is selected."""
        selected = [r for r in self._selected_ids() if self.ctx.calibration.is_active(r)]
        if selected:
            for rid in selected:
                self.ctx.calibration.cancel(rid)
        else:
            self.ctx.calibration.cancel_all()

    def stop_enabled(self) -> bool:
        return self.ctx.calibration.active_count > 0

    def context_actions(self):
        selected = bool(self._selected_ids())
        for a in (self.use_settings_action, self.explore_action, self.delete_action):
            a.setEnabled(selected)
        return [self.use_settings_action, self.explore_action, None, self.delete_action]

    def status_text(self) -> str:
        n = self.ctx.calibration.active_count
        return f"{n} run(s) active" if n else ""

    # ------------------------------------------------------------------ runs

    def _run(self) -> None:
        s = self.ctx.session
        ds, frame = s.dataset, s.frame()
        if ds is None or frame is None:
            return
        solver = s.solver
        entry = SOLVERS.get(solver.name)
        if not entry.multi_objective:
            idx = int(solver.options.get("objective_index", 0))
            if idx >= len(s.objectives):
                QMessageBox.warning(self, "Objective index", f"Objective # {idx} does not exist; there are "
                                                             f"{len(s.objectives)} objectives (numbered from 0).")
                return
        spec = s.working_spec()
        n = len(s.project.runs) + 1
        label = self.label.text().strip() or f"{spec.display_label} #{n}"
        model = CATALOG.instantiate(spec)
        total, _ = parameter_counts(model)
        rec = RunRecord(new_id(), label, ds.name, spec, list(s.objectives), solver, status="queued",
                        n_params_total=total)
        payload = CalibrationPayload(rec.id, spec.to_dict(), [o.to_dict() for o in s.objectives], solver.to_dict(),
                                     frame, ds.calibration.to_dict())
        s.add_run(rec)
        self.ctx.calibration.submit(rec, payload)
        self.label.clear()
        self._select_row(rec.id)

    def _selected_ids(self) -> list[str]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]

    def _select_row(self, run_id: str) -> None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == run_id:
                self.table.selectRow(r)
                return

    def _selection_changed(self) -> None:
        enabled = bool(self._selected_ids())
        for a in (self.use_settings_action, self.explore_action, self.delete_action):
            a.setEnabled(enabled)

    def _delete(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        if any(self.ctx.calibration.is_active(r) for r in ids):
            QMessageBox.information(self, "Delete runs", "Cancel running runs before deleting them.")
            return
        if QMessageBox.question(self, "Delete runs", f"Delete {len(ids)} run(s)? This cannot be undone.") \
                == QMessageBox.StandardButton.Yes:
            self.ctx.session.remove_runs(ids)

    def _explore(self) -> None:
        ids = self._selected_ids()
        if ids and self.show_explore is not None:
            self.show_explore(ids[0])

    def _use_settings(self) -> None:
        ids = self._selected_ids()
        run = self.ctx.session.run(ids[0]) if ids else None
        if run is None:
            return
        s = self.ctx.session
        s.set_model(run.model, {k: v.value for k, v in run.model.parameters.items() if v.value is not None})
        s.set_objectives(list(run.objectives))
        if run.solver:
            s.set_solver(run.solver)
        self._load_from_session()

    def _fill_table(self) -> None:
        keep = self._selected_ids()
        runs = self.ctx.session.project.runs
        self.table.setRowCount(len(runs))
        for r, run in enumerate(runs):
            self._fill_row(r, run)
        for rid in keep:
            self._select_row(rid)

    def _fill_row(self, r: int, run: RunRecord) -> None:
        solver = SOLVERS.get(run.solver.name).label if run.solver else "manual"
        cal = run.n_params_calibrated or "-"
        cells = [text_item(run.label, run.id), text_item(run.model.display_label),
                 text_item(f"{cal} / {run.n_params_total}"), text_item(solver), text_item(run.status),
                 text_item(""), num_item(len(run.history)), num_item(run.elapsed_s, "{:.1f}"),
                 num_item(run.n_solutions)]
        if run.message:
            cells[4].setToolTip(run.message)
        for c, it in enumerate(cells):
            self.table.setItem(r, c, it)
        self._set_progress(r, run)

    def _set_progress(self, r: int, run: RunRecord) -> None:
        """Progress bar in the Progress column while a run is queued or running."""
        col = RUN_COLUMNS.index("Progress")
        if run.status not in ("queued", "running"):
            self.table.removeCellWidget(r, col)
            self.table.item(r, col).setText("100%" if run.status == "finished" else "")
            return
        bar = self.table.cellWidget(r, col)
        if not isinstance(bar, QProgressBar):
            bar = QProgressBar()
            bar.setMaximumHeight(16)
            bar.setTextVisible(True)
            self.table.setCellWidget(r, col, bar)
        frac, text = self.ctx.calibration.progress_info(run.id)
        if run.status == "queued" or frac is None:
            bar.setRange(0, 0)
            bar.setFormat(text or run.status)
        else:
            bar.setRange(0, 1000)
            bar.setValue(int(frac * 1000))
            bar.setFormat(f"{frac:.0%}  {text}")

    def _row_of(self, run_id: str) -> int | None:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == run_id:
                return r
        return None

    def _on_run_changed(self, run_id: str) -> None:
        r = self._row_of(run_id)
        run = self.ctx.session.run(run_id)
        if r is not None and run is not None:
            self._fill_row(r, run)

    def _on_progress(self, run_id: str) -> None:
        self._on_run_changed(run_id)
        if self._monitor_id is None:
            self._monitor_id = run_id
        if run_id in {r.id for r in self._monitored()} or self.monitor_box.currentData() == self.ACTIVE:
            self._draw_monitor()

    def _on_finished(self, run_id: str) -> None:
        run = self.ctx.session.run(run_id)
        if run is not None:
            self.ctx.session.update_run(run)
            if run.status == "failed":
                QMessageBox.warning(self, "Calibration failed", f"{run.label}: {run.message}")
        self._on_run_changed(run_id)
        if run_id in {r.id for r in self._monitored()} or self.monitor_box.currentData() == self.ACTIVE:
            self._draw_monitor()

    # ------------------------------------------------------------------ monitor

    #: Monitor modes besides a particular run id.
    SELECTED, ACTIVE = "__selected__", "__active__"
    #: Convergence measures besides an objective name.
    SIZE, HV = "__front_size__", "__hypervolume__"
    #: Earlier generations drawn at most (evenly thinned beyond), to keep the front chart responsive.
    MAX_HISTORY_LAYERS = 40

    def _fill_monitor_box(self) -> None:
        current = self.monitor_box.currentData()
        self.monitor_box.blockSignals(True)
        self.monitor_box.clear()
        self.monitor_box.addItem("Selected run", self.SELECTED)
        self.monitor_box.addItem("All running runs (overlaid)", self.ACTIVE)
        for run in reversed(self.ctx.session.project.runs):
            self.monitor_box.addItem(f"{run.label}  [{run.status}]", run.id)
        i = self.monitor_box.findData(current)
        self.monitor_box.setCurrentIndex(i if i >= 0 else 0)
        self.monitor_box.blockSignals(False)

    def _monitored(self) -> list[RunRecord]:
        """Runs the monitor shows, in a stable order."""
        s = self.ctx.session
        mode = self.monitor_box.currentData() or self.SELECTED
        if mode == self.ACTIVE:
            runs = [r for r in s.project.runs if self.ctx.calibration.is_active(r.id) and r.history]
            if runs:
                return runs
            mode = self.SELECTED
        if mode == self.SELECTED:
            run = s.run(self._monitor_id)
            return [run] if run is not None else []
        run = s.run(mode)
        return [run] if run is not None else []

    def _monitor_selected(self) -> None:
        ids = self._selected_ids()
        if ids:
            self._monitor_id = ids[0]
            self._draw_monitor()

    def _sync_conv_measures(self, names: list[str]) -> None:
        labels = objective_labels(names)
        wanted = [*names, self.SIZE, self.HV]
        if [self.conv_obj.itemData(i) for i in range(self.conv_obj.count())] == wanted:
            return
        current = self.conv_obj.currentData()
        self.conv_obj.blockSignals(True)
        self.conv_obj.clear()
        for n in names:
            self.conv_obj.addItem(f"Best {labels.get(n, n)}", n)
        self.conv_obj.addItem("Front size (solutions)", self.SIZE)
        self.conv_obj.addItem("Hypervolume (normalised)", self.HV)
        i = self.conv_obj.findData(current)
        self.conv_obj.setCurrentIndex(i if i >= 0 else 0)
        self.conv_obj.blockSignals(False)

    def _draw_monitor(self) -> None:
        runs = self._monitored()
        self.conv.clear()
        self.conv_legend.clear()
        if not runs or not runs[0].objective_names:
            self.front.set_layers([])
            self.generation_label.setText("")
            return
        names = runs[0].objective_names
        self._sync_conv_measures(names)
        measure = self.conv_obj.currentData() or names[0]
        single = len(runs) == 1
        labels = objective_labels(names)
        self.conv.setLabel("left", {self.SIZE: "Solutions in the front", self.HV: "Hypervolume (normalised)"}
                           .get(measure, labels.get(measure, measure)))
        for i, run in enumerate(runs):
            if not run.history:
                continue
            color = theme.current().accent if single else theme.series_color(i)
            if measure in (self.SIZE, self.HV):
                h = self._front_history(run)
                x, y = h.evaluations, (h.size if measure == self.SIZE else h.hypervolume)
            elif measure in run.objective_names:
                j = run.objective_names.index(measure)
                flags = np.asarray(run.minimize_flags, dtype=bool)
                x = [h[1] or h[0] for h in run.history]
                y = []
                for _, _, F in run.history:
                    F = np.atleast_2d(F)
                    col = F[:, j] if F.size else np.array([np.nan])
                    if not np.isfinite(col).any():  # a report with no defined value: leave a gap
                        y.append(np.nan)
                        continue
                    m = float(np.nanmin(col))
                    y.append(m if flags[j] else -m)
            else:
                continue
            self.conv.plot(x, y, pen=pg.mkPen(color, width=2), symbol="o", symbolSize=4, connect="finite",
                           name=None if single else run.label)
        self._draw_fronts(runs, single)

    def _draw_fronts(self, runs: list[RunRecord], single: bool) -> None:
        if not single:
            self.history.setEnabled(False)
            self.generation.setEnabled(False)
            self.generation_label.setText(f"{len(runs)} runs")
            self.front_box.setTitle("Current fronts")
            self.front.set_layers([self._current_layer(r, theme.series_color(i)) for i, r in enumerate(runs)])
            return
        run = runs[0]
        n = len(run.history)
        self.history.setEnabled(n > 1)
        self.generation.setEnabled(n > 1)
        last_id, last_n = getattr(self, "_slider_state", (None, 0))
        # Follow a running calibration (and start a newly shown run at its end) unless the user dragged back.
        at_end = last_id != run.id or self.generation.value() >= last_n
        self.generation.blockSignals(True)
        self.generation.setMaximum(max(n, 1))
        if at_end or self.generation.value() > n:
            self.generation.setValue(max(n, 1))
        self.generation.blockSignals(False)
        self._slider_state = (run.id, n)
        k = self.generation.value()
        replaying = 0 < k < n
        if not n:
            self.generation_label.setText("")
        else:
            gen, evals, _ = run.history[k - 1]
            self.generation_label.setText(f"report {k}/{n}: generation {gen}" + (f", {evals} evaluations" if evals
                                                                              else ""))
        flags = np.asarray(run.minimize_flags, dtype=bool)
        layers: list[ParetoLayer] = []
        if self.history.isChecked() and k > 1:
            earlier = list(range(k - 1))
            if len(earlier) > self.MAX_HISTORY_LAYERS:
                earlier = sorted(set(np.linspace(0, k - 2, self.MAX_HISTORY_LAYERS).round().astype(int)))
            muted = theme.current().muted
            for m, g in enumerate(earlier):
                F = np.atleast_2d(run.history[g][2])
                if not F.size:
                    continue
                age = (g + 1) / k  # 0 (oldest) .. 1 (newest)
                layers.append(ParetoLayer(f"{run.id}:h{g}", "earlier generations", np.where(flags, F, -F),
                                          run.objective_names, muted, size=6, alpha=int(20 + 120 * age),
                                          legend=m == len(earlier) - 1, clickable=False))
        if replaying:
            F = np.atleast_2d(run.history[k - 1][2])
            layers.append(ParetoLayer(run.id, f"report {k}", np.where(flags, F, -F), run.objective_names,
                                      theme.series_color(0)))
            self.front_box.setTitle(f"Front at report {k} of {n}")
        else:
            layers.append(self._current_layer(run, theme.series_color(0)))
            self.front_box.setTitle("Final front" if run.has_results else "Current front")
        self.front.set_layers(layers)

    def _front_history(self, run: RunRecord):
        """Front statistics, recomputed only when the run has reported again."""
        cache = self.__dict__.setdefault("_fh_cache", {})
        key = (run.id, len(run.history))
        if key not in cache:
            cache.clear() if len(cache) > 32 else None
            cache[key] = front_history(run.history)
        return cache[key]

    @staticmethod
    def _current_layer(run: RunRecord, color: str) -> ParetoLayer:
        flags = np.asarray(run.minimize_flags, dtype=bool)
        if run.has_results:
            values, knee = run.display_F(), run.knee_index()
        elif run.history:
            F = np.atleast_2d(run.history[-1][2])
            values, knee = np.where(flags, F, -F), None
        else:
            values, knee = np.empty((0, len(flags))), None
        return ParetoLayer(run.id, run.label, values, run.objective_names, color, knee=knee)
