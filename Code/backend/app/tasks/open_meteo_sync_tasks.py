"""
Phase 2: Open-Meteo 本地数据自动同步任务。

通过 Celery Beat 定时调用 `docker compose run --rm open-meteo-sync` 触发同步。
- 同步期间旧数据继续可用（sync 是追加/覆盖文件，不删除）
- 同步失败不影响线上服务，下次 beat 触发时重试
- 支持多模型同步（通过 OPEN_METEO_SYNC_DOMAINS 配置）
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import uuid
from typing import Any

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings
from app.core.redis_client import (
    acquire_dedup_lock,
    get_redis_client,
    release_dedup_lock,
)
from datetime import UTC

logger = logging.getLogger(__name__)

# 同步任务超时（秒）：ECMWF IFS 0.25° 全球同步约 10-30 分钟
_SYNC_TIMEOUT_SECONDS = 3600

# ─── 全局同步互斥（C1 + L-1）──────────────────────────────────────
# 三入口（API trigger / Celery Beat task / launch.py sync）共用同一把锁：
# - Redis 可用：SET NX key=sync:{domains}（value=owner token，Lua 比对后删除；
#   TTL=7200s > 最长同步时长 3600s，避免锁在同步期间过期被他人接管后误删他人锁）
# - Redis 不可用：进程内 threading 互斥兜底（仅单进程内串行）
_SYNC_LOCK_TTL_SECONDS = 7200
_sync_local_lock = threading.Lock()
_sync_local_holders: set[str] = set()


def _sync_lock_key(domains: str) -> str:
    return f"sync:{domains or 'default'}"


def acquire_open_meteo_sync_lock(
    domains: str, ttl_seconds: int = _SYNC_LOCK_TTL_SECONDS
) -> str | None:
    """尝试获取全局同步锁。

    Returns:
        持有者 token（str）：获取成功；None：锁已被其他入口持有。
    """
    key = _sync_lock_key(domains)
    if get_redis_client() is not None:
        return acquire_dedup_lock(key, ttl_seconds=ttl_seconds)
    with _sync_local_lock:
        if key in _sync_local_holders:
            return None
        _sync_local_holders.add(key)
        return f"local-{uuid.uuid4().hex}"


def release_open_meteo_sync_lock(domains: str, token: str | None = None) -> None:
    """释放全局同步锁（须与 acquire 返回的 token 配对）。"""
    key = _sync_lock_key(domains)
    if get_redis_client() is not None:
        release_dedup_lock(key, token)
        return
    with _sync_local_lock:
        _sync_local_holders.discard(key)


def is_open_meteo_sync_locked(domains: str) -> bool:
    """只读探测锁是否被持有（API 用于快速 409，不实际获取锁）。"""
    key = _sync_lock_key(domains)
    client = get_redis_client()
    if client is not None:
        try:
            return client.get(key) is not None
        except Exception:  # noqa: BLE001 - 探测失败按未持有处理
            return False
    with _sync_local_lock:
        return key in _sync_local_holders


def _build_sync_command(domains: str | None = None) -> list[str]:
    """构建 docker compose sync 命令。

    数据栈：`Code/infra/data-sync`（`-p data-sync`）；API 在 backend（`cgda-open-meteo`）。
    官方镜像：`sync <domains> <variables>`（尾部参数覆盖 compose 默认 command）。
    ``domains`` 可临时覆盖环境默认（不改持久配置）。
    """
    project = settings.open_meteo_sync_compose_project
    domains = (domains or settings.open_meteo_sync_domains or "").strip()
    variables = settings.open_meteo_sync_variables
    compose_file = os.path.join(
        settings.open_meteo_sync_compose_dir, "docker-compose.yml"
    )
    env_file = os.path.join(settings.open_meteo_sync_compose_dir, ".env")

    cmd = [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        compose_file,
    ]
    if os.path.isfile(env_file):
        cmd.extend(["--env-file", env_file])
    cmd.extend(
        [
            "--profile",
            "sync",
            "run",
            "--rm",
            "open-meteo-sync",
            "sync",
            domains,
            variables,
        ]
    )
    return cmd


def _ensure_sync_volume() -> None:
    """Ensure shared named volume exists (data-sync compose marks it external)."""
    vol = "backend_open-meteo-data"
    env_file = os.path.join(settings.open_meteo_sync_compose_dir, ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    key, _, val = s.partition("=")
                    if key.strip() == "OPEN_METEO_DATA_VOLUME":
                        name = val.strip().strip('"').strip("'")
                        if name:
                            vol = name
                        break
        except OSError:
            pass
    try:
        inspect = subprocess.run(
            ["docker", "volume", "inspect", vol],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if inspect.returncode == 0:
            return
        create = subprocess.run(
            ["docker", "volume", "create", vol],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if create.returncode != 0:
            logger.warning(
                "Failed to create volume %s: %s",
                vol,
                (create.stderr or create.stdout or "")[-300:],
            )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Volume ensure skipped: %s", exc)


def execute_open_meteo_sync(domains: str | None = None) -> dict[str, Any]:
    """执行 Open-Meteo 同步（非 Celery 入口，可供 API 直接调用）。

    同步期间旧数据继续可用：open-meteo 容器读取的是 named volume，
    sync 容器覆盖文件时 open-meteo 容器不会中断服务。

    ``domains``：逗号分隔模型 id，临时覆盖 ``OPEN_METEO_SYNC_DOMAINS``（不落库）。
    返回同步结果摘要。失败时抛 RuntimeError。
    """
    from datetime import datetime

    from app.services.weather_engine_settings import record_open_meteo_sync_result

    domains_eff = (domains or settings.open_meteo_sync_domains or "").strip()
    if not domains_eff:
        raise RuntimeError(
            "Open-Meteo sync domains empty; set OPEN_METEO_SYNC_DOMAINS or pass domains="
        )

    # C1：全局互斥——锁被持有（另一进程/线程正在同步）时直接跳过，不重复跑 docker。
    lock_token = acquire_open_meteo_sync_lock(domains_eff)
    if lock_token is None:
        logger.warning("Open-Meteo sync skipped: lock held for domains=%s", domains_eff)
        return {
            "status": "skipped",
            "domains": domains_eff,
            "message": "another sync is already running for these domains",
            "finished_at": datetime.now(UTC).isoformat(),
        }

    try:
        _ensure_sync_volume()
        cmd = _build_sync_command(domains=domains_eff)
        logger.info("Open-Meteo sync starting: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                cwd=settings.open_meteo_sync_compose_dir,
                timeout=_SYNC_TIMEOUT_SECONDS,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            record_open_meteo_sync_result(
                ok=False,
                domains=domains_eff,
                message="docker command not found; ensure Docker is installed",
                exit_code=None,
            )
            raise RuntimeError(
                "docker command not found; ensure Docker is installed"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            record_open_meteo_sync_result(
                ok=False,
                domains=domains_eff,
                message=f"Open-Meteo sync timed out after {_SYNC_TIMEOUT_SECONDS}s",
                exit_code=None,
            )
            raise RuntimeError(
                f"Open-Meteo sync timed out after {_SYNC_TIMEOUT_SECONDS}s"
            ) from exc

        if result.returncode != 0:
            stderr_tail = result.stderr[-2000:] if result.stderr else ""
            logger.error(
                "Open-Meteo sync failed (exit=%d): stderr=%s",
                result.returncode,
                stderr_tail,
            )
            record_open_meteo_sync_result(
                ok=False,
                domains=domains_eff,
                message=f"exit code {result.returncode}",
                exit_code=result.returncode,
                stderr_tail=stderr_tail,
            )
            raise RuntimeError(
                f"Open-Meteo sync failed with exit code {result.returncode}: "
                f"{result.stderr[-500:] if result.stderr else 'no stderr'}"
            )

        finished_at = datetime.now(UTC).isoformat()
        logger.info("Open-Meteo sync completed successfully")
        record_open_meteo_sync_result(
            ok=True,
            domains=domains_eff,
            message="ok",
            exit_code=0,
            stderr_tail=result.stderr[-500:] if result.stderr else "",
        )
        # R-1：Celery worker 内同步成功后主动失效 coverage 探针缓存（读端 Redis 优先），
        # 避免各 worker 继续读旧 coverage 直至 TTL 过期。
        try:
            from app.api.routers.weather_router import (
                invalidate_weather_coverage_cache,
            )

            invalidate_weather_coverage_cache()
        except Exception:  # noqa: BLE001 - 失效失败由 TTL 兜底，不影响同步结果
            logger.debug(
                "Open-Meteo sync: coverage cache invalidation failed", exc_info=True
            )
        return {
            "status": "succeeded",
            "domains": domains_eff,
            "stdout_tail": result.stdout[-1000:] if result.stdout else "",
            "finished_at": finished_at,
        }
    finally:
        release_open_meteo_sync_lock(domains_eff, lock_token)


if celery_available and celery_app is not None:

    @celery_app.task(
        name="app.tasks.open_meteo_sync_tasks.sync_open_meteo_data",
        queue=settings.workflow_queue_weather_batch,
        soft_time_limit=3600,
        time_limit=3900,
    )
    def sync_open_meteo_data(domains: str | None = None) -> dict[str, Any]:
        """Celery 任务入口：定时同步本地 Open-Meteo 数据（weather-batch 队列）。

        ``domains`` 可选；Beat 定时调用不传，沿用环境默认。
        """
        return execute_open_meteo_sync(domains=domains)

else:

    def sync_open_meteo_data(domains: str | None = None) -> dict[str, Any]:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using Open-Meteo sync tasks."
        )
