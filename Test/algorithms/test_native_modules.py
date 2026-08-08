from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from contracts.job import JobRequest, JobResult
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, RuntimeContext, TimeRange
from ingest.station import StationRecord
from modules.block_inversion import BlockInversionModule
from modules.bundles import DailyBundleModule, TimeSeriesBundleModule
from modules.fy import FyDailyModule
from modules.inversion import InversionDailyModule
from modules.ndvi import NdviDailyModule
from modules.omega import OmegaBlockModule
from modules.smap import SmapDailyModule
from modules.station import StationDailyModule
from modules.registry import get_module
from pipelines.timeseries_bundle_products import TimeSeriesBundlePipeline
from runner.dispatch import run_job
from utils.local_adapters import LocalProductSink


class _RecordingScheduler:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, dict | None]] = []
        self.completed: list[JobResult] = []

    def get_run_context(self, request: JobRequest) -> dict[str, str]:
        return {"job_id": request.job_id}

    def update_status(self, job_id: str, run_id: str, status: str, detail=None) -> None:
        _ = (job_id, run_id)
        self.statuses.append((status, detail))

    def complete(self, result: JobResult) -> None:
        self.completed.append(result)


class _NoopDataSource:
    def discover(self, request):
        _ = request
        return []

    def resolve(self, request):
        _ = request
        raise AssertionError(
            "daily_bundle native module should not call datasource adapter directly"
        )

    def acquire(self, bundle):
        _ = bundle
        raise AssertionError(
            "daily_bundle native module should not call datasource adapter directly"
        )

    def materialize(self, bundle):
        _ = bundle
        raise AssertionError(
            "daily_bundle native module should not call datasource adapter directly"
        )


class _RecordingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def bind_context(self, job_id: str, run_id: str) -> None:
        _ = (job_id, run_id)

    def emit_stage_start(self, stage: str, message: str) -> None:
        self.events.append(("start", stage))
        _ = message

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        _ = (stage, progress, message)

    def emit_warning(self, stage: str, message: str, extra=None) -> None:
        _ = (stage, message, extra)

    def emit_error(self, stage: str, message: str, extra=None) -> None:
        self.events.append(("error", stage))
        _ = (message, extra)

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        self.events.append(("artifact", stage))
        _ = (artifact_uri, artifact_type)

    def emit_stage_end(self, stage: str, message: str) -> None:
        self.events.append(("end", stage))
        _ = message


class NativeModuleTests(unittest.TestCase):
    def test_get_module_resolves_native_daily_bundle_for_pipeline_alias(self) -> None:
        module = get_module("daily_bundle_pipeline")
        self.assertIsInstance(module, DailyBundleModule)
        self.assertEqual(module.name, "daily_bundle")

    def test_get_module_resolves_native_timeseries_bundle_for_pipeline_alias(
        self,
    ) -> None:
        module = get_module("timeseries_bundle_pipeline")
        self.assertIsInstance(module, TimeSeriesBundleModule)
        self.assertEqual(module.name, "timeseries_bundle")

    def test_get_module_resolves_native_block_inversion_for_pipeline_alias(
        self,
    ) -> None:
        module = get_module("block_inversion_pipeline")
        self.assertIsInstance(module, BlockInversionModule)
        self.assertEqual(module.name, "block_inversion")

    def test_get_module_resolves_native_ndvi_for_pipeline_alias(self) -> None:
        module = get_module("ndvi_daily_pipeline")
        self.assertIsInstance(module, NdviDailyModule)
        self.assertEqual(module.name, "ndvi_daily")

    def test_get_module_resolves_native_fy_for_pipeline_alias(self) -> None:
        module = get_module("fy_daily_pipeline")
        self.assertIsInstance(module, FyDailyModule)
        self.assertEqual(module.name, "fy_daily")

    def test_get_module_resolves_native_inversion_for_pipeline_alias(self) -> None:
        module = get_module("inversion_daily_pipeline")
        self.assertIsInstance(module, InversionDailyModule)
        self.assertEqual(module.name, "inversion_daily")

    def test_get_module_resolves_native_omega_for_pipeline_alias(self) -> None:
        module = get_module("omega_block_pipeline")
        self.assertIsInstance(module, OmegaBlockModule)
        self.assertEqual(module.name, "omega_block")

    def test_get_module_resolves_native_smap_for_pipeline_alias(self) -> None:
        module = get_module("smap_daily_pipeline")
        self.assertIsInstance(module, SmapDailyModule)
        self.assertEqual(module.name, "smap_daily")

    def test_get_module_resolves_native_station_for_pipeline_alias(self) -> None:
        module = get_module("station_daily_pipeline")
        self.assertIsInstance(module, StationDailyModule)
        self.assertEqual(module.name, "station_daily")

    def test_run_job_executes_native_daily_bundle_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            request = JobRequest(
                job_id="job-native-daily",
                pipeline_name="workflow",
                module_name="daily_bundle",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"anc_root": "mock-anc"},
                algorithm_params={},
                output_spec=OutputSpec(extra={"output_dir": str(workspace / "daily")}),
            )

            fake_bundle = {
                "TBv": np.array([1.0, 2.0], dtype=np.float64),
                "TBh": np.array([3.0, 4.0], dtype=np.float64),
                "IA": np.array([5.0, 6.0], dtype=np.float64),
                "Ts": np.array([7.0, 8.0], dtype=np.float64),
                "SM_ref": np.array([0.2, 0.3], dtype=np.float64),
                "NDVI": np.array([0.4, 0.5], dtype=np.float64),
                "SF": np.array([0.6, 0.7], dtype=np.float64),
                "vwc": np.array([0.8, 0.9], dtype=np.float64),
            }

            with (
                patch("modules.bundles.load_lin_pix_selection", return_value=None),
                patch(
                    "modules.bundles.build_daily_bundle_for_date",
                    return_value=fake_bundle,
                ) as bundle_builder,
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            bundle_builder.assert_called_once()

            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest_payload["products"][0]["type"], "daily_bundle_mat"
            )
            self.assertEqual(manifest_payload["extra"]["module_name"], "daily_bundle")
            self.assertEqual(manifest_payload["extra"]["count"], 1)
            self.assertTrue(Path(manifest_payload["products"][0]["uri"]).exists())
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_executes_native_daily_bundle_module_from_prepared_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            anc_root = workspace / "ancillary_root"
            anc_root.mkdir()
            request = JobRequest(
                job_id="job-native-daily-prepared",
                pipeline_name="workflow",
                module_name="daily_bundle",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "anc_root": {
                            "selector": {"uris": [str(anc_root)]},
                        }
                    }
                },
                algorithm_params={},
                output_spec=OutputSpec(
                    extra={"output_dir": str(workspace / "daily_prepared")}
                ),
            )

            fake_bundle = {
                "TBv": np.array([1.0, 2.0], dtype=np.float64),
                "TBh": np.array([3.0, 4.0], dtype=np.float64),
                "IA": np.array([5.0, 6.0], dtype=np.float64),
                "Ts": np.array([7.0, 8.0], dtype=np.float64),
                "SM_ref": np.array([0.2, 0.3], dtype=np.float64),
                "NDVI": np.array([0.4, 0.5], dtype=np.float64),
                "SF": np.array([0.6, 0.7], dtype=np.float64),
                "vwc": np.array([0.8, 0.9], dtype=np.float64),
            }

            def fake_build_daily_bundle_for_date(
                *, date_key, config, datasource_selection, lin_pix
            ):
                _ = (date_key, config, lin_pix)
                self.assertEqual(
                    datasource_selection["anc_root"], str(expected_anc_root)
                )
                return fake_bundle

            expected_anc_root = anc_root
            with (
                patch("modules.bundles.load_lin_pix_selection", return_value=None),
                patch(
                    "modules.bundles.build_daily_bundle_for_date",
                    side_effect=fake_build_daily_bundle_for_date,
                ) as bundle_builder,
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            bundle_builder.assert_called_once()
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest_payload["products"][0]["type"], "daily_bundle_mat"
            )
            self.assertEqual(manifest_payload["extra"]["module_name"], "daily_bundle")
            self.assertEqual(manifest_payload["extra"]["count"], 1)

    def test_run_job_executes_daily_bundle_pipeline_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            ancillary_root = workspace / "ancillary_root_pipeline"
            smap_root = workspace / "smap_root_pipeline"
            ndvi_root = workspace / "ndvi_root_pipeline"
            ancillary_root.mkdir()
            smap_root.mkdir()
            ndvi_root.mkdir()
            request = JobRequest(
                job_id="job-pipeline-daily-prepared",
                pipeline_name="daily_bundle_pipeline",
                task_type="daily_bundle",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "ancillary_mat": {"selector": {"uris": [str(ancillary_root)]}},
                        "smap_daily_mat": {"selector": {"uris": [str(smap_root)]}},
                        "ndvi_daily_mat": {"selector": {"uris": [str(ndvi_root)]}},
                    }
                },
                algorithm_params={},
                output_spec=OutputSpec(
                    extra={"output_dir": str(workspace / "daily_pipeline_prepared")}
                ),
            )

            fake_bundle = {
                "TBv": np.array([1.0, 2.0], dtype=np.float64),
                "TBh": np.array([3.0, 4.0], dtype=np.float64),
                "IA": np.array([5.0, 6.0], dtype=np.float64),
                "Ts": np.array([7.0, 8.0], dtype=np.float64),
                "SM_ref": np.array([0.2, 0.3], dtype=np.float64),
                "NDVI": np.array([0.4, 0.5], dtype=np.float64),
                "SF": np.array([0.6, 0.7], dtype=np.float64),
                "vwc": np.array([0.8, 0.9], dtype=np.float64),
            }

            def fake_build_daily_bundle_for_date(
                *, date_key, config, datasource_selection, lin_pix
            ):
                _ = (date_key, config, lin_pix)
                self.assertEqual(
                    datasource_selection["anc_root"], str(expected_anc_root)
                )
                self.assertEqual(
                    datasource_selection["smap_folder"], str(expected_smap_root)
                )
                self.assertEqual(
                    datasource_selection["ndvi_folder"], str(expected_ndvi_root)
                )
                return fake_bundle

            expected_anc_root = ancillary_root
            expected_smap_root = smap_root
            expected_ndvi_root = ndvi_root
            with (
                patch(
                    "pipelines.daily_bundle_products.load_lin_pix_selection",
                    return_value=None,
                ),
                patch(
                    "pipelines.daily_bundle_products.build_daily_bundle_for_date",
                    side_effect=fake_build_daily_bundle_for_date,
                ) as bundle_builder,
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            bundle_builder.assert_called_once()
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest_payload["products"][0]["type"], "daily_bundle_mat"
            )
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "daily_bundle_pipeline"
            )
            self.assertEqual(manifest_payload["extra"]["count"], 1)

    def test_run_job_executes_native_ndvi_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "ndvi_16day"
            output_dir = workspace / "daily"
            quality_dir = workspace / "quality"
            input_dir.mkdir()
            quality_dir.mkdir()
            request = JobRequest(
                job_id="job-native-ndvi",
                pipeline_name="workflow",
                module_name="ndvi_daily",
                task_type="workflow",
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

            with (
                patch(
                    "modules.ndvi.load_ndvi_stack",
                    return_value=(ndvi_stack, observation_dates),
                ),
                patch(
                    "modules.ndvi.process_ndvi_stack_to_daily",
                    return_value=(daily_stack, daily_dates),
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertEqual(product_types.count("daily_ndvi_mat"), 5)
            self.assertEqual(product_types.count("ndvi_yearly_qa_mat"), 3)
            self.assertIn("ndvi_multi_year_qa_mat", product_types)
            self.assertEqual(manifest_payload["extra"]["module_name"], "ndvi_daily")
            self.assertEqual(manifest_payload["extra"]["count"], 5)
            self.assertTrue((quality_dir / "VI_v_qa.mat").exists())

    def test_run_job_executes_native_ndvi_module_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "ndvi_16day_prepared"
            output_dir = workspace / "daily_prepared"
            quality_dir = workspace / "quality_prepared"
            input_dir.mkdir()
            quality_dir.mkdir()
            request = JobRequest(
                job_id="job-native-ndvi-prepared",
                pipeline_name="workflow",
                module_name="ndvi_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "NDVI_16DAY_RASTER": {
                            "selector": {"uris": [str(input_dir)]},
                        }
                    }
                },
                algorithm_params={"emit_quality_products": False},
                output_spec=OutputSpec(
                    extra={
                        "output_dir": str(output_dir),
                        "quality_output_dir": str(quality_dir),
                    }
                ),
            )

            observation_dates = [datetime(2020, 1, 1)]
            daily_dates = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
            daily_stack = np.stack(
                [
                    np.array([[0.1, 0.2]], dtype=np.float64),
                    np.array([[0.3, 0.4]], dtype=np.float64),
                ],
                axis=2,
            )
            ndvi_stack = np.stack([np.array([[0.15, 0.25]], dtype=np.float64)], axis=2)

            def fake_load_ndvi_stack(*, input_dir, start_time, end_time):
                _ = (start_time, end_time)
                self.assertEqual(Path(input_dir), expected_input_dir)
                return ndvi_stack, observation_dates

            expected_input_dir = input_dir
            with (
                patch("modules.ndvi.load_ndvi_stack", side_effect=fake_load_ndvi_stack),
                patch(
                    "modules.ndvi.process_ndvi_stack_to_daily",
                    return_value=(daily_stack, daily_dates),
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertEqual(product_types.count("daily_ndvi_mat"), 2)
            self.assertEqual(manifest_payload["extra"]["module_name"], "ndvi_daily")
            self.assertEqual(manifest_payload["extra"]["count"], 2)

    def test_run_job_executes_ndvi_pipeline_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "ndvi_16day_pipeline_prepared"
            clim_dir = workspace / "ndvi_clim_pipeline_prepared"
            output_dir = workspace / "daily_pipeline_prepared"
            quality_dir = workspace / "quality_pipeline_prepared"
            input_dir.mkdir()
            clim_dir.mkdir()
            quality_dir.mkdir()
            request = JobRequest(
                job_id="job-pipeline-ndvi-prepared",
                pipeline_name="ndvi_daily_pipeline",
                task_type="ndvi_daily",
                time_range=TimeRange(
                    start=datetime(2020, 6, 1), end=datetime(2020, 6, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "NDVI_16DAY_RASTER": {"selector": {"uris": [str(input_dir)]}},
                        "ndvi_clim_dir": {"selector": {"uris": [str(clim_dir)]}},
                    }
                },
                algorithm_params={"emit_quality_products": True},
                output_spec=OutputSpec(
                    extra={
                        "output_dir": str(output_dir),
                        "quality_output_dir": str(quality_dir),
                    }
                ),
            )

            observation_dates = [datetime(2020, 6, 1)]
            daily_dates = [datetime(2020, 6, 1)]
            daily_stack = np.stack([np.array([[0.1, 0.2]], dtype=np.float64)], axis=2)
            ndvi_stack = np.stack([np.array([[0.15, 0.25]], dtype=np.float64)], axis=2)

            def fake_load_ndvi_stack(*, input_dir, start_time, end_time):
                _ = (start_time, end_time)
                self.assertEqual(Path(input_dir), expected_input_dir)
                return ndvi_stack, observation_dates

            def fake_load_daily_climatology_stack(input_dir, dates):
                self.assertEqual(Path(input_dir), expected_clim_dir)
                self.assertEqual(dates, daily_dates)
                return np.stack([np.array([[0.05, 0.06]], dtype=np.float64)], axis=2)

            expected_input_dir = input_dir
            expected_clim_dir = clim_dir
            with (
                patch(
                    "pipelines.ndvi_products.load_ndvi_stack",
                    side_effect=fake_load_ndvi_stack,
                ),
                patch(
                    "pipelines.ndvi_products.process_ndvi_stack_to_daily",
                    return_value=(daily_stack, daily_dates),
                ),
                patch(
                    "pipelines.ndvi_products._load_daily_climatology_stack",
                    side_effect=fake_load_daily_climatology_stack,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("daily_ndvi_mat", product_types)
            self.assertIn("ndvi_yearly_qa_mat", product_types)
            self.assertIn("ndvi_multi_year_qa_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "ndvi_daily_pipeline"
            )

    def test_run_job_executes_native_smap_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "smap_h5"
            output_dir = workspace / "smap_daily"
            input_dir.mkdir()
            request = JobRequest(
                job_id="job-native-smap",
                pipeline_name="workflow",
                module_name="smap_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir)},
                algorithm_params={},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_outputs = [output_dir / "20200101.mat", output_dir / "20200102.mat"]

            def fake_convert(*, input_dir, output_dir, start_time, end_time):
                _ = (input_dir, start_time, end_time)
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in fake_outputs:
                    path.write_bytes(b"MAT")
                return fake_outputs

            with patch(
                "modules.smap.convert_smap_l3_directory_to_mat",
                side_effect=fake_convert,
            ) as converter:
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            converter.assert_called_once()
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest_payload["products"]), 2)
            self.assertEqual(manifest_payload["products"][0]["type"], "smap_daily_mat")
            self.assertEqual(
                manifest_payload["products"][0]["tags"]["date_key"], "20200101"
            )
            self.assertEqual(manifest_payload["extra"]["module_name"], "smap_daily")
            self.assertEqual(manifest_payload["extra"]["count"], 2)
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_executes_native_smap_module_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "smap_h5_prepared"
            output_dir = workspace / "smap_daily_prepared"
            input_dir.mkdir()
            request = JobRequest(
                job_id="job-native-smap-prepared",
                pipeline_name="workflow",
                module_name="smap_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "SMAP_SPL3SMP_E": {
                            "selector": {"uris": [str(input_dir)]},
                            "accepted_formats": [],
                        }
                    }
                },
                algorithm_params={},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_outputs = [output_dir / "20200101.mat", output_dir / "20200102.mat"]

            def fake_convert(*, input_dir, output_dir, start_time, end_time):
                _ = (start_time, end_time)
                self.assertEqual(Path(input_dir), input_dir_path)
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in fake_outputs:
                    path.write_bytes(b"MAT")
                return fake_outputs

            input_dir_path = input_dir
            with patch(
                "modules.smap.convert_smap_l3_directory_to_mat",
                side_effect=fake_convert,
            ) as converter:
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            converter.assert_called_once()
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest_payload["products"]), 2)
            self.assertEqual(manifest_payload["products"][0]["type"], "smap_daily_mat")
            self.assertEqual(manifest_payload["extra"]["module_name"], "smap_daily")
            self.assertEqual(manifest_payload["extra"]["count"], 2)
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_executes_smap_pipeline_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "smap_pipeline_prepared"
            output_dir = workspace / "smap_pipeline_daily"
            input_dir.mkdir()
            request = JobRequest(
                job_id="job-pipeline-smap-prepared",
                pipeline_name="smap_daily_pipeline",
                task_type="smap_daily",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "SMAP_SPL3SMP_E": {
                            "selector": {"uris": [str(input_dir)]},
                        }
                    }
                },
                algorithm_params={},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_outputs = [output_dir / "20200101.mat", output_dir / "20200102.mat"]

            def fake_convert(*, input_dir, output_dir, start_time, end_time):
                _ = (start_time, end_time)
                self.assertEqual(Path(input_dir), expected_input_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                for path in fake_outputs:
                    path.write_bytes(b"MAT")
                return fake_outputs

            expected_input_dir = input_dir
            with patch(
                "pipelines.smap_products.convert_smap_l3_directory_to_mat",
                side_effect=fake_convert,
            ) as converter:
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            converter.assert_called_once()
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest_payload["products"]), 2)
            self.assertEqual(manifest_payload["products"][0]["type"], "smap_daily_mat")
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "smap_daily_pipeline"
            )
            self.assertEqual(manifest_payload["extra"]["count"], 2)
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_executes_native_timeseries_bundle_module_from_prepared_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            ancillary_root = workspace / "ancillary_root_timeseries"
            ancillary_root.mkdir()
            request = JobRequest(
                job_id="job-native-timeseries-prepared",
                pipeline_name="workflow",
                module_name="timeseries_bundle",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "anc_root": {
                            "selector": {"uris": [str(ancillary_root)]},
                        }
                    }
                },
                algorithm_params={},
                output_spec=OutputSpec(
                    extra={"output_dir": str(workspace / "timeseries_prepared")}
                ),
            )

            fake_bundle = SimpleNamespace(
                data={"TBv_mat": np.array([[1.0], [2.0]], dtype=np.float64)},
                date_keys=["20200101", "20200102"],
                missing_dates=["20200103"],
                pixel_count=1,
            )

            def fake_build_timeseries_bundle_from_range(
                start_time, end_time, config, datasource_selection, *, lin_pix=None
            ):
                _ = (start_time, end_time, config, lin_pix)
                self.assertEqual(
                    datasource_selection["anc_root"], str(expected_anc_root)
                )
                return fake_bundle

            expected_anc_root = ancillary_root
            with (
                patch("modules.bundles.load_lin_pix_selection", return_value=None),
                patch(
                    "modules.bundles.build_timeseries_bundle_from_range",
                    side_effect=fake_build_timeseries_bundle_from_range,
                ) as builder,
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            builder.assert_called_once()
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest_payload["products"][0]["type"], "timeseries_bundle_mat"
            )
            self.assertEqual(
                manifest_payload["extra"]["module_name"], "timeseries_bundle"
            )
            self.assertEqual(manifest_payload["extra"]["pixel_count"], 1)

    def test_run_job_executes_timeseries_bundle_pipeline_from_prepared_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            ancillary_root = workspace / "ancillary_root_timeseries_pipeline"
            daily_root = workspace / "daily_sources_timeseries_pipeline"
            ancillary_root.mkdir()
            daily_root.mkdir()
            request = JobRequest(
                job_id="job-pipeline-timeseries-prepared",
                pipeline_name="timeseries_bundle_pipeline",
                task_type="timeseries_bundle",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "ancillary_mat": {"selector": {"uris": [str(ancillary_root)]}},
                        "daily_mat_sources": {"selector": {"uris": [str(daily_root)]}},
                    }
                },
                algorithm_params={},
                output_spec=OutputSpec(
                    extra={
                        "output_dir": str(workspace / "timeseries_pipeline_prepared")
                    }
                ),
            )

            fake_bundle = SimpleNamespace(
                data={"TBv_mat": np.array([[1.0], [2.0]], dtype=np.float64)},
                date_keys=["20200101", "20200102"],
                missing_dates=["20200103"],
                pixel_count=1,
            )

            def fake_build_timeseries_bundle_from_range(
                start_time, end_time, config, datasource_selection, *, lin_pix=None
            ):
                _ = (start_time, end_time, config, lin_pix)
                self.assertEqual(
                    datasource_selection["anc_root"], str(expected_anc_root)
                )
                self.assertEqual(
                    datasource_selection["smap_folder"], str(expected_daily_root)
                )
                self.assertEqual(
                    datasource_selection["ndvi_folder"], str(expected_daily_root)
                )
                return fake_bundle

            expected_anc_root = ancillary_root
            expected_daily_root = daily_root
            with (
                patch(
                    "pipelines.timeseries_bundle_products.load_lin_pix_selection",
                    return_value=None,
                ),
                patch(
                    "pipelines.timeseries_bundle_products.build_timeseries_bundle_from_range",
                    side_effect=fake_build_timeseries_bundle_from_range,
                ) as builder,
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            builder.assert_called_once()
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest_payload["products"][0]["type"], "timeseries_bundle_mat"
            )
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "timeseries_bundle_pipeline"
            )
            self.assertEqual(manifest_payload["extra"]["pixel_count"], 1)

    def test_timeseries_bundle_pipeline_execute_uses_matching_multi_resource_prepared_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            logger = _RecordingLogger()
            ancillary_root = workspace / "ancillary_root_timeseries_multi"
            smap_root = workspace / "smap_root_timeseries_multi"
            ndvi_root = workspace / "ndvi_root_timeseries_multi"
            ancillary_root.mkdir()
            smap_root.mkdir()
            ndvi_root.mkdir()
            request = JobRequest(
                job_id="job-pipeline-timeseries-multi-prepared",
                pipeline_name="timeseries_bundle_pipeline",
                task_type="timeseries_bundle",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_prepared_inputs": {
                        "ancillary_mat": {
                            "materialized_resources": [
                                {
                                    "local_path": str(ancillary_root),
                                    "source_kind": "local_dir",
                                },
                            ]
                        },
                        "daily_mat_sources": {
                            "materialized_resources": [
                                {
                                    "local_path": str(smap_root),
                                    "source_kind": "local_dir",
                                    "metadata": {"role": "smap_folder"},
                                },
                                {
                                    "local_path": str(ndvi_root),
                                    "source_kind": "local_dir",
                                    "metadata": {"role": "ndvi_folder"},
                                },
                            ]
                        },
                    }
                },
                algorithm_params={},
                output_spec=OutputSpec(
                    extra={
                        "output_dir": str(
                            workspace / "timeseries_pipeline_multi_prepared"
                        )
                    }
                ),
            )
            ctx = RuntimeContext(
                job_id=request.job_id,
                run_id="run-timeseries-multi-prepared",
                workspace=workspace,
                tmp_dir=workspace / "tmp",
                cache_dir=workspace / "cache",
            )

            fake_bundle = SimpleNamespace(
                data={"TBv_mat": np.array([[1.0], [2.0]], dtype=np.float64)},
                date_keys=["20200101", "20200102"],
                missing_dates=["20200103"],
                pixel_count=1,
            )

            def fake_build_timeseries_bundle_from_range(
                start_time, end_time, config, datasource_selection, *, lin_pix=None
            ):
                _ = (start_time, end_time, config, lin_pix)
                self.assertEqual(datasource_selection["anc_root"], str(ancillary_root))
                self.assertEqual(datasource_selection["smap_folder"], str(smap_root))
                self.assertEqual(datasource_selection["ndvi_folder"], str(ndvi_root))
                return fake_bundle

            pipeline = TimeSeriesBundlePipeline(logger_adapter=logger)
            with (
                patch(
                    "pipelines.timeseries_bundle_products.load_lin_pix_selection",
                    return_value=None,
                ),
                patch(
                    "pipelines.timeseries_bundle_products.build_timeseries_bundle_from_range",
                    side_effect=fake_build_timeseries_bundle_from_range,
                ) as builder,
            ):
                manifest = pipeline.execute(request, ctx)

            builder.assert_called_once()
            self.assertEqual(manifest.products[0].type, "timeseries_bundle_mat")
            self.assertEqual(
                manifest.extra["pipeline_name"], "timeseries_bundle_pipeline"
            )
            self.assertEqual(manifest.extra["pixel_count"], 1)

    def test_run_job_executes_native_station_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "station"
            input_dir.mkdir()
            request = JobRequest(
                job_id="job-native-station",
                pipeline_name="workflow",
                module_name="station_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir)},
                algorithm_params={
                    "source_type": "ISMN",
                    "emit_validation_products": False,
                },
                output_spec=OutputSpec(
                    extra={"output_dir": str(workspace / "station_daily")}
                ),
            )

            records = [
                StationRecord(
                    year=2020,
                    month=1,
                    day=1,
                    hour=6,
                    lat=10.0,
                    lon=100.0,
                    elev=50.0,
                    depth_upper=0.0,
                    depth_lower=0.05,
                    soil_moisture=0.2,
                    quality_flag=1,
                    site_id="site_a",
                    source="ISMN",
                ),
                StationRecord(
                    year=2020,
                    month=1,
                    day=2,
                    hour=6,
                    lat=10.0,
                    lon=100.0,
                    elev=50.0,
                    depth_upper=0.0,
                    depth_lower=0.05,
                    soil_moisture=0.25,
                    quality_flag=1,
                    site_id="site_a",
                    source="ISMN",
                ),
            ]

            fake_file = input_dir / "site_a.stm"
            fake_file.write_text("dummy", encoding="utf-8")

            with (
                patch(
                    "modules.station.discover_ismn_stm_files", return_value=[fake_file]
                ),
                patch(
                    "modules.station.parse_ismn_stm_file",
                    return_value=records,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("station_daily_mat", product_types)
            self.assertIn("station_am6_mat", product_types)
            self.assertEqual(manifest_payload["extra"]["module_name"], "station_daily")
            self.assertEqual(manifest_payload["extra"]["source_type"], "ISMN")
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_executes_native_station_module_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "station_prepared"
            output_dir = workspace / "station_daily_prepared"
            site_info_csv = workspace / "site_info_prepared.csv"
            smap_grid_mat = workspace / "smap_grid_prepared.mat"
            landcover_mat = workspace / "landcover_prepared.mat"
            climate_mat = workspace / "climate_prepared.mat"
            network_map_csv = workspace / "network_map_prepared.csv"
            input_dir.mkdir()
            site_info_csv.write_text("site_id,lat,lon\n", encoding="utf-8")
            smap_grid_mat.write_bytes(b"MAT")
            landcover_mat.write_bytes(b"MAT")
            climate_mat.write_bytes(b"MAT")
            network_map_csv.write_text(
                "site_id,network_id\nCOSMOS001,NET-A\n", encoding="utf-8"
            )
            request = JobRequest(
                job_id="job-native-station-prepared",
                pipeline_name="workflow",
                module_name="station_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "ISMN_STM_OR_CASMOS_TXT": {
                            "selector": {"uris": [str(input_dir)]}
                        },
                        "site_info_csv": {"selector": {"uris": [str(site_info_csv)]}},
                        "smap_grid_mat": {"selector": {"uris": [str(smap_grid_mat)]}},
                        "landcover_mat": {"selector": {"uris": [str(landcover_mat)]}},
                        "climate_mat": {"selector": {"uris": [str(climate_mat)]}},
                        "network_map_csv": {
                            "selector": {"uris": [str(network_map_csv)]}
                        },
                    }
                },
                algorithm_params={
                    "source_type": "CASMOS",
                    "emit_validation_products": True,
                    "validation_min_valid_days": 1,
                },
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

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
            ]
            fake_file = input_dir / "COSMOS001.txt"
            fake_file.write_text("dummy", encoding="utf-8")

            def fake_discover_casmos_txt_files(path):
                self.assertEqual(Path(path), expected_input_dir)
                return [fake_file]

            def fake_load_casmos_site_info(path):
                self.assertEqual(Path(path), expected_site_info_csv)
                return {"COSMOS001": {"name": "Prepared Site"}}

            def fake_parse_casmos_txt_file(path, *, site_info):
                self.assertEqual(Path(path), fake_file)
                self.assertIn("COSMOS001", site_info)
                return records

            def fake_load_mat_file(path):
                current_path = Path(path)
                if current_path == expected_smap_grid_mat:
                    return {
                        "lat_smap": np.array([35.0], dtype=np.float64),
                        "lon_smap": np.array([120.0], dtype=np.float64),
                        "IGBP_9km_12": np.array([5], dtype=np.int16),
                    }
                if current_path == expected_landcover_mat:
                    return {
                        "IGBP_9km_12": np.array([6], dtype=np.int16),
                        "lat_9km": np.array([35.0], dtype=np.float64),
                        "lon_9km": np.array([120.0], dtype=np.float64),
                    }
                if current_path == expected_climate_mat:
                    return {
                        "Koppen_present_083": np.array([3], dtype=np.int16),
                        "lat_kop": np.array([35.0], dtype=np.float64),
                        "lon_kop": np.array([120.0], dtype=np.float64),
                    }
                raise AssertionError(f"Unexpected MAT path: {current_path}")

            def fake_build_station_validation_outputs(
                records_by_site,
                validation_start,
                validation_end,
                *,
                smap_lat,
                smap_lon,
                min_valid_days,
                landcover_grid,
                landcover_lat,
                landcover_lon,
                climate_grid,
                climate_lat,
                climate_lon,
                smap_landcover_grid,
                network_map,
            ):
                _ = (records_by_site, validation_start, validation_end)
                self.assertEqual(min_valid_days, 1)
                self.assertEqual(network_map, {"COSMOS001": "NET-A"})
                self.assertIsNotNone(smap_lat)
                self.assertIsNotNone(smap_lon)
                self.assertIsNotNone(landcover_grid)
                self.assertIsNotNone(landcover_lat)
                self.assertIsNotNone(landcover_lon)
                self.assertIsNotNone(climate_grid)
                self.assertIsNotNone(climate_lat)
                self.assertIsNotNone(climate_lon)
                self.assertIsNotNone(smap_landcover_grid)
                return {"summary": {"count": np.array([1], dtype=np.int16)}}

            expected_input_dir = input_dir
            expected_site_info_csv = site_info_csv
            expected_smap_grid_mat = smap_grid_mat
            expected_landcover_mat = landcover_mat
            expected_climate_mat = climate_mat
            with (
                patch(
                    "modules.station.discover_casmos_txt_files",
                    side_effect=fake_discover_casmos_txt_files,
                ),
                patch(
                    "modules.station.load_casmos_site_info",
                    side_effect=fake_load_casmos_site_info,
                ),
                patch(
                    "modules.station.parse_casmos_txt_file",
                    side_effect=fake_parse_casmos_txt_file,
                ),
                patch(
                    "modules.station.load_mat_file",
                    side_effect=fake_load_mat_file,
                ),
                patch(
                    "modules.station.build_station_validation_outputs",
                    side_effect=fake_build_station_validation_outputs,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("station_daily_mat", product_types)
            self.assertIn("station_am6_mat", product_types)
            self.assertIn("station_summary_validation_mat", product_types)
            self.assertEqual(manifest_payload["extra"]["module_name"], "station_daily")
            self.assertEqual(manifest_payload["extra"]["source_type"], "CASMOS")
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_executes_station_pipeline_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "station_pipeline_prepared"
            output_dir = workspace / "station_pipeline_daily"
            site_info_csv = workspace / "site_info_pipeline.csv"
            smap_grid_mat = workspace / "smap_grid_pipeline.mat"
            landcover_mat = workspace / "landcover_pipeline.mat"
            climate_mat = workspace / "climate_pipeline.mat"
            network_map_csv = workspace / "network_map_pipeline.csv"
            input_dir.mkdir()
            site_info_csv.write_text("site_id,lat,lon\n", encoding="utf-8")
            smap_grid_mat.write_bytes(b"MAT")
            landcover_mat.write_bytes(b"MAT")
            climate_mat.write_bytes(b"MAT")
            network_map_csv.write_text(
                "site_id,network_id\nCOSMOS001,NET-B\n", encoding="utf-8"
            )
            request = JobRequest(
                job_id="job-pipeline-station-prepared",
                pipeline_name="station_daily_pipeline",
                task_type="station_daily",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "ISMN_STM_OR_CASMOS_TXT": {
                            "selector": {"uris": [str(input_dir)]}
                        },
                        "site_info_csv": {"selector": {"uris": [str(site_info_csv)]}},
                        "smap_grid_mat": {"selector": {"uris": [str(smap_grid_mat)]}},
                        "landcover_mat": {"selector": {"uris": [str(landcover_mat)]}},
                        "climate_mat": {"selector": {"uris": [str(climate_mat)]}},
                        "network_map_csv": {
                            "selector": {"uris": [str(network_map_csv)]}
                        },
                    }
                },
                algorithm_params={
                    "source_type": "CASMOS",
                    "emit_validation_products": True,
                    "validation_min_valid_days": 1,
                },
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

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
            ]
            fake_file = input_dir / "COSMOS001.txt"
            fake_file.write_text("dummy", encoding="utf-8")

            def fake_discover_casmos_txt_files(path):
                self.assertEqual(Path(path), expected_input_dir)
                return [fake_file]

            def fake_load_casmos_site_info(path):
                self.assertEqual(Path(path), expected_site_info_csv)
                return {"COSMOS001": {"name": "Prepared Site"}}

            def fake_parse_casmos_txt_file(path, *, site_info):
                self.assertEqual(Path(path), fake_file)
                self.assertIn("COSMOS001", site_info)
                return records

            def fake_load_mat_file(path):
                current_path = Path(path)
                if current_path == expected_smap_grid_mat:
                    return {
                        "lat_smap": np.array([35.0], dtype=np.float64),
                        "lon_smap": np.array([120.0], dtype=np.float64),
                        "IGBP_9km_12": np.array([5], dtype=np.int16),
                    }
                if current_path == expected_landcover_mat:
                    return {
                        "IGBP_9km_12": np.array([6], dtype=np.int16),
                        "lat_9km": np.array([35.0], dtype=np.float64),
                        "lon_9km": np.array([120.0], dtype=np.float64),
                    }
                if current_path == expected_climate_mat:
                    return {
                        "Koppen_present_083": np.array([3], dtype=np.int16),
                        "lat_kop": np.array([35.0], dtype=np.float64),
                        "lon_kop": np.array([120.0], dtype=np.float64),
                    }
                raise AssertionError(f"Unexpected MAT path: {current_path}")

            def fake_build_station_validation_outputs(
                records_by_site,
                validation_start,
                validation_end,
                *,
                smap_lat,
                smap_lon,
                min_valid_days,
                landcover_grid,
                landcover_lat,
                landcover_lon,
                climate_grid,
                climate_lat,
                climate_lon,
                smap_landcover_grid,
                network_map,
            ):
                _ = (records_by_site, validation_start, validation_end)
                self.assertEqual(min_valid_days, 1)
                self.assertEqual(network_map, {"COSMOS001": "NET-B"})
                self.assertIsNotNone(smap_lat)
                self.assertIsNotNone(smap_lon)
                self.assertIsNotNone(landcover_grid)
                self.assertIsNotNone(landcover_lat)
                self.assertIsNotNone(landcover_lon)
                self.assertIsNotNone(climate_grid)
                self.assertIsNotNone(climate_lat)
                self.assertIsNotNone(climate_lon)
                self.assertIsNotNone(smap_landcover_grid)
                return {"summary": {"count": np.array([1], dtype=np.int16)}}

            expected_input_dir = input_dir
            expected_site_info_csv = site_info_csv
            expected_smap_grid_mat = smap_grid_mat
            expected_landcover_mat = landcover_mat
            expected_climate_mat = climate_mat
            with (
                patch(
                    "pipelines.station_products.discover_casmos_txt_files",
                    side_effect=fake_discover_casmos_txt_files,
                ),
                patch(
                    "pipelines.station_products.load_casmos_site_info",
                    side_effect=fake_load_casmos_site_info,
                ),
                patch(
                    "pipelines.station_products.parse_casmos_txt_file",
                    side_effect=fake_parse_casmos_txt_file,
                ),
                patch(
                    "pipelines.station_products.load_mat_file",
                    side_effect=fake_load_mat_file,
                ),
                patch(
                    "pipelines.station_products.build_station_validation_outputs",
                    side_effect=fake_build_station_validation_outputs,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("station_daily_mat", product_types)
            self.assertIn("station_am6_mat", product_types)
            self.assertIn("station_summary_validation_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "station_daily_pipeline"
            )
            self.assertEqual(manifest_payload["extra"]["source_type"], "CASMOS")
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )

    def test_run_job_executes_native_fy_module_in_plan_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "fy_hdf"
            input_dir.mkdir()
            output_dir = workspace / "fy_daily"
            request = JobRequest(
                job_id="job-native-fy",
                pipeline_name="workflow",
                module_name="fy_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_dir": str(input_dir)},
                algorithm_params={"orbit_mode": "MWRID", "execute_commands": False},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            class _Plan:
                def __init__(
                    self,
                    date_key: str,
                    orbit_type: str,
                    satellite: str,
                    output_root: Path,
                ) -> None:
                    self.date_key = date_key
                    self.orbit_type = orbit_type
                    self.satellite = satellite
                    self.output_dir = str(output_root)
                    self.work_dir = str(output_root / "_work" / date_key)
                    self.output_prefix = (
                        f"{satellite}_GBAL_L1_10V10H_{date_key}_{orbit_type}"
                    )

            fake_plan = _Plan("20200101", "MWRID", "FY3D", output_dir)
            fake_plan_json = output_dir / "fy_daily_plan.json"
            fake_command_json = (
                output_dir / "_work" / "20200101" / "fy_daily_commands.json"
            )

            def fake_write_plan_json(plans, output_path):
                _ = plans
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("[]", encoding="utf-8")
                return output_path

            def fake_write_command_json(steps, output_path):
                _ = steps
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("[]", encoding="utf-8")
                return output_path

            with (
                patch("modules.fy.build_fy_daily_job_plans", return_value=[fake_plan]),
                patch(
                    "modules.fy.write_fy_daily_plan_json",
                    side_effect=fake_write_plan_json,
                ),
                patch(
                    "modules.fy.build_fy_daily_command_steps",
                    return_value=[],
                ),
                patch(
                    "modules.fy.write_fy_command_plan_json",
                    side_effect=fake_write_command_json,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("fy_daily_job_plan", product_types)
            self.assertIn("fy_daily_command_plan", product_types)
            self.assertEqual(manifest_payload["extra"]["module_name"], "fy_daily")
            self.assertEqual(manifest_payload["extra"]["artifact_mode"], "plan_only")
            self.assertEqual(manifest_payload["extra"]["plan_count"], 1)
            self.assertTrue(fake_plan_json.exists())
            self.assertTrue(fake_command_json.exists())

    def test_run_job_executes_native_fy_module_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "fy_hdf_prepared"
            input_dir.mkdir()
            output_dir = workspace / "fy_daily_prepared"
            request = JobRequest(
                job_id="job-native-fy-prepared",
                pipeline_name="workflow",
                module_name="fy_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "FY_MWRI_HDF": {
                            "selector": {"uris": [str(input_dir)]},
                        }
                    }
                },
                algorithm_params={"orbit_mode": "MWRID", "execute_commands": False},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            class _Plan:
                def __init__(
                    self,
                    date_key: str,
                    orbit_type: str,
                    satellite: str,
                    output_root: Path,
                ) -> None:
                    self.date_key = date_key
                    self.orbit_type = orbit_type
                    self.satellite = satellite
                    self.output_dir = str(output_root)
                    self.work_dir = str(output_root / "_work" / date_key)
                    self.output_prefix = (
                        f"{satellite}_GBAL_L1_10V10H_{date_key}_{orbit_type}"
                    )

            fake_plan = _Plan("20200101", "MWRID", "FY3D", output_dir)
            fake_plan_json = output_dir / "fy_daily_plan.json"
            fake_command_json = (
                output_dir / "_work" / "20200101" / "fy_daily_commands.json"
            )

            def fake_build_fy_daily_job_plans(
                *, input_dir, output_root, start_time, end_time, orbit_mode
            ):
                _ = (output_root, start_time, end_time)
                self.assertEqual(Path(input_dir), expected_input_dir)
                self.assertEqual(orbit_mode, "MWRID")
                return [fake_plan]

            def fake_write_plan_json(plans, output_path):
                _ = plans
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("[]", encoding="utf-8")
                return output_path

            def fake_write_command_json(steps, output_path):
                _ = steps
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("[]", encoding="utf-8")
                return output_path

            expected_input_dir = input_dir
            with (
                patch(
                    "modules.fy.build_fy_daily_job_plans",
                    side_effect=fake_build_fy_daily_job_plans,
                ),
                patch(
                    "modules.fy.write_fy_daily_plan_json",
                    side_effect=fake_write_plan_json,
                ),
                patch(
                    "modules.fy.build_fy_daily_command_steps",
                    return_value=[],
                ),
                patch(
                    "modules.fy.write_fy_command_plan_json",
                    side_effect=fake_write_command_json,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("fy_daily_job_plan", product_types)
            self.assertIn("fy_daily_command_plan", product_types)
            self.assertEqual(manifest_payload["extra"]["module_name"], "fy_daily")
            self.assertEqual(manifest_payload["extra"]["artifact_mode"], "plan_only")
            self.assertEqual(manifest_payload["extra"]["plan_count"], 1)
            self.assertTrue(fake_plan_json.exists())
            self.assertTrue(fake_command_json.exists())

    def test_run_job_executes_fy_pipeline_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_dir = workspace / "fy_hdf_pipeline_prepared"
            input_dir.mkdir()
            output_dir = workspace / "fy_daily_pipeline_prepared"
            request = JobRequest(
                job_id="job-pipeline-fy-prepared",
                pipeline_name="fy_daily_pipeline",
                task_type="fy_daily",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "FY_MWRI_HDF": {
                            "selector": {"uris": [str(input_dir)]},
                        }
                    }
                },
                algorithm_params={"orbit_mode": "MWRID", "execute_commands": False},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            class _Plan:
                def __init__(
                    self,
                    date_key: str,
                    orbit_type: str,
                    satellite: str,
                    output_root: Path,
                ) -> None:
                    self.date_key = date_key
                    self.orbit_type = orbit_type
                    self.satellite = satellite
                    self.output_dir = str(output_root)
                    self.work_dir = str(output_root / "_work" / date_key)
                    self.output_prefix = (
                        f"{satellite}_GBAL_L1_10V10H_{date_key}_{orbit_type}"
                    )

            fake_plan = _Plan("20200101", "MWRID", "FY3D", output_dir)
            fake_plan_json = output_dir / "fy_daily_plan.json"
            fake_command_json = (
                output_dir / "_work" / "20200101" / "fy_daily_commands.json"
            )

            def fake_build_fy_daily_job_plans(
                *, input_dir, output_root, start_time, end_time, orbit_mode
            ):
                _ = (output_root, start_time, end_time)
                self.assertEqual(Path(input_dir), expected_input_dir)
                self.assertEqual(orbit_mode, "MWRID")
                return [fake_plan]

            def fake_write_plan_json(plans, output_path):
                _ = plans
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("[]", encoding="utf-8")
                return output_path

            def fake_write_command_json(steps, output_path):
                _ = steps
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text("[]", encoding="utf-8")
                return output_path

            expected_input_dir = input_dir
            with (
                patch(
                    "pipelines.fy_products.build_fy_daily_job_plans",
                    side_effect=fake_build_fy_daily_job_plans,
                ),
                patch(
                    "pipelines.fy_products.write_fy_daily_plan_json",
                    side_effect=fake_write_plan_json,
                ),
                patch(
                    "pipelines.fy_products.build_fy_daily_command_steps",
                    return_value=[],
                ),
                patch(
                    "pipelines.fy_products.write_fy_command_plan_json",
                    side_effect=fake_write_command_json,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("fy_daily_job_plan", product_types)
            self.assertIn("fy_daily_command_plan", product_types)
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "fy_daily_pipeline"
            )
            self.assertEqual(manifest_payload["extra"]["artifact_mode"], "plan_only")
            self.assertEqual(manifest_payload["extra"]["plan_count"], 1)
            self.assertTrue(fake_plan_json.exists())
            self.assertTrue(fake_command_json.exists())

    def test_run_job_executes_native_inversion_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "daily_bundle.mat"
            input_mat.write_bytes(b"MAT")
            output_dir = workspace / "inversion_daily"
            request = JobRequest(
                job_id="job-native-inversion",
                pipeline_name="workflow",
                module_name="inversion_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={"input_mat": str(input_mat)},
                algorithm_params={"mode": "ddca", "freq_ghz": 1.4},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            payload = {"TBv": np.array([[250.0]]), "TBh": np.array([[240.0]])}
            ddca_inputs = {
                "tbv": np.array([[250.0]], dtype=np.float64),
                "tbh": np.array([[240.0]], dtype=np.float64),
                "ts": np.array([[300.0]], dtype=np.float64),
                "tau_ini": np.array([[0.5]], dtype=np.float64),
                "h_value": np.array([[0.1]], dtype=np.float64),
                "clay_fraction": np.array([[0.3]], dtype=np.float64),
                "albedo": np.array([[0.05]], dtype=np.float64),
                "porosity": np.array([[0.45]], dtype=np.float64),
                "theta_deg": np.array([[40.0]], dtype=np.float64),
            }

            with (
                patch("modules.inversion.load_mat_file", return_value=payload),
                patch(
                    "modules.inversion.extract_ddca_inputs",
                    return_value=ddca_inputs,
                ),
                patch(
                    "algorithms.inversion.ddca_retrieve_grid",
                    return_value=(
                        np.array([[0.21]], dtype=np.float64),
                        np.array([[0.87]], dtype=np.float64),
                    ),
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("sm_mat", product_types)
            self.assertIn("vod_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["module_name"], "inversion_daily"
            )
            self.assertEqual(manifest_payload["extra"]["mode"], "ddca")
            self.assertTrue(Path(manifest_payload["extra"]["output_path"]).exists())

    def test_run_job_executes_native_inversion_module_from_prepared_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "daily_bundle_prepared.mat"
            input_mat.write_bytes(b"MAT")
            output_dir = workspace / "inversion_daily_prepared"
            request = JobRequest(
                job_id="job-native-inversion-prepared",
                pipeline_name="workflow",
                module_name="inversion_daily",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "daily_bundle_mat": {
                            "selector": {"uris": [str(input_mat)]},
                        }
                    }
                },
                algorithm_params={"mode": "ddca", "freq_ghz": 1.4},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            payload = {"TBv": np.array([[250.0]]), "TBh": np.array([[240.0]])}
            ddca_inputs = {
                "tbv": np.array([[250.0]], dtype=np.float64),
                "tbh": np.array([[240.0]], dtype=np.float64),
                "ts": np.array([[300.0]], dtype=np.float64),
                "tau_ini": np.array([[0.5]], dtype=np.float64),
                "h_value": np.array([[0.1]], dtype=np.float64),
                "clay_fraction": np.array([[0.3]], dtype=np.float64),
                "albedo": np.array([[0.05]], dtype=np.float64),
                "porosity": np.array([[0.45]], dtype=np.float64),
                "theta_deg": np.array([[40.0]], dtype=np.float64),
            }

            def fake_load_mat_file(path):
                self.assertEqual(Path(path), expected_input_mat)
                return payload

            expected_input_mat = input_mat
            with (
                patch(
                    "modules.inversion.load_mat_file", side_effect=fake_load_mat_file
                ),
                patch(
                    "modules.inversion.extract_ddca_inputs",
                    return_value=ddca_inputs,
                ),
                patch(
                    "algorithms.inversion.ddca_retrieve_grid",
                    return_value=(
                        np.array([[0.21]], dtype=np.float64),
                        np.array([[0.87]], dtype=np.float64),
                    ),
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("sm_mat", product_types)
            self.assertIn("vod_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["module_name"], "inversion_daily"
            )
            self.assertEqual(manifest_payload["extra"]["mode"], "ddca")

    def test_run_job_executes_inversion_pipeline_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "daily_bundle_pipeline_prepared.mat"
            input_mat.write_bytes(b"MAT")
            output_dir = workspace / "inversion_pipeline_prepared"
            request = JobRequest(
                job_id="job-pipeline-inversion-prepared",
                pipeline_name="inversion_daily_pipeline",
                task_type="inversion_daily",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 1)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "daily_bundle_mat": {
                            "selector": {"uris": [str(input_mat)]},
                        }
                    }
                },
                algorithm_params={"mode": "dh", "freq_ghz": 1.4},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            payload = {"TBv": np.array([[250.0]]), "TBh": np.array([[240.0]])}
            dh_inputs = {
                "tbv": np.array([[250.0]], dtype=np.float64),
                "tbh": np.array([[240.0]], dtype=np.float64),
                "ts": np.array([[300.0]], dtype=np.float64),
                "tau_ini": np.array([[0.5]], dtype=np.float64),
                "clay_fraction": np.array([[0.3]], dtype=np.float64),
                "albedo": np.array([[0.05]], dtype=np.float64),
                "porosity": np.array([[0.45]], dtype=np.float64),
                "theta_deg": np.array([[40.0]], dtype=np.float64),
            }

            def fake_load_mat_file(path):
                self.assertEqual(Path(path), expected_input_mat)
                return payload

            expected_input_mat = input_mat
            with (
                patch(
                    "pipelines.inversion_products.load_mat_file",
                    side_effect=fake_load_mat_file,
                ),
                patch(
                    "pipelines.inversion_products.extract_inversion_inputs",
                    return_value=dh_inputs,
                ),
                patch(
                    "algorithms.inversion.retrieve_dynamic_h_grid",
                    return_value=np.array([[0.11]], dtype=np.float64),
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("dh_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "inversion_daily_pipeline"
            )
            self.assertEqual(manifest_payload["extra"]["mode"], "dh")

    def test_run_job_executes_native_block_inversion_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "timeseries_bundle.mat"
            input_mat.write_bytes(b"MAT")
            output_dir = workspace / "block_inversion"
            request = JobRequest(
                job_id="job-native-block",
                pipeline_name="workflow",
                module_name="block_inversion",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "input_mat": str(input_mat),
                    "dh_mat": str(input_mat),
                },
                algorithm_params={"mode": "ddca", "write_daily_files": True},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_result = {
                "date_keys": ["20200101", "20200102"],
                "missing_dates": ["20200103"],
                "Tau_ini_mat": np.array([[0.5, 0.6], [0.7, 0.8]], dtype=np.float64),
                "SM_mat": np.array([[0.2, 0.25], [0.3, 0.35]], dtype=np.float64),
                "VOD_mat": np.array([[1.1, 1.2], [1.3, 1.4]], dtype=np.float64),
                "H_used_mat": np.array([[0.15, 0.16], [0.17, 0.18]], dtype=np.float64),
            }

            with (
                patch(
                    "modules.block_inversion.load_mat_file",
                    return_value={"date_keys": fake_result["date_keys"]},
                ),
                patch(
                    "algorithms.block_inversion.build_block_field_config",
                    return_value=object(),
                ),
                patch(
                    "algorithms.block_inversion.execute_block_inversion",
                    return_value=fake_result,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("tau_block_mat", product_types)
            self.assertIn("sm_vod_block_mat", product_types)
            self.assertIn("sm_daily_mat", product_types)
            self.assertIn("vod_daily_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["module_name"], "block_inversion"
            )
            self.assertEqual(manifest_payload["extra"]["mode"], "ddca")
            self.assertEqual(manifest_payload["extra"]["missing_dates"], ["20200103"])

    def test_run_job_executes_native_block_inversion_module_from_prepared_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "timeseries_bundle_prepared.mat"
            dh_mat = workspace / "dh_prepared.mat"
            input_mat.write_bytes(b"MAT")
            dh_mat.write_bytes(b"MAT")
            output_dir = workspace / "block_inversion_prepared"
            request = JobRequest(
                job_id="job-native-block-prepared",
                pipeline_name="workflow",
                module_name="block_inversion",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "timeseries_bundle_mat": {
                            "selector": {"uris": [str(input_mat)]}
                        },
                        "dh_mat": {"selector": {"uris": [str(dh_mat)]}},
                    }
                },
                algorithm_params={"mode": "dh", "write_daily_files": True},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_result = {
                "date_keys": ["20200101", "20200102"],
                "missing_dates": [],
                "Tau_ini_mat": np.array([[0.5, 0.6], [0.7, 0.8]], dtype=np.float64),
                "DH_mat": np.array([[0.12, 0.13], [0.14, 0.15]], dtype=np.float64),
            }

            def fake_load_mat_file(path):
                self.assertEqual(Path(path), expected_input_mat)
                return {"date_keys": fake_result["date_keys"]}

            def fake_execute_block_inversion(
                payload, *, mode, freq_ghz, pixel_chunk_size, dh_mat_path, field_config
            ):
                _ = (payload, freq_ghz, pixel_chunk_size, field_config)
                self.assertEqual(mode, "dh")
                self.assertEqual(Path(str(dh_mat_path)), expected_dh_mat)
                return fake_result

            expected_input_mat = input_mat
            expected_dh_mat = dh_mat
            with (
                patch(
                    "modules.block_inversion.load_mat_file",
                    side_effect=fake_load_mat_file,
                ),
                patch(
                    "algorithms.block_inversion.build_block_field_config",
                    return_value=object(),
                ),
                patch(
                    "algorithms.block_inversion.execute_block_inversion",
                    side_effect=fake_execute_block_inversion,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("tau_block_mat", product_types)
            self.assertIn("dh_block_mat", product_types)
            self.assertIn("dh_daily_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["module_name"], "block_inversion"
            )
            self.assertEqual(manifest_payload["extra"]["mode"], "dh")

    def test_run_job_executes_block_inversion_pipeline_from_prepared_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "timeseries_bundle_pipeline_prepared.mat"
            dh_mat = workspace / "dh_pipeline_prepared.mat"
            input_mat.write_bytes(b"MAT")
            dh_mat.write_bytes(b"MAT")
            output_dir = workspace / "block_inversion_pipeline_prepared"
            request = JobRequest(
                job_id="job-pipeline-block-prepared",
                pipeline_name="block_inversion_pipeline",
                task_type="block_inversion",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "timeseries_bundle_mat": {
                            "selector": {"uris": [str(input_mat)]}
                        },
                        "dh_mat": {"selector": {"uris": [str(dh_mat)]}},
                    }
                },
                algorithm_params={"mode": "dh", "write_daily_files": True},
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_result = {
                "date_keys": ["20200101", "20200102"],
                "missing_dates": [],
                "Tau_ini_mat": np.array([[0.5, 0.6], [0.7, 0.8]], dtype=np.float64),
                "DH_mat": np.array([[0.12, 0.13], [0.14, 0.15]], dtype=np.float64),
            }

            def fake_load_mat_file(path):
                self.assertEqual(Path(path), expected_input_mat)
                return {"date_keys": fake_result["date_keys"]}

            def fake_execute_block_inversion(
                payload, *, mode, freq_ghz, pixel_chunk_size, dh_mat_path, field_config
            ):
                _ = (payload, freq_ghz, pixel_chunk_size, field_config)
                self.assertEqual(mode, "dh")
                self.assertEqual(Path(str(dh_mat_path)), expected_dh_mat)
                return fake_result

            expected_input_mat = input_mat
            expected_dh_mat = dh_mat
            with (
                patch(
                    "pipelines.block_inversion_products.load_mat_file",
                    side_effect=fake_load_mat_file,
                ),
                patch(
                    "algorithms.block_inversion.build_block_field_config",
                    return_value=object(),
                ),
                patch(
                    "algorithms.block_inversion.execute_block_inversion",
                    side_effect=fake_execute_block_inversion,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("tau_block_mat", product_types)
            self.assertIn("dh_block_mat", product_types)
            self.assertIn("dh_daily_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "block_inversion_pipeline"
            )
            self.assertEqual(manifest_payload["extra"]["mode"], "dh")

    def test_run_job_executes_native_omega_block_module_from_prepared_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "timeseries_bundle_omega_prepared.mat"
            omega_fixed_mat = workspace / "omega_fixed_prepared.mat"
            exp0_calib_mat = workspace / "exp0_calib_prepared.mat"
            input_mat.write_bytes(b"MAT")
            omega_fixed_mat.write_bytes(b"MAT")
            exp0_calib_mat.write_bytes(b"MAT")
            output_dir = workspace / "omega_block_prepared"
            request = JobRequest(
                job_id="job-native-omega-prepared",
                pipeline_name="workflow",
                module_name="omega_block",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "timeseries_bundle_mat": {
                            "selector": {"uris": [str(input_mat)]}
                        },
                        "omega_fixed_mat": {
                            "selector": {"uris": [str(omega_fixed_mat)]}
                        },
                        "exp0_calib_mat": {"selector": {"uris": [str(exp0_calib_mat)]}},
                    }
                },
                algorithm_params={
                    "write_daily_files": True,
                    "temp_scheme": "DUAL",
                    "exp_mode": "Exp2",
                    "block_days": 8,
                },
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_result = {
                "date_keys": ["20200101", "20200102"],
                "OMEGA_mat": np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float64),
                "SM_RET_mat": np.array([[0.2, 0.25], [0.3, 0.35]], dtype=np.float64),
                "VOD_RET_mat": np.array([[1.1, 1.2], [1.3, 1.4]], dtype=np.float64),
                "Tau_star_mat": np.array([[0.5, 0.6], [0.7, 0.8]], dtype=np.float64),
                "qc_flag_mat": np.zeros((1, 2), dtype=np.uint8),
                "qc_condk_mat": np.array([[10.0, 12.0]], dtype=np.float64),
                "qc_sratio_mat": np.array([[0.1, 0.2]], dtype=np.float64),
            }

            def fake_load_mat_file(path):
                current_path = Path(path)
                if current_path == expected_input_mat:
                    return {
                        "date_keys": fake_result["date_keys"],
                        "TBv_mat": np.array([[1.0]]),
                    }
                if current_path == expected_omega_fixed_mat:
                    return {"omega_fixed_vec": np.array([0.12, 0.13], dtype=np.float64)}
                if current_path == expected_exp0_calib_mat:
                    return {
                        "h_exp0_vec": np.array([0.2, 0.21], dtype=np.float64),
                        "alpha_exp0_vec": np.array([0.17, 0.18], dtype=np.float64),
                    }
                raise AssertionError(f"Unexpected MAT path: {current_path}")

            def fake_execute(payload, *, config, field_config):
                self.assertIn("omega_fixed_vec", payload)
                self.assertIn("h_exp0_vec", payload)
                self.assertIn("alpha_exp0_vec", payload)
                self.assertEqual(config.temp_scheme, "DUAL")
                self.assertEqual(config.exp_mode, "Exp2")
                self.assertEqual(config.block_days, 8)
                self.assertIsNotNone(field_config)
                return fake_result

            expected_input_mat = input_mat
            expected_omega_fixed_mat = omega_fixed_mat
            expected_exp0_calib_mat = exp0_calib_mat
            with (
                patch("modules.omega.load_mat_file", side_effect=fake_load_mat_file),
                patch(
                    "algorithms.omega.execute_omega_retrieval",
                    side_effect=fake_execute,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("omega_block_mat", product_types)
            self.assertIn("omega_daily_mat", product_types)
            self.assertEqual(manifest_payload["extra"]["module_name"], "omega_block")
            self.assertEqual(manifest_payload["extra"]["temp_scheme"], "DUAL")
            self.assertEqual(manifest_payload["extra"]["exp_mode"], "Exp2")

    def test_run_job_executes_omega_block_pipeline_from_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "timeseries_bundle_omega_pipeline_prepared.mat"
            omega_fixed_mat = workspace / "omega_fixed_pipeline_prepared.mat"
            exp0_calib_mat = workspace / "exp0_calib_pipeline_prepared.mat"
            input_mat.write_bytes(b"MAT")
            omega_fixed_mat.write_bytes(b"MAT")
            exp0_calib_mat.write_bytes(b"MAT")
            output_dir = workspace / "omega_block_pipeline_prepared"
            request = JobRequest(
                job_id="job-pipeline-omega-prepared",
                pipeline_name="omega_block_pipeline",
                task_type="omega_block",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "_data_access_requests": {
                        "timeseries_bundle_mat": {
                            "selector": {"uris": [str(input_mat)]}
                        },
                        "omega_fixed_mat": {
                            "selector": {"uris": [str(omega_fixed_mat)]}
                        },
                        "exp0_calib_mat": {"selector": {"uris": [str(exp0_calib_mat)]}},
                    }
                },
                algorithm_params={
                    "write_daily_files": True,
                    "temp_scheme": "DUAL",
                    "exp_mode": "Exp2",
                    "block_days": 8,
                },
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_result = {
                "date_keys": ["20200101", "20200102"],
                "OMEGA_mat": np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float64),
                "SM_RET_mat": np.array([[0.2, 0.25], [0.3, 0.35]], dtype=np.float64),
                "VOD_RET_mat": np.array([[1.1, 1.2], [1.3, 1.4]], dtype=np.float64),
                "Tau_star_mat": np.array([[0.5, 0.6], [0.7, 0.8]], dtype=np.float64),
                "qc_flag_mat": np.zeros((1, 2), dtype=np.uint8),
                "qc_condk_mat": np.array([[10.0, 12.0]], dtype=np.float64),
                "qc_sratio_mat": np.array([[0.1, 0.2]], dtype=np.float64),
            }

            def fake_load_mat_file(path):
                current_path = Path(path)
                if current_path == expected_input_mat:
                    return {
                        "date_keys": fake_result["date_keys"],
                        "TBv_mat": np.array([[1.0]]),
                    }
                if current_path == expected_omega_fixed_mat:
                    return {"omega_fixed_vec": np.array([0.12, 0.13], dtype=np.float64)}
                if current_path == expected_exp0_calib_mat:
                    return {
                        "h_exp0_vec": np.array([0.2, 0.21], dtype=np.float64),
                        "alpha_exp0_vec": np.array([0.17, 0.18], dtype=np.float64),
                    }
                raise AssertionError(f"Unexpected MAT path: {current_path}")

            def fake_execute(payload, *, config, field_config):
                self.assertIn("omega_fixed_vec", payload)
                self.assertIn("h_exp0_vec", payload)
                self.assertIn("alpha_exp0_vec", payload)
                self.assertEqual(config.temp_scheme, "DUAL")
                self.assertEqual(config.exp_mode, "Exp2")
                self.assertEqual(config.block_days, 8)
                self.assertIsNotNone(field_config)
                return fake_result

            expected_input_mat = input_mat
            expected_omega_fixed_mat = omega_fixed_mat
            expected_exp0_calib_mat = exp0_calib_mat
            with (
                patch(
                    "pipelines.omega_block_products.load_mat_file",
                    side_effect=fake_load_mat_file,
                ),
                patch(
                    "algorithms.omega.execute_omega_retrieval",
                    side_effect=fake_execute,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("omega_block_mat", product_types)
            self.assertIn("omega_daily_mat", product_types)
            self.assertEqual(
                manifest_payload["extra"]["pipeline_name"], "omega_block_pipeline"
            )
            self.assertEqual(manifest_payload["extra"]["temp_scheme"], "DUAL")
            self.assertEqual(manifest_payload["extra"]["exp_mode"], "Exp2")

    def test_run_job_executes_native_omega_block_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir)
            scheduler = _RecordingScheduler()
            datasource = _NoopDataSource()
            logger = _RecordingLogger()
            sink = LocalProductSink(workspace / "products" / "manifests")
            input_mat = workspace / "timeseries_bundle.mat"
            omega_fixed_mat = workspace / "omega_fixed.mat"
            exp0_calib_mat = workspace / "exp0_calib.mat"
            input_mat.write_bytes(b"MAT")
            omega_fixed_mat.write_bytes(b"MAT")
            exp0_calib_mat.write_bytes(b"MAT")
            output_dir = workspace / "omega_block"
            request = JobRequest(
                job_id="job-native-omega",
                pipeline_name="workflow",
                module_name="omega_block",
                task_type="workflow",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={
                    "input_mat": str(input_mat),
                    "omega_fixed_mat": str(omega_fixed_mat),
                    "exp0_calib_mat": str(exp0_calib_mat),
                },
                algorithm_params={
                    "write_daily_files": True,
                    "temp_scheme": "DUAL",
                    "exp_mode": "Exp2",
                    "block_days": 8,
                },
                output_spec=OutputSpec(extra={"output_dir": str(output_dir)}),
            )

            fake_result = {
                "date_keys": ["20200101", "20200102"],
                "OMEGA_mat": np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float64),
                "SM_RET_mat": np.array([[0.2, 0.25], [0.3, 0.35]], dtype=np.float64),
                "VOD_RET_mat": np.array([[1.1, 1.2], [1.3, 1.4]], dtype=np.float64),
                "Tau_star_mat": np.array([[0.5, 0.6], [0.7, 0.8]], dtype=np.float64),
                "qc_flag_mat": np.zeros((1, 2), dtype=np.uint8),
                "qc_condk_mat": np.array([[10.0, 12.0]], dtype=np.float64),
                "qc_sratio_mat": np.array([[0.1, 0.2]], dtype=np.float64),
                "block_start_keys": ["20200101"],
                "block_end_keys": ["20200102"],
            }

            def fake_load_mat_file(path):
                path = Path(path)
                if path == input_mat:
                    return {
                        "date_keys": fake_result["date_keys"],
                        "TBv_mat": np.array([[1.0]]),
                    }
                if path == omega_fixed_mat:
                    return {"omega_fixed_vec": np.array([0.12, 0.13], dtype=np.float64)}
                if path == exp0_calib_mat:
                    return {
                        "h_exp0_vec": np.array([0.2, 0.21], dtype=np.float64),
                        "alpha_exp0_vec": np.array([0.17, 0.18], dtype=np.float64),
                    }
                raise AssertionError(f"Unexpected MAT path: {path}")

            def fake_execute(payload, *, config, field_config):
                self.assertIn("omega_fixed_vec", payload)
                self.assertIn("h_exp0_vec", payload)
                self.assertIn("alpha_exp0_vec", payload)
                self.assertEqual(config.temp_scheme, "DUAL")
                self.assertEqual(config.exp_mode, "Exp2")
                self.assertEqual(config.block_days, 8)
                self.assertIsNotNone(field_config)
                return fake_result

            with (
                patch("modules.omega.load_mat_file", side_effect=fake_load_mat_file),
                patch(
                    "algorithms.omega.execute_omega_retrieval",
                    side_effect=fake_execute,
                ),
            ):
                result = run_job(
                    request,
                    scheduler,
                    datasource,
                    logger,
                    product_sink=sink,
                    workspace=workspace,
                )

            self.assertEqual(result.status, "success")
            self.assertIsNotNone(result.manifest_uri)
            manifest_payload = json.loads(
                Path(result.manifest_uri).read_text(encoding="utf-8")
            )
            product_types = [
                product["type"] for product in manifest_payload["products"]
            ]
            self.assertIn("omega_block_mat", product_types)
            self.assertIn("omega_daily_mat", product_types)
            self.assertEqual(manifest_payload["extra"]["module_name"], "omega_block")
            self.assertEqual(manifest_payload["extra"]["temp_scheme"], "DUAL")
            self.assertEqual(manifest_payload["extra"]["exp_mode"], "Exp2")
            self.assertEqual(
                manifest_payload["qc_layers"],
                ["qc_flag_mat", "qc_condk_mat", "qc_sratio_mat"],
            )
            self.assertEqual(
                [status for status, _ in scheduler.statuses], ["running", "planning"]
            )


if __name__ == "__main__":
    unittest.main()
