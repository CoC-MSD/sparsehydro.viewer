"""Explore workspace: one run's trade-offs, with linked Pareto scatter, parallel
coordinates, hydrograph and unit hydrograph.

Selection is the session's (:class:`~sparsehydro_viewer.core.selection.SolutionSelection`):
a click, Ctrl+click or Shift-drag in the scatter, a clicked line or a brush in
the parallel coordinates all write it, and every chart here (and on Compare)
redraws from it. The hydrograph shows one line per selected solution over a
filled band between the minimum and maximum of the selection, or of the whole
Pareto set when a single solution is selected.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.data import Period
from ..core.runs import RunRecord
from ..core.selection import SolutionRef, SolutionSelection
from ..core.simulate import MAX_LINES, SolutionSeries, simulate_solutions
from ..services import LiveResult
from ..widgets import AxisSpec, ParallelCoordinates, ParetoLayer, ParetoPlot, TimeseriesPlot, UHPreview
from .common import (
    history_key,
    history_layers,
    num_item,
    objective_better,
    objective_labels,
    page_header,
    parse_history_key,
    text_item,
)
from .context import AppContext
from .shell.page import Page


def simulate_selection(run: RunRecord, frame, calibration: Period, validation: Period, index: int,
                       band_rows: list[int], components: bool = False) -> SolutionSeries:
    """Simulate solution *index* (and a band over *band_rows*) on the calibration period.

    Kept for scripts and tests; the page uses :func:`~sparsehydro_viewer.core.simulate.simulate_solutions`.
    """
    ref = SolutionRef(run.id, index)
    return simulate_solutions(run, frame, [ref], calibration, primary=ref, band_rows=band_rows,
                              validation=validation, components=components)


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
                                                            "primary selected solution's values", "load-sliders",
                                       self._load)
        self.components_action = self.action(
            "Components", "Show the primary selected solution's hydrograph as the sum of its individual hydrographs",
            "components", lambda: self._simulate(), checkable=True)
        self.history_action = self.action(
            "Earlier generations", "Show the fronts the run reported on its way, fainter the older; their solutions "
            "can be selected and simulated when the run kept their parameter sets", "restore",
            lambda: self._history_toggled(), checkable=True)
        self.best_box = QComboBox()
        self.best_box.setToolTip("Select the best solution for an objective")
        self.best_box.setAccessibleName("Select the best solution for an objective")
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
        self.ts.setToolTip("One line per selected solution (up to 12) over the band between the minimum and "
                           "maximum of the selection - or of the whole Pareto set when one solution is selected")
        self.uh = UHPreview(show_table=False)
        self.params = QTableWidget(0, 5)
        self.params.setAccessibleName("Parameters of the primary selected solution")
        self.params.setHorizontalHeaderLabels(["Parameter", "Value", "Lower", "Upper", "Position"])
        self.params.verticalHeader().setVisible(False)
        self.params.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.params.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.selected = QTableWidget(0, 0)
        self.selected.setAccessibleName("Selected solutions")
        self.selected.setToolTip("Every selected solution with its objectives and parameters; click a row to make "
                                 "it the primary one (the one the parameters, unit hydrograph and components show)")
        self.selected.verticalHeader().setVisible(False)
        self.selected.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.selected.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.selected.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.selected.itemSelectionChanged.connect(self._selected_row_chosen)
        self.selection_info = QLabel()
        self.selection_info.setWordWrap(True)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.addTab(self.params, "Primary")
        self.detail_tabs.addTab(self.selected, "Selected (0)")

        def boxed(title: str, w: QWidget) -> QGroupBox:
            g = QGroupBox(title)
            lay = QVBoxLayout(g)
            lay.addWidget(w)
            return g

        pc_hint = QLabel("Click a line or point to select it, Ctrl+click to add or remove; Shift+drag in the "
                         "scatter or drag along an axis to select several (click the axis to clear). Right-click "
                         "an axis for options. Objectives are oriented so better is up.")
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
        side.addWidget(boxed("Unit hydrograph (primary solution)", self.uh))
        sel_box = QGroupBox("Selected solutions")
        sl = QVBoxLayout(sel_box)
        sl.addWidget(self.selection_info)
        sl.addWidget(self.detail_tabs, 1)
        side.addWidget(sel_box)
        bottom = QSplitter()
        bottom.addWidget(boxed("Hydrograph (calibration period): selected solutions and their range", self.ts))
        bottom.addWidget(side)
        bottom.setStretchFactor(0, 2)
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top_split)
        main.addWidget(bottom)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Explore", "Inspect one run's Pareto set: select one or several trade-offs in "
                                             "either chart, see their hydrographs and range, and compare them with "
                                             "the slider point."))
        lay.addLayout(top)
        lay.addWidget(main, 1)

        self._run: RunRecord | None = None
        self._pending: tuple | None = None
        self._lines: list[str] = []  # curve keys drawn on the time series
        self._filling = False
        self._pareto_rows: list[int] | None = None  # layer index -> run index while filtered
        self._pareto_other: list[int] = []
        s.runsChanged.connect(self.refresh_runs)
        s.runUpdated.connect(lambda _rid: self.refresh_runs())
        s.projectChanged.connect(self.refresh_runs)
        s.solutionSelectionChanged.connect(self._selection_changed)
        s.solutionSelectionChanged.connect(lambda *_: self.contextChanged.emit())
        s.solutionFilterChanged.connect(self._filter_changed)
        self.pareto.pointPicked.connect(self._pareto_picked)
        self.pareto.rangeSelected.connect(self._pareto_range)
        self.pareto.selectionCleared.connect(lambda: self._run and s.select_in_run(self._run.id, []))
        self.parallel.rowPicked.connect(lambda i, add: self._pick(SolutionRef(self._run.id, i), add)
                                        if self._run else None)
        self.parallel.selectionChanged.connect(self._brush_changed)
        ctx.controller.result.connect(self._live)
        self.refresh_runs()

    # ------------------------------------------------------------------ shell

    def context_actions(self):
        return [self.knee_action, self.load_action, None, self.components_action, self.history_action]

    def active_chart(self):
        return self.ts

    def status_text(self) -> str:
        refs = self._refs()
        if self._run is None or not refs:
            return ""
        more = f" (+{len(refs) - 1} selected)" if len(refs) > 1 else ""
        return f"{self._run.label}: solution {refs[0].label()}{more}"

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
        s = self.ctx.session
        self._run = s.run(self.run_box.currentData())
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
        better = objective_better(run.objective_names)
        axes = [AxisSpec(n, labels.get(n, n), better.get(n) or None, kind="objective") for n in run.objective_names]
        axes += [AxisSpec(p, p) for p in run.param_names]
        self._filling = True  # set_data reports "all rows": not a brush
        try:
            self.parallel.set_data(axes, np.hstack([run.display_F(), run.pareto_X]),
                                   group_labels=[run.label], group_colors=[theme.series_color(0)])
        finally:
            self._filling = False
        self._draw_pareto()
        # Nothing is written to the shared selection here: with none of this run's solutions selected the page
        # shows the knee by default (see _refs), so merely showing a run does not select anything elsewhere.
        self._selection_changed()

    # ------------------------------------------------------------------ selection (writes the session)

    def _refs(self) -> list[SolutionRef]:
        """This run's selected solutions, the primary first; the knee when none is selected."""
        if self._run is None:
            return []
        return self.ctx.session.selection.of_run(self._run.id) or [SolutionRef(self._run.id, self._run.knee_index())]

    def _pick(self, ref: SolutionRef, add: bool) -> None:
        """A click selects only that solution; Ctrl+click adds it to, or removes it from, the selection."""
        s = self.ctx.session
        if add and not s.selection.of_run(ref.run_id):
            # Ctrl+click while the default knee is shown: keep it and add the clicked solution.
            shown = [r for r in self._refs() if r != ref]
            s.select_in_run(ref.run_id, [*shown, ref], ref)
        elif add:
            s.toggle_selected(ref)
        else:
            s.select_in_run(ref.run_id, [ref], ref)

    def _select_knee(self) -> None:
        if self._run:
            self.ctx.session.select(self._run.id, [self._run.knee_index()])

    def _select_best(self) -> None:
        if self._run and self.best_box.currentData():
            self.ctx.session.select(self._run.id, [self._run.best_index(self.best_box.currentData())])

    def _load(self) -> None:
        refs = self._refs()
        if self._run and refs:
            self.ctx.session.load_solution(self._run.id, refs[0].index, refs[0].generation)

    def _layer_ref(self, key: str, i: int) -> SolutionRef:
        """The solution behind point *i* of scatter layer *key* (final front, filtered subsets or a report)."""
        run_id = self._run.id  # type: ignore[union-attr]
        _rid, report = parse_history_key(key)
        if report is not None:
            return SolutionRef(run_id, i, report)
        if key.endswith(":out"):
            return SolutionRef(run_id, self._pareto_other[i])
        return SolutionRef(run_id, self._pareto_rows[i] if self._pareto_rows is not None else i)

    def _pareto_picked(self, key: str, i: int, add: bool) -> None:
        if self._run is not None:
            self._pick(self._layer_ref(key, i), add)

    def _pareto_range(self, picked: dict, add: bool) -> None:
        run = self._run
        if run is None:
            return
        refs = sorted({self._layer_ref(key, i) for key, idx in picked.items() for i in idx},
                      key=lambda r: (-1 if r.generation is None else r.generation, r.index))
        self.ctx.session.select_in_run(run.id, refs, add=add)

    def _history_toggled(self) -> None:
        run = self._run
        if run is not None and self.history_action.isChecked() and not run.history:
            self.selection_info.setText("This run has no recorded earlier generations.")
        self._draw_pareto()
        self._mark_selection()

    def _brush_changed(self, rows: list[int]) -> None:
        """A brush in the parallel coordinates filters the run everywhere and selects what passes it."""
        run = self._run
        if run is None or self._filling:
            return
        s = self.ctx.session
        filtering = len(rows) < run.n_solutions
        was_filtering = run.id in s.filter_rows
        s.set_filter(run.id, rows if filtering else None)
        primary = s.selection.primary
        if filtering:
            refs = [SolutionRef(run.id, i) for i in rows]
            s.select_in_run(run.id, refs, primary if primary in refs else None)
        elif was_filtering:  # brush cleared: back to the primary solution alone
            keep = [primary] if primary is not None and primary.run_id == run.id else []
            s.select_in_run(run.id, keep)

    def _selected_row_chosen(self) -> None:
        if self._filling or self._run is None:
            return
        rows = {i.row() for i in self.selected.selectedIndexes()}
        refs = self._refs()
        if len(rows) == 1 and (r := rows.pop()) < len(refs) and refs[r] != refs[0]:
            self.ctx.session.select_in_run(self._run.id, refs, refs[r])

    # ------------------------------------------------------------------ drawing (reads the session)

    def _filter_changed(self, run_id: str) -> None:
        if self._run is not None and run_id == self._run.id:
            self._draw_pareto()
            self._mark_selection()

    def _draw_pareto(self) -> None:
        run = self._run
        if run is None:
            return
        F = run.display_F()
        rows = self.ctx.session.filter_rows.get(run.id)
        if rows is not None and len(rows) < run.n_solutions:
            # Layer indices refer to subsets; _layer_index translates them back.
            self._pareto_rows = list(rows)
            inside = set(rows)
            self._pareto_other = [i for i in range(run.n_solutions) if i not in inside]
            layers = [
                ParetoLayer(run.id, run.label, F[self._pareto_rows], run.objective_names, theme.series_color(0)),
                ParetoLayer(run.id + ":out", "filtered out", F[self._pareto_other], run.objective_names,
                            theme.current().muted, faded=True, size=6),
            ]
        else:
            self._pareto_rows, self._pareto_other = None, []
            layers = [ParetoLayer(run.id, run.label, F, run.objective_names, theme.series_color(0),
                                  knee=run.knee_index())]
        if self.history_action.isChecked():  # behind the front, not setting the axes
            layers = history_layers(run, color=theme.current().muted) + layers
        self.pareto.set_layers(layers)

    def _mark_selection(self) -> None:
        """Show the session's selection in the scatter and the parallel coordinates."""
        run = self._run
        if run is None:
            return
        indices = [r.index for r in self._refs() if r.is_final]
        self.parallel.set_highlight(indices, indices[0] if indices else None)
        marks: dict[str, list[int]] = {}
        primary = None
        pos = {r: k for k, r in enumerate(self._pareto_rows)} if self._pareto_rows is not None else None
        out = {r: k for k, r in enumerate(self._pareto_other)}
        refs = self._refs()
        for ref in refs:
            i = ref.index
            if not ref.is_final:
                key, k = history_key(run.id, ref.generation), i
            elif pos is None:
                key, k = run.id, i
            else:
                key, k = (run.id, pos[i]) if i in pos else (run.id + ":out", out[i])
            marks.setdefault(key, []).append(k)
            if ref == refs[0]:
                primary = (key, k)
        self.pareto.set_selection(marks, primary=primary)

    def _selection_changed(self, _selection: SolutionSelection | None = None) -> None:
        if self._run is None:
            return
        self._mark_selection()
        self._simulate()

    def _simulate(self) -> None:
        s = self.ctx.session
        run = self._run
        if run is None:
            return
        try:
            frame = s.frame(run.dataset)
            ds = s.project.dataset(run.dataset)
        except Exception as exc:
            self.selection_info.setText(f"Dataset {run.dataset!r} unavailable: {exc}")
            return
        refs = self._refs()
        final = [r.index for r in refs if r.is_final]
        if len(final) > 1:
            band_rows, band_label = final, f"Range of the {len(final)} selected solutions"
        else:
            band_rows, band_label = list(range(run.n_solutions)), f"Pareto range ({run.n_solutions} solutions)"
        cal, val = ds.calibration, ds.validation
        components = self.components_action.isChecked()
        primary = refs[0] if refs else None
        self._pending = (run.id, tuple(refs), components)
        token = self._pending
        cache = self.ctx.sim_cache

        def work(_ctx):
            return token, simulate_solutions(run, frame, refs, cal, primary=primary, band_rows=band_rows,
                                             band_label=band_label, validation=val, components=components,
                                             cache=cache)

        self.submit_job(f"Simulate {run.label}", work, on_done=lambda out: self._show_sim(*out))

    def _show_sim(self, token: tuple, sim: SolutionSeries) -> None:
        if self._pending != token or self._run is None:
            return  # a newer request superseded this one
        run = self._run
        th = theme.current()
        self.ts.set_data(sim.t, sim.rain, sim.observed)
        if sim.band is not None:
            self.ts.set_band("band", sim.t, sim.band[0], sim.band[1], th.predicted, name=sim.band_label)
        else:
            self.ts.remove_band("band")
        keys = []
        for k, (ref, y) in enumerate(sim.lines.items()):
            key = f"sol:{ref.generation}:{ref.index}"
            keys.append(key)
            self.ts.remove_curve(key)  # names and styles change with the selection
            if ref == sim.primary:
                self.ts.set_curve(key, sim.t, y, color=th.selection, width=2.4, name=f"solution {ref.label()}")
            else:
                self.ts.set_curve(key, sim.t, y, color=theme.series_color(k), width=1.4, dashed=k % 2 == 0,
                                  name=f"solution {ref.label()}")
        for key in self._lines:
            if key not in keys:
                self.ts.remove_curve(key)
        self._lines = keys
        self.ts.set_stack("components", sim.t, [(label, y, theme.series_color(i))
                                                for i, (label, y) in enumerate(sim.parts or [])])
        self.uh.set_curves(sim.curves)
        self._fill_selected(run)
        if sim.primary is None:
            self.selection_info.setText("No solution selected: the band is the range of the whole Pareto set. "
                                        "Click a point or a line to select one.")
            self.params.setRowCount(0)
            return
        labels = objective_labels(run.objective_names)
        text = f"Solution {sim.primary.label()}"
        if sim.primary.is_final:
            F = run.display_F()[sim.primary.index]
            text += ": " + "; ".join(f"{labels.get(n, n)} = <b>{v:.4g}</b>" for n, v in zip(run.objective_names, F))
        if sim.validation:
            text += "; validation: " + ", ".join(f"{labels.get(n, n)} {v:.4g}" for n, v in sim.validation.items())
        if sim.n_selected > 1:
            text += f"<br>{sim.n_selected} solutions selected"
            if sim.n_selected > MAX_LINES:
                text += f": lines for the first {MAX_LINES}, the band covers all of them"
        self.selection_info.setText(text)
        self._fill_params(run, sim.primary)

    def _fill_params(self, run: RunRecord, ref: SolutionRef) -> None:
        names = run.param_names
        vals = run.solution_values(ref.index) if ref.is_final else run.solution_values(ref.index, ref.generation)
        bounds = self._bounds(run)
        self.params.setRowCount(len(vals))
        for r, (n, v) in enumerate(vals.items()):
            b = bounds.get(n, (np.nan, np.nan))
            pos = (v - b[0]) / (b[1] - b[0]) * 100 if b[1] > b[0] else np.nan
            item = text_item(n + ("" if n in names else "  (fixed)"))
            self.params.setItem(r, 0, item)
            self.params.setItem(r, 1, num_item(v))
            self.params.setItem(r, 2, num_item(b[0]))
            self.params.setItem(r, 3, num_item(b[1]))
            self.params.setItem(r, 4, num_item(pos, "{:.0f}%"))
            if np.isfinite(pos) and (pos < 2 or pos > 98) and n in names:
                for c in range(5):
                    self.params.item(r, c).setToolTip("At a bound: consider widening it")
                    self.params.item(r, c).setForeground(Qt.GlobalColor.darkYellow)

    def _fill_selected(self, run: RunRecord) -> None:
        """Table of every selected solution: objectives then calibrated parameters."""
        refs = [r for r in self._refs() if r.is_final]
        labels = objective_labels(run.objective_names)
        cols = ["Solution"] + [labels.get(n, n) for n in run.objective_names] + list(run.param_names)
        F = run.display_F()
        self._filling = True
        try:
            self.selected.clear()
            self.selected.setColumnCount(len(cols))
            self.selected.setHorizontalHeaderLabels(cols)
            self.selected.setRowCount(len(refs))
            for r, ref in enumerate(refs):
                self.selected.setItem(r, 0, text_item(ref.label() + ("  (primary)" if r == 0 else "")))
                for c, v in enumerate([*F[ref.index], *run.pareto_X[ref.index]], start=1):
                    self.selected.setItem(r, c, num_item(float(v)))
            self.selected.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        finally:
            self._filling = False
        self.detail_tabs.setTabText(1, f"Selected ({len(refs)})")

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
