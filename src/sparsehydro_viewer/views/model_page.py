"""Model workspace: build the working model from processes (or, in the Advanced tab,
from components), preview its unit hydrographs, and see every parameter change in
the hydrograph and objectives."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.catalog import CATALOG, ModelSpec, parameter_counts
from ..core.data import epoch_seconds
from ..core.trace import flow_parts
from ..resources import icon
from ..services import LiveResult
from ..widgets import TimeseriesPlot, UHPreview
from ..widgets.model_composer import ModelComposer, apply_renames
from ..widgets.process_builder import ProcessBuilder
from ..widgets.states_panel import StatesPanel
from .common import num_item, objective_labels, page_header, text_item
from .context import AppContext
from .shell.page import Page


class ModelPage(Page):
    title = "Model"
    icon_name = "nav-model"
    uses_working_model = True

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        s = ctx.session

        # Processes (default): grow the model one process at a time. Advanced: the raw component tree.
        self.builder = ProcessBuilder()
        self.builder.changed.connect(self._structure_edited)
        self.composer = ModelComposer()
        self.composer.changed.connect(self._structure_edited)
        self.name = QLineEdit()
        self.name.setPlaceholderText("model name (optional)")
        self.name.editingFinished.connect(lambda: s.set_model_label(self.name.text().strip()))
        self.counts = QLabel()
        builder_scroll = QScrollArea()
        builder_scroll.setWidgetResizable(True)
        builder_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        builder_scroll.setWidget(self.builder)
        advanced = QWidget()
        al = QVBoxLayout(advanced)
        al.setContentsMargins(0, 4, 0, 0)
        hint = QLabel("The component tree behind the model. Use it for structures the Processes tab does not "
                      "cover, e.g. several RDII terms or nested sums.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        al.addWidget(hint)
        al.addWidget(self.composer, 1)
        self.structure_tabs = QTabWidget()
        self.structure_tabs.addTab(builder_scroll, "Processes")
        self.structure_tabs.addTab(advanced, "Advanced")
        box = QGroupBox("Model")
        bl = QVBoxLayout(box)
        bl.addWidget(self.structure_tabs, 1)
        row = QHBoxLayout()
        row.addWidget(self.name, 1)
        row.addWidget(self.counts)
        bl.addLayout(row)

        self.metrics = QTableWidget(0, 3)
        self.metrics.setHorizontalHeaderLabels(["Objective", "Calibration", "Validation"])
        self.metrics.verticalHeader().setVisible(False)
        self.metrics.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metrics.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.metrics.setMaximumHeight(170)
        self.constraints = QLabel()
        self.constraints.setWordWrap(True)
        self.status = QLabel()
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        mbox = QGroupBox("Objectives at the current slider values")
        ml = QVBoxLayout(mbox)
        ml.addWidget(self.metrics)
        ml.addWidget(self.constraints)
        ml.addWidget(self.status)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(box, 3)
        ll.addWidget(mbox, 1)
        left.setMinimumWidth(360)
        left.setMaximumWidth(480)

        self.plot = TimeseriesPlot()
        plot_box = QGroupBox("Simulated vs observed (calibration period)")
        pl = QVBoxLayout(plot_box)
        pl.addWidget(self.plot, 1)
        self.uh = UHPreview()
        self.pin_action = self.action("Pin shape", "Keep the current unit hydrographs for comparison", "pin",
                                      self._pin)
        self.clear_pins_action = self.action("Clear pinned shapes", "Remove pinned unit hydrographs", "clear",
                                             self.uh.clear_pinned)
        self.components_action = self.action(
            "Components", "Show the simulated hydrograph as the sum of its individual hydrographs (each unit "
            "hydrograph, each term of a sum)", "components", self._trace_needs_changed, checkable=True)
        self.export_trace_action = self.action(
            "Export trace…", "Save the whole record's simulation with every component, state and flux to CSV",
            "export", self.export_trace)
        self.states = StatesPanel()
        self.states.link_x(self.plot.flow_plot.getViewBox())
        self.lower_tabs = QTabWidget()
        self.lower_tabs.addTab(self.uh, "Unit hydrographs (unit area)")
        self.lower_tabs.addTab(self.states, icon("states"), "Internal states")
        self.lower_tabs.currentChanged.connect(lambda *_: self._trace_needs_changed())
        uh_box = QGroupBox()
        ul = QVBoxLayout(uh_box)
        ul.setContentsMargins(4, 4, 4, 4)
        ul.addWidget(self.lower_tabs, 1)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(plot_box)
        right.addWidget(uh_box)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Model", "Build the working model by adding processes (rainfall losses, unit "
                                           "hydrographs, other flow components), then move its sliders (Working "
                                           "model panel, right): the hydrograph, unit hydrographs and objectives "
                                           "update as you drag."))
        lay.addWidget(split, 1)

        self._pins = 0
        self._last_t = 0.0
        self._data_key: tuple | None = None
        s.modelChanged.connect(self._sync_from_session)
        s.projectChanged.connect(self._sync_from_session)
        s.parametersEdited.connect(self._update_counts)
        ctx.controller.result.connect(self._on_result)
        ctx.controller.unavailable.connect(self.status.setText)
        self._sync_from_session()

    # ------------------------------------------------------------------ shell

    def context_actions(self):
        return [self.components_action, self.export_trace_action, None, self.pin_action, self.clear_pins_action]

    def export_trace(self, path: str | None = None) -> None:
        """Write the working model's trace over the whole record (and a ``.fields.csv`` describing it)."""
        s = self.ctx.session
        ds = s.dataset
        if ds is None:
            self.status.setText("Load a dataset first.")
            return
        if path is None:
            from PySide6.QtWidgets import QFileDialog

            name = f"{ds.name} {s.model_spec.display_label} trace.csv".replace("/", "-")
            path, _ = QFileDialog.getSaveFileName(self, "Export trace", name, "CSV files (*.csv)")
            if not path:
                return
        spec, values, objectives, frame = s.model_spec, dict(s.values), list(s.objectives), s.frame()

        def work(ctx):
            from ..core.data import Period
            from ..core.evaluation import Evaluator
            from ..core.trace import trace_frame, trace_metadata

            ctx.progress("simulating the whole record")
            ev = Evaluator(spec, frame, objectives, Period())
            table = trace_frame(ev, values)
            table.to_csv(path, index=False)
            trace_metadata(ev.trace_fields()).to_csv(str(path).rsplit(".", 1)[0] + ".fields.csv", index=False)
            return path

        self.submit_job("Export trace", work,
                        on_done=lambda p: self.window().statusBar().showMessage(f"Trace saved to {p}", 8000))

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self._trace_needs_changed()

    def hideEvent(self, ev) -> None:  # noqa: N802
        super().hideEvent(ev)
        self._trace_needs_changed()

    def wants_trace(self) -> bool:
        """The trace costs a second model run, so it is computed only while it is on screen."""
        return self.isVisible() and (self.components_action.isChecked()
                                     or self.lower_tabs.currentWidget() is self.states)

    def _trace_needs_changed(self) -> None:
        self.ctx.controller.live.set_trace(self.wants_trace())
        if not self.components_action.isChecked():
            self.plot.clear_stack("components")

    def active_chart(self):
        return self.plot

    # ------------------------------------------------------------------ structure

    def _structure_edited(self, root, renames: dict) -> None:
        s = self.ctx.session
        spec = ModelSpec(root, parameters=apply_renames(s.model_spec.parameters, renames), label=s.model_spec.label)
        s.set_model(spec, apply_renames(s.values, renames))

    def _sync_from_session(self) -> None:
        spec = self.ctx.session.model_spec
        if spec.root.to_dict() != self.composer.root.to_dict():
            self.composer.set_root(spec.root)
        self.builder.set_root(spec.root)
        self.name.setText(spec.label)
        self.name.setPlaceholderText(spec.display_label if not spec.label else "model name (optional)")
        self._update_counts()

    def _update_counts(self) -> None:
        model = CATALOG.instantiate(self.ctx.session.model_spec, strict=False)
        total, cal = parameter_counts(model)
        self.counts.setText(f"<b>{total}</b> parameters, <b>{cal}</b> calibrated")

    def _pin(self) -> None:
        self._pins += 1
        self.uh.pin_current(f"pin {self._pins}")

    # ------------------------------------------------------------------ live results

    def _show_trace(self, res: LiveResult) -> None:
        """Stack the individual hydrographs under the simulation and feed the states panel."""
        if res.trace is None or res.trace_fields is None:
            return
        arrays = dict(res.trace)
        arrays.setdefault(res.output_key, res.calibration.predicted)
        self.states.set_fields(res.trace_fields, self.ctx.session.model_spec.structure_key)
        self.states.set_trace(self._t, arrays)
        if self.components_action.isChecked():
            fields = {f.name: f for f in res.trace_fields}
            parts = flow_parts(res.trace_fields, arrays, res.output_key)
            layers = [(fields[name].label, y, theme.series_color(i)) for i, (name, y) in enumerate(parts)]
            self.plot.set_stack("components", self._t, layers)
            self.components_action.setToolTip(
                "Individual hydrographs: " + ", ".join(label for label, _, _ in layers) if layers
                else "This model's output is not a sum of hydrographs")

    def _on_result(self, res: LiveResult) -> None:
        now = time.perf_counter()
        th = theme.current()
        key = (id(res.observed), len(res.observed))
        if key != self._data_key:
            self._data_key = key
            self._t = epoch_seconds(res.datetime)
            self.plot.set_data(self._t, res.rain, res.observed)
        self.plot.set_curve("sim", self._t, res.calibration.predicted, color=th.predicted,
                            name="Simulated (working model)")
        self.uh.set_curves(res.kernels)
        self._show_trace(res)
        labels = objective_labels(res.calibration.objectives)
        rows = list(res.calibration.objectives.items())
        self.metrics.setRowCount(len(rows))
        for r, (name, v) in enumerate(rows):
            self.metrics.setItem(r, 0, text_item(labels.get(name, name)))
            self.metrics.setItem(r, 1, num_item(v))
            vv = res.validation.objectives.get(name) if res.validation else None
            self.metrics.setItem(r, 2, num_item(vv))
        bad = {k: g for k, g in res.calibration.constraints.items() if g > 0}
        notes = []
        if bad:
            notes.append("Constraint violated: " + ", ".join(f"{k} (g = {g:.3g})" for k, g in bad.items()))
        notes += [f"⚠ {r.message()}" for r in res.slow_responses]
        self.constraints.setText("<br>".join(f"<span style='color:#D55E00'>{n}</span>" for n in notes))
        self._last_result = res
        dt = (now - self._last_t) if self._last_t else 0.0
        self._last_t = now
        self.status.setText(f"{len(res.observed):,} steps at {res.dt_hours * 60:g} min"
                            + (f"; refresh interval {dt * 1000:.0f} ms" if 0 < dt < 2 else ""))
