"""geo_math / overlay_safe_wgs84_bounds."""

from __future__ import annotations

from app.services.geo_math import (
    grid_size_from_span,
    normalize_lng_lat_bbox,
    overlay_safe_wgs84_bounds,
    pixel_center_axis,
    wrap_longitude,
)


def test_wrap_longitude_edges():
    assert wrap_longitude(180.0) == 180.0
    assert wrap_longitude(-180.0) == -180.0
    assert abs(wrap_longitude(190.0) - (-170.0)) < 1e-12


def test_normalize_dateline_unwrap():
    w, s, e, n = normalize_lng_lat_bbox(170.0, -10.0, -170.0, 10.0)
    assert w < e
    assert e > 180.0


def test_overlay_safe_global():
    w, s, e, n = overlay_safe_wgs84_bounds(-180.0, -85.0, 180.0, 85.0)
    assert (w, e) == (-180.0, 180.0)


def test_overlay_safe_pacific_strip():
    w, s, e, n = overlay_safe_wgs84_bounds(170.0, -10.0, -170.0, 10.0)
    assert w < e
    assert e == 190.0


def test_grid_size_rounds_not_truncates():
    # 0.9/0.4 = 2.25 → round → 2；int 截断也是 2
    assert grid_size_from_span(0.9, 0.4) == 2
    # 1.1/0.4 = 2.75 → round → 3；int 截断会得到 2（旧 bug）
    assert grid_size_from_span(1.1, 0.4) == 3
    assert grid_size_from_span(0.1, 0.4) == 1


def test_pixel_center_axis_matches_from_bounds_centers():
    # west=-180, east=180, width=4 → centers at -135,-45,45,135
    centers = pixel_center_axis(-180.0, 180.0, 4)
    assert centers[0] == -135.0
    assert centers[-1] == 135.0


def test_lng_span_from_list_dateline():
    from app.services.geo_math import lng_span_from_list

    span = lng_span_from_list([170.0, -170.0, 175.0])
    assert span is not None
    assert span[0] < span[1]
    assert span[1] > 180.0
