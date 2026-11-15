"""Minimal WKT handling for node locations (EPSG:4326 longitude/latitude, the ontology convention)."""

from __future__ import annotations

import math
import re

_POINT = re.compile(r"^\s*POINT\s*Z?\s*\(\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)(?:\s+[-+0-9.eE]+)?\s*\)\s*$", re.I)


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


__all__ = ["parse_point", "point_wkt"]
