"""Sites workspace: map widget, tree and map linked through the session, import dialog, basemap privacy."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtWidgets import QInputDialog, QMessageBox

from sparsehydro_viewer.core.data import DatasetSpec
from sparsehydro_viewer.core.geometry import parse_point, parse_polygon, to_mercator
from sparsehydro_viewer.core.store import ProjectStore
from sparsehydro_viewer.widgets.map_view import MapFeature, MapView

NO_MOD = Qt.KeyboardModifier.NoModifier


# ---------------------------------------------------------------------------- map widget


@pytest.fixture
def map_view(qtbot):
    view = MapView()
    qtbot.addWidget(view)
    view.resize(600, 400)
    view.show()
    view.set_features([
        MapFeature("a", "A", "POINT (-84.50 39.10)", "#1f77b4"),
        MapFeature("b", "B", "POINT (-84.40 39.20)", "#ff7f0e"),
        MapFeature("c", "C (no location)", None, "#2ca02c"),
        MapFeature("z", "Zone", "POLYGON ((-84.6 39.0, -84.3 39.0, -84.3 39.3, -84.6 39.3, -84.6 39.0))",
                   "#9467bd", "zone"),
    ])
    view.zoom_to()
    return view


def test_map_picks_points_before_zones(map_view) -> None:
    ax, ay = to_mercator(-84.5, 39.1)
    assert map_view.pick(ax, ay) == "a"
    zx, zy = to_mercator(-84.35, 39.02)  # inside the zone, far from both sites
    assert map_view.pick(zx, zy) == "z"
    fx, fy = to_mercator(-80.0, 30.0)
    assert map_view.pick(fx, fy) is None
    assert map_view.empty_hint.isVisibleTo(map_view) and "1 site" in map_view.empty_hint.text()


def test_map_click_selection_with_ctrl_toggle(map_view, qtbot) -> None:
    ax, ay = to_mercator(-84.5, 39.1)
    bx, by = to_mercator(-84.4, 39.2)
    with qtbot.waitSignal(map_view.selectionChanged) as sig:
        map_view._clicked(QPointF(ax, ay), NO_MOD, False)
    assert sig.args == [["a"]]
    map_view._clicked(QPointF(bx, by), Qt.KeyboardModifier.ControlModifier, False)
    assert map_view.selection == ["a", "b"]
    map_view._clicked(QPointF(ax, ay), Qt.KeyboardModifier.ControlModifier, False)
    assert map_view.selection == ["b"]
    fx, fy = to_mercator(-80.0, 30.0)
    map_view._clicked(QPointF(fx, fy), NO_MOD, False)
    assert map_view.selection == []
    map_view.set_selection(["a", "unknown"])
    assert map_view.selection == ["a"]


def test_map_move_mode_places_and_draw_mode_makes_polygon(map_view, qtbot) -> None:
    map_view.set_mode("move")
    fx, fy = to_mercator(-84.0, 39.5)
    with qtbot.waitSignal(map_view.placeRequested) as sig:
        map_view._clicked(QPointF(fx, fy), NO_MOD, False)
    assert sig.args[0] == pytest.approx(-84.0) and sig.args[1] == pytest.approx(39.5)

    map_view.set_mode("draw")
    for lon, lat in ((-84.0, 39.0), (-83.9, 39.0), (-83.9, 39.1)):
        map_view._clicked(QPointF(*to_mercator(lon, lat)), NO_MOD, False)
    with qtbot.waitSignal(map_view.polygonDrawn) as sig:
        map_view._clicked(QPointF(*to_mercator(-83.9, 39.1)), NO_MOD, True)  # double-click finishes
    ring = sig.args[0]
    assert len(ring) == 3 and ring[0] == pytest.approx((-84.0, 39.0))
    assert map_view.mode == "select"
    with pytest.raises(ValueError):
        map_view.set_mode("nope")


def test_map_zoom_and_scale_bar(map_view) -> None:
    map_view.zoom_to(["a"])
    (x0, x1), (y0, y1) = map_view.vb.viewRange()
    ax, ay = to_mercator(-84.5, 39.1)
    assert x0 < ax < x1 and y0 < ay < y1 and (x1 - x0) < 5000  # tight around one point
    assert map_view.scale_bar.text.endswith(("m", "km"))


def test_map_basemap_off_creates_no_network_access(map_view) -> None:
    assert map_view.tiles is None
    assert not map_view.findChildren(QNetworkAccessManager)
    map_view.set_basemap(False)
    assert map_view.tiles is None and not map_view.attribution.isVisible()


# ---------------------------------------------------------------------------- sites page


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from sparsehydro_viewer.app import create_app
    from sparsehydro_viewer.views.main_window import MainWindow

    create_app()
    QSettings().setValue("map/basemap", False)
    win = MainWindow()
    win.show()
    yield win
    win.ctx.session.set_dirty(False)
    win.ctx.calibration.shutdown()
    win.close()
    win.deleteLater()


def _tree_iris(page) -> list[str]:
    out = []
    for i in range(page.tree.topLevelItemCount()):
        out.append(page.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)[1])
    return out


def test_nodes_appear_in_tree_and_map_and_selection_is_shared(window, qtbot) -> None:
    s = window.ctx.session
    page = window.pages[0]
    with qtbot.waitSignal(s.nodesStructureChanged):
        a = s.add_node("monitoring_site", "A", geometry="POINT (-84.5 39.1)")
    b = s.add_node("monitoring_site", "B")
    z = s.add_node("zone", "Shed", geometry="POLYGON ((-84.6 39.0, -84.3 39.0, -84.3 39.3, -84.6 39.0))")
    assert set(_tree_iris(page)) == {a, b, z}
    assert set(page.map.features) == {a, b, z}

    s.select_nodes([a])  # session -> tree, map, properties
    assert [i.data(0, Qt.ItemDataRole.UserRole)[1] for i in page.tree.selectedItems()] == [a]
    assert page.map.selection == [a] and page.props.iris == [a]

    page.map._select([z], NO_MOD)  # map -> session -> tree
    assert s.selected_nodes == [z]
    assert [i.data(0, Qt.ItemDataRole.UserRole)[1] for i in page.tree.selectedItems()] == [z]

    page.tree.clearSelection()  # tree -> session -> map
    page.tree.topLevelItem(_tree_iris(page).index(b)).setSelected(True)
    assert s.selected_nodes == [b] and page.map.selection == [b]
    assert not page.map._sel_points.data.size  # B has no location, so nothing is highlighted


def test_place_move_and_draw_update_the_database(window, qtbot, monkeypatch) -> None:
    s = window.ctx.session
    page = window.pages[0]
    b = s.add_node("monitoring_site", "B")
    s.select_nodes([b])
    page._place(-84.2, 39.3)
    assert parse_point(s.store.node(b).geometry) == pytest.approx((-84.2, 39.3))
    assert s.dirty
    page._point_moved(b, -84.25, 39.35)
    assert parse_point(s.store.node(b).geometry) == pytest.approx((-84.25, 39.35))

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("North shed", True)))
    page._zone_drawn([(-84.0, 39.0), (-83.9, 39.0), (-83.9, 39.1)])
    zones = s.store.nodes("zone")
    assert [z.label for z in zones] == ["North shed"]
    assert len(parse_polygon(zones[0].geometry)) == 3
    assert s.selected_nodes == [zones[0].iri]


def test_edit_locations_and_draw_zone_are_exclusive_modes(window) -> None:
    page = window.pages[0]
    page.edit_locations_action.setChecked(True)
    page._toggle_edit_locations()
    assert page.map.mode == "move"
    page.draw_zone_action.setChecked(True)
    page._draw_zone()
    assert page.map.mode == "draw" and not page.edit_locations_action.isChecked()
    page.map.set_mode("select")
    assert not page.draw_zone_action.isChecked() and not page.edit_locations_action.isChecked()


def test_delete_site_removes_its_sensors_and_datasets(window, qtbot, sample_frame, sample_csv, monkeypatch) -> None:
    s = window.ctx.session
    page = window.pages[0]
    with qtbot.waitSignal(window.ctx.controller.result, timeout=15000):
        s.add_dataset(DatasetSpec("MH-12", path=str(sample_csv)), sample_frame)
    site = s.dataset.site_iri
    assert s.selected_nodes == [site] and s.store.sensors_of(site)
    other = s.add_node("monitoring_site", "Other")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    page._delete()
    assert s.store.node(site) is None and not s.store.sensors_of(site)
    assert s.dataset is None and not s.project.datasets
    assert _tree_iris(page) == [other] and s.selected_nodes == []


def test_sites_page_never_touches_the_network_by_default(window) -> None:
    page = window.pages[0]
    assert not page.basemap_action.isChecked() and page.map.tiles is None
    assert not window.findChildren(QNetworkAccessManager)


def test_basemap_requires_acknowledgement(window, monkeypatch) -> None:
    from PySide6.QtCore import QSettings

    QSettings().setValue("map/basemap_acknowledged", False)
    page = window.pages[0]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    page.basemap_action.setChecked(True)
    page._toggle_basemap()
    assert not page.basemap_action.isChecked() and page.map.tiles is None


def test_application_icon(window, tmp_path) -> None:
    import importlib.util
    import struct
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from sparsehydro_viewer.resources import APP_ICON_SIZES, APP_ICON_SVG

    ic = QApplication.windowIcon()
    assert not ic.isNull() and {s.width() for s in ic.availableSizes()} >= {16, 32, 256}
    assert not window.windowIcon().isNull()
    spec = importlib.util.spec_from_file_location(
        "make_icon", Path(__file__).resolve().parents[2] / "packaging" / "make_icon.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.write_ico(APP_ICON_SVG, tmp_path / "app.ico", sizes=(16, 256))
    reserved, kind, count = struct.unpack("<HHH", out.read_bytes()[:6])
    assert (reserved, kind, count) == (0, 1, 2) and 256 in APP_ICON_SIZES


# ---------------------------------------------------------------------------- import dialog


def test_import_dialog_new_site_with_location(qtbot, sample_csv) -> None:
    from sparsehydro_viewer.views.import_dialog import ImportDialog

    dlg = ImportDialog(ProjectStore.memory())
    qtbot.addWidget(dlg)
    assert dlg.lon.isEnabled()
    dlg.path.setText(str(sample_csv))
    dlg._sniff()
    assert dlg.name.text() == sample_csv.stem
    assert dlg.column_boxes["rain"].currentData() and dlg.column_boxes["stormflow"].currentData()
    dlg.lon.setValue(-84.5)
    dlg.lat.setValue(39.1)
    dlg._accept()
    assert dlg.spec is not None and dlg.spec.kind == "csv" and dlg.spec.site_iri is None
    assert dlg.location == (-84.5, 39.1)


def test_import_dialog_into_existing_site(qtbot, sample_csv) -> None:
    from sparsehydro_viewer.views.import_dialog import ImportDialog

    st = ProjectStore.memory()
    site = st.add_site("Existing", geometry="POINT (0 0)")
    dlg = ImportDialog(st, preset_site=site)
    qtbot.addWidget(dlg)
    assert dlg.site.currentData() == site and not dlg.lon.isEnabled()
    dlg.path.setText(str(sample_csv))
    dlg._sniff()
    dlg._accept()
    assert dlg.spec.site_iri == site and dlg.location is None
