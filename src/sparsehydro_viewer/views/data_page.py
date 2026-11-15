"""Data workspace: load datasets, inspect them, set calibration/validation periods."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.data import (
    FLOW_TO_CFS,
    DatasetSpec,
    Period,
    epoch_seconds,
    guess_columns,
    load_dataset,
    sniff_columns,
    summarize,
)
from ..widgets import TimeseriesPlot
from ..widgets.chart_toolbar import ChartToolbar
from ..widgets.timeseries_plot import PERIOD_COLORS
from .common import page_header
from .context import AppContext

_COLUMN_ROLES = (("datetime", "Date/time"), ("rain", "Rain (depth per step)"),
                 ("stormflow", "Observed flow (target)"),
                 ("temperature_c", "Temperature [°C] (optional)"))


class _PeriodEditor(QWidget):
    """Checkbox + start/end editors; :attr:`edited` fires when the user changes anything."""

    edited = Signal()

    def __init__(self, title: str, color: str) -> None:
        super().__init__()
        self.enabled = QCheckBox(title)
        self.enabled.setStyleSheet(f"QCheckBox {{ color: {color}; font-weight: 600; }}")
        self.start, self.end = QDateTimeEdit(), QDateTimeEdit()
        for e in (self.start, self.end):
            e.setDisplayFormat("yyyy-MM-dd HH:mm")
            e.setCalendarPopup(True)
            e.editingFinished.connect(self.edited)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.enabled)
        lay.addWidget(self.start, 1)
        lay.addWidget(QLabel("to"))
        lay.addWidget(self.end, 1)
        self.enabled.toggled.connect(self._sync)
        self.enabled.toggled.connect(lambda *_: self.edited.emit())
        self._sync(False)

    def _sync(self, on: bool) -> None:
        self.start.setEnabled(on)
        self.end.setEnabled(on)

    def set_range(self, t0: pd.Timestamp, t1: pd.Timestamp) -> None:
        for e in (self.start, self.end):
            e.setDateTimeRange(QDateTime(t0.to_pydatetime()), QDateTime(t1.to_pydatetime()))

    def set_period(self, p: Period, t0: pd.Timestamp, t1: pd.Timestamp) -> None:
        for w in (self.enabled, self.start, self.end):
            w.blockSignals(True)
        self.enabled.setChecked(not p.is_open)
        self._sync(not p.is_open)
        self.start.setDateTime(QDateTime(pd.Timestamp(p.start or t0).to_pydatetime()))
        self.end.setDateTime(QDateTime(pd.Timestamp(p.end or t1).to_pydatetime()))
        for w in (self.enabled, self.start, self.end):
            w.blockSignals(False)

    def period(self) -> Period:
        if not self.enabled.isChecked():
            return Period()
        fmt = "%Y-%m-%d %H:%M:%S"
        return Period(self.start.dateTime().toPython().strftime(fmt), self.end.dateTime().toPython().strftime(fmt))


class DataPage(QWidget):
    title = "Data"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        s = ctx.session

        # -- source ----------------------------------------------------------
        self.kind_csv, self.kind_tsf = QRadioButton("CSV (one file)"), QRadioButton("FlowFinity TSF (rain + flow)")
        self.kind_csv.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.kind_csv)
        grp.addButton(self.kind_tsf)
        self.path, self.flow_path = QLineEdit(), QLineEdit()
        b1, b2 = QPushButton("Browse..."), QPushButton("Browse...")
        b1.clicked.connect(lambda: self._browse(self.path))
        b2.clicked.connect(lambda: self._browse(self.flow_path))
        self.column_boxes = {role: QComboBox() for role, _ in _COLUMN_ROLES}
        self.units = QComboBox()
        self.units.addItems(list(FLOW_TO_CFS))
        self.clip = QCheckBox("Set negative flows to zero")
        self.clip.setChecked(True)
        self.name = QLineEdit()
        self.name.setPlaceholderText("dataset name")
        load = QPushButton("Load dataset")
        load.setObjectName("primary")
        load.clicked.connect(self._load)

        src = QGroupBox("Source")
        form = QFormLayout(src)
        form.addRow(self.kind_csv)
        form.addRow(self.kind_tsf)
        r1 = QHBoxLayout()
        r1.addWidget(self.path, 1)
        r1.addWidget(b1)
        r2 = QHBoxLayout()
        r2.addWidget(self.flow_path, 1)
        r2.addWidget(b2)
        self._flow_label = QLabel("Flow file")
        form.addRow("File", r1)
        form.addRow(self._flow_label, r2)
        self._column_labels = {}
        for role, label in _COLUMN_ROLES:
            lbl = QLabel(label)
            self._column_labels[role] = lbl
            form.addRow(lbl, self.column_boxes[role])
        form.addRow("Flow units", self.units)
        form.addRow(self.clip)
        form.addRow("Name", self.name)
        form.addRow(load)
        self.kind_csv.toggled.connect(self._kind_changed)
        self.path.editingFinished.connect(self._sniff)
        self._kind_changed(True)

        # -- datasets & periods -------------------------------------------------
        self.datasets = QComboBox()
        self.datasets.currentTextChanged.connect(lambda n: n and s.select_dataset(n))
        self.cal = _PeriodEditor("Calibration", PERIOD_COLORS["calibration"])
        self.val = _PeriodEditor("Validation", PERIOD_COLORS["validation"])
        for ed in (self.cal, self.val):
            ed.edited.connect(self._apply_periods)
        per = QGroupBox("Project datasets and periods")
        pl = QVBoxLayout(per)
        pl.addWidget(self.datasets)
        pl.addWidget(self.cal)
        pl.addWidget(self.val)
        hint = QLabel("Set periods here or on the chart: use the toolbar's Select tools and drag across the "
                      "chart, then drag the shaded regions or their edges. Changes apply immediately. Without a "
                      "calibration period the whole record is used; the validation period is scored but never "
                      "used for fitting.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        pl.addWidget(hint)
        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(src)
        ll.addWidget(per)
        ll.addWidget(self.summary)
        ll.addStretch(1)
        left.setMinimumWidth(360)
        left.setMaximumWidth(480)

        self.plot = TimeseriesPlot()
        self.toolbar = ChartToolbar(self.plot, periods=True)
        self.toolbar.periodEdited.connect(self._period_from_chart)
        self.toolbar.periodCleared.connect(lambda key: self.ctx.session.set_period(key, Period()))
        chart = QWidget()
        cl = QVBoxLayout(chart)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.toolbar)
        cl.addWidget(self.plot, 1)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(chart)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Data", "Load rainfall and flow, check the record, and choose the calibration "
                                          "and validation periods."))
        lay.addWidget(split, 1)
        s.datasetChanged.connect(self.refresh)
        s.projectChanged.connect(self.refresh)
        s.periodsChanged.connect(self._show_periods)

    # ------------------------------------------------------------------ source

    def _kind_changed(self, csv: bool) -> None:
        self.flow_path.setEnabled(not csv)
        self._flow_label.setEnabled(not csv)
        for role, box in self.column_boxes.items():
            box.setEnabled(csv)
            self._column_labels[role].setEnabled(csv)

    def _browse(self, target: QLineEdit) -> None:
        filt = "CSV files (*.csv);;All files (*)" if self.kind_csv.isChecked() else "TSF files (*.tsf);;All files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", target.text() or str(Path.home()), filt)
        if path:
            target.setText(path)
            if target is self.path:
                self._sniff()

    def _sniff(self) -> None:
        p = self.path.text().strip()
        if not p or not Path(p).exists():
            return
        if not self.name.text():
            self.name.setText(Path(p).parent.name if self.kind_tsf.isChecked() else Path(p).stem)
        if not self.kind_csv.isChecked():
            return
        try:
            cols = sniff_columns(p)
        except Exception as exc:
            QMessageBox.warning(self, "Cannot read file", str(exc))
            return
        guess = guess_columns(cols)
        for role, box in self.column_boxes.items():
            box.clear()
            box.addItem("", "")
            for c in cols:
                box.addItem(c, c)
            box.setCurrentIndex(max(0, box.findData(guess.get(role, ""))))

    def _spec(self) -> DatasetSpec:
        name = self.name.text().strip() or Path(self.path.text()).stem or "dataset"
        kind = "csv" if self.kind_csv.isChecked() else "tsf"
        return DatasetSpec(
            name=name, kind=kind, path=self.path.text().strip(), flow_path=self.flow_path.text().strip(),
            columns={role: box.currentData() or "" for role, box in self.column_boxes.items()},
            flow_units=self.units.currentText(), clip_negative_flow=self.clip.isChecked(),
        )

    def _load(self) -> None:
        spec = self._spec()
        if not spec.path:
            QMessageBox.information(self, "Load dataset", "Choose a file first.")
            return

        def work(_ctx):
            return load_dataset(spec)

        def done(frame: pd.DataFrame) -> None:
            self.ctx.session.add_dataset(spec, frame)

        self.ctx.jobs.submit(f"Load {spec.name}", work, on_done=done,
                             on_error=lambda m: QMessageBox.warning(self, "Load failed", m))

    # ------------------------------------------------------------------ periods

    def _apply_periods(self) -> None:
        self.ctx.session.set_periods(self.cal.period(), self.val.period())

    def _period_from_chart(self, key: str, x0: float, x1: float) -> None:
        """Snap a chart selection (epoch seconds) to the record's time steps and store it in the session."""
        frame = self.ctx.session.frame()
        if frame is None:
            return
        t = frame["datetime"].to_numpy()
        a = np.datetime64(pd.to_datetime(x0, unit="s"))
        b = np.datetime64(pd.to_datetime(x1, unit="s"))
        i0 = int(np.clip(np.searchsorted(t, a), 0, len(t) - 1))
        i1 = int(np.clip(np.searchsorted(t, b, side="right") - 1, 0, len(t) - 1))
        if i1 <= i0:
            self._show_periods()  # too small a selection: put the region back where the session has it
            return
        fmt = "%Y-%m-%d %H:%M:%S"
        self.ctx.session.set_period(key, Period(pd.Timestamp(t[i0]).strftime(fmt), pd.Timestamp(t[i1]).strftime(fmt)))

    def _show_periods(self) -> None:
        """Mirror the session's periods in the editors and as draggable regions on the chart."""
        s = self.ctx.session
        ds = s.dataset
        try:
            frame = s.frame()
        except Exception:  # unreadable file: refresh() reports it
            return
        if ds is None or frame is None:
            return
        t0, t1 = frame["datetime"].iloc[0], frame["datetime"].iloc[-1]
        for key, ed, p in (("calibration", self.cal, ds.calibration), ("validation", self.val, ds.validation)):
            ed.set_period(p, t0, t1)
            if p.is_open:
                self.plot.remove_period(key)
            else:
                a, b = epoch_seconds([pd.Timestamp(p.start or t0), pd.Timestamp(p.end or t1)])
                self.plot.set_period(key, float(a), float(b))

    # ------------------------------------------------------------------ refresh

    def refresh(self) -> None:
        s = self.ctx.session
        self.datasets.blockSignals(True)
        self.datasets.clear()
        self.datasets.addItems([d.name for d in s.project.datasets])
        if s.dataset_name:
            self.datasets.setCurrentText(s.dataset_name)
        self.datasets.blockSignals(False)
        ds = s.dataset
        try:
            frame = s.frame()
        except Exception as exc:
            self.summary.setText(f"Could not read {ds.name if ds else 'dataset'}: {exc}")
            return
        if frame is None or ds is None:
            self.summary.setText("No dataset loaded.")
            self.plot.set_data([], None, None)
            return
        t = epoch_seconds(frame["datetime"])
        self.plot.set_data(t, frame["rain"].to_numpy(), frame["stormflow"].to_numpy())
        t0, t1 = frame["datetime"].iloc[0], frame["datetime"].iloc[-1]
        for ed in (self.cal, self.val):
            ed.set_range(t0, t1)
        self._show_periods()
        sm = summarize(frame)
        self.summary.setText(
            f"<b>{ds.name}</b>: {sm.rows:,} rows, {sm.start:%Y-%m-%d %H:%M} to {sm.end:%Y-%m-%d %H:%M}<br>"
            f"time step {sm.dt_minutes:g} min ({sm.irregular_steps} irregular steps), total rain "
            f"{sm.total_rain:.2f} in, peak flow {sm.peak_flow:.3g} cfs, missing flow values {sm.missing_flow}")
