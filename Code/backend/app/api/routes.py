from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from threading import Lock

from app.api.deps import require_write_access
from app.core.config import settings
from app.services.demo_snapshots import get_demo_layer_snapshot, list_demo_layer_snapshots
from app.services.interaction_hub import interaction_hub
from app.services.layer_catalog import get_layer_catalog
from app.services.python_provider_bridge_service import python_provider_bridge_service
from app.services.result_storage import result_storage_service
from app.services.task_store import task_store
from shared.contracts.api_contracts import (
    DemoLayerSnapshot,
    DemoLayerSnapshotsResponse,
    FrontendCommandRequest,
    FrontendCommandResponse,
    LayerCatalogResponse,
    RuntimeConfigUpdateRequest,
    RuntimeConfigUpdateResponse,
    RuntimeStatusResponse,
    TaskAcceptedResponse,
    TaskStatusResponse,
    TaskSubmitRequest,
    WorkflowAcceptedResponse,
    WorkflowEventsResponse,
    WorkflowRunStatusResponse,
    WorkflowSubmitRequest,
)

router = APIRouter()

# P0-4: Per-IP rate limiter for SSE endpoint (in-process, suitable for single-node).
# For multi-worker deployments replace with a Redis-based counter.
_SSE_RATE_LIMIT = 10  # max SSE connections per IP
_SSE_WINDOW = timedelta(minutes=5)


class _SseRateLimiter:
    def __init__(self, limit: int, window: timedelta) -> None:
        self._limit = limit
        self._window = window
        self._lock = Lock()
        self._requests: dict[str, list[datetime]] = {}

    def check(self, ip: str) -> bool:
        now = datetime.utcnow()
        cutoff = now - self._window
        with self._lock:
            timestamps = self._requests.setdefault(ip, [])
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._limit:
                return False
            timestamps.append(now)
            return True


_sse_limiter = _SseRateLimiter(_SSE_RATE_LIMIT, _SSE_WINDOW)


def _service_json_response(service_response) -> JSONResponse:
    return JSONResponse(status_code=service_response.status_code, content=service_response.body)


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.service_name,
        "environment": settings.environment,
    }


@router.get("/layers", tags=["catalog"], response_model=LayerCatalogResponse)
def list_layers() -> LayerCatalogResponse:
    return get_layer_catalog()


@router.get("/demo/layers/snapshots", tags=["demo"], response_model=DemoLayerSnapshotsResponse)
def list_demo_snapshots(hour: float = 12) -> DemoLayerSnapshotsResponse:
    return list_demo_layer_snapshots(hour)


@router.get("/demo/layers/{layer_id}/snapshot", tags=["demo"], response_model=DemoLayerSnapshot)
def get_demo_snapshot(layer_id: str, hour: float = 12) -> DemoLayerSnapshot:
    snapshot = get_demo_layer_snapshot(layer_id, hour)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Demo layer not found: {layer_id}",
        )
    return snapshot


@router.post(
    "/workflow-runs",
    tags=["workflow"],
    response_model=WorkflowAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_write_access)],
)
def submit_workflow(payload: WorkflowSubmitRequest) -> WorkflowAcceptedResponse:
    try:
        return interaction_hub.submit_workflow(payload)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_429_TOO_MANY_REQUESTS if "capacity" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/workflow-runs/{run_id}", tags=["workflow"], response_model=WorkflowRunStatusResponse)
def get_workflow_run(run_id: str) -> WorkflowRunStatusResponse:
    run_status = interaction_hub.get_workflow_run(run_id)
    if run_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    return run_status


@router.get("/workflow-runs/{run_id}/events", tags=["workflow"], response_model=WorkflowEventsResponse)
def list_workflow_events(request: Request, run_id: str) -> WorkflowEventsResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not _sse_limiter.check(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many SSE connections from {client_ip}. Limit: {_SSE_RATE_LIMIT} per {_SSE_WINDOW}.",
        )
    events = interaction_hub.list_workflow_events(run_id)
    if events is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow run not found: {run_id}",
        )
    return events


@router.patch(
    "/runtime/config",
    tags=["runtime"],
    response_model=RuntimeConfigUpdateResponse,
    dependencies=[Depends(require_write_access)],
)
def update_runtime_config(payload: RuntimeConfigUpdateRequest) -> RuntimeConfigUpdateResponse:
    try:
        return interaction_hub.update_runtime_config(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/runtime/status", tags=["runtime"], response_model=RuntimeStatusResponse)
def get_runtime_status() -> RuntimeStatusResponse:
    return interaction_hub.get_runtime_status()


@router.get("/algorithm/workflows", tags=["algorithm"])
def list_algorithm_workflows() -> JSONResponse:
    return _service_json_response(python_provider_bridge_service.list_workflows_response())


@router.get("/algorithm/workflows/{workflow_name}", tags=["algorithm"])
def describe_algorithm_workflow(workflow_name: str) -> JSONResponse:
    return _service_json_response(python_provider_bridge_service.describe_workflow_response(workflow_name))


@router.get("/algorithm/workflows/{workflow_name}/panel-schema", tags=["algorithm"])
def get_algorithm_workflow_panel_schema(workflow_name: str) -> JSONResponse:
    return _service_json_response(python_provider_bridge_service.get_workflow_panel_schema_response(workflow_name))


@router.get("/algorithm/workflows/{workflow_name}/ui-schema", tags=["algorithm"])
def get_algorithm_workflow_ui_schema(workflow_name: str) -> JSONResponse:
    return _service_json_response(python_provider_bridge_service.get_workflow_ui_schema_response(workflow_name))


@router.post(
    "/frontend/commands",
    tags=["frontend"],
    response_model=FrontendCommandResponse,
    dependencies=[Depends(require_write_access)],
)
def submit_frontend_command(payload: FrontendCommandRequest) -> FrontendCommandResponse:
    return interaction_hub.submit_frontend_command(payload)


@router.post(
    "/tasks",
    tags=["tasks"],
    response_model=TaskAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_write_access)],
)
def create_task(payload: TaskSubmitRequest) -> TaskAcceptedResponse:
    try:
        return task_store.create_task(payload)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_429_TOO_MANY_REQUESTS if "capacity" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/tasks/{task_id}", tags=["tasks"], response_model=TaskStatusResponse)
def get_task_status(task_id: str) -> TaskStatusResponse:
    task_status = task_store.get_task(task_id)
    if task_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )
    return task_status


@router.get("/artifacts/{artifact_id}", tags=["artifacts"])
def get_artifact(artifact_id: str) -> Response:
    artifact = result_storage_service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not found: {artifact_id}",
        )
    if artifact.public_url:
        return RedirectResponse(url=artifact.public_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    if artifact.file_path is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Artifact backend did not provide a readable path or url: {artifact_id}",
        )
    return FileResponse(
        artifact.file_path,
        media_type=artifact.mime_type,
        filename=artifact.file_path.name,
    )
