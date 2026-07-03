from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from uuid import uuid4

from app.core.celery_app import celery_available, get_celery_runtime_details, revoke_task
from app.core.config import settings
from app.core.logging import ensure_logging_configured, log_context
from app.services.result_storage import result_storage_service
from app.services.workflow_repository import SQLiteWorkflowRepository
from app.tasks.download_tasks import dispatch_download_follow_up_task, execute_download_follow_up_task
from app.tasks.workflow_tasks import (
    dispatch_workflow_task,
    execute_workflow_task,
    resolve_workflow_channel,
    resolve_workflow_queue,
)
from shared.contracts.api_contracts import (
    BackendServiceStatus,
    EventChannel,
    ExecutionStatus,
    FrontendCommandRequest,
    FrontendCommandResponse,
    LogLevel,
    RuntimeConfigUpdateRequest,
    RuntimeConfigUpdateResponse,
    RuntimeStatusResponse,
    ServiceHealth,
    WorkflowAcceptedResponse,
    WorkflowEvent,
    WorkflowEventsResponse,
    WorkflowPriority,
    WorkflowResultReference,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)


logger = logging.getLogger(__name__)
ensure_logging_configured()
@dataclass
class _SubmissionTransition:
    status: WorkflowRunStatusResponse
    events: list[WorkflowEvent] = None
    request_json: bool = False

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = []


ALLOWED_RUNTIME_CONFIG_KEYS: dict[str, set[str]] = {
    "frontend": {"demo_source_mode", "timeline_granularity", "ui_density"},
    "backend": {"task_executor", "demo_snapshot_provider"},
    "workflow": {"default_queue", "result_retention"},
}


class InMemoryInteractionHub:
    def __init__(self, repository: SQLiteWorkflowRepository | None = None) -> None:
        self._repository = repository or SQLiteWorkflowRepository()

    def _workflow_status_url(self, run_id: str) -> str:
        return f"/workflow-runs/{run_id}"

    def _workflow_events_url(self, run_id: str) -> str:
        return f"/workflow-runs/{run_id}/events"

    def submit_workflow(self, payload: WorkflowSubmitRequest) -> WorkflowAcceptedResponse:
        now = datetime.now(timezone.utc)
        run_id = f"run-{uuid4().hex[:12]}"
        status_url = self._workflow_status_url(run_id)
        events_url = self._workflow_events_url(run_id)
        request_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
        with log_context(run_id=run_id):
            self._assert_workflow_capacity()
            self._validate_requested_outputs(payload)
            logger.info("Workflow accepted")
            accepted_at = now
            queued_at = datetime.now(timezone.utc)
            submission_transitions = self._build_submission_transitions(
                run_id=run_id,
                payload=payload,
                accepted_at=accepted_at,
                queued_at=queued_at,
                status_url=status_url,
                events_url=events_url,
            )
            for transition in submission_transitions:
                self._save_run_status(
                    transition.status,
                    request_json=request_json if transition.request_json else None,
                )
                for event in transition.events:
                    self._record_event(event=event)

            if self._use_celery_executor():
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
                self._save_run_status(
                    self._build_running_transition(
                        run_id=run_id,
                        payload=payload,
                        created_at=created_at,
                        updated_at=running_at,
                        status_url=self._workflow_status_url(run_id),
                        events_url=self._workflow_events_url(run_id),
                        executor_metadata={
                            **(current_run.executor_metadata if current_run is not None else {}),
                            "started_at": running_at.isoformat(),
                            "worker_task_name": "app.tasks.workflow_tasks.process_workflow_run",
                        },
                    )
                )
                self._record_event(
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
                    event_factory=lambda **kwargs: self._make_event(run_id=run_id, **kwargs),
                )
                self._finalize_workflow_success(
                    run_id=run_id,
                    payload=payload,
                    execution=execution,
                    requested_at=running_at,
                )
                logger.info("Workflow execution finished")
            except Exception:
                logger.exception("Workflow execution failed")
                self._finalize_workflow_failure(
                    run_id=run_id,
                    payload=payload,
                    created_at=created_at,
                )

    def get_workflow_run(self, run_id: str) -> WorkflowRunStatusResponse | None:
        return self._repository.get_run(run_id)

    def list_workflow_events(self, run_id: str) -> WorkflowEventsResponse | None:
        events = self._repository.list_events(run_id)
        if events is None:
            return None
        return WorkflowEventsResponse(run_id=run_id, items=events)

    def update_runtime_config(self, payload: RuntimeConfigUpdateRequest) -> RuntimeConfigUpdateResponse:
        now = datetime.now(timezone.utc)
        self._validate_runtime_config(payload)
        applied_count = self._repository.apply_runtime_config(payload.items)
        return RuntimeConfigUpdateResponse(
            accepted=True,
            updated_at=now,
            applied_count=applied_count,
            message="运行时配置已更新。",
            config_snapshot=self._repository.get_config_snapshot(),
        )

    def get_runtime_status(self) -> RuntimeStatusResponse:
        now = datetime.now(timezone.utc)
        active_run_count = self._repository.count_active_runs()
        celery_details = get_celery_runtime_details()
        if self._use_celery_executor():
            if not celery_available:
                dispatcher_health = ServiceHealth.offline
                dispatcher_message = "Celery 未安装，当前异步消费不可用。"
            elif not celery_details.get("probe_ok"):
                dispatcher_health = ServiceHealth.degraded
                dispatcher_message = "Celery 已配置，但当前无法确认 worker 在线状态。"
            elif int(celery_details.get("worker_count", 0)) == 0:
                dispatcher_health = ServiceHealth.degraded
                dispatcher_message = "Celery broker 可访问，但未发现在线 worker。"
            else:
                dispatcher_health = ServiceHealth.busy if active_run_count > 0 else ServiceHealth.ok
                dispatcher_message = "当前使用 Celery 异步分发器，worker 在线。"
        else:
            dispatcher_health = ServiceHealth.busy if active_run_count > 0 else ServiceHealth.ok
            dispatcher_message = "当前使用本地同步任务编排器。"
        services = [
            BackendServiceStatus(
                service_name="api",
                health=ServiceHealth.ok,
                message="接口服务正常。",
                updated_at=now,
                details={"router_count": 14, "workflow_route_count_hint": 14},
            ),
            BackendServiceStatus(
                service_name="workflow_dispatcher",
                health=dispatcher_health,
                message=dispatcher_message,
                updated_at=now,
                details={
                    "active_run_count": active_run_count,
                    "executor": settings.workflow_executor,
                    "celery_available": celery_available,
                    "celery_probe": celery_details,
                    "max_active_runs": settings.max_active_runs,
                    "queues": {
                        "realtime": settings.workflow_queue_realtime,
                        "algorithm_realtime": settings.workflow_queue_algorithm_realtime,
                        "algorithm_standard": settings.workflow_queue_algorithm_standard,
                        "algorithm_heavy": settings.workflow_queue_algorithm_heavy,
                        "algorithm_batch": settings.workflow_queue_algorithm_batch,
                        "download_realtime": settings.workflow_queue_download_realtime,
                        "download_standard": settings.workflow_queue_download_standard,
                        "analysis_standard": settings.workflow_queue_analysis_standard,
                        "analysis_heavy": settings.workflow_queue_analysis_heavy,
                        "analysis_batch": settings.workflow_queue_analysis_batch,
                    },
                },
            ),
            BackendServiceStatus(
                service_name="analysis_workflow_service",
                health=ServiceHealth.ok,
                message="分析工作流服务可用。",
                updated_at=now,
                details={
                    "execution_mode": "sync_or_provider",
                    "result_inline_max_bytes": settings.result_inline_max_bytes,
                    "provider_max_hotspots": settings.provider_max_hotspots,
                    "provider_max_series_points": settings.provider_max_series_points,
                    "provider_table_chunk_size": settings.provider_table_chunk_size,
                    "provider_series_chunk_size": settings.provider_series_chunk_size,
                    "object_store_backend": settings.object_store_backend,
                },
            ),
            BackendServiceStatus(
                service_name="python_provider_bridge_service",
                health=ServiceHealth.ok,
                message="Python 算法桥接服务可用。",
                updated_at=now,
                details={
                    "provider_root": settings.python_provider_root,
                    "workspace": settings.python_provider_workspace,
                    "queues": {
                        "realtime": settings.workflow_queue_algorithm_realtime,
                        "standard": settings.workflow_queue_algorithm_standard,
                        "heavy": settings.workflow_queue_algorithm_heavy,
                        "batch": settings.workflow_queue_algorithm_batch,
                    },
                },
            ),
            BackendServiceStatus(
                service_name="download_workflow_service",
                health=ServiceHealth.ok,
                message="下载工作流服务可用。",
                updated_at=now,
                details={
                    "dispatch_channel": "download",
                    "download_realtime_queue": settings.workflow_queue_download_realtime,
                    "download_standard_queue": settings.workflow_queue_download_standard,
                    "cache_dir": settings.cache_dir,
                    "cache_default_ttl_seconds": settings.cache_default_ttl_seconds,
                },
            ),
        ]
        overall_health = ServiceHealth.busy if active_run_count > 0 else ServiceHealth.ok
        return RuntimeStatusResponse(
            overall_health=overall_health,
            service_name=settings.service_name,
            environment=settings.environment,
            updated_at=now,
            active_run_count=active_run_count,
            config_snapshot=self._repository.get_config_snapshot(),
            services=services,
        )

    def submit_frontend_command(self, payload: FrontendCommandRequest) -> FrontendCommandResponse:
        now = datetime.now(timezone.utc)
        next_action = {
            "preload": "schedule-prefetch",
            "clear_cache": "clear-local-cache",
            "cleanup": "release-preview-resources",
            "cancel_run": "cancel-pending-run",
            "reload_catalog": "refresh-layer-catalog",
            "custom": "inspect-custom-command",
        }.get(payload.command_type.value, "inspect-command")
        return FrontendCommandResponse(
            accepted=True,
            command_type=payload.command_type,
            target=payload.target,
            created_at=now,
            message="前端控制指令已接收。",
            next_action=next_action,
        )

    def cancel_workflow_run(self, run_id: str) -> WorkflowRunStatusResponse:
        now = datetime.now(timezone.utc)
        current_run = self._repository.get_run(run_id)
        if current_run is None:
            raise ValueError(f"Workflow run not found: {run_id}")

        if current_run.status in (ExecutionStatus.succeeded, ExecutionStatus.failed, ExecutionStatus.cancelled):
            raise ValueError(f"Cannot cancel workflow in terminal state: {current_run.status.value}")

        if self._use_celery_executor() and current_run.executor_metadata:
            task_id = current_run.executor_metadata.get("task_id")
            if task_id:
                revoke_task(task_id, terminate=True)

        self._save_run_status(
            self._build_execution_transition(
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
                status_url=self._workflow_status_url(run_id),
                events_url=self._workflow_events_url(run_id),
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
        self._record_event(
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
        new_response = self.submit_workflow(payload)
        new_run = self._repository.get_run(new_response.run_id)

        if new_run:
            self._save_run_status(
                self._build_execution_transition(
                    run_id=new_response.run_id,
                    payload=payload,
                    status=new_run.status,
                    progress=new_run.progress,
                    message=new_run.message,
                    created_at=new_run.created_at,
                    updated_at=now,
                    status_url=self._workflow_status_url(new_response.run_id),
                    events_url=self._workflow_events_url(new_response.run_id),
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

    def _dispatch_async_workflow(self, run_id: str, payload: WorkflowSubmitRequest) -> None:
        dispatch_at = datetime.now(timezone.utc)
        with log_context(run_id=run_id):
            try:
                queue_name = resolve_workflow_queue(payload)
                dispatch_channel = resolve_workflow_channel(payload)
                task_id = dispatch_workflow_task(run_id, payload)
                current_run = self._repository.get_run(run_id)
                self._save_run_status(
                    self._build_execution_transition(
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
                self._record_event(
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
                queue_name = resolve_workflow_queue(payload)
                dispatch_channel = resolve_workflow_channel(payload)
                self._save_run_status(
                    self._build_execution_transition(
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
                self._record_event(
                    run_id=run_id,
                    channel=EventChannel.log,
                    level=LogLevel.error,
                    message="Celery 派发失败。",
                    progress=100,
                    payload={"error_code": "workflow_dispatch_failed"},
                    created_at=dispatch_at,
                )

    def _finalize_workflow_success(
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
        diagnostics = [*execution.diagnostics, *spill_diagnostics]
        result_dto = self._augment_result_dto(
            execution.result_dto,
            materialized_result_count=len(result_refs),
            spill_diagnostics_count=len(spill_diagnostics),
        )
        completed_at = datetime.now(timezone.utc)
        self._save_run_status(
            self._build_succeeded_transition(
                run_id=run_id,
                payload=payload,
                message=execution.message,
                created_at=requested_at,
                updated_at=completed_at,
                status_url=self._workflow_status_url(run_id),
                events_url=self._workflow_events_url(run_id),
                result_refs=result_refs,
                result_dto=result_dto,
                diagnostics=diagnostics,
            )
        )
        for event in execution.events:
            self._record_event(event=event)
        if spill_diagnostics:
            self._record_event(
                run_id=run_id,
                channel=EventChannel.system,
                message="大结果已自动落盘为 artifact 引用。",
                progress=96,
                payload={"spill_count": len(spill_diagnostics)},
                created_at=completed_at,
            )
        self._record_event(
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
            self._dispatch_follow_up_tasks(
                run_id=run_id,
                payload=payload,
                follow_up_tasks=execution.follow_up_tasks,
                created_at=completed_at,
            )

    def _finalize_workflow_failure(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        created_at: datetime,
    ) -> None:
        failed_at = datetime.now(timezone.utc)
        self._save_run_status(
            self._build_failed_transition(
                run_id=run_id,
                payload=payload,
                message="工作流执行失败，请查看服务端日志。",
                created_at=created_at,
                updated_at=failed_at,
                status_url=self._workflow_status_url(run_id),
                events_url=self._workflow_events_url(run_id),
                diagnostics=[
                    "workflow-runs 已进入服务编排链，但本次执行失败。",
                    "error_code=workflow_execution_failed",
                ],
            )
        )
        self._record_event(
            run_id=run_id,
            channel=EventChannel.log,
            level=LogLevel.error,
            message="工作流执行失败。",
            progress=100,
            payload={"error_code": "workflow_execution_failed"},
            created_at=failed_at,
        )

    def _augment_result_dto(
        self,
        result_dto: dict[str, object] | None,
        **extra_fields: object,
    ) -> dict[str, object] | None:
        if not result_dto:
            return result_dto
        return {**result_dto, **extra_fields}

    def _dispatch_follow_up_tasks(
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
            if task_data.get("task_type") != "download_fetch_placeholder":
                continue
            with log_context(run_id=run_id):
                try:
                    if self._use_celery_executor():
                        task_id = dispatch_download_follow_up_task(
                            task_data=task_data,
                            queue_name=queue_name,
                            priority=priority,
                        )
                        self._record_event(
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
                        self._record_event(
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
                    self._record_event(
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

    def _use_celery_executor(self) -> bool:
        return settings.workflow_executor.lower() == "celery"

    def _assert_workflow_capacity(self) -> None:
        active_runs = self._repository.count_active_runs()
        if active_runs >= settings.max_active_runs:
            raise ValueError(
                f"Workflow capacity reached: active_runs={active_runs}, limit={settings.max_active_runs}"
            )

    def _validate_requested_outputs(self, payload: WorkflowSubmitRequest) -> None:
        if len(payload.requested_outputs) > settings.max_requested_outputs:
            raise ValueError(
                f"Requested outputs exceed limit: count={len(payload.requested_outputs)}, limit={settings.max_requested_outputs}"
            )

    def _validate_runtime_config(self, payload: RuntimeConfigUpdateRequest) -> None:
        for item in payload.items:
            allowed_keys = ALLOWED_RUNTIME_CONFIG_KEYS.get(item.scope.value, set())
            if item.key not in allowed_keys:
                raise ValueError(f"Unsupported runtime config key: {item.scope.value}.{item.key}")

    def _build_submission_transitions(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        accepted_at: datetime,
        queued_at: datetime,
        status_url: str,
        events_url: str,
    ) -> list[_SubmissionTransition]:
        accepted_status = self._build_transition_status(
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
        queued_status = self._build_transition_status(
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
                "executor": settings.workflow_executor,
                "dispatch_channel": resolve_workflow_channel(payload),
                "queue_name": resolve_workflow_queue(payload),
            },
        )
        return [
            _SubmissionTransition(
                status=accepted_status,
                request_json=True,
                events=[
                    self._make_event(
                        run_id=run_id,
                        channel=EventChannel.status,
                        message="工作流已创建。",
                        progress=3,
                        payload={"status": ExecutionStatus.accepted.value},
                        created_at=accepted_at,
                    ),
                    self._make_event(
                        run_id=run_id,
                        channel=EventChannel.log,
                        message="已完成参数接收与协议校验。",
                        progress=8,
                        payload={"layer_id": payload.layer_id, "command_type": payload.command_type.value},
                    ),
                ],
            ),
            _SubmissionTransition(
                status=queued_status,
                request_json=False,
                events=[
                    self._make_event(
                        run_id=run_id,
                        channel=EventChannel.status,
                        message="工作流已进入任务层。",
                        progress=12,
                        payload={
                            "status": ExecutionStatus.queued.value,
                            "executor": settings.workflow_executor,
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

    def _build_running_transition(
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
        return self._build_transition_status(
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

    def _build_succeeded_transition(
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
        return self._build_transition_status(
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

    def _build_failed_transition(
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
        return self._build_transition_status(
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

    def _build_transition_status(
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

    def _save_run_status(
        self,
        *,
        run_status: WorkflowRunStatusResponse,
        request_json: str | None = None,
    ) -> None:
        self._repository.save_run(run_status, request_json=request_json)

    def _record_event(
        self,
        event: WorkflowEvent | None = None,
        *,
        run_id: str | None = None,
        channel: EventChannel | str | None = None,
        message: str | None = None,
        progress: int | None = None,
        payload: dict[str, object] | None = None,
        level: LogLevel | str = LogLevel.info,
        created_at: datetime | None = None,
    ) -> None:
        if event is None:
            if run_id is None or channel is None or message is None:
                raise ValueError("run_id, channel and message are required when event is not provided")
            event = self._make_event(
                run_id=run_id,
                channel=channel,
                message=message,
                progress=progress,
                payload=payload,
                level=level,
                created_at=created_at,
            )
        self._repository.append_event(event)

    def _make_event(
        self,
        *,
        run_id: str,
        channel: EventChannel | str,
        message: str,
        progress: int | None = None,
        payload: dict[str, object] | None = None,
        level: LogLevel | str = LogLevel.info,
        created_at: datetime | None = None,
    ) -> WorkflowEvent:
        resolved_channel = channel if isinstance(channel, EventChannel) else EventChannel(channel)
        resolved_level = level if isinstance(level, LogLevel) else LogLevel(level)
        return WorkflowEvent(
            event_id=f"evt-{uuid4().hex[:10]}",
            run_id=run_id,
            channel=resolved_channel,
            level=resolved_level,
            message=message,
            created_at=created_at or datetime.now(timezone.utc),
            progress=progress,
            payload=payload or {},
        )


interaction_hub = InMemoryInteractionHub()
