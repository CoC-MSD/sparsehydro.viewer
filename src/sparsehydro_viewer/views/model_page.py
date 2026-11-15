"""Model workspace: compose the working model from components, preview its unit
hydrographs, and see every parameter change in the hydrograph and objectives."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..core.catalog import CATALOG, ModelSpec, parameter_counts
from ..core.data import epoch_seconds
from ..services import LiveResult
from ..widgets import TimeseriesPlot, UHPreview
from ..widgets.chart_toolbar import ChartToolbar
from ..widgets.model_composer import ModelComposer, apply_renames
from .common import num_item, objective_labels, page_header, text_item
from .context import AppContext


class ModelPage(QWidget):
    title = "Model"
    uses_working_model = True

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        s = ctx.session

        self.composer = ModelComposer()
        self.composer.changed.connect(self._structure_edited)
        self.name = QLineEdit()
        self.name.setPlaceholderText("model name (optional)")
        self.name.editingFinished.connect(lambda: s.set_model_label(self.name.text().strip()))
        self.counts = QLabel()
        box = QGroupBox("Model structure")
        bl = QVBoxLayout(box)
        hint = QLabel("Select a component to change its type or options. Add terms (e.g. a sanitary pattern) "
                      "or unit hydrographs; every edit rebuilds the working model and updates all views.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        bl.addWidget(hint)
        bl.addWidget(self.composer, 1)
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
        pl.addWidget(ChartToolbar(self.plot))
        pl.addWidget(self.plot, 1)
        self.uh = UHPreview()
        pin = QPushButton("Pin shape")
        pin.setToolTip("Keep the current unit hydrograph for comparison")
        pin.clicked.connect(self._pin)
        clear = QPushButton("Clear pinned")
        clear.clicked.connect(self.uh.clear_pinned)
        uh_box = QGroupBox("Unit hydrographs (unit area)")
        ul = QVBoxLayout(uh_box)
        ul.addWidget(self.uh, 1)
        r = QHBoxLayout()
        r.addStretch(1)
        r.addWidget(pin)
        r.addWidget(clear)
        ul.addLayout(r)

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
        lay.addWidget(page_header("Model", "Compose the working model from components, then move its sliders "
                                           "(Working model dock, right): the hydrograph, unit hydrographs and "
                                           "objectives update as you drag."))
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

    # ------------------------------------------------------------------ structure

    def _structure_edited(self, root, renames: dict) -> None:
        s = self.ctx.session
        spec = ModelSpec(root, parameters=apply_renames(s.model_spec.parameters, renames), label=s.model_spec.label)
        s.set_model(spec, apply_renames(s.values, renames))

    def _sync_from_session(self) -> None:
        spec = self.ctx.session.model_spec
        if spec.root.to_dict() != self.composer.root.to_dict():
            self.composer.set_root(spec.root)
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
        labels = objective_labels(res.calibration.objectives)
        rows = list(res.calibration.objectives.items())
        self.metrics.setRowCount(len(rows))
        for r, (name, v) in enumerate(rows):
            self.metrics.setItem(r, 0, text_item(labels.get(name, name)))
            self.metrics.setItem(r, 1, num_item(v))
            vv = res.validation.objectives.get(name) if res.validation else None
            self.metrics.setItem(r, 2, num_item(vv))
        bad = {k: g for k, g in res.calibration.constraints.items() if g > 0}
        self.constraints.setText(
            "" if not bad else "<span style='color:#D55E00'>Constraint violated: "
            + ", ".join(f"{k} (g = {g:.3g})" for k, g in bad.items()) + "</span>")
        dt = (now - self._last_t) if self._last_t else 0.0
        self._last_t = now
        self.status.setText(f"{len(res.observed):,} steps at {res.dt_hours * 60:g} min"
                            + (f"; refresh interval {dt * 1000:.0f} ms" if 0 < dt < 2 else ""))
