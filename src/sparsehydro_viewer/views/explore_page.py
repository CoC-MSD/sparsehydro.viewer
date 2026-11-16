"""Explore workspace: one run's trade-offs, with linked Pareto scatter, parallel
coordinates, hydrograph and unit hydrograph."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.data import Period, epoch_seconds
from ..core.evaluation import Evaluator
from ..core.runs import RunRecord
from ..core.trace import flow_parts
from ..core.uh import KernelCurve, kernel_curves
from ..services import LiveResult
from ..widgets import AxisSpec, ParallelCoordinates, ParetoLayer, ParetoPlot, TimeseriesPlot, UHPreview
from .common import num_item, objective_better, objective_labels, page_header, text_item
from .context import AppContext
from .shell.page import Page

MAX_BAND = 60


@dataclass
class _Sim:
    run_id: str
    index: int
    t: np.ndarray
    rain: np.ndarray
    observed: np.ndarray
    predicted: np.ndarray
    band: tuple[np.ndarray, np.ndarray] | None
    curves: list[KernelCurve]
    validation: dict[str, float] | None
    #: Individual hydrographs ``(label, series)`` when requested.
    parts: list[tuple[str, np.ndarray]] | None = None


def simulate_selection(run: RunRecord, frame, calibration: Period, validation: Period, index: int,
                       band_rows: list[int], components: bool = False) -> _Sim:
    """Simulate solution *index* (and a band over *band_rows*) for display.

    With *components*, also split the simulation into its individual hydrographs.
    """
    ev = Evaluator(run.model, frame, run.objectives, calibration)
    ev.evaluate(run.fixed_values)
    res = ev.evaluate_vector(run.param_names, run.pareto_X[index])
    curves = kernel_curves(ev.built, ev.dt_hours)
    parts = None
    if components:  # before the band below changes the parameters
        trace = ev.trace()
        trace.setdefault(ev.predicted_key, res.predicted)
        fields = ev.trace_fields()
        labels = {f.name: f.label for f in fields}
        parts = [(labels[n], y) for n, y in flow_parts(fields, trace, ev.predicted_key)]
    band = None
    rows = band_rows[:MAX_BAND]
    if len(rows) > 1:
        sims = ev.simulate_many(run.param_names, run.pareto_X[rows])
        band = (sims.min(axis=0), sims.max(axis=0))
    val = None
    if not validation.is_open:
        try:
            vev = Evaluator(run.model, frame, run.objectives, validation)
            vev.evaluate(run.fixed_values)
            val = vev.evaluate_vector(run.param_names, run.pareto_X[index]).objectives
        except ValueError:
            val = None
    return _Sim(run.id, index, epoch_seconds(ev.datetime), ev.rain, ev.observed, res.predicted, band, curves, val,
                parts)


class ExplorePage(Page):
    title = "Explore"
    icon_name = "nav-explore"
    uses_working_model = True

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        s = ctx.session
        self.run_box = QComboBox()
        self.run_box.setToolTip("Calibration run whose Pareto set is explored")
        self.run_box.setAccessibleName("Run to explore")
        self.run_box.currentIndexChanged.connect(self._run_changed)
        self.info = QLabel()
        self.info.setObjectName("hint")
        self.knee_action = self.action("Select knee", "Select the balanced (knee) solution", "knee",
                                       self._select_knee, shortcut="K")
        self.load_action = self.action("Load into sliders", "Make this run's model the working model with the "
                                                            "selected solution's values", "load-sliders", self._load)
        self.components_action = self.action(
            "Components", "Show the selected solution's hydrograph as the sum of its individual hydrographs",
            "components", lambda: self._simulate(), checkable=True)
        self.best_box = QComboBox()
        self.best_box.setToolTip("Select the best solution for an objective")
        self.best_box.activated.connect(self._select_best)
        top = QHBoxLayout()
        top.addWidget(QLabel("Run"))
        top.addWidget(self.run_box, 2)
        top.addWidget(self.info, 3)
        top.addWidget(QLabel("Best for:"))
        top.addWidget(self.best_box)

        self.pareto = ParetoPlot(labels=objective_labels(), better=objective_better())
        self.parallel = ParallelCoordinates()
        self.ts = TimeseriesPlot()
        self.uh = UHPreview(show_table=False)
        self.params = QTableWidget(0, 5)
        self.params.setAccessibleName("Parameters of the selected solution")
        self.params.setHorizontalHeaderLabels(["Parameter", "Value", "Lower", "Upper", "Position"])
        self.params.verticalHeader().setVisible(False)
        self.params.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.params.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.selection_info = QLabel()
        self.selection_info.setWordWrap(True)

        def boxed(title: str, w: QWidget) -> QGroupBox:
            g = QGroupBox(title)
            lay = QVBoxLayout(g)
            lay.addWidget(w)
            return g

        pc_hint = QLabel("Drag along an axis to filter, click an axis to clear, click a line to select, "
                         "right-click an axis for options. Objectives are oriented so better is up.")
        pc_hint.setObjectName("hint")
        pc_hint.setWordWrap(True)
        pc_box = QGroupBox("Parallel coordinates (objectives * and parameters)")
        pl = QVBoxLayout(pc_box)
        pl.addWidget(self.parallel, 1)
        pl.addWidget(pc_hint)
        top_split = QSplitter()
        top_split.addWidget(boxed("Objective space", self.pareto))
        top_split.addWidget(pc_box)
        top_split.setStretchFactor(1, 2)
        side = QSplitter(Qt.Orientation.Vertical)
        side.addWidget(boxed("Unit hydrograph", self.uh))
        sel_box = QGroupBox("Selected solution")
        sl = QVBoxLayout(sel_box)
        sl.addWidget(self.selection_info)
        sl.addWidget(self.params, 1)
        side.addWidget(sel_box)
        bottom = QSplitter()
        bottom.addWidget(boxed("Hydrograph (calibration period; band = filtered solutions)", self.ts))
        bottom.addWidget(side)
        bottom.setStretchFactor(0, 2)
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top_split)
        main.addWidget(bottom)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Explore", "Inspect one run's Pareto set: choose a trade-off, see its "
                                             "hydrograph and unit hydrograph, and compare it with the slider point."))
        lay.addLayout(top)
        lay.addWidget(main, 1)

        self._run: RunRecord | None = None
        self._brushed: list[int] = []
        self._pending_job = None
        s.runsChanged.connect(self.refresh_runs)
        s.runUpdated.connect(lambda _rid: self.refresh_runs())
        s.selectionChanged.connect(self._selection_changed)
        s.selectionChanged.connect(lambda *_: self.contextChanged.emit())
        s.projectChanged.connect(self.refresh_runs)
        self._pareto_rows: list[int] | None = None  # layer index -> run index while filtered
        self._pareto_other: list[int] = []
        self.pareto.pointClicked.connect(self._pareto_clicked)
        self.parallel.rowClicked.connect(lambda i: self._run and s.select(self._run.id, [i]))
        self.parallel.selectionChanged.connect(self._brush_changed)
        ctx.controller.result.connect(self._live)
        self.refresh_runs()

    # ------------------------------------------------------------------ shell

    def context_actions(self):
        return [self.knee_action, self.load_action, None, self.components_action]

    def active_chart(self):
        return self.ts

    def status_text(self) -> str:
        s = self.ctx.session
        if self._run is None or s.selected_run != self._run.id or not s.selected_solutions:
            return ""
        return f"{self._run.label}: solution #{s.selected_solutions[0]}"

    # ------------------------------------------------------------------ runs

    def refresh_runs(self) -> None:
        current = self.run_box.currentData()
        runs = [r for r in self.ctx.session.project.runs if r.has_results]
        self.run_box.blockSignals(True)
        self.run_box.clear()
        for r in runs:
            self.run_box.addItem(f"{r.label}  ({r.n_solutions} solutions)", r.id)
        idx = self.run_box.findData(current)
        self.run_box.setCurrentIndex(idx if idx >= 0 else len(runs) - 1)
        self.run_box.blockSignals(False)
        if self.run_box.currentData() != (self._run.id if self._run else None):
            self._run_changed()

    def show_run(self, run_id: str) -> None:
        self.refresh_runs()
        i = self.run_box.findData(run_id)
        if i >= 0:
            self.run_box.setCurrentIndex(i)

    def _run_changed(self) -> None:
        self._run = self.ctx.session.run(self.run_box.currentData())
        run = self._run
        if run is None:
            self.info.setText("No finished runs yet.")
            self.pareto.set_layers([])
            self.parallel.set_data([], np.empty((0, 0)))
            return
        labels = objective_labels(run.objective_names)
        self.info.setText(f"{run.model.display_label} | {run.n_params_calibrated} of {run.n_params_total} "
                          f"parameters calibrated | dataset {run.dataset}")
        self.best_box.clear()
        for n in run.objective_names:
            self.best_box.addItem(labels.get(n, n), n)
        knee = run.knee_index()
        self.pareto.set_layers([ParetoLayer(run.id, run.label, run.display_F(), run.objective_names,
                                            theme.series_color(0), knee=knee)])
        better = objective_better(run.objective_names)
        axes = [AxisSpec(n, labels.get(n, n), better.get(n) or None, kind="objective") for n in run.objective_names]
        axes += [AxisSpec(p, p) for p in run.param_names]
        self.parallel.set_data(axes, np.hstack([run.display_F(), run.pareto_X]),
                               group_labels=[run.label], group_colors=[theme.series_color(0)])
        self.ctx.session.select(run.id, [knee])

    # ------------------------------------------------------------------ selection

    def _select_knee(self) -> None:
        if self._run:
            self.ctx.session.select(self._run.id, [self._run.knee_index()])

    def _select_best(self) -> None:
        if self._run and self.best_box.currentData():
            self.ctx.session.select(self._run.id, [self._run.best_index(self.best_box.currentData())])

    def _load(self) -> None:
        s = self.ctx.session
        if self._run and s.selected_run == self._run.id and s.selected_solutions:
            s.load_solution(self._run.id, s.selected_solutions[0])

    def _brush_changed(self, rows: list[int]) -> None:
        self._brushed = rows
        run = self._run
        if run is None:
            return
        F = run.display_F()
        if len(rows) < run.n_solutions:
            # Layer indices refer to subsets; _pareto_clicked translates them back.
            self._pareto_rows = list(rows)
            self._pareto_other = [i for i in range(run.n_solutions) if i not in set(rows)]
            self.pareto.set_layers([
                ParetoLayer(run.id, run.label, F[self._pareto_rows], run.objective_names, theme.series_color(0)),
                ParetoLayer(run.id + ":out", "filtered out", F[self._pareto_other], run.objective_names,
                            theme.current().muted, faded=True, size=6),
            ])
        else:
            self._pareto_rows, self._pareto_other = None, []
            self.pareto.set_layers([ParetoLayer(run.id, run.label, F, run.objective_names, theme.series_color(0),
                                                knee=run.knee_index())])
        self._selection_changed(run.id, self.ctx.session.selected_solutions)

    def _pareto_clicked(self, key: str, i: int) -> None:
        if self._run is None:
            return
        if key.endswith(":out"):
            i = self._pareto_other[i]
        elif self._pareto_rows is not None:
            i = self._pareto_rows[i]
        self.ctx.session.select(self._run.id, [i])

    def _selection_changed(self, run_id: str, indices: list[int]) -> None:
        if self._run is None or run_id != self._run.id:
            return
        self.parallel.set_highlight(indices)
        sel = indices
        if self._pareto_rows is not None:
            pos = {r: k for k, r in enumerate(self._pareto_rows)}
            sel = [pos[i] for i in indices if i in pos]
        self.pareto.set_selection(run_id, sel)
        self._simulate()

    def _simulate(self) -> None:
        s = self.ctx.session
        run = self._run
        if run is None or s.selected_run != run.id or not s.selected_solutions:
            return
        try:
            frame = s.frame(run.dataset)
            ds = s.project.dataset(run.dataset)
        except Exception as exc:
            self.selection_info.setText(f"Dataset {run.dataset!r} unavailable: {exc}")
            return
        idx = s.selected_solutions[0]
        brushed = self._brushed if 1 < len(self._brushed) < run.n_solutions else []
        cal, val = ds.calibration, ds.validation
        self._pending_job = (run.id, idx)
        components = self.components_action.isChecked()

        def work(_ctx):
            return simulate_selection(run, frame, cal, val, idx, brushed, components)

        self.submit_job(f"Simulate {run.label} #{idx}", work, on_done=self._show_sim)

    def _show_sim(self, sim: _Sim) -> None:
        if self._pending_job != (sim.run_id, sim.index) or self._run is None:
            return  # a newer request superseded this one
        run = self._run
        th = theme.current()
        self.ts.set_data(sim.t, sim.rain, sim.observed)
        if sim.band is not None:
            self.ts.set_band("band", sim.t, sim.band[0], sim.band[1], th.predicted)
        else:
            self.ts.remove_band("band")
        self.ts.set_curve("sel", sim.t, sim.predicted, color=th.selection, width=2, name=f"solution #{sim.index}")
        self.ts.set_stack("components", sim.t, [(label, y, theme.series_color(i))
                                                for i, (label, y) in enumerate(sim.parts or [])])
        self.uh.set_curves(sim.curves)
        F = run.display_F()[sim.index]
        labels = objective_labels(run.objective_names)
        parts = [f"{labels.get(n, n)} = <b>{v:.4g}</b>" for n, v in zip(run.objective_names, F)]
        if sim.validation:
            parts.append("validation: " + ", ".join(f"{labels.get(n, n)} {v:.4g}" for n, v in sim.validation.items()))
        self.selection_info.setText(f"Solution #{sim.index}: " + "; ".join(parts))
        names = run.param_names
        lo = {p: run.pareto_X[:, k].min() for k, p in enumerate(names)}
        vals = run.solution_values(sim.index)
        bounds = self._bounds(run)
        self.params.setRowCount(len(vals))
        for r, (n, v) in enumerate(vals.items()):
            b = bounds.get(n, (np.nan, np.nan))
            pos = (v - b[0]) / (b[1] - b[0]) * 100 if b[1] > b[0] else np.nan
            item = text_item(n + ("" if n in lo else "  (fixed)"))
            self.params.setItem(r, 0, item)
            self.params.setItem(r, 1, num_item(v))
            self.params.setItem(r, 2, num_item(b[0]))
            self.params.setItem(r, 3, num_item(b[1]))
            self.params.setItem(r, 4, num_item(pos, "{:.0f}%"))
            if np.isfinite(pos) and (pos < 2 or pos > 98) and n in lo:
                for c in range(5):
                    self.params.item(r, c).setToolTip("At a bound: consider widening it")
                    self.params.item(r, c).setForeground(Qt.GlobalColor.darkYellow)

    @staticmethod
    def _bounds(run: RunRecord) -> dict[str, tuple[float, float]]:
        from ..core.catalog import CATALOG

        return {p.name: (p.lower, p.upper) for p in CATALOG.describe_parameters(run.model)}

    # ------------------------------------------------------------------ live slider point

    def _live(self, res: LiveResult) -> None:
        run = self._run
        s = self.ctx.session
        if run is None or s.model_spec.structure_key != run.model.structure_key:
            self.pareto.set_marker(None)
            self.parallel.set_extra_line(None)
            return
        if res.calibration.objectives.keys() >= set(run.objective_names):
            self.pareto.set_marker(res.calibration.objectives, "sliders")
        values = dict(res.calibration.values)
        values.update(res.calibration.objectives)
        self.parallel.set_extra_line(values, "sliders")
