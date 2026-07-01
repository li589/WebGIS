from __future__ import annotations

from typing import Any

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings
from app.services.analysis_workflow_service import analysis_workflow_service
from app.services.download_workflow_service import download_workflow_service
from app.services.provider_workflow_service import provider_workflow_service
from app.services.workflow_execution import WorkflowExecutionResult
from shared.contracts.api_contracts import (
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowResourceProfile,
    WorkflowSubmitRequest,
)


def execute_workflow_task(*, run_id: str, payload: WorkflowSubmitRequest, requested_at, event_factory) -> WorkflowExecutionResult:
    if provider_workflow_service.supports(payload):
        handler = provider_workflow_service.execute
    else:
        task_map = {
            WorkflowCommandType.analysis: analysis_workflow_service.execute,
            WorkflowCommandType.export: analysis_workflow_service.execute,
            WorkflowCommandType.custom: analysis_workflow_service.execute,
            WorkflowCommandType.layer_preview: download_workflow_service.execute,
            WorkflowCommandType.refresh_data: download_workflow_service.execute,
            WorkflowCommandType.sync_demo: download_workflow_service.execute,
        }
        handler = task_map[payload.command_type]
    return handler(
        run_id=run_id,
        payload=payload,
        requested_at=requested_at,
        event_factory=event_factory,
    )


def resolve_workflow_channel(payload: WorkflowSubmitRequest) -> str:
    if payload.command_type in {
        WorkflowCommandType.refresh_data,
        WorkflowCommandType.sync_demo,
        WorkflowCommandType.layer_preview,
    }:
        return "download"
    return "analysis"


def resolve_workflow_queue(payload: WorkflowSubmitRequest) -> str:
    if payload.queue_tag:
        return payload.queue_tag
    channel = resolve_workflow_channel(payload)
    is_realtime = payload.realtime_preferred or payload.priority in {WorkflowPriority.high, WorkflowPriority.critical}
    if channel == "download":
        return settings.workflow_queue_download_realtime if is_realtime else settings.workflow_queue_download_standard
    if payload.resource_profile == WorkflowResourceProfile.batch:
        return settings.workflow_queue_analysis_batch
    if payload.resource_profile == WorkflowResourceProfile.heavy:
        return settings.workflow_queue_analysis_heavy
    if is_realtime:
        return settings.workflow_queue_realtime
    return settings.workflow_queue_analysis_standard


if celery_available and celery_app is not None:

    @celery_app.task(name="app.tasks.workflow_tasks.process_workflow_run")
    def process_workflow_run_task(run_id: str, payload_data: dict[str, Any]) -> None:
        from app.services.interaction_hub import interaction_hub

        payload = WorkflowSubmitRequest.model_validate(payload_data)
        interaction_hub.process_workflow_run(run_id, payload)

else:

    def process_workflow_run_task(run_id: str, payload_data: dict[str, Any]) -> None:
        raise RuntimeError("Celery is not installed. Install backend dependencies before using celery executor.")


def dispatch_workflow_task(run_id: str, payload: WorkflowSubmitRequest) -> str:
    if not celery_available or celery_app is None:
        raise RuntimeError("Celery is not installed. Install backend dependencies before using celery executor.")

    async_result = process_workflow_run_task.apply_async(
        kwargs={"run_id": run_id, "payload_data": payload.model_dump(mode="json")},
        queue=resolve_workflow_queue(payload),
        priority={
            WorkflowPriority.low: 1,
            WorkflowPriority.normal: 5,
            WorkflowPriority.high: 8,
            WorkflowPriority.critical: 9,
        }[payload.priority],
    )
    return async_result.id
