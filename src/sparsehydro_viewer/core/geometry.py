"""Minimal geometry for node locations.

Locations are WKT in EPSG:4326 (longitude, latitude), the water-ontology
convention.  The map draws in Web Mercator (EPSG:3857) metres so that standard
slippy-map tiles line up; this module converts between the two and computes
tile coordinates.  No GIS dependency is needed for points and simple polygons.
"""

from __future__ import annotations

import math
import re

import numpy as np

R = 6378137.0  # Web Mercator sphere radius [m]
MAX_LAT = 85.05112878  # latitude limit of Web Mercator
WORLD = 2 * math.pi * R  # width of the world in Web Mercator metres

_NUM = r"[-+0-9.eE]+"
_POINT = re.compile(rf"^\s*POINT\s*Z?\s*\(\s*({_NUM})\s+({_NUM})(?:\s+{_NUM})?\s*\)\s*$", re.I)
_POLYGON = re.compile(r"^\s*POLYGON\s*Z?\s*\(\s*\((.*?)\)", re.I | re.S)


# ---------------------------------------------------------------------------
# WKT
# ---------------------------------------------------------------------------


def parse_point(wkt: str | None) -> tuple[float, float] | None:
    """``(lon, lat)`` of a WKT ``POINT``; ``None`` for anything else."""
    if not wkt:
        return None
    m = _POINT.match(wkt)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def point_wkt(lon: float, lat: float) -> str:
    """WKT ``POINT (lon lat)`` with 7 decimals (about 1 cm)."""
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0) or math.isnan(lon) or math.isnan(lat):
        raise ValueError(f"({lon}, {lat}) is not a longitude/latitude pair")
    return f"POINT ({lon:.7f} {lat:.7f})"


def parse_polygon(wkt: str | None) -> list[tuple[float, float]] | None:
    """Outer ring of a WKT ``POLYGON`` as ``[(lon, lat), ...]`` (closing vertex dropped)."""
    if not wkt:
        return None
    m = _POLYGON.match(wkt)
    if not m:
        return None
    ring = []
    for pair in m.group(1).split(","):
        parts = pair.split()
        if len(parts) < 2:
            return None
        ring.append((float(parts[0]), float(parts[1])))
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    return ring if len(ring) >= 3 else None


def polygon_wkt(ring: list[tuple[float, float]]) -> str:
    """WKT ``POLYGON`` from at least three ``(lon, lat)`` vertices (the ring is closed here)."""
    if len(ring) < 3:
        raise ValueError("a polygon needs at least three vertices")
    pts = list(ring) + [ring[0]]
    return "POLYGON ((" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in pts) + "))"


#: A polygon is a list of rings (the outer ring first, then holes); a ring is a list of ``(lon, lat)`` with the
#: closing vertex dropped. Areal geometries are lists of polygons (one for a POLYGON).
Ring = list[tuple[float, float]]
Polygons = list[list[Ring]]

_TYPE = re.compile(r"^\s*([A-Za-z]+)\s*(?:ZM|Z|M)?\s*(\(.*\)|EMPTY)\s*$", re.S)


def _nested(text: str) -> list:
    """Parse WKT parentheses into nested lists; innermost lists hold ``(x, y)`` tuples."""
    stack: list[list] = [[]]
    token = ""
    for ch in text:
        if ch == "(":
            stack.append([])
        elif ch in "),":
            if token.strip():
                nums = token.split()
                stack[-1].append((float(nums[0]), float(nums[1])))
            token = ""
            if ch == ")":
                done = stack.pop()
                stack[-1].append(done)
        else:
            token += ch
    return stack[0][0] if stack[0] else []


def parse_polygons(wkt: str | None) -> Polygons:
    """Polygons (with holes) of a WKT ``POLYGON`` or ``MULTIPOLYGON``; ``[]`` for anything else."""
    if not wkt:
        return []
    m = _TYPE.match(wkt)
    if not m or m.group(2).upper() == "EMPTY":
        return []
    kind = m.group(1).upper()
    try:
        tree = _nested(m.group(2))
    except (ValueError, IndexError):
        return []
    if kind == "POLYGON":
        tree = [tree]
    elif kind != "MULTIPOLYGON":
        return []
    out: Polygons = []
    for poly in tree:
        rings = []
        for ring in poly:
            ring = list(ring)
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring.pop()
            if len(ring) >= 3:
                rings.append(ring)
        if rings:
            out.append(rings)
    return out


def polygons_wkt(polygons: Polygons) -> str:
    """WKT ``POLYGON`` (one polygon) or ``MULTIPOLYGON``; rings are closed here."""
    if not polygons:
        raise ValueError("no polygon")

    def ring(r: Ring) -> str:
        if len(r) < 3:
            raise ValueError("a ring needs at least three vertices")
        return "(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in [*r, r[0]]) + ")"

    def poly(p: list[Ring]) -> str:
        return "(" + ", ".join(ring(r) for r in p) + ")"

    if len(polygons) == 1:
        return "POLYGON " + poly(polygons[0])
    return "MULTIPOLYGON (" + ", ".join(poly(p) for p in polygons) + ")"


def _in_ring(x: float, y: float, ring: Ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def point_in_polygons(lon: float, lat: float, polygons: Polygons) -> bool:
    """Whether ``(lon, lat)`` is inside any polygon and outside its holes (ray casting)."""
    for rings in polygons:
        if _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, h) for h in rings[1:]):
            return True
    return False


def spherical_area_m2(polygons: Polygons) -> float:
    """Area on the sphere (mean Earth radius), holes subtracted; within about 0.5 % of the ellipsoidal area.
    Used when pyproj is not installed (see :func:`sparsehydro_viewer.core.gis.area_acres`)."""
    r = 6371008.8

    def ring_area(ring: Ring) -> float:
        total = 0.0
        n = len(ring)
        for i in range(n):
            lon1, lat1 = map(math.radians, ring[i])
            lon2, lat2 = map(math.radians, ring[(i + 1) % n])
            total += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
        return abs(total) * r * r / 2

    return sum(ring_area(p[0]) - sum(ring_area(h) for h in p[1:]) for p in polygons)


def geometry_points(wkt: str | None) -> list[tuple[float, float]]:
    """All vertices (a point, or every polygon ring) of a geometry, for extents."""
    p = parse_point(wkt)
    if p is not None:
        return [p]
    return [pt for poly in parse_polygons(wkt) for ring in poly for pt in ring]


# ---------------------------------------------------------------------------
# Web Mercator
# ---------------------------------------------------------------------------


def to_mercator(lon, lat):
    """Longitude/latitude (degrees) to Web Mercator metres (works on scalars and arrays)."""
    lon = np.asarray(lon, dtype=float)
    lat = np.clip(np.asarray(lat, dtype=float), -MAX_LAT, MAX_LAT)
    x = R * np.radians(lon)
    y = R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    return (float(x), float(y)) if x.ndim == 0 else (x, y)


def from_mercator(x, y):
    """Web Mercator metres to longitude/latitude (degrees)."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lon = np.degrees(x / R)
    lat = np.degrees(2 * np.arctan(np.exp(y / R)) - np.pi / 2)
    return (float(lon), float(lat)) if lon.ndim == 0 else (lon, lat)


def ground_scale(y_mercator: float) -> float:
    """Metres on the ground per Web Mercator metre at northing *y* (``cos(latitude)``)."""
    _, lat = from_mercator(0.0, y_mercator)
    return math.cos(math.radians(lat))


# ---------------------------------------------------------------------------
# slippy-map tiles (z/x/y, 256 px, origin top-left)
# ---------------------------------------------------------------------------


def tile_zoom(metres_per_pixel: float, max_zoom: int = 19) -> int:
    """Tile zoom level whose resolution best matches *metres_per_pixel* (Mercator metres)."""
    if metres_per_pixel <= 0 or not math.isfinite(metres_per_pixel):
        return 0
    z = math.log2(WORLD / (256.0 * metres_per_pixel))
    return int(min(max_zoom, max(0, round(z))))


def tile_range(x0: float, y0: float, x1: float, y1: float, z: int) -> tuple[range, range]:
    """Tile columns and rows covering the Mercator box ``[x0, x1] x [y0, y1]`` at zoom *z*."""
    n = 2 ** z

    def col(x: float) -> int:
        return int(min(n - 1, max(0, math.floor((x / WORLD + 0.5) * n))))

    def row(y: float) -> int:
        return int(min(n - 1, max(0, math.floor((0.5 - y / WORLD) * n))))

    return range(col(min(x0, x1)), col(max(x0, x1)) + 1), range(row(max(y0, y1)), row(min(y0, y1)) + 1)


def tile_bounds(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    """Mercator ``(left, bottom, width, height)`` of tile ``z/x/y``."""
    n = 2 ** z
    size = WORLD / n
    left = (x / n - 0.5) * WORLD
    top = (0.5 - y / n) * WORLD
    return left, top - size, size, size


__all__ = [
    "MAX_LAT", "R", "WORLD", "Polygons", "Ring", "from_mercator", "geometry_points", "ground_scale", "parse_point",
    "parse_polygon", "parse_polygons", "point_in_polygons", "point_wkt", "polygon_wkt", "polygons_wkt",
    "spherical_area_m2", "tile_bounds", "tile_range", "tile_zoom", "to_mercator",
]
