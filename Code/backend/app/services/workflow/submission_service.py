"""Workflow submission service.

Handles workflow submission, execution dispatch, and capacity validation.
Uses late binding to access lifecycle service (for finalize/handle methods)
to break the circular dependency: submission → lifecycle → submission.
"""

from __future__ import annotations

from datetime import datetime, UTC
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
    _normalize_request,
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
        self._lifecycle: WorkflowLifecycleService | None = None

    def set_lifecycle_service(self, lifecycle: WorkflowLifecycleService) -> None:
        """Late binding to break circular dependency."""
        self._lifecycle = lifecycle

    @property
    def lifecycle(self) -> WorkflowLifecycleService:
        if self._lifecycle is None:
            raise RuntimeError(
                "Lifecycle service not set. Call set_lifecycle_service() first."
            )
        return self._lifecycle

    def submit_workflow(
        self,
        payload: WorkflowSubmitRequest,
        *,
        user_id: int | None = None,
        role: str | None = None,
    ) -> WorkflowAcceptedResponse:
        payload = normalize_workflow_submit_request(payload)
        from app.services.resource_profile_resolver import (
            apply_resource_profile_to_payload,
        )

        # Upgrade standard → heavy when seed meta or heavy modules are present
        apply_resource_profile_to_payload(payload)
        # Same layer+tool analysis: cancel prior non-terminal run before accept.
        cancelled_prior = self._cancel_exclusive_analysis_runs(payload)
        now = datetime.now(UTC)
        run_id = f"run-{uuid4().hex[:12]}"
        status_url = self._transitions.workflow_status_url(run_id)
        events_url = self._transitions.workflow_events_url(run_id)
        request_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
        run_class = resolve_workflow_run_class(payload)
        with log_context(run_id=run_id):
            self._validate_remote_dataset_access(payload)
            self._validate_requested_outputs(payload)
            self._validate_request_params(payload)
            logger.info(
                "Workflow accepted run_class=%s exclusivity_cancelled=%s",
                run_class,
                cancelled_prior,
            )
            accepted_at = now
            queued_at = datetime.now(UTC)
            submission_transitions = self._transitions.build_submission_transitions(
                run_id=run_id,
                payload=payload,
                accepted_at=accepted_at,
                queued_at=queued_at,
                status_url=status_url,
                events_url=events_url,
                make_event_fn=self._persistence.make_event,
            )
            capacity_limit = self._workflow_capacity_limit(run_class)
            user_limit = self._user_concurrency_limit(user_id, role)
            user_queued = False
            for transition in submission_transitions:
                if transition.request_json:
                    # Atomic capacity reservation + first persist (closes TOCTOU).
                    try:
                        self._persistence.save_run_under_capacity(
                            run_status=transition.status,
                            request_json=request_json,
                            run_class=run_class,
                            limit=capacity_limit,
                            user_id=user_id,
                            user_limit=user_limit,
                        )
                    except ValueError as exc:
                        if "User workflow capacity" in str(exc):
                            # Phase C：用户级并发上限达到——保存为 queued 状态，
                            # 等待 queue_dispatch_service 在其他工作流完成后唤醒。
                            # 注意：transition.status 的状态是 accepted，需要覆写为
                            # queued，否则 dispatch_queued_workflows 无法找到该 run
                            # （它搜索 status='queued'），且该 run 会被错误计为
                            # accepted 但不会派发到 Celery，永久卡死。
                            user_queued = True
                            queued_run_status = transition.status.model_copy(
                                update={
                                    "status": ExecutionStatus.queued,
                                    "progress": 5,
                                }
                            )
                            self._persistence.save_run_status(
                                run_status=queued_run_status,
                                request_json=request_json,
                                run_class=run_class,
                                user_id=user_id,
                            )
                        else:
                            raise
                else:
                    self._persistence.save_run_status(
                        run_status=transition.status,
                        request_json=None,
                        run_class=None,
                    )
                for event in transition.events:
                    self._persistence.record_event(event=event)

            if user_queued:
                logger.info(
                    "Workflow queued due to user concurrency limit: "
                    "run_id=%s user_id=%s user_limit=%s",
                    run_id,
                    user_id,
                    user_limit,
                )
                self._persistence.record_event(
                    run_id=run_id,
                    channel=EventChannel.system,
                    level=LogLevel.warning,
                    message="用户并发工作流数已达上限，工作流已入队等待调度。",
                    progress=5,
                    payload={
                        "queued_reason": "user_concurrency_limit",
                        "user_limit": user_limit,
                    },
                    created_at=datetime.now(UTC),
                )
                return WorkflowAcceptedResponse(
                    run_id=run_id,
                    status=ExecutionStatus.queued,
                    status_url=status_url,
                    events_url=events_url,
                    created_at=now,
                    message="用户并发工作流数已达上限，工作流已入队等待调度。",
                )

            if use_celery_executor():
                self._dispatch_async_workflow(run_id, payload)
            else:
                self.process_workflow_run(run_id, payload)

            message = "工作流已提交，可轮询状态、事件与结果引用。"
            if cancelled_prior:
                message = (
                    f"工作流已提交（已取代 {cancelled_prior} 个同工具先前分析）。"
                    "可轮询状态、事件与结果引用。"
                )
            return WorkflowAcceptedResponse(
                run_id=run_id,
                status=ExecutionStatus.accepted,
                status_url=status_url,
                events_url=events_url,
                created_at=now,
                message=message,
            )

    @staticmethod
    def _analysis_exclusivity_key(payload: WorkflowSubmitRequest) -> str | None:
        params = payload.parameters if isinstance(payload.parameters, dict) else {}
        key = str(params.get("analysis_exclusivity_key") or "").strip()
        return key or None

    def _cancel_exclusive_analysis_runs(self, payload: WorkflowSubmitRequest) -> int:
        """Cancel non-terminal runs sharing ``analysis_exclusivity_key``.

        Returns the number of runs cancelled (best-effort; race-safe via lifecycle CAS).
        """
        key = self._analysis_exclusivity_key(payload)
        if not key:
            return 0
        terminal = {
            ExecutionStatus.succeeded,
            ExecutionStatus.failed,
            ExecutionStatus.cancelled,
        }
        cancelled = 0
        for run in self._repository.list_runs():
            if run.status in terminal:
                continue
            meta = dict(run.executor_metadata or {})
            if str(meta.get("analysis_exclusivity_key") or "").strip() == key:
                try:
                    self.lifecycle.cancel_workflow_run(run.run_id)
                    cancelled += 1
                    continue
                except Exception:
                    logger.warning(
                        "Failed to cancel exclusive analysis run %s key=%s",
                        run.run_id,
                        key,
                        exc_info=True,
                    )
            raw = self._repository.get_run_request_json(run.run_id)
            if not raw:
                continue
            try:
                req = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(req, dict):
                continue
            req_params = (
                req.get("parameters") if isinstance(req.get("parameters"), dict) else {}
            )
            if str(req_params.get("analysis_exclusivity_key") or "").strip() != key:
                continue
            try:
                self.lifecycle.cancel_workflow_run(run.run_id)
                cancelled += 1
            except Exception:
                logger.warning(
                    "Failed to cancel exclusive analysis run %s key=%s",
                    run.run_id,
                    key,
                    exc_info=True,
                )
        return cancelled

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

        # C5：at-least-once 重投追踪（审查 H2）。
        # acks_late 保证 worker 崩溃后任务重投，但幂等检查仅挡终态。
        # running 状态的重投意味着原 worker 已死亡——记录 retry 次数与诊断信息，
        # 供后续排查重复计算与产物覆盖（受保护终态 H2a 已在收口端阻止终态覆盖）。
        existing_meta = dict(current_run.executor_metadata if current_run else {})
        retry_count = 0
        if current_run is not None and current_run.status == ExecutionStatus.running:
            retry_count = int(existing_meta.get("execution_retry_count", 0)) + 1
            logger.warning(
                "Workflow run %s redelivered while still running (execution_retry=%d). "
                "Original started_at=%s worker_task_id=%s. "
                "Re-executing from scratch; check lifecycle logs for duplicate artifacts.",
                run_id,
                retry_count,
                existing_meta.get("started_at"),
                existing_meta.get("celery_task_id"),
            )
            self._persistence.record_event(
                run_id=run_id,
                channel=EventChannel.system,
                level=LogLevel.warning,
                message=(
                    f"工作流重投：当前状态 running，疑似前次 worker 崩溃"
                    f"（重试次数={retry_count}）"
                ),
                progress=5,
                payload={
                    "execution_retry_count": retry_count,
                    "previous_started_at": existing_meta.get("started_at"),
                    "previous_worker_task_id": existing_meta.get("celery_task_id"),
                },
                created_at=datetime.now(UTC),
            )

        now = datetime.now(UTC)
        created_at = current_run.created_at if current_run is not None else now

        with log_context(run_id=run_id):
            try:
                running_at = datetime.now(UTC)
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
                            **existing_meta,
                            "started_at": running_at.isoformat(),
                            "worker_task_name": "app.tasks.workflow_tasks.process_workflow_run",
                            "execution_retry_count": retry_count,
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
        dispatch_at = datetime.now(UTC)
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
                logger.exception(
                    "Workflow dispatch failed – marking as queued (message may have been delivered)"
                )
                current_run = self._repository.get_run(run_id)
                # C4：派发超时 / 异常时不确定消息是否实际投递（H1 审查）。
                # 改为 queued 而非 failed：若已投递，worker 消费后正常执行；
                # 若未投递，watchdog 在 15 min 内标记为 stuck_running_watchdog→failed。
                self._persistence.save_run_status(
                    run_status=self._transitions.build_execution_transition(
                        run_id=run_id,
                        payload=payload,
                        status=ExecutionStatus.queued,
                        progress=20,
                        message="工作流已提交到队列（派发确认异常：消息可能已投递，worker 将在恢复后消费）。",
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
                            "dispatch_ack_uncertain": True,
                        },
                        diagnostics=[
                            "派发确认异常：消息可能已投递到队列，若 worker 未在 15 min 内消费将被 watchdog 标记为失败。",
                            "error_code=workflow_dispatch_timeout_or_error",
                            f"dispatch_error={exc}",
                        ],
                    )
                )
                self._persistence.record_event(
                    run_id=run_id,
                    channel=EventChannel.log,
                    level=LogLevel.warning,
                    message="Celery 派发确认异常（消息可能已投递）。",
                    progress=20,
                    payload={"error_code": "workflow_dispatch_uncertain"},
                    created_at=dispatch_at,
                )

    def _workflow_capacity_limit(self, run_class: str = RUN_CLASS_BUSINESS) -> int:
        if run_class == RUN_CLASS_WEATHER_TILE:
            return self._persistence.get_effective_config_int(
                "backend",
                "max_active_weather_tile_runs",
                settings.max_active_weather_tile_runs,
            )
        return self._persistence.get_effective_config_int(
            "backend",
            "max_active_runs",
            settings.max_active_runs,
        )

    def _user_concurrency_limit(
        self, user_id: int | None, role: str | None
    ) -> int | None:
        """Phase C: Compute the per-user concurrent workflow limit.

        Resolution order:
        1. ``admin`` role → ``None`` (no per-user limit).
        2. User-specific ``max_concurrent_workflows`` in users table → use it.
        3. Role-based default from config (``max_concurrent_workflows_standard``
           or ``max_concurrent_workflows_demo``).

        Returns ``None`` when no limit applies (admin, unknown role, or
        no user context).
        """
        if not user_id or not role:
            return None
        if role == "admin":
            return None  # admin 不受用户级限制
        # 1. 检查用户独立配置
        from app.services.user_repository import get_user_repository

        user_repo = get_user_repository()
        user_limit = user_repo.get_max_concurrent_workflows(user_id)
        if user_limit is not None:
            return user_limit
        # 2. 回退到角色默认值
        if role == "standard":
            return self._persistence.get_effective_config_int(
                "backend",
                "max_concurrent_workflows_standard",
                settings.max_concurrent_workflows_standard,
            )
        if role == "demo":
            return self._persistence.get_effective_config_int(
                "backend",
                "max_concurrent_workflows_demo",
                settings.max_concurrent_workflows_demo,
            )
        return None

    def _assert_workflow_capacity(self, run_class: str = RUN_CLASS_BUSINESS) -> None:
        """Read-only capacity probe (tests / diagnostics). Submit path uses atomic reserve."""
        active_runs = self._repository.count_active_runs(run_class=run_class)
        limit = self._workflow_capacity_limit(run_class)
        if active_runs >= limit:
            if run_class == RUN_CLASS_WEATHER_TILE:
                raise ValueError(
                    f"Weather tile workflow capacity reached: active_runs={active_runs}, limit={limit}"
                )
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

    def _validate_remote_dataset_access(self, payload: WorkflowSubmitRequest) -> None:
        """提交期远程数据集访问预校验（#56）。

        遍历 ``datasource_selection._data_access_requests[*].selector.uris``，
        逐 URI 构建 AccessPolicyContext 并执行 check_remote_access，
        把越权数据集请求在提交阶段即拒绝（而非下载执行时）。

        三态语义：
        - 明确拒绝（RemoteAccessDeniedError）→ fail-closed：附 dataset
          上下文 re-raise，由 router 转为 403；
        - 基础设施异常（registry 读失败等）→ fail-open + warning（与
          下载链 ``_build_access_policy_context`` 降级语义一致）；
        - 非 REMOTE_SCHEMES（http/file 直链或本地路径）→ 确定性跳过
          （非降级，不触发 registry）。
        """
        from urllib.parse import urlparse

        uris_by_dataset = self._collect_remote_dataset_uris(payload)
        if not uris_by_dataset:
            return

        try:
            from app.services.remote_dataset_grants import get_remote_dataset_grants
            from app.services.remote_source_registry import get_remote_source_registry
            from shared.remote_sources.access_control import (
                build_policy_context_from_uri,
                check_remote_access,
            )
            from shared.remote_sources.uri import REMOTE_SCHEMES

            sources_reg = get_remote_source_registry()
            grants_reg = get_remote_dataset_grants()
        except Exception:  # noqa: BLE001 — 基础设施不可用 → fail-open
            logger.warning(
                "Remote dataset access validation skipped: registry unavailable",
                exc_info=True,
            )
            return

        for dataset, uris in uris_by_dataset.items():
            for uri in uris:
                if "://" not in uri:
                    continue  # 本地路径 / dataset key：不涉远程访问
                scheme = (urlparse(uri).scheme or "").lower()
                if scheme not in REMOTE_SCHEMES:
                    continue  # http/file 等直链：确定性跳过
                try:
                    ctx = build_policy_context_from_uri(
                        uri,
                        source_registry=sources_reg,
                        grants_registry=grants_reg,
                    )
                    check_remote_access(uri, ctx)
                except Exception as exc:  # noqa: BLE001
                    from shared.remote_sources.access_control import (
                        RemoteAccessDeniedError,
                    )

                    if isinstance(exc, RemoteAccessDeniedError):
                        # 明确拒绝 → fail-closed，附 dataset 上下文
                        raise RemoteAccessDeniedError(
                            uri,
                            f"dataset '{dataset}' not in authorized grants: {exc.reason}",
                        ) from exc
                    # 基础设施异常（registry 读失败/URI 解析异常等）→ fail-open
                    logger.warning(
                        "Remote dataset access check degraded for dataset=%s uri=%s",
                        dataset,
                        uri,
                        exc_info=True,
                    )
                    continue

    @staticmethod
    def _collect_remote_dataset_uris(
        payload: WorkflowSubmitRequest,
    ) -> dict[str, list[str]]:
        """从 normalize 后的 payload 提取 dataset → 远程 URI 列表映射。

        数据源：``algorithm_request.datasource_selection._data_access_requests``
        （normalize 阶段已合并 default 数据集请求，见
        ``workflow_request_resolver`` 的 ``_build_default_data_access_requests``）。
        """
        algo_req = _normalize_algorithm_request(payload.algorithm_request)
        datasource_selection = _normalize_request(
            algo_req.get("datasource_selection")
        )
        data_access_requests = _normalize_request(
            datasource_selection.get("_data_access_requests")
        )
        if not isinstance(data_access_requests, dict):
            return {}
        result: dict[str, list[str]] = {}
        for dataset, request in data_access_requests.items():
            if not isinstance(request, dict):
                continue
            selector = request.get("selector")
            if not isinstance(selector, dict):
                continue
            uris = [
                u for u in (selector.get("uris") or []) if isinstance(u, str) and u
            ]
            if uris:
                result[str(dataset)] = uris
        return result

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

        Fail-closed 条件（阻断提交）：
        - 已知 module 但模板校验过程异常（非 ImportError）；
        - 校验返回 errors。
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
        except ImportError:
            logger.debug(
                "Submission-time template validation skipped for module=%s (import failed)",
                module_name,
                exc_info=True,
            )
            return
        except Exception:
            # 已知 module 但校验过程异常 → fail-closed，避免绕过校验
            logger.warning(
                "Submission-time template validation failed for module=%s",
                module_name,
                exc_info=True,
            )
            raise WorkflowValidationError(
                [
                    {
                        "field": "algorithm_request",
                        "message": f"参数校验内部错误，请检查模块 '{module_name}' 的参数配置",
                    }
                ]
            )
        if errors:
            raise WorkflowValidationError(
                [_template_error_to_issue(msg) for msg in errors]
            )
