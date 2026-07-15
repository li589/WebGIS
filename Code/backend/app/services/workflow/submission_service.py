"""Workflow submission service.

Handles workflow submission, execution dispatch, and capacity validation.
Uses late binding to access lifecycle service (for finalize/handle methods)
to break the circular dependency: submission → lifecycle → submission.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.logging import ensure_logging_configured, log_context
from app.services.result_storage import result_storage_service
from app.services.workflow_request_resolver import normalize_workflow_submit_request
from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import WorkflowTransitionBuilder, use_celery_executor
from app.services.workflow.follow_up_dispatch_service import FollowUpDispatchService
from app.services.workflow.run_class import (
    RUN_CLASS_BUSINESS,
    RUN_CLASS_WEATHER_TILE,
    resolve_workflow_run_class,
)
from app.tasks.workflow_tasks import (
    dispatch_workflow_task,
    execute_workflow_task,
    resolve_workflow_channel,
    resolve_workflow_queue,
)
from shared.contracts.api_contracts import (
    EventChannel,
    ExecutionStatus,
    LogLevel,
    WorkflowAcceptedResponse,
    WorkflowEventsResponse,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)

if TYPE_CHECKING:
    from app.services.workflow.lifecycle_service import WorkflowLifecycleService

logger = logging.getLogger(__name__)
ensure_logging_configured()


class WorkflowSubmissionService:
    """Handles workflow submission, execution, and query operations."""

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
        self._lifecycle: "WorkflowLifecycleService | None" = None

    def set_lifecycle_service(self, lifecycle: "WorkflowLifecycleService") -> None:
        """Late binding to break circular dependency."""
        self._lifecycle = lifecycle

    @property
    def lifecycle(self) -> "WorkflowLifecycleService":
        if self._lifecycle is None:
            raise RuntimeError("Lifecycle service not set. Call set_lifecycle_service() first.")
        return self._lifecycle

    def submit_workflow(self, payload: WorkflowSubmitRequest) -> WorkflowAcceptedResponse:
        payload = normalize_workflow_submit_request(payload)
        now = datetime.now(timezone.utc)
        run_id = f"run-{uuid4().hex[:12]}"
        status_url = self._transitions.workflow_status_url(run_id)
        events_url = self._transitions.workflow_events_url(run_id)
        request_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
        run_class = resolve_workflow_run_class(payload)
        with log_context(run_id=run_id):
            self._assert_workflow_capacity(run_class)
            self._validate_requested_outputs(payload)
            logger.info("Workflow accepted run_class=%s", run_class)
            accepted_at = now
            queued_at = datetime.now(timezone.utc)
            submission_transitions = self._transitions.build_submission_transitions(
                run_id=run_id,
                payload=payload,
                accepted_at=accepted_at,
                queued_at=queued_at,
                status_url=status_url,
                events_url=events_url,
                make_event_fn=self._persistence.make_event,
            )
            for transition in submission_transitions:
                self._persistence.save_run_status(
                    run_status=transition.status,
                    request_json=request_json if transition.request_json else None,
                    run_class=run_class if transition.request_json else None,
                )
                for event in transition.events:
                    self._persistence.record_event(event=event)

            if use_celery_executor():
                self._dispatch_async_workflow(run_id, payload)
            else:
                self.process_workflow_run(run_id, payload)

            return WorkflowAcceptedResponse(
                run_id=run_id,
                status=ExecutionStatus.accepted,
                status_url=status_url,
                events_url=events_url,
                created_at=now,
                message="工作流已提交，可轮询状态、事件与结果引用。",
            )

    def process_workflow_run(self, run_id: str, payload: WorkflowSubmitRequest) -> None:
        current_run = self._repository.get_run(run_id)
        now = datetime.now(timezone.utc)
        created_at = current_run.created_at if current_run is not None else now

        with log_context(run_id=run_id):
            try:
                running_at = datetime.now(timezone.utc)
                logger.info("Workflow execution started")
                self._persistence.save_run_status(
                    run_status=self._transitions.build_running_transition(
                        run_id=run_id,
                        payload=payload,
                        created_at=created_at,
                        updated_at=running_at,
                        status_url=self._transitions.workflow_status_url(run_id),
                        events_url=self._transitions.workflow_events_url(run_id),
                        executor_metadata={
                            **(current_run.executor_metadata if current_run is not None else {}),
                            "started_at": running_at.isoformat(),
                            "worker_task_name": "app.tasks.workflow_tasks.process_workflow_run",
                        },
                    )
                )
                self._persistence.record_event(
                    run_id=run_id,
                    channel=EventChannel.system,
                    message="任务层开始调用业务服务。",
                    progress=35,
                    payload={"executor": "app.tasks.workflow_tasks.execute_workflow_task"},
                    created_at=running_at,
                )

                execution = execute_workflow_task(
                    run_id=run_id,
                    payload=payload,
                    requested_at=running_at,
                    event_factory=lambda **kwargs: self._persistence.make_event(run_id=run_id, **kwargs),
                )
                self.lifecycle.finalize_workflow_success(
                    run_id=run_id,
                    payload=payload,
                    execution=execution,
                    requested_at=running_at,
                )
                logger.info("Workflow execution finished")
            except SoftTimeLimitExceeded:
                logger.warning("Workflow execution soft-time-limit exceeded")
                self.lifecycle.handle_workflow_timeout(
                    run_id=run_id,
                    payload=payload,
                    created_at=created_at,
                )
            except Exception as exc:
                logger.exception("Workflow execution failed")
                self.lifecycle.handle_workflow_failure(
                    run_id=run_id,
                    payload=payload,
                    created_at=created_at,
                    exc=exc,
                )

    def get_workflow_run(self, run_id: str) -> WorkflowRunStatusResponse | None:
        return self._repository.get_run(run_id)

    def list_workflow_events(
        self,
        run_id: str,
        *,
        after_event_id: str | None = None,
        limit: int | None = None,
    ) -> WorkflowEventsResponse | None:
        if self._repository.get_run(run_id) is None:
            return None
        events = self._repository.list_events(run_id, after_event_id=after_event_id, limit=limit)
        return WorkflowEventsResponse(run_id=run_id, items=events)

    def _dispatch_async_workflow(self, run_id: str, payload: WorkflowSubmitRequest) -> None:
        dispatch_at = datetime.now(timezone.utc)
        queue_name = resolve_workflow_queue(payload)
        dispatch_channel = resolve_workflow_channel(payload)
        with log_context(run_id=run_id):
            try:
                task_id = dispatch_workflow_task(run_id, payload)
                current_run = self._repository.get_run(run_id)
                self._persistence.save_run_status(
                    run_status=self._transitions.build_execution_transition(
                        run_id=run_id,
                        payload=payload,
                        status=ExecutionStatus.queued,
                        progress=18,
                        message="工作流已成功派发到 Celery，等待 worker 消费。",
                        created_at=current_run.created_at if current_run else dispatch_at,
                        updated_at=dispatch_at,
                        result_refs=current_run.result_refs if current_run else None,
                        diagnostics=current_run.diagnostics if current_run else None,
                        executor_metadata={
                            **(current_run.executor_metadata if current_run is not None else {}),
                            "executor": settings.workflow_executor,
                            "dispatch_channel": dispatch_channel,
                            "queue_name": queue_name,
                            "task_id": task_id,
                            "dispatched_at": dispatch_at.isoformat(),
                        },
                    )
                )
                logger.info("Workflow dispatched to celery")
                self._persistence.record_event(
                    run_id=run_id,
                    channel=EventChannel.system,
                    message="工作流已成功派发到 Celery。",
                    progress=18,
                    payload={
                        "task_id": task_id,
                        "queue_name": queue_name,
                        "dispatch_channel": dispatch_channel,
                        "executor": settings.workflow_executor,
                    },
                    created_at=dispatch_at,
                )
            except Exception as exc:
                logger.exception("Workflow dispatch failed")
                current_run = self._repository.get_run(run_id)
                self._persistence.save_run_status(
                    run_status=self._transitions.build_execution_transition(
                        run_id=run_id,
                        payload=payload,
                        status=ExecutionStatus.failed,
                        progress=100,
                        message="工作流派发失败，请检查 worker 与 broker 状态。",
                        created_at=current_run.created_at if current_run else dispatch_at,
                        updated_at=dispatch_at,
                        executor_metadata={
                            **(current_run.executor_metadata if current_run is not None else {}),
                            "executor": settings.workflow_executor,
                            "dispatch_channel": dispatch_channel,
                            "queue_name": queue_name,
                            "dispatch_failed_at": dispatch_at.isoformat(),
                            "dispatch_error": str(exc),
                        },
                        diagnostics=[
                            "异步派发失败，请检查 Redis/Celery 配置。",
                            "error_code=workflow_dispatch_failed",
                            f"dispatch_error={exc}",
                        ],
                    )
                )
                self._persistence.record_event(
                    run_id=run_id,
                    channel=EventChannel.log,
                    level=LogLevel.error,
                    message="Celery 派发失败。",
                    progress=100,
                    payload={"error_code": "workflow_dispatch_failed"},
                    created_at=dispatch_at,
                )

    def _assert_workflow_capacity(self, run_class: str = RUN_CLASS_BUSINESS) -> None:
        active_runs = self._repository.count_active_runs(run_class=run_class)
        if run_class == RUN_CLASS_WEATHER_TILE:
            limit = self._persistence.get_effective_config_int(
                "backend",
                "max_active_weather_tile_runs",
                settings.max_active_weather_tile_runs,
            )
            if active_runs >= limit:
                raise ValueError(
                    f"Weather tile workflow capacity reached: active_runs={active_runs}, limit={limit}"
                )
            return

        limit = self._persistence.get_effective_config_int(
            "backend",
            "max_active_runs",
            settings.max_active_runs,
        )
        if active_runs >= limit:
            raise ValueError(
                f"Workflow capacity reached: active_runs={active_runs}, limit={limit}"
            )

    def _validate_requested_outputs(self, payload: WorkflowSubmitRequest) -> None:
        limit = self._persistence.get_effective_config_int("backend", "max_requested_outputs", settings.max_requested_outputs)
        if len(payload.requested_outputs) > limit:
            raise ValueError(
                f"Requested outputs exceed limit: count={len(payload.requested_outputs)}, limit={limit}"
            )
