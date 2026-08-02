"""Workflow submission service.

Handles workflow submission, execution dispatch, and capacity validation.
Uses late binding to access lifecycle service (for finalize/handle methods)
to break the circular dependency: submission → lifecycle → submission.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.logging import ensure_logging_configured, log_context
from app.services.workflow_request_resolver import (
    _normalize_algorithm_request,
    _python_provider_import_path,
    normalize_workflow_submit_request,
)
from app.services.workflow_repository import SQLiteWorkflowRepository
from app.services.workflow.persistence_service import WorkflowPersistenceService
from app.services.workflow.transition_builder import (
    WorkflowTransitionBuilder,
    use_celery_executor,
)
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
    WorkflowCommandType,
    WorkflowEventsResponse,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)

if TYPE_CHECKING:
    from app.services.workflow.lifecycle_service import WorkflowLifecycleService

logger = logging.getLogger(__name__)
ensure_logging_configured()


class WorkflowValidationError(ValueError):
    """提交期参数预校验失败。

    携带结构化 issue 列表（``[{"field": ..., "message": ...}]``），供
    ``workflow_router`` 转为 422 响应。继承 ``ValueError`` 以兼容既有
    "校验失败用 ValueError" 的约定，但 router 会优先捕获本类型以返回
    字段级定位信息。
    """

    def __init__(self, issues: list[dict[str, str]]) -> None:
        self.issues = issues
        super().__init__(self._format_message(issues))

    @staticmethod
    def _format_message(issues: list[dict[str, str]]) -> str:
        if not issues:
            return "workflow request validation failed"
        return "; ".join(
            f"[{item.get('field', '?')}] {item.get('message', '')}".rstrip()
            for item in issues
        )


# validate_request_against_template 返回的字符串错误 → {field, message} 的映射规则。
# 按错误消息前缀匹配，提取出字段路径供前端定位。
_TEMPLATE_ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^Missing required datasource key: '([^']*)'"),
        "datasource_selection",
    ),
    (re.compile(r"^Missing required algorithm param: '([^']*)'"), "algorithm_params"),
    (re.compile(r"^algorithm param '([^']*)'"), "algorithm_params"),
    (
        re.compile(r"^dataset '([^']*)'"),
        "datasource_selection._data_access_requests",
    ),
)


def _template_error_to_issue(message: str) -> dict[str, str]:
    """把 ``validate_request_against_template`` 的字符串错误转为 ``{field, message}``。"""
    for pattern, prefix in _TEMPLATE_ERROR_PATTERNS:
        match = pattern.match(message)
        if match:
            return {"field": f"{prefix}.{match.group(1)}", "message": message}
    if message.startswith("task_type "):
        return {"field": "task_type", "message": message}
    return {"field": "_unknown", "message": message}


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
        self._follow_up = follow_up or FollowUpDispatchService(
            self._repository, self._persistence, self._transitions
        )
        self._lifecycle: "WorkflowLifecycleService | None" = None

    def set_lifecycle_service(self, lifecycle: "WorkflowLifecycleService") -> None:
        """Late binding to break circular dependency."""
        self._lifecycle = lifecycle

    @property
    def lifecycle(self) -> "WorkflowLifecycleService":
        if self._lifecycle is None:
            raise RuntimeError(
                "Lifecycle service not set. Call set_lifecycle_service() first."
            )
        return self._lifecycle

    def submit_workflow(
        self, payload: WorkflowSubmitRequest
    ) -> WorkflowAcceptedResponse:
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
            self._validate_request_params(payload)
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
        # 幂等检查：acks_late 开启后，worker 崩溃会触发任务重投。
        # 若 run 已处于终态，说明此前已成功/失败/取消，直接跳过避免重复执行。
        if current_run is not None and current_run.status in (
            ExecutionStatus.succeeded,
            ExecutionStatus.failed,
            ExecutionStatus.cancelled,
        ):
            logger.info(
                "Workflow run %s already in terminal state %s; skipping re-execution "
                "(likely acks_late redelivery after worker crash)",
                run_id,
                current_run.status.value,
            )
            return
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
                            **(
                                current_run.executor_metadata
                                if current_run is not None
                                else {}
                            ),
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
                    payload={
                        "executor": "app.tasks.workflow_tasks.execute_workflow_task"
                    },
                    created_at=running_at,
                )

                execution = execute_workflow_task(
                    run_id=run_id,
                    payload=payload,
                    requested_at=running_at,
                    event_factory=self._make_persisting_event_factory(run_id),
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

    def _make_persisting_event_factory(self, run_id: str):
        """Create event_factory that persists immediately for UI mid-run progress.

        Bridges call this factory during execute (node_progress) and also return
        the same event objects in ``execution.events`` for lifecycle finalize.
        ``append_event`` uses INSERT OR IGNORE so finalize re-writes are safe.
        """

        def _factory(**kwargs):
            event = self._persistence.make_event(run_id=run_id, **kwargs)
            self._persistence.record_event(event=event)
            return event

        return _factory

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
        events = self._repository.list_events(
            run_id, after_event_id=after_event_id, limit=limit
        )
        return WorkflowEventsResponse(run_id=run_id, items=events)

    def _dispatch_async_workflow(
        self, run_id: str, payload: WorkflowSubmitRequest
    ) -> None:
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
                        created_at=current_run.created_at
                        if current_run
                        else dispatch_at,
                        updated_at=dispatch_at,
                        result_refs=current_run.result_refs if current_run else None,
                        diagnostics=current_run.diagnostics if current_run else None,
                        executor_metadata={
                            **(
                                current_run.executor_metadata
                                if current_run is not None
                                else {}
                            ),
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
                        created_at=current_run.created_at
                        if current_run
                        else dispatch_at,
                        updated_at=dispatch_at,
                        executor_metadata={
                            **(
                                current_run.executor_metadata
                                if current_run is not None
                                else {}
                            ),
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
        limit = self._persistence.get_effective_config_int(
            "backend", "max_requested_outputs", settings.max_requested_outputs
        )
        if len(payload.requested_outputs) > limit:
            raise ValueError(
                f"Requested outputs exceed limit: count={len(payload.requested_outputs)}, limit={limit}"
            )

    def _validate_request_params(self, payload: WorkflowSubmitRequest) -> None:
        """提交期参数预校验。仅校验可静态检查的参数，不阻塞未知的可选参数。

        对于 ``command_type == "analysis"`` 且携带 ``module_name`` 的请求，
        尝试用 Python provider 的 ``RequestTemplateSpec`` 做静态校验
        （required datasource/algorithm keys、allowed_task_types、
        allowed_algorithm_values 等）。校验失败时抛出
        :class:`WorkflowValidationError`，由 router 转为 422 结构化响应。

        跳过条件（不阻塞提交，让执行阶段处理）：
        - 非 analysis 命令；
        - 无 module_name（workflow_definition / workflow_name 模式，图编译时校验）；
        - python provider root 不存在；
        - 未知 module（无模板）；
        - 模板导入/校验过程异常（降级跳过，避免阻断提交链路）。
        """
        if payload.command_type != WorkflowCommandType.analysis:
            return
        algo_req = _normalize_algorithm_request(payload.algorithm_request)
        module_name = algo_req.get("module_name")
        if not module_name:
            # workflow_definition 模式：跳过模板校验（图编译时校验）
            return
        provider_root = Path(settings.python_provider_root)
        if not provider_root.exists():
            return
        errors: list[str] = []
        try:
            with _python_provider_import_path(provider_root):
                deriver = importlib.import_module("contracts.template_deriver")
                template = deriver.get_module_request_template(module_name)
                if template is None:
                    return  # 未知模块：跳过，让执行阶段处理
                # validate_request_against_template 通过属性访问（duck typing）读取
                # task_type / datasource_selection / algorithm_params，用 SimpleNamespace
                # 构造轻量代理，避免实例化完整 JobRequest（需要 time_range/region 等必填字段）。
                request_proxy = SimpleNamespace(
                    task_type=algo_req.get("task_type") or module_name,
                    datasource_selection=algo_req.get("datasource_selection") or {},
                    algorithm_params=algo_req.get("algorithm_params") or {},
                )
                _, errors = deriver.validate_request_against_template(
                    request_proxy, template
                )
        except Exception:
            logger.debug(
                "Submission-time template validation skipped for module=%s",
                module_name,
                exc_info=True,
            )
            return
        if errors:
            raise WorkflowValidationError(
                [_template_error_to_issue(msg) for msg in errors]
            )
