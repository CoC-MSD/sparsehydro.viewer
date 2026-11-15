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


def geometry_points(wkt: str | None) -> list[tuple[float, float]]:
    """All vertices (points or polygon ring) of a geometry, for extents."""
    p = parse_point(wkt)
    if p is not None:
        return [p]
    return parse_polygon(wkt) or []


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
    "MAX_LAT", "R", "WORLD", "from_mercator", "geometry_points", "ground_scale", "parse_point", "parse_polygon",
    "point_wkt", "polygon_wkt", "tile_bounds", "tile_range", "tile_zoom", "to_mercator",
]
