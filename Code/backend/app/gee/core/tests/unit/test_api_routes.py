import json

import pytest

from webgis_gee.api.contracts import (
    ExportTaskStatusResponse,
    WorkflowContractAdapter,
    WorkflowExecutionResponse,
    WorkflowSubmissionPayload,
    WorkflowValidationResponse,
)
from webgis_gee.api.facade import WorkflowApiFacade
from webgis_gee.api.routes import WorkflowApiHandlers, create_api_router
from webgis_gee.application.services import WorkflowService
from webgis_gee.config.settings import Settings
from webgis_gee.runtime.exceptions import WorkflowValidationError


def _create_handlers(tmp_path) -> WorkflowApiHandlers:
    service = WorkflowService(settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)))
    facade = WorkflowApiFacade(adapter=WorkflowContractAdapter(service))
    return WorkflowApiHandlers(facade=facade)


def _find_route(router, path: str):
    return next(route for route in router.routes if route.path == path)


class _RaisingFacade:
    def __init__(self, exception: Exception, *, method_name: str) -> None:
        self._exception = exception
        self._method_name = method_name

    def validate_workflow(self, workflow):
        if self._method_name == "validate_workflow":
            raise self._exception
        raise AssertionError("unexpected facade method call")

    def submit_workflow(self, workflow, context=None):
        if self._method_name == "submit_workflow":
            raise self._exception
        raise AssertionError("unexpected facade method call")

    def run_workflow_job(self, payload):
        if self._method_name == "run_workflow_job":
            raise self._exception
        raise AssertionError("unexpected facade method call")

    def get_export_task_status(self, manifest_uri, *, update_manifest=False, gee_module=None):
        if self._method_name == "get_export_task_status":
            raise self._exception
        raise AssertionError("unexpected facade method call")

    def diagnose(self):
        if self._method_name == "diagnose":
            raise self._exception
        raise AssertionError("unexpected facade method call")


class _RecordingFacade:
    def __init__(self) -> None:
        self.last_get_export_task_status_call: dict[str, object] | None = None

    def get_export_task_status(self, manifest_uri, *, update_manifest=False, gee_module=None):
        self.last_get_export_task_status_call = {
            "manifest_uri": manifest_uri,
            "update_manifest": update_manifest,
            "gee_module": gee_module,
        }
        return ExportTaskStatusResponse(
            status="manifest_created",
            state="LOCAL_ONLY",
            started=False,
            manifest_uri=manifest_uri,
        )


def test_handlers_validate_workflow_returns_route_friendly_validation_model(tmp_path) -> None:
    handlers = _create_handlers(tmp_path)

    response = handlers.validate_workflow(
        {
            "workflow": {
                "workflow_id": "route-validate-demo",
                "nodes": [
                    {"node_id": "n1", "node_type": "literal", "params": {"value": "ok"}},
                ],
            }
        }
    )

    assert isinstance(response, WorkflowValidationResponse)
    assert response.workflow.workflow_id == "route-validate-demo"
    assert response.saveback_terminal_plans["n1"].action == "monitor_only"


def test_handlers_submit_workflow_returns_route_friendly_execution_model(tmp_path) -> None:
    handlers = _create_handlers(tmp_path)

    response = handlers.submit_workflow(
        {
            "workflow": {
                "workflow_id": "route-submit-demo",
                "nodes": [
                    {"node_id": "n1", "node_type": "literal", "params": {"value": "ok"}},
                ],
            }
        }
    )

    assert isinstance(response, WorkflowExecutionResponse)
    assert response.status == "completed"
    assert response.outputs["n1.value"] == "ok"
    assert response.saveback_terminal_plan is not None


def test_handlers_run_workflow_job_returns_route_friendly_execution_model(tmp_path) -> None:
    handlers = _create_handlers(tmp_path)

    response = handlers.run_workflow_job(
        {
            "workflow": {
                "workflow_id": "route-worker-demo",
                "nodes": [
                    {"node_id": "n1", "node_type": "literal", "params": {"value": 42}},
                ],
            },
            "context": {
                "workflow_id": "route-worker-demo",
            },
        }
    )

    assert isinstance(response, WorkflowExecutionResponse)
    assert response.outputs["n1.value"] == 42


def test_handlers_get_export_task_status_returns_route_friendly_model(tmp_path) -> None:
    handlers = _create_handlers(tmp_path)
    manifest_path = tmp_path / "exports" / "route-handler.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "workflow_id": "route-handler-export-demo",
                "task_ref": {
                    "started": False,
                    "status": "manifest_created",
                },
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    response = handlers.get_export_task_status(manifest_uri=f"file://{manifest_path}")

    assert isinstance(response, ExportTaskStatusResponse)
    assert response.status == "manifest_created"
    assert response.state == "LOCAL_ONLY"


def test_handlers_diagnose_returns_diagnostics_report(tmp_path) -> None:
    handlers = _create_handlers(tmp_path)

    response = handlers.diagnose()

    assert response.status == "ok"
    assert "workflow_schema" in response.checks


def test_create_api_router_registers_fastapi_routes_when_dependency_is_available() -> None:
    pytest.importorskip("fastapi")

    router = create_api_router()
    route_paths = {route.path for route in router.routes}

    assert "/gee/workflows:validate" in route_paths
    assert "/gee/workflows:submit" in route_paths
    assert "/gee/workflow-jobs:run" in route_paths
    assert "/gee/exports:status" in route_paths
    assert "/gee/diagnostics" in route_paths


def test_create_api_router_preserves_workflow_validation_error_message() -> None:
    fastapi = pytest.importorskip("fastapi")
    router = create_api_router(
        facade=_RaisingFacade(
            WorkflowValidationError("workflow schema version is invalid"),
            method_name="validate_workflow",
        )
    )

    endpoint = _find_route(router, "/gee/workflows:validate").endpoint

    with pytest.raises(fastapi.HTTPException) as exc_info:
        endpoint(
            WorkflowSubmissionPayload.model_validate(
                {
                    "workflow": {
                        "workflow_id": "route-validate-error-demo",
                        "nodes": [{"node_id": "n1", "node_type": "literal", "params": {"value": "ok"}}],
                    }
                }
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "workflow schema version is invalid"


def test_create_api_router_hides_internal_submit_exception_details() -> None:
    fastapi = pytest.importorskip("fastapi")
    router = create_api_router(
        facade=_RaisingFacade(
            RuntimeError("redis://internal-secret@127.0.0.1:6379/0 connection failed"),
            method_name="submit_workflow",
        )
    )

    endpoint = _find_route(router, "/gee/workflows:submit").endpoint

    with pytest.raises(fastapi.HTTPException) as exc_info:
        endpoint(
            WorkflowSubmissionPayload.model_validate(
                {
                    "workflow": {
                        "workflow_id": "route-submit-error-demo",
                        "nodes": [{"node_id": "n1", "node_type": "literal", "params": {"value": "ok"}}],
                    }
                }
            )
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Workflow submission failed."
    assert "internal-secret" not in exc_info.value.detail


def test_create_api_router_returns_generic_client_error_for_invalid_export_request() -> None:
    fastapi = pytest.importorskip("fastapi")
    router = create_api_router(
        facade=_RaisingFacade(
            ValueError("invalid s3 manifest uri: s3://secret-bucket/private-path"),
            method_name="get_export_task_status",
        )
    )

    endpoint = _find_route(router, "/gee/exports:status").endpoint

    with pytest.raises(fastapi.HTTPException) as exc_info:
        endpoint(manifest_uri="s3://secret-bucket/private-path", update_manifest=True)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid export status request."
    assert "secret-bucket" not in exc_info.value.detail


def test_create_api_router_uses_read_only_export_status_by_default() -> None:
    pytest.importorskip("fastapi")
    facade = _RecordingFacade()
    router = create_api_router(facade=facade)

    endpoint = _find_route(router, "/gee/exports:status").endpoint
    response = endpoint(
        manifest_uri="file://C:/safe/exports/demo.json",
        update_manifest=False,
    )

    assert response.status == "manifest_created"
    assert facade.last_get_export_task_status_call is not None
    assert facade.last_get_export_task_status_call["update_manifest"] is False
