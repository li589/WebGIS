"""Workflow transition builders.

Stateless builders for WorkflowRunStatusResponse transitions and SubmissionTransition
dataclass. Extracted from interaction_hub.py to separate transition object construction
from service orchestration logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.services.effective_config import get_task_executor
from app.tasks.workflow_tasks import resolve_workflow_channel, resolve_workflow_queue
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowEvent,
    WorkflowPriority,
    WorkflowResultReference,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)


@dataclass
class SubmissionTransition:
    """Submission phase transition: status + events + request_json flag."""

    status: WorkflowRunStatusResponse
    events: list[WorkflowEvent] = field(default_factory=list)
    request_json: bool = False


def use_celery_executor() -> bool:
    """Check if Celery executor is configured (env + runtime DB overlay)."""
    try:
        from app.services.effective_config import use_celery_executor_effective

        return use_celery_executor_effective()
    except Exception:
        return settings.workflow_executor.lower() == "celery"


class WorkflowTransitionBuilder:
    """Builds WorkflowRunStatusResponse transition objects for various workflow states.

    Stateless — all methods are pure functions that construct response objects.
    """

    @staticmethod
    def workflow_status_url(run_id: str) -> str:
        return f"/workflow-runs/{run_id}"

    @staticmethod
    def workflow_events_url(run_id: str) -> str:
        return f"/workflow-runs/{run_id}/events"

    def build_submission_transitions(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        accepted_at: datetime,
        queued_at: datetime,
        status_url: str,
        events_url: str,
        make_event_fn,
    ) -> list[SubmissionTransition]:
        """Build accepted + queued transitions for workflow submission.

        Args:
            make_event_fn: callable to create WorkflowEvent instances (from persistence service).
        """
        accepted_status = self.build_transition_status(
            run_id=run_id,
            payload=payload,
            status=ExecutionStatus.accepted,
            progress=3,
            message="工作流已创建，准备进入服务编排链。",
            created_at=accepted_at,
            updated_at=accepted_at,
            status_url=status_url,
            events_url=events_url,
        )
        queued_status = self.build_transition_status(
            run_id=run_id,
            payload=payload,
            status=ExecutionStatus.queued,
            progress=12,
            message="工作流已进入本地任务编排器。",
            created_at=accepted_at,
            updated_at=queued_at,
            status_url=status_url,
            events_url=events_url,
            executor_metadata={
                "executor": get_task_executor(),
                "dispatch_channel": resolve_workflow_channel(payload),
                "queue_name": resolve_workflow_queue(payload),
            },
        )
        return [
            SubmissionTransition(
                status=accepted_status,
                request_json=True,
                events=[
                    make_event_fn(
                        run_id=run_id,
                        channel="status",
                        message="工作流已创建。",
                        progress=3,
                        payload={"status": ExecutionStatus.accepted.value},
                        created_at=accepted_at,
                    ),
                    make_event_fn(
                        run_id=run_id,
                        channel="log",
                        message="已完成参数接收与协议校验。",
                        progress=8,
                        payload={"layer_id": payload.layer_id, "command_type": payload.command_type.value},
                    ),
                ],
            ),
            SubmissionTransition(
                status=queued_status,
                request_json=False,
                events=[
                    make_event_fn(
                        run_id=run_id,
                        channel="status",
                        message="工作流已进入任务层。",
                        progress=12,
                        payload={
                            "status": ExecutionStatus.queued.value,
                            "executor": get_task_executor(),
                            "dispatch_channel": resolve_workflow_channel(payload),
                            "queue_name": resolve_workflow_queue(payload),
                            "priority": payload.priority.value,
                            "resource_profile": payload.resource_profile.value,
                        },
                        created_at=queued_at,
                    )
                ],
            ),
        ]

    def build_execution_transition(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        status: ExecutionStatus,
        progress: int,
        message: str,
        created_at: datetime,
        updated_at: datetime,
        result_refs: list[WorkflowResultReference] | None = None,
        result_dto: dict[str, object] | None = None,
        diagnostics: list[str] | None = None,
        executor_metadata: dict[str, object] | None = None,
    ) -> WorkflowRunStatusResponse:
        return self.build_transition_status(
            run_id=run_id,
            payload=payload,
            status=status,
            progress=progress,
            message=message,
            created_at=created_at,
            updated_at=updated_at,
            status_url=self.workflow_status_url(run_id),
            events_url=self.workflow_events_url(run_id),
            result_refs=result_refs,
            result_dto=result_dto,
            diagnostics=diagnostics,
            executor_metadata=executor_metadata,
        )

    def build_running_transition(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        created_at: datetime,
        updated_at: datetime,
        status_url: str,
        events_url: str,
        executor_metadata: dict[str, object] | None = None,
    ) -> WorkflowRunStatusResponse:
        return self.build_transition_status(
            run_id=run_id,
            payload=payload,
            status=ExecutionStatus.running,
            progress=35,
            message="服务层正在执行真实工作流。",
            created_at=created_at,
            updated_at=updated_at,
            status_url=status_url,
            events_url=events_url,
            executor_metadata=executor_metadata,
        )

    def build_succeeded_transition(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        message: str,
        created_at: datetime,
        updated_at: datetime,
        status_url: str,
        events_url: str,
        result_refs: list[WorkflowResultReference] | None = None,
        result_dto: dict[str, object] | None = None,
        diagnostics: list[str] | None = None,
    ) -> WorkflowRunStatusResponse:
        return self.build_transition_status(
            run_id=run_id,
            payload=payload,
            status=ExecutionStatus.succeeded,
            progress=100,
            message=message,
            created_at=created_at,
            updated_at=updated_at,
            status_url=status_url,
            events_url=events_url,
            result_refs=result_refs,
            result_dto=result_dto,
            diagnostics=diagnostics,
        )

    def build_failed_transition(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        message: str,
        created_at: datetime,
        updated_at: datetime,
        status_url: str,
        events_url: str,
        diagnostics: list[str] | None = None,
    ) -> WorkflowRunStatusResponse:
        return self.build_transition_status(
            run_id=run_id,
            payload=payload,
            status=ExecutionStatus.failed,
            progress=100,
            message=message,
            created_at=created_at,
            updated_at=updated_at,
            status_url=status_url,
            events_url=events_url,
            diagnostics=diagnostics,
        )

    def build_retry_pending_transition(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        created_at: datetime,
        updated_at: datetime,
        status_url: str,
        events_url: str,
        category,
        current_attempt: int,
        next_attempt: int,
        backoff_seconds: float,
    ) -> WorkflowRunStatusResponse:
        """Build retry_pending status response."""
        return WorkflowRunStatusResponse(
            run_id=run_id,
            status=ExecutionStatus.retry_pending,
            command_type=payload.command_type,
            priority=payload.priority,
            created_at=created_at,
            updated_at=updated_at,
            status_url=status_url,
            events_url=events_url,
            message=f"工作流瞬态失败（{category.value}），等待第 {next_attempt} 次重试。",
            diagnostics=[
                f"failure_category={category.value}",
                f"attempt={current_attempt}",
                f"next_attempt={next_attempt}",
                f"backoff_seconds={backoff_seconds:.1f}",
                f"retryable={category.retryable}",
            ],
            progress=0,
        )

    def build_transition_status(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        status: ExecutionStatus,
        progress: int,
        message: str,
        created_at: datetime,
        updated_at: datetime,
        status_url: str | None = None,
        events_url: str | None = None,
        result_refs: list[WorkflowResultReference] | None = None,
        result_dto: dict[str, object] | None = None,
        diagnostics: list[str] | None = None,
        executor_metadata: dict[str, object] | None = None,
    ) -> WorkflowRunStatusResponse:
        return WorkflowRunStatusResponse(
            run_id=run_id,
            status_url=status_url,
            events_url=events_url,
            command_type=payload.command_type,
            command_label=payload.command_label,
            layer_id=payload.layer_id or payload.map_context.active_layer_id,
            priority=payload.priority,
            resource_profile=payload.resource_profile,
            realtime_preferred=payload.realtime_preferred,
            queue_tag=payload.queue_tag,
            status=status,
            progress=progress,
            message=message,
            created_at=created_at,
            updated_at=updated_at,
            spatial_filter=payload.spatial_filter,
            time_range=payload.time_range,
            requested_outputs=payload.requested_outputs,
            client=payload.client,
            map_context=payload.map_context,
            config_overrides=payload.config_overrides,
            executor_metadata=executor_metadata or {},
            result_refs=result_refs or [],
            result_dto=result_dto or None,
            diagnostics=diagnostics or [],
        )
