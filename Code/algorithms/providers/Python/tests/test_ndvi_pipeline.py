from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.io import loadmat, savemat

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from pipelines.ndvi_products import NdviDailyPipeline


class NdviPipelineTests(unittest.TestCase):
    def test_execute_splits_yearly_metrics_and_ignores_historical_quality_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "ndvi_16day"
            output_dir = root / "daily"
            quality_dir = root / "quality"
            input_dir.mkdir()
            quality_dir.mkdir()

            historical_value = np.full((1, 2), 99.0, dtype=np.float64)
            savemat(
                quality_dir / "VI_viirs_1999.mat",
                {
                    "NDVI_v_mean": historical_value,
                    "NDVI_v_max": historical_value,
                    "NDVI_v_min": historical_value,
                    "NDVI_v_diff_mean": historical_value,
                    "NDVI_v_diff_std": historical_value,
                    "NDVI_v_range": historical_value,
                    "NDVI_v_od": historical_value,
                    "NDVI_v_vali": historical_value,
                },
                do_compression=True,
            )

            observation_dates = [
                datetime(2019, 12, 20),
                datetime(2020, 1, 5),
                datetime(2020, 2, 5),
                datetime(2020, 12, 20),
                datetime(2021, 1, 10),
            ]
            daily_dates = [
                datetime(2019, 12, 31),
                datetime(2020, 1, 1),
                datetime(2020, 6, 1),
                datetime(2020, 12, 31),
                datetime(2021, 1, 1),
            ]
            daily_stack = np.stack(
                [
                    np.array([[0.1, 0.2]], dtype=np.float64),
                    np.array([[0.3, 0.4]], dtype=np.float64),
                    np.array([[0.5, 0.6]], dtype=np.float64),
                    np.array([[0.7, 0.8]], dtype=np.float64),
                    np.array([[0.9, 1.0]], dtype=np.float64),
                ],
                axis=2,
            )
            ndvi_stack = np.stack(
                [
                    np.array([[0.15, 0.25]], dtype=np.float64),
                    np.array([[0.35, 0.45]], dtype=np.float64),
                ],
                axis=2,
            )

            request = JobRequest(
                job_id="job-ndvi",
                pipeline_name="ndvi_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(start=datetime(2019, 12, 20), end=datetime(2021, 1, 1)),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir)},
                algorithm_params={"emit_quality_products": True},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir), "quality_output_dir": str(quality_dir)}),
            )
            ctx = RuntimeContext(
                job_id="job-ndvi",
                run_id="run-ndvi",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            with patch("pipelines.ndvi_products.load_ndvi_stack", return_value=(ndvi_stack, observation_dates)), patch(
                "pipelines.ndvi_products.process_ndvi_stack_to_daily",
                return_value=(daily_stack, daily_dates),
            ):
                manifest = NdviDailyPipeline().execute(request, ctx)

            yearly_products = [product for product in manifest.products if product.type == "ndvi_yearly_qa_mat"]
            self.assertEqual([product.tags["year"] for product in yearly_products], ["2019", "2020", "2021"])
            self.assertTrue((quality_dir / "VI_viirs_2019.mat").exists())
            self.assertTrue((quality_dir / "VI_viirs_2020.mat").exists())
            self.assertTrue((quality_dir / "VI_viirs_2021.mat").exists())

            merged = loadmat(quality_dir / "VI_v_qa.mat")
            self.assertIn("NDVI_v_mean", merged)
            self.assertFalse(np.allclose(merged["NDVI_v_mean"], historical_value, equal_nan=True))
            self.assertEqual(
                [product.type for product in manifest.products if product.type.endswith("_qa_mat")],
                ["ndvi_yearly_qa_mat", "ndvi_yearly_qa_mat", "ndvi_yearly_qa_mat", "ndvi_multi_year_qa_mat"],
            )


if __name__ == "__main__":
    unittest.main()
