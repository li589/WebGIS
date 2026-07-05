from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from webgis_gee.application.services import WorkflowService
from webgis_gee.domain.models import DiagnosticsReport, ExecutionContext, RunResult, WorkflowDefinition
from webgis_gee.workflow.versioning import TerminalPlanResponse, TerminalPlanSummary


class WorkflowSubmissionPayload(BaseModel):
    """Thin request contract for workflow submission endpoints."""

    workflow: WorkflowDefinition | dict[str, Any]
    context: ExecutionContext | dict[str, Any] | None = None


class ExportTaskStatusPayload(BaseModel):
    """Thin request contract for export task status polling endpoints."""

    manifest_uri: str = Field(min_length=1)
    update_manifest: bool = False


class WorkflowJobPayload(BaseModel):
    """Serialized payload contract for Celery worker execution."""

    workflow: WorkflowDefinition | dict[str, Any]
    context: ExecutionContext | dict[str, Any] | None = None


class SavebackTerminalPlanPayload(BaseModel):
    """Stable API contract for terminal saveback plans."""

    action: str
    reasons: list[str] = Field(default_factory=list)
    summary: TerminalPlanSummary


class SavebackTerminalPlanResponse(BaseModel):
    """Top-level response model for API consumers."""

    terminal_plan: SavebackTerminalPlanPayload


class WorkflowValidationResponse(BaseModel):
    """Route-friendly validation response with typed terminal plan projections."""

    workflow: WorkflowDefinition
    saveback_terminal_plan: SavebackTerminalPlanPayload | None = None
    saveback_terminal_plans: dict[str, SavebackTerminalPlanPayload] = Field(default_factory=dict)

    @classmethod
    def from_workflow(cls, workflow: WorkflowDefinition) -> "WorkflowValidationResponse":
        saveback_terminal_plans = _collect_saveback_terminal_plans(
            workflow=workflow,
            outputs=None,
        )
        return cls(
            workflow=workflow,
            saveback_terminal_plan=_select_primary_saveback_terminal_plan(
                saveback_terminal_plans,
                workflow=workflow,
            ),
            saveback_terminal_plans=saveback_terminal_plans,
        )


class WorkflowExecutionResponse(BaseModel):
    """Stable API response model for workflow execution routes."""

    run_id: str
    workflow_id: str
    status: str
    node_results: list[dict[str, Any]] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    saveback_terminal_plan: SavebackTerminalPlanPayload | None = None
    saveback_terminal_plans: dict[str, SavebackTerminalPlanPayload] = Field(default_factory=dict)

    @classmethod
    def from_run_result(
        cls,
        result: RunResult,
        *,
        workflow: WorkflowDefinition | None = None,
    ) -> "WorkflowExecutionResponse":
        saveback_terminal_plans = _collect_saveback_terminal_plans(
            workflow=workflow,
            outputs=result.outputs,
        )
        return cls(
            run_id=result.run_id,
            workflow_id=result.workflow_id,
            status=result.status.value,
            node_results=[node_result.model_dump(mode="python") for node_result in result.node_results],
            outputs=result.outputs,
            artifacts=[artifact.model_dump(mode="python") for artifact in result.artifacts],
            warnings=list(result.warnings),
            errors=list(result.errors),
            saveback_terminal_plan=_select_primary_saveback_terminal_plan(
                saveback_terminal_plans,
                workflow=workflow,
            ),
            saveback_terminal_plans=saveback_terminal_plans,
        )


class ExportTaskStatusResponse(BaseModel):
    """Stable API response model for export polling routes."""

    status: str
    state: str
    task_id: str | None = None
    started: bool
    manifest_uri: str | None = None
    polled_at: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_status_payload(cls, payload: dict[str, Any]) -> "ExportTaskStatusResponse":
        return cls.model_validate(payload)


def _collect_saveback_terminal_plans(
    *,
    workflow: WorkflowDefinition | None,
    outputs: dict[str, Any] | None,
) -> dict[str, SavebackTerminalPlanPayload]:
    plans: dict[str, SavebackTerminalPlanPayload] = {}

    if workflow is not None:
        metadata_plan = workflow.metadata.get("saveback_terminal_plan", {})
        if isinstance(metadata_plan, dict):
            node_terminals = metadata_plan.get("node_terminals", [])
            if isinstance(node_terminals, list):
                for item in node_terminals:
                    if not isinstance(item, dict):
                        continue
                    node_id = item.get("node_id")
                    if not isinstance(node_id, str) or not node_id:
                        continue
                    plans[node_id] = SavebackTerminalPlanPayload.model_validate(
                        {
                            "action": item.get("action"),
                            "reasons": item.get("reasons", []),
                            "summary": item.get("summary", {}),
                        }
                    )

    if outputs is not None:
        for output_name, output_value in outputs.items():
            if not output_name.endswith(".saveback_terminal_plan") or not isinstance(output_value, dict):
                continue
            node_id = output_name.removesuffix(".saveback_terminal_plan")
            plans[node_id] = SavebackTerminalPlanPayload.model_validate(output_value)

    return plans


def _select_primary_saveback_terminal_plan(
    plans: dict[str, SavebackTerminalPlanPayload],
    *,
    workflow: WorkflowDefinition | None = None,
) -> SavebackTerminalPlanPayload | None:
    if not plans:
        return None
    workflow_node_order: dict[str, int] = {}
    if workflow is not None:
        workflow_node_order = {
            node.node_id: index
            for index, node in enumerate(workflow.nodes)
        }

    def sort_key(item: tuple[str, SavebackTerminalPlanPayload]) -> tuple[int, int, str]:
        node_id, plan = item
        action_priority = 0 if plan.action == "writeback_required" else 1
        node_priority = workflow_node_order.get(node_id, len(workflow_node_order))
        return (action_priority, node_priority, node_id)

    _, primary_plan = min(plans.items(), key=sort_key)
    return primary_plan


class WorkflowContractAdapter:
    """Thin integration adapter used by FastAPI/Celery layers in WebGIS."""

    def __init__(self, service: WorkflowService) -> None:
        self._service = service

    def validate_workflow(
        self,
        workflow: WorkflowDefinition | dict[str, Any],
    ) -> WorkflowDefinition:
        workflow_model = self._service.normalize_workflow_definition(workflow)
        return self._service.validate_workflow(workflow_model)

    def validate_workflow_response(
        self,
        workflow: WorkflowDefinition | dict[str, Any],
    ) -> WorkflowValidationResponse:
        validated_workflow = self.validate_workflow(workflow)
        return WorkflowValidationResponse.from_workflow(validated_workflow)

    def submit_workflow(
        self,
        workflow: WorkflowDefinition | dict[str, Any],
        context: ExecutionContext | dict[str, Any] | None = None,
    ) -> RunResult:
        workflow_model = self._service.normalize_workflow_definition(workflow)
        context_model = None if context is None else ExecutionContext.model_validate(context)
        return self._service.execute_workflow(workflow_model, context_model)

    def submit_workflow_response(
        self,
        workflow: WorkflowDefinition | dict[str, Any],
        context: ExecutionContext | dict[str, Any] | None = None,
    ) -> WorkflowExecutionResponse:
        workflow_model = self._service.normalize_workflow_definition(workflow)
        context_model = None if context is None else ExecutionContext.model_validate(context)
        result = self._service.execute_workflow(workflow_model, context_model)
        return WorkflowExecutionResponse.from_run_result(result, workflow=workflow_model)

    def get_export_task_status(
        self,
        manifest_uri: str,
        *,
        gee_module: object | None = None,
        update_manifest: bool = False,
    ) -> dict[str, object]:
        request = ExportTaskStatusPayload(
            manifest_uri=manifest_uri,
            update_manifest=update_manifest,
        )
        return self._service.poll_export_task(
            manifest_uri=request.manifest_uri,
            gee_module=gee_module,
            update_manifest=request.update_manifest,
        )

    def get_export_task_status_response(
        self,
        manifest_uri: str,
        *,
        gee_module: object | None = None,
        update_manifest: bool = False,
    ) -> ExportTaskStatusResponse:
        return ExportTaskStatusResponse.from_status_payload(
            self.get_export_task_status(
                manifest_uri,
                gee_module=gee_module,
                update_manifest=update_manifest,
            )
        )

    def run_workflow_job(
        self,
        payload: WorkflowJobPayload | WorkflowSubmissionPayload | dict[str, Any],
    ) -> RunResult:
        request = WorkflowJobPayload.model_validate(payload)
        return self.submit_workflow(request.workflow, request.context)

    def run_workflow_job_response(
        self,
        payload: WorkflowJobPayload | WorkflowSubmissionPayload | dict[str, Any],
    ) -> WorkflowExecutionResponse:
        request = WorkflowJobPayload.model_validate(payload)
        return self.submit_workflow_response(request.workflow, request.context)

    def diagnose(self) -> DiagnosticsReport:
        return self._service.diagnose()
