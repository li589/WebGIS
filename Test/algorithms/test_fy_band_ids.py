"""FY band_ids coercion — workflow JSON may pass strings from node properties."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from algorithms.fy import build_fy_daily_command_steps, normalize_fy_band_ids
from ingest.fy import FyDailyJobPlan


class NormalizeFyBandIdsTests(unittest.TestCase):
    def test_list_of_strings(self) -> None:
        self.assertEqual(normalize_fy_band_ids(["1", "2"]), (1, 2))

    def test_comma_separated_string(self) -> None:
        self.assertEqual(normalize_fy_band_ids("1,2"), (1, 2))

    def test_build_command_steps_accepts_string_band_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            plan = FyDailyJobPlan(
                date_key="20260131",
                orbit_type="MWRID",
                input_files=(str(tmp_dir / "FY3D_MWRID.HDF"),),
                output_dir=str(tmp_dir),
                work_dir=str(tmp_dir),
                output_prefix="FY3D_GBAL_L1_10V10H_20260131_MWRID",
                satellite="FY3D",
                metadata={"input_format": "hdf"},
            )
            with patch("algorithms.fy.resolve_gdal_bins") as mock_bins:
                mock_bins.return_value = {
                    "gdal_translate": "gdal_translate",
                    "gdalwarp": "gdalwarp",
                    "gdalbuildvrt": "gdalbuildvrt",
                }
                steps = build_fy_daily_command_steps(plan, band_ids=("1", "2"))
            self.assertGreater(len(steps), 0)


if __name__ == "__main__":
    unittest.main()
