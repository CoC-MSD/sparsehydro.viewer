"""Compare workspace: alternative models side by side, with parameter count as a
first-class axis so the most parsimonious adequate model stands out."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.data import epoch_seconds
from ..core.diagnostics import ComplexityPoint, complexity_front, fit_statistics
from ..core.evaluation import Evaluator
from ..core.runs import RunRecord
from ..widgets import AxisSpec, ParallelCoordinates, ParetoLayer, ParetoPlot, TimeseriesPlot
from .common import num_item, objective_better, objective_labels, page_header, text_item, with_toolbar
from .context import AppContext

SCORE_COLUMNS = ["cal NSE", "cal RMSE", "AIC", "BIC", "val NSE", "val RMSE"]
PARAMS_AXIS = "__n_params__"


@dataclass
class _Score:
    run_id: str
    index: int
    cal: dict[str, float]
    val: dict[str, float] | None
    t: np.ndarray
    predicted: np.ndarray
    observed: np.ndarray
    rain: np.ndarray
    dataset: str


def score_run(run: RunRecord, frame, calibration, validation, index: int) -> _Score:
    """Fit statistics of one solution on the calibration and validation periods."""
    k = run.n_params_calibrated
    ev = Evaluator(run.model, frame, run.objectives, calibration)
    ev.evaluate(run.fixed_values)
    res = ev.evaluate_vector(run.param_names, run.pareto_X[index])
    cal = fit_statistics(ev.observed, res.predicted, k)
    val = None
    if not validation.is_open:
        try:
            vev = Evaluator(run.model, frame, run.objectives, validation)
            vev.evaluate(run.fixed_values)
            vres = vev.evaluate_vector(run.param_names, run.pareto_X[index])
            val = fit_statistics(vev.observed, vres.predicted, k)
        except ValueError:
            val = None
    return _Score(run.id, index, cal, val, epoch_seconds(ev.datetime), res.predicted, ev.observed, ev.rain,
                  run.dataset)


class ComparePage(QWidget):
    title = "Compare"
    uses_working_model = True

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        s = ctx.session
        self.table = QTableWidget(0, 0)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self._check_changed)
        self.metric = QComboBox()
        self.metric.setToolTip("Performance measure plotted against parameter count")
        self.metric.currentIndexChanged.connect(self._draw)
        self.solution = QComboBox()
        self.solution.addItem("Knee solution", "knee")
        self.solution.addItem("Best for the plotted objective", "best")
        self.solution.currentIndexChanged.connect(self._solution_changed)
        score = QPushButton("Score selected runs")
        score.setObjectName("primary")
        score.setToolTip("Simulate each checked run's chosen solution on the calibration and validation periods "
                         "and compute NSE, RMSE, AIC and BIC")
        score.clicked.connect(self._score)
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("Measure"))
        ctl.addWidget(self.metric, 1)
        ctl.addWidget(QLabel("Solution"))
        ctl.addWidget(self.solution, 1)
        ctl.addStretch(1)
        ctl.addWidget(score)
        tbox = QGroupBox("Runs (tick to compare)")
        tl = QVBoxLayout(tbox)
        tl.addLayout(ctl)
        tl.addWidget(self.table, 1)
        note = QLabel("AIC/BIC assume independent Gaussian errors; with autocorrelated flows treat them as a "
                      "ranking aid between models fitted to the same period, not as a test.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        tl.addWidget(note)

        self.complexity = pg.PlotWidget()
        self.complexity.showGrid(x=True, y=True, alpha=0.15)
        self.complexity.setLabel("bottom", "Calibrated parameters")
        theme.plain_axes(self.complexity)
        self.complexity.getViewBox().setDefaultPadding(0.15)  # room for the run labels
        self.parallel = ParallelCoordinates()
        self.pareto = ParetoPlot(labels=objective_labels(), better=objective_better())
        self.ts = TimeseriesPlot()

        def boxed(title: str, w: QWidget) -> QGroupBox:
            g = QGroupBox(title)
            lay = QVBoxLayout(g)
            lay.addWidget(w)
            return g

        top = QSplitter()
        top.addWidget(tbox)
        top.addWidget(boxed("Complexity vs performance (line = models not beaten by a simpler one)",
                            self.complexity))
        top.setStretchFactor(0, 3)
        top.setStretchFactor(1, 2)
        mid = QSplitter()
        mid.addWidget(boxed("All Pareto solutions; parameter count is an axis", self.parallel))
        mid.addWidget(boxed("Pareto fronts", self.pareto))
        mid.setStretchFactor(0, 3)
        mid.setStretchFactor(1, 2)
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(mid)
        main.addWidget(boxed("Chosen solutions (calibration period)", with_toolbar(self.ts)))
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Compare", "Compare alternative models. Prefer the simplest model whose "
                                             "performance is close to the best; the step line shows where extra "
                                             "parameters stop paying for themselves."))
        lay.addWidget(main, 1)
        self._checked: set[str] = set()
        self._seen: set[str] = set()
        self._scores: dict[str, _Score] = {}
        self._filling = False
        s.runsChanged.connect(self.refresh)
        s.runUpdated.connect(lambda _rid: self.refresh())
        s.projectChanged.connect(self._reset)
        self.parallel.rowClicked.connect(self._row_clicked)
        self.refresh()

    # ------------------------------------------------------------------ data

    def _reset(self) -> None:
        self._checked.clear()
        self._seen.clear()
        self._scores.clear()
        self.refresh()

    def _runs(self) -> list[RunRecord]:
        return [r for r in self.ctx.session.project.runs if r.has_results]

    def _selected_runs(self) -> list[RunRecord]:
        return [r for r in self._runs() if r.id in self._checked]

    def _objectives(self) -> list[str]:
        names: list[str] = []
        for r in self._runs():
            for n in r.objective_names:
                if n not in names:
                    names.append(n)
        return names

    def _solution_index(self, run: RunRecord) -> int:
        metric = self.metric.currentData()
        if self.solution.currentData() == "best" and metric in run.objective_names:
            return run.best_index(metric)
        return run.knee_index()

    # ------------------------------------------------------------------ table

    def refresh(self) -> None:
        runs = self._runs()
        ids = {r.id for r in runs}
        self._checked |= ids - self._seen  # newly finished runs start ticked; unticked ones stay unticked
        self._seen = ids
        self._checked &= ids
        objs = self._objectives()
        labels = objective_labels(objs)
        cur = self.metric.currentData()
        self.metric.blockSignals(True)
        self.metric.clear()
        for n in objs:
            self.metric.addItem(f"{labels.get(n, n)} (best in run)", n)
        for c in SCORE_COLUMNS:
            self.metric.addItem(c + " (scored)", c)
        i = self.metric.findData(cur)
        self.metric.setCurrentIndex(i if i >= 0 else 0)
        self.metric.blockSignals(False)

        cols = ["Run", "Model", "Dataset", "k cal", "k total", "Solutions"] + \
               [f"best {labels.get(n, n)}" for n in objs] + SCORE_COLUMNS
        self._filling = True
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(runs))
        for r, run in enumerate(runs):
            first = text_item(run.label, run.id)
            first.setFlags(first.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            first.setCheckState(Qt.CheckState.Checked if run.id in self._checked else Qt.CheckState.Unchecked)
            first.setForeground(pg.mkColor(theme.series_color(self._color_index(run.id))))
            cells: list[QTableWidgetItem] = [first, text_item(run.model.display_label), text_item(run.dataset),
                                             num_item(run.n_params_calibrated), num_item(run.n_params_total),
                                             num_item(run.n_solutions)]
            D = run.display_F()
            better = objective_better(run.objective_names)
            for n in objs:
                if n in run.objective_names:
                    col = D[:, run.objective_names.index(n)]
                    cells.append(num_item(float(np.nanmax(col) if better.get(n) == "max" else np.nanmin(col))))
                else:
                    cells.append(num_item(None))
            sc = self._scores.get(run.id)
            vals = [sc.cal.get("NSE"), sc.cal.get("RMSE"), sc.cal.get("AIC"), sc.cal.get("BIC"),
                    sc.val.get("NSE") if sc.val else None, sc.val.get("RMSE") if sc.val else None] if sc \
                else [None] * len(SCORE_COLUMNS)
            cells += [num_item(v) for v in vals]
            for c, it in enumerate(cells):
                self.table.setItem(r, c, it)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSortingEnabled(True)
        self._filling = False
        self._draw()

    def _color_index(self, run_id: str) -> int:
        ids = [r.id for r in self._runs()]
        return ids.index(run_id) if run_id in ids else 0

    def _check_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 0:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._checked.add(rid)
        else:
            self._checked.discard(rid)
        self._draw()

    def _solution_changed(self) -> None:
        self._scores.clear()
        self.refresh()

    # ------------------------------------------------------------------ scoring

    def _score(self) -> None:
        s = self.ctx.session
        jobs = []
        for run in self._selected_runs():
            try:
                frame, ds = s.frame(run.dataset), s.project.dataset(run.dataset)
            except Exception:
                continue
            jobs.append((run, frame, ds.calibration, ds.validation, self._solution_index(run)))
        if not jobs:
            return

        def work(ctx):
            out = []
            for i, (run, frame, cal, val, idx) in enumerate(jobs):
                if ctx.cancelled:
                    break
                ctx.progress(f"scoring {run.label}", i / len(jobs))
                out.append(score_run(run, frame, cal, val, idx))
            return out

        def done(scores: list[_Score]) -> None:
            for sc in scores:
                self._scores[sc.run_id] = sc
            self.refresh()

        self.ctx.jobs.submit("Score runs", work, on_done=done)

    # ------------------------------------------------------------------ plots

    def _metric_value(self, run: RunRecord) -> float | None:
        """Score in natural form for the selected measure."""
        m = self.metric.currentData()
        if m in SCORE_COLUMNS:
            sc = self._scores.get(run.id)
            if sc is None:
                return None
            src = sc.val if m.startswith("val") else sc.cal
            if src is None:
                return None
            return src.get(m.split(" ", 1)[1] if " " in m else m)
        if m in run.objective_names:
            return float(run.display_F()[self._solution_index(run), run.objective_names.index(m)])
        return None

    def _metric_better(self) -> str:
        m = self.metric.currentData() or ""
        if m in SCORE_COLUMNS:
            return "max" if "NSE" in m else "min"
        return objective_better([m]).get(m, "min") or "min"

    def _draw(self) -> None:
        runs = self._selected_runs()
        th = theme.current()
        # -- complexity
        self.complexity.clear()
        better = self._metric_better()
        m = self.metric.currentData() or ""
        self.complexity.setLabel("left", f"{self.metric.currentText()}  ({'higher' if better == 'max' else 'lower'} "
                                         "is better)")
        pts = []
        for run in runs:
            v = self._metric_value(run)
            if v is None or not np.isfinite(v):
                continue
            pts.append(ComplexityPoint(run.id, run.label, run.n_params_calibrated, -v if better == "max" else v))
            c = theme.series_color(self._color_index(run.id))
            self.complexity.addItem(pg.ScatterPlotItem([run.n_params_calibrated], [v], size=12, brush=c,
                                                       pen=pg.mkPen(th.plot_bg)))
            t = pg.TextItem(run.label, color=th.plot_fg, anchor=(0, 1))
            t.setPos(run.n_params_calibrated, v)
            self.complexity.addItem(t)
        front = complexity_front(pts)
        if len(front) > 1:
            xs = [p.n_params for p in front]
            ys = [-p.score if better == "max" else p.score for p in front]
            self.complexity.plot(xs, ys, pen=pg.mkPen(th.accent, width=2), stepMode=None)
        if not pts and m in SCORE_COLUMNS:
            t = pg.TextItem("Press 'Score selected runs' to compute this measure", color=th.muted)
            self.complexity.addItem(t)

        # -- parallel coordinates and Pareto fronts
        objs = [n for n in self._objectives() if all(n in r.objective_names for r in runs)] if runs else []
        labels = objective_labels(objs)
        obj_better = objective_better(objs)
        axes = [AxisSpec(PARAMS_AXIS, "parameters", "min", kind="count")]
        axes += [AxisSpec(n, labels.get(n, n), obj_better.get(n) or None, kind="objective") for n in objs]
        blocks, groups = [], []
        self._row_index: list[tuple[str, int]] = []
        for g, run in enumerate(runs):
            D = run.display_F()
            cols = [D[:, run.objective_names.index(n)] for n in objs]
            blocks.append(np.column_stack([np.full(run.n_solutions, run.n_params_calibrated)] + cols))
            groups += [g] * run.n_solutions
            self._row_index += [(run.id, i) for i in range(run.n_solutions)]
        data = np.vstack(blocks) if blocks else np.empty((0, len(axes)))
        self.parallel.set_data(axes, data, groups=np.asarray(groups, dtype=int),
                               group_labels=[r.label for r in runs],
                               group_colors=[theme.series_color(self._color_index(r.id)) for r in runs])
        self.pareto.set_layers([ParetoLayer(r.id, r.label, r.display_F(), r.objective_names,
                                            theme.series_color(self._color_index(r.id)), knee=self._solution_index(r))
                                for r in runs])

        # -- hydrographs of scored solutions (same dataset as the first one)
        self.ts.clear_curves()
        scored = [self._scores[r.id] for r in runs if r.id in self._scores]
        if scored:
            first = scored[0]
            self.ts.set_data(first.t, first.rain, first.observed)
            for sc in scored:
                if sc.dataset == first.dataset and len(sc.t) == len(first.t):
                    run = self.ctx.session.run(sc.run_id)
                    self.ts.set_curve(sc.run_id, sc.t, sc.predicted,
                                      color=theme.series_color(self._color_index(sc.run_id)),
                                      name=run.label if run else sc.run_id)

    def _row_clicked(self, row: int) -> None:
        if 0 <= row < len(self._row_index):
            rid, idx = self._row_index[row]
            self.ctx.session.select(rid, [idx])
            self.parallel.set_highlight([row])
