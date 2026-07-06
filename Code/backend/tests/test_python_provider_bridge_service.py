from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from app.services.bridge_protocol import BridgeExecutionError
from app.services.python_provider_bridge_service import python_provider_bridge_service
from shared.contracts.api_contracts import (
    ClientIdentity,
    FailureCategory,
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


class _ServiceResponse:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self.body = body


class _InvalidValidationJobService:
    def validate_job_response(self, payload: object) -> _ServiceResponse:
        _ = payload
        return _ServiceResponse(
            200,
            {
                "is_valid": False,
                "errors": ["module 'ndvi_daily' requires datasource_selection keys: input_dir"],
                "template": {
                    "entry_kind": "module",
                    "entry_name": "ndvi_daily",
                    "allowed_task_types": ["ndvi_daily", "workflow"],
                    "required_datasource_keys": ["input_dir"],
                    "required_algorithm_keys": [],
                },
            },
        )

    def submit_job(self, payload: object) -> _ServiceResponse:  # pragma: no cover - should not be called
        raise AssertionError(f"submit_job should not be called when validation fails: {payload!r}")


class PythonProviderBridgeServiceTests(unittest.TestCase):
    def _build_payload(self) -> WorkflowSubmitRequest:
        return WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="ndvi",
            priority=WorkflowPriority.normal,
            requested_outputs=[],
            client=ClientIdentity(client_id="test-client"),
            map_context=RuntimeMapContext(active_layer_id="ndvi"),
            algorithm_request={
                "module_name": "ndvi_daily",
                "task_type": "ndvi_daily",
            },
        )

    def test_execute_includes_default_data_source_diagnostics_on_validation_failure(self) -> None:
        resolution_diagnostics = {
            "layer_id": "ndvi",
            "layer_status": "available",
            "module_name": "ndvi_daily",
            "task_type": "ndvi_daily",
            "unresolved_default_datasets": [
                {
                    "dataset_name": "NDVI_16DAY_RASTER",
                    "candidate_sources": ["NDVI_VIIRS", "NDVI_MODIS", "ndvi"],
                }
            ],
        }

        with patch.object(
            python_provider_bridge_service,
            "_get_job_service",
            return_value=_InvalidValidationJobService(),
        ), patch(
            "app.services.python_provider_bridge_service.describe_python_provider_resolution",
            return_value=resolution_diagnostics,
        ):
            with self.assertRaises(BridgeExecutionError) as ctx:
                python_provider_bridge_service.execute(
                    run_id="run-bridge-1",
                    payload=self._build_payload(),
                    requested_at=datetime.now(timezone.utc),
                    event_factory=lambda **kwargs: kwargs,
                )

        error = ctx.exception
        self.assertEqual(error.category, FailureCategory.validation_error)
        self.assertIn("Provider template validation failed", str(error))
        self.assertIn("Default data sources are not ready for layer 'ndvi'", str(error))
        self.assertIn("NDVI_16DAY_RASTER <= NDVI_VIIRS, NDVI_MODIS, ndvi", str(error))
        self.assertEqual(error.details["resolution_diagnostics"], resolution_diagnostics)
        self.assertEqual(
            error.details["validation_errors"],
            ["module 'ndvi_daily' requires datasource_selection keys: input_dir"],
        )


if __name__ == "__main__":
    unittest.main()
