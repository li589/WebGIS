"""grid_presets / invalid value helpers."""

from __future__ import annotations

import numpy as np

from app.data_io.services.grid_presets import (
    resolve_geo_reference,
    suggest_grid_preset,
)
from app.data_io.services.raster_science import apply_invalid_values


def test_suggest_ease2_9km_shape():
    assert suggest_grid_preset([1624, 3856]) == "ease2-global-9km"
    assert suggest_grid_preset([1, 1624, 3856]) == "ease2-global-9km"
    assert suggest_grid_preset([100, 200]) is None


def test_resolve_ease2_transform_symmetric():
    transform, crs, bounds = resolve_geo_reference(
        height=1624,
        width=3856,
        grid_preset="ease2-global-9km",
    )
    assert crs == "EPSG:6933"
    assert bounds[0] == -bounds[2]
    assert bounds[1] == -bounds[3]
    assert bounds[0] < bounds[2]
    assert transform is not None


def test_ease2_bounds_to_wgs84_not_collapsed():
    from app.services.crs import crs_transformer
    from app.data_io.services.grid_presets import GRID_PRESETS

    b = GRID_PRESETS["ease2-global-9km"]["bounds"]
    w, s, e, n = crs_transformer.transform_bounds(*b, "EPSG:6933", "EPSG:4326")
    assert w < e
    assert abs(w + 180) < 1e-6
    assert abs(e - 180) < 1e-6
    assert s < -85.0
    assert n > 85.0


def test_asymmetric_ease_east_clamped_and_normalized():
    """模拟 west+cols*res 浮点越界：仍应得到全球 WGS84 bounds。"""
    from app.services.crs import crs_transformer

    # 故意让 east 略大于有效域
    w, s, e, n = crs_transformer.transform_bounds(
        -17367530.445161516,
        -7314540.830865865,
        17367530.445173528,
        7314540.830865865,
        "EPSG:6933",
        "EPSG:4326",
    )
    assert w < e
    assert e - w > 359.0


def test_apply_invalid_values():
    arr = np.array([[1.0, -9999.0], [np.nan, 3.0]], dtype=np.float32)
    out = apply_invalid_values(arr, invalid_values=[-9999.0], nodata=-1.0)
    assert out[0, 1] == -1.0
    assert out[1, 0] == -1.0
    assert out[0, 0] == 1.0
