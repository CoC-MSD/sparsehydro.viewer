"""Sites workspace: the project's monitoring sites and zones, their data, locations and attributes.

* left - tree of sites (with their sensors and datasets) and zones;
* centre - Map (locations, zones) and Time series (the current dataset, with
  calibration and validation periods);
* right - properties of the selected nodes.

Selection is shared through the session: selecting in the tree selects on
the map and vice versa, and a site with data becomes the current dataset.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, theme
from ..core.data import Period, epoch_seconds, load_dataset, summarize
from ..core.geometry import parse_point, point_wkt, polygon_wkt
from ..resources import icon
from ..widgets import TimeseriesPlot
from ..widgets.chart_actions import PeriodActions
from ..widgets.map_view import MapFeature, MapView
from ..widgets.period_editor import PeriodEditor
from ..widgets.tile_layer import DEFAULT_ATTRIBUTION
from ..widgets.timeseries_plot import PERIOD_COLORS
from .common import page_header
from .context import AppContext
from .import_dialog import ImportDialog
from .node_properties import NodePropertiesPanel
from .shell.page import Page

ROLE = Qt.ItemDataRole.UserRole  # (kind, key): ("site"|"sensor"|"zone", iri) or ("dataset", name)

SENSOR_LABELS = {"FLOW_METER": "Flow meter", "RAIN_GAGE": "Rain gauge", "LEVEL_SENSOR": "Level sensor",
                 "VELOCITY_SENSOR": "Velocity sensor", "TEMPERATURE_SENSOR": "Temperature sensor",
                 "VIRTUAL": "Virtual sensor"}


def site_color(kinds: set[str]) -> str:
    """Map colour by what a site measures."""
    if {"FLOW_METER", "RAIN_GAGE"} <= kinds:
        return theme.series_color(0)
    if "FLOW_METER" in kinds:
        return theme.series_color(2)
    if "RAIN_GAGE" in kinds:
        return theme.series_color(4)
    return theme.current().muted


class SitesPage(Page):
    title = "Sites"
    icon_name = "nav-sites"
    primary_text = "Import data…"
    primary_tip = "Read rainfall and flow files into the project, as a new site or at an existing one"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        s = ctx.session
        self.settings = QSettings()

        # -- tree -------------------------------------------------------------
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Type"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._tree_selection_changed)
        self.tree.setColumnWidth(0, 200)
        tree_box = QGroupBox("Sites and zones")
        tl = QVBoxLayout(tree_box)
        tl.addWidget(self.tree)
        tree_box.setMinimumWidth(260)

        # -- map ----------------------------------------------------------------
        self.map = MapView()
        self.map.selectionChanged.connect(s.select_nodes)
        self.map.pointMoved.connect(self._point_moved)
        self.map.placeRequested.connect(self._place)
        self.map.polygonDrawn.connect(self._zone_drawn)
        self.map.modeChanged.connect(self._map_mode_changed)

        # -- time series ------------------------------------------------------------
        self.datasets = QComboBox()
        self.datasets.setToolTip("Dataset shown on the chart (also the analysis dataset of every page)")
        self.datasets.setAccessibleName("Dataset shown")
        self.datasets.currentTextChanged.connect(lambda n: n and s.select_dataset(n))
        self.cal = PeriodEditor("Calibration", PERIOD_COLORS["calibration"])
        self.val = PeriodEditor("Validation", PERIOD_COLORS["validation"])
        for ed in (self.cal, self.val):
            ed.edited.connect(self._apply_periods)
        self.plot = TimeseriesPlot()
        self.periods = PeriodActions(self.plot, self)
        self.periods.periodEdited.connect(self._period_from_chart)
        self.periods.periodCleared.connect(lambda key: s.set_period(key, Period()))
        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        ts = QWidget()
        tsl = QVBoxLayout(ts)
        tsl.setContentsMargins(0, 4, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("Dataset"))
        row.addWidget(self.datasets, 1)
        tsl.addLayout(row)
        per = QHBoxLayout()
        per.addWidget(self.cal, 1)
        per.addWidget(self.val, 1)
        tsl.addLayout(per)
        tsl.addWidget(self.plot, 1)
        tsl.addWidget(self.summary)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.map, icon("nav-sites"), "Map")
        self.tabs.addTab(ts, icon("nav-data"), "Time series")
        self.tabs.currentChanged.connect(lambda *_: self.contextChanged.emit())

        # -- properties ------------------------------------------------------------
        self.props = NodePropertiesPanel(ctx)
        props_box = QGroupBox("Properties")
        pl = QVBoxLayout(props_box)
        pl.addWidget(self.props)
        props_box.setMinimumWidth(300)

        split = QSplitter()
        split.addWidget(tree_box)
        split.addWidget(self.tabs)
        split.addWidget(props_box)
        split.setStretchFactor(1, 1)
        lay = QVBoxLayout(self)
        lay.addWidget(page_header("Sites", "Monitoring sites and zones with their data, locations and attributes. "
                                           "Import data, place sites on the map, and choose the calibration and "
                                           "validation periods of each dataset."))
        lay.addWidget(split, 1)

        # -- actions -------------------------------------------------------------------
        self.add_site_action = self.action("Add site", "Add a monitoring site (place it on the map afterwards)",
                                           "map-pin", self._add_site)
        self.draw_zone_action = self.action("Draw zone", "Draw a zone (sewershed, drainage area) on the map: "
                                                         "click vertices, double-click to finish", "polygon",
                                            self._draw_zone, checkable=True)
        self.delete_action = self.action("Delete", "Delete the selected sites or zones and their data", "delete",
                                         self._delete)
        self.edit_locations_action = self.action(
            "Edit locations", "Drag sites to move them; click the map to place the selected site", "move-pin",
            self._toggle_edit_locations, checkable=True)
        self.zoom_selection_action = self.action("Zoom to selection", "Zoom the map to the selected sites and zones",
                                                 "zoom-selection", lambda: self.map.zoom_to(s.selected_nodes or None))
        self.basemap_action = self.action("Basemap", "Show OpenStreetMap tiles under the map (online)", "nav-sites",
                                          self._toggle_basemap, checkable=True)
        self.gis_import_action = self.action(
            "Import GIS layer…", "Import sewersheds (polygons) or sites (points) from a file geodatabase, shapefile, "
                                "GeoPackage, GeoJSON or KML, with their attributes", "load-data", self.import_gis)
        self.gis_export_action = self.action(
            "Export to GIS…", "Save the zones or the sites (the selected ones, or all) to a GeoPackage, GeoJSON or "
                              "shapefile", "export", self.export_gis)
        # Select tool: one button whose arrow switches between rectangle and lasso selection.
        self.select_action = self.action(
            "Select", "Select on the map: click a site or zone (Ctrl+click adds or removes), drag to select what is "
                      "inside; Alt picks zones only, Esc clears. The arrow switches rectangle / lasso.",
            "select", lambda: self._set_map_tool(self._select_shape), shortcut="S", checkable=True)
        self._select_shape = "select"
        menu = QMenu(self)
        for mode, text, icon_name in (("select", "Rectangle", "select"), ("lasso", "Lasso (free shape)", "lasso")):
            a = menu.addAction(icon(icon_name), text)
            a.triggered.connect(lambda _=False, m=mode: self._choose_select_shape(m))
        self.select_action.setMenu(menu)
        self._select_menu = menu
        self.select_action.setChecked(True)

        s.projectChanged.connect(self._project_changed)
        s.nodesStructureChanged.connect(self.rebuild)
        s.nodesChanged.connect(lambda iris: self.rebuild())
        s.nodeSelectionChanged.connect(self._selection_changed)
        s.datasetChanged.connect(self.refresh_series)
        s.datasetChanged.connect(self.rebuild)
        s.datasetChanged.connect(self.contextChanged)
        s.periodsChanged.connect(self._show_periods)
        s.periodsChanged.connect(self.contextChanged)
        self._syncing = False
        self.rebuild()
        self.refresh_series()
        if self.settings.value("map/basemap", False, type=bool):
            self.basemap_action.setChecked(True)
            self._apply_basemap(True)

    # ------------------------------------------------------------------ shell

    def primary(self) -> None:
        self.import_data()

    def context_actions(self):
        if self.tabs.currentIndex() == 1:
            acts = [self.add_site_action, self.delete_action, None, *self.periods.actions()]
        else:  # map tools: one exclusive group together with the toolbar's Pan and Zoom box
            acts = [self.select_action, self.edit_locations_action, self.draw_zone_action, None,
                    self.add_site_action, self.delete_action, None, self.gis_import_action, self.gis_export_action,
                    None, self.zoom_selection_action, self.basemap_action]
        self.delete_action.setEnabled(bool(self.ctx.session.selected_nodes))
        return acts

    def active_chart(self):
        """The time-series chart on its tab, the map on the Map tab (the toolbar's Pan, Zoom box, Fit all and
        Export act on it)."""
        return self.plot if self.tabs.currentIndex() == 1 else self.map

    # ------------------------------------------------------------------ GIS

    def import_gis(self, path: str | None = None) -> None:
        from ..core import gis
        from .gis_import_dialog import GisImportDialog

        if not gis.available():
            QMessageBox.information(self, "Import GIS layer", gis.MISSING)
            return
        dlg = GisImportDialog(self.ctx, self, path)
        if dlg.exec() != QDialog.DialogCode.Accepted or dlg.layer is None:
            return
        layer, plan = dlg.result_plan()
        self.import_gis_layer(layer, plan)

    def import_gis_layer(self, layer, plan):
        """Import an already-read layer with *plan*; select and show what was added."""
        s = self.ctx.session
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            report = s.import_gis_layer(layer, plan)
        finally:
            QApplication.restoreOverrideCursor()
        if report.added or report.updated:
            s.select_nodes(report.added or report.updated)
            self.tabs.setCurrentIndex(0)
            self.map.zoom_to(report.added or report.updated)
        msg = f"{layer.name}: {report.summary()}."
        if report.refused:
            QMessageBox.information(self, "Import GIS layer", msg + "\n\nNot imported:\n" + "\n".join(report.refused[:20]))
        self.window().statusBar().showMessage(msg, 10000)
        return report

    def export_gis(self) -> None:
        from ..core import gis

        if not gis.available():
            QMessageBox.information(self, "Export to GIS", gis.MISSING)
            return
        s = self.ctx.session
        choice, ok = QInputDialog.getItem(self, "Export to GIS", "Export:", ["Zones", "Sites"], 0, False)
        if not ok:
            return
        table = "zone" if choice == "Zones" else "monitoring_site"
        path, _ = QFileDialog.getSaveFileName(self, "Export to GIS", f"{choice.lower()}.gpkg",
                                              "GeoPackage (*.gpkg);;GeoJSON (*.geojson);;Shapefile (*.shp)")
        if not path:
            return
        selected = [i for i in s.selected_nodes if (n := s.store.node(i)) is not None and n.table == table]
        try:
            n = gis.export_nodes(s.store, path, table, iris=selected or None)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            QMessageBox.warning(self, "Export to GIS", f"Could not export: {exc}")
            return
        self.window().statusBar().showMessage(f"Exported {n} {choice.lower()} to {path}", 8000)

    def _set_map_tool(self, mode: str) -> None:
        self.tabs.setCurrentIndex(0)
        self.map.set_mode(mode)

    def _choose_select_shape(self, mode: str) -> None:
        self._select_shape = mode
        self.select_action.setIcon(icon("lasso" if mode == "lasso" else "select"))
        self._set_map_tool(mode)

    def status_text(self) -> str:
        s = self.ctx.session
        n = len(s.selected_nodes)
        parts = [f"{n} selected"] if n > 1 else []
        ds = s.dataset
        if ds is not None:
            cal = "whole record" if ds.calibration.is_open else \
                f"{ds.calibration.start[:10]} → {(ds.calibration.end or '')[:10]}"
            parts.append(f"calibration: {cal}")
        return "   ".join(parts)

    # ------------------------------------------------------------------ tree and map

    def rebuild(self) -> None:
        """Rebuild the tree and the map from the project database."""
        s = self.ctx.session
        st = s.store
        self._syncing = True
        self.tree.clear()
        features = []
        for site in st.nodes("monitoring_site"):
            sensors = st.sensors_of(site.iri)
            kinds = {n.extra.get("sensor_kind") for n in sensors}
            color = site_color(kinds)  # type: ignore[arg-type]
            item = QTreeWidgetItem([site.label or site.iri, "Site"])
            item.setIcon(0, icon("map-pin", color))
            item.setData(0, ROLE, ("site", site.iri))
            if parse_point(site.geometry) is None:
                item.setToolTip(0, "No location yet")
                item.setForeground(1, Qt.GlobalColor.gray)
                item.setText(1, "Site (no location)")
            for sensor in sensors:
                child = QTreeWidgetItem([sensor.label, SENSOR_LABELS.get(sensor.extra.get("sensor_kind"), "Sensor")])
                child.setData(0, ROLE, ("sensor", sensor.iri))
                item.addChild(child)
            for ds in s.datasets_of(site.iri):
                child = QTreeWidgetItem([ds.name, "Dataset"])
                child.setIcon(0, icon("nav-data"))
                child.setData(0, ROLE, ("dataset", ds.name))
                if ds.name == s.dataset_name:
                    f = child.font(0)
                    f.setBold(True)
                    child.setFont(0, f)
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            features.append(MapFeature(site.iri, site.label, site.geometry, color, "site",
                                       ", ".join(SENSOR_LABELS.get(k, k) for k in sorted(k for k in kinds if k))))
        for zone in st.nodes("zone"):
            item = QTreeWidgetItem([zone.label or zone.iri, "Zone"])
            item.setIcon(0, icon("polygon", theme.series_color(1)))
            item.setData(0, ROLE, ("zone", zone.iri))
            self.tree.addTopLevelItem(item)
            features.append(MapFeature(zone.iri, zone.label, zone.geometry, theme.series_color(1), "zone",
                                       zone.extra.get("zone_kind", "")))
        self.tree.expandAll()
        first = not self.map.features
        self.map.set_features(features)
        if first:
            self.map.zoom_to()
        self._syncing = False
        self._selection_changed(s.selected_nodes)

    def _tree_selection_changed(self) -> None:
        if self._syncing:
            return
        s = self.ctx.session
        iris, dataset = [], None
        for item in self.tree.selectedItems():
            kind, key = item.data(0, ROLE)
            if kind == "dataset":
                dataset = key
                parent = item.parent()
                if parent is not None:
                    iris.append(parent.data(0, ROLE)[1])
            else:
                iris.append(key)
        s.select_nodes(iris)
        if dataset:
            s.select_dataset(dataset)

    def _selection_changed(self, iris: list) -> None:
        self._syncing = True
        self.tree.clearSelection()
        wanted = set(iris)

        def walk(item: QTreeWidgetItem) -> None:
            kind, key = item.data(0, ROLE)
            if kind != "dataset" and key in wanted:
                item.setSelected(True)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        self._syncing = False
        self.map.set_selection(list(iris))
        self.props.show_nodes(list(iris))
        self.contextChanged.emit()

    # ------------------------------------------------------------------ editing

    def import_data(self) -> None:
        s = self.ctx.session
        preset = s.selected_nodes[0] if len(s.selected_nodes) == 1 and \
            (n := s.store.node(s.selected_nodes[0])) is not None and n.table == "monitoring_site" else None
        dlg = ImportDialog(s.store, self, preset_site=preset)
        if not dlg.exec() or dlg.spec is None:
            return
        spec, location = dlg.spec, dlg.location
        spec.name = s.project.unique_dataset_name(spec.name)

        def work(ctx):
            ctx.progress(f"reading {Path(spec.path).name}")
            return load_dataset(spec)

        def done(frame: pd.DataFrame) -> None:
            s.add_dataset(spec, frame)
            if location is not None and spec.site_iri:
                s.update_node(spec.site_iri, geometry=point_wkt(*location))
            s.nodesStructureChanged.emit()
            if spec.site_iri:
                s.select_nodes([spec.site_iri])
            self.tabs.setCurrentIndex(1)

        self.submit_job(f"Import {spec.name}", work, on_done=done,
                        on_error=lambda m: QMessageBox.warning(self, "Import failed", m))

    def _add_site(self) -> None:
        name, ok = QInputDialog.getText(self, "Add site", "Site name:")
        if ok and name.strip():
            iri = self.ctx.session.add_node("monitoring_site", name.strip())
            self.ctx.session.select_nodes([iri])
            self.tabs.setCurrentIndex(0)
            self.edit_locations_action.setChecked(True)
            self._toggle_edit_locations()
            self.window().statusBar().showMessage("Click the map to place the new site.", 6000)

    def _draw_zone(self) -> None:
        self.tabs.setCurrentIndex(0)
        if self.draw_zone_action.isChecked():
            self.edit_locations_action.setChecked(False)
            self.map.set_mode("draw")
            self.window().statusBar().showMessage("Click the zone's vertices; double-click or Enter to finish, "
                                                  "Esc to cancel.", 10000)
        else:
            self.map.set_mode(self._select_shape)

    def _zone_drawn(self, ring: list) -> None:
        name, ok = QInputDialog.getText(self, "New zone", "Zone name:")
        if ok and name.strip():
            iri = self.ctx.session.add_node("zone", name.strip(), geometry=polygon_wkt(ring))
            self.ctx.session.select_nodes([iri])

    def _delete(self) -> None:
        s = self.ctx.session
        iris = [i for i in s.selected_nodes if (n := s.store.node(i)) is not None and n.table != "sensor"]
        if not iris:
            return
        names = ", ".join(s.store.node(i).label for i in iris)  # type: ignore[union-attr]
        datasets = [d.name for i in iris for d in s.datasets_of(i)]
        extra = f"\n\nTheir datasets will be removed too: {', '.join(datasets)}." if datasets else ""
        if QMessageBox.question(self, "Delete", f"Delete {names}?{extra}") == QMessageBox.StandardButton.Yes:
            s.delete_nodes(iris)

    def _toggle_edit_locations(self) -> None:
        on = self.edit_locations_action.isChecked()
        if on:
            self.draw_zone_action.setChecked(False)
            self.tabs.setCurrentIndex(0)
        self.map.set_mode("move" if on else self._select_shape)

    def _map_mode_changed(self, mode: str) -> None:
        """Keep exactly one map tool checked (Pan and Zoom box follow the map through the toolbar)."""
        self.select_action.setChecked(mode in ("select", "lasso"))
        self.edit_locations_action.setChecked(mode == "move")
        self.draw_zone_action.setChecked(mode == "draw")

    def _point_moved(self, iri: str, lon: float, lat: float) -> None:
        self.ctx.session.update_node(iri, geometry=point_wkt(lon, lat))

    def _place(self, lon: float, lat: float) -> None:
        s = self.ctx.session
        sites = [i for i in s.selected_nodes if (n := s.store.node(i)) is not None and n.table == "monitoring_site"]
        if len(sites) == 1:
            s.update_node(sites[0], geometry=point_wkt(lon, lat))
        else:
            self.window().statusBar().showMessage("Select one site to place it.", 4000)

    # ------------------------------------------------------------------ basemap

    def _toggle_basemap(self) -> None:
        on = self.basemap_action.isChecked()
        if on and not self.settings.value("map/basemap_acknowledged", False, type=bool):
            answer = QMessageBox.question(
                self, "Online basemap",
                "The basemap downloads map tiles from OpenStreetMap's tile server, which then sees the areas you "
                "view (not your project data). Tiles are cached on this computer.\n\nTurn the basemap on?")
            if answer != QMessageBox.StandardButton.Yes:
                self.basemap_action.setChecked(False)
                return
            self.settings.setValue("map/basemap_acknowledged", True)
        self.settings.setValue("map/basemap", on)
        self._apply_basemap(on)

    def _apply_basemap(self, on: bool) -> None:
        from platformdirs import user_cache_dir

        cache = Path(user_cache_dir("sparsehydro-viewer")) / "tiles"
        cache.mkdir(parents=True, exist_ok=True)
        self.map.set_basemap(on, cache, self.settings.value("map/tile_url", None), DEFAULT_ATTRIBUTION,
                             user_agent=f"sparsehydro-viewer/{__version__}")

    # ------------------------------------------------------------------ time series and periods

    def _project_changed(self) -> None:
        self.map.features = {}
        self.rebuild()
        self.refresh_series()

    def refresh_series(self) -> None:
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
            self.summary.setText("No data yet: use Import data… in the toolbar.")
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
            f"<b>{ds.name}</b>: {sm.rows:,} rows, {sm.start:%Y-%m-%d %H:%M} to {sm.end:%Y-%m-%d %H:%M}; "
            f"time step {sm.dt_minutes:g} min ({sm.irregular_steps} irregular steps); total rain "
            f"{sm.total_rain:.2f} in; peak flow {sm.peak_flow:.3g} cfs; missing flow values {sm.missing_flow}")

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
            self._show_periods()
            return
        fmt = "%Y-%m-%d %H:%M:%S"
        self.ctx.session.set_period(key, Period(pd.Timestamp(t[i0]).strftime(fmt), pd.Timestamp(t[i1]).strftime(fmt)))

    def _show_periods(self) -> None:
        s = self.ctx.session
        ds = s.dataset
        try:
            frame = s.frame()
        except Exception:
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


__all__ = ["SitesPage", "site_color"]
