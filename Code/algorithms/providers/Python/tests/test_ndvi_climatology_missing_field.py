"""NDVI-03: climatology missing NDVI_clim field raises KeyError."""
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
from pipelines.ndvi_products import NdviDailyPipeline


class NdviClimatologyMissingFieldTests(unittest.TestCase):
    """NDVI-03: climatology file missing NDVI_clim raises KeyError."""

    def test_missing_ndvi_clim_raises_key_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            input_dir = root / "ndvi_input"
            output_dir = root / "daily"
            quality_dir = root / "quality"
            clim_dir = root / "climatology"
            input_dir.mkdir()
            output_dir.mkdir()
            quality_dir.mkdir()
            clim_dir.mkdir()

            doy = datetime(2020, 6, 1).timetuple().tm_yday
            savemat(clim_dir / f"{doy}.mat", {"some_other_field": np.zeros((1, 2))}, do_compression=True)

            request = JobRequest(
                job_id="ndvi-clim-missing",
                pipeline_name="ndvi_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(start=datetime(2020, 6, 1), end=datetime(2020, 6, 1)),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir), "ndvi_clim_dir": str(clim_dir)},
                algorithm_params={"emit_quality_products": True},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir), "quality_output_dir": str(quality_dir)}),
            )
            runtime_ctx = RuntimeContext(
                job_id="ndvi-clim-missing",
                run_id="run-ndvi-clim",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            ndvi_stack = np.stack([np.array([[0.15, 0.25]], dtype=np.float64)], axis=2)
            observation_dates = [datetime(2020, 6, 1)]
            daily_stack = np.stack([np.array([[0.1, 0.2]], dtype=np.float64)], axis=2)
            daily_dates = [datetime(2020, 6, 1)]

            with patch("pipelines.ndvi_products.load_ndvi_stack", return_value=(ndvi_stack, observation_dates)), \
                 patch("pipelines.ndvi_products.process_ndvi_stack_to_daily", return_value=(daily_stack, daily_dates)):
                with self.assertRaises(KeyError) as exc_info:
                    NdviDailyPipeline().execute(request, runtime_ctx)
            self.assertIn("NDVI_clim", str(exc_info.exception))


if __name__ == "__main__":
    unittest.main()
