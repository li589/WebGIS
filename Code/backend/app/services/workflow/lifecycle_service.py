"""Workflow lifecycle service.

Handles workflow cancel, retry, timeout, failure, and success finalization.
Uses late binding to access submission service (for retry → submit_workflow)
to break the circular dependency: lifecycle → submission → lifecycle.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import TYPE_CHECKING

from app.core.celery_app import revoke_task
from app.core.config import settings
from app.core.logging import log_context
from app.services.failure_classifier import FailureClassifier
from app.services.result_storage import result_storage_service
from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder, use_celery_executor
from app.services.workflow.follow_up_dispatch_service import FollowUpDispatchService
from app.tasks.workflow_tasks import dispatch_workflow_task
from shared.contracts.api_contracts import (
    EventChannel,
    ExecutionStatus,
    FailureCategory,
    LogLevel,
    WorkflowAcceptedResponse,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)

if TYPE_CHECKING:
    from app.services.workflow.submission_service import WorkflowSubmissionService

logger = logging.getLogger(__name__)


class WorkflowLifecycleService:
    """Handles workflow lifecycle transitions: cancel, retry, finalize success/failure."""

    def __init__(
        self,
        repository: SQLiteWorkflowRepository | None = None,
        persistence: WorkflowPersistenceService | None = None,
        transitions: WorkflowTransitionBuilder | None = None,
        follow_up: FollowUpDispatchService | None = None,
    ) -> None:
        self._repository = repository or SQLiteWorkflowRepository()
        self._persistence = persistence or WorkflowPersistenceService(self._repository)
        self._transitions = transitions or WorkflowTransitionBuilder()
        self._follow_up = follow_up or FollowUpDispatchService(self._repository, self._persistence, self._transitions)
        self._submission: "WorkflowSubmissionService | None" = None

    def set_submission_service(self, submission: "WorkflowSubmissionService") -> None:
        """Late binding to break circular dependency."""
        self._submission = submission

    @property
    def submission(self) -> "WorkflowSubmissionService":
        if self._submission is None:
            raise RuntimeError("Submission service not set. Call set_submission_service() first.")
        return self._submission

    def cancel_workflow_run(self, run_id: str) -> WorkflowRunStatusResponse:
        now = datetime.now(timezone.utc)
        current_run = self._repository.get_run(run_id)
        if current_run is None:
            raise ValueError(f"Workflow run not found: {run_id}")

        if current_run.status in (ExecutionStatus.succeeded, ExecutionStatus.failed, ExecutionStatus.cancelled):
            raise ValueError(f"Cannot cancel workflow in terminal state: {current_run.status.value}")

        if use_celery_executor() and current_run.executor_metadata:
            task_id = current_run.executor_metadata.get("task_id")
            if task_id:
                revoke_task(task_id, terminate=True)

        self._persistence.save_run_status(
            run_status=self._transitions.build_execution_transition(
                run_id=run_id,
                payload=WorkflowSubmitRequest(
                    command_type=current_run.command_type,
                    command_label=current_run.command_label,
                    priority=current_run.priority,
                    resource_profile=current_run.resource_profile,
                    realtime_preferred=current_run.realtime_preferred,
                    queue_tag=current_run.queue_tag,
                    spatial_filter=current_run.spatial_filter,
                    time_range=current_run.time_range,
                    requested_outputs=current_run.requested_outputs,
                    client=current_run.client,
                    map_context=current_run.map_context,
                    config_overrides=current_run.config_overrides,
                ),
                status=ExecutionStatus.cancelled,
                progress=100,
                message="工作流已被用户取消。",
                created_at=current_run.created_at,
                updated_at=now,
                result_refs=current_run.result_refs,
                result_dto=current_run.result_dto,
                diagnostics=[
                    "工作流已被取消。",
                    "error_code=workflow_cancelled_by_user",
                ],
                executor_metadata={
                    **current_run.executor_metadata,
                    "cancelled_at": now.isoformat(),
                    "cancelled_by": "user",
                },
            )
        )
        self._persistence.record_event(
            run_id=run_id,
            channel=EventChannel.status,
            message="工作流已被取消。",
            progress=100,
            payload={"status": ExecutionStatus.cancelled.value},
            created_at=now,
        )
        return self._repository.get_run(run_id)

    def retry_workflow_run(self, run_id: str) -> WorkflowAcceptedResponse:
        now = datetime.now(timezone.utc)
        request_json = self._repository.get_run_request_json(run_id)
        if request_json is None:
            raise ValueError(f"Cannot retry: no request found for run {run_id}")

        payload = WorkflowSubmitRequest.model_validate_json(request_json)
        new_response = self.submission.submit_workflow(payload)
        new_run = self._repository.get_run(new_response.run_id)

        if new_run:
            self._persistence.save_run_status(
                run_status=self._transitions.build_execution_transition(
                    run_id=new_response.run_id,
                    payload=payload,
                    status=new_run.status,
                    progress=new_run.progress,
                    message=new_run.message,
                    created_at=new_run.created_at,
                    updated_at=now,
                    result_refs=new_run.result_refs,
                    result_dto=new_run.result_dto,
                    diagnostics=new_run.diagnostics,
                    executor_metadata={
                        **new_run.executor_metadata,
                        "retry_of_run_id": run_id,
                    },
                )
            )
        return new_response

    def handle_workflow_timeout(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        created_at: datetime,
    ) -> None:
        """Celery 软超时：进入 failed 状态，标记为超时原因（不可重试）。"""
        current_attempt = payload.retry_attempt or 1
        exc = TimeoutError(
            f"Workflow execution exceeded soft time limit "
            f"({settings.celery_task_soft_time_limit}s) and was terminated."
        )
        category = FailureCategory.terminal_failure
        self.finalize_workflow_failure(
            run_id=run_id,
            payload=payload,
            created_at=created_at,
            exc=exc,
            category=category,
            attempt_count=current_attempt,
        )

    def handle_workflow_failure(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        created_at: datetime,
        exc: Exception,
    ) -> None:
        """失败分类处理：可重试 → retry_pending + 调度重试；不可重试 → failed。"""
        category = FailureClassifier.classify(exc)
        retry_policy = payload.retry_policy
        current_attempt = payload.retry_attempt or 1

        if category.retryable and current_attempt < retry_policy.max_attempts:
            next_attempt = current_attempt + 1
            backoff_seconds = retry_policy.compute_backoff(current_attempt)
            self.finalize_workflow_retry(
                run_id=run_id,
                payload=payload,
                created_at=created_at,
                exc=exc,
                category=category,
                current_attempt=current_attempt,
                next_attempt=next_attempt,
                backoff_seconds=backoff_seconds,
            )
        else:
            self.finalize_workflow_failure(
                run_id=run_id,
                payload=payload,
                created_at=created_at,
                exc=exc,
                category=category,
                attempt_count=current_attempt,
            )

    def finalize_workflow_retry(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        created_at: datetime,
        exc: Exception,
        category: FailureCategory,
        current_attempt: int,
        next_attempt: int,
        backoff_seconds: float,
    ) -> None:
        """瞬态失败进入 retry_pending 状态，并调度延迟重试。"""
        retry_at = datetime.now(timezone.utc)
        self._persistence.save_run_status(
            run_status=self._transitions.build_retry_pending_transition(
                run_id=run_id,
                payload=payload,
                created_at=created_at,
                updated_at=retry_at,
                status_url=self._transitions.workflow_status_url(run_id),
                events_url=self._transitions.workflow_events_url(run_id),
                category=category,
                current_attempt=current_attempt,
                next_attempt=next_attempt,
                backoff_seconds=backoff_seconds,
            )
        )
        self._persistence.record_event(
            run_id=run_id,
            channel=EventChannel.log,
            level=LogLevel.warning,
            message=(
                f"工作流瞬态失败（{category.value}），"
                f"第 {current_attempt}/{payload.retry_policy.max_attempts} 次尝试，"
                f"将在 {backoff_seconds:.1f}s 后重试。"
            ),
            progress=50,
            payload={
                "failure_category": category.value,
                "attempt": current_attempt,
                "next_attempt": next_attempt,
                "backoff_seconds": backoff_seconds,
                "error_message": str(exc)[:500],
            },
            created_at=retry_at,
        )
        self._schedule_retry(
            run_id=run_id,
            payload=payload,
            next_attempt=next_attempt,
            backoff_seconds=backoff_seconds,
        )

    def finalize_workflow_success(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        execution,
        requested_at: datetime,
    ) -> None:
        result_refs, spill_diagnostics = result_storage_service.materialize_result_refs(
            run_id=run_id,
            result_refs=execution.result_refs,
        )
        logger.info(
            "[LifecycleService] materialize_result_refs: run_id=%s result_refs_count=%d spill_count=%d",
            run_id, len(result_refs), len(spill_diagnostics),
        )
        for r in result_refs:
            logger.info(
                "[LifecycleService] result_ref: result_id=%s result_kind=%s resource_url=%s inline_data=%s",
                r.result_id, r.result_kind, r.resource_url, "present" if r.inline_data else "None",
            )
        diagnostics = [*execution.diagnostics, *spill_diagnostics]
        result_dto = self._persistence.augment_result_dto(
            execution.result_dto,
            materialized_result_count=len(result_refs),
            spill_diagnostics_count=len(spill_diagnostics),
        )
        completed_at = datetime.now(timezone.utc)
        self._persistence.save_run_status(
            run_status=self._transitions.build_succeeded_transition(
                run_id=run_id,
                payload=payload,
                message=execution.message,
                created_at=requested_at,
                updated_at=completed_at,
                status_url=self._transitions.workflow_status_url(run_id),
                events_url=self._transitions.workflow_events_url(run_id),
                result_refs=result_refs,
                result_dto=result_dto,
                diagnostics=diagnostics,
            )
        )
        for event in execution.events:
            self._persistence.record_event(event=event)
        if spill_diagnostics:
            self._persistence.record_event(
                run_id=run_id,
                channel=EventChannel.system,
                message="大结果已自动落盘为 artifact 引用。",
                progress=96,
                payload={"spill_count": len(spill_diagnostics)},
                created_at=completed_at,
            )
        self._persistence.record_event(
            run_id=run_id,
            channel=EventChannel.status,
            message="工作流执行成功。",
            progress=100,
            payload={
                "status": ExecutionStatus.succeeded.value,
                "result_count": len(result_refs),
            },
            created_at=completed_at,
        )
        if execution.follow_up_tasks:
            self._follow_up.dispatch_follow_up_tasks(
                run_id=run_id,
                payload=payload,
                follow_up_tasks=execution.follow_up_tasks,
                created_at=completed_at,
            )

    def finalize_workflow_failure(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        created_at: datetime,
        exc: Exception | None = None,
        category: FailureCategory | None = None,
        attempt_count: int = 1,
    ) -> None:
        failed_at = datetime.now(timezone.utc)
        diagnostics = [
            "workflow-runs 已进入服务编排链，但本次执行失败。",
            f"error_code=workflow_execution_failed",
            f"attempt_count={attempt_count}",
        ]
        if category is not None:
            diagnostics.append(f"failure_category={category.value}")
            diagnostics.append(f"retryable={category.retryable}")
        if exc is not None:
            diagnostics.append(f"error_type={type(exc).__name__}")
            diagnostics.append(f"error_message={str(exc)[:200]}")
            diagnostics.extend(self._persistence.extract_exception_diagnostics(exc))

        failure_message = "工作流执行失败，请查看服务端日志。"
        if exc is not None and category == FailureCategory.validation_error:
            failure_message = f"工作流校验失败：{str(exc)[:180]}"

        self._persistence.save_run_status(
            run_status=self._transitions.build_failed_transition(
                run_id=run_id,
                payload=payload,
                message=failure_message,
                created_at=created_at,
                updated_at=failed_at,
                status_url=self._transitions.workflow_status_url(run_id),
                events_url=self._transitions.workflow_events_url(run_id),
                diagnostics=diagnostics,
            )
        )
        self._persistence.record_event(
            run_id=run_id,
            channel=EventChannel.log,
            level=LogLevel.error,
            message="工作流执行失败。",
            progress=100,
            payload={
                "error_code": "workflow_execution_failed",
                "failure_category": category.value if category else "unknown",
                "attempt_count": attempt_count,
                "error_type": type(exc).__name__ if exc else "unknown",
            },
            created_at=failed_at,
        )

    def _schedule_retry(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        next_attempt: int,
        backoff_seconds: float,
    ) -> None:
        """调度延迟重试任务。

        修复：调度失败时不再静默吞掉异常，而是将 workflow 从 retry_pending
        转为 failed，避免僵尸任务永久卡在 retry_pending 状态。
        """
        try:
            retry_payload = payload.model_copy(update={"retry_attempt": next_attempt})
            dispatch_workflow_task(
                run_id=run_id,
                payload=retry_payload,
                countdown=backoff_seconds,
            )
        except Exception as schedule_exc:
            logger.exception(
                "Failed to schedule workflow retry for run %s, transitioning to failed",
                run_id,
            )
            self.finalize_workflow_failure(
                run_id=run_id,
                payload=payload,
                created_at=datetime.now(timezone.utc),
                exc=schedule_exc,
                category=FailureCategory.terminal_failure,
                attempt_count=next_attempt - 1,
            )
