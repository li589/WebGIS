from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from app.core.celery_app import celery_app, celery_available
from app.core.logging import ensure_logging_configured, log_context
from app.services.download_service import download_service
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import EventChannel, LogLevel, WorkflowEvent

logger = logging.getLogger(__name__)
ensure_logging_configured()


def execute_download_follow_up_task(*, task_data: dict[str, Any]) -> None:
    run_id = str(task_data["run_id"])
    task_id = str(task_data.get("task_id") or f"download-task-{uuid4().hex[:10]}")
    repository = SQLiteWorkflowRepository()
    with log_context(run_id=run_id, task_id=task_id):
        logger.info("Download follow-up task started")
        run = repository.get_run(run_id)
        if run is None:
            raise ValueError(f"Workflow run not found for download follow-up task: {run_id}")
        updated_at = datetime.now(timezone.utc)
        result_refs, diagnostics = download_service.complete_follow_up_task(
            run_id=run_id,
            result_refs=run.result_refs,
            cache_key=str(task_data["cache_key"]),
            summary_result_id=str(task_data["summary_result_id"]),
            manifest_result_id=str(task_data["manifest_result_id"]),
            updated_at=updated_at,
        )
        run.result_refs = result_refs
        run.diagnostics = [*run.diagnostics, *diagnostics]
        run.updated_at = updated_at
        run.message = "下载工作流执行完成，异步下载占位结果已回写。"
        repository.save_run(run)
        repository.append_event(
            WorkflowEvent(
                event_id=f"evt-{uuid4().hex[:10]}",
                run_id=run_id,
                channel=EventChannel.system,
                level=LogLevel.info,
                message="下载 follow-up task 已完成并回写 manifest。",
                created_at=updated_at,
                progress=100,
                payload={
                    "task_id": task_id,
                    "download_ticket_id": task_data.get("download_ticket_id"),
                    "cache_key": task_data.get("cache_key"),
                    "artifact_resource_key": task_data.get("artifact_resource_key"),
                },
            )
        )
        logger.info("Download follow-up task finished")


if celery_available and celery_app is not None:

    @celery_app.task(name="app.tasks.download_tasks.process_download_follow_up")
    def process_download_follow_up_task(task_data: dict[str, Any]) -> None:
        execute_download_follow_up_task(task_data=task_data)

else:

    def process_download_follow_up_task(task_data: dict[str, Any]) -> None:
        raise RuntimeError("Celery is not installed. Install backend dependencies before using celery executor.")


def dispatch_download_follow_up_task(*, task_data: dict[str, Any], queue_name: str, priority: int) -> str:
    if not celery_available or celery_app is None:
        raise RuntimeError("Celery is not installed. Install backend dependencies before using celery executor.")
    async_result = process_download_follow_up_task.apply_async(
        kwargs={"task_data": task_data},
        queue=queue_name,
        priority=priority,
    )
    return async_result.id
