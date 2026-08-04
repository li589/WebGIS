"""numeric_sanitize + station/SMAP fill-value hardening."""

from __future__ import annotations

import math
import unittest

import numpy as np

from algorithms.block_inversion import _as_time_pixel_matrix
from algorithms.station import aggregate_station_records_daily, filter_station_records
from data_access.numeric_sanitize import (
    mask_common_fill_values,
    sanitize_science_array,
)
from ingest.station import StationRecord


class NumericSanitizeTests(unittest.TestCase):
    def test_common_fills_become_nan(self) -> None:
        raw = np.array([-9999.0, 1.0, -32768.0, np.inf, np.nan, 2.0], dtype=np.float64)
        out = mask_common_fill_values(raw)
        self.assertTrue(np.isnan(out[0]))
        self.assertEqual(out[1], 1.0)
        self.assertTrue(np.isnan(out[2]))
        self.assertTrue(np.isnan(out[3]))
        self.assertTrue(np.isnan(out[4]))
        self.assertEqual(out[5], 2.0)

    def test_sanitize_science_array_range(self) -> None:
        raw = np.array([-9999.0, 280.0, 400.0], dtype=np.float64)
        out = sanitize_science_array(raw, min_valid=0.0, max_valid=350.0)
        self.assertTrue(np.isnan(out[0]))
        self.assertEqual(out[1], 280.0)
        self.assertTrue(np.isnan(out[2]))

    def test_block_as_time_pixel_masks_fill(self) -> None:
        mat = _as_time_pixel_matrix(
            [[280.0, -9999.0], [np.inf, 300.0]], name="tbv_mat"
        )
        self.assertEqual(mat.shape, (2, 2))
        self.assertTrue(np.isnan(mat[0, 1]))
        self.assertTrue(np.isnan(mat[1, 0]))
        self.assertEqual(mat[0, 0], 280.0)


class StationFillValueTests(unittest.TestCase):
    def _rec(self, sm: float) -> StationRecord:
        return StationRecord(
            year=2020,
            month=1,
            day=1,
            hour=6,
            lat=40.0,
            lon=116.0,
            elev=50.0,
            depth_upper=0.0,
            depth_lower=0.05,
            soil_moisture=sm,
            quality_flag=1,
            site_id="A",
            source="test",
        )

    def test_filter_rejects_fill_and_inf(self) -> None:
        records = [
            self._rec(0.2),
            self._rec(-9999.0),
            self._rec(float("inf")),
            self._rec(float("nan")),
        ]
        out = filter_station_records(records, require_good_quality=True)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0].soil_moisture, 0.2)

    def test_aggregate_skips_fill(self) -> None:
        records = [self._rec(0.1), self._rec(-9999.0), self._rec(0.3)]
        out = aggregate_station_records_daily(records)
        self.assertEqual(len(out), 1)
        self.assertTrue(math.isfinite(out[0].soil_moisture))
        self.assertAlmostEqual(out[0].soil_moisture, 0.2)


if __name__ == "__main__":
    unittest.main()
