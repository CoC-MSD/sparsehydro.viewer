"""Import wizard: read rainfall and flow into the project, as a new site or at an existing one."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..core.data import FLOW_TO_CFS, DatasetSpec, guess_columns, sniff_columns
from ..core.store import ProjectStore

COLUMN_ROLES = (("datetime", "Date/time"), ("rain", "Rain (depth per step)"),
                ("stormflow", "Observed flow (target)"), ("temperature_c", "Temperature [°C] (optional)"))


class ImportDialog(QDialog):
    """Choose files and columns; the result is a :class:`DatasetSpec` plus where to put it.

    ``site_iri`` is ``None`` for a new site; ``location`` is an optional ``(lon, lat)`` for a new site.
    """

    def __init__(self, store: ProjectStore, parent: QWidget | None = None, preset_site: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import data")
        self.setMinimumWidth(560)
        self.store = store
        self.kind_csv, self.kind_tsf = QRadioButton("CSV (one file)"), QRadioButton("FlowFinity TSF (rain + flow)")
        self.kind_csv.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.kind_csv)
        grp.addButton(self.kind_tsf)
        self.path, self.flow_path = QLineEdit(), QLineEdit()
        b1, b2 = QPushButton("Browse…"), QPushButton("Browse…")
        b1.clicked.connect(lambda: self._browse(self.path))
        b2.clicked.connect(lambda: self._browse(self.flow_path))
        self.column_boxes = {role: QComboBox() for role, _ in COLUMN_ROLES}
        self.units = QComboBox()
        self.units.addItems(list(FLOW_TO_CFS))
        self.clip = QCheckBox("Set negative flows to zero")
        self.clip.setChecked(True)
        self.name = QLineEdit()
        self.name.setPlaceholderText("dataset name")

        src = QGroupBox("Source")
        form = QFormLayout(src)
        form.addRow(self.kind_csv)
        form.addRow(self.kind_tsf)
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        r1.addWidget(self.path, 1)
        r1.addWidget(b1)
        r2.addWidget(self.flow_path, 1)
        r2.addWidget(b2)
        self._flow_label = QLabel("Flow file")
        form.addRow("File", r1)
        form.addRow(self._flow_label, r2)
        self._column_labels = {}
        for role, label in COLUMN_ROLES:
            lbl = QLabel(label)
            self._column_labels[role] = lbl
            form.addRow(lbl, self.column_boxes[role])
        form.addRow("Flow units", self.units)
        form.addRow(self.clip)

        self.site = QComboBox()
        self.site.addItem("New site", None)
        for n in store.nodes("monitoring_site"):
            self.site.addItem(n.label or n.iri, n.iri)
        if preset_site:
            self.site.setCurrentIndex(max(0, self.site.findData(preset_site)))
        self.lon, self.lat = QDoubleSpinBox(), QDoubleSpinBox()
        for w, lim in ((self.lon, 180), (self.lat, 90)):
            w.setRange(-lim, lim)
            w.setDecimals(6)
            w.setSuffix(" °")
            w.setSpecialValueText("not set")
            w.setMinimum(-lim - 1)  # the "not set" value sits just below the valid range
            w.setValue(-lim - 1)
        dst = QGroupBox("Destination")
        df = QFormLayout(dst)
        df.addRow("Site", self.site)
        df.addRow("Dataset name", self.name)
        loc = QHBoxLayout()
        loc.addWidget(QLabel("lon"))
        loc.addWidget(self.lon)
        loc.addWidget(QLabel("lat"))
        loc.addWidget(self.lat)
        self._loc_label = QLabel("Location (new site)")
        df.addRow(self._loc_label, loc)
        self.site.currentIndexChanged.connect(self._site_changed)
        self._site_changed()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(src)
        lay.addWidget(dst)
        lay.addWidget(buttons)
        self.kind_csv.toggled.connect(self._kind_changed)
        self.path.editingFinished.connect(self._sniff)
        self._kind_changed(True)
        self.spec: DatasetSpec | None = None
        self.site_iri: str | None = None
        self.location: tuple[float, float] | None = None

    def _site_changed(self) -> None:
        new = self.site.currentData() is None
        for w in (self.lon, self.lat, self._loc_label):
            w.setEnabled(new)

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

    def _accept(self) -> None:
        path = self.path.text().strip()
        if not path:
            QMessageBox.information(self, "Import data", "Choose a file first.")
            return
        kind = "csv" if self.kind_csv.isChecked() else "tsf"
        if kind == "tsf" and not self.flow_path.text().strip():
            QMessageBox.information(self, "Import data", "Choose the flow file too.")
            return
        self.site_iri = self.site.currentData()
        self.spec = DatasetSpec(
            name=self.name.text().strip() or Path(path).stem or "dataset", kind=kind, path=path,
            flow_path=self.flow_path.text().strip(),
            columns={role: box.currentData() or "" for role, box in self.column_boxes.items()},
            flow_units=self.units.currentText(), clip_negative_flow=self.clip.isChecked(), site_iri=self.site_iri)
        if self.site_iri is None and self.lon.value() >= -180 and self.lat.value() >= -90:
            self.location = (self.lon.value(), self.lat.value())
        self.accept()


__all__ = ["COLUMN_ROLES", "ImportDialog"]
