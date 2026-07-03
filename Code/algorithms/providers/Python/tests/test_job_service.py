from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path

from contracts.job import JobResult
from service.async_jobs import AsyncJobRegistry
from service.job_api import JobService, start_local_async_worker
from service.job_queue import InMemoryJobQueue
from utils.local_adapters import ConsoleLoggerAdapter, LocalDataSourceAdapter, LocalProductSink, LocalSchedulerAdapter


def _build_valid_omega_request_payload() -> dict[str, object]:
    return {
        "job_id": "omega-service-job",
        "pipeline_name": "workflow",
        "workflow_name": "retrieval_workflow",
        "task_type": "retrieval",
        "time_range": {
            "start": "2025-01-01T00:00:00Z",
            "end": "2025-01-02T00:00:00Z",
        },
        "region": {
            "kind": "global",
            "value": {},
        },
        "datasource_selection": {
            "omega_fixed_mat": "D:/data/omega_fixed.mat",
            "exp0_calib_mat": "D:/data/exp0_calib.mat",
        },
        "algorithm_params": {
            "mode": "omega",
        },
    }


class JobServiceTests(unittest.TestCase):
    def _build_service(self, run_job_fn) -> JobService:
        workspace = tempfile.mkdtemp()
        service = JobService(
            scheduler_adapter=LocalSchedulerAdapter(),
            datasource_adapter=LocalDataSourceAdapter(),
            logger_adapter=ConsoleLoggerAdapter(),
            product_sink=LocalProductSink(workspace),
            workspace=workspace,
            run_job_fn=run_job_fn,
            async_job_registry=AsyncJobRegistry(),
            job_queue=InMemoryJobQueue(),
        )
        start_local_async_worker(service)
        return service

    def test_validate_job_returns_normalized_request(self) -> None:
        service = self._build_service(run_job_fn=lambda *args, **kwargs: None)

        response = service.validate_job(_build_valid_omega_request_payload())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.body["valid"])
        self.assertEqual(response.body["normalized_request"]["workflow_name"], "retrieval_workflow")
        self.assertEqual(response.body["normalized_request"]["algorithm_params"]["mode"], "omega")

    def test_validate_job_returns_structured_error_for_missing_omega_inputs(self) -> None:
        service = self._build_service(run_job_fn=lambda *args, **kwargs: None)
        payload = _build_valid_omega_request_payload()
        payload["datasource_selection"] = {}

        response = service.validate_job(payload)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.body["error_code"], "job_request_validation_failed")
        self.assertEqual(response.body["issues"][0]["field_path"], "job_request.datasource_selection.omega_fixed_mat")

    def test_submit_job_rejects_invalid_json_string(self) -> None:
        service = self._build_service(run_job_fn=lambda *args, **kwargs: None)

        response = service.submit_job("{not-json}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.body["error_code"], "job_request_decode_failed")

    def test_submit_job_returns_serialized_job_result_on_success(self) -> None:
        captured = {}

        def fake_run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink=None, workspace=None):
            captured["job_id"] = request.job_id
            captured["workspace"] = workspace
            return JobResult(
                job_id=request.job_id,
                run_id="run-001",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
                manifest_uri="D:/workspace/manifests/run-001.json",
                log_uri="https://logs.example.com/jobs/run-001.log",
                metrics={
                    "conversion_trace": {
                        "dataset_count": 1,
                        "entry_count": 2,
                        "datasets": [
                            {
                                "dataset_name": "mock_dataset",
                                "entry_count": 2,
                                "resource_count": 2,
                                "adapters": ["mat", "netcdf"],
                                "formats": ["mat", "nc"],
                                "logical_types": ["array"],
                                "resources": [
                                    {
                                        "uri": "cache://materialized/mock-1.mat",
                                        "origin_uri": "minio://bucket/mock-1.mat",
                                        "local_path": "D:/workspace/cache/mock-1.mat",
                                        "adapter": "mat",
                                        "format": "mat",
                                        "logical_type": "array",
                                        "loaded_summary": {
                                            "counts": {"variable_count": 2},
                                            "schema": {"variable_names": ("tb", "sm")},
                                            "document": {},
                                            "spatial": {},
                                            "title": "MAT resource",
                                            "highlights": [
                                                {"key": "variable_count", "label": "Variables", "value": 2},
                                                {"key": "variable_names", "label": "Variable Names", "value": "tb, sm"},
                                            ],
                                            "warnings": [],
                                        },
                                    },
                                    {
                                        "uri": "cache://materialized/mock-2.nc",
                                        "origin_uri": "https://example.com/mock-2.nc",
                                        "local_path": "D:/workspace/cache/mock-2.nc",
                                        "adapter": "netcdf",
                                        "format": "nc",
                                        "logical_type": "array",
                                        "loaded_summary": {
                                            "counts": {"dimension_count": 2, "variable_count": 1},
                                            "schema": {"dimension_names": ("x", "y")},
                                            "document": {},
                                            "spatial": {},
                                            "title": "NetCDF dataset",
                                            "highlights": [
                                                {"key": "dimension_count", "label": "Dimensions", "value": 2},
                                                {"key": "variable_count", "label": "Variables", "value": 1},
                                                {"key": "dimension_names", "label": "Dimension Names", "value": "x, y"},
                                            ],
                                            "warnings": [],
                                        },
                                    },
                                ],
                            }
                        ],
                    }
                },
            )

        service = self._build_service(run_job_fn=fake_run_job)

        response = service.submit_job(json.dumps(_build_valid_omega_request_payload()))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["job_id"], "omega-service-job")
        self.assertEqual(response.body["job_result"]["status"], "success")
        self.assertEqual(response.body["job_result"]["manifest_uri"], "D:/workspace/manifests/run-001.json")
        self.assertTrue(response.body["job_result"]["started_at"].endswith("+00:00"))
        self.assertEqual(response.body["result_dto"]["job_id"], "omega-service-job")
        self.assertFalse(response.body["result_dto"]["manifest_loaded"])
        self.assertEqual(response.body["result_dto"]["products"], [])
        self.assertEqual(response.body["result_dto"]["artifacts"]["manifest"]["storage_backend"], "file")
        self.assertEqual(response.body["result_dto"]["artifacts"]["manifest"]["object_key"], "D:/workspace/manifests/run-001.json")
        self.assertEqual(response.body["result_dto"]["artifacts"]["manifest"]["preview_url"], "file:///D:/workspace/manifests/run-001.json")
        self.assertEqual(response.body["result_dto"]["artifacts"]["log"]["storage_backend"], "https")
        self.assertEqual(response.body["result_dto"]["artifacts"]["log"]["download_url"], "https://logs.example.com/jobs/run-001.log")
        self.assertIsNone(response.body["result_dto"]["artifacts"]["metadata"]["uri"])
        self.assertEqual(response.body["result_dto"]["conversion_trace"]["dataset_count"], 1)
        self.assertEqual(response.body["result_dto"]["conversion_trace"]["entry_count"], 2)
        self.assertEqual(response.body["result_dto"]["conversion_trace"]["datasets"][0]["resource_count"], 2)
        self.assertEqual(
            response.body["result_dto"]["conversion_trace"]["datasets"][0]["resources"][0]["origin_uri"],
            "minio://bucket/mock-1.mat",
        )
        self.assertEqual(
            response.body["result_dto"]["conversion_trace"]["datasets"][0]["resources"][1]["loaded_summary"]["counts"]["dimension_count"],
            2,
        )
        self.assertEqual(
            response.body["result_dto"]["conversion_trace"]["datasets"][0]["resources"][1]["loaded_summary"]["title"],
            "NetCDF dataset",
        )
        panel = response.body["result_dto"]["conversion_trace_panel"]
        self.assertTrue(panel["available"])
        self.assertEqual(panel["dataset_count"], 1)
        self.assertEqual(panel["resource_count"], 2)
        self.assertEqual(panel["adapters"], ["mat", "netcdf"])
        self.assertEqual(panel["formats"], ["mat", "nc"])
        self.assertEqual(panel["logical_types"], ["array"])
        self.assertEqual(panel["warnings"], [])
        self.assertEqual(panel["datasets"][0]["title"], "mock_dataset")
        self.assertEqual(panel["datasets"][0]["highlights"][0]["value"], 2)
        self.assertEqual(panel["datasets"][0]["resources"][0]["title"], "MAT resource")
        self.assertEqual(
            panel["datasets"][0]["resources"][0]["summary"]["schema"]["variable_names"],
            ["tb", "sm"],
        )
        self.assertEqual(panel["datasets"][0]["resources"][1]["title"], "NetCDF dataset")
        self.assertEqual(
            panel["datasets"][0]["resources"][1]["summary"]["schema"]["dimension_names"],
            ["x", "y"],
        )

    def test_submit_job_expands_local_manifest_into_result_dto(self) -> None:
        captured: dict[str, Path] = {}

        def fake_run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink=None, workspace=None):
            manifest_path = Path(workspace) / "products" / "manifests" / "run-dto-001.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            captured["manifest_path"] = manifest_path
            manifest_path.write_text(
                json.dumps(
                    {
                        "job_id": request.job_id,
                        "run_id": "run-dto-001",
                        "products": [
                            {
                                "name": "omega_block_20250101_20250102",
                                "type": "omega_block_mat",
                                "uri": "minio://omega-bucket/jobs/run-dto-001/omega_block.mat",
                                "variable": "OMEGA_mat",
                                "tags": {"bucket": "omega-bucket"},
                            }
                        ],
                        "main_layers": ["OMEGA_mat", "SM_RET_mat"],
                        "qc_layers": ["qc_flag_mat"],
                        "tables": ["summary_table"],
                        "metadata_uri": "minio://omega-bucket/jobs/run-dto-001/metadata.json",
                        "created_at": "2025-01-01T00:01:00+00:00",
                        "extra": {
                            "storage_backend": "minio",
                            "conversion_trace": {
                                "dataset_count": 1,
                                "entry_count": 2,
                                "datasets": [
                                    {
                                        "dataset_name": "omega_inputs",
                                        "entry_count": 2,
                                        "resource_count": 2,
                                        "adapters": ["mat", "xml"],
                                        "formats": ["mat", "xml"],
                                        "logical_types": ["array", "document"],
                                        "resources": [
                                            {
                                                "uri": "cache://materialized/omega-fixed.mat",
                                                "origin_uri": "minio://omega-bucket/jobs/run-dto-001/omega_fixed.mat",
                                                "local_path": "D:/workspace/cache/omega-fixed.mat",
                                                "adapter": "mat",
                                                "format": "mat",
                                                "logical_type": "array",
                                                "loaded_summary": {
                                                    "counts": {"variable_count": 3},
                                                    "schema": {"variable_names": ("tb", "sm", "aux")},
                                                    "document": {},
                                                    "spatial": {},
                                                    "title": "MAT resource",
                                                    "highlights": [
                                                        {"key": "variable_count", "label": "Variables", "value": 3},
                                                        {"key": "variable_names", "label": "Variable Names", "value": "tb, sm, aux"},
                                                    ],
                                                    "warnings": [],
                                                },
                                            },
                                            {
                                                "uri": "cache://materialized/omega-config.xml",
                                                "origin_uri": "https://example.com/jobs/run-dto-001/config.xml",
                                                "local_path": "D:/workspace/cache/omega-config.xml",
                                                "adapter": "xml",
                                                "format": "xml",
                                                "logical_type": "document",
                                                "loaded_summary": {
                                                    "counts": {},
                                                    "schema": {},
                                                    "document": {"root_tag": "root"},
                                                    "spatial": {},
                                                    "title": "XML document root",
                                                    "highlights": [
                                                        {"key": "root_tag", "label": "Root Tag", "value": "root"},
                                                    ],
                                                    "warnings": [],
                                                },
                                            },
                                        ],
                                    }
                                ],
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return JobResult(
                job_id=request.job_id,
                run_id="run-dto-001",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
                manifest_uri=str(manifest_path),
                log_uri="https://logs.example.com/jobs/run-dto-001.log",
            )

        service = self._build_service(run_job_fn=fake_run_job)

        response = service.submit_job(_build_valid_omega_request_payload())

        self.assertEqual(response.status_code, 200)
        result_dto = response.body["result_dto"]
        manifest_path = captured["manifest_path"]
        self.assertTrue(result_dto["manifest_loaded"])
        self.assertEqual(result_dto["manifest_summary"]["product_count"], 1)
        self.assertEqual(result_dto["artifacts"]["metadata_uri"], "minio://omega-bucket/jobs/run-dto-001/metadata.json")
        self.assertEqual(result_dto["artifacts"]["manifest"]["storage_backend"], "file")
        self.assertEqual(result_dto["artifacts"]["manifest"]["object_key"], manifest_path.as_posix())
        self.assertEqual(result_dto["artifacts"]["metadata"]["storage_backend"], "minio")
        self.assertEqual(result_dto["artifacts"]["metadata"]["bucket"], "omega-bucket")
        self.assertEqual(result_dto["artifacts"]["metadata"]["object_key"], "jobs/run-dto-001/metadata.json")
        self.assertEqual(result_dto["artifacts"]["log"]["storage_backend"], "https")
        self.assertEqual(result_dto["artifacts"]["log"]["preview_url"], "https://logs.example.com/jobs/run-dto-001.log")
        self.assertEqual(result_dto["products"][0]["type"], "omega_block_mat")
        self.assertTrue(result_dto["products"][0]["is_previewable"])
        self.assertEqual(result_dto["products"][0]["storage_backend"], "minio")
        self.assertEqual(result_dto["products"][0]["bucket"], "omega-bucket")
        self.assertEqual(result_dto["products"][0]["object_key"], "jobs/run-dto-001/omega_block.mat")
        self.assertIsNone(result_dto["products"][0]["preview_url"])
        self.assertIsNone(result_dto["products"][0]["download_url"])
        self.assertEqual(result_dto["main_layers"], ["OMEGA_mat", "SM_RET_mat"])
        self.assertEqual(result_dto["qc_layers"], ["qc_flag_mat"])
        self.assertEqual(result_dto["tables"], ["summary_table"])
        self.assertEqual(result_dto["extra"]["storage_backend"], "minio")
        self.assertEqual(result_dto["conversion_trace"]["dataset_count"], 1)
        self.assertEqual(result_dto["conversion_trace"]["entry_count"], 2)
        self.assertEqual(result_dto["conversion_trace"]["datasets"][0]["resource_count"], 2)
        self.assertEqual(
            result_dto["conversion_trace"]["datasets"][0]["resources"][0]["origin_uri"],
            "minio://omega-bucket/jobs/run-dto-001/omega_fixed.mat",
        )
        self.assertEqual(
            result_dto["conversion_trace"]["datasets"][0]["resources"][1]["loaded_summary"]["document"]["root_tag"],
            "root",
        )
        self.assertEqual(
            result_dto["conversion_trace"]["datasets"][0]["resources"][1]["loaded_summary"]["title"],
            "XML document root",
        )
        self.assertEqual(result_dto["manifest_summary"]["conversion_trace_dataset_count"], 1)
        self.assertEqual(result_dto["manifest_summary"]["conversion_trace_resource_count"], 2)
        panel = result_dto["conversion_trace_panel"]
        self.assertTrue(panel["available"])
        self.assertEqual(panel["dataset_count"], 1)
        self.assertEqual(panel["resource_count"], 2)
        self.assertEqual(panel["datasets"][0]["dataset_name"], "omega_inputs")
        self.assertEqual(panel["datasets"][0]["resources"][0]["title"], "MAT resource")
        self.assertEqual(
            panel["datasets"][0]["resources"][0]["summary"]["schema"]["variable_names"],
            ["tb", "sm", "aux"],
        )
        self.assertEqual(panel["datasets"][0]["resources"][1]["title"], "XML document root")
        self.assertEqual(
            panel["datasets"][0]["resources"][1]["summary"]["document"]["root_tag"],
            "root",
        )

    def test_submit_job_expands_http_and_s3_storage_fields_into_result_dto(self) -> None:
        def fake_run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink=None, workspace=None):
            manifest_path = Path(workspace) / "products" / "manifests" / "run-dto-002.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "job_id": request.job_id,
                        "run_id": "run-dto-002",
                        "products": [
                            {
                                "name": "omega_preview",
                                "type": "raster",
                                "uri": "https://files.example.com/jobs/run-dto-002/omega_preview.tif",
                                "variable": "OMEGA_PREVIEW",
                            },
                            {
                                "name": "omega_archive",
                                "type": "raster",
                                "uri": "s3://archive-bucket/jobs/run-dto-002/omega_archive.tif",
                                "variable": "OMEGA_ARCHIVE",
                                "preview_url": "https://signed.example.com/preview/omega_archive.tif",
                                "download_url": "https://signed.example.com/download/omega_archive.tif",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return JobResult(
                job_id=request.job_id,
                run_id="run-dto-002",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
                manifest_uri=str(manifest_path),
            )

        service = self._build_service(run_job_fn=fake_run_job)

        response = service.submit_job(_build_valid_omega_request_payload())

        self.assertEqual(response.status_code, 200)
        products = response.body["result_dto"]["products"]
        self.assertEqual(products[0]["storage_backend"], "https")
        self.assertIsNone(products[0]["bucket"])
        self.assertIsNone(products[0]["object_key"])
        self.assertEqual(products[0]["preview_url"], "https://files.example.com/jobs/run-dto-002/omega_preview.tif")
        self.assertEqual(products[0]["download_url"], "https://files.example.com/jobs/run-dto-002/omega_preview.tif")
        self.assertEqual(products[1]["storage_backend"], "s3")
        self.assertEqual(products[1]["bucket"], "archive-bucket")
        self.assertEqual(products[1]["object_key"], "jobs/run-dto-002/omega_archive.tif")
        self.assertEqual(products[1]["preview_url"], "https://signed.example.com/preview/omega_archive.tif")
        self.assertEqual(products[1]["download_url"], "https://signed.example.com/download/omega_archive.tif")

    def test_submit_job_expands_local_file_storage_fields_into_result_dto(self) -> None:
        captured: dict[str, Path] = {}

        def fake_run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink=None, workspace=None):
            artifact_path = Path(workspace) / "products" / "omega_local.mat"
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text("placeholder", encoding="utf-8")
            captured["artifact_path"] = artifact_path
            manifest_path = Path(workspace) / "products" / "manifests" / "run-dto-003.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "job_id": request.job_id,
                        "run_id": "run-dto-003",
                        "products": [
                            {
                                "name": "omega_local",
                                "type": "omega_block_mat",
                                "uri": str(artifact_path),
                                "variable": "OMEGA_LOCAL",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return JobResult(
                job_id=request.job_id,
                run_id="run-dto-003",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
                manifest_uri=str(manifest_path),
            )

        service = self._build_service(run_job_fn=fake_run_job)

        response = service.submit_job(_build_valid_omega_request_payload())

        self.assertEqual(response.status_code, 200)
        product = response.body["result_dto"]["products"][0]
        artifact_path = captured["artifact_path"]
        self.assertEqual(product["storage_backend"], "file")
        self.assertIsNone(product["bucket"])
        self.assertEqual(product["object_key"], artifact_path.as_posix())
        self.assertEqual(product["preview_url"], artifact_path.as_uri())
        self.assertEqual(product["download_url"], artifact_path.as_uri())

    def test_submit_job_returns_execution_error_payload_when_run_job_fails(self) -> None:
        def fake_run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink=None, workspace=None):
            return JobResult(
                job_id=request.job_id,
                run_id="run-002",
                status="failed",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 2, tzinfo=UTC),
                error_summary="simulated failure",
            )

        service = self._build_service(run_job_fn=fake_run_job)

        response = service.submit_job(_build_valid_omega_request_payload())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.body["error_type"], "job_execution_failed")
        self.assertEqual(response.body["job_result"]["status"], "failed")
        self.assertEqual(response.body["developer_message"], "simulated failure")

    def test_get_schema_responses_return_expected_titles(self) -> None:
        service = self._build_service(run_job_fn=lambda *args, **kwargs: None)

        job_schema = service.get_job_request_schema_response()
        workflow_schema = service.get_workflow_definition_schema_response()

        self.assertEqual(job_schema.status_code, 200)
        self.assertEqual(job_schema.body["title"], "JobRequest")
        self.assertEqual(workflow_schema.status_code, 200)
        self.assertEqual(workflow_schema.body["title"], "WorkflowDefinition")

    def test_list_modules_and_describe_module_return_structured_metadata(self) -> None:
        service = self._build_service(run_job_fn=lambda *args, **kwargs: None)

        modules_response = service.list_modules_response()
        describe_response = service.describe_module_response("omega_block")

        self.assertEqual(modules_response.status_code, 200)
        self.assertGreaterEqual(modules_response.body["count"], 1)
        self.assertTrue(any(item["name"] == "omega_block" for item in modules_response.body["modules"]))
        self.assertEqual(describe_response.status_code, 200)
        self.assertEqual(describe_response.body["name"], "omega_block")
        self.assertEqual(describe_response.body["entry_kind"], "module")
        self.assertTrue(any(port["name"] == "input_mat" for port in describe_response.body["input_ports"]))
        self.assertEqual(describe_response.body["request_template"]["entry_name"], "omega_block")

    def test_list_workflows_and_describe_workflow_return_panel_metadata(self) -> None:
        service = self._build_service(run_job_fn=lambda *args, **kwargs: None)

        workflows_response = service.list_workflows_response()
        describe_response = service.describe_workflow_response("retrieval_workflow")
        panel_response = service.get_workflow_panel_schema_response("retrieval_workflow")
        ui_response = service.get_workflow_ui_schema_response("retrieval_workflow")

        self.assertEqual(workflows_response.status_code, 200)
        self.assertEqual(workflows_response.body["count"], 1)
        self.assertEqual(workflows_response.body["workflows"][0]["name"], "retrieval_workflow")
        self.assertEqual(tuple(workflows_response.body["workflows"][0]["preview_modes"]), ("dh", "ddca", "omega"))
        self.assertEqual(describe_response.status_code, 200)
        self.assertEqual(describe_response.body["name"], "retrieval_workflow")
        self.assertEqual(describe_response.body["definition"]["workflow_id"], "retrieval_workflow")
        self.assertIn("definition_variants", describe_response.body)
        self.assertIn("omega", describe_response.body["definition_variants"])
        self.assertEqual(panel_response.status_code, 200)
        self.assertEqual(panel_response.body["workflow_id"], "retrieval_workflow")
        self.assertTrue(any(field["key"] == "algorithm_params" for field in panel_response.body["request_fields"]))
        self.assertTrue(any(field["key"] == "mode" for field in panel_response.body["algorithm_param_fields"]))
        self.assertTrue(any(field["key"] == "omega_fixed_mat" for field in panel_response.body["datasource_fields"]))
        self.assertTrue(any(field["key"] == "exp0_calib_mat" for field in panel_response.body["datasource_fields"]))
        self.assertTrue(any("Preview merges workflow variants" in note for note in panel_response.body["notes"]))
        self.assertEqual(ui_response.status_code, 200)
        self.assertEqual(ui_response.body["workflow_id"], "retrieval_workflow")
        self.assertTrue(any(section["key"] == "datasource_selection" for section in ui_response.body["sections"]))
        datasource_section = next(section for section in ui_response.body["sections"] if section["key"] == "datasource_selection")
        self.assertTrue(any(field["key"] == "omega_fixed_mat" for field in datasource_section["fields"]))

    def test_describe_unknown_catalog_entries_returns_not_found(self) -> None:
        service = self._build_service(run_job_fn=lambda *args, **kwargs: None)

        module_response = service.describe_module_response("missing-module")
        workflow_response = service.describe_workflow_response("missing-workflow")

        self.assertEqual(module_response.status_code, 404)
        self.assertEqual(module_response.body["error_code"], "module_not_found")
        self.assertEqual(workflow_response.status_code, 404)
        self.assertEqual(workflow_response.body["error_code"], "workflow_not_found")

    def test_submit_job_async_returns_submission_and_status_can_be_queried(self) -> None:
        def fake_run_job(request, scheduler_adapter, datasource_adapter, logger_adapter, product_sink=None, workspace=None):
            scheduler_adapter.update_status(request.job_id, "run-async-001", "running", {"stage": "dispatch"})
            result = JobResult(
                job_id=request.job_id,
                run_id="run-async-001",
                status="success",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                finished_at=datetime(2025, 1, 1, 0, 3, tzinfo=UTC),
                manifest_uri="D:/workspace/manifests/run-async-001.json",
            )
            scheduler_adapter.complete(result)
            return result

        service = self._build_service(run_job_fn=fake_run_job)

        accepted = service.submit_job_async(_build_valid_omega_request_payload())

        self.assertEqual(accepted.status_code, 202)
        submission_id = accepted.body["submission_id"]
        self.assertTrue(submission_id)

        snapshot = None
        for _ in range(30):
            snapshot_response = service.get_job_status(submission_id)
            snapshot = snapshot_response.body
            if snapshot["state"] == "completed":
                break
            time.sleep(0.05)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["state"], "completed")
        self.assertEqual(snapshot["run_id"], "run-async-001")
        self.assertEqual(snapshot["job_result"]["status"], "success")
        self.assertEqual(snapshot["final_response_status"], 200)
        self.assertEqual(snapshot["result_dto"]["run_id"], "run-async-001")
        self.assertFalse(snapshot["result_dto"]["manifest_loaded"])

    def test_get_job_status_returns_not_found_for_unknown_submission(self) -> None:
        service = self._build_service(run_job_fn=lambda *args, **kwargs: None)

        response = service.get_job_status("missing-submission")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.body["error_code"], "job_not_found")


if __name__ == "__main__":
    unittest.main()
