import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse

from app.api.deps import require_write_access

from app.api.routers._helpers import service_json_response
from app.core.redis_client import (
    cache_get_json,
    cache_set_json,
)
from app.services.weather_bridge_service import weather_bridge_service
from app.services.weather_coverage_cache import (
    COVERAGE_CACHE as _COVERAGE_CACHE,
    COVERAGE_CACHE_TTL_SECONDS as _COVERAGE_CACHE_TTL_SECONDS,
    COVERAGE_REDIS_PREFIX as _COVERAGE_REDIS_PREFIX,
    COVERAGE_REDIS_TTL_SECONDS as _COVERAGE_REDIS_TTL_SECONDS,
    invalidate_weather_coverage_cache,
)
from app.weatherengine.service import weather_engine_service
from shared.contracts.api_contracts import WeatherPointResponse
import contextlib

router = APIRouter()

logger = logging.getLogger(__name__)

# ── 本地 Open-Meteo 数据覆盖范围探针（Phase 1c）──────────────
# C2：coverage 缓存落 Redis（TTL 300s），多 worker 共享；
# 进程内 dict 仅作 Redis 不可用时的降级缓存。
# L1: sync job 状态已迁移至 weather_sync_service。
# P0-2: 缓存状态和失效函数迁移至 weather_coverage_cache 模块，消除反向依赖。


def _probe_local_open_meteo_coverage(model: str) -> tuple[dict | None, str | None]:
    """返回 (coverage, error_code)。

    error_code:
    - ``local_unreachable``：容器/网络不可达
    - ``model_empty``：可达但无可用时次（模型未 sync 或值全空）
    - ``probe_error``：其它解析错误

    coverage 字段：
    - ``times``：原始 hourly.time（供瓦片 hour 索引映射，与 Open-Meteo 对齐）
    - ``valid_times``：temperature 非空的时次（供时间轴绿/紫着色）
    """
    cache_key = f"local:{model}"
    # C2：Redis 优先（多 worker 共享），miss 才本地缓存/探针
    redis_key = f"{_COVERAGE_REDIS_PREFIX}{model}"
    redis_hit = cache_get_json(redis_key)
    if redis_hit is not None:
        _COVERAGE_CACHE[cache_key] = {**redis_hit, "_ts": time.time()}
        return {k: v for k, v in redis_hit.items() if k != "_ts"}, None
    cached = _COVERAGE_CACHE.get(cache_key)
    if cached and time.time() - cached["_ts"] < _COVERAGE_CACHE_TTL_SECONDS:
        return {k: v for k, v in cached.items() if k != "_ts"}, None

    from app.weatherengine.provider_ids import OPEN_METEO_LOCAL_URL

    probe_url = (
        f"{OPEN_METEO_LOCAL_URL}?latitude=23.13&longitude=113.26"
        f"&hourly=temperature_2m&models={model}&forecast_days=16&timezone=Asia%2FShanghai"
    )
    try:
        with urlopen(probe_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, OSError) as exc:
        logger.warning(
            "weather coverage probe unreachable for model=%s: %s", model, exc
        )
        return None, "local_unreachable"
    except json.JSONDecodeError as exc:
        logger.warning(
            "weather coverage probe decode failed for model=%s: %s", model, exc
        )
        return None, "probe_error"

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    if not times:
        return None, "model_empty"

    # 仅非空温度计入「有效覆盖」；全空则视为模型未 sync
    valid_times: list[str] = []
    for i, iso in enumerate(times):
        val = temps[i] if i < len(temps) else None
        if val is not None:
            valid_times.append(iso)
    if not valid_times:
        return None, "model_empty"

    coverage = {
        "model": model,
        "source": "local",
        "data_start_iso": valid_times[0],
        "data_end_iso": valid_times[-1],
        "hour_count": len(times),
        "valid_hour_count": len(valid_times),
        # 保留完整 times 供瓦片索引；UI 着色用 valid_times
        "times": times,
        "valid_times": valid_times,
        "max_tile_hour": min(47, max(0, len(times) - 1)),
        "probe_ts": time.time(),
    }
    _COVERAGE_CACHE[cache_key] = {**coverage, "_ts": time.time()}
    cache_set_json(redis_key, coverage, _COVERAGE_REDIS_TTL_SECONDS)
    return coverage, None


@router.get("/weather/coverage", tags=["weather"])
def get_weather_coverage(model: str | None = None):
    """返回本地 Open-Meteo 数据覆盖范围，供前端时间轴限制可选时段。"""
    from app.services.weather_engine_settings import get_effective_weather_default_model

    resolved_model = (
        model or get_effective_weather_default_model()
    ).strip() or get_effective_weather_default_model()
    coverage, error_code = _probe_local_open_meteo_coverage(resolved_model)
    if coverage is None:
        messages = {
            "local_unreachable": "Local Open-Meteo is unreachable (container may be down).",
            "model_empty": f"No usable data for model={resolved_model} (not synced or empty hourly).",
            "probe_error": f"Coverage probe failed for model={resolved_model}.",
        }
        code = error_code or "probe_error"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": code,
                "message": messages.get(code, messages["probe_error"]),
                "model": resolved_model,
            },
        )
    return coverage


@router.get("/weather/sync/overview", tags=["weather"])
def get_open_meteo_sync_overview():
    """Open-Meteo 同步与本地可达性总览（设置页 / 运维）。"""
    from app.services.config_service import get_weather_sync_overview
    from app.services.weather_engine_settings import get_effective_weather_default_model

    overview = get_weather_sync_overview()

    # Enrich coverage snapshot (same probe as /weather/coverage)
    try:
        model = get_effective_weather_default_model()
        cov, err = _probe_local_open_meteo_coverage(model)
        if cov is not None:
            overview["coverage"] = {
                "model": cov.get("model", model),
                "data_start_iso": cov.get("data_start_iso"),
                "data_end_iso": cov.get("data_end_iso"),
                "hour_count": cov.get("hour_count"),
                "valid_hour_count": cov.get("valid_hour_count"),
                "max_tile_hour": cov.get("max_tile_hour"),
            }
            overview["coverage_error"] = None
        else:
            overview["coverage"] = None
            overview["coverage_error"] = err or "probe_error"
    except Exception as exc:
        logger.debug("overview coverage enrich failed: %s", exc)
        overview["coverage_error"] = overview.get("coverage_error") or "probe_error"

    # L1: in-flight sync 查询委托给 service
    from app.services.weather_sync_service import has_in_progress_sync

    overview["sync_in_progress"] = has_in_progress_sync()
    return overview


class OpenMeteoSyncTriggerRequest(BaseModel):
    """Optional one-shot domains override (does not persist OPEN_METEO_SYNC_DOMAINS)."""

    domains: str | None = Field(
        default=None,
        description="Comma-separated model ids for this sync only, e.g. ecmwf_ifs025,gfs_global",
    )


@router.post(
    "/weather/sync/trigger",
    tags=["weather"],
    dependencies=[Depends(require_write_access)],
)
def trigger_open_meteo_sync(
    body: OpenMeteoSyncTriggerRequest = OpenMeteoSyncTriggerRequest(),
):
    """手动触发 Open-Meteo 数据同步（L1: 业务逻辑已抽取到 weather_sync_service）。"""
    from app.services.weather_sync_service import (
        SyncInProgressError,
        SyncUnavailableError,
        SyncValidationError,
        trigger_sync,
    )

    try:
        return trigger_sync(body.domains)
    except SyncValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SyncInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "sync_in_progress",
                "message": (
                    f"Open-Meteo 同步正在进行中（domains={exc.domains}），"
                    "请稍后再试或查询 /weather/sync/status。"
                ),
            },
        ) from exc
    except SyncUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "sync_unavailable",
                "message": str(exc),
                "docker_cli_available": exc.docker_ok,
                "compose_file_exists": exc.compose_ok,
            },
        ) from exc


@router.get("/weather/sync/status", tags=["weather"])
def get_open_meteo_sync_status(task_id: str):
    """查询同步任务状态（含完成时间 / domains / 错误摘要）。"""
    from app.core.celery_app import celery_app, celery_available
    from app.core.config import settings
    from app.services.weather_sync_service import get_local_sync_job

    # L1: Redis + 进程内 dict 查询委托给 service
    local_job = get_local_sync_job(task_id)
    if local_job is not None:
        return local_job

    if not celery_available or celery_app is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Celery is not available and no local sync job matched this task_id.",
        )
    from celery.result import AsyncResult

    result: AsyncResult = celery_app.AsyncResult(task_id)
    state = result.state
    info = (
        result.info
        if result.successful()
        else str(result.info)
        if result.info
        else None
    )
    payload: dict = {
        "task_id": task_id,
        "state": state,
        "info": info,
        "mode": "celery",
        "domains": settings.open_meteo_sync_domains,
    }
    if result.successful() and isinstance(info, dict):
        payload["finished_at"] = info.get("finished_at")
        payload["domains"] = info.get("domains") or settings.open_meteo_sync_domains
        payload["stdout_tail"] = info.get("stdout_tail")
        with contextlib.suppress(Exception):
            invalidate_weather_coverage_cache()
    if state == "FAILURE":
        payload["error"] = str(result.info) if result.info else "sync failed"
        tb = getattr(result, "traceback", None)
        if tb:
            payload["stderr_tail"] = str(tb)[-2000:]
    return payload


def _weather_service_response(service_call) -> JSONResponse:
    try:
        return service_json_response(service_call())
    except RuntimeError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "disabled" in detail.lower() or "initialize" in detail.lower()
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/weather/point", tags=["weather"], response_model=WeatherPointResponse)
def get_weather_point(
    layer_id: str,
    latitude: float,
    longitude: float,
    model: str | None = None,
    forecast_hours: int = 6,
    place_name: str | None = None,
    provider: str | None = None,
) -> WeatherPointResponse:
    try:
        return weather_engine_service.get_point_weather(
            layer_id=layer_id,
            latitude=latitude,
            longitude=longitude,
            model=model,
            forecast_hours=forecast_hours,
            place_name=place_name,
            provider_id=provider,
        )
    except ValueError as exc:
        detail = str(exc)
        lower = detail.lower()
        if any(
            token in lower
            for token in (
                "no enabled weather provider",
                "is disabled",
                "is not registered",
                "does not support layer",
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=detail
        ) from exc
    except (HTTPError, URLError) as exc:
        detail = "Weather point forecast is temporarily unavailable."
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail
        ) from exc


@router.get("/weather/providers-for-layer/{layer_id}", tags=["weather"])
def get_providers_for_layer(layer_id: str, include_disabled: bool = False):
    """List weather providers that declare support for ``layer_id`` (for layer source dropdown)."""
    from app.weatherengine.constants import WEATHER_LAYER_SPECS
    from app.weatherengine.fetch_gateway import list_providers_for_layer
    from app.services.config_service import _ensure_weather_providers_registered

    if layer_id not in WEATHER_LAYER_SPECS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown weather layer: {layer_id}",
        )
    _ensure_weather_providers_registered()
    return {
        "layer_id": layer_id,
        "providers": list_providers_for_layer(
            layer_id, include_disabled=include_disabled
        ),
    }


@router.get("/weather/workflows", tags=["weather"])
def list_weather_workflows() -> JSONResponse:
    return _weather_service_response(weather_bridge_service.list_workflows_response)


@router.get("/weather/workflows/diagnostics", tags=["weather"])
def get_weather_diagnostics() -> JSONResponse:
    return _weather_service_response(weather_bridge_service.get_diagnostics_response)


@router.get("/weather/workflows/{workflow_name}", tags=["weather"])
def describe_weather_workflow(workflow_name: str) -> JSONResponse:
    return _weather_service_response(
        lambda: weather_bridge_service.describe_workflow_response(workflow_name)
    )
