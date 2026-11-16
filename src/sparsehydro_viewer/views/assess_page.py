"""Assess workspace: grade a model with the MSDGC calibration criteria (Modeling Guidelines Rev 5.8)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.assess import APPROACHES, ASSESS_OPTIONS, PERIODS, ZONE_PRESETS, AssessmentRun, run_assessment
from ..core.data import epoch_seconds
from ..core.options import resolve_options
from ..widgets import TimeseriesPlot
from ..widgets.assess_scatter import AssessScatter
from ..widgets.option_form import OptionForm
from .common import draw_working, num_item, page_header, text_item
from .context import AppContext
from .shell.page import Page

GRADE_STYLE = {  # text, symbol, colour: the grade is never told by colour alone
    "pass": ("Pass", "✓", "#1a7f37"),
    "conditional": ("Conditional pass", "◐", "#9a6700"),
    "fail": ("Fail", "✗", "#cf222e"),
}
STATUS_TEXT = {"pass": "✓ pass", "conditional": "◐ conditional", "fail": "✗ fail", "missing": "— missing"}


def _range_text(lo, hi, units: str) -> str:
    u = f" {units}" if units else ""
    if lo is None and hi is None:
        return ""
    if hi is None:
        return f"≥ {lo:g}{u}"
    if lo is None:
        return f"≤ {hi:g}{u}"
    return f"{lo:g} to {hi:g}{u}"


class AssessPage(Page):
    title = "Assess"
    icon_name = "nav-assess"
    uses_working_model = True
    primary_text = "Assess"
    primary_tip = "Grade the selected model with the MSDGC calibration criteria"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        s = ctx.session
        self.source = QComboBox()
        self.source.setToolTip("Model to assess: the working model at its slider values, or a calibration run's "
                               "balanced (knee) solution")
        self.source.setAccessibleName("Model to assess")
        self.form = OptionForm(choice_labels={**APPROACHES, **ZONE_PRESETS, **PERIODS})
        self.form.set_specs(ASSESS_OPTIONS, s.ui("assess_options", {}))
        self.form.changed.connect(lambda: s.set_ui("assess_options", self.form.values()))
        settings = QGroupBox("Assessment")
        sl = QVBoxLayout(settings)
        sl.addWidget(QLabel("Model"))
        sl.addWidget(self.source)
        sl.addWidget(self.form)
        site_hint = QLabel("Qcritical needs the site's average dry weather flow (ODWF-A) and sewer system: set them "
                           "in the site's properties on the Sites page.")
        site_hint.setObjectName("hint")
        site_hint.setWordWrap(True)
        sl.addWidget(site_hint)

        self.grade = QLabel("Not assessed yet")
        self.grade.setObjectName("gradeBanner")
        self.grade.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grade.setMinimumHeight(54)
        self.grade.setAccessibleName("Calibration grade")
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.criteria = self._table(["Criterion", "Value", "Pass", "Fail outside", "Status"])
        self.criteria.setAccessibleName("Calibration criteria")
        crit_box = QGroupBox("Criteria (Guidelines Vol. II 7.1)")
        cl = QVBoxLayout(crit_box)
        cl.addWidget(self.grade)
        cl.addWidget(self.criteria, 1)
        cl.addWidget(self.warnings)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(settings)
        ll.addWidget(crit_box, 1)
        left.setMinimumWidth(380)
        left.setMaximumWidth(520)

        self.scatter = AssessScatter()
        self.scatter.eventClicked.connect(self._show_event)
        self.summary = self._table(["Months", "Events", "rc conveyance", "rc overflow/storage", "rc treatment",
                                    "rc ave (Cinci)"])
        self.summary.setAccessibleName("Concordance correlation by month group")
        self.qcrit = self._table(["Level", "Flow [cfs]", "Observed above [MG]", "Model above [MG]", "Error [%]"])
        self.qcrit.setAccessibleName("Critical flow volumes")
        self.events = self._table(["Event", "Start", "Duration [h]", "Month group", "Included", "Con15",
                                   "Obs. conveyance [MG]", "Model conveyance [MG]", "Obs. event [MG]",
                                   "Model event [MG]", "Obs. peak [cfs]", "Model peak [cfs]"])
        self.events.setSortingEnabled(True)
        self.events.setAccessibleName("Events of the assessment")
        self.events.setToolTip("Select an event to zoom the hydrograph to it; click a column header to sort")
        self.events.itemSelectionChanged.connect(self._event_selected)
        self.plot = TimeseriesPlot()
        events_tab = QSplitter(Qt.Orientation.Vertical)
        events_tab.addWidget(self.events)
        events_tab.addWidget(self.plot)
        tables = QWidget()
        tl = QVBoxLayout(tables)
        tl.addWidget(QLabel("Concordance correlation by month group (Guidelines Table 7-3)"))
        tl.addWidget(self.summary)
        tl.addWidget(QLabel("Critical flow volume: Qc1 is graded, Qc2–Qc4 are reported (Table 7-2)"))
        tl.addWidget(self.qcrit)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.scatter, "Zone volumes")
        self.tabs.addTab(tables, "Summary")
        self.tabs.addTab(events_tab, "Events")
        self.tabs.currentChanged.connect(lambda *_: self.contextChanged.emit())

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Assess", "Grade a model the way the MSDGC Modeling Guidelines (Rev 5.8) do: zone "
                                            "volumes of every event compared by Lin's concordance correlation, the "
                                            "critical flow volume and the peak fit of the largest storms (Con15)."))
        lay.addWidget(split, 1)
        self.last: AssessmentRun | None = None
        self._shown_dataset: str | None = None
        self.watch_working_model()
        for sig in (s.runsChanged, s.projectChanged, s.modelChanged, s.modelRenamed, s.datasetChanged):
            sig.connect(self.refresh_sources)
        self.refresh_sources()

    @staticmethod
    def _table(headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        return t

    # ------------------------------------------------------------------ shell

    def active_chart(self):
        return self.plot if self.tabs.currentIndex() == 2 else None

    def status_text(self) -> str:
        if self.last is None:
            return ""
        g = GRADE_STYLE[self.last.result.grade][0]
        return f"MSDGC: {g}" + ("" if self.last.result.official else " (provisional)") + f" - {self.last.source}"

    def working_model_changed(self, res) -> None:
        """The working model at its current values, beside the assessed model's hydrograph."""
        s = self.ctx.session
        draw_working(self.plot, res, s, show=self.last is not None and self._shown_dataset == s.dataset_name)

    # ------------------------------------------------------------------ sources

    def refresh_sources(self) -> None:
        current = self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        s = self.ctx.session
        self.source.addItem(f"Working model: {s.model_spec.display_label} (current slider values)", ("working", None))
        self.source.setItemData(0, f"The model built on the Model page ({s.model_spec.display_label}) at the values "
                                   "of the Working model panel, on the current dataset", Qt.ItemDataRole.ToolTipRole)
        for r in s.project.runs:
            if r.has_results:
                self.source.addItem(f"{r.label}: knee solution ({r.dataset})", ("run", r.id))
                self.source.setItemData(self.source.count() - 1,
                                        f"Model {r.model.display_label}, calibrated on {r.dataset}",
                                        Qt.ItemDataRole.ToolTipRole)
        i = self.source.findData(current)
        self.source.setCurrentIndex(max(i, 0))
        self.source.blockSignals(False)

    def _source(self):
        """``(spec, values, dataset name, label)`` of the selected source."""
        s = self.ctx.session
        kind, key = self.source.currentData() or ("working", None)
        if kind == "run":
            run = s.project.run(key)
            return run.model, run.solution_values(run.knee_index()), run.dataset, f"{run.label} (knee)"
        return s.model_spec, dict(s.values), s.dataset_name, f"{s.model_spec.display_label} (working model)"

    # ------------------------------------------------------------------ run

    def primary(self) -> None:
        self.assess()

    def assess(self) -> None:
        s = self.ctx.session
        spec, values, ds_name, label = self._source()
        if ds_name is None:
            self.warnings.setText("Load a dataset first.")
            return
        frame = s.frame(ds_name)
        ds = s.project.dataset(ds_name)
        attrs = s.store.attributes(ds.site_iri) if ds.site_iri else {}
        options = resolve_options(ASSESS_OPTIONS, self.form.values())
        objectives = list(s.objectives)

        def work(ctx):
            ctx.progress(f"assessing {label}")
            return run_assessment(spec, values, frame, ds, attrs, options, objectives, source=label)

        self.submit_job(f"Assess {label}", work, on_done=lambda run: self.show_run(run, ds_name),
                        on_error=lambda m: self.warnings.setText(f"<span style='color:#cf222e'>{m}</span>"))

    # ------------------------------------------------------------------ display

    def show_run(self, run: AssessmentRun, dataset: str | None = None) -> None:
        self.last = run
        self._shown_dataset = dataset
        res = run.result
        inputs = f"{dataset}: {self.ctx.session.inputs_text(dataset)}" if dataset else ""
        text, symbol, color = GRADE_STYLE[res.grade]
        official = "official grade" if res.official else "provisional: see the notes below"
        self.grade.setText(f"<span style='font-size:20pt'>{symbol} {text}</span><br>"
                           f"<span style='font-size:9pt'>{run.source}, {run.period.lower()} — {official}"
                           + (f"<br>{inputs}" if inputs else "") + "</span>")
        self.grade.setStyleSheet(f"QLabel#gradeBanner {{ border: 2px solid {color}; border-radius: 6px; "
                                 f"color: {color}; padding: 4px; }}")
        self.grade.setAccessibleDescription(f"{text}, {official}")
        rows = res.scorecard.as_rows()
        self.criteria.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.criteria.setItem(i, 0, text_item(r["label"] + ("" if r["required"] else " (reported)")))
            self.criteria.setItem(i, 1, num_item(r["value"], "{:.3f}" if not r["units"] else "{:+.1f}"))
            self.criteria.setItem(i, 2, text_item(_range_text(r["pass_lower"], r["pass_upper"], r["units"])))
            self.criteria.setItem(i, 3, text_item(_range_text(r["fail_lower"], r["fail_upper"], r["units"])))
            status = text_item(STATUS_TEXT.get(r["status"], r["status"]))
            st_color = {"pass": "#1a7f37", "conditional": "#9a6700", "fail": "#cf222e"}.get(r["status"])
            if st_color:
                status.setForeground(theme_color(st_color))
            self.criteria.setItem(i, 4, status)
        self.warnings.setText("<br>".join(f"• {w}" for w in res.warnings))
        self._fill_summary(res)
        self._fill_qcrit(res)
        self._fill_events(run)
        self.scatter.set_result(res)
        t = epoch_seconds(run.datetime)
        self._t = t
        self.plot.set_data(t, run.rain, run.observed)
        self.plot.remove_curve("sim")  # its name is the assessed model's
        self.plot.set_curve("sim", t, run.simulated, color=theme.current().selection, name=f"Assessed: {run.source}")
        self.working_model_changed(self.ctx.controller.last)
        spans = [(float(t[int(e.start_idx)]), float(t[min(int(e.end_idx), len(t) - 1)]))
                 for e in res.events.itertuples() if bool(e.included)]
        self.plot.set_spans(spans)
        self.contextChanged.emit()

    def _fill_summary(self, res) -> None:
        names = {"all": "All months", "critical": "Critical (Apr–Jul)", "non_critical": "Other months"}
        self.summary.setRowCount(len(res.summary))
        for i, r in enumerate(res.summary.itertuples()):
            self.summary.setItem(i, 0, text_item(names.get(r.group, r.group)))
            self.summary.setItem(i, 1, num_item(int(r.n)))
            for j, key in enumerate(("conveyance_ccc", "storage_ccc", "treatment_ccc", "cinci_score"), 2):
                self.summary.setItem(i, j, num_item(getattr(r, key), "{:.3f}"))

    def _fill_qcrit(self, res) -> None:
        q = res.qcritical
        self.qcrit.setRowCount(len(q))
        for i, r in enumerate(q.itertuples()):
            self.qcrit.setItem(i, 0, text_item(r.level + (" (graded)" if i == 0 else "")))
            self.qcrit.setItem(i, 1, num_item(r.flow_cfs, "{:.3f}"))
            self.qcrit.setItem(i, 2, num_item(r.observed_mg, "{:.4f}"))
            self.qcrit.setItem(i, 3, num_item(r.modeled_mg, "{:.4f}"))
            self.qcrit.setItem(i, 4, num_item(r.percent, "{:+.1f}"))

    def _fill_events(self, run: AssessmentRun) -> None:
        ev = run.result.events
        self.events.setSortingEnabled(False)
        self.events.setRowCount(len(ev))
        for i, e in enumerate(ev.itertuples()):
            first = text_item(str(e.event_id), int(e.event_id))
            self.events.setItem(i, 0, first)
            self.events.setItem(i, 1, text_item(str(e.start)[:16]))
            self.events.setItem(i, 2, num_item(float(e.duration_hours), "{:.1f}"))
            self.events.setItem(i, 3, text_item("critical" if e.critical else "other"))
            self.events.setItem(i, 4, text_item("yes" if e.included else ("excluded" if e.excluded else "no")))
            self.events.setItem(i, 5, text_item("✓" if getattr(e, "con15", False) else ""))
            for j, col in enumerate(("observed_conveyance_mg", "modeled_conveyance_mg", "observed_event_mg",
                                     "modeled_event_mg", "observed_peak_cfs", "modeled_peak_cfs"), 6):
                self.events.setItem(i, j, num_item(float(getattr(e, col)), "{:.4g}"))
        self.events.setSortingEnabled(True)

    def _show_event(self, event_id) -> None:
        self.tabs.setCurrentIndex(2)
        for row in range(self.events.rowCount()):
            if self.events.item(row, 0).data(Qt.ItemDataRole.UserRole) == event_id:
                self.events.selectRow(row)
                return

    def _event_selected(self) -> None:
        rows = {i.row() for i in self.events.selectedItems()}
        if not rows or self.last is None:
            return
        event_id = self.events.item(min(rows), 0).data(Qt.ItemDataRole.UserRole)
        ev = self.last.result.events.set_index("event_id").loc[event_id]
        t = self._t
        pad = 6 * 3600.0
        self.plot.zoom_to(float(t[int(ev.start_idx)]) - pad, float(t[min(int(ev.end_idx), len(t) - 1)]) + pad)

    def selected_event(self):
        rows = {i.row() for i in self.events.selectedItems()}
        return self.events.item(min(rows), 0).data(Qt.ItemDataRole.UserRole) if rows else None


def theme_color(color: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(color))


__all__ = ["AssessPage", "GRADE_STYLE"]
