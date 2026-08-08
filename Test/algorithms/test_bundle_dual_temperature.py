"""Bundle-02: DUAL temperature scheme and match_info diagnostics in manifest."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.io import savemat

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from pipelines.daily_bundle_products import DailyBundlePipeline


class BundleDUALTemperatureTests(unittest.TestCase):
    """Bundle-02: DUAL temperature scheme exposes TC/Tsoil1/Tsoil2/Ct/TG layers."""

    def _make_mat(self, tmp_dir: Path, name: str) -> Path:
        p = tmp_dir / f"{name}.mat"
        savemat(p, {"data": np.zeros((1, 3), dtype=np.float64)}, do_compression=True)
        return p

    def test_dual_scheme_main_layers_include_temperature_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "bundle_output"
            output_dir.mkdir()

            request = JobRequest(
                job_id="bundle-dual",
                pipeline_name="daily_bundle_pipeline",
                task_type="bundle",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "smap_daily_mat": str(self._make_mat(root, "smap")),
                    "ndvi_daily_mat": str(self._make_mat(root, "ndvi")),
                    "ancillary_mat": str(self._make_mat(root, "anc")),
                },
                algorithm_params={"temp_scheme": "DUAL", "save_match_info": True},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )
            ctx = RuntimeContext(
                job_id="bundle-dual",
                run_id="run-bundle",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            with (
                patch(
                    "pipelines.daily_bundle_products.load_lin_pix_selection",
                    return_value=None,
                ),
                patch(
                    "pipelines.daily_bundle_products.build_daily_bundle_for_date"
                ) as mock_bundle,
            ):
                mock_bundle.return_value = {
                    "TBv": np.zeros((1, 3)),
                    "TC": np.zeros((1, 3)),
                    "Tsoil1": np.zeros((1, 3)),
                    "Tsoil2": np.zeros((1, 3)),
                    "Ct": np.zeros((1, 3)),
                    "TG": np.zeros((1, 3)),
                    "match_slot_index": np.zeros((1, 3)),
                    "match_day_offset": np.zeros((1, 3)),
                    "match_picked_file": np.array([["file1"]]),
                    "match_picked_utc": np.zeros((1, 3)),
                }
                manifest = DailyBundlePipeline().execute(request, ctx)

        self.assertIn("TC", manifest.main_layers)
        self.assertIn("Tsoil1", manifest.main_layers)
        self.assertIn("Tsoil2", manifest.main_layers)
        self.assertIn("Ct", manifest.main_layers)
        self.assertIn("TG", manifest.main_layers)
        self.assertIn("match_slot_index", manifest.main_layers)
        self.assertIn("match_day_offset", manifest.main_layers)
        self.assertIn("match_picked_file", manifest.main_layers)
        self.assertIn("match_picked_utc", manifest.main_layers)
        # Verify DUAL scheme saved in extra
        self.assertEqual(manifest.extra.get("temp_scheme"), "DUAL")
        self.assertEqual(manifest.extra.get("save_match_info"), True)

    def test_single_scheme_does_not_include_dual_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "bundle_output"
            output_dir.mkdir()

            request = JobRequest(
                job_id="bundle-single",
                pipeline_name="daily_bundle_pipeline",
                task_type="bundle",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "smap_daily_mat": str(self._make_mat(root, "smap")),
                    "ndvi_daily_mat": str(self._make_mat(root, "ndvi")),
                    "ancillary_mat": str(self._make_mat(root, "anc")),
                },
                algorithm_params={"temp_scheme": "SINGLE"},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )
            ctx = RuntimeContext(
                job_id="bundle-single",
                run_id="run-bundle-s",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            with (
                patch(
                    "pipelines.daily_bundle_products.load_lin_pix_selection",
                    return_value=None,
                ),
                patch(
                    "pipelines.daily_bundle_products.build_daily_bundle_for_date"
                ) as mock_bundle,
            ):
                mock_bundle.return_value = {
                    "TBv": np.zeros((1, 3)),
                    "Ts": np.zeros((1, 3)),
                }
                manifest = DailyBundlePipeline().execute(request, ctx)

        self.assertNotIn("TC", manifest.main_layers)
        self.assertNotIn("Tsoil1", manifest.main_layers)
        self.assertNotIn("match_slot_index", manifest.main_layers)
        self.assertEqual(manifest.extra.get("temp_scheme"), "SINGLE")


if __name__ == "__main__":
    unittest.main()
