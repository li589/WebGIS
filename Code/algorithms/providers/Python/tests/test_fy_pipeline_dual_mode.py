"""FY-01: plan_only vs data_products dual contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from pipelines.fy_products import FyDailyPipeline


def _make_fy_plan(
    tmp_dir: Path, date_key: str = "20230101", satellite: str = "FY3D"
) -> dict:
    return {
        "date_key": date_key,
        "orbit_type": "D",
        "input_files": (str(tmp_dir / "input.HDF"),),
        "output_dir": str(tmp_dir),
        "work_dir": str(tmp_dir),  # Use same dir so files survive temp dir cleanup
        "output_prefix": f"{satellite}_GBAL_L1_10V10H_{date_key}_D",
        "satellite": satellite,
        "metadata": {"input_dir": str(tmp_dir), "file_count": "1"},
    }


class FyPlanOnlyModeTests(unittest.TestCase):
    """FY-01: execute_commands=false produces plan-only artifacts."""

    def test_plan_only_manifest_excludes_data_layers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "input.HDF").touch()
            plan_dict = _make_fy_plan(tmp_dir)

            request = JobRequest(
                job_id="fy-plan-only",
                pipeline_name="fy_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(
                    start=datetime(2023, 1, 1), end=datetime(2023, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(tmp_dir)},
                algorithm_params={"execute_commands": False, "orbit_mode": "MWRID"},
                output_spec=OutputSpec(extra={}),
            )
            ctx = RuntimeContext(
                job_id="fy-plan-only",
                run_id="run-fy-plan",
                workspace=Path(tempfile.mkdtemp()),
                tmp_dir=Path(tempfile.mkdtemp()),
                cache_dir=Path(tempfile.mkdtemp()),
            )

            with (
                patch("pipelines.fy_products.build_fy_daily_job_plans") as mock_plans,
                patch(
                    "pipelines.fy_products.build_fy_daily_command_steps",
                    return_value=[],
                ),
            ):
                from ingest.fy import FyDailyJobPlan

                mock_plans.return_value = [FyDailyJobPlan(**plan_dict)]
                manifest = FyDailyPipeline().execute(request, ctx)

        product_types = {p.type for p in manifest.products}
        self.assertIn("fy_daily_job_plan", product_types)
        self.assertIn("fy_daily_command_plan", product_types)
        self.assertNotIn("fy_daily_mat", product_types)
        self.assertNotIn("fy_daily_tif", product_types)
        self.assertEqual(manifest.main_layers, [])


class FyDataProductsModeTests(unittest.TestCase):
    """FY-01: execute_commands=true produces data artifacts."""

    def test_data_products_manifest_includes_main_layers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "input.HDF").touch()

            import numpy as np
            import rasterio

            tif_dir = tmp_dir / "tif"
            tif_dir.mkdir()
            tif_path = tif_dir / "FY3D_D_20230101.tif"
            profile = {
                "driver": "GTiff",
                "height": 2,
                "width": 2,
                "count": 3,
                "dtype": "int16",
                "nodata": -9999,
            }
            with rasterio.open(tif_path, "w", **profile) as dst:
                dst.write(np.array([[500, 500], [500, 500]], dtype=np.int16), 1)
                dst.write(np.array([[600, 600], [600, 600]], dtype=np.int16), 2)
                dst.write(np.array([[50, 50], [50, 50]], dtype=np.int16), 3)

            plan_dict = _make_fy_plan(tmp_dir, date_key="20230101", satellite="FY3D")

            request = JobRequest(
                job_id="fy-data",
                pipeline_name="fy_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(
                    start=datetime(2023, 1, 1), end=datetime(2023, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(tmp_dir)},
                algorithm_params={"execute_commands": True, "orbit_mode": "MWRID"},
                output_spec=OutputSpec(extra={}),
            )
            ctx = RuntimeContext(
                job_id="fy-data",
                run_id="run-fy-data",
                workspace=Path(tempfile.mkdtemp()),
                tmp_dir=Path(tempfile.mkdtemp()),
                cache_dir=Path(tempfile.mkdtemp()),
            )

            with (
                patch("pipelines.fy_products.build_fy_daily_job_plans") as mock_plans,
                patch(
                    "pipelines.fy_products.build_fy_daily_command_steps",
                    return_value=[],
                ),
                patch("pipelines.fy_products.execute_fy_command_steps"),
                patch(
                    "pipelines.fy_products.get_fy_daily_multiband_output_path",
                    return_value=tif_path,
                ),
            ):
                from ingest.fy import FyDailyJobPlan

                mock_plans.return_value = [FyDailyJobPlan(**plan_dict)]
                manifest = FyDailyPipeline().execute(request, ctx)

        product_types = {p.type for p in manifest.products}
        self.assertIn("fy_daily_mat", product_types)
        self.assertIn("fy_daily_tif", product_types)
        self.assertIn("TBv", manifest.main_layers)
        self.assertIn("TBh", manifest.main_layers)
        self.assertIn("IA", manifest.main_layers)


class FyCommandPlanFileTests(unittest.TestCase):
    """FY-01: command plan JSON is written correctly."""

    def test_command_plan_json_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            (tmp_dir / "input.HDF").touch()
            plan_dict = _make_fy_plan(tmp_dir)

            request = JobRequest(
                job_id="fy-json",
                pipeline_name="fy_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(
                    start=datetime(2023, 1, 1), end=datetime(2023, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(tmp_dir)},
                algorithm_params={"execute_commands": False, "orbit_mode": "MWRID"},
                output_spec=OutputSpec(extra={}),
            )
            ctx = RuntimeContext(
                job_id="fy-json",
                run_id="run-fy-json",
                workspace=Path(tempfile.mkdtemp()),
                tmp_dir=Path(tempfile.mkdtemp()),
                cache_dir=Path(tempfile.mkdtemp()),
            )

            with (
                patch("pipelines.fy_products.build_fy_daily_job_plans") as mock_plans,
                patch(
                    "pipelines.fy_products.build_fy_daily_command_steps"
                ) as mock_steps,
            ):
                from ingest.fy import FyDailyJobPlan
                from algorithms.fy import FyCommandStep

                mock_steps.return_value = [
                    FyCommandStep(
                        name="s1",
                        command="gdal_translate",
                        outputs=(str(tmp_dir / "s1.tif"),),
                    ),
                    FyCommandStep(
                        name="s2",
                        command="gdalwarp",
                        outputs=(str(tmp_dir / "s2.tif"),),
                    ),
                ]
                mock_plans.return_value = [FyDailyJobPlan(**plan_dict)]
                manifest = FyDailyPipeline().execute(request, ctx)

            command_plan_refs = [
                p for p in manifest.products if p.type == "fy_daily_command_plan"
            ]
            self.assertEqual(len(command_plan_refs), 1)
            plan_path = Path(command_plan_refs[0].uri)
            self.assertTrue(plan_path.exists())
            with open(plan_path) as f:
                plan_data = json.load(f)
            self.assertEqual(len(plan_data), 2)
            self.assertEqual(plan_data[0]["name"], "s1")


if __name__ == "__main__":
    unittest.main()
