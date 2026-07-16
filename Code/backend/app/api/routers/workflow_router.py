import os
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import require_write_access
from app.services.result_view_service import result_view_service
from app.services.workflow.service_container import (
    lifecycle_service,
    submission_service,
)
from shared.contracts.api_contracts import (
    WorkflowAcceptedResponse,
    WorkflowEventsResponse,
    WorkflowRunStatusResponse,
    WorkflowRunViewResponse,
    WorkflowSubmitRequest,
)

router = APIRouter()

# JSON 事件轮询限流：按「每 IP / 每分钟请求数」（非 SSE 连接数）
_EVENTS_POLL_RATE_LIMIT = int(os.getenv("BACKEND_EVENTS_POLL_RATE_LIMIT_PER_MINUTE", "120"))
_EVENTS_POLL_WINDOW = timedelta(minutes=1)


class EventsPollRateLimiter:
    def __init__(self, limit: int, window: timedelta) -> None:
        self._limit = limit
        self._window = window
        self._lock = Lock()
        self._requests: dict[str, list[datetime]] = {}

    def check(self, ip: str) -> bool:
        now = datetime.now(timezone.utc)
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


_events_poll_limiter = EventsPollRateLimiter(_EVENTS_POLL_RATE_LIMIT, _EVENTS_POLL_WINDOW)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


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
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_429_TOO_MANY_REQUESTS if "capacity" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        raise


@router.get("/workflow-runs/{run_id}", tags=["workflow"], response_model=WorkflowRunStatusResponse)
def get_workflow_run(run_id: str) -> WorkflowRunStatusResponse:
    run_status = submission_service.get_workflow_run(run_id)
    if run_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow run not found: {run_id}")
    return run_status


@router.get("/workflow-runs/{run_id}/view", tags=["workflow"], response_model=WorkflowRunViewResponse)
def get_workflow_run_view(run_id: str) -> WorkflowRunViewResponse:
    run_view = result_view_service.get_workflow_run_view(run_id)
    if run_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow run not found: {run_id}")
    return run_view


@router.get("/workflow-runs/{run_id}/events", tags=["workflow"], response_model=WorkflowEventsResponse)
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
    events = submission_service.list_workflow_events(run_id, after_event_id=after_event_id, limit=limit)
    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow run not found: {run_id}")
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/workflow-runs/{run_id}/retry",
    tags=["workflow"],
    response_model=WorkflowAcceptedResponse,
    dependencies=[Depends(require_write_access)],
)
def retry_workflow_run(run_id: str) -> WorkflowAcceptedResponse:
    try:
        return lifecycle_service.retry_workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
