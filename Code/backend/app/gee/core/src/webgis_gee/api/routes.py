from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from webgis_gee.api.contracts import (
    ExportTaskStatusResponse,
    WorkflowJobPayload,
    WorkflowExecutionResponse,
    WorkflowSubmissionPayload,
    WorkflowValidationResponse,
)
from webgis_gee.api.facade import WorkflowApiFacade, create_default_api_facade
from webgis_gee.domain.models import DiagnosticsReport
from webgis_gee.runtime.exceptions import WorkflowValidationError


logger = logging.getLogger(__name__)


class WorkflowApiHandlers:
    """Backend-facing handlers that can be mounted into FastAPI routes."""

    def __init__(self, facade: WorkflowApiFacade | None = None) -> None:
        self._facade = facade or create_default_api_facade()

    def validate_workflow(
        self,
        payload: WorkflowSubmissionPayload | dict[str, Any],
    ) -> WorkflowValidationResponse:
        request = WorkflowSubmissionPayload.model_validate(payload)
        return self._facade.validate_workflow(request.workflow)

    def submit_workflow(
        self,
        payload: WorkflowSubmissionPayload | dict[str, Any],
    ) -> WorkflowExecutionResponse:
        request = WorkflowSubmissionPayload.model_validate(payload)
        return self._facade.submit_workflow(request.workflow, request.context)

    def run_workflow_job(
        self,
        payload: WorkflowJobPayload | WorkflowSubmissionPayload | dict[str, Any],
    ) -> WorkflowExecutionResponse:
        request = WorkflowJobPayload.model_validate(payload)
        return self._facade.run_workflow_job(request.model_dump(mode="python"))

    def get_export_task_status(
        self,
        manifest_uri: str,
        *,
        update_manifest: bool = False,
        gee_module: object | None = None,
    ) -> ExportTaskStatusResponse:
        return self._facade.get_export_task_status(
            manifest_uri=manifest_uri,
            update_manifest=update_manifest,
            gee_module=gee_module,
        )

    def diagnose(self) -> DiagnosticsReport:
        return self._facade.diagnose()


def create_api_router(facade: WorkflowApiFacade | None = None):
    """Create an optional FastAPI router without making FastAPI a hard dependency."""

    try:
        from fastapi import APIRouter, HTTPException, Query
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only in FastAPI integrations
        raise RuntimeError(
            "FastAPI is not installed. Install it in the WebGIS backend environment to use create_api_router()."
        ) from exc

    handlers = WorkflowApiHandlers(facade=facade)
    router = APIRouter(prefix="/gee", tags=["gee"])

    def handle_api_exception(
        exc: Exception,
        *,
        client_error_message: str = "Invalid request.",
        server_error_message: str = "Internal server error.",
    ) -> None:
        if isinstance(exc, HTTPException):
            raise exc
        if isinstance(exc, WorkflowValidationError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if isinstance(exc, ValidationError):
            raise HTTPException(status_code=400, detail=client_error_message) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=client_error_message) from exc
        logger.exception("Unhandled API exception in GEE router", exc_info=exc)
        raise HTTPException(status_code=500, detail=server_error_message) from exc

    @router.post("/workflows:validate", response_model=WorkflowValidationResponse)
    def validate_workflow(payload: WorkflowSubmissionPayload) -> WorkflowValidationResponse:
        try:
            return handlers.validate_workflow(payload)
        except Exception as exc:
            handle_api_exception(
                exc,
                client_error_message="Invalid workflow request.",
                server_error_message="Workflow validation failed.",
            )

    @router.post("/workflows:submit", response_model=WorkflowExecutionResponse)
    def submit_workflow(payload: WorkflowSubmissionPayload) -> WorkflowExecutionResponse:
        try:
            return handlers.submit_workflow(payload)
        except Exception as exc:
            handle_api_exception(
                exc,
                client_error_message="Invalid workflow request.",
                server_error_message="Workflow submission failed.",
            )

    @router.post("/workflow-jobs:run", response_model=WorkflowExecutionResponse)
    def run_workflow_job(payload: WorkflowJobPayload) -> WorkflowExecutionResponse:
        try:
            return handlers.run_workflow_job(payload)
        except Exception as exc:
            handle_api_exception(
                exc,
                client_error_message="Invalid workflow job request.",
                server_error_message="Workflow job execution failed.",
            )

    @router.get("/exports:status", response_model=ExportTaskStatusResponse)
    def get_export_status(
        manifest_uri: str,
        update_manifest: bool = Query(default=False),
    ) -> ExportTaskStatusResponse:
        try:
            return handlers.get_export_task_status(
                manifest_uri=manifest_uri,
                update_manifest=update_manifest,
            )
        except Exception as exc:
            handle_api_exception(
                exc,
                client_error_message="Invalid export status request.",
                server_error_message="Export status lookup failed.",
            )

    @router.get("/diagnostics", response_model=DiagnosticsReport)
    def diagnose() -> DiagnosticsReport:
        try:
            return handlers.diagnose()
        except Exception as exc:
            handle_api_exception(
                exc,
                server_error_message="Diagnostics request failed.",
            )

    return router
