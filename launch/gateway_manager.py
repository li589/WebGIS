"""Nginx gateway (demo / public same-origin entry on :5175).

Separate compose project ``gateway`` so it does not mix with backend /
data-sync stacks. Mutually exclusive with Vite on the same port.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from launch.constants import FRONTEND_DIR, GATEWAY_DIR, IS_WINDOWS
from launch.logging_setup import log
from launch.subprocess_utils import hidden_kwargs, terminate_by_cmdline_patterns

from launch.docker_manager import docker_available

GATEWAY_CONTAINER = "cgda-gateway-nginx"
GATEWAY_PROJECT = "gateway"
GATEWAY_PORT = 5175


def gateway_compose_file() -> Path:
    return GATEWAY_DIR / "docker-compose.yml"


def frontend_dist_index() -> Path:
    return FRONTEND_DIR / "dist" / "index.html"


def gateway_running() -> bool:
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", GATEWAY_CONTAINER],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            **hidden_kwargs(),
        )
        return r.returncode == 0 and r.stdout.strip() == "running"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ensure_frontend_dist(*, rebuild: bool = False) -> bool:
    """Ensure ``Code/frontend/dist`` exists; optionally run ``npm run build``."""
    index = frontend_dist_index()
    if index.is_file() and not rebuild:
        log.ok("Gateway", f"前端静态资源已就绪: {index}")
        return True

    log.info("Gateway", "构建前端 dist（npm run build）...")
    npm = shutil.which("npm")
    if not npm:
        log.error(
            "Gateway",
            "未找到 npm。请先安装 Node.js，或手动执行: cd Code/frontend && npm run build",
        )
        return False

    try:
        r = subprocess.run(
            [npm, "run", "build"],
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            # npm/vite 输出恒为 UTF-8；Windows 默认 GBK 解码会崩 reader 线程，
            # 吞掉构建输出（真失败时也看不到错误）。2026-08-23 修复。
            encoding="utf-8",
            errors="replace",
            timeout=600,
            **hidden_kwargs(),
        )
    except subprocess.TimeoutExpired:
        log.error("Gateway", "npm run build 超时（600s）")
        return False

    if r.returncode != 0:
        log.error("Gateway", f"npm run build 失败:\n{r.stderr or r.stdout}")
        return False

    if not index.is_file():
        log.error("Gateway", f"构建完成但未找到 {index}")
        return False

    log.ok("Gateway", "前端 dist 构建完成")
    return True


def stop_vite_on_gateway_port() -> None:
    """释放 5175：停止可能占用端口的 Vite 开发服务器。"""
    log.info("Gateway", "停止可能占用 :5175 的 Vite 开发服务器...")
    terminate_by_cmdline_patterns(
        [
            str(FRONTEND_DIR),
            f"vite --port {GATEWAY_PORT}",
        ]
    )
    time.sleep(1)


def start_gateway_infra(*, rebuild_frontend: bool = False) -> bool:
    """Start Nginx gateway compose project."""
    log.banner("启动 Nginx Gateway（同域入口 :5175）")
    if not docker_available():
        hint = (
            "请先以管理员身份启动 Docker Desktop"
            if IS_WINDOWS
            else "请先启动 Docker Engine"
        )
        log.error("Gateway", f"Docker 未运行或未安装，{hint}")
        return False

    compose = gateway_compose_file()
    if not compose.is_file():
        log.error("Gateway", f"缺少 compose: {compose}")
        return False

    if not ensure_frontend_dist(rebuild=rebuild_frontend):
        return False

    stop_vite_on_gateway_port()

    log.info("Gateway", "docker compose -p gateway up -d ...")
    try:
        r = subprocess.run(
            ["docker", "compose", "-p", GATEWAY_PROJECT, "up", "-d"],
            cwd=str(GATEWAY_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            **hidden_kwargs(),
        )
        if r.returncode != 0:
            log.error("Gateway", f"启动失败:\n{r.stderr or r.stdout}")
            if IS_WINDOWS:
                log.info(
                    "Gateway",
                    "提示: Windows 请确认 Docker Desktop 以管理员身份运行",
                )
            return False
    except subprocess.TimeoutExpired:
        log.error("Gateway", "docker compose 启动超时（120s）")
        return False

    # 短暂等待健康
    for _ in range(15):
        if gateway_running():
            break
        time.sleep(1)

    if not gateway_running():
        log.warn("Gateway", "容器已提交但尚未显示 running，请稍后 launch.py status")
    else:
        log.ok("Gateway", f"Nginx 已启动: http://localhost:{GATEWAY_PORT}")
        log.info("Gateway", "  静态: Code/frontend/dist")
        log.info("Gateway", "  反代: host.docker.internal:8000 → FastAPI")
        log.info("Gateway", "  与 Vite 开发互斥（同端口）；本地 HMR 请用 launch.py start --vite")
    return True


def stop_gateway_infra() -> None:
    compose = gateway_compose_file()
    if not compose.is_file():
        return
    log.info("Gateway", "停止 gateway 容器（Nginx）...")
    try:
        subprocess.run(
            ["docker", "compose", "-p", GATEWAY_PROJECT, "down"],
            cwd=str(GATEWAY_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            **hidden_kwargs(),
        )
        log.ok("Gateway", "gateway 容器已停止")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.warn("Gateway", "gateway 容器停止超时或 Docker 不可用")
