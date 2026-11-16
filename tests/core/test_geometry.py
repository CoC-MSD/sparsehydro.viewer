"""WKT parsing, Web Mercator projection and slippy-tile arithmetic."""

from __future__ import annotations

import math

import numpy as np
import pytest

from sparsehydro_viewer.core.geometry import (
    MAX_LAT,
    WORLD,
    from_mercator,
    geometry_points,
    ground_scale,
    parse_point,
    parse_polygon,
    point_wkt,
    polygon_wkt,
    tile_bounds,
    tile_range,
    tile_zoom,
    to_mercator,
)


def test_point_round_trip_and_variants() -> None:
    wkt = point_wkt(-84.5123456, 39.1)
    assert wkt == "POINT (-84.5123456 39.1000000)"
    assert parse_point(wkt) == (-84.5123456, 39.1)
    assert parse_point("point z (1 2 3)") == (1.0, 2.0)
    assert parse_point("POINT(1e1 -2.5)") == (10.0, -2.5)
    for bad in (None, "", "LINESTRING (0 0, 1 1)", "POINT ()"):
        assert parse_point(bad) is None
    with pytest.raises(ValueError):
        point_wkt(200, 0)
    with pytest.raises(ValueError):
        point_wkt(0, math.nan)


def test_polygon_round_trip() -> None:
    ring = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    wkt = polygon_wkt(ring)
    assert wkt.startswith("POLYGON ((") and wkt.count(",") == 3  # closed ring
    assert parse_polygon(wkt) == ring
    assert parse_polygon("POLYGON ((0 0, 1 1, 0 0))") is None  # degenerate
    assert parse_polygon("POINT (0 0)") is None
    assert geometry_points(wkt) == ring
    assert geometry_points("POINT (3 4)") == [(3.0, 4.0)]
    assert geometry_points(None) == []
    with pytest.raises(ValueError):
        polygon_wkt([(0, 0), (1, 1)])


def test_mercator_round_trip_scalars_and_arrays() -> None:
    assert to_mercator(0, 0) == pytest.approx((0.0, 0.0), abs=1e-6)
    x, _ = to_mercator(180, 0)
    assert x == pytest.approx(WORLD / 2)
    lon, lat = from_mercator(*to_mercator(-84.5, 39.1))
    assert lon == pytest.approx(-84.5) and lat == pytest.approx(39.1)
    xs, ys = to_mercator(np.array([-84.5, 10.0]), np.array([39.1, -20.0]))
    lons, lats = from_mercator(xs, ys)
    np.testing.assert_allclose(lons, [-84.5, 10.0])
    np.testing.assert_allclose(lats, [39.1, -20.0])
    _, y = to_mercator(0, 89.9)  # clipped to the projection's limit
    assert from_mercator(0, y)[1] == pytest.approx(MAX_LAT)
    assert ground_scale(0.0) == pytest.approx(1.0)
    assert ground_scale(to_mercator(0, 60)[1]) == pytest.approx(0.5)


def test_tiles() -> None:
    assert tile_zoom(WORLD / 256) == 0
    assert tile_zoom(WORLD / 256 / 2**10) == 10
    assert tile_zoom(1e-9) == 19 and tile_zoom(0) == 0
    cols, rows = tile_range(-WORLD / 2, -WORLD / 2, WORLD / 2, WORLD / 2, 2)
    assert list(cols) == [0, 1, 2, 3] and list(rows) == [0, 1, 2, 3]
    left, bottom, w, h = tile_bounds(0, 0, 1)
    assert (left, bottom + h) == (-WORLD / 2, WORLD / 2) and w == h == WORLD / 2
    x, y = to_mercator(-84.5, 39.1)  # the tile containing a point contains it
    cols, rows = tile_range(x, y, x, y, 12)
    left, bottom, w, h = tile_bounds(cols[0], rows[0], 12)
    assert left <= x <= left + w and bottom <= y <= bottom + h
