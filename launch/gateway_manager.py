"""Nginx gateway (demo / public same-origin entry on :5175).

Separate compose project ``gateway`` so it does not mix with backend /
data-sync stacks.

Profiles:
- **static** (default): serve ``Code/frontend/dist``
- **hmr** (``--vite``): proxy SPA/HMR to host Vite on
  :attr:`launch.constants.VITE_BEHIND_GATEWAY_PORT` while keeping API
  reverse-proxy on the same public port.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from launch.constants import (
    FRONTEND_DIR,
    GATEWAY_DIR,
    IS_WINDOWS,
    VITE_BEHIND_GATEWAY_PORT,
)
from launch.logging_setup import log
from launch.subprocess_utils import hidden_kwargs, terminate_by_cmdline_patterns

from launch.docker_manager import docker_available

GATEWAY_CONTAINER = "cgda-gateway-nginx"
GATEWAY_PROJECT = "gateway"
GATEWAY_PORT = 5175


def gateway_compose_file() -> Path:
    return GATEWAY_DIR / "docker-compose.yml"


def gateway_hmr_compose_file() -> Path:
    return GATEWAY_DIR / "docker-compose.hmr.yml"


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


def gateway_hmr_active() -> bool:
    """True when the running gateway container mounts nginx.hmr.conf."""
    if not gateway_running():
        return False
    try:
        r = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{range .Mounts}}{{.Source}} {{end}}",
                GATEWAY_CONTAINER,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            **hidden_kwargs(),
        )
        if r.returncode != 0:
            return False
        return "nginx.hmr.conf" in (r.stdout or "").replace("\\", "/")
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
    """释放 5175：停止可能占用公开口的 Vite（旧互斥剖面残留）。"""
    log.info("Gateway", "停止可能占用 :5175 的 Vite 开发服务器...")
    terminate_by_cmdline_patterns(
        [
            str(FRONTEND_DIR),
            f"vite --port {GATEWAY_PORT}",
        ]
    )
    time.sleep(1)


def stop_vite_behind_gateway() -> None:
    """停止 Gateway HMR 剖面背后的 Vite（:5174）。"""
    terminate_by_cmdline_patterns(
        [
            str(FRONTEND_DIR),
            f"vite --port {VITE_BEHIND_GATEWAY_PORT}",
        ]
    )


def _compose_up(*, hmr: bool) -> bool:
    compose = gateway_compose_file()
    cmd = ["docker", "compose", "-p", GATEWAY_PROJECT, "-f", str(compose.name)]
    if hmr:
        hmr_file = gateway_hmr_compose_file()
        if not hmr_file.is_file():
            log.error("Gateway", f"缺少 HMR compose: {hmr_file}")
            return False
        cmd.extend(["-f", str(hmr_file.name)])
    cmd.extend(["up", "-d", "--force-recreate"])
    profile = "HMR（反代 Vite）" if hmr else "静态 dist"
    log.info("Gateway", f"docker compose up -d [{profile}] ...")
    try:
        r = subprocess.run(
            cmd,
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
    return True


def reload_gateway_nginx() -> bool:
    """Graceful reload of nginx config inside the gateway container."""
    if not gateway_running():
        log.error(
            "Gateway",
            f"容器 {GATEWAY_CONTAINER} 未运行；请先 launch.py start gateway",
        )
        return False
    log.info("Gateway", "nginx -t && nginx -s reload ...")
    try:
        test = subprocess.run(
            ["docker", "exec", GATEWAY_CONTAINER, "nginx", "-t"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            **hidden_kwargs(),
        )
        # nginx -t writes to stderr even on success
        out = (test.stderr or "") + (test.stdout or "")
        if test.returncode != 0:
            log.error("Gateway", f"nginx -t 失败:\n{out}")
            return False
        rel = subprocess.run(
            ["docker", "exec", GATEWAY_CONTAINER, "nginx", "-s", "reload"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            **hidden_kwargs(),
        )
        if rel.returncode != 0:
            log.error(
                "Gateway",
                f"nginx -s reload 失败:\n{(rel.stderr or '') + (rel.stdout or '')}",
            )
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.error("Gateway", f"reload 失败: {exc}")
        return False
    mode = "HMR" if gateway_hmr_active() else "静态"
    log.ok("Gateway", f"Nginx 配置已热重载（剖面: {mode}）")
    return True


def start_gateway_infra(*, rebuild_frontend: bool = False, hmr: bool = False) -> bool:
    """Start Nginx gateway compose project (static or HMR profile)."""
    title = "启动 Nginx Gateway + Vite HMR" if hmr else "启动 Nginx Gateway（同域入口 :5175）"
    log.banner(title)
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

    if hmr:
        # HMR 剖面不依赖 dist，但仍可选用 rebuild 刷新静态回退产物
        if rebuild_frontend and not ensure_frontend_dist(rebuild=True):
            return False
    else:
        if not ensure_frontend_dist(rebuild=rebuild_frontend):
            return False

    # 公开口必须留给 Gateway；旧「Vite 独占 5175」残留要清掉
    stop_vite_on_gateway_port()
    if not hmr:
        stop_vite_behind_gateway()

    if not _compose_up(hmr=hmr):
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
        if hmr:
            log.info(
                "Gateway",
                f"  HMR: 反代 host Vite :{VITE_BEHIND_GATEWAY_PORT}（请确保 Vite 已启动）",
            )
            log.info("Gateway", "  反代 API: host.docker.internal:8000 → FastAPI")
        else:
            log.info("Gateway", "  静态: Code/frontend/dist")
            log.info("Gateway", "  反代: host.docker.internal:8000 → FastAPI")
            log.info(
                "Gateway",
                "  本地前端 HMR: launch.py start --vite（Gateway 同域 + Vite :%s）"
                % VITE_BEHIND_GATEWAY_PORT,
            )
    return True


def stop_gateway_infra() -> None:
    compose = gateway_compose_file()
    if not compose.is_file():
        return
    log.info("Gateway", "停止 gateway 容器（Nginx）...")
    try:
        # Explicit base + hmr files so compose tears down either profile
        cmd = [
            "docker",
            "compose",
            "-p",
            GATEWAY_PROJECT,
            "-f",
            str(gateway_compose_file().name),
        ]
        hmr_file = gateway_hmr_compose_file()
        if hmr_file.is_file():
            cmd.extend(["-f", str(hmr_file.name)])
        cmd.append("down")
        subprocess.run(
            cmd,
            cwd=str(GATEWAY_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            **hidden_kwargs(),
        )
        log.ok("Gateway", "gateway 容器已停止")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.warn("Gateway", "gateway 容器停止超时或 Docker 不可用")
