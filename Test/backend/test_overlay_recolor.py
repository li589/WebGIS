"""Overlay dynamic recolor / nodata tests."""

from __future__ import annotations


import numpy as np

from app.services.overlay_tile_service import _apply_palette
from app.services.raster_preview_service import (
    colorize_array_to_rgba,
    normalize_nodata_mode,
    resolve_palette_id,
)


def test_resolve_palette_aliases() -> None:
    assert resolve_palette_id("viridis") == "viridis", 'resolve_palette_id("viridis") == "viridis"'
    assert resolve_palette_id("unknown-xyz").startswith("viridis") or resolve_palette_id("unknown-xyz") == "viridis", 'resolve_palette_id("unknown-xyz").startswith("viridis") or resolve_palette_id("unknown-xyz") == "viridis" is truthy'


def test_nodata_mode_normalize() -> None:
    assert normalize_nodata_mode(None) == "transparent", 'normalize_nodata_mode(None) == "transparent"'
    assert normalize_nodata_mode("solid") == "solid", 'normalize_nodata_mode("solid") == "solid"'
    assert normalize_nodata_mode("TRANSPARENT") == "transparent", 'normalize_nodata_mode("TRANSPARENT") == "transparent"'


def test_apply_palette_solid_nodata() -> None:
    data = np.full((32, 32), np.nan, dtype=np.float32)
    data[2:6, 2:6] = 0.5
    valid = np.isfinite(data)
    rgba = _apply_palette(
        data,
        valid,
        palette="viridis",
        min_value=0.0,
        max_value=1.0,
        nodata_mode="solid",
        nodata_color="#ff0000",
    )
    assert rgba.shape == (32, 32, 4), 'rgba.shape == (32, 32, 4)'
    assert int(rgba[4, 4, 3]) > 0, 'int(rgba[4, 4, 3]) > 0'
    # nodata cell should be opaque red-ish
    assert int(rgba[0, 0, 3]) == 255, 'int(rgba[0, 0, 3]) == 255'
    assert int(rgba[0, 0, 0]) > 200, 'int(rgba[0, 0, 0]) > 200'


def test_colorize_array_transparent_nodata() -> None:
    arr = np.array([[np.nan, 1.0], [0.0, 0.5]], dtype=np.float32)
    rgba = colorize_array_to_rgba(
        arr,
        palette="viridis",
        min_value=0.0,
        max_value=1.0,
        nodata_mode="transparent",
    )
    assert int(rgba[0, 0, 3]) == 0, 'int(rgba[0, 0, 3]) == 0'
    assert int(rgba[0, 1, 3]) > 0, 'int(rgba[0, 1, 3]) > 0'
