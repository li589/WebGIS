from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from threading import Lock

from app.api.deps import require_write_access
from app.core.config import settings
from app.services.coordinate_transform_service import transform_point
from app.services.demo_snapshots import get_demo_layer_snapshot, list_demo_layer_snapshots
from app.services.gee_bridge_service import gee_bridge_service
from app.services.interaction_hub import interaction_hub
from app.services.layer_catalog import get_layer_catalog
from app.services.python_provider_bridge_service import python_provider_bridge_service
from app.services.provider_workflow_service import provider_workflow_service
from app.services.result_storage import result_storage_service
from app.services.result_view_service import result_view_service
from app.services.task_store import task_store
from app.services.weather_bridge_service import weather_bridge_service
from app.weatherengine.service import weather_engine_service
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
    WeatherPointResponse,
    TaskSubmitRequest,
    WorkflowAcceptedResponse,
    WorkflowEventsResponse,
    WorkflowRunStatusResponse,
    WorkflowRunViewResponse,
    WorkflowSubmitRequest,
)

router = APIRouter()

_SSE_RATE_LIMIT = 10
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
            timestamps = self._requests.pop(ip, None)
            if timestamps is None:
                timestamps = []
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._limit:
                return False
            timestamps.append(now)
            self._requests[ip] = timestamps
            return True


_sse_limiter = _SseRateLimiter(_SSE_RATE_LIMIT, _SSE_WINDOW)


def _service_json_response(service_response) -> JSONResponse:
    return JSONResponse(status_code=service_response.status_code, content=service_response.body)


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name, "environment": settings.environment}


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Demo layer not found: {layer_id}")
    return snapshot


@router.get("/geo/transform", tags=["geo"])
def transform_geo_point(lng: float, lat: float, source: str, target: str = "EPSG:3857") -> dict[str, float | str]:
    try:
        point = transform_point(lng, lat, source=source, target=target)
        return {"lng": point.lng, "lat": point.lat, "source": source, "target": target}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/weather/point", tags=["weather"], response_model=WeatherPointResponse)
def get_weather_point(
    layer_id: str,
    latitude: float,
    longitude: float,
    model: str | None = None,
    forecast_hours: int = 6,
    place_name: str | None = None,
) -> WeatherPointResponse:
    try:
        return weather_engine_service.get_point_weather(
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            model=model,
            forecast_hours=forecast_hours,
            place_name=place_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/artifacts/{artifact_id}", tags=["artifacts"])
def get_artifact(artifact_id: str):
    artifact = result_storage_service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact not found: {artifact_id}")
    if artifact.file_path is not None and artifact.file_path.exists():
        return FileResponse(path=artifact.file_path, media_type=artifact.mime_type, filename=artifact.file_path.name)
    if artifact.public_url:
        return RedirectResponse(url=artifact.public_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact is unavailable: {artifact_id}")


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow run not found: {run_id}")
    return run_status


@router.get("/workflow-runs/{run_id}/view", tags=["workflow"], response_model=WorkflowRunViewResponse)
def get_workflow_run_view(run_id: str) -> WorkflowRunViewResponse:
    run_view = result_view_service.get_workflow_run_view(run_id)
    if run_view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow run not found: {run_id}")
    return run_view


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workflow run not found: {run_id}")
    return events


@router.post("/workflow-runs/{run_id}/cancel", tags=["workflow"], response_model=WorkflowRunStatusResponse, dependencies=[Depends(require_write_access)])
def cancel_workflow_run(run_id: str) -> WorkflowRunStatusResponse:
    try:
        return interaction_hub.cancel_workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/workflow-runs/{run_id}/retry", tags=["workflow"], response_model=WorkflowAcceptedResponse, dependencies=[Depends(require_write_access)])
def retry_workflow_run(run_id: str) -> WorkflowAcceptedResponse:
    try:
        return interaction_hub.retry_workflow_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/runtime/status", tags=["runtime"], response_model=RuntimeStatusResponse)
def get_runtime_status() -> RuntimeStatusResponse:
    return interaction_hub.get_runtime_status()


def _algorithm_service_response(service_call) -> JSONResponse:
    try:
        return _service_json_response(service_call())
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/algorithm/workflows", tags=["algorithm"])
def list_algorithm_workflows() -> JSONResponse:
    return _algorithm_service_response(python_provider_bridge_service.list_workflows_response)


@router.get("/algorithm/workflows/{workflow_name}", tags=["algorithm"])
def describe_algorithm_workflow(workflow_name: str) -> JSONResponse:
    return _algorithm_service_response(lambda: python_provider_bridge_service.describe_workflow_response(workflow_name))


@router.get("/algorithm/workflows/{workflow_name}/panel-schema", tags=["algorithm"])
def get_algorithm_workflow_panel_schema(workflow_name: str) -> JSONResponse:
    return _algorithm_service_response(lambda: python_provider_bridge_service.get_workflow_panel_schema_response(workflow_name))


@router.get("/algorithm/workflows/{workflow_name}/ui-schema", tags=["algorithm"])
def get_algorithm_workflow_ui_schema(workflow_name: str) -> JSONResponse:
    return _algorithm_service_response(lambda: python_provider_bridge_service.get_workflow_ui_schema_response(workflow_name))


@router.get("/algorithm/diagnostics", tags=["algorithm"])
def get_algorithm_diagnostics() -> JSONResponse:
    return _algorithm_service_response(python_provider_bridge_service.get_diagnostics_response)


@router.post(
    "/frontend/commands",
    tags=["frontend"],
    response_model=FrontendCommandResponse,
    dependencies=[Depends(require_write_access)],
)
def submit_frontend_command(payload: FrontendCommandRequest) -> FrontendCommandResponse:
    return interaction_hub.submit_frontend_command(payload)


# ---------------- GEE 引擎接口 ----------------
# GEE 引擎通过 /gee/* 暴露元数据、诊断和导出状态查询；
# 工作流执行统一走 /workflow-runs（通过 gee_request 字段路由到 gee_bridge_service）。


def _gee_service_response(service_call) -> JSONResponse:
    try:
        return _service_json_response(service_call())
    except RuntimeError as exc:
        detail = str(exc)
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if "disabled" in detail.lower() or "initialize" in detail.lower() else status.HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/gee/workflows", tags=["gee"])
def list_gee_workflows() -> JSONResponse:
    return _gee_service_response(gee_bridge_service.list_workflows_response)


@router.get("/gee/workflows/{workflow_name}", tags=["gee"])
def describe_gee_workflow(workflow_name: str) -> JSONResponse:
    return _gee_service_response(lambda: gee_bridge_service.describe_workflow_response(workflow_name))


@router.get("/gee/workflows/{workflow_name}/panel-schema", tags=["gee"])
def get_gee_workflow_panel_schema(workflow_name: str) -> JSONResponse:
    return _gee_service_response(lambda: gee_bridge_service.get_workflow_panel_schema_response(workflow_name))


@router.get("/gee/workflows/{workflow_name}/ui-schema", tags=["gee"])
def get_gee_workflow_ui_schema(workflow_name: str) -> JSONResponse:
    return _gee_service_response(lambda: gee_bridge_service.get_workflow_ui_schema_response(workflow_name))


@router.get("/gee/diagnostics", tags=["gee"])
def get_gee_diagnostics() -> JSONResponse:
    return _gee_service_response(gee_bridge_service.get_diagnostics_response)


@router.get("/gee/exports:status", tags=["gee"])
def get_gee_export_status(manifest_uri: str, update_manifest: bool = False) -> JSONResponse:
    return _gee_service_response(
        lambda: gee_bridge_service.get_export_status_response(manifest_uri, update_manifest=update_manifest)
    )


# ---------------- 天气工作流引擎接口 ----------------
# 天气工作流引擎通过 /weather/workflows/* 暴露元数据和诊断；
# 工作流执行统一走 /workflow-runs（通过 weather_request 字段路由到 weather_bridge_service）。


def _weather_service_response(service_call) -> JSONResponse:
    try:
        return _service_json_response(service_call())
    except RuntimeError as exc:
        detail = str(exc)
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if "disabled" in detail.lower() or "initialize" in detail.lower() else status.HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/weather/workflows", tags=["weather"])
def list_weather_workflows() -> JSONResponse:
    return _weather_service_response(weather_bridge_service.list_workflows_response)


@router.get("/weather/workflows/diagnostics", tags=["weather"])
def get_weather_diagnostics() -> JSONResponse:
    return _weather_service_response(weather_bridge_service.get_diagnostics_response)


@router.get("/weather/workflows/{workflow_name}", tags=["weather"])
def describe_weather_workflow(workflow_name: str) -> JSONResponse:
    return _weather_service_response(lambda: weather_bridge_service.describe_workflow_response(workflow_name))


# ---------------- Provider 工作流引擎接口 ----------------
# m19 修复：补齐 Provider 路由暴露，与其他 bridge 对齐
# Provider 通过 /provider/workflows/* 暴露元数据和诊断；
# 工作流执行统一走 /workflow-runs（通过 layer_id 路由到 provider_workflow_service）。


def _provider_service_response(service_call) -> JSONResponse:
    try:
        return _service_json_response(service_call())
    except RuntimeError as exc:
        detail = str(exc)
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if "disabled" in detail.lower() or "initialize" in detail.lower() else status.HTTP_500_INTERNAL_SERVER_ERROR
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/provider/workflows", tags=["provider"])
def list_provider_workflows() -> JSONResponse:
    return _provider_service_response(provider_workflow_service.list_workflows_response)


@router.get("/provider/workflows/diagnostics", tags=["provider"])
def get_provider_diagnostics() -> JSONResponse:
    return _provider_service_response(provider_workflow_service.get_diagnostics_response)


@router.get("/provider/workflows/{workflow_name}", tags=["provider"])
def describe_provider_workflow(workflow_name: str) -> JSONResponse:
    return _provider_service_response(lambda: provider_workflow_service.describe_workflow_response(workflow_name))
