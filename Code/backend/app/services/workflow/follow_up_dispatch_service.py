"""Follow-up dispatch service.

Handles download follow-up task dispatch (Celery or inline) and stale workflow
cleanup on backend startup. Extracted from interaction_hub.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from uuid import uuid4

from app.core.logging import log_context
from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder, use_celery_executor
from app.tasks.download_tasks import dispatch_download_follow_up_task, execute_download_follow_up_task
from app.tasks.workflow_tasks import resolve_workflow_queue
from shared.contracts.api_contracts import (
    EventChannel,
    ExecutionStatus,
    LogLevel,
    WorkflowPriority,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)


class FollowUpDispatchService:
    """Dispatches follow-up download tasks and cleans up stale workflow runs."""

    def __init__(
        self,
        repository: SQLiteWorkflowRepository | None = None,
        persistence: WorkflowPersistenceService | None = None,
        transitions: WorkflowTransitionBuilder | None = None,
    ) -> None:
        self._repository = repository or SQLiteWorkflowRepository()
        self._persistence = persistence or WorkflowPersistenceService(self._repository)
        self._transitions = transitions or WorkflowTransitionBuilder()

    def dispatch_follow_up_tasks(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        follow_up_tasks: list[dict[str, object]],
        created_at: datetime,
    ) -> None:
        priority = {
            WorkflowPriority.low: 1,
            WorkflowPriority.normal: 5,
            WorkflowPriority.high: 8,
            WorkflowPriority.critical: 9,
        }[payload.priority]
        queue_name = resolve_workflow_queue(payload)
        for task_data in follow_up_tasks:
            # P0 修复：task_type 过滤条件与 download_service.build_follow_up_task 产出的值对齐
            if task_data.get("task_type") not in {"download_fetch", "download_fetch_placeholder"}:
                continue
            with log_context(run_id=run_id):
                try:
                    if use_celery_executor():
                        task_id = dispatch_download_follow_up_task(
                            task_data=task_data,
                            queue_name=queue_name,
                            priority=priority,
                        )
                        self._persistence.record_event(
                            run_id=run_id,
                            channel=EventChannel.system,
                            message="下载 follow-up task 已派发到 Celery。",
                            progress=100,
                            payload={
                                "task_type": task_data.get("task_type"),
                                "task_id": task_id,
                                "queue_name": queue_name,
                            },
                            created_at=created_at,
                        )
                    else:
                        inline_task_id = f"download-task-{uuid4().hex[:10]}"
                        execute_download_follow_up_task(
                            task_data={**task_data, "task_id": inline_task_id},
                        )
                        self._persistence.record_event(
                            run_id=run_id,
                            channel=EventChannel.system,
                            message="下载 follow-up task 已在本地执行完成。",
                            progress=100,
                            payload={
                                "task_type": task_data.get("task_type"),
                                "task_id": inline_task_id,
                            },
                            created_at=datetime.now(timezone.utc),
                        )
                except Exception:
                    logger.exception("Download follow-up dispatch failed")
                    self._persistence.record_event(
                        run_id=run_id,
                        channel=EventChannel.log,
                        level=LogLevel.error,
                        message="下载 follow-up task 派发失败。",
                        progress=100,
                        payload={
                            "task_type": task_data.get("task_type"),
                            "error_code": "download_follow_up_dispatch_failed",
                        },
                        created_at=datetime.now(timezone.utc),
                    )

    def cleanup_stale_workflow_runs(self) -> int:
        """后端启动时清理上一会话遗留的僵尸工作流。

        非终态（accepted/queued/running/retry_pending）的工作流在进程重启后
        不会再被 Celery worker 消费，会永久卡住。本方法将它们标记为 failed，
        使前端能感知失败并允许用户重试。
        返回被清理的工作流数量。
        """
        non_terminal_statuses = {
            ExecutionStatus.accepted,
            ExecutionStatus.queued,
            ExecutionStatus.running,
            ExecutionStatus.retry_pending,
        }
        now = datetime.now(timezone.utc)
        cleaned = 0
        for run in self._repository.list_runs():
            if run.status not in non_terminal_statuses:
                continue
            with log_context(run_id=run.run_id):
                logger.warning(
                    "Cleaning up stale workflow run (status=%s, updated_at=%s) on startup",
                    run.status.value,
                    run.updated_at.isoformat(),
                )
                payload = WorkflowSubmitRequest(
                    command_type=run.command_type,
                    command_label=run.command_label,
                    priority=run.priority,
                    resource_profile=run.resource_profile,
                    realtime_preferred=run.realtime_preferred,
                    queue_tag=run.queue_tag,
                    spatial_filter=run.spatial_filter,
                    time_range=run.time_range,
                    requested_outputs=run.requested_outputs,
                    client=run.client,
                    map_context=run.map_context,
                    config_overrides=run.config_overrides,
                )
                self._persistence.save_run_status(
                    run_status=self._transitions.build_execution_transition(
                        run_id=run.run_id,
                        payload=payload,
                        status=ExecutionStatus.failed,
                        progress=100,
                        message="工作流因后端重启被中断（僵尸任务清理）。",
                        created_at=run.created_at,
                        updated_at=now,
                        result_refs=run.result_refs,
                        result_dto=run.result_dto,
                        diagnostics=[
                            f"工作流在 {run.status.value} 状态下因后端进程重启而中断。",
                            "error_code=workflow_orphaned_by_restart",
                            f"last_status={run.status.value}",
                            f"last_updated_at={run.updated_at.isoformat()}",
                        ],
                        executor_metadata={
                            **run.executor_metadata,
                            "orphaned_at": now.isoformat(),
                            "cleanup_reason": "backend_restart",
                        },
                    )
                )
                self._persistence.record_event(
                    run_id=run.run_id,
                    channel=EventChannel.log,
                    level=LogLevel.warning,
                    message="工作流因后端重启被中断，已标记为失败。可点击重试重新提交。",
                    progress=100,
                    payload={
                        "cleanup_reason": "backend_restart",
                        "previous_status": run.status.value,
                    },
                    created_at=now,
                )
                cleaned += 1
        if cleaned > 0:
            logger.info("Cleaned up %d stale workflow run(s) on startup", cleaned)
        return cleaned
