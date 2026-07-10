from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response
from pathlib import Path
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import tempfile
import urllib.request
from urllib.error import HTTPError, URLError

from app.api.deps import require_write_access
from app.core.config import settings
from app.services.api_config import api_config_manager, ApiProvider, DataType
from app.services.coordinate_transform_service import transform_point
from app.services.demo_snapshots import get_demo_layer_snapshot, list_demo_layer_snapshots
from app.services.interaction_hub import interaction_hub
from app.services.layer_catalog import get_layer_catalog
from app.services.python_provider_bridge_service import python_provider_bridge_service
from app.services.raster_preview_service import raster_preview_service
from app.services.provider_workflow_service import provider_workflow_service
from app.services.result_storage import result_storage_service
from app.services.result_view_service import result_view_service
from app.services.weather_bridge_service import weather_bridge_service
from app.services.workflow_request_resolver import describe_layer_run_readiness
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


_sse_limiter = _SseRateLimiter(_SSE_RATE_LIMIT, _SSE_WINDOW)


# #region debug-point A:runtime-api-debug-helper
def _report_debug_event(
    hypothesis_id: str,
    location: str,
    msg: str,
    data: dict | None = None,
    *,
    run_id: str = "post-fix",
) -> None:
    payload = {
        "sessionId": "runtime-api-pending",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "msg": msg,
        "data": data or {},
        "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:7777/event",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request, timeout=2).read()
    except Exception:
        pass


# #endregion


def _service_json_response(service_response) -> JSONResponse:
    # m26 修复：支持 dict 和对象两种返回格式
    # 某些 bridge service 返回 {"status_code": int, "body": dict} 格式的 dict
    # 其他服务返回具有 status_code 和 body 属性的对象
    if isinstance(service_response, dict):
        return JSONResponse(status_code=service_response.get("status_code", 200), content=service_response.get("body", {}))
    return JSONResponse(status_code=service_response.status_code, content=service_response.body)


def _mark_compat_response(response: Response, *, replacement: str, status_label: str) -> None:
    response.headers["Deprecation"] = "true"
    response.headers["X-Compat-Status"] = status_label
    response.headers["X-Replacement-Path"] = replacement
    response.headers["Warning"] = f'299 - "Deprecated compatibility endpoint. Prefer {replacement}."'


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name, "environment": settings.environment}


@router.get("/layers", tags=["catalog"], response_model=LayerCatalogResponse)
def list_layers() -> LayerCatalogResponse:
    catalog = get_layer_catalog()

    def _check_readiness(item) -> tuple[str, dict]:
        readiness = describe_layer_run_readiness(item.layer_id) or {}
        return item.layer_id, readiness

    # 并行执行所有 readiness 检查（这些操作是 I/O 密集型的 module import）
    layer_readiness: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_check_readiness, desc): desc for desc in catalog.items}
        for future in as_completed(futures):
            layer_id, readiness = future.result()
            layer_readiness[layer_id] = readiness

    items = []
    for descriptor in catalog.items:
        readiness = layer_readiness.get(descriptor.layer_id, {})
        items.append(
            descriptor.model_copy(
                update={
                    "run_readiness": readiness.get("run_readiness", descriptor.run_readiness),
                    "run_readiness_summary": readiness.get("run_readiness_summary", descriptor.run_readiness_summary),
                    "run_readiness_notes": readiness.get("run_readiness_notes", descriptor.run_readiness_notes),
                }
            )
        )
    return LayerCatalogResponse(items=items)


@router.get("/demo/layers/snapshots", tags=["demo"], response_model=DemoLayerSnapshotsResponse)
def list_demo_snapshots(response: Response, hour: float = 12) -> DemoLayerSnapshotsResponse:
    _mark_compat_response(response, replacement="/layers + /workflow-runs", status_label="soft-offline-demo")
    return list_demo_layer_snapshots(hour)


@router.get("/demo/layers/{layer_id}/snapshot", tags=["demo"], response_model=DemoLayerSnapshot)
def get_demo_snapshot(response: Response, layer_id: str, hour: float = 12) -> DemoLayerSnapshot:
    _mark_compat_response(response, replacement="/layers + /workflow-runs/{run_id}/view", status_label="soft-offline-demo")
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
    except (HTTPError, URLError) as exc:
        detail = "Open-Meteo point forecast is temporarily unavailable."
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc


@router.get("/artifacts/{artifact_id}", tags=["artifacts"])
def get_artifact(artifact_id: str):
    artifact = result_storage_service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact not found: {artifact_id}")
    if artifact.file_path is not None and artifact.file_path.exists():
        return FileResponse(path=artifact.file_path, media_type=artifact.mime_type, filename=artifact.file_path.name)
    # MinIO 存储：直接读取数据返回，避免 307 重定向导致浏览器直连 MinIO 跨域
    data = result_storage_service.fetch_artifact_bytes(artifact_id)
    if data is not None:
        return Response(content=data, media_type=artifact.mime_type)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact is unavailable: {artifact_id}")


@router.get("/artifacts/{artifact_id}/preview.png", tags=["artifacts"])
def get_artifact_preview_png(
    artifact_id: str,
    palette: str = "thermal-orange",
    width: int = 768,
    height: int = 768,
    min_value: float | None = None,
    max_value: float | None = None,
):
    artifact = result_storage_service.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact not found: {artifact_id}")
    if artifact.mime_type != "image/tiff":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Artifact is not a TIFF/COG: {artifact_id}")

    # 本地存储：file_path 直接可用；MinIO：file_path=None，回退到 fetch_bytes + 临时文件
    cog_path = artifact.file_path
    temp_path: Path | None = None
    if cog_path is None or not cog_path.exists():
        raw_bytes = result_storage_service.fetch_artifact_bytes(artifact_id)
        if raw_bytes is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Artifact bytes not found: {artifact_id}")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".tif",
            prefix=f"preview_{artifact_id}_",
            delete=False,
        ) as temp_file:
            temp_file.write(raw_bytes)
            temp_path = Path(temp_file.name)
        cog_path = temp_path

    try:
        png_bytes = raster_preview_service.render_cog_preview(
            cog_path=cog_path,
            palette=palette,
            width=width,
            height=height,
            min_value=min_value,
            max_value=max_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
    return Response(content=png_bytes, media_type="image/png")


@router.post(
    "/workflow-runs",
    tags=["workflow"],
    response_model=WorkflowAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_write_access)],
)
def submit_workflow(payload: WorkflowSubmitRequest) -> WorkflowAcceptedResponse:
    try:
        # #region debug-point D:workflow-submit-enter
        _report_debug_event(
            "D",
            "app.api.routes.submit_workflow.enter",
            "[DEBUG] workflow submit enter",
            {
                "layer_id": payload.layer_id,
                "command_type": payload.command_type,
                "requested_outputs": payload.requested_outputs,
                "client_page": payload.client.page if payload.client else None,
            },
        )
        # #endregion
        accepted = interaction_hub.submit_workflow(payload)
        # #region debug-point B:workflow-submit-accepted
        _report_debug_event(
            "B",
            "app.api.routes.submit_workflow.accepted",
            "[DEBUG] workflow submit accepted",
            {
                "layer_id": payload.layer_id,
                "run_id": accepted.run_id,
                "status": accepted.status,
            },
        )
        # #endregion
        return accepted
    except ValueError as exc:
        # #region debug-point D:workflow-submit-value-error
        _report_debug_event(
            "D",
            "app.api.routes.submit_workflow.value_error",
            "[DEBUG] workflow submit value error",
            {
                "layer_id": payload.layer_id,
                "detail": str(exc),
            },
        )
        # #endregion
        detail = str(exc)
        status_code = status.HTTP_429_TOO_MANY_REQUESTS if "capacity" in detail.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except Exception as exc:
        # #region debug-point D:workflow-submit-unexpected-error
        _report_debug_event(
            "D",
            "app.api.routes.submit_workflow.unexpected_error",
            "[DEBUG] workflow submit unexpected error",
            {
                "layer_id": payload.layer_id,
                "error_type": type(exc).__name__,
                "detail": str(exc),
            },
        )
        # #endregion
        raise


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


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


@router.get("/workflow-runs/{run_id}/events", tags=["workflow"], response_model=WorkflowEventsResponse)
def list_workflow_events(
    request: Request,
    run_id: str,
    after_event_id: str | None = None,
    limit: int | None = None,
) -> WorkflowEventsResponse:
    client_ip = _get_client_ip(request)
    if not _sse_limiter.check(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many SSE connections from {client_ip}. Limit: {_SSE_RATE_LIMIT} per {_SSE_WINDOW}.",
        )
    events = interaction_hub.list_workflow_events(run_id, after_event_id=after_event_id, limit=limit)
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


# GEE 引擎路由已迁移至 GEE router（通过 main.py 挂载），由 webgis_gee/api/routes.py 管理。

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


# ---------------- API 配置管理接口 ----------------
# 统一 API 配置端点，支持切换/替换数据源（Gee、百度、高德、天地图等）


@router.get("/runtime/api-config", tags=["runtime"])
def get_api_config_status() -> JSONResponse:
    """返回所有 API 配置状态，供前端判断可用数据源。"""
    try:
        configs = api_config_manager.get_all_configs()
        serializable_configs = api_config_manager.get_all_configs_serializable()
        # #region debug-point A:runtime-api-config-enter
        _report_debug_event(
            "A",
            "app.api.routes.get_api_config_status.enter",
            "[DEBUG] runtime api-config enter",
            {
                "config_count": len(configs),
                "key_types": [type(key).__name__ for key in configs.keys()],
                "sample_value_types": [type(value).__name__ for value in list(configs.values())[:3]],
            },
        )
        # #endregion
        # #region debug-point A:runtime-api-config-success
        _report_debug_event(
            "A",
            "app.api.routes.get_api_config_status.success",
            "[DEBUG] runtime api-config serialized",
            {
                "provider_ids": list(serializable_configs.keys()),
            },
        )
        # #endregion
        return JSONResponse(content=serializable_configs)
    except Exception as exc:
        # #region debug-point A:runtime-api-config-error
        _report_debug_event(
            "A",
            "app.api.routes.get_api_config_status.error",
            "[DEBUG] runtime api-config failed",
            {
                "error_type": type(exc).__name__,
                "detail": str(exc),
            },
        )
        # #endregion
        raise


@router.get("/runtime/api-config/{provider}", tags=["runtime"])
def get_provider_api_config(provider: str) -> JSONResponse:
    """返回指定 Provider 的 API 配置状态。"""
    try:
        api_provider = ApiProvider(provider)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown provider: {provider}")
    config = api_config_manager.get_config(api_provider)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Config not found for provider: {provider}")
    try:
        serializable_config = api_config_manager.get_config_serializable(api_provider)
        # #region debug-point A:runtime-provider-api-config-enter
        _report_debug_event(
            "A",
            "app.api.routes.get_provider_api_config.enter",
            "[DEBUG] runtime provider api-config enter",
            {
                "provider": provider,
                "config_type": type(config).__name__,
                "endpoint_type": type(config.endpoint).__name__,
            },
        )
        # #endregion
        # #region debug-point A:runtime-provider-api-config-success
        _report_debug_event(
            "A",
            "app.api.routes.get_provider_api_config.success",
            "[DEBUG] runtime provider api-config serialized",
            {
                "provider": provider,
                "keys": list(serializable_config.keys()) if isinstance(serializable_config, dict) else [],
            },
        )
        # #endregion
        return JSONResponse(content=serializable_config)
    except Exception as exc:
        # #region debug-point A:runtime-provider-api-config-error
        _report_debug_event(
            "A",
            "app.api.routes.get_provider_api_config.error",
            "[DEBUG] runtime provider api-config failed",
            {
                "provider": provider,
                "error_type": type(exc).__name__,
                "detail": str(exc),
            },
        )
        # #endregion
        raise


@router.post("/runtime/api-config/{provider}", tags=["runtime"], dependencies=[Depends(require_write_access)])
def update_provider_api_config(provider: str, config_update: dict) -> JSONResponse:
    """更新指定 Provider 的 API 配置（如 API Key）。"""
    try:
        api_provider = ApiProvider(provider)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown provider: {provider}")
    success = api_config_manager.update_config(api_provider, config_update)
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to update config for provider: {provider}")
    return JSONResponse(content={"status": "updated", "provider": provider})


@router.get("/runtime/api-config/{provider}/best", tags=["runtime"])
def get_best_available_api(provider: str) -> JSONResponse:
    """返回指定数据类型中最佳可用的 API Provider。"""
    try:
        data_type = DataType(provider)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown data type: {provider}")
    # get_best_available 需要 set[DataType]
    best = api_config_manager.get_best_available(required_capabilities={data_type})
    if best is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"No available API provider for data type: {provider}")
    # 返回可序列化格式
    return JSONResponse(content={
        "provider": best.provider.value,
        "name": best.name,
        "endpoint_url": best.endpoint.url,
        "capabilities": [c.value for c in best.endpoint.capabilities],
        "priority": best.priority,
    })
