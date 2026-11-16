"""GIS import and export of sites and zones (sewersheds) - optional ``gis`` extra.

Reads any vector format GDAL reads - file geodatabases (``.gdb``, choose the
layer), shapefiles, GeoPackage, GeoJSON, KML/KMZ - through ``pyogrio`` and
reprojects to EPSG:4326 with ``pyproj``. Geometries travel as WKB, decoded
here, so neither shapely nor geopandas is needed.

* Polygons and multipolygons become ``zone`` rows (holes kept), points
  become ``monitoring_site`` rows; lines are refused (no edge geometry yet).
* Columns become attributes (``attribute_measurement``) under ``shv:`` keys
  with inferred types; an id column goes to ``alt_ids``.
* Features whose id (or, without an id column, label) already exists are
  skipped, updated or added again, as chosen.
* Optionally each site inside a zone gets a ``BELONGS_TO_ZONE`` edge, and a
  zone's area (on the WGS84 ellipsoid) is stored as an attribute.

The base installation stays GIS-free: :func:`available` tells the UI
whether to offer the import, and :data:`MISSING` says how to enable it.
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .geometry import Polygons, parse_point, parse_polygons, point_in_polygons, point_wkt, polygons_wkt
from .store import AttributeDefinition, ProjectStore

MISSING = ("GIS import needs the optional GIS packages: pip install \"sparsehydro-viewer[gis]\" (pyogrio and "
           "pyproj). The Windows installer includes them.")
#: File types offered in the open dialog (a file geodatabase is a folder, chosen separately).
FILE_FILTER = ("GIS layers (*.shp *.gpkg *.geojson *.json *.kml *.kmz *.fgb *.gml *.sqlite);;"
               "All files (*)")
ZONE_KINDS = ("SEWERSHED", "DRAINAGE_AREA", "SERVICE_AREA", "CATCHMENT", "OTHER")
AREA_KEY = "shv:contributing_area"
SQM_PER_ACRE = 4046.8564224
Progress = Callable[[int, int, str], None]


def available() -> bool:
    """Whether the optional GIS packages are installed."""
    import importlib.util

    return all(importlib.util.find_spec(m) is not None for m in ("pyogrio", "pyproj"))


# ---------------------------------------------------------------------------- WKB


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data, self.pos = data, 0

    def take(self, fmt: str) -> tuple:
        size = struct.calcsize(fmt)
        out = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return out


def _read_geometry(r: _Reader) -> tuple[str, Any]:
    """``(kind, coords)``: point ``(x, y)``, polygons ``[[ring, ...], ...]``, line ``[[(x, y)...], ...]``."""
    (order,) = r.take("B")
    e = "<" if order == 1 else ">"
    (code,) = r.take(e + "I")
    iso = code & 0x1FFFFFFF
    if code & 0xE0000000:  # EWKB (PostGIS): Z, M and SRID as flag bits on a 2D type code
        has_z, has_m = bool(code & 0x80000000), bool(code & 0x40000000)
    else:  # ISO: 1000 = Z, 2000 = M, 3000 = ZM
        has_z, has_m = iso // 1000 in (1, 3), iso // 1000 in (2, 3)
    base = iso % 1000
    dims = 2 + has_z + has_m
    if code & 0x20000000:  # EWKB SRID
        r.take(e + "I")

    def point() -> tuple[float, float]:
        vals = r.take(e + "d" * dims)
        return float(vals[0]), float(vals[1])

    def ring() -> list[tuple[float, float]]:
        (n,) = r.take(e + "I")
        return [point() for _ in range(n)]

    if base == 1:
        return "point", point()
    if base == 2:
        return "line", [ring()]
    if base == 3:
        (n,) = r.take(e + "I")
        return "polygon", [[ring() for _ in range(n)]]
    if base in (4, 5, 6, 7):
        (n,) = r.take(e + "I")
        parts = [_read_geometry(r) for _ in range(n)]
        kinds = {k for k, _ in parts}
        if base == 4 or kinds == {"point"}:
            return "points", [c for _, c in parts]
        if kinds <= {"polygon"}:
            return "polygon", [poly for _, c in parts for poly in c]
        if kinds <= {"line"}:
            return "line", [ln for _, c in parts for ln in c]
        return "mixed", parts
    raise ValueError(f"unsupported WKB geometry type {code}")


def parse_wkb(data: bytes | None) -> tuple[str | None, Any]:
    """Decode WKB (ISO or EWKB, 2D/Z/M) to ``(kind, coordinates)``; ``(None, None)`` when empty."""
    if data is None or len(data) == 0:
        return None, None
    return _read_geometry(_Reader(bytes(data)))


def _ring_wkb(ring) -> bytes:
    pts = [*ring, ring[0]]
    return struct.pack("<I", len(pts)) + b"".join(struct.pack("<dd", x, y) for x, y in pts)


def to_wkb(wkt: str) -> bytes:
    """WKB (little endian, 2D) of a WKT point, polygon or multipolygon, for export."""
    p = parse_point(wkt)
    if p is not None:
        return struct.pack("<BIdd", 1, 1, *p)
    polygons = parse_polygons(wkt)
    if not polygons:
        raise ValueError(f"cannot export geometry {wkt[:40]!r}")

    def poly(rings) -> bytes:
        return struct.pack("<BII", 1, 3, len(rings)) + b"".join(_ring_wkb(r) for r in rings)

    return struct.pack("<BII", 1, 6, len(polygons)) + b"".join(poly(p) for p in polygons)


# ---------------------------------------------------------------------------- reading


@dataclass
class LayerInfo:
    name: str
    geometry_type: str
    count: int
    crs: str | None


@dataclass
class GisFeature:
    """One feature, reprojected to longitude/latitude."""

    kind: str | None  # "point" | "polygon" | "line" | "points" | "mixed" | None (no geometry)
    wkt: str | None  # EPSG:4326 WKT for points and polygons
    attributes: dict[str, Any]


@dataclass
class GisLayer:
    path: str
    name: str
    crs: str | None
    fields: list[str]
    features: list[GisFeature]
    warnings: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        """``zone`` (polygons), ``site`` (points), or ``unsupported``."""
        kinds = {f.kind for f in self.features if f.kind}
        if kinds and kinds <= {"polygon"}:
            return "zone"
        if kinds and kinds <= {"point"}:
            return "site"
        return "unsupported"

    def field_values(self, name: str) -> list[Any]:
        return [f.attributes.get(name) for f in self.features]


def list_layers(path: str | Path) -> list[LayerInfo]:
    """Layers of a file or file geodatabase with their geometry type, feature count and CRS."""
    import pyogrio

    out = []
    for name, gtype in pyogrio.list_layers(str(path)):
        info = pyogrio.read_info(str(path), layer=name)
        out.append(LayerInfo(str(name), str(gtype or "None"), int(info.get("features", -1)), info.get("crs")))
    return out


def _transformer(crs: str | None, sample: list[tuple[float, float]]):
    """Callable reprojecting x/y arrays to lon/lat, or ``None`` when already geographic."""
    if not crs:
        if all(-180 <= x <= 180 and -90 <= y <= 90 for x, y in sample[:200]):
            return None  # no CRS, but coordinates look like longitude/latitude
        raise ValueError("the layer has no coordinate reference system (a .prj file is missing?) and its "
                         "coordinates are not longitude/latitude")
    from pyproj import CRS, Transformer

    src = CRS.from_user_input(crs)
    if src.equals(CRS.from_epsg(4326), ignore_axis_order=True):
        return None
    t = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
    return lambda xs, ys: t.transform(xs, ys)


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float | np.floating) and not math.isfinite(float(value)):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def read_layer(path: str | Path, layer: str | None = None, *, progress: Progress | None = None,
               should_stop: Callable[[], bool] = lambda: False) -> GisLayer:
    """Read *layer* (the first one when ``None``), reprojected to EPSG:4326."""
    import pyogrio.raw

    report = progress or (lambda i, n, t: None)
    report(0, 0, "reading")
    meta, _fids, geometry, field_data = pyogrio.raw.read(str(path), layer=layer)
    fields = [str(f) for f in meta["fields"]]
    crs = meta.get("crs")
    decoded = [parse_wkb(g) for g in geometry]
    sample = [c for k, c in decoded if k == "point"] + \
             [pt for k, c in decoded if k == "polygon" for poly in c[:1] for pt in poly[0][:5]]
    reproject = _transformer(crs, sample)
    n = len(decoded)
    features, warnings = [], []
    for i, (kind, coords) in enumerate(decoded):
        if i % 200 == 0:
            if should_stop():
                raise InterruptedError("cancelled")
            report(i, n, f"feature {i} of {n}")
        attrs = {name: _clean(field_data[j][i]) for j, name in enumerate(fields)}
        wkt = None
        try:
            if kind == "point":
                x, y = coords
                if reproject is not None:
                    x, y = reproject(x, y)
                wkt = point_wkt(float(x), float(y))
            elif kind == "polygon":
                polys: Polygons = []
                for rings in coords:
                    out_rings = []
                    for ring in rings:
                        xs = np.array([p[0] for p in ring])
                        ys = np.array([p[1] for p in ring])
                        if reproject is not None:
                            xs, ys = reproject(xs, ys)
                        pts = list(zip(map(float, xs), map(float, ys)))
                        if len(pts) > 1 and pts[0] == pts[-1]:
                            pts.pop()
                        if len(pts) >= 3:
                            out_rings.append(pts)
                    if out_rings:
                        polys.append(out_rings)
                wkt = polygons_wkt(polys) if polys else None
        except ValueError as exc:
            warnings.append(f"feature {i + 1}: {exc}")
        features.append(GisFeature(kind, wkt, attrs))
    report(n, n, "read")
    name = layer or Path(path).stem
    return GisLayer(str(path), str(name), str(crs) if crs else None, fields, features, warnings)


# ---------------------------------------------------------------------------- import


def infer_type(values: list[Any]) -> str:
    """Attribute type of a column: ``bool``, ``int``, ``float`` or ``str`` (empty values ignored)."""
    vals = [v for v in values if v is not None and v != ""]
    if not vals:
        return "str"
    if all(isinstance(v, bool | np.bool_) for v in vals):
        return "bool"
    if all(isinstance(v, int | np.integer) and not isinstance(v, bool) for v in vals):
        return "int"
    if all(isinstance(v, int | float | np.integer | np.floating) and not isinstance(v, bool) for v in vals):
        return "float"
    return "str"


def attribute_key(field_name: str) -> str:
    return "shv:" + (re.sub(r"[^A-Za-z0-9]+", "_", field_name).strip("_").lower() or "field")


@dataclass
class ColumnPlan:
    """How one column is imported as an attribute."""

    field: str
    key: str
    label: str
    value_type: str
    unit: str = ""


@dataclass
class ImportPlan:
    """What :func:`import_layer` does with a layer.

    :ivar label_field: Column naming each feature (``""``: ``"<layer> <n>"``).
    :ivar id_field: Column with the feature's identifier (kept in ``alt_ids``, matched against existing nodes).
    :ivar zone_kind: Fixed ``zone_kind`` of imported zones, or the name of a column holding it.
    :ivar columns: Columns imported as attributes.
    :ivar on_duplicate: ``skip``, ``update`` (geometry and attributes) or ``add`` (import again).
    :ivar link_sites: Add ``BELONGS_TO_ZONE`` edges from every site to the zones that contain it.
    :ivar store_area: Write each zone's area [acres] to :data:`AREA_KEY`.
    """

    label_field: str = ""
    id_field: str = ""
    zone_kind: str = "SEWERSHED"
    columns: list[ColumnPlan] = field(default_factory=list)
    on_duplicate: str = "skip"
    link_sites: bool = True
    store_area: bool = True

    @classmethod
    def default(cls, layer: GisLayer) -> ImportPlan:
        """Sensible defaults: a name-like label column, an id-like column, every other column as an attribute."""
        lower = {f.lower(): f for f in layer.fields}
        label = next((lower[k] for k in ("name", "label", "site_name", "basin", "sewershed", "shed_name")
                      if k in lower), layer.fields[0] if layer.fields else "")
        def unique(name: str) -> bool:
            vals = [v for v in layer.field_values(name) if v is not None and v != ""]
            return len(vals) == len(layer.features) and len(set(map(str, vals))) == len(vals)

        named = [lower[k] for k in ("id", "site_id", "basin_id", "facilityid") if k in lower]
        suffixed = [f for f in layer.fields if f.lower().endswith("id") and f.lower() not in ("objectid", "fid")]
        ident = next((f for f in [*named, *suffixed] if f != label and unique(f)), "")
        cols = [ColumnPlan(f, attribute_key(f), f, infer_type(layer.field_values(f)))
                for f in layer.fields if f not in (label, ident) and f.lower() not in ("shape_length", "shape_area")]
        return cls(label_field=label, id_field=ident, columns=cols)


@dataclass
class ImportReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: int = 0
    refused: list[str] = field(default_factory=list)
    links: int = 0

    def summary(self) -> str:
        parts = [f"{len(self.added)} added"]
        if self.updated:
            parts.append(f"{len(self.updated)} updated")
        if self.skipped:
            parts.append(f"{self.skipped} already present (skipped)")
        if self.refused:
            parts.append(f"{len(self.refused)} not imported")
        if self.links:
            parts.append(f"{self.links} site-zone links")
        return ", ".join(parts)


def area_acres(wkt: str) -> float:
    """Area of a (multi)polygon on the WGS84 ellipsoid (pyproj), or on the sphere without pyproj."""
    polygons = parse_polygons(wkt)
    try:
        from pyproj import Geod
    except ImportError:
        from .geometry import spherical_area_m2

        return spherical_area_m2(polygons) / SQM_PER_ACRE
    geod = Geod(ellps="WGS84")
    total = 0.0
    for rings in polygons:
        for k, ring in enumerate(rings):
            a, _ = geod.polygon_area_perimeter([p[0] for p in ring], [p[1] for p in ring])
            total += abs(a) if k == 0 else -abs(a)
    return total / SQM_PER_ACRE


def _existing(store: ProjectStore, table: str) -> dict[str, str]:
    """Identifier -> iri of a table's nodes (alt ids and labels)."""
    out: dict[str, str] = {}
    for n in store.nodes(table):
        out.setdefault(f"label:{n.label}", n.iri)
        for a in n.alt_ids:
            out.setdefault(f"id:{a}", n.iri)
    return out


def import_layer(store: ProjectStore, layer: GisLayer, plan: ImportPlan, *, progress: Progress | None = None,
                 should_stop: Callable[[], bool] = lambda: False) -> ImportReport:
    """Write *layer*'s features into *store* as zones or sites according to *plan*."""
    report_progress = progress or (lambda i, n, t: None)
    kind = layer.kind
    rep = ImportReport()
    if kind == "unsupported":
        kinds = sorted({f.kind or "none" for f in layer.features})
        rep.refused.append(f"{layer.name}: geometry {', '.join(kinds)} - only polygons (zones) and points (sites) "
                           "can be imported")
        return rep
    table = "zone" if kind == "zone" else "monitoring_site"
    for c in plan.columns:
        store.define_attribute(AttributeDefinition(c.key, c.label, c.value_type, c.unit, category="Imported",
                                                   description=f"Column {c.field} of {layer.name}",
                                                   applies_to=(table,)))
    if table == "zone" and plan.store_area:
        store.define_attribute(AttributeDefinition(AREA_KEY, "Contributing area", "float", "ac", category="Area",
                                                   minimum=0.0, decimals=2,
                                                   description="Area of the zone polygon on the WGS84 ellipsoid",
                                                   applies_to=("zone",)))
    existing = _existing(store, table)
    source = f"GIS: {Path(layer.path).name}/{layer.name}"
    zone_kind_field = plan.zone_kind if plan.zone_kind in layer.fields else ""
    n = len(layer.features)
    for i, f in enumerate(layer.features):
        if i % 50 == 0:
            if should_stop():
                raise InterruptedError("cancelled")
            report_progress(i, n, f"importing {i} of {n}")
        if f.wkt is None or f.kind not in ("point", "polygon"):
            rep.refused.append(f"feature {i + 1}: {'no geometry' if f.kind is None else f.kind}")
            continue
        label = str(f.attributes.get(plan.label_field) or "").strip() if plan.label_field else ""
        label = label or f"{layer.name} {i + 1}"
        ident = f.attributes.get(plan.id_field) if plan.id_field else None
        ident = None if ident is None or ident == "" else str(ident)
        key = f"id:{ident}" if ident is not None else f"label:{label}"
        iri = existing.get(key)
        if iri is not None and plan.on_duplicate == "skip":
            rep.skipped += 1
            continue
        extra: dict[str, Any] = {}
        if table == "zone":
            extra["zone_kind"] = str(f.attributes.get(zone_kind_field) or "OTHER") if zone_kind_field \
                else plan.zone_kind
        if iri is not None and plan.on_duplicate == "update":
            store.update_node(iri, geometry=f.wkt, **extra)
            rep.updated.append(iri)
        else:
            iri = store.add_node(table, label, geometry=f.wkt, alt_ids=[ident] if ident else [],
                                 source_system=source, **extra)
            existing[key] = iri
            rep.added.append(iri)
        for c in plan.columns:
            value = f.attributes.get(c.field)
            if value is None or value == "":
                continue
            try:
                store.set_attribute(iri, c.key, value, source="GIS")
            except (TypeError, ValueError):
                pass  # e.g. text in a numeric column: leave the attribute empty
        if table == "zone" and plan.store_area:
            store.set_attribute(iri, AREA_KEY, round(area_acres(f.wkt), 4), source="GIS")
    if plan.link_sites:
        rep.links = link_sites_to_zones(store)
    report_progress(n, n, "imported")
    return rep


def link_sites_to_zones(store: ProjectStore) -> int:
    """Add a ``BELONGS_TO_ZONE`` edge from every located site to each zone containing it; returns the count added."""
    zones = [(z.iri, parse_polygons(z.geometry)) for z in store.nodes("zone")]
    zones = [(iri, p) for iri, p in zones if p]
    have = {(a, b) for a, b, _ in store.edges(relation="BELONGS_TO_ZONE")}
    added = 0
    for site in store.nodes("monitoring_site"):
        pt = parse_point(site.geometry)
        if pt is None:
            continue
        for iri, polys in zones:
            if (site.iri, iri) not in have and point_in_polygons(pt[0], pt[1], polys):
                store.add_edge(site.iri, iri, "BELONGS_TO_ZONE")
                added += 1
    return added


# ---------------------------------------------------------------------------- export


EXPORT_DRIVERS = {".gpkg": "GPKG", ".geojson": "GeoJSON", ".json": "GeoJSON", ".shp": "ESRI Shapefile"}


def export_nodes(store: ProjectStore, path: str | Path, table: str, *, iris: list[str] | None = None) -> int:
    """Write the located zones (``table="zone"``) or sites (``"monitoring_site"``) to a GeoPackage, GeoJSON or
    shapefile in EPSG:4326, with their label, iri, alt ids and attributes; returns the number written."""
    import pyogrio.raw

    path = Path(path)
    driver = EXPORT_DRIVERS.get(path.suffix.lower())
    if driver is None:
        raise ValueError(f"export to {path.suffix or 'this file type'} is not supported; use "
                         f"{', '.join(sorted(EXPORT_DRIVERS))}")
    nodes = [n for n in store.nodes(table) if n.geometry and (iris is None or n.iri in iris)]
    nodes = [n for n in nodes if (parse_point(n.geometry) if table == "monitoring_site" else parse_polygons(n.geometry))]
    if not nodes:
        return 0
    attrs = [store.attributes(n.iri) for n in nodes]
    keys = sorted({k for a in attrs for k in a})
    names = ["label", "iri", "alt_ids", *[k.replace("shv:", "").replace(":", "_") for k in keys]]
    if driver == "ESRI Shapefile":
        names = [nm[:10] for nm in names]  # dBase field names
    columns = [np.array([n.label for n in nodes], dtype=object), np.array([n.iri for n in nodes], dtype=object),
               np.array([";".join(n.alt_ids) for n in nodes], dtype=object)]
    for k in keys:
        vals = [a.get(k) for a in attrs]
        numeric = all(v is None or isinstance(v, int | float) and not isinstance(v, bool) for v in vals)
        columns.append(np.array([np.nan if v is None else float(v) for v in vals]) if numeric
                       else np.array(["" if v is None else str(v) for v in vals], dtype=object))
    geometry = np.array([to_wkb(n.geometry) for n in nodes], dtype=object)
    gtype = "Point" if table == "monitoring_site" else "MultiPolygon"
    if path.exists():
        path.unlink()
    pyogrio.raw.write(str(path), geometry, columns, names, layer="sites" if table == "monitoring_site" else "zones",
                      driver=driver, geometry_type=gtype, crs="EPSG:4326")
    return len(nodes)


__all__ = ["AREA_KEY", "FILE_FILTER", "MISSING", "ZONE_KINDS", "ColumnPlan", "GisFeature", "GisLayer", "ImportPlan",
           "ImportReport", "LayerInfo", "area_acres", "attribute_key", "available", "export_nodes", "import_layer",
           "infer_type", "link_sites_to_zones", "list_layers", "parse_wkb", "read_layer", "to_wkb"]
