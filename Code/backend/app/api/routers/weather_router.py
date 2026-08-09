import json
import logging
import time
from datetime import datetime, UTC
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
    get_redis_client,
    scan_keys,
)
from app.services.weather_bridge_service import weather_bridge_service
from app.weatherengine.service import weather_engine_service
from shared.contracts.api_contracts import WeatherPointResponse

router = APIRouter()

logger = logging.getLogger(__name__)

# ── 本地 Open-Meteo 数据覆盖范围探针（Phase 1c）──────────────
# C2：coverage 与本地线程 sync job 状态同时落 Redis（TTL 300s），多 worker 共享；
# 进程内 dict 仅作 Redis 不可用时的降级缓存。
_COVERAGE_CACHE: dict[str, dict] = {}
_COVERAGE_CACHE_TTL_SECONDS = 600  # 10 分钟
_COVERAGE_REDIS_PREFIX = "weather:coverage:"
_COVERAGE_REDIS_TTL_SECONDS = 300
_SYNC_JOB_REDIS_PREFIX = "weather:sync:job:"
_SYNC_JOB_REDIS_TTL_SECONDS = 300

# Celery 不可用 / broker 超时时的本进程同步任务状态（降级面；Redis 优先）
_LOCAL_SYNC_JOBS: dict[str, dict] = {}


def _parse_iso_ts(value: str) -> float:
    """Best-effort 解析 ISO8601 时间戳为 epoch 秒（失败返回 0，用于本地 job 清理）。"""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0


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


def invalidate_weather_coverage_cache(model: str | None = None) -> None:
    """同步成功后清除探针缓存（本地 + Redis）。

    - ``model`` 给定：删该模型的本地/Redis 键。
    - ``model`` 未给定（无参调用）：清空本地 dict，并按前缀扫描删除全部 Redis coverage 键
      （R-1 修复：此前无参版只清进程内 dict，而读端 Redis 优先，导致同步后各 worker
      仍会读到旧 coverage 直到 TTL 过期）。
    """
    client = get_redis_client()
    if model:
        _COVERAGE_CACHE.pop(f"local:{model}", None)
        if client is not None:
            try:
                client.delete(f"{_COVERAGE_REDIS_PREFIX}{model}")
            except Exception:  # noqa: BLE001 - best-effort
                pass
        return
    _COVERAGE_CACHE.clear()
    if client is None:
        return
    try:
        keys = scan_keys(client, f"{_COVERAGE_REDIS_PREFIX}*")
        if keys:
            client.delete(*keys)
    except Exception:  # noqa: BLE001 - best-effort，失效失败由 TTL 兜底
        logger.debug(
            "invalidate_weather_coverage_cache scan/delete failed", exc_info=True
        )


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

    # In-flight local-thread sync jobs
    overview["sync_in_progress"] = any(
        isinstance(job, dict)
        and str(job.get("state", "")).upper() in {"PENDING", "STARTED", "RETRY"}
        for job in _LOCAL_SYNC_JOBS.values()
    )
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
    """手动触发 Open-Meteo 数据同步。

    优先 Celery 异步派发；broker 卡住/超时时降级为本地后台线程。
    可选 body.domains 临时覆盖同步域（白名单校验，不改环境变量）。
    Docker/compose 不可用时返回 503 sync_unavailable。
    """
    import concurrent.futures
    import shutil
    import threading
    import uuid
    from datetime import datetime
    from pathlib import Path

    from app.core.celery_app import celery_available
    from app.core.config import settings
    from app.tasks.open_meteo_sync_tasks import (
        execute_open_meteo_sync,
        is_open_meteo_sync_locked,
        sync_open_meteo_data,
    )
    from app.weatherengine.supported_models import is_supported_weather_model

    domains_override: str | None = None
    if body.domains and body.domains.strip():
        parts = [p.strip() for p in body.domains.split(",") if p.strip()]
        if not parts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="domains must list at least one model id",
            )
        bad = [p for p in parts if not is_supported_weather_model(p)]
        if bad:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported weather model(s): {', '.join(bad)}",
            )
        domains_override = ",".join(parts)

    # C1：全局互斥——同一 domains 的同步已在运行（API/Beat/launch 任一入口）时返回 409。
    domains_eff = domains_override or settings.open_meteo_sync_domains
    if is_open_meteo_sync_locked(domains_eff):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "sync_in_progress",
                "message": (
                    f"Open-Meteo 同步正在进行中（domains={domains_eff}），"
                    "请稍后再试或查询 /weather/sync/status。"
                ),
            },
        )

    docker_ok = bool(shutil.which("docker"))
    compose_ok = Path(
        settings.open_meteo_sync_compose_dir, "docker-compose.yml"
    ).is_file()
    if not docker_ok or not compose_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "sync_unavailable",
                "message": (
                    "Open-Meteo sync service unavailable: "
                    + (
                        "Docker CLI not found"
                        if not docker_ok
                        else f"compose file missing under {settings.open_meteo_sync_compose_dir}"
                    )
                ),
                "docker_cli_available": docker_ok,
                "compose_file_exists": compose_ok,
            },
        )

    def _record_local_sync_job(task_id: str, job: dict) -> None:
        """写入本地线程 sync job 状态：进程内 dict + Redis（TTL 300s，多 worker 共享）。"""
        _LOCAL_SYNC_JOBS[task_id] = job
        # 顺手清理超期 job，避免进程内 dict 无限增长
        cutoff = time.time() - _SYNC_JOB_REDIS_TTL_SECONDS
        stale = [
            tid
            for tid, j in _LOCAL_SYNC_JOBS.items()
            if j.get("finished_at") and _parse_iso_ts(j["finished_at"]) < cutoff
        ]
        for tid in stale:
            _LOCAL_SYNC_JOBS.pop(tid, None)
        cache_set_json(
            f"{_SYNC_JOB_REDIS_PREFIX}{task_id}",
            job,
            _SYNC_JOB_REDIS_TTL_SECONDS,
        )

    def _run_local(task_id: str) -> None:
        _record_local_sync_job(
            task_id,
            {
                "task_id": task_id,
                "state": "STARTED",
                "info": None,
                "mode": "local_thread",
                "finished_at": None,
                "domains": domains_override or settings.open_meteo_sync_domains,
            },
        )
        try:
            result = execute_open_meteo_sync(domains=domains_override)
            invalidate_weather_coverage_cache()
            _record_local_sync_job(
                task_id,
                {
                    "task_id": task_id,
                    "state": "SUCCESS",
                    "info": result,
                    "mode": "local_thread",
                    "finished_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            logger.exception("Local Open-Meteo sync thread failed")
            # 记录失败摘要，便于断网/Docker 不可用诊断
            _record_local_sync_job(
                task_id,
                {
                    "task_id": task_id,
                    "state": "FAILURE",
                    "info": str(exc),
                    "mode": "local_thread",
                    "finished_at": datetime.now(UTC).isoformat(),
                    "error": str(exc),
                },
            )

    def _dispatch_local(reason: str) -> dict:
        task_id = f"local-{uuid.uuid4().hex[:12]}"
        thread = threading.Thread(
            target=_run_local,
            args=(task_id,),
            name=f"om-sync-{task_id}",
            daemon=True,
        )
        thread.start()
        return {
            "status": "dispatched",
            "task_id": task_id,
            "mode": "local_thread",
            "domains": domains_override or settings.open_meteo_sync_domains,
            "message": (
                f"{reason} Sync running in a local background thread. "
                "Poll /weather/sync/status?task_id=..."
            ),
        }

    # 1) 尝试 Celery（限时；池退出 wait=False，避免 broker 挂起拖死 HTTP）
    if celery_available:
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            fut = pool.submit(
                lambda: sync_open_meteo_data.apply_async(
                    kwargs={"domains": domains_override} if domains_override else {},
                    queue=settings.workflow_queue_weather_batch,
                )
            )
            async_result = fut.result(timeout=4)
            return {
                "status": "dispatched",
                "task_id": async_result.task_id,
                "mode": "celery",
                "domains": domains_override or settings.open_meteo_sync_domains,
                "message": "Sync task dispatched via Celery. Poll /weather/sync/status?task_id=...",
            }
        except concurrent.futures.TimeoutError:
            logger.warning("Celery apply_async timed out; falling back to local thread")
            return _dispatch_local("Celery broker timeout;")
        except Exception as exc:
            logger.warning(
                "Celery dispatch failed (%s); falling back to local thread", exc
            )
            return _dispatch_local(f"Celery dispatch failed ({exc});")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    # 2) Celery 不可用：本进程后台线程
    return _dispatch_local("Celery unavailable;")


@router.get("/weather/sync/status", tags=["weather"])
def get_open_meteo_sync_status(task_id: str):
    """查询同步任务状态（含完成时间 / domains / 错误摘要）。"""
    from app.core.celery_app import celery_app, celery_available
    from app.core.config import settings

    # C2：本地线程降级任务——Redis 优先（多 worker 共享），miss 回落到进程内 dict
    redis_job = cache_get_json(f"{_SYNC_JOB_REDIS_PREFIX}{task_id}")
    if redis_job is not None and isinstance(redis_job, dict):
        return {
            "task_id": task_id,
            "state": redis_job.get("state"),
            "info": redis_job.get("info"),
            "mode": redis_job.get("mode", "local_thread"),
            "finished_at": redis_job.get("finished_at"),
            "error": redis_job.get("error"),
            "domains": redis_job.get("domains") or settings.open_meteo_sync_domains,
        }

    if task_id in _LOCAL_SYNC_JOBS:
        job = _LOCAL_SYNC_JOBS[task_id]
        return {
            "task_id": task_id,
            "state": job.get("state"),
            "info": job.get("info"),
            "mode": "local_thread",
            "finished_at": job.get("finished_at"),
            "error": job.get("error"),
            "domains": settings.open_meteo_sync_domains,
        }

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
        try:
            invalidate_weather_coverage_cache()
        except Exception:
            pass
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
