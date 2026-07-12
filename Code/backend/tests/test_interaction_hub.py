from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services.bridge_protocol import BridgeExecutionError
from app.services.workflow.submission_service import WorkflowSubmissionService
from app.services.workflow.lifecycle_service import WorkflowLifecycleService
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder
from app.services.workflow.follow_up_dispatch_service import FollowUpDispatchService
from app.services.workflow.runtime_status_service import RuntimeStatusService
from app.services.workflow_execution import WorkflowExecutionResult
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    FailureCategory,
    WorkflowAnalysisResultDto,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowDownloadResultDto,
    WorkflowPriority,
    WorkflowProviderResultDto,
    WorkflowResultReference,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
    RuntimeMapContext,
    ClientIdentity,
)


def _build_services(repository: SQLiteWorkflowRepository):
    """Build all 6 workflow services wired together with a custom repository."""
    transitions = WorkflowTransitionBuilder()
    persistence = WorkflowPersistenceService(repository)
    follow_up = FollowUpDispatchService(repository, persistence, transitions)
    runtime_status = RuntimeStatusService(repository)
    submission = WorkflowSubmissionService(repository, persistence, transitions, follow_up)
    lifecycle = WorkflowLifecycleService(repository, persistence, transitions, follow_up)
    submission.set_lifecycle_service(lifecycle)
    lifecycle.set_submission_service(submission)
    return submission, lifecycle, runtime_status


class WorkflowServicesTests(unittest.TestCase):
    def _build_payload(self, command_type: WorkflowCommandType, *, layer_id: str = "wind-field") -> WorkflowSubmitRequest:
        return WorkflowSubmitRequest(
            command_type=command_type,
            layer_id=layer_id,
            priority=WorkflowPriority.normal,
            requested_outputs=[],
            client=ClientIdentity(client_id="test-client"),
            map_context=RuntimeMapContext(active_layer_id=layer_id),
        )

    @staticmethod
    def _as_dict(value):
        return value if isinstance(value, dict) else value.model_dump(mode="json")

    def test_submit_workflow_creates_accepted_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)
            with patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                return_value=WorkflowExecutionResult(message="ok"),
            ):
                response = submission.submit_workflow(self._build_payload(WorkflowCommandType.analysis))

            self.assertIsInstance(response, WorkflowAcceptedResponse)
            run = submission.get_workflow_run(response.run_id)
            self.assertIsNotNone(run)
            self.assertEqual(run.status, ExecutionStatus.succeeded)
            self.assertEqual(run.status_url, f"/workflow-runs/{response.run_id}")
            self.assertEqual(run.events_url, f"/workflow-runs/{response.run_id}/events")

    def test_cancel_workflow_marks_terminal_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)
            with patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                return_value=WorkflowExecutionResult(message="ok"),
            ):
                response = submission.submit_workflow(self._build_payload(WorkflowCommandType.analysis))
            with self.assertRaisesRegex(ValueError, "terminal state"):
                lifecycle.cancel_workflow_run(response.run_id)

    def test_runtime_status_reports_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)
            status = runtime_status.get_runtime_status()

            self.assertEqual(status.service_name, settings.service_name)
            self.assertGreaterEqual(len(status.services), 3)

    def test_schedule_retry_passes_countdown_and_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)
            payload = self._build_payload(WorkflowCommandType.analysis)

            with patch("app.services.workflow.lifecycle_service.dispatch_workflow_task") as dispatch_mock:
                lifecycle._schedule_retry(
                    run_id="run-retry-1",
                    payload=payload,
                    next_attempt=2,
                    backoff_seconds=4.5,
                )

            dispatch_mock.assert_called_once()
            call_kwargs = dispatch_mock.call_args.kwargs
            self.assertEqual(call_kwargs["run_id"], "run-retry-1")
            self.assertEqual(call_kwargs["countdown"], 4.5)
            self.assertEqual(call_kwargs["payload"].retry_attempt, 2)

    def test_submit_workflow_auto_populates_algorithm_request_from_layer_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)

            with patch(
                "app.services.workflow_request_resolver._resolve_data_access_source_uri",
                side_effect=lambda source: f"D:/prepared/{str(source).replace('/', '_')}",
            ), patch("app.services.workflow.submission_service.execute_workflow_task") as execute_mock:
                response = submission.submit_workflow(self._build_payload(WorkflowCommandType.analysis, layer_id="ndvi"))

            execute_mock.assert_called_once()
            normalized_payload = execute_mock.call_args.kwargs["payload"]
            algorithm_request = self._as_dict(normalized_payload.algorithm_request)
            self.assertEqual(algorithm_request["module_name"], "ndvi_daily")
            self.assertEqual(algorithm_request["workflow_entry_name"], "ndvi_daily")
            self.assertEqual(algorithm_request["task_type"], "ndvi_daily")
            self.assertEqual(
                algorithm_request["datasource_selection"]["_data_access_requests"]["NDVI_16DAY_RASTER"]["selector"]["uris"],
                ["D:/prepared/NDVI_VIIRS"],
            )

            request_json = repository.get_run_request_json(response.run_id)
            self.assertIsNotNone(request_json)
            persisted_payload = WorkflowSubmitRequest.model_validate_json(request_json)
            persisted_algorithm_request = self._as_dict(persisted_payload.algorithm_request)
            self.assertEqual(persisted_algorithm_request["module_name"], "ndvi_daily")
            self.assertEqual(persisted_algorithm_request["task_type"], "ndvi_daily")

    def test_submit_workflow_auto_populates_python_provider_defaults_for_smap_and_fy_layers(self) -> None:
        expected_layers = {
            "smap-soil": ("smap_daily", "SMAP_SPL3SMP_E", "D:/prepared/SMAP_L3"),
            "fy-mwri": ("fy_daily", "FY_MWRI_HDF", "D:/prepared/fy"),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)
            with patch(
                "app.services.workflow_request_resolver._resolve_data_access_source_uri",
                side_effect=lambda source: f"D:/prepared/{str(source).replace('/', '_')}",
            ), patch("app.services.workflow.submission_service.execute_workflow_task") as execute_mock:
                for layer_id in expected_layers:
                    submission.submit_workflow(self._build_payload(WorkflowCommandType.analysis, layer_id=layer_id))

            self.assertEqual(execute_mock.call_count, len(expected_layers))
            for call in execute_mock.call_args_list:
                normalized_payload = call.kwargs["payload"]
                layer_id = normalized_payload.layer_id
                expected_task_type, expected_dataset_name, expected_uri = expected_layers[layer_id]
                algorithm_request = self._as_dict(normalized_payload.algorithm_request)

                with self.subTest(layer_id=layer_id):
                    self.assertEqual(algorithm_request["module_name"], expected_task_type)
                    self.assertEqual(algorithm_request["task_type"], expected_task_type)
                    self.assertEqual(
                        algorithm_request["datasource_selection"]["_data_access_requests"][expected_dataset_name]["selector"]["uris"],
                        [expected_uri],
                    )

    def test_submit_workflow_keeps_python_provider_datasource_missing_when_default_sources_are_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)

            with patch(
                "app.services.workflow_request_resolver._resolve_data_access_source_uri",
                return_value=None,
            ), patch("app.services.workflow.submission_service.execute_workflow_task") as execute_mock:
                submission.submit_workflow(self._build_payload(WorkflowCommandType.analysis, layer_id="ndvi"))

            execute_mock.assert_called_once()
            normalized_payload = execute_mock.call_args.kwargs["payload"]
            algorithm_request = self._as_dict(normalized_payload.algorithm_request)
            self.assertEqual(algorithm_request["module_name"], "ndvi_daily")
            self.assertEqual(algorithm_request["task_type"], "ndvi_daily")
            datasource_selection = algorithm_request.get("datasource_selection", {})
            self.assertFalse(datasource_selection.get("_data_access_requests"))

    def test_submit_workflow_surfaces_validation_failure_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)

            with patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                side_effect=BridgeExecutionError(
                    category=FailureCategory.validation_error,
                    message="Provider template validation failed: module 'ndvi_daily' requires datasource_selection keys: input_dir",
                ),
            ):
                response = submission.submit_workflow(self._build_payload(WorkflowCommandType.analysis, layer_id="ndvi"))

            run = submission.get_workflow_run(response.run_id)
            self.assertIsNotNone(run)
            self.assertEqual(run.status, ExecutionStatus.failed)
            self.assertIn("工作流校验失败：", run.message)
            self.assertIn("Provider template validation failed", run.message)

    def test_submit_workflow_persists_resolution_diagnostics_for_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)

            with patch(
                "app.services.workflow.submission_service.execute_workflow_task",
                side_effect=BridgeExecutionError(
                    category=FailureCategory.validation_error,
                    message="Provider template validation failed: module 'ndvi_daily' requires datasource_selection keys: input_dir",
                    details={
                        "resolution_diagnostics": {
                            "layer_id": "ndvi",
                            "module_name": "ndvi_daily",
                            "task_type": "ndvi_daily",
                            "layer_status": "placeholder",
                            "unresolved_default_datasets": [
                                {
                                    "dataset_name": "NDVI_16DAY_RASTER",
                                    "candidate_sources": ["NDVI_VIIRS", "NDVI_MODIS", "ndvi"],
                                }
                            ],
                        }
                    },
                ),
            ):
                response = submission.submit_workflow(self._build_payload(WorkflowCommandType.analysis, layer_id="ndvi"))

            run = submission.get_workflow_run(response.run_id)
            self.assertIsNotNone(run)
            self.assertIn("validation_layer_id=ndvi", run.diagnostics)
            self.assertIn("validation_module_name=ndvi_daily", run.diagnostics)
            self.assertIn("validation_layer_status=placeholder", run.diagnostics)
            self.assertIn("validation_dataset_missing=NDVI_16DAY_RASTER", run.diagnostics)
            self.assertIn(
                "validation_dataset_candidates.NDVI_16DAY_RASTER=NDVI_VIIRS|NDVI_MODIS|ndvi",
                run.diagnostics,
            )

    def test_submit_workflow_auto_populates_gee_request_from_layer_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = SQLiteWorkflowRepository(state_dir=Path(tmpdir))
            submission, lifecycle, runtime_status = _build_services(repository)
            with patch("app.services.workflow.submission_service.execute_workflow_task") as execute_mock:
                response = submission.submit_workflow(self._build_payload(WorkflowCommandType.analysis, layer_id="remote-sensing"))

            execute_mock.assert_called_once()
            normalized_payload = execute_mock.call_args.kwargs["payload"]
            gee_request = (
                normalized_payload.gee_request
                if isinstance(normalized_payload.gee_request, dict)
                else normalized_payload.gee_request.model_dump(mode="json")
            )
            self.assertEqual(gee_request["workflow_id"], "gee-remote-sensing-ndvi")
            self.assertEqual(gee_request["workflow"]["workflow_id"], "gee-remote-sensing-ndvi")
            self.assertEqual(gee_request["workflow"]["nodes"][0]["node_type"], "gee_image")
            self.assertEqual(gee_request["workflow"]["nodes"][1]["node_type"], "gee_spectral_index")
            self.assertEqual(gee_request["workflow"]["nodes"][2]["node_type"], "gee_export_image")

            request_json = repository.get_run_request_json(response.run_id)
            self.assertIsNotNone(request_json)
            persisted_payload = WorkflowSubmitRequest.model_validate_json(request_json)
            persisted_gee_request = (
                persisted_payload.gee_request
                if isinstance(persisted_payload.gee_request, dict)
                else persisted_payload.gee_request.model_dump(mode="json")
            )
            self.assertEqual(persisted_gee_request["workflow_id"], "gee-remote-sensing-ndvi")


if __name__ == "__main__":
    unittest.main()
