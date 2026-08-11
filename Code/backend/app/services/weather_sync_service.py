"""Open-Meteo 数据同步服务（L1: 从 weather_router 抽取的业务编排层）。

职责：
- 同步触发：域校验、互斥锁、Docker 可用性检查、Celery 派发 + 本地降级
- 同步状态查询：Redis 优先 → 进程内 dict → Celery AsyncResult
- 本地降级任务跟踪：进程内 dict + Redis 共享

router 只保留 HTTP 壳（请求模型、异常翻译），业务逻辑在此。
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
import uuid
from datetime import datetime, UTC
from pathlib import Path

from app.core.redis_client import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)

# ── 常量（从 weather_router 迁移） ───────────────────────────────────────────

_SYNC_JOB_REDIS_PREFIX = "weather:sync:job:"
_SYNC_JOB_REDIS_TTL_SECONDS = 300

# G1-07: 模块级共享 executor，用于 Celery apply_async 限时派发
_sync_dispatch_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

# Celery 不可用 / broker 超时时的本进程同步任务状态（降级面；Redis 优先）
_LOCAL_SYNC_JOBS: dict[str, dict] = {}


# ── 工具函数 ─────────────────────────────────────────────────────────────────


def _parse_iso_ts(value: str) -> float:
    """Best-effort 解析 ISO8601 时间戳为 epoch 秒（失败返回 0，用于本地 job 清理）。"""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0


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


# ── 异常类型 ─────────────────────────────────────────────────────────────────


class SyncValidationError(ValueError):
    """域校验失败（空域 / 不支持的模型）。"""


class SyncInProgressError(Exception):
    """同一 domains 的同步已在运行。"""

    def __init__(self, domains: str) -> None:
        self.domains = domains
        super().__init__(f"Sync in progress for domains={domains}")


class SyncUnavailableError(Exception):
    """Docker / compose 不可用。"""

    def __init__(self, docker_ok: bool, compose_ok: bool, compose_dir: str) -> None:
        self.docker_ok = docker_ok
        self.compose_ok = compose_ok
        self.compose_dir = compose_dir
        super().__init__(
            "Open-Meteo sync service unavailable: "
            + (
                "Docker CLI not found"
                if not docker_ok
                else f"compose file missing under {compose_dir}"
            )
        )


# ── 同步触发 ─────────────────────────────────────────────────────────────────


def trigger_sync(domains_override: str | None) -> dict:
    """触发 Open-Meteo 数据同步（L1: 从 weather_router 抽取）。

    优先 Celery 异步派发；broker 卡住/超时时降级为本地后台线程。

    Args:
        domains_override: 逗号分隔的模型 ID（可选，临时覆盖同步域）

    Returns:
        派发结果 dict（status / task_id / mode / domains / message）

    Raises:
        SyncValidationError: 域校验失败
        SyncInProgressError: 同步已在运行
        SyncUnavailableError: Docker/compose 不可用
    """
    import shutil

    from app.core.celery_app import celery_available
    from app.core.config import settings
    from app.tasks.open_meteo_sync_tasks import (
        execute_open_meteo_sync,
        is_open_meteo_sync_locked,
        sync_open_meteo_data,
    )
    from app.weatherengine.supported_models import is_supported_weather_model

    # ── 域校验 ───────────────────────────────────────────────────────────
    resolved_override: str | None = None
    if domains_override and domains_override.strip():
        parts = [p.strip() for p in domains_override.split(",") if p.strip()]
        if not parts:
            raise SyncValidationError("domains must list at least one model id")
        bad = [p for p in parts if not is_supported_weather_model(p)]
        if bad:
            raise SyncValidationError(f"Unsupported weather model(s): {', '.join(bad)}")
        resolved_override = ",".join(parts)

    # ── 全局互斥 ─────────────────────────────────────────────────────────
    domains_eff = resolved_override or settings.open_meteo_sync_domains
    if is_open_meteo_sync_locked(domains_eff):
        raise SyncInProgressError(domains_eff)

    # ── Docker 可用性 ────────────────────────────────────────────────────
    docker_ok = bool(shutil.which("docker"))
    compose_ok = Path(
        settings.open_meteo_sync_compose_dir, "docker-compose.yml"
    ).is_file()
    if not docker_ok or not compose_ok:
        raise SyncUnavailableError(
            docker_ok, compose_ok, settings.open_meteo_sync_compose_dir
        )

    # ── 本地降级路径 ─────────────────────────────────────────────────────
    def _run_local(task_id: str) -> None:
        _record_local_sync_job(
            task_id,
            {
                "task_id": task_id,
                "state": "STARTED",
                "info": None,
                "mode": "local_thread",
                "finished_at": None,
                "domains": resolved_override or settings.open_meteo_sync_domains,
            },
        )
        try:
            result = execute_open_meteo_sync(domains=resolved_override)
            # 同步成功后失效 coverage 缓存（从 weather_router 导入）
            from app.api.routers.weather_router import invalidate_weather_coverage_cache

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
            "domains": resolved_override or settings.open_meteo_sync_domains,
            "message": (
                f"{reason} Sync running in a local background thread. "
                "Poll /weather/sync/status?task_id=..."
            ),
        }

    # ── Celery 派发（限时；共享 executor） ────────────────────────────────
    if celery_available:
        try:
            fut = _sync_dispatch_executor.submit(
                lambda: sync_open_meteo_data.apply_async(
                    kwargs={"domains": resolved_override} if resolved_override else {},
                    queue=settings.workflow_queue_weather_batch,
                )
            )
            async_result = fut.result(timeout=4)
            return {
                "status": "dispatched",
                "task_id": async_result.task_id,
                "mode": "celery",
                "domains": resolved_override or settings.open_meteo_sync_domains,
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

    # Celery 不可用：本进程后台线程
    return _dispatch_local("Celery unavailable;")


# ── 状态查询辅助（router 调用） ───────────────────────────────────────────────


def has_in_progress_sync() -> bool:
    """检查是否有正在运行的本地降级同步任务。"""
    return any(
        isinstance(job, dict)
        and str(job.get("state", "")).upper() in {"PENDING", "STARTED", "RETRY"}
        for job in _LOCAL_SYNC_JOBS.values()
    )


def get_local_sync_job(task_id: str) -> dict | None:
    """查询本地降级 sync job（Redis 优先 → 进程内 dict）。

    供 router 的 /weather/sync/status 调用；Celery AsyncResult 由 router 自行处理。
    """
    from app.core.config import settings

    # Redis 优先（多 worker 共享）
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

    # 进程内 dict 降级缓存
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

    return None
