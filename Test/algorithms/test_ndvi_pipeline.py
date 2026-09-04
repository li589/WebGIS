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
    def test_execute_splits_yearly_metrics_and_ignores_historical_quality_files(
        self,
    ) -> None:
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
                time_range=TimeRange(
                    start=datetime(2019, 12, 20), end=datetime(2021, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir)},
                algorithm_params={"emit_quality_products": True},
                output_spec=OutputSpec(
                    extra={
                        "output_dir": str(output_dir),
                        "quality_output_dir": str(quality_dir),
                    }
                ),
            )
            ctx = RuntimeContext(
                job_id="job-ndvi",
                run_id="run-ndvi",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            with (
                patch(
                    "pipelines.ndvi_products.load_ndvi_stack",
                    return_value=(ndvi_stack, observation_dates),
                ),
                patch(
                    "pipelines.ndvi_products.process_ndvi_stack_to_daily",
                    return_value=(daily_stack, daily_dates),
                ),
            ):
                manifest = NdviDailyPipeline().execute(request, ctx)

            yearly_products = [
                product
                for product in manifest.products
                if product.type == "ndvi_yearly_qa_mat"
            ]
            self.assertEqual(
                [product.tags["year"] for product in yearly_products],
                ["2019", "2020", "2021"],
            )
            self.assertTrue((quality_dir / "VI_viirs_2019.mat").exists())
            self.assertTrue((quality_dir / "VI_viirs_2020.mat").exists())
            self.assertTrue((quality_dir / "VI_viirs_2021.mat").exists())

            merged = loadmat(quality_dir / "VI_v_qa.mat")
            self.assertIn("NDVI_v_mean", merged)
            self.assertFalse(
                np.allclose(merged["NDVI_v_mean"], historical_value, equal_nan=True)
            )
            self.assertEqual(
                [
                    product.type
                    for product in manifest.products
                    if product.type.endswith("_qa_mat")
                ],
                [
                    "ndvi_yearly_qa_mat",
                    "ndvi_yearly_qa_mat",
                    "ndvi_yearly_qa_mat",
                    "ndvi_multi_year_qa_mat",
                ],
            )

    def test_vi_sg_interpolate_graceful_degradation(self) -> None:
        from algorithms.ndvi import to_day_numbers, vi_sg_interpolate

        # Case 1: 单点观测（如仅有一个 16 天合成颗粒），在覆盖期内应保持常数且不为 NaN
        obs_dates = [datetime(2026, 6, 26)]
        out_dates = [datetime(2026, 7, 1), datetime(2026, 7, 10), datetime(2026, 7, 20)]
        obs_days = to_day_numbers(obs_dates)
        out_days = to_day_numbers(out_dates)
        sg_days = out_days
        data = np.array([0.65])
        res = vi_sg_interpolate(data, obs_days, sg_days, out_days, composite_days=16)
        self.assertAlmostEqual(res[0], 0.65)
        self.assertAlmostEqual(res[1], 0.65)
        self.assertTrue(np.isnan(res[2]))  # 2026-07-20 超过 16 天覆盖期

        # Case 2: 2 个有效观测点，应平滑降级为线性插值而不是全 NaN
        obs_dates_2 = [datetime(2026, 7, 1), datetime(2026, 7, 15)]
        out_dates_2 = [datetime(2026, 7, 5), datetime(2026, 7, 10)]
        obs_days_2 = to_day_numbers(obs_dates_2)
        out_days_2 = to_day_numbers(out_dates_2)
        data_2 = np.array([0.4, 0.8])
        res_2 = vi_sg_interpolate(data_2, obs_days_2, out_days_2, out_days_2, composite_days=16)
        self.assertFalse(np.isnan(res_2).any())
        self.assertTrue(0.4 < res_2[0] < 0.8)


if __name__ == "__main__":
    unittest.main()
