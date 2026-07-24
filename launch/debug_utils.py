"""Debug diagnostics and log file utilities for the CGDA launcher.

Extracted from the original ``launch.py``. Provides:

- :func:`print_debug_info`: prints Python / platform / Docker / Redis /
  disk / PID-file diagnostics (used by ``--debug`` flag).
- :func:`get_log_files`: maps a component name to ``[(label, path), ...]``
  (used by ``logs`` command).
- :func:`parse_log_timestamp`: extracts timestamps from log lines for
  merged-log sorting.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from launch.constants import (
    BACKEND_DIR,
    CELERY_WORKERS,
    DATA_SYNC_DIR,
    FRONTEND_DIR,
    LAUNCHER_LOG,
    LOG_DIR,
    PID_FILE,
)
from launch.docker_manager import docker_available, redis_running
from launch.logging_setup import log
from launch.subprocess_utils import hidden_kwargs

# 日志行时间戳提取
_TS_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def parse_log_timestamp(line: str) -> datetime | None:
    """尝试从日志行开头提取时间戳。"""
    m = _TS_PATTERN.search(line[:60])
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def get_log_files(component: str | None) -> list[tuple[str, Path]]:
    """根据组件名返回 [(label, path), ...]。"""
    if component is None or component == "all":
        files = [
            ("launcher", LAUNCHER_LOG),
            ("fastapi", LOG_DIR / "fastapi.log"),
            ("beat", LOG_DIR / "beat.log"),
            ("frontend", LOG_DIR / "frontend.log"),
        ]
        for w in CELERY_WORKERS:
            files.append((f"worker-{w['name']}", LOG_DIR / f"worker-{w['name']}.log"))
        return files
    if component == "fastapi":
        return [("fastapi", LOG_DIR / "fastapi.log")]
    if component == "beat":
        return [("beat", LOG_DIR / "beat.log")]
    if component == "frontend":
        return [("frontend", LOG_DIR / "frontend.log")]
    if component in ("worker", "worker:all"):
        return [
            (f"worker-{w['name']}", LOG_DIR / f"worker-{w['name']}.log")
            for w in CELERY_WORKERS
        ]
    if component.startswith("worker:"):
        name = component.split(":", 1)[1]
        return [(f"worker-{name}", LOG_DIR / f"worker-{name}.log")]
    return []


def print_debug_info() -> None:
    """打印调试诊断信息。"""
    log.banner("调试诊断信息")
    log.info("Debug", f"Python:   {sys.version.splitlines()[0]}")
    log.info("Debug", f"Platform: {platform.platform()}")
    log.info("Debug", f"Executable: {sys.executable}")
    log.info("Debug", f"Backend dir:  {BACKEND_DIR}")
    log.info("Debug", f"Frontend dir: {FRONTEND_DIR}")
    log.info("Debug", f"Data-sync:    {DATA_SYNC_DIR}")
    log.info("Debug", f"Log dir:      {LOG_DIR}")

    # Docker
    if docker_available():
        log.ok("Debug", "Docker: 可用")
        try:
            r = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
                **hidden_kwargs(),
            )
            if r.returncode == 0:
                log.info("Debug", f"Docker Server 版本: {r.stdout.strip()}")
        except Exception:
            pass
    else:
        log.warn("Debug", "Docker: 不可用")

    # Redis
    if redis_running():
        log.ok("Debug", "Redis: 运行中")
    else:
        log.warn("Debug", "Redis: 未检测到")

    # 磁盘空间
    try:
        total, used, free = shutil.disk_usage(BACKEND_DIR)
        log.info(
            "Debug",
            f"磁盘: 总 {total // 1024 // 1024}MB, 已用 {used // 1024 // 1024}MB, 可用 {free // 1024 // 1024}MB",
        )
    except Exception:
        pass

    # PID 文件
    if PID_FILE.exists():
        import json

        try:
            pids = json.loads(PID_FILE.read_text(encoding="utf-8"))
            log.info(
                "Debug", f"PID 文件存在，记录 {len(pids)} 个进程: {list(pids.keys())}"
            )
        except Exception:
            log.warn("Debug", "PID 文件解析失败")
    else:
        log.info("Debug", "无 PID 文件")

    log.banner("调试信息结束")
