"""Docker infrastructure management for the CGDA launcher.

Extracted from the original ``launch.py``. Owns Docker Compose lifecycle
for the backend runtime stack (Redis + MinIO + Open-Meteo API) and
Redis readiness checks.
"""

from __future__ import annotations

import subprocess
import time

from launch.constants import BACKEND_DIR, IS_WINDOWS
from launch.logging_setup import log
from launch.subprocess_utils import (
    ensure_named_volume,
    hidden_kwargs,
    resolve_open_meteo_volume_name,
)


def docker_available() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            **hidden_kwargs(),
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def start_docker_infra(*, start_open_meteo: bool = True) -> bool:
    """启动 Redis + MinIO；可选启动 backend 内的 cgda-open-meteo API。"""
    log.banner("启动 Docker 运行栈 (Redis + MinIO + Open-Meteo API)")
    if not docker_available():
        hint = (
            "请先启动 Docker Desktop"
            if IS_WINDOWS
            else "请先启动 Docker Engine / 守护进程"
        )
        log.error("Docker", f"Docker 未运行或未安装，{hint}")
        return False

    if start_open_meteo:
        ensure_named_volume(resolve_open_meteo_volume_name())

    services = ["redis", "minio", "minio-init"]
    if start_open_meteo:
        services.append("open-meteo")

    log.info("Docker", f"启动容器: {', '.join(services)}...")
    try:
        r = subprocess.run(
            ["docker", "compose", "-p", "backend", "up", "-d", *services],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=180,
            **hidden_kwargs(),
        )
        if r.returncode != 0:
            log.error("Docker", f"docker compose 启动失败:\n{r.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log.error("Docker", "docker compose 启动超时（180s）")
        return False

    log.ok("Docker", "容器已启动")
    log.info("Docker", "  Redis:  redis://127.0.0.1:6379/0")
    log.info(
        "Docker", "  MinIO:  API http://127.0.0.1:9100 | Console http://127.0.0.1:9101"
    )
    if start_open_meteo:
        log.info(
            "Docker",
            "  Open-Meteo API: http://127.0.0.1:8080 （named volume；同步: python launch.py sync）",
        )
    else:
        log.warn("Docker", "已跳过 Open-Meteo API（--no-open-meteo）")
    return True


def stop_docker_infra() -> None:
    log.info("Docker", "停止 backend 容器（Redis + MinIO + Open-Meteo API）...")
    try:
        subprocess.run(
            ["docker", "compose", "-p", "backend", "down"],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            **hidden_kwargs(),
        )
        log.ok("Docker", "backend 容器已停止")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.warn("Docker", "backend 容器停止超时或 Docker 不可用")


def wait_for_redis(max_wait: int = 30) -> bool:
    """等待 Redis 就绪。"""
    log.info("Redis", f"等待 Redis 就绪（最多 {max_wait}s）...")
    for i in range(max_wait):
        try:
            r = subprocess.run(
                ["docker", "exec", "cgda-redis", "redis-cli", "ping"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                **hidden_kwargs(),
            )
            if r.returncode == 0 and "PONG" in r.stdout:
                log.ok("Redis", "Redis 就绪")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        time.sleep(1)
    log.warn("Redis", f"Redis 未在 {max_wait}s 内就绪，继续启动（可能影响功能）")
    return False


def redis_running() -> bool:
    """快速检查 Redis 是否运行（3s 超时）。"""
    try:
        r = subprocess.run(
            ["docker", "exec", "cgda-redis", "redis-cli", "ping"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
            **hidden_kwargs(),
        )
        return r.returncode == 0 and "PONG" in r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
