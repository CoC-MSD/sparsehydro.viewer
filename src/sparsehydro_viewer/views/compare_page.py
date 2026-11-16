"""Compare workspace: alternative models side by side, with parameter count as a
first-class axis so the most parsimonious adequate model stands out."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
from ..widgets.timeseries_plot import PERIOD_COLORS
from .common import num_item, objective_better, objective_labels, page_header, text_item
from .context import AppContext
from .shell.page import Page

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
    #: MSDGC grade on the calibration period ("pass" | "conditional" | "fail"), Cinci score, official flag.
    grade: str | None = None
    cinci: float | None = None
    official: bool = False


#: Marker of each grade on the complexity plot: shape as well as colour tells them apart.
GRADE_SYMBOL = {"pass": "o", "conditional": "d", "fail": "x"}
GRADE_SHORT = {"pass": "MSDGC pass", "conditional": "MSDGC conditional", "fail": "MSDGC fail"}


def grade_run(run: RunRecord, index: int, frame, dataset, attributes: dict, options: dict):
    """MSDGC grade of solution *index* on the dataset's calibration period (``None`` when it cannot be graded)."""
    from ..core.assess import ASSESS_OPTIONS, run_assessment
    from ..core.options import resolve_options

    opts = resolve_options(ASSESS_OPTIONS, {**options, "period": "calibration"})
    try:
        return run_assessment(run.model, run.solution_values(index), frame, dataset, attributes, opts,
                              run.objectives, source=run.label).result
    except Exception:  # noqa: BLE001 - e.g. no events in the period: the run is simply not graded
        return None


@dataclass
class _Hydrograph:
    """One chosen solution simulated over its dataset's whole record."""

    run_id: str
    index: int
    dataset: str
    t: np.ndarray
    rain: np.ndarray
    observed: np.ndarray
    predicted: np.ndarray


def simulate_whole_record(run: RunRecord, frame, index: int) -> _Hydrograph:
    """Solution *index* of *run* over the whole record (not only a period), for the chosen-solutions chart."""
    from ..core.data import Period

    ev = Evaluator(run.model, frame, run.objectives, Period())
    ev.evaluate(run.fixed_values)
    res = ev.evaluate_vector(run.param_names, run.pareto_X[index])
    return _Hydrograph(run.id, index, run.dataset, epoch_seconds(ev.datetime), np.asarray(ev.rain, float),
                       np.asarray(ev.observed, float), np.asarray(res.predicted, float))


def solution_choices(run: RunRecord) -> list[tuple[str, str]]:
    """``(key, label)`` of the solutions offered for a run: knee, best for each objective, and every solution."""
    labels = objective_labels(run.objective_names)
    out = [("knee", "Knee (balanced)")]
    out += [(f"best:{n}", f"Best {labels.get(n, n)}") for n in run.objective_names]
    return out


def resolve_choice(run: RunRecord, choice: str) -> int:
    """Pareto index of a choice key (``knee``, ``best:<objective>`` or ``index:<i>``)."""
    if choice.startswith("best:") and choice[5:] in run.objective_names:
        return run.best_index(choice[5:])
    if choice.startswith("index:"):
        i = int(choice[6:])
        if 0 <= i < run.n_solutions:
            return i
    return run.knee_index()


def score_run(run: RunRecord, frame, calibration, validation, index: int, *, dataset=None,
              attributes: dict | None = None, assess_options: dict | None = None) -> _Score:
    """Fit statistics of one solution on the calibration and validation periods, and its MSDGC grade."""
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
    graded = grade_run(run, index, frame, dataset, attributes or {}, assess_options or {}) \
        if dataset is not None else None
    return _Score(run.id, index, cal, val, epoch_seconds(ev.datetime), res.predicted, ev.observed, ev.rain,
                  run.dataset, graded.grade if graded else None,
                  float(graded.summary.set_index("group").loc["all", "cinci_score"]) if graded else None,
                  bool(graded.official) if graded else False)


class ComparePage(Page):
    title = "Compare"
    icon_name = "nav-compare"
    uses_working_model = True
    primary_text = "Score runs"
    primary_tip = ("Simulate each ticked run's chosen solution on the calibration and validation periods, "
                   "compute NSE, RMSE, AIC and BIC, and grade it with the MSDGC criteria")

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
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
        self.solution.setToolTip("Solution used for every run (scores, complexity plot, hydrographs); change it for "
                                 "one run in the Chosen solutions list")
        self.solution.currentIndexChanged.connect(self._solution_changed)
        self.grade_filter = QComboBox()
        self.grade_filter.addItem("All runs", None)
        self.grade_filter.addItem("MSDGC pass", ("pass",))
        self.grade_filter.addItem("MSDGC pass or conditional", ("pass", "conditional"))
        self.grade_filter.setToolTip("Plot only the ticked runs whose MSDGC grade (after scoring) is one of these")
        self.grade_filter.setAccessibleName("MSDGC grade filter")
        self.grade_filter.currentIndexChanged.connect(self._draw)
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("Measure"))
        ctl.addWidget(self.metric, 1)
        ctl.addWidget(QLabel("Solution"))
        ctl.addWidget(self.solution, 1)
        ctl.addWidget(QLabel("Show"))
        ctl.addWidget(self.grade_filter, 1)
        ctl.addStretch(1)
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
        self.ts.setToolTip("Chosen solution of every ticked run over the whole record; shaded: calibration "
                           "(blue) and validation (orange) periods")
        self.choices = QTableWidget(0, 2)
        self.choices.setHorizontalHeaderLabels(["Run", "Solution"])
        self.choices.verticalHeader().setVisible(False)
        self.choices.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.choices.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.choices.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.choices.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.choices.setAccessibleName("Chosen solution of each ticked run")
        self.choices.setToolTip("Solution of each run shown in the hydrograph and used for scoring: the knee, the "
                                "best for an objective, or one picked in the parallel coordinates")
        self.ts_note = QLabel()
        self.ts_note.setObjectName("hint")
        self.ts_note.setWordWrap(True)
        chosen_side = QWidget()
        cl = QVBoxLayout(chosen_side)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.choices, 1)
        cl.addWidget(self.ts_note)
        chosen_side.setMinimumWidth(260)
        chosen_side.setMaximumWidth(420)
        chosen = QSplitter()
        chosen.addWidget(chosen_side)
        chosen.addWidget(self.ts)
        chosen.setStretchFactor(1, 1)
        self._sim_timer = QTimer(self)
        self._sim_timer.setSingleShot(True)
        self._sim_timer.setInterval(120)
        self._sim_timer.timeout.connect(self._simulate_chosen)

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
        main.addWidget(boxed("Chosen solutions (whole record)", chosen))
        # The hydrograph was squeezed to a few pixels by the two chart rows above on ordinary screens.
        self.ts.setMinimumHeight(260)
        main.setChildrenCollapsible(False)
        for i, stretch in enumerate((2, 2, 3)):
            main.setStretchFactor(i, stretch)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Compare", "Compare alternative models. Prefer the simplest model whose "
                                             "performance is close to the best; the step line shows where extra "
                                             "parameters stop paying for themselves."))
        lay.addWidget(main, 1)
        self._checked: set[str] = set()
        self._seen: set[str] = set()
        self._scores: dict[str, _Score] = {}
        self._choice: dict[str, str] = {}  # run id -> "knee" | "best:<objective>" | "index:<i>"
        self._hydrographs: dict[tuple[str, int], _Hydrograph] = {}
        self._sim_job = None
        self._sim_errors: dict[tuple[str, int], str] = {}
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
        self._choice.clear()
        self._hydrographs.clear()
        self._sim_errors.clear()
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

    def _default_choice(self, run: RunRecord) -> str:
        metric = self.metric.currentData()
        if self.solution.currentData() == "best" and metric in run.objective_names:
            return f"best:{metric}"
        return "knee"

    def choice(self, run: RunRecord) -> str:
        return self._choice.get(run.id) or self._default_choice(run)

    def set_choice(self, run_id: str, choice: str) -> None:
        """Choose the solution of one run (``knee``, ``best:<objective>`` or ``index:<i>``)."""
        if self._choice.get(run_id) == choice:
            return
        self._choice[run_id] = choice
        self._scores.pop(run_id, None)  # its scores were for another solution
        self.refresh()

    def _solution_index(self, run: RunRecord) -> int:
        return resolve_choice(run, self.choice(run))

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
               [f"best {labels.get(n, n)}" for n in objs] + SCORE_COLUMNS + ["MSDGC grade", "Cinci score"]
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
            cells += [self._grade_item(sc), num_item(sc.cinci if sc else None, "{:.3f}")]
            for c, it in enumerate(cells):
                self.table.setItem(r, c, it)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSortingEnabled(True)
        self._filling = False
        self._draw()
        self.contextChanged.emit()

    @staticmethod
    def _grade_item(sc) -> QTableWidgetItem:
        from PySide6.QtGui import QBrush, QColor

        from .assess_page import GRADE_STYLE

        if sc is None or sc.grade is None:
            it = text_item("" if sc is None else "not graded")
            it.setToolTip("Score the run to grade it; a run with no events in its calibration period is not graded")
            return it
        text, symbol, color = GRADE_STYLE[sc.grade]
        it = text_item(f"{symbol} {text}" + ("" if sc.official else " *"), ["pass", "conditional", "fail"].index(sc.grade))
        it.setForeground(QBrush(QColor(color)))
        it.setToolTip("MSDGC calibration grade on the calibration period"
                      + ("" if sc.official else "\n* provisional: see the Assess page for what is missing"))
        return it

    def _passes_filter(self, run: RunRecord) -> bool:
        wanted = self.grade_filter.currentData()
        if not wanted:
            return True
        sc = self._scores.get(run.id)
        return sc is not None and sc.grade in wanted

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
        self.contextChanged.emit()

    def _solution_changed(self) -> None:
        self._scores.clear()
        self._choice.clear()
        self.refresh()

    # ------------------------------------------------------------------ scoring

    # ------------------------------------------------------------------ shell

    def primary(self) -> None:
        self._score()

    def primary_enabled(self) -> bool:
        return bool(self._selected_runs()) and not self.stop_enabled()

    def active_chart(self):
        return self.ts

    def status_text(self) -> str:
        n = len(self._selected_runs())
        return f"{n} run(s) ticked" if n else ""

    def _score(self) -> None:
        s = self.ctx.session
        jobs = []
        for run in self._selected_runs():
            try:
                frame, ds = s.frame(run.dataset), s.project.dataset(run.dataset)
            except Exception:
                continue
            attrs = s.store.attributes(ds.site_iri) if ds.site_iri else {}
            jobs.append((run, frame, ds, attrs, self._solution_index(run)))
        if not jobs:
            return
        assess_options = dict(s.ui("assess_options", {}))

        def work(ctx):
            out = []
            for i, (run, frame, ds, attrs, idx) in enumerate(jobs):
                if ctx.cancelled:
                    break
                ctx.progress(f"scoring {run.label}", i / len(jobs))
                out.append(score_run(run, frame, ds.calibration, ds.validation, idx, dataset=ds, attributes=attrs,
                                     assess_options=assess_options))
            return out

        def done(scores: list[_Score]) -> None:
            for sc in scores:
                self._scores[sc.run_id] = sc
            self.refresh()

        self.submit_job("Score runs", work, on_done=done)

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
        runs = [r for r in self._selected_runs() if self._passes_filter(r)]
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
            sc = self._scores.get(run.id)
            grade = sc.grade if sc else None
            self.complexity.addItem(pg.ScatterPlotItem([run.n_params_calibrated], [v], size=14 if grade else 12,
                                                       symbol=GRADE_SYMBOL.get(grade, "o"), brush=c,
                                                       pen=pg.mkPen(th.plot_bg)))
            label = run.label + (f"  [{GRADE_SHORT[grade]}]" if grade else "")
            t = pg.TextItem(label, color=th.plot_fg, anchor=(0, 1))
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

        # -- chosen solutions: list and hydrographs (simulated in the background)
        self._fill_choices(runs)
        self._sim_timer.start()

    # ------------------------------------------------------------------ chosen solutions

    def _fill_choices(self, runs: list[RunRecord]) -> None:
        self.choices.setRowCount(len(runs))
        for i, run in enumerate(runs):
            name = text_item(run.label, run.id)
            name.setForeground(pg.mkColor(theme.series_color(self._color_index(run.id))))
            name.setToolTip(f"{run.model.display_label} on {run.dataset}")
            self.choices.setItem(i, 0, name)
            box = QComboBox()
            box.setAccessibleName(f"Solution of {run.label}")
            for key, label in solution_choices(run):
                box.addItem(label, key)
            current = self.choice(run)
            if current.startswith("index:"):
                box.addItem(f"Picked: solution #{resolve_choice(run, current) + 1}", current)
            box.setCurrentIndex(max(box.findData(current), 0))
            box.setToolTip("Knee: the balanced solution of the front; Best: the best for that objective; Picked: "
                           "the solution clicked in the parallel coordinates")
            box.currentIndexChanged.connect(lambda _i, b=box, rid=run.id: self.set_choice(rid, b.currentData()))
            self.choices.setCellWidget(i, 1, box)

    def chosen_runs(self) -> list[tuple[RunRecord, int]]:
        return [(r, self._solution_index(r)) for r in self._selected_runs() if self._passes_filter(r)]

    def _simulate_chosen(self) -> None:
        """Simulate the chosen solutions not yet cached, then redraw the chart."""
        s = self.ctx.session
        todo = []
        for run, idx in self.chosen_runs():
            if (run.id, idx) in self._hydrographs:
                continue
            try:
                todo.append((run, idx, s.frame(run.dataset)))
            except Exception:  # noqa: BLE001 - dataset removed: the run is listed but not drawn
                continue
        if not todo:
            self._draw_hydrographs()
            return
        if self._sim_job is not None:
            return  # the running job redraws when done, then picks up what is missing

        def work(ctx):
            out = []
            for i, (run, idx, frame) in enumerate(todo):
                if ctx.cancelled:
                    break
                ctx.progress(f"simulating {run.label}", i / len(todo))
                try:
                    out.append(simulate_whole_record(run, frame, idx))
                except Exception as exc:  # noqa: BLE001 - reported in the chart note
                    out.append((run.id, idx, f"{type(exc).__name__}: {exc}"))
            return out

        def done(results) -> None:
            self._sim_job = None
            for h in results:
                if isinstance(h, _Hydrograph):
                    self._hydrographs[(h.run_id, h.index)] = h
                else:
                    self._sim_errors[(h[0], h[1])] = h[2]
            self._simulate_chosen()

        def failed(_msg: str) -> None:
            self._sim_job = None

        self._sim_job = self.submit_job("Simulate chosen solutions", work, on_done=done, on_error=failed)

    def _draw_hydrographs(self) -> None:
        """Observed and rain of the analysis dataset (or the first run's), every chosen solution on it."""
        self.ts.clear_curves()
        chosen = [(r, i) for r, i in self.chosen_runs() if (r.id, i) in self._hydrographs]
        if not chosen:
            self.ts_note.setText("Tick runs to compare their chosen solutions." if not self._selected_runs()
                                 else "")
            return
        s = self.ctx.session
        names = [r.dataset for r, _ in chosen]
        base_name = s.dataset_name if s.dataset_name in names else names[0]
        base = next(self._hydrographs[(r.id, i)] for r, i in chosen if r.dataset == base_name)
        self.ts.set_data(base.t, base.rain, base.observed, f"Observed ({base_name})")
        others = []
        for n, (run, idx) in enumerate(chosen):
            h = self._hydrographs[(run.id, idx)]
            if h.dataset != base_name:
                others.append(run.label)
                continue
            label = dict(solution_choices(run)).get(self.choice(run), f"solution #{idx + 1}")
            self.ts.set_curve(f"run:{run.id}", h.t, h.predicted, color=theme.series_color(self._color_index(run.id)),
                              width=1.8, dashed=n % 2 == 1, name=f"{run.label}: {label}")
        spans = []
        try:
            ds = s.project.dataset(base_name)
            for key, period in (("calibration", ds.calibration), ("validation", ds.validation)):
                if not period.is_open:
                    t0 = epoch_seconds([period.start])[0] if period.start else base.t[0]
                    t1 = epoch_seconds([period.end])[0] if period.end else base.t[-1]
                    c = QColor(PERIOD_COLORS[key])
                    c.setAlpha(28)
                    spans.append((t0, t1, c.name(QColor.NameFormat.HexArgb)))
        except KeyError:
            pass
        self.ts.set_spans(spans)
        notes = []
        if others:
            notes.append(f"Not drawn (other datasets than {base_name}): {', '.join(others)}.")
        errors = [msg for (rid, _), msg in self._sim_errors.items() if rid in self._checked]
        if errors:
            notes.append("Could not simulate: " + "; ".join(errors))
        self.ts_note.setText(" ".join(notes))

    def _row_clicked(self, row: int) -> None:
        if 0 <= row < len(self._row_index):
            rid, idx = self._row_index[row]
            self.ctx.session.select(rid, [idx])
            self.set_choice(rid, f"index:{idx}")
            self.parallel.set_highlight([row])
