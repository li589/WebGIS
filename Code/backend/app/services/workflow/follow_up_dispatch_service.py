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
from app.services.workflow.transition_builder import (
    WorkflowTransitionBuilder,
    use_celery_executor,
)
from app.tasks.download_tasks import (
    dispatch_download_follow_up_task,
    execute_download_follow_up_task,
)
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
            if task_data.get("task_type") not in {
                "download_fetch",
                "download_fetch_placeholder",
            }:
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
        """后端启动时清理真正无法继续的僵尸工作流。

        重要：仅重启 FastAPI **不会** 停止 Celery worker。此前把所有非终态
        run 一律标 failed，会导致 worker 仍在跑、前端却显示失败/超时，且新
        任务被卡在队列（worker 仍被旧任务占用）。

        策略：
        - ``running``：永不因 FastAPI 启动清理（worker 可能仍在执行）。
        - ``accepted`` / ``queued`` / ``retry_pending``：仅当 Celery 侧已无
          对应 task（不在 active/reserved/unacked/队列中）且超过宽限时间
          时才标记失败。
        """
        from datetime import timedelta

        non_terminal_queue_statuses = {
            ExecutionStatus.accepted,
            ExecutionStatus.queued,
            ExecutionStatus.retry_pending,
        }
        now = datetime.now(timezone.utc)
        grace = timedelta(minutes=15)
        live_task_ids = self._collect_live_celery_task_ids()
        cleaned = 0
        for run in self._repository.list_runs():
            if run.status == ExecutionStatus.running:
                # Worker may still be computing after an API-only restart.
                continue
            if run.status not in non_terminal_queue_statuses:
                continue
            age = now - (
                run.updated_at
                if run.updated_at.tzinfo
                else run.updated_at.replace(tzinfo=timezone.utc)
            )
            if age < grace:
                continue
            task_id = str((run.executor_metadata or {}).get("task_id") or "").strip()
            if task_id and task_id in live_task_ids:
                continue
            with log_context(run_id=run.run_id):
                logger.warning(
                    "Cleaning up stale queued workflow run (status=%s, updated_at=%s, task_id=%s)",
                    run.status.value,
                    run.updated_at.isoformat(),
                    task_id or "-",
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
                        message="工作流排队超时且 Celery 侧已无对应任务（僵尸任务清理）。",
                        created_at=run.created_at,
                        updated_at=now,
                        result_refs=run.result_refs,
                        result_dto=run.result_dto,
                        diagnostics=[
                            f"工作流在 {run.status.value} 状态下超过 {int(grace.total_seconds())}s 且无活跃 Celery 任务。",
                            "error_code=workflow_orphaned_stale_queue",
                            f"last_status={run.status.value}",
                            f"last_updated_at={run.updated_at.isoformat()}",
                        ],
                        executor_metadata={
                            **run.executor_metadata,
                            "orphaned_at": now.isoformat(),
                            "cleanup_reason": "stale_queue_no_celery_task",
                        },
                    )
                )
                self._persistence.record_event(
                    run_id=run.run_id,
                    channel=EventChannel.log,
                    level=LogLevel.warning,
                    message="工作流排队超时且无 Celery 任务，已标记为失败。可点击重试重新提交。",
                    progress=100,
                    payload={
                        "cleanup_reason": "stale_queue_no_celery_task",
                        "previous_status": run.status.value,
                    },
                    created_at=now,
                )
                cleaned += 1
        if cleaned > 0:
            logger.info("Cleaned up %d stale workflow run(s) on startup", cleaned)
        return cleaned

    @staticmethod
    def _collect_live_celery_task_ids() -> set[str]:
        """Return task ids currently active, reserved, or unacked in the broker."""
        live: set[str] = set()
        try:
            from app.core.celery_app import celery_app

            inspector = celery_app.control.inspect(timeout=2.0)
            if inspector is not None:
                for bucket in (inspector.active() or {}, inspector.reserved() or {}):
                    for tasks in bucket.values():
                        for task in tasks or []:
                            task_id = str(task.get("id") or "").strip()
                            if task_id:
                                live.add(task_id)
        except Exception:
            logger.debug("Celery inspect failed during stale cleanup", exc_info=True)

        try:
            import json
            from urllib.parse import urlparse

            import redis

            from app.core.config import settings

            parsed = urlparse(settings.redis_url)
            client = redis.Redis(
                host=parsed.hostname or "127.0.0.1",
                port=parsed.port or 6379,
                db=int((parsed.path or "/0").lstrip("/") or "0"),
            )
            unacked = client.hgetall("unacked") or {}
            for raw in unacked.values():
                try:
                    payload = json.loads(raw)
                    # kombu format: [message_dict, ...] or nested
                    msg = (
                        payload[0] if isinstance(payload, list) and payload else payload
                    )
                    headers = (
                        (msg or {}).get("headers") if isinstance(msg, dict) else {}
                    )
                    task_id = str((headers or {}).get("id") or "").strip()
                    if task_id:
                        live.add(task_id)
                except Exception:
                    continue
        except Exception:
            logger.debug(
                "Redis unacked scan failed during stale cleanup", exc_info=True
            )
        return live
