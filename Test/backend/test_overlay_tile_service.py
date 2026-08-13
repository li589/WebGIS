"""Tests for overlay XYZ tile helpers."""

from __future__ import annotations


from app.services.overlay_tile_service import (
    _apply_palette,
    overview_max_zoom,
    render_geotiff_tile_png,
    tile_bbox_wgs84,
    tile_meta_fields,
)
import numpy as np


def test_tile_bbox_z0() -> None:
    west, south, east, north = tile_bbox_wgs84(0, 0, 0)
    assert round(west, 7) == round(-180.0, 7), 'round(west, 7) == round(-180.0, 7)'
    assert round(east, 7) == round(180.0, 7), 'round(east, 7) == round(180.0, 7)'
    assert north > 0.0, 'north > 0.0'
    assert south < 0.0, 'south < 0.0'


def test_tile_meta_fields() -> None:
    meta = tile_meta_fields("imported-demo")
    assert "{z}" in meta["tile_url_template"], '"{z}" in meta["tile_url_template"]'
    assert meta["overview_max_zoom"] == overview_max_zoom(), 'meta["overview_max_zoom"] == overview_max_zoom()'
    assert meta["maxzoom"] >= meta["minzoom"], 'meta["maxzoom"] >= meta["minzoom"]'


def test_apply_palette_handles_nan_mix() -> None:
    data = np.full((256, 256), np.nan, dtype=np.float32)
    data[10:20, 10:20] = 0.3
    valid = np.isfinite(data)
    rgba = _apply_palette(data, valid)
    assert rgba.shape == (256, 256, 4), 'rgba.shape == (256, 256, 4)'
    assert int(rgba[15, 15, 3]) > 0, 'int(rgba[15, 15, 3]) > 0'
    assert int(rgba[0, 0, 3]) == 0, 'int(rgba[0, 0, 3]) == 0'
