"""Tests for overlay XYZ tile helpers."""

from __future__ import annotations

import unittest

from app.services.overlay_tile_service import (
    _apply_palette,
    overview_max_zoom,
    render_geotiff_tile_png,
    tile_bbox_wgs84,
    tile_meta_fields,
)
import numpy as np


class OverlayTileServiceTests(unittest.TestCase):
    def test_tile_bbox_z0(self) -> None:
        west, south, east, north = tile_bbox_wgs84(0, 0, 0)
        self.assertAlmostEqual(west, -180.0, places=5)
        self.assertAlmostEqual(east, 180.0, places=5)
        self.assertGreater(north, 0.0)
        self.assertLess(south, 0.0)

    def test_tile_meta_fields(self) -> None:
        meta = tile_meta_fields("imported-demo")
        self.assertIn("{z}", meta["tile_url_template"])
        self.assertEqual(meta["overview_max_zoom"], overview_max_zoom())
        self.assertGreaterEqual(meta["maxzoom"], meta["minzoom"])

    def test_apply_palette_handles_nan_mix(self) -> None:
        data = np.full((256, 256), np.nan, dtype=np.float32)
        data[10:20, 10:20] = 0.3
        valid = np.isfinite(data)
        rgba = _apply_palette(data, valid)
        self.assertEqual(rgba.shape, (256, 256, 4))
        self.assertGreater(int(rgba[15, 15, 3]), 0)
        self.assertEqual(int(rgba[0, 0, 3]), 0)


if __name__ == "__main__":
    unittest.main()
