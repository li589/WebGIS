"""FY-02: TIF physical quantity unpacking matches MATLAB calibration."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio

from algorithms.fy import FY3D_PROFILE
from pipelines.fy_products import _load_fy_multiband_payload


class FyPhysicalQuantityUnpackTests(unittest.TestCase):
    """FY-02: TB = packed * scale + offset; IA = packed * zen_scale."""

    def test_tb_calibration_with_offset(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        tif_path = tmp_dir / "test_fy.tif"

        # TB = raw * 0.01 + 327.68; valid range [0, 330]
        # raw=0 → TB=327.68K (within range), raw=228 → TB=330K (within range)
        profile = {
            "driver": "GTiff",
            "height": 2,
            "width": 2,
            "count": 3,
            "dtype": "int16",
            "nodata": -9999,
        }
        with rasterio.open(tif_path, "w", **profile) as dst:
            dst.write(np.array([[0, 0], [0, 0]], dtype=np.int16), 1)
            dst.write(np.array([[228, 228], [228, 228]], dtype=np.int16), 2)
            dst.write(np.array([[50, 50], [50, 50]], dtype=np.int16), 3)

        payload = _load_fy_multiband_payload(tif_path, satellite="FY3D")

        prof = FY3D_PROFILE
        expected_tbv = np.array([[327.68, 327.68], [327.68, 327.68]], dtype=np.float64)
        expected_tbh = np.array([[329.96, 329.96], [329.96, 329.96]], dtype=np.float64)
        expected_ia = np.array([[0.5, 0.5], [0.5, 0.5]], dtype=np.float64)

        np.testing.assert_array_almost_equal(payload["TBv"], expected_tbv)
        np.testing.assert_array_almost_equal(payload["TBh"], expected_tbh)
        np.testing.assert_array_almost_equal(payload["IA"], expected_ia)

    def test_tb_nan_for_invalid_range(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        tif_path = tmp_dir / "test_fy_nan.tif"

        # raw=4000 → TB=367.68K > 330, should become NaN
        # raw=0 → TB=327.68K within [0,330], should remain valid
        profile = {
            "driver": "GTiff",
            "height": 2,
            "width": 2,
            "count": 3,
            "dtype": "int16",
            "nodata": -9999,
        }
        with rasterio.open(tif_path, "w", **profile) as dst:
            dst.write(np.array([[4000, 0], [0, 4000]], dtype=np.int16), 1)
            dst.write(np.array([[4000, 228], [228, 4000]], dtype=np.int16), 2)
            dst.write(np.array([[50, 50], [50, 50]], dtype=np.int16), 3)

        payload = _load_fy_multiband_payload(tif_path, satellite="FY3D")

        self.assertTrue(np.isnan(payload["TBv"][0, 0]))
        self.assertTrue(np.isnan(payload["TBv"][1, 1]))
        self.assertFalse(np.isnan(payload["TBv"][0, 1]))
        self.assertFalse(np.isnan(payload["TBv"][1, 0]))

    def test_nodata_becomes_nan(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        tif_path = tmp_dir / "test_fy_nodata.tif"

        # Valid raw values for TBh: raw=0 → TB=327.68K, raw=228 → TB=330K (both in [0,330])
        profile = {
            "driver": "GTiff",
            "height": 2,
            "width": 2,
            "count": 3,
            "dtype": "int16",
            "nodata": -9999,
        }
        with rasterio.open(tif_path, "w", **profile) as dst:
            dst.write(np.array([[-9999, 0], [0, -9999]], dtype=np.int16), 1)
            dst.write(np.array([[-9999, 228], [228, -9999]], dtype=np.int16), 2)
            dst.write(np.array([[50, 50], [50, 50]], dtype=np.int16), 3)

        payload = _load_fy_multiband_payload(tif_path, satellite="FY3D")

        self.assertTrue(np.isnan(payload["TBv"][0, 0]))
        self.assertTrue(np.isnan(payload["TBv"][1, 1]))
        self.assertFalse(np.isnan(payload["TBv"][0, 1]))
        self.assertFalse(np.isnan(payload["TBv"][1, 0]))

    def test_insufficient_bands_raises(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        tif_path = tmp_dir / "test_fy_few.tif"

        profile = {
            "driver": "GTiff",
            "height": 2,
            "width": 2,
            "count": 2,
            "dtype": "int16",
            "nodata": -9999,
        }
        with rasterio.open(tif_path, "w", **profile) as dst:
            dst.write(np.zeros((2, 2), dtype=np.int16), 1)
            dst.write(np.zeros((2, 2), dtype=np.int16), 2)

        with self.assertRaises(ValueError) as ctx:
            _load_fy_multiband_payload(tif_path, satellite="FY3D")
        self.assertIn("at least 3 bands", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
