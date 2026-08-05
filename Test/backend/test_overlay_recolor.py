"""Overlay dynamic recolor / nodata tests."""

from __future__ import annotations

import unittest

import numpy as np

from app.services.overlay_tile_service import _apply_palette
from app.services.raster_preview_service import (
    colorize_array_to_rgba,
    normalize_nodata_mode,
    resolve_palette_id,
)


class OverlayRecolorTests(unittest.TestCase):
    def test_resolve_palette_aliases(self) -> None:
        self.assertEqual(resolve_palette_id("viridis"), "viridis")
        self.assertTrue(resolve_palette_id("unknown-xyz").startswith("viridis") or resolve_palette_id("unknown-xyz") == "viridis")

    def test_nodata_mode_normalize(self) -> None:
        self.assertEqual(normalize_nodata_mode(None), "transparent")
        self.assertEqual(normalize_nodata_mode("solid"), "solid")
        self.assertEqual(normalize_nodata_mode("TRANSPARENT"), "transparent")

    def test_apply_palette_solid_nodata(self) -> None:
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
        self.assertEqual(rgba.shape, (32, 32, 4))
        self.assertGreater(int(rgba[4, 4, 3]), 0)
        # nodata cell should be opaque red-ish
        self.assertEqual(int(rgba[0, 0, 3]), 255)
        self.assertGreater(int(rgba[0, 0, 0]), 200)

    def test_colorize_array_transparent_nodata(self) -> None:
        arr = np.array([[np.nan, 1.0], [0.0, 0.5]], dtype=np.float32)
        rgba = colorize_array_to_rgba(
            arr,
            palette="viridis",
            min_value=0.0,
            max_value=1.0,
            nodata_mode="transparent",
        )
        self.assertEqual(int(rgba[0, 0, 3]), 0)
        self.assertGreater(int(rgba[0, 1, 3]), 0)


if __name__ == "__main__":
    unittest.main()
