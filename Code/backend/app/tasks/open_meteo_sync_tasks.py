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
from typing import Any

from app.core.celery_app import celery_app, celery_available
from app.core.config import settings

logger = logging.getLogger(__name__)

# 同步任务超时（秒）：ECMWF IFS 0.25° 全球同步约 10-30 分钟
_SYNC_TIMEOUT_SECONDS = 3600


def _build_sync_command() -> list[str]:
    """构建 docker compose sync 命令。

    数据栈：`Code/infra/data-sync`（`-p data-sync`）；API 在 backend（`cgda-open-meteo`）。
    官方镜像：`sync <domains> <variables>`（尾部参数覆盖 compose 默认 command）。
    """
    project = settings.open_meteo_sync_compose_project
    domains = settings.open_meteo_sync_domains
    variables = settings.open_meteo_sync_variables
    compose_file = os.path.join(settings.open_meteo_sync_compose_dir, "docker-compose.yml")
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


def execute_open_meteo_sync() -> dict[str, Any]:
    """执行 Open-Meteo 同步（非 Celery 入口，可供 API 直接调用）。

    同步期间旧数据继续可用：open-meteo 容器读取的是 named volume，
    sync 容器覆盖文件时 open-meteo 容器不会中断服务。

    返回同步结果摘要。失败时抛 RuntimeError。
    """
    from datetime import datetime, timezone

    from app.services.weather_engine_settings import record_open_meteo_sync_result

    _ensure_sync_volume()
    cmd = _build_sync_command()
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
            domains=settings.open_meteo_sync_domains,
            message="docker command not found; ensure Docker is installed",
            exit_code=None,
        )
        raise RuntimeError("docker command not found; ensure Docker is installed") from exc
    except subprocess.TimeoutExpired as exc:
        record_open_meteo_sync_result(
            ok=False,
            domains=settings.open_meteo_sync_domains,
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
            domains=settings.open_meteo_sync_domains,
            message=f"exit code {result.returncode}",
            exit_code=result.returncode,
            stderr_tail=stderr_tail,
        )
        raise RuntimeError(
            f"Open-Meteo sync failed with exit code {result.returncode}: "
            f"{result.stderr[-500:] if result.stderr else 'no stderr'}"
        )

    finished_at = datetime.now(timezone.utc).isoformat()
    logger.info("Open-Meteo sync completed successfully")
    record_open_meteo_sync_result(
        ok=True,
        domains=settings.open_meteo_sync_domains,
        message="ok",
        exit_code=0,
        stderr_tail=result.stderr[-500:] if result.stderr else "",
    )
    return {
        "status": "succeeded",
        "domains": settings.open_meteo_sync_domains,
        "stdout_tail": result.stdout[-1000:] if result.stdout else "",
        "finished_at": finished_at,
    }


if celery_available and celery_app is not None:

    @celery_app.task(
        name="app.tasks.open_meteo_sync_tasks.sync_open_meteo_data",
        queue=settings.workflow_queue_weather_batch,
        soft_time_limit=3600,
        time_limit=3900,
    )
    def sync_open_meteo_data() -> dict[str, Any]:
        """Celery 任务入口：定时同步本地 Open-Meteo 数据（weather-batch 队列）。"""
        return execute_open_meteo_sync()

else:

    def sync_open_meteo_data() -> dict[str, Any]:
        raise RuntimeError(
            "Celery is not installed. Install backend dependencies before using Open-Meteo sync tasks."
        )
