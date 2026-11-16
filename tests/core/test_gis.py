"""GIS import/export of zones and sites, and the geometry it relies on.

Fixtures are written by the tests (pyogrio): a shapefile in a state-plane CRS, a GeoPackage with a multipolygon
and a hole, GeoJSON points, a file geodatabase and a line layer. GIS tests skip without the ``gis`` extra.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from sparsehydro_viewer.core.geometry import (
    parse_point,
    parse_polygons,
    point_in_polygons,
    polygons_wkt,
    spherical_area_m2,
)


def same_ring(a, b, atol: float = 1e-7) -> bool:
    """Same vertices whatever the ring's direction and start (writers such as shapefiles reorient rings)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.shape != b.shape:
        return False
    for ring in (b, b[::-1]):
        for k in range(len(ring)):
            if np.allclose(a, np.roll(ring, k, axis=0), atol=atol):
                return True
    return False


SQUARE = [(-84.6, 39.0), (-84.3, 39.0), (-84.3, 39.3), (-84.6, 39.3)]
HOLE = [(-84.5, 39.1), (-84.4, 39.1), (-84.4, 39.2), (-84.5, 39.2)]
SECOND = [(-84.2, 39.0), (-84.1, 39.0), (-84.1, 39.1)]


# ---------------------------------------------------------------------------- geometry (no GIS packages)


def test_polygons_with_holes_and_multipolygons_round_trip() -> None:
    wkt = polygons_wkt([[SQUARE, HOLE], [SECOND]])
    assert wkt.startswith("MULTIPOLYGON (((")
    back = parse_polygons(wkt)
    assert len(back) == 2 and len(back[0]) == 2 and np.allclose(back[0][1], HOLE)
    single = parse_polygons("POLYGON Z ((0 0 1, 4 0 1, 4 4 1, 0 0 1))")
    assert single == [[[(0.0, 0.0), (4.0, 0.0), (4.0, 4.0)]]]
    assert parse_polygons("POINT (1 2)") == [] and parse_polygons("POLYGON EMPTY") == []
    assert polygons_wkt([[SQUARE]]).startswith("POLYGON ((")


def test_point_in_polygons_respects_holes() -> None:
    polys = [[SQUARE, HOLE], [SECOND]]
    assert point_in_polygons(-84.35, 39.25, polys)
    assert not point_in_polygons(-84.45, 39.15, polys)  # in the hole
    assert point_in_polygons(-84.15, 39.02, polys)  # second part
    assert not point_in_polygons(-85.0, 39.0, polys)


def test_spherical_area_is_close_to_the_ellipsoid() -> None:
    sphere = spherical_area_m2([[SQUARE]])
    pyproj = pytest.importorskip("pyproj")
    a, _ = pyproj.Geod(ellps="WGS84").polygon_area_perimeter([p[0] for p in SQUARE], [p[1] for p in SQUARE])
    assert sphere == pytest.approx(abs(a), rel=5e-3)
    assert spherical_area_m2([[SQUARE, HOLE]]) < sphere


def test_wkb_round_trip_and_ewkb() -> None:
    from sparsehydro_viewer.core.gis import parse_wkb, to_wkb

    assert parse_wkb(to_wkb("POINT (-84.5 39.1)")) == ("point", (-84.5, 39.1))
    kind, polys = parse_wkb(to_wkb(polygons_wkt([[SQUARE, HOLE], [SECOND]])))
    assert kind == "polygon" and len(polys) == 2 and np.allclose(polys[0][1][:4], HOLE)
    ewkb_point_z = struct.pack("<BIddd", 1, 0x80000001, 1.0, 2.0, 3.0)  # PostGIS point Z
    assert parse_wkb(ewkb_point_z) == ("point", (1.0, 2.0))
    iso_point_zm = struct.pack("<BIdddd", 1, 3001, 1.0, 2.0, 3.0, 4.0)
    assert parse_wkb(iso_point_zm) == ("point", (1.0, 2.0))
    assert parse_wkb(b"") == (None, None)


# ---------------------------------------------------------------------------- fixtures written with pyogrio


def _poly_wkb(rings_xy) -> bytes:
    body = b""
    for ring in rings_xy:
        pts = [*ring, ring[0]]
        body += struct.pack("<I", len(pts)) + b"".join(struct.pack("<dd", x, y) for x, y in pts)
    return struct.pack("<BII", 1, 3, len(rings_xy)) + body


def _write(path, geometries, fields: dict, gtype: str, crs: str, driver: str, layer: str | None = None) -> None:
    import pyogrio.raw

    names = list(fields)
    data = [np.asarray(v) for v in fields.values()]
    pyogrio.raw.write(str(path), np.array(geometries, dtype=object), data, names, driver=driver,
                      geometry_type=gtype, crs=crs, layer=layer)


@pytest.fixture
def gis():
    pytest.importorskip("pyogrio")
    pytest.importorskip("pyproj")
    from sparsehydro_viewer.core import gis

    return gis


@pytest.fixture
def stateplane_shp(tmp_path, gis):
    """Two sewersheds in Ohio State Plane South (US feet), as a shapefile."""
    from pyproj import Transformer

    t = Transformer.from_crs(4326, 3735, always_xy=True)
    rings = [SQUARE, SECOND]
    geoms = []
    for ring in rings:
        xs, ys = t.transform([p[0] for p in ring], [p[1] for p in ring])
        geoms.append(_poly_wkb([list(zip(xs, ys))]))
    path = tmp_path / "sheds.shp"
    _write(path, geoms, {"NAME": np.array(["Mill Creek", "Duck Creek"], dtype=object),
                         "SHED_ID": np.array([101, 102]), "IMPERV": np.array([0.31, 0.45]),
                         "OWNER": np.array(["MSD", "MSD"], dtype=object)},
           "Polygon", "EPSG:3735", "ESRI Shapefile")
    return path


def test_state_plane_shapefile_imports_as_zones(gis, stateplane_shp) -> None:
    from sparsehydro_viewer.core.store import ProjectStore

    layers = gis.list_layers(stateplane_shp)
    assert [(lay.name, lay.count) for lay in layers] == [("sheds", 2)]
    layer = gis.read_layer(stateplane_shp)
    assert layer.kind == "zone" and layer.fields == ["NAME", "SHED_ID", "IMPERV", "OWNER"]
    ring = parse_polygons(layer.features[0].wkt)[0][0]
    assert same_ring(ring, SQUARE)  # reprojected back to longitude/latitude within 1e-7 degrees
    plan = gis.ImportPlan.default(layer)
    assert (plan.label_field, plan.id_field) == ("NAME", "SHED_ID")
    assert {c.field: c.value_type for c in plan.columns} == {"IMPERV": "float", "OWNER": "str"}

    store = ProjectStore.memory()
    rep = gis.import_layer(store, layer, plan)
    assert len(rep.added) == 2 and not rep.refused
    zones = {z.label: z for z in store.nodes("zone")}
    mill = zones["Mill Creek"]
    assert mill.alt_ids == ["101"] and mill.extra["zone_kind"] == "SEWERSHED"
    assert mill.source_system == "GIS: sheds.shp/sheds"
    attrs = store.attributes(mill.iri)
    assert attrs["shv:imperv"] == pytest.approx(0.31) and attrs["shv:owner"] == "MSD"
    from pyproj import Geod

    a, _ = Geod(ellps="WGS84").polygon_area_perimeter([p[0] for p in SQUARE], [p[1] for p in SQUARE])
    assert attrs[gis.AREA_KEY] == pytest.approx(abs(a) / gis.SQM_PER_ACRE, rel=1e-6)


def test_duplicate_policies(gis, stateplane_shp) -> None:
    from sparsehydro_viewer.core.store import ProjectStore

    store = ProjectStore.memory()
    layer = gis.read_layer(stateplane_shp)
    plan = gis.ImportPlan.default(layer)
    gis.import_layer(store, layer, plan)
    again = gis.import_layer(store, layer, plan)  # skip (default): matched by SHED_ID
    assert again.skipped == 2 and not again.added and len(store.nodes("zone")) == 2
    layer.features[0].attributes["IMPERV"] = 0.5
    plan.on_duplicate = "update"
    upd = gis.import_layer(store, layer, plan)
    assert len(upd.updated) == 2 and len(store.nodes("zone")) == 2
    mill = next(z for z in store.nodes("zone") if z.label == "Mill Creek")
    assert store.attributes(mill.iri)["shv:imperv"] == pytest.approx(0.5)
    plan.on_duplicate = "add"
    assert len(gis.import_layer(store, layer, plan).added) == 2 and len(store.nodes("zone")) == 4


def test_geopackage_multipolygon_with_hole_and_geojson_sites_are_linked(gis, tmp_path) -> None:
    from sparsehydro_viewer.core.store import ProjectStore

    gpkg = tmp_path / "zones.gpkg"
    multi = struct.pack("<BII", 1, 6, 2) + _poly_wkb([SQUARE, HOLE]) + _poly_wkb([SECOND])
    _write(gpkg, [multi], {"name": np.array(["North"], dtype=object)}, "MultiPolygon", "EPSG:4326", "GPKG",
           layer="basins")
    pts = tmp_path / "meters.geojson"
    _write(pts, [struct.pack("<BIdd", 1, 1, -84.35, 39.25), struct.pack("<BIdd", 1, 1, -84.45, 39.15),
                 struct.pack("<BIdd", 1, 1, -84.15, 39.02)],
           {"site_id": np.array(["M1", "M2", "M3"], dtype=object), "depth_in": np.array([12, 18, 24])},
           "Point", "EPSG:4326", "GeoJSON")
    store = ProjectStore.memory()
    zone_layer = gis.read_layer(gpkg, "basins")
    rep = gis.import_layer(store, zone_layer, gis.ImportPlan.default(zone_layer))
    zone = store.node(rep.added[0])
    polys = parse_polygons(zone.geometry)
    assert len(polys) == 2 and len(polys[0]) == 2  # two parts, the first with its hole
    site_layer = gis.read_layer(pts)
    assert site_layer.kind == "site"
    plan = gis.ImportPlan.default(site_layer)
    assert plan.label_field == "site_id" and plan.columns[0].value_type == "int"
    rep = gis.import_layer(store, site_layer, plan)
    assert len(rep.added) == 3
    linked = {store.node(a).label for a, b, _ in store.edges(relation="BELONGS_TO_ZONE")}
    assert linked == {"M1", "M3"}  # M2 lies in the hole
    assert rep.links == 2 and gis.link_sites_to_zones(store) == 0  # not added twice
    assert parse_point(store.node(rep.added[0]).geometry) == pytest.approx((-84.35, 39.25))


def test_file_geodatabase_layers(gis, tmp_path) -> None:
    gdb = tmp_path / "network.gdb"
    _write(gdb, [_poly_wkb([SQUARE])], {"BASIN": np.array(["A"], dtype=object)}, "Polygon", "EPSG:4326",
           "OpenFileGDB", layer="Sewersheds")
    _write(gdb, [struct.pack("<BIdd", 1, 1, -84.4, 39.1)], {"ID": np.array(["S1"], dtype=object)}, "Point",
           "EPSG:4326", "OpenFileGDB", layer="Meters")
    names = sorted(lay.name for lay in gis.list_layers(gdb))
    assert names == ["Meters", "Sewersheds"]
    layer = gis.read_layer(gdb, "Sewersheds")
    assert layer.kind == "zone" and same_ring(parse_polygons(layer.features[0].wkt)[0][0], SQUARE, atol=1e-9)


def test_lines_are_refused(gis, tmp_path) -> None:
    from sparsehydro_viewer.core.store import ProjectStore

    path = tmp_path / "pipes.geojson"
    line = struct.pack("<BII", 1, 2, 2) + struct.pack("<dddd", -84.5, 39.1, -84.4, 39.2)
    _write(path, [line], {"id": np.array([1])}, "LineString", "EPSG:4326", "GeoJSON")
    layer = gis.read_layer(path)
    assert layer.kind == "unsupported"
    rep = gis.import_layer(ProjectStore.memory(), layer, gis.ImportPlan.default(layer))
    assert not rep.added and "only polygons" in rep.refused[0]


def test_export_round_trip(gis, stateplane_shp, tmp_path) -> None:
    from sparsehydro_viewer.core.store import ProjectStore

    store = ProjectStore.memory()
    layer = gis.read_layer(stateplane_shp)
    gis.import_layer(store, layer, gis.ImportPlan.default(layer))
    store.add_node("monitoring_site", "Meter", geometry="POINT (-84.4 39.1)")
    out = tmp_path / "export.gpkg"
    assert gis.export_nodes(store, out, "zone") == 2
    back = gis.read_layer(out)
    assert back.kind == "zone" and {"label", "iri", "imperv", "contributing_area"} <= set(back.fields)
    exported = {f.attributes["label"]: f.wkt for f in back.features}
    assert same_ring(parse_polygons(exported["Mill Creek"])[0][0], parse_polygons(layer.features[0].wkt)[0][0])
    assert gis.export_nodes(store, tmp_path / "sites.geojson", "monitoring_site") == 1
    with pytest.raises(ValueError, match="not supported"):
        gis.export_nodes(store, tmp_path / "x.kml", "zone")
