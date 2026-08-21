import os
from datetime import datetime, timedelta, UTC
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import (
    CredentialContext,
    check_resource_access,
    get_request_user,
    require_workflow_run_access,
)
from app.api.error_codes import AUTH_ERROR, ApiError
from app.core import config
from app.services.result_view_service import result_view_service
from app.services.workflow.service_container import (
    lifecycle_service,
    retry_dispatcher,
    submission_service,
)
from app.services.workflow.submission_service import WorkflowValidationError
from shared.remote_sources.access_control import RemoteAccessDeniedError
from shared.contracts.api_contracts import (
    WorkflowAcceptedResponse,
    WorkflowEventsResponse,
    WorkflowRunStatusResponse,
    WorkflowRunViewResponse,
    WorkflowSubmitRequest,
)

router = APIRouter()

# JSON 事件轮询限流：按「每 IP / 每分钟请求数」（非 SSE 连接数）
_EVENTS_POLL_RATE_LIMIT = int(
    os.getenv("BACKEND_EVENTS_POLL_RATE_LIMIT_PER_MINUTE", "120")
)
_EVENTS_POLL_WINDOW = timedelta(minutes=1)


def _deny_if_not_run_owner(run_id: str, cred: CredentialContext | None) -> None:
    """Hide non-owned runs as 404 for non-admin authenticated users.

    When user auth is enabled, anonymous callers fail closed with 401
    (aligned with ``check_resource_access``). Legacy runs with
    ``user_id is None`` are admin / service_key / dev_bypass only.
    """
    if cred is None:
        if config.settings.user_auth_enabled:
            raise ApiError(
                AUTH_ERROR,
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        return
    if cred.role == "admin":
        return
    if cred.user_id is None:
        if cred.source in {"service_key", "dev_bypass"}:
            return
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    from app.services.workflow_repository import SQLiteWorkflowRepository

    owner = SQLiteWorkflowRepository().get_run_user_id(run_id)
    if owner is None or owner != cred.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )


class EventsPollRateLimiter:
    def __init__(self, limit: int, window: timedelta) -> None:
        self._limit = limit
        self._window = window
        self._lock = Lock()
        self._requests: dict[str, list[datetime]] = {}

    def check(self, ip: str) -> bool:
        now = datetime.now(UTC)
        cutoff = now - self._window
        with self._lock:
            timestamps = self._requests.pop(ip, None)
            if timestamps is None:
                timestamps = []
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._limit:
                return False
            timestamps.append(now)
            self._requests[ip] = timestamps
            return True


_events_poll_limiter = EventsPollRateLimiter(
    _EVENTS_POLL_RATE_LIMIT, _EVENTS_POLL_WINDOW
)


def _get_client_ip(request: Request) -> str:
    """Reuse write-limiter IP policy (honor BACKEND_TRUST_PROXY only)."""
    from app.api.rate_limit import client_ip

    return client_ip(request)


@router.post(
    "/workflow-runs",
    tags=["workflow"],
    response_model=WorkflowAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_workflow(
    payload: WorkflowSubmitRequest,
    _write_ok: None = Depends(require_workflow_run_access),
    cred: CredentialContext | None = Depends(get_request_user),
) -> WorkflowAcceptedResponse:
    # When called directly (e.g., in tests without FastAPI DI), ``cred`` may
    # be an unresolved ``Depends`` object — guard with isinstance.
    _cred = cred if isinstance(cred, CredentialContext) else None
    # Auth is enforced by require_workflow_run_access; ACL only when a real
    # credential was resolved (direct unit calls may pass unresolved Depends).
    if _cred is not None and payload.layer_id:
        check_resource_access(_cred, "layer", payload.layer_id)
    try:
        accepted = submission_service.submit_workflow(
            payload,
            user_id=_cred.user_id if _cred else None,
            role=_cred.role if _cred else None,
        )
        return accepted
    except RemoteAccessDeniedError as exc:
        # #56 提交期远程数据集访问预校验拒绝：403 + C403001（统一鉴权类错误码）。
        # 必须在 ValueError 之前捕获（RemoteAccessDeniedError 继承 Exception）。
        raise ApiError(
            AUTH_ERROR,
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"远程数据集访问被拒绝：{exc.reason}",
        ) from exc
    except WorkflowValidationError as exc:
        # 提交期参数预校验失败：返回 422 + 结构化字段级错误，
        # 供前端定位具体表单字段。必须在 ValueError 之前捕获
        # （WorkflowValidationError 继承 ValueError）。
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_type": "validation",
                "user_message": "请求参数未通过业务校验，请检查表单字段。",
                "issues": exc.issues,
            },
        ) from exc
    except ValueError as exc:
        detail = str(exc)
        # User concurrency queue is returned as a normal WorkflowAcceptedResponse
        # from submission_service (status=queued). Global capacity → 429.
        status_code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if "capacity" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get(
    "/workflow-runs", tags=["workflow"], response_model=list[WorkflowRunStatusResponse]
)
def list_workflow_runs(
    active_only: bool = True,
    status: str | None = Query(
        default=None, description="按状态过滤，如 succeeded / failed / cancelled"
    ),
    limit: int | None = Query(
        default=None, ge=1, le=200, description="取最近 N 条（按创建时间倒序）"
    ),
    cred: CredentialContext | None = Depends(get_request_user),
) -> list[WorkflowRunStatusResponse]:
    """列出工作流 run。active_only=true（默认）仅返回非终态 run。

    可选 status 过滤与 limit 取最近 N 条（按创建时间倒序），
    供前端启动恢复（含"最近成功 run 产物自动恢复"）与跨会话状态同步使用。
    非 admin 仅可见本人 run（无 user_id 的旧 run 对非 admin 不可见）。
    """
    # 查询参数 ``status`` 遮蔽了模块级 ``fastapi.status``，此处取别名使用。
    from fastapi import status as http_status

    from app.services.workflow_repository import SQLiteWorkflowRepository
    from shared.contracts.api_contracts import ExecutionStatus

    repo = SQLiteWorkflowRepository()
    all_runs = repo.list_runs()
    _cred = cred if isinstance(cred, CredentialContext) else None
    if _cred is None:
        if config.settings.user_auth_enabled:
            raise ApiError(
                AUTH_ERROR,
                status_code=http_status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
    elif _cred.role != "admin":
        if _cred.user_id is not None:
            owners = repo.list_run_user_ids()
            all_runs = [r for r in all_runs if owners.get(r.run_id) == _cred.user_id]
        elif _cred.source not in {"service_key", "dev_bypass"}:
            all_runs = []
    if status is not None:
        all_runs = [r for r in all_runs if r.status.value == status]
    if not active_only:
        if limit is not None:
            all_runs = sorted(all_runs, key=lambda r: r.created_at, reverse=True)[
                :limit
            ]
        return all_runs
    active_statuses = {
        ExecutionStatus.accepted,
        ExecutionStatus.queued,
        ExecutionStatus.running,
    }
    active = [r for r in all_runs if r.status in active_statuses]
    if limit is not None:
        active = sorted(active, key=lambda r: r.created_at, reverse=True)[:limit]
    return active


@router.get(
    "/workflow-runs/{run_id}",
    tags=["workflow"],
    response_model=WorkflowRunStatusResponse,
)
def get_workflow_run(
    run_id: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> WorkflowRunStatusResponse:
    run_status = submission_service.get_workflow_run(run_id)
    if run_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    _cred = cred if isinstance(cred, CredentialContext) else None
    _deny_if_not_run_owner(run_id, _cred)
    return run_status


@router.get(
    "/workflow-runs/{run_id}/view",
    tags=["workflow"],
    response_model=WorkflowRunViewResponse,
)
def get_workflow_run_view(
    run_id: str,
    cred: CredentialContext | None = Depends(get_request_user),
) -> WorkflowRunViewResponse:
    run_view = result_view_service.get_workflow_run_view(run_id)
    if run_view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    _cred = cred if isinstance(cred, CredentialContext) else None
    _deny_if_not_run_owner(run_id, _cred)
    return run_view


@router.get(
    "/workflow-runs/{run_id}/events",
    tags=["workflow"],
    response_model=WorkflowEventsResponse,
)
def list_workflow_events(
    request: Request,
    run_id: str,
    after_event_id: str | None = None,
    limit: int | None = None,
    cred: CredentialContext | None = Depends(get_request_user),
) -> WorkflowEventsResponse:
    client_ip = _get_client_ip(request)
    if not _events_poll_limiter.check(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Too many workflow event poll requests from {client_ip}. "
                f"Limit: {_EVENTS_POLL_RATE_LIMIT} per minute."
            ),
        )
    _cred = cred if isinstance(cred, CredentialContext) else None
    _deny_if_not_run_owner(run_id, _cred)
    events = submission_service.list_workflow_events(
        run_id, after_event_id=after_event_id, limit=limit
    )
    if events is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    return events


@router.post(
    "/workflow-runs/{run_id}/cancel",
    tags=["workflow"],
    response_model=WorkflowRunStatusResponse,
)
def cancel_workflow_run(
    run_id: str,
    _run_ok: None = Depends(require_workflow_run_access),
    cred: CredentialContext | None = Depends(get_request_user),
) -> WorkflowRunStatusResponse:
    _cred = cred if isinstance(cred, CredentialContext) else None
    _deny_if_not_run_owner(run_id, _cred)
    try:
        return lifecycle_service.cancel_workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post(
    "/workflow-runs/{run_id}/retry",
    tags=["workflow"],
    response_model=WorkflowAcceptedResponse,
)
def retry_workflow_run(
    run_id: str,
    _run_ok: None = Depends(require_workflow_run_access),
    cred: CredentialContext | None = Depends(get_request_user),
) -> WorkflowAcceptedResponse:
    _cred = cred if isinstance(cred, CredentialContext) else None
    _deny_if_not_run_owner(run_id, _cred)
    try:
        return retry_dispatcher.retry_workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post(
    "/workflow-runs/{run_id}/materialize-map-layers",
    tags=["workflow"],
)
def materialize_workflow_map_layers(
    run_id: str,
    _run_ok: None = Depends(require_workflow_run_access),
    cred: CredentialContext | None = Depends(get_request_user),
) -> dict[str, Any]:
    """Publish algorithm science products as imported overlays for map display.

    L2: 业务逻辑已下沉到 python_provider_result_builder.materialize_map_layers。
    """
    from app.services.python_provider_result_builder import (
        python_provider_result_builder,
    )

    _cred = cred if isinstance(cred, CredentialContext) else None
    _deny_if_not_run_owner(run_id, _cred)
    run_status = submission_service.get_workflow_run(run_id)
    if run_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    try:
        return python_provider_result_builder.materialize_map_layers(run_id, run_status)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
