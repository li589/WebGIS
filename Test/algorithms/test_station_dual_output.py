"""Station-01: ISMN and CASMOS produce both daily.mat and am6.mat products."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from ingest.station import StationRecord
from pipelines.station_products import StationDailyPipeline


class StationDualOutputTests(unittest.TestCase):
    """Station-01: both daily.mat and am6.mat are produced consistently."""

    def _make_records(self) -> list[StationRecord]:
        records = []
        for day in range(1, 31):
            for hour in [0, 6, 12, 18]:
                records.append(
                    StationRecord(
                        year=2020,
                        month=1,
                        day=day,
                        hour=hour,
                        lat=30.0,
                        lon=115.0,
                        elev=100.0,
                        depth_upper=0.05,
                        depth_lower=0.05,
                        soil_moisture=0.25,
                        quality_flag=1,
                        site_id="SITE001",
                        source="ISMN",
                    )
                )
        return records

    def test_ismn_produces_daily_and_am6_products(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "station_output"
            output_dir.mkdir()

            request = JobRequest(
                job_id="station-dual",
                pipeline_name="station_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 10)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(root)},
                algorithm_params={
                    "source_type": "ISMN",
                    "emit_validation_products": False,
                    "validation_hour": 6,
                    "validation_min_valid_days": 1,
                },
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )
            ctx = RuntimeContext(
                job_id="station-dual",
                run_id="run-station",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            records = self._make_records()
            pipeline = StationDailyPipeline()

            # STM file matches discovery pattern *sm_0.*.stm
            stm_file = root / "SITE001_sm_0.dat.stm"
            stm_file.write_text("", encoding="utf-8")

            # Intercept both file discovery and parsing so the pipeline receives the mock records
            with patch(
                "pipelines.station_products.discover_ismn_stm_files",
                return_value=[stm_file],
            ):
                with patch(
                    "pipelines.station_products.parse_ismn_stm_file",
                    return_value=records,
                ):
                    manifest = pipeline.execute(request, ctx)

            product_types = {p.type for p in manifest.products}
            self.assertIn("station_daily_mat", product_types)
            self.assertIn("station_am6_mat", product_types)

            daily_refs = [p for p in manifest.products if p.type == "station_daily_mat"]
            am6_refs = [p for p in manifest.products if p.type == "station_am6_mat"]
            self.assertEqual(len(daily_refs), 1)
            self.assertEqual(len(am6_refs), 1)
            self.assertTrue(Path(daily_refs[0].uri).exists())
            self.assertTrue(Path(am6_refs[0].uri).exists())

    def test_casmos_produces_daily_and_am6_products(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "station_output"
            output_dir.mkdir()

            records = [
                StationRecord(
                    year=2020,
                    month=1,
                    day=1,
                    hour=6,
                    lat=35.0,
                    lon=120.0,
                    elev=200.0,
                    depth_upper=0.10,
                    depth_lower=0.10,
                    soil_moisture=0.30,
                    quality_flag=1,
                    site_id="COSMOS001",
                    source="CASMOS",
                ),
                StationRecord(
                    year=2020,
                    month=1,
                    day=2,
                    hour=6,
                    lat=35.0,
                    lon=120.0,
                    elev=200.0,
                    depth_upper=0.10,
                    depth_lower=0.10,
                    soil_moisture=0.32,
                    quality_flag=1,
                    site_id="COSMOS001",
                    source="CASMOS",
                ),
            ]

            request = JobRequest(
                job_id="cosmos-dual",
                pipeline_name="station_daily_pipeline",
                task_type="extract",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 10)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(root)},
                algorithm_params={
                    "source_type": "CASMOS",
                    "emit_validation_products": False,
                    "validation_hour": 6,
                    "validation_min_valid_days": 1,
                },
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )
            ctx = RuntimeContext(
                job_id="cosmos-dual",
                run_id="run-cosmos",
                workspace=root,
                tmp_dir=root / "tmp",
                cache_dir=root / "cache",
            )

            pipeline = StationDailyPipeline()
            txt_file = root / "COSMOS001.txt"
            txt_file.write_text("", encoding="utf-8")

            # Intercept file discovery and parsing with pre-built records
            with patch(
                "pipelines.station_products.discover_casmos_txt_files",
                return_value=[txt_file],
            ):
                with patch(
                    "pipelines.station_products.parse_casmos_txt_file",
                    return_value=records,
                ):
                    manifest = pipeline.execute(request, ctx)

            product_types = {p.type for p in manifest.products}
            self.assertIn("station_daily_mat", product_types)
            self.assertIn("station_am6_mat", product_types)


if __name__ == "__main__":
    unittest.main()
