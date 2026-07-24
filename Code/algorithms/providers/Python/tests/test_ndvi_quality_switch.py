"""NDVI-01: emit_quality_products switch controls QA output only."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from pipelines.ndvi_products import NdviDailyPipeline


class NdviQualitySwitchTests(unittest.TestCase):
    """NDVI-01: emit_quality_products controls QA products, not daily NDVI."""

    def _make_ndvi_stack(self):
        daily_stack = np.stack(
            [
                np.array([[0.1, 0.2]], dtype=np.float64),
                np.array([[0.3, 0.4]], dtype=np.float64),
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
        observation_dates = [datetime(2020, 6, 1), datetime(2020, 6, 17)]
        return ndvi_stack, observation_dates, daily_stack

    def test_quality_on_produces_daily_ndvi_and_qa_products(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "ndvi_input"
            output_dir = root / "daily"
            quality_dir = root / "quality"
            input_dir.mkdir()
            quality_dir.mkdir()

            request = JobRequest(
                job_id="ndvi-qa-on",
                pipeline_name="ndvi_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(
                    start=datetime(2020, 6, 1), end=datetime(2020, 6, 30)
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
                job_id="ndvi-qa-on",
                run_id="run-ndvi-qa",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            daily_stack = np.stack(
                [
                    np.array([[0.1, 0.2]], dtype=np.float64),
                    np.array([[0.3, 0.4]], dtype=np.float64),
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
            observation_dates = [datetime(2020, 6, 1), datetime(2020, 6, 17)]
            daily_dates = [datetime(2020, 6, 1), datetime(2020, 6, 2)]

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

            product_types = {p.type for p in manifest.products}
            self.assertIn("daily_ndvi_mat", product_types)
            self.assertIn("ndvi_yearly_qa_mat", product_types)
            self.assertIn("ndvi_multi_year_qa_mat", product_types)
            self.assertTrue((quality_dir / "VI_v_qa.mat").exists())

    def test_quality_off_produces_only_daily_ndvi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "ndvi_input"
            output_dir = root / "daily"
            input_dir.mkdir()

            request = JobRequest(
                job_id="ndvi-qa-off",
                pipeline_name="ndvi_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(
                    start=datetime(2020, 6, 1), end=datetime(2020, 6, 30)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir)},
                algorithm_params={"emit_quality_products": False},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )
            ctx = RuntimeContext(
                job_id="ndvi-qa-off",
                run_id="run-ndvi-noqa",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            ndvi_stack = np.stack([np.array([[0.15, 0.25]], dtype=np.float64)], axis=2)
            observation_dates = [datetime(2020, 6, 1)]
            daily_stack = np.stack([np.array([[0.1, 0.2]], dtype=np.float64)], axis=2)
            daily_dates = [datetime(2020, 6, 1)]

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

            product_types = {p.type for p in manifest.products}
            self.assertIn("daily_ndvi_mat", product_types)
            # QA products must NOT be present
            self.assertNotIn("ndvi_yearly_qa_mat", product_types)
            self.assertNotIn("ndvi_multi_year_qa_mat", product_types)
            # Only daily files
            self.assertEqual(
                len([p for p in manifest.products if p.type == "daily_ndvi_mat"]), 1
            )


if __name__ == "__main__":
    unittest.main()
