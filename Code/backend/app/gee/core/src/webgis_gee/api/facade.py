from __future__ import annotations

from typing import Any

from webgis_gee.api.contracts import (
    ExportTaskStatusResponse,
    WorkflowContractAdapter,
    WorkflowExecutionResponse,
    WorkflowValidationResponse,
)
from webgis_gee.domain.models import DiagnosticsReport, ExecutionContext, WorkflowDefinition
from webgis_gee.application.services import WorkflowService
from webgis_gee.nodes.registry import NodeRegistry


class WorkflowApiFacade:
    """Route-facing facade that exposes stable API response models."""

    def __init__(self, adapter: WorkflowContractAdapter) -> None:
        self._adapter = adapter

    def validate_workflow(
        self,
        workflow: WorkflowDefinition | dict[str, Any],
    ) -> WorkflowValidationResponse:
        return self._adapter.validate_workflow_response(workflow)

    def submit_workflow(
        self,
        workflow: WorkflowDefinition | dict[str, Any],
        context: ExecutionContext | dict[str, Any] | None = None,
    ) -> WorkflowExecutionResponse:
        return self._adapter.submit_workflow_response(workflow, context)

    def run_workflow_job(
        self,
        payload: dict[str, Any],
    ) -> WorkflowExecutionResponse:
        return self._adapter.run_workflow_job_response(payload)

    def get_export_task_status(
        self,
        manifest_uri: str,
        *,
        gee_module: object | None = None,
        update_manifest: bool = False,
    ) -> ExportTaskStatusResponse:
        return self._adapter.get_export_task_status_response(
            manifest_uri,
            gee_module=gee_module,
            update_manifest=update_manifest,
        )

    def diagnose(self) -> DiagnosticsReport:
        return self._adapter.diagnose()


def create_default_facade() -> WorkflowService:
    registry = NodeRegistry()
    service = WorkflowService(registry)
    return service


def create_default_contract_adapter() -> WorkflowContractAdapter:
    return WorkflowContractAdapter(create_default_facade())


def create_default_api_facade() -> WorkflowApiFacade:
    return WorkflowApiFacade(create_default_contract_adapter())
