import os
from datetime import datetime, timedelta, UTC
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import require_write_access
from app.services.result_view_service import result_view_service
from app.services.workflow.service_container import (
    lifecycle_service,
    retry_dispatcher,
    submission_service,
)
from app.services.workflow.submission_service import WorkflowValidationError
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
    dependencies=[Depends(require_write_access)],
)
def submit_workflow(payload: WorkflowSubmitRequest) -> WorkflowAcceptedResponse:
    try:
        accepted = submission_service.submit_workflow(payload)
        return accepted
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
        status_code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if "capacity" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception:
        raise


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
) -> list[WorkflowRunStatusResponse]:
    """列出工作流 run。active_only=true（默认）仅返回非终态 run。

    可选 status 过滤与 limit 取最近 N 条（按创建时间倒序），
    供前端启动恢复（含"最近成功 run 产物自动恢复"）与跨会话状态同步使用。
    """
    from app.services.workflow_repository import SQLiteWorkflowRepository
    from shared.contracts.api_contracts import ExecutionStatus

    repo = SQLiteWorkflowRepository()
    all_runs = repo.list_runs()
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
def get_workflow_run(run_id: str) -> WorkflowRunStatusResponse:
    run_status = submission_service.get_workflow_run(run_id)
    if run_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    return run_status


@router.get(
    "/workflow-runs/{run_id}/view",
    tags=["workflow"],
    response_model=WorkflowRunViewResponse,
)
def get_workflow_run_view(run_id: str) -> WorkflowRunViewResponse:
    run_view = result_view_service.get_workflow_run_view(run_id)
    if run_view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
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
    dependencies=[Depends(require_write_access)],
)
def cancel_workflow_run(run_id: str) -> WorkflowRunStatusResponse:
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
    dependencies=[Depends(require_write_access)],
)
def retry_workflow_run(run_id: str) -> WorkflowAcceptedResponse:
    try:
        return retry_dispatcher.retry_workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post(
    "/workflow-runs/{run_id}/materialize-map-layers",
    tags=["workflow"],
    dependencies=[Depends(require_write_access)],
)
def materialize_workflow_map_layers(run_id: str) -> dict:
    """Publish algorithm science products as imported overlays for map display.

    L2: 业务逻辑已下沉到 python_provider_result_builder.materialize_map_layers。
    """
    from app.services.python_provider_result_builder import (
        python_provider_result_builder,
    )

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
