"""Import sewersheds (zones) or sites from a GIS file: file -> layer -> preview -> field mapping -> options.

Reading runs on the job pool (pyogrio does not touch the project); the import
itself is done by the Sites page through the session once the dialog is
accepted. See :mod:`sparsehydro_viewer.core.gis`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import gis
from ..widgets.map_view import MapFeature, MapView
from .context import AppContext

TYPES = ("str", "float", "int", "bool")
DUPLICATES = {"skip": "Skip them (keep what is in the project)",
              "update": "Update their geometry and attributes",
              "add": "Add them again as new features"}


class GisImportDialog(QDialog):
    """Choose a layer and how to map it; :meth:`result_plan` gives ``(layer, plan)`` after acceptance."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None, path: str | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Import sewersheds or sites from GIS")
        self.resize(1000, 680)
        self.layer: gis.GisLayer | None = None
        self._job = None

        # -- source ---------------------------------------------------------------------
        self.path = QLineEdit(path or "")
        self.path.setReadOnly(True)
        self.path.setPlaceholderText("choose a file or a file geodatabase (.gdb folder)")
        self.path.setAccessibleName("GIS source")
        browse = QPushButton("File…")
        browse.setToolTip("Shapefile, GeoPackage, GeoJSON, KML/KMZ, FlatGeobuf, ...")
        browse.clicked.connect(self._browse_file)
        gdb = QPushButton("Geodatabase…")
        gdb.setToolTip("Choose a file geodatabase folder (.gdb)")
        gdb.clicked.connect(self._browse_gdb)
        self.layers = QComboBox()
        self.layers.setToolTip("Layer to import (geometry type, number of features, coordinate system)")
        self.layers.setAccessibleName("Layer")
        self.layers.currentIndexChanged.connect(self._read_layer)
        src = QGroupBox("Source")
        sl = QFormLayout(src)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        row.addWidget(gdb)
        sl.addRow("File", row)
        sl.addRow("Layer", self.layers)

        # -- preview ----------------------------------------------------------------------
        self.preview = MapView()
        self.preview.setMinimumHeight(220)
        self.preview.setToolTip("Preview of the layer (reprojected to longitude/latitude)")
        self.summary = QLabel("Choose a file.")
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)

        # -- mapping ------------------------------------------------------------------------
        self.label_field = QComboBox()
        self.label_field.setToolTip("Column with each feature's name (empty names become '<layer> <n>')")
        self.id_field = QComboBox()
        self.id_field.setToolTip("Column with each feature's identifier: kept as an alternative id and used to "
                                 "recognise features already in the project")
        self.zone_kind = QComboBox()
        self.zone_kind.setToolTip("Kind of the imported zones, fixed or read from a column")
        self.duplicates = QComboBox()
        for key, text in DUPLICATES.items():
            self.duplicates.addItem(text, key)
        self.duplicates.setToolTip("Features whose id (or name, without an id column) is already in the project")
        self.link = QCheckBox("Link each site to the zones that contain it")
        self.link.setChecked(True)
        self.link.setToolTip("Adds BELONGS_TO_ZONE relations between every located site and the zones around it")
        self.area = QCheckBox("Store each zone's area (acres) as 'Contributing area'")
        self.area.setChecked(True)
        self.area.setToolTip("Computed on the WGS84 ellipsoid from the polygon (holes excluded)")
        form = QFormLayout()
        form.addRow("Name column", self.label_field)
        form.addRow("Id column", self.id_field)
        form.addRow("Zone kind", self.zone_kind)
        form.addRow("Already in the project", self.duplicates)
        form.addRow(self.link)
        form.addRow(self.area)
        self.columns = QTableWidget(0, 5)
        self.columns.setHorizontalHeaderLabels(["Import", "Column", "Attribute name", "Type", "Unit"])
        self.columns.verticalHeader().setVisible(False)
        self.columns.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.columns.horizontalHeader().setStretchLastSection(True)
        self.columns.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.columns.setAccessibleName("Columns imported as attributes")
        self.columns.setToolTip("Tick the columns to keep as attributes; the name, type and unit can be edited")
        mapping = QGroupBox("Mapping")
        ml = QVBoxLayout(mapping)
        ml.addLayout(form)
        ml.addWidget(QLabel("Attributes"))
        ml.addWidget(self.columns, 1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.preview, 1)
        ll.addWidget(self.summary)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(mapping)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(src)
        lay.addWidget(split, 1)
        lay.addWidget(self.buttons)
        if path:
            self.set_source(path)

    # ------------------------------------------------------------------ source

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "GIS layer", "", gis.FILE_FILTER)
        if path:
            self.set_source(path)

    def _browse_gdb(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "File geodatabase (.gdb folder)")
        if path:
            self.set_source(path)

    def set_source(self, path: str) -> None:
        self.path.setText(path)
        self.layers.blockSignals(True)
        self.layers.clear()
        try:
            infos = gis.list_layers(path)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.summary.setText(f"Cannot read {Path(path).name}: {exc}")
            self.layers.blockSignals(False)
            return
        for info in infos:
            crs = f", {info.crs}" if info.crs else ", no coordinate system"
            self.layers.addItem(f"{info.name}  ({info.geometry_type}, {info.count} features{crs})", info.name)
        # Prefer a polygon layer (sewersheds) in multi-layer sources such as geodatabases.
        poly = next((i for i, info in enumerate(infos) if "Polygon" in info.geometry_type), 0)
        self.layers.setCurrentIndex(poly)
        self.layers.blockSignals(False)
        self._read_layer()

    def _read_layer(self) -> None:
        name, path = self.layers.currentData(), self.path.text()
        if not name or not path:
            return
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.summary.setText(f"Reading {name}…")

        def work(ctx):
            return gis.read_layer(path, name, progress=lambda i, n, t: ctx.progress(t, i / n if n else None),
                                  should_stop=ctx.token)

        def failed(msg: str) -> None:
            self.summary.setText(f"Cannot read {name}: {msg}")

        self._job = self.ctx.jobs.submit(f"Read {name}", work, on_done=self.show_layer, on_error=failed)

    # ------------------------------------------------------------------ mapping

    def show_layer(self, layer: gis.GisLayer) -> None:
        self.layer = layer
        kind = layer.kind
        n = len(layer.features)
        what = {"zone": "polygons, imported as zones", "site": "points, imported as sites"}.get(
            kind, "geometries that cannot be imported (only polygons and points)")
        crs = layer.crs or "none (coordinates read as longitude/latitude)"
        warn = f" {len(layer.warnings)} feature(s) could not be read." if layer.warnings else ""
        self.summary.setText(f"{n} features: {what}. Coordinate system: {crs}.{warn}")
        color = "#8e44ad" if kind == "zone" else "#0072B2"
        self.preview.set_features([MapFeature(f"f{i}", str(i + 1), f.wkt, color, "zone" if f.kind == "polygon"
                                              else "site") for i, f in enumerate(layer.features) if f.wkt])
        self.preview.zoom_to()
        plan = gis.ImportPlan.default(layer)
        for combo, value, blank in ((self.label_field, plan.label_field, "(number the features)"),
                                    (self.id_field, plan.id_field, "(none)")):
            combo.clear()
            combo.addItem(blank, "")
            for f in layer.fields:
                combo.addItem(f, f)
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.zone_kind.clear()
        for k in gis.ZONE_KINDS:
            self.zone_kind.addItem(k.replace("_", " ").title(), k)
        for f in layer.fields:
            self.zone_kind.addItem(f"From column {f}", f)
        is_zone = kind == "zone"
        for w in (self.zone_kind, self.area):
            w.setEnabled(is_zone)
        self.columns.setRowCount(len(layer.fields))
        planned = {c.field: c for c in plan.columns}
        for r, f in enumerate(layer.fields):
            c = planned.get(f) or gis.ColumnPlan(f, gis.attribute_key(f), f, gis.infer_type(layer.field_values(f)))
            tick = QTableWidgetItem()
            tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            tick.setCheckState(Qt.CheckState.Checked if f in planned else Qt.CheckState.Unchecked)
            self.columns.setItem(r, 0, tick)
            col = QTableWidgetItem(f)
            col.setFlags(Qt.ItemFlag.ItemIsEnabled)
            example = next((v for v in layer.field_values(f) if v not in (None, "")), "")
            col.setToolTip(f"Example: {example}")
            self.columns.setItem(r, 1, col)
            self.columns.setItem(r, 2, QTableWidgetItem(c.label))
            types = QComboBox()
            types.addItems(TYPES)
            types.setCurrentText(c.value_type)
            types.setAccessibleName(f"Type of {f}")
            self.columns.setCellWidget(r, 3, types)
            self.columns.setItem(r, 4, QTableWidgetItem(c.unit))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(kind != "unsupported")

    def result_plan(self) -> tuple[gis.GisLayer, gis.ImportPlan]:
        """The layer read and the plan built from the dialog's choices."""
        assert self.layer is not None
        columns = []
        for r in range(self.columns.rowCount()):
            if self.columns.item(r, 0).checkState() != Qt.CheckState.Checked:
                continue
            field_name = self.columns.item(r, 1).text()
            label = self.columns.item(r, 2).text().strip() or field_name
            columns.append(gis.ColumnPlan(field_name, gis.attribute_key(label), label,
                                          self.columns.cellWidget(r, 3).currentText(),
                                          self.columns.item(r, 4).text().strip()))
        plan = gis.ImportPlan(label_field=self.label_field.currentData() or "", id_field=self.id_field.currentData()
                              or "", zone_kind=self.zone_kind.currentData() or "SEWERSHED", columns=columns,
                              on_duplicate=self.duplicates.currentData(), link_sites=self.link.isChecked(),
                              store_area=self.area.isChecked() and self.layer.kind == "zone")
        return self.layer, plan


__all__ = ["GisImportDialog"]
