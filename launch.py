#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CGDA 跨平台一键启动器
=====================
支持 Windows / Linux，优先使用 Docker 启动基础设施（Redis + MinIO + Open-Meteo API；
数据同步在 Code/infra/data-sync），
后端服务（FastAPI + Celery Workers + Beat）以子进程方式运行。

用法:
    python launch.py                     # 等同 start（无参数默认）
    python launch.py start [component] [options]
    python launch.py stop
    python launch.py status
    python launch.py restart [component] [options]
    python launch.py logs [component] [-n N]
    python launch.py flush
    python launch.py sync [job]          # 数据面一次性同步（默认 open-meteo-sync）

组件 (component):
    (无) 或 all        启动全部服务并进入监控循环（默认）
    docker              仅启动 Docker 运行栈（Redis + MinIO + cgda-open-meteo）
    fastapi             仅启动 FastAPI 后端（需要 Redis 已运行）
    beat                仅启动 Celery Beat 调度器
    worker              仅启动全部 7 个 Celery Worker
    worker:all          同上
    worker:realtime     仅启动 realtime 队列 Worker
    worker:standard     仅启动 standard 队列 Worker
    worker:heavy        仅启动 heavy 队列 Worker
    worker:batch        仅启动 batch 队列 Worker
    worker:download     仅启动 download 队列 Worker
    worker:gee          仅启动 gee 队列 Worker
    worker:weather      仅启动 weather 队列 Worker
    frontend            仅启动前端 Vite 开发服务器

选项 (仅 start / restart):
    --no-frontend       不启动前端开发服务器（仅 start all）
    --no-docker         不启动 Docker 容器（使用外部 Redis/MinIO）
    --no-open-meteo     不启动 cgda-open-meteo API（仍可启 Redis/MinIO）
    --frontend-only     仅启动前端（等同 start frontend，向后兼容）
    --debug             调试模式：不隐藏窗口，Celery 日志级别 DEBUG，打印诊断信息
    --frontend-port N   前端端口（默认 5175）

选项 (仅 logs):
    -n N                显示最后 N 行（默认 50）

示例:
    python launch.py start                      # 启动全部，进入监控循环
    python launch.py start docker               # 仅 Redis + MinIO + Open-Meteo API
    python launch.py sync                       # 跑 data-sync open-meteo-sync
    python launch.py start worker:weather       # 仅启动 weather Worker
    python launch.py start fastapi --debug      # 调试模式启动 FastAPI
    python launch.py start --frontend-port 3000 # 全部启动，前端用 3000 端口
    python launch.py logs fastapi -n 100        # 查看 FastAPI 最后 100 行日志
    python launch.py logs worker:all            # 查看所有 Worker 日志
    python launch.py flush                      # 清空 Redis + 文件缓存
    python launch.py stop                       # 停止全部服务
    python launch.py status                     # 查看服务状态

Windows: start.bat / stop.bat    Linux/macOS: ./start.sh / ./stop.sh
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

# ─── Windows 控制台 UTF-8 输出 ───────────────────────────────────────────────
if sys.platform == "win32" or sys.platform == "win":
    # 尝试配置控制台编码为 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# ─── 路径常量 ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR / "Code" / "backend"
FRONTEND_DIR = SCRIPT_DIR / "Code" / "frontend"
DATA_SYNC_DIR = SCRIPT_DIR / "Code" / "infra" / "data-sync"
LOG_DIR = BACKEND_DIR / ".data" / "logs"
DATA_DIRS = [
    BACKEND_DIR / ".data" / "logs",
    BACKEND_DIR / ".data" / "workflow_state",
    BACKEND_DIR / ".data" / "artifacts",
    BACKEND_DIR / ".data" / "cache",
]
LAUNCHER_LOG = LOG_DIR / "launcher.log"
PID_FILE = LOG_DIR / "launcher_pids.json"
WEATHER_CACHE_DIR = BACKEND_DIR / ".data" / "cache" / "weather"
WEATHERENGINE_CACHE_DIR = BACKEND_DIR / ".data" / "cache" / "weatherengine"
DEFAULT_FRONTEND_PORT = 5175
DEFAULT_OPEN_METEO_VOLUME = "backend_open-meteo-data"
IS_WINDOWS = sys.platform == "win32"

# ─── 服务定义 ────────────────────────────────────────────────────────────────
# 7 个 Celery Worker 队列
CELERY_WORKERS: list[dict[str, str]] = [
    {"name": "realtime", "queues": "realtime"},
    {"name": "standard", "queues": "standard"},
    {"name": "heavy", "queues": "heavy"},
    {"name": "batch", "queues": "batch"},
    {"name": "download", "queues": "download-realtime,download-standard"},
    {"name": "gee", "queues": "gee-realtime,gee-standard,gee-heavy,gee-batch"},
    {"name": "weather", "queues": "weather-realtime,weather-standard,weather-heavy,weather-batch"},
]
VALID_WORKER_NAMES = [w["name"] for w in CELERY_WORKERS]

# ─── 日志系统 ────────────────────────────────────────────────────────────────
# 单文件上限 5 MB，保留 3 个备份，避免 launcher.log 长期运行无限增长
_LAUNCHER_LOG_MAX_BYTES = 5 * 1024 * 1024
_LAUNCHER_LOG_BACKUP_COUNT = 3

# 子进程 stdout 重定向的日志文件：超过此大小则在启动时轮转
# Windows 下 fd 固定无法运行中轮转，只能在启动时检查
_SUBPROCESS_LOG_ROTATE_THRESHOLD = 50 * 1024 * 1024  # 50 MB


class Log:
    """规范的彩色日志输出器，同时写入控制台和文件（带轮转）。"""

    _COLORS = {
        "DEBUG": "\033[90m",      # 灰
        "INFO": "\033[36m",       # 青
        "OK": "\033[32m",         # 绿
        "WARN": "\033[33m",       # 黄
        "ERROR": "\033[31m",      # 红
        "RESET": "\033[0m",
    }
    _BOLD = "\033[1m"

    def __init__(self, log_file: Path):
        self._log_file = log_file
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        # 使用 RotatingFileHandler 替代裸 open，避免长期运行文件无限增长
        self._file_handler = RotatingFileHandler(
            log_file,
            maxBytes=_LAUNCHER_LOG_MAX_BYTES,
            backupCount=_LAUNCHER_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        self._file_handler.setLevel(logging.DEBUG)
        # 使用内部 logging.Logger 简化日志记录，避免手动构造 LogRecord
        # 关闭 logging 模块在 emit 失败时打印调用栈到 stderr 的行为
        # （Windows 下文件被其他进程占用时轮转会失败，调用栈会污染控制台）
        logging.raiseExceptions = False
        self._logger = logging.getLogger("launcher")
        self._logger.setLevel(logging.DEBUG)
        # 避免重复添加 handler（多次实例化时）
        for h in self._logger.handlers:
            if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(log_file):
                self._logger.removeHandler(h)
        self._logger.addHandler(self._file_handler)
        self._logger.propagate = False  # 不冒泡到 root logger
        self._is_tty = sys.stdout.isatty()
        # Windows 启用 ANSI 颜色
        if sys.platform == "win32" and self._is_tty:
            os.system("")  # 激活 VT100

    def _write(self, level: str, category: str, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cat_padded = category.ljust(10)
        line = f"[{ts}] [{level:5s}] [{cat_padded}] {message}"
        # 写文件（无颜色，RotatingFileHandler 自动轮转）
        log_level = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "OK": logging.INFO,
            "WARN": logging.WARNING,
            "ERROR": logging.ERROR,
        }.get(level, logging.INFO)
        self._logger.log(log_level, line)
        # 写控制台（带颜色）
        if self._is_tty:
            color = self._COLORS.get(level, "")
            bold = self._BOLD if level in ("ERROR", "OK") else ""
            print(f"{bold}{color}{line}{self._COLORS['RESET']}")
        else:
            print(line)

    def info(self, category: str, msg: str) -> None:
        self._write("INFO", category, msg)

    def ok(self, category: str, msg: str) -> None:
        self._write("OK", category, msg)

    def warn(self, category: str, msg: str) -> None:
        self._write("WARN", category, msg)

    def error(self, category: str, msg: str) -> None:
        self._write("ERROR", category, msg)

    def debug(self, category: str, msg: str) -> None:
        self._write("DEBUG", category, msg)

    def banner(self, title: str) -> None:
        line = "═" * 60
        self.info("Launcher", line)
        self.info("Launcher", f"  {title}")
        self.info("Launcher", line)

    def close(self) -> None:
        self._file_handler.close()


log = Log(LAUNCHER_LOG)


def _rotate_subprocess_log_if_needed(log_file: Path) -> None:
    """启动前检查子进程日志文件大小，超过阈值则轮转。

    Windows 下 subprocess.Popen 的 stdout 文件描述符固定，无法在运行中轮转。
    此函数在每次启动子进程前调用，若上次日志超过 50 MB 则重命名为 .old，
    让子进程从空文件开始写。.old 文件保留供查阅，下次轮转时被覆盖。
    """
    try:
        if not log_file.exists():
            return
        size = log_file.stat().st_size
        if size < _SUBPROCESS_LOG_ROTATE_THRESHOLD:
            return
        old_file = log_file.with_suffix(log_file.suffix + ".old")
        # 如果已有 .old 文件，先删除（保留最新一轮）
        if old_file.exists():
            old_file.unlink()
        log_file.rename(old_file)
        log.info("Log", f"轮转 {log_file.name} ({size // 1024 // 1024} MB → {old_file.name})")
    except OSError as exc:
        log.warn("Log", f"轮转 {log_file.name} 失败: {exc}")


# ─── 跨平台子进程工具 ────────────────────────────────────────────────────────
def _hidden_kwargs() -> dict[str, Any]:
    """返回在 Windows 上隐藏控制台窗口的 subprocess 参数。"""
    kwargs: dict[str, Any] = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _python_executable() -> str:
    """返回当前 Python 解释器路径，确保子进程使用同一环境。"""
    return sys.executable


def _child_env() -> dict[str, str]:
    """子进程环境：UTF-8 + PYTHONPATH（backend / Code）。"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    code_root = str(BACKEND_DIR.parent)
    paths = [str(BACKEND_DIR), code_root]
    prev = env.get("PYTHONPATH", "").strip()
    if prev:
        paths.append(prev)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _resolve_open_meteo_volume_name() -> str:
    """从 data-sync/.env 读取 volume 名，缺省 backend_open-meteo-data。"""
    env_file = DATA_SYNC_DIR / ".env"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                key, _, val = s.partition("=")
                if key.strip() == "OPEN_METEO_DATA_VOLUME":
                    name = val.strip().strip('"').strip("'")
                    if name:
                        return name
        except OSError:
            pass
    return DEFAULT_OPEN_METEO_VOLUME


def ensure_named_volume(name: str) -> bool:
    """确保 Docker named volume 存在（不落项目目录）。"""
    try:
        r = subprocess.run(
            ["docker", "volume", "inspect", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            **_hidden_kwargs(),
        )
        if r.returncode == 0:
            return True
        log.info("Docker", f"创建 named volume: {name}")
        c = subprocess.run(
            ["docker", "volume", "create", name],
            capture_output=True,
            text=True,
            timeout=30,
            **_hidden_kwargs(),
        )
        return c.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warn("Docker", f"volume 检查失败: {exc}")
        return False


def ensure_project_initialized() -> None:
    """跨平台初始化：数据目录、data-sync .env、前端依赖提示。"""
    for d in DATA_DIRS:
        d.mkdir(parents=True, exist_ok=True)

    if DATA_SYNC_DIR.is_dir():
        ds_env = DATA_SYNC_DIR / ".env"
        ds_ex = DATA_SYNC_DIR / ".env.example"
        if not ds_env.is_file() and ds_ex.is_file():
            shutil.copyfile(ds_ex, ds_env)
            log.info("Init", f"已生成 data-sync .env ← .env.example")

    if not (FRONTEND_DIR / "node_modules").is_dir():
        pkg = "pnpm install" if (FRONTEND_DIR / "pnpm-lock.yaml").is_file() else "npm install"
        log.warn("Init", f"前端 node_modules 缺失，请先在 Code/frontend 执行: {pkg}")


def _frontend_dev_command(port: int) -> list[str] | None:
    """解析前端启动命令。

    优先直接跑 node_modules/vite（避开 pnpm exec 的 deps-status / approve-builds 失败），
    其次 npx，最后 pnpm。
    """
    port_s = str(port)
    vite_js = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    node_candidates = ("node.exe", "node") if IS_WINDOWS else ("node",)
    if vite_js.is_file():
        for cand in node_candidates:
            node = shutil.which(cand)
            if node:
                return [node, str(vite_js), "--port", port_s, "--host"]
    npx_candidates = ("npx.cmd", "npx.exe", "npx") if IS_WINDOWS else ("npx",)
    for cand in npx_candidates:
        if shutil.which(cand):
            return [cand, "vite", "--port", port_s, "--host"]
    pnpm_candidates = ("pnpm.cmd", "pnpm.exe", "pnpm") if IS_WINDOWS else ("pnpm",)
    for cand in pnpm_candidates:
        if shutil.which(cand):
            return [cand, "exec", "vite", "--port", port_s, "--host"]
    return None


def _terminate_by_cmdline_patterns(patterns: list[str]) -> None:
    """按命令行子串终止进程（Windows: CIM/WMI/taskkill 回退；Linux: pkill -f）。"""
    if not patterns:
        return
    if IS_WINDOWS:
        # 一次拉取进程列表，避免依赖本机是否装齐 CimCmdlets
        ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$rows = @()
try {
  $rows = @(Get-CimInstance Win32_Process | Select-Object ProcessId, CommandLine)
} catch {
  try { $rows = @(Get-WmiObject Win32_Process | Select-Object ProcessId, CommandLine) } catch { $rows = @() }
}
$rows | ForEach-Object {
  if ($_.CommandLine) {
    '{0}|{1}' -f $_.ProcessId, ($_.CommandLine -replace '[\r\n]+',' ')
  }
}
"""
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=30,
                **_hidden_kwargs(),
            )
            lines = (r.stdout or "").splitlines()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            lines = []

        my_pid = os.getpid()
        for line in lines:
            if "|" not in line:
                continue
            pid_s, _, cmdline = line.partition("|")
            try:
                pid = int(pid_s.strip())
            except ValueError:
                continue
            if pid == my_pid:
                continue
            if any(pat in cmdline for pat in patterns):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **_hidden_kwargs(),
                )
        return

    for pat in patterns:
        subprocess.run(
            ["pkill", "-f", pat],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


# ─── Docker 管理 ─────────────────────────────────────────────────────────────
def docker_available() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            **_hidden_kwargs(),
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def start_docker_infra(*, start_open_meteo: bool = True) -> bool:
    """启动 Redis + MinIO；可选启动 backend 内的 cgda-open-meteo API。"""
    log.banner("启动 Docker 运行栈 (Redis + MinIO + Open-Meteo API)")
    if not docker_available():
        hint = "请先启动 Docker Desktop" if IS_WINDOWS else "请先启动 Docker Engine / 守护进程"
        log.error("Docker", f"Docker 未运行或未安装，{hint}")
        return False

    if start_open_meteo:
        ensure_named_volume(_resolve_open_meteo_volume_name())

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
            **_hidden_kwargs(),
        )
        if r.returncode != 0:
            log.error("Docker", f"docker compose 启动失败:\n{r.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log.error("Docker", "docker compose 启动超时（180s）")
        return False

    log.ok("Docker", "容器已启动")
    log.info("Docker", "  Redis:  redis://127.0.0.1:6379/0")
    log.info("Docker", "  MinIO:  API http://127.0.0.1:9100 | Console http://127.0.0.1:9101")
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
            **_hidden_kwargs(),
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
                **_hidden_kwargs(),
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
            **_hidden_kwargs(),
        )
        return r.returncode == 0 and "PONG" in r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ─── 进程管理 ────────────────────────────────────────────────────────────────
class ProcessManager:
    """管理所有子进程的生命周期。"""

    def __init__(self, debug: bool = False, frontend_port: int = DEFAULT_FRONTEND_PORT):
        self.processes: dict[str, subprocess.Popen] = {}
        self._shutting_down = False
        self.debug = debug
        self.frontend_port = frontend_port

    @property
    def _loglevel(self) -> str:
        """Celery 日志级别，debug 模式下为 DEBUG。"""
        return "DEBUG" if self.debug else "INFO"

    def _proc_kwargs(self) -> dict[str, Any]:
        """返回子进程参数；debug 模式下不隐藏窗口。"""
        if self.debug:
            return {}
        return _hidden_kwargs()

    def start_celery_workers(self, worker_names: list[str] | None = None) -> None:
        """启动 Celery Worker。worker_names 为 None 时启动全部 7 个。"""
        if worker_names is None:
            workers_to_start = CELERY_WORKERS
            log.banner(f"启动 Celery Workers ({len(workers_to_start)} 个队列)")
        else:
            workers_to_start = [w for w in CELERY_WORKERS if w["name"] in worker_names]
            log.banner(f"启动 Celery Workers ({len(workers_to_start)} 个)")

        py = _python_executable()
        worker_script = str(BACKEND_DIR / "start_celery_worker.py")
        hostname = platform.node()
        child_env = _child_env()

        for w in workers_to_start:
            name = w["name"]
            queues = w["queues"]
            log_file = LOG_DIR / f"worker-{name}.log"
            log.info("Worker", f"启动 worker-{name} (queues={queues})")

            # 启动前轮转：若上次日志超 50 MB，重命名为 .old 后从空文件开始
            _rotate_subprocess_log_if_needed(log_file)
            # 清空旧日志（仅当未被轮转时）
            if not log_file.exists():
                log_file.write_text("", encoding="utf-8")

            proc = subprocess.Popen(
                [
                    py, worker_script, "worker",
                    f"--loglevel={self._loglevel}",
                    f"--queues={queues}",
                    f"--hostname=worker-{name}@{hostname}",
                    "-f", str(log_file),
                ],
                cwd=str(BACKEND_DIR),
                env=child_env,
                stdout=open(log_file, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                **self._proc_kwargs(),
            )
            self.processes[f"worker-{name}"] = proc

        log.ok("Worker", f"{len(workers_to_start)} 个 Worker 已启动，日志: .data/logs/worker-*.log")

    def start_celery_beat(self) -> None:
        """启动 Celery Beat 定时调度器。"""
        log.info("Beat", "启动 Celery Beat 调度器...")
        py = _python_executable()
        beat_script = str(BACKEND_DIR / "start_celery_beat.py")
        log_file = LOG_DIR / "beat.log"
        _rotate_subprocess_log_if_needed(log_file)
        if not log_file.exists():
            log_file.write_text("", encoding="utf-8")

        proc = subprocess.Popen(
            [
                py, beat_script,
                f"--loglevel={self._loglevel}",
                "-f", str(log_file),
            ],
            cwd=str(BACKEND_DIR),
            env=_child_env(),
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            **self._proc_kwargs(),
        )
        self.processes["beat"] = proc
        log.ok("Beat", "Celery Beat 已启动")

    def start_fastapi(self) -> None:
        """启动 FastAPI 后端服务。"""
        log.info("FastAPI", "启动 FastAPI 后端服务...")
        py = _python_executable()
        fastapi_script = str(BACKEND_DIR / "start_fastapi.py")
        log_file = LOG_DIR / "fastapi.log"
        _rotate_subprocess_log_if_needed(log_file)
        if not log_file.exists():
            log_file.write_text("", encoding="utf-8")

        proc = subprocess.Popen(
            [py, fastapi_script],
            cwd=str(BACKEND_DIR),
            env=_child_env(),
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            **self._proc_kwargs(),
        )
        self.processes["fastapi"] = proc
        log.ok("FastAPI", "FastAPI 已启动")
        log.info("FastAPI", "  API:  http://127.0.0.1:8000")
        log.info("FastAPI", "  Docs: http://127.0.0.1:8000/docs")
        log.info("FastAPI", f"  日志: {log_file}")

    def start_frontend(self) -> None:
        """启动前端 Vite 开发服务器。"""
        log.info("Frontend", f"启动前端 Vite 开发服务器 (port={self.frontend_port})...")
        cmd = _frontend_dev_command(self.frontend_port)
        if not cmd:
            log.error("Frontend", "未找到 pnpm/npx，请安装 Node.js 并确保在 PATH 中")
            return
        log_file = LOG_DIR / "frontend.log"
        _rotate_subprocess_log_if_needed(log_file)
        if not log_file.exists():
            log_file.write_text("", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(FRONTEND_DIR),
                env=_child_env(),
                stdout=open(log_file, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                **self._proc_kwargs(),
            )
            self.processes["frontend"] = proc
            log.ok("Frontend", f"Vite 已启动（{cmd[0]}）")
            log.info("Frontend", f"  URL:  http://localhost:{self.frontend_port}")
            log.info("Frontend", f"  日志: {log_file}")
        except FileNotFoundError:
            # Windows 上偶发 which 命中不可直接 CreateProcess 的 shim，回退 npx
            fallback = None
            for cand in (("npx.cmd", "npx.exe", "npx") if IS_WINDOWS else ("npx",)):
                if shutil.which(cand):
                    fallback = [cand, "vite", "--port", str(self.frontend_port), "--host"]
                    break
            if not fallback or fallback[0] == cmd[0]:
                log.error("Frontend", f"启动命令不可用: {cmd[0]}")
                return
            log.warn("Frontend", f"{cmd[0]} 不可执行，回退 {fallback[0]}")
            try:
                proc = subprocess.Popen(
                    fallback,
                    cwd=str(FRONTEND_DIR),
                    env=_child_env(),
                    stdout=open(log_file, "a", encoding="utf-8"),
                    stderr=subprocess.STDOUT,
                    **self._proc_kwargs(),
                )
                self.processes["frontend"] = proc
                log.ok("Frontend", f"Vite 已启动（{fallback[0]}）")
                log.info("Frontend", f"  URL:  http://localhost:{self.frontend_port}")
            except FileNotFoundError:
                log.error("Frontend", f"回退命令也不可用: {fallback[0]}")

    def wait_for_fastapi(self, max_wait: int = 30) -> bool:
        """等待 FastAPI 就绪。"""
        log.info("FastAPI", f"等待 HTTP 就绪（最多 {max_wait}s）...")
        import urllib.request
        for i in range(max_wait):
            try:
                req = urllib.request.Request("http://127.0.0.1:8000/health")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        log.ok("FastAPI", "FastAPI HTTP 就绪")
                        return True
            except Exception:
                pass
            time.sleep(1)
        log.warn("FastAPI", f"FastAPI 未在 {max_wait}s 内就绪")
        return False

    def save_pids(self, merge: bool = False) -> None:
        """保存 PID 信息到文件，供 stop 命令使用。

        merge=True 时与现有 PID 文件合并（用于单组件启动）。
        """
        import json
        pids = {name: proc.pid for name, proc in self.processes.items()}
        if merge and PID_FILE.exists():
            try:
                existing = json.loads(PID_FILE.read_text(encoding="utf-8"))
                existing.update(pids)
                pids = existing
            except (json.JSONDecodeError, OSError):
                pass
        PID_FILE.write_text(json.dumps(pids, indent=2), encoding="utf-8")
        log.debug("Launcher", f"PID 文件已保存: {PID_FILE} ({len(pids)} 个进程)")

    def stop_all(self) -> None:
        """停止所有子进程。"""
        log.banner("停止所有服务")
        for name, proc in reversed(list(self.processes.items())):
            if proc.poll() is not None:
                log.info("Stop", f"{name} 已退出")
                continue
            log.info("Stop", f"停止 {name} (pid={proc.pid})...")
            proc.terminate()
            try:
                proc.wait(timeout=10)
                log.ok("Stop", f"{name} 已停止")
            except subprocess.TimeoutExpired:
                log.warn("Stop", f"{name} 10s 内未退出，强制 kill")
                proc.kill()
                proc.wait(timeout=5)
        self.processes.clear()

    def monitor(self) -> None:
        """监控所有进程，有进程异常退出时报告。"""
        for name, proc in list(self.processes.items()):
            rc = proc.poll()
            if rc is not None:
                if self._shutting_down:
                    continue
                log.error("Monitor", f"{name} 异常退出 (code={rc})")
                # 读取最后几行日志帮助诊断
                log_file = LOG_DIR / f"{name}.log"
                if name.startswith("worker-"):
                    log_file = LOG_DIR / f"worker-{name.replace('worker-', '')}.log"
                if log_file.exists():
                    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    tail = "\n".join(lines[-5:]) if lines else "(空日志)"
                    log.error("Monitor", f"{name} 日志尾部:\n{tail}")

    def install_signal_handlers(self) -> None:
        """安装信号处理器，Ctrl+C 优雅退出。"""
        def handler(signum, frame):
            if self._shutting_down:
                return
            self._shutting_down = True
            log.warn("Signal", f"收到信号 {signum}，正在优雅停止所有服务...")
            self.stop_all()
            log.banner("已停止")
            sys.exit(0)

        signal.signal(signal.SIGINT, handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handler)


# ─── 辅助函数 ────────────────────────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# 日志行时间戳提取
_TS_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _parse_log_timestamp(line: str) -> datetime | None:
    """尝试从日志行开头提取时间戳。"""
    m = _TS_PATTERN.search(line[:60])
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return None


def _get_log_files(component: str | None) -> list[tuple[str, Path]]:
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
        return [(f"worker-{w['name']}", LOG_DIR / f"worker-{w['name']}.log") for w in CELERY_WORKERS]
    if component.startswith("worker:"):
        name = component.split(":", 1)[1]
        return [(f"worker-{name}", LOG_DIR / f"worker-{name}.log")]
    return []


def _print_debug_info() -> None:
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
                capture_output=True, text=True, timeout=5,
                **_hidden_kwargs(),
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
        log.info("Debug", f"磁盘: 总 {total // 1024 // 1024}MB, 已用 {used // 1024 // 1024}MB, 可用 {free // 1024 // 1024}MB")
    except Exception:
        pass

    # PID 文件
    if PID_FILE.exists():
        import json
        try:
            pids = json.loads(PID_FILE.read_text(encoding="utf-8"))
            log.info("Debug", f"PID 文件存在，记录 {len(pids)} 个进程: {list(pids.keys())}")
        except Exception:
            log.warn("Debug", "PID 文件解析失败")
    else:
        log.info("Debug", "无 PID 文件")

    log.banner("调试信息结束")


# ─── 停止命令 ────────────────────────────────────────────────────────────────
def cmd_stop() -> int:
    """停止所有 CGDA 服务。"""
    log.banner("停止 CGDA 服务")

    # 1. 从 PID 文件读取进程
    import json
    if PID_FILE.exists():
        try:
            pids = json.loads(PID_FILE.read_text(encoding="utf-8"))
            for name, pid in pids.items():
                try:
                    os.kill(pid, signal.SIGTERM)
                    log.info("Stop", f"已发送 SIGTERM 到 {name} (pid={pid})")
                except (ProcessLookupError, PermissionError):
                    log.debug("Stop", f"{name} (pid={pid}) 已不存在")
        except (json.JSONDecodeError, OSError):
            pass
        PID_FILE.unlink(missing_ok=True)

    # 2. 兜底：按命令行匹配杀进程（不用已弃用的 wmic）
    _terminate_by_cmdline_patterns(
        [
            "start_celery_worker.py",
            "start_celery_beat.py",
            "start_fastapi.py",
        ]
    )

    # 3. 杀前端 Vite（尽量限定本仓库路径 / 默认端口，避免误杀其它 vite）
    _terminate_by_cmdline_patterns(
        [
            str(FRONTEND_DIR),
            f"vite --port {DEFAULT_FRONTEND_PORT}",
        ]
    )

    time.sleep(1)

    # 4. 停止 Docker 容器
    stop_docker_infra()

    log.ok("Stop", "所有服务已停止")
    return 0


# ─── 状态命令 ────────────────────────────────────────────────────────────────
def cmd_status() -> int:
    """检查所有服务运行状态。"""
    log.banner("CGDA 服务状态")

    # Docker 容器
    log.info("Status", "Docker 容器:")
    containers = [
        ("cgda-redis", "Redis"),
        ("cgda-minio", "MinIO"),
        ("cgda-open-meteo", "Open-Meteo"),
    ]
    for cid, label in containers:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", cid],
            capture_output=True, text=True, **_hidden_kwargs(),
        )
        state = r.stdout.strip() if r.returncode == 0 else "未运行"
        icon = "✓" if state == "running" else "✗"
        log.info("Status", f"  {icon} {label:8s} ({cid}): {state}")

    # FastAPI
    import urllib.request
    try:
        req = urllib.request.Request("http://127.0.0.1:8000/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            ok = resp.status == 200
    except Exception:
        ok = False
    icon = "✓" if ok else "✗"
    log.info("Status", f"  {icon} FastAPI  (http://127.0.0.1:8000): {'就绪' if ok else '未响应'}")

    # 前端
    try:
        req = urllib.request.Request(f"http://localhost:{DEFAULT_FRONTEND_PORT}/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            fe_ok = resp.status == 200
    except Exception:
        fe_ok = False
    icon = "✓" if fe_ok else "✗"
    log.info("Status", f"  {icon} Frontend (http://localhost:{DEFAULT_FRONTEND_PORT}):  {'就绪' if fe_ok else '未响应'}")

    # Celery Workers（从 PID 文件检查）
    import json
    if PID_FILE.exists():
        try:
            pids = json.loads(PID_FILE.read_text(encoding="utf-8"))
            log.info("Status", "子进程 PID:")
            for name, pid in pids.items():
                alive = _pid_alive(pid)
                icon = "✓" if alive else "✗"
                log.info("Status", f"  {icon} {name:20s} pid={pid} {'运行中' if alive else '已退出'}")
        except (json.JSONDecodeError, OSError):
            pass
    else:
        log.info("Status", "无 PID 文件（服务可能未通过 launch.py 启动）")

    # 数据面
    vol = _resolve_open_meteo_volume_name()
    vol_ok = False
    try:
        r = subprocess.run(
            ["docker", "volume", "inspect", vol],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            **_hidden_kwargs(),
        )
        vol_ok = r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    icon = "✓" if vol_ok else "✗"
    log.info("Status", f"  {icon} data-sync volume ({vol}): {'存在' if vol_ok else '缺失'}")
    sync_compose = DATA_SYNC_DIR / "docker-compose.yml"
    icon = "✓" if sync_compose.is_file() else "✗"
    log.info("Status", f"  {icon} data-sync compose: {DATA_SYNC_DIR}")

    return 0


# ─── 启动命令 ────────────────────────────────────────────────────────────────
def cmd_start(args: argparse.Namespace) -> int:
    """启动 CGDA 服务（全部或指定组件）。"""
    component = args.component
    if component is None:
        component = "all"

    # --frontend-only 向后兼容：等同于 start frontend
    if getattr(args, "frontend_only", False) and component == "all":
        component = "frontend"

    # 始终初始化运行时目录 / data-sync .env
    ensure_project_initialized()

    if args.debug:
        _print_debug_info()

    # ── 全部启动 ──
    if component == "all":
        return _start_all(args)

    # ── 单组件启动 ──
    pm = ProcessManager(debug=args.debug, frontend_port=args.frontend_port)
    pm.install_signal_handlers()

    if component == "docker":
        if not start_docker_infra(start_open_meteo=not getattr(args, "no_open_meteo", False)):
            return 1
        wait_for_redis(max_wait=30)
        log.ok("Launcher", "Docker 基础设施已启动（不进入监控循环）")
        return 0

    if component == "fastapi":
        if not redis_running():
            log.warn("FastAPI", "Redis 未检测到，FastAPI 可能无法正常工作（请先 start docker）")
        pm.start_fastapi()
        pm.wait_for_fastapi(max_wait=30)
        pm.save_pids(merge=True)
        log.ok("Launcher", "FastAPI 已启动（不进入监控循环）")
        return 0

    if component == "beat":
        pm.start_celery_beat()
        pm.save_pids(merge=True)
        log.ok("Launcher", "Celery Beat 已启动（不进入监控循环）")
        return 0

    if component == "frontend":
        pm.start_frontend()
        time.sleep(2)
        pm.save_pids(merge=True)
        log.ok("Launcher", "前端已启动（不进入监控循环）")
        return 0

    if component in ("worker", "worker:all"):
        pm.start_celery_workers()
        pm.save_pids(merge=True)
        log.ok("Launcher", "所有 Worker 已启动（不进入监控循环）")
        return 0

    if component.startswith("worker:"):
        name = component.split(":", 1)[1]
        if name not in VALID_WORKER_NAMES:
            log.error("Launcher", f"未知 worker: {name}")
            log.info("Launcher", f"可选 worker: {', '.join(VALID_WORKER_NAMES)}")
            return 1
        pm.start_celery_workers([name])
        pm.save_pids(merge=True)
        log.ok("Launcher", f"worker-{name} 已启动（不进入监控循环）")
        return 0

    log.error("Launcher", f"未知组件: {component}")
    log.info("Launcher", "可用组件: all, docker, fastapi, beat, worker, worker:<name>, frontend")
    return 1


def _start_all(args: argparse.Namespace) -> int:
    """启动全部服务并进入监控循环。"""
    log.banner("CGDA 一键启动")
    log.info("Launcher", f"操作系统: {sys.platform}")
    log.info("Launcher", f"Python:   {sys.executable}")
    log.info("Launcher", f"后端目录: {BACKEND_DIR}")
    log.info("Launcher", f"前端目录: {FRONTEND_DIR}")
    log.info("Launcher", f"数据同步: {DATA_SYNC_DIR}")
    if args.debug:
        log.info("Launcher", "调试模式: ON（窗口可见，Celery 日志级别 DEBUG）")
    log.ok("Launcher", "初始化完成（数据目录 / data-sync .env）")

    pm = ProcessManager(debug=args.debug, frontend_port=args.frontend_port)
    pm.install_signal_handlers()

    # 1. 启动 Docker 基础设施
    if not args.no_docker:
        if not start_docker_infra(start_open_meteo=not getattr(args, "no_open_meteo", False)):
            log.error("Launcher", "Docker 基础设施启动失败，终止")
            return 1
        wait_for_redis(max_wait=30)
        time.sleep(2)  # 额外缓冲确保 Redis 完全就绪
    else:
        log.warn("Launcher", "跳过 Docker（--no-docker），使用外部 Redis/MinIO")

    # 2. 启动 Celery Workers + Beat
    if not args.frontend_only:
        pm.start_celery_workers()
        pm.start_celery_beat()
        time.sleep(2)

        # 3. 启动 FastAPI
        pm.start_fastapi()
        pm.wait_for_fastapi(max_wait=30)

    # 4. 启动前端
    if not args.no_frontend:
        pm.start_frontend()
        time.sleep(3)

    # 5. 保存 PID
    pm.save_pids()

    # 6. 汇总
    log.banner("启动完成")
    log.ok("Launcher", "所有服务已启动:")
    if not args.frontend_only:
        log.info("Launcher", "  FastAPI:   http://127.0.0.1:8000")
        log.info("Launcher", "  API Docs:  http://127.0.0.1:8000/docs")
        log.info("Launcher", "  Workers:   7 个 Celery Worker + 1 Beat")
    if not args.no_frontend:
        log.info("Launcher", f"  Frontend:  http://localhost:{args.frontend_port}")
    log.info("Launcher", f"  日志目录:  {LOG_DIR}")
    log.info("Launcher", "  停止方式:  python launch.py stop  或  Ctrl+C")
    log.info("Launcher", "  查看日志:  python launch.py logs [component]")
    log.info("Launcher", "  数据同步:  python launch.py sync  （Code/infra/data-sync）")
    log.info("Launcher", "")

    # 7. 持续监控（阻塞，直到收到信号）
    try:
        while not pm._shutting_down:
            time.sleep(5)
            pm.monitor()
    except KeyboardInterrupt:
        pass

    pm.stop_all()
    log.banner("已停止")
    return 0


# ─── 重启命令 ────────────────────────────────────────────────────────────────
def cmd_restart(args: argparse.Namespace) -> int:
    """重启 CGDA 服务（全部或指定组件）。"""
    log.banner("重启 CGDA 服务")
    cmd_stop()
    time.sleep(2)
    return cmd_start(args)


# ─── 日志命令 ────────────────────────────────────────────────────────────────
def cmd_logs(args: argparse.Namespace) -> int:
    """查看服务日志。"""
    component = args.component
    n = args.n

    files = _get_log_files(component)
    if not files:
        log.error("Logs", f"未知组件: {component}")
        log.info("Logs", "可用: all, fastapi, beat, frontend, worker, worker:<name>")
        return 1

    # ── 合并所有日志（component 为 None 或 all）──
    if component is None or component == "all":
        log.banner(f"合并日志（最后 {n} 行）")
        entries: list[tuple[datetime, str, str]] = []
        for label, fpath in files:
            if not fpath.exists():
                continue
            try:
                mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
                lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                ts = _parse_log_timestamp(line)
                if ts is None:
                    ts = mtime
                entries.append((ts, label, line))

        entries.sort(key=lambda x: x[0])
        for ts, label, line in entries[-n:]:
            print(f"[{label:15s}] {line}")
        return 0

    # ── 单组件 / 多文件日志 ──
    # 检查文件是否存在
    existing = [(lbl, fp) for lbl, fp in files if fp.exists()]
    if not existing:
        log.error("Logs", f"日志文件不存在: {component}")
        log.info("Logs", f"期望路径: {files[0][1]}")
        return 1

    # Linux: 使用 tail -f 跟踪
    if sys.platform != "win32":
        cmd = ["tail", "-n", str(n), "-f"] + [str(fp) for _, fp in existing]
        log.info("Logs", f"跟踪 {len(existing)} 个文件（Ctrl+C 退出）...")
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass
        return 0

    # Windows: 打印最后 N 行
    for label, fpath in existing:
        print(f"{'=' * 20} {label} {'=' * 20}")
        try:
            lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            print(f"(读取失败: {e})")
            continue
        for line in lines[-n:]:
            print(line)
        print()
    return 0


# ─── 数据同步命令 ────────────────────────────────────────────────────────────
def cmd_sync(job: str = "open-meteo-sync") -> int:
    """跑 data-sync 一次性任务（默认 open-meteo-sync）；不启运行栈。"""
    ensure_project_initialized()
    log.banner(f"数据同步: {job}")
    if not DATA_SYNC_DIR.is_dir():
        log.error("Sync", f"目录不存在: {DATA_SYNC_DIR}")
        return 1
    if not docker_available():
        hint = "请先启动 Docker Desktop" if IS_WINDOWS else "请先启动 Docker Engine"
        log.error("Sync", f"Docker 不可用，{hint}")
        return 1

    vol = _resolve_open_meteo_volume_name()
    if not ensure_named_volume(vol):
        log.error("Sync", f"无法准备 volume: {vol}")
        return 1

    env_file = DATA_SYNC_DIR / ".env"
    domains = "ecmwf_ifs025"
    if env_file.is_file():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("OPEN_METEO_SYNC_DOMAINS="):
                    domains = line.split("=", 1)[1].strip().strip('"').strip("'") or domains
                    break
        except OSError:
            pass

    cmd = ["docker", "compose", "-p", "data-sync"]
    if env_file.is_file():
        cmd.extend(["--env-file", str(env_file)])
    cmd.extend(["--profile", "sync", "run", "--rm", job])
    log.info("Sync", " ".join(cmd))
    try:
        r = subprocess.run(
            cmd,
            cwd=str(DATA_SYNC_DIR),
            timeout=3600,
        )
    except subprocess.TimeoutExpired:
        log.error("Sync", "同步超时（3600s）")
        _record_cli_sync_result(ok=False, domains=domains, message="sync timeout 3600s", exit_code=1)
        return 1
    except FileNotFoundError:
        log.error("Sync", "docker 命令未找到")
        _record_cli_sync_result(ok=False, domains=domains, message="docker not found", exit_code=127)
        return 1

    if r.returncode != 0:
        log.error("Sync", f"同步失败 exit={r.returncode}")
        _record_cli_sync_result(
            ok=False,
            domains=domains,
            message=f"exit code {r.returncode}",
            exit_code=r.returncode,
        )
        return r.returncode
    log.ok("Sync", f"{job} 完成")
    _record_cli_sync_result(ok=True, domains=domains, message=f"{job} completed via launch.py", exit_code=0)
    return 0


def _record_cli_sync_result(
    *,
    ok: bool,
    domains: str,
    message: str,
    exit_code: int | None,
) -> None:
    """Best-effort: persist sync result into backend SQLite so settings overview stays current."""
    try:
        if str(BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(BACKEND_DIR))
        from app.services.weather_engine_settings import record_open_meteo_sync_result

        record_open_meteo_sync_result(
            ok=ok,
            domains=domains,
            message=message,
            exit_code=exit_code,
        )
    except Exception as exc:
        log.warn("Sync", f"未能写入 sync 历史记录: {exc}")


# ─── 清空缓存命令 ────────────────────────────────────────────────────────────
def cmd_flush() -> int:
    """清空 Redis DB + 文件缓存。"""
    log.banner("清空缓存")

    # 1. 清空 Redis DB
    log.info("Flush", "清空 Redis DB (FLUSHDB)...")
    try:
        r = subprocess.run(
            ["docker", "exec", "cgda-redis", "redis-cli", "FLUSHDB"],
            capture_output=True, text=True, timeout=10,
            **_hidden_kwargs(),
        )
        if r.returncode == 0:
            log.ok("Flush", f"Redis DB 已清空 (响应: {r.stdout.strip()})")
        else:
            log.error("Flush", f"Redis 清空失败: {r.stderr.strip()}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.error("Flush", f"Redis 清空异常: {e}")

    # 2. 清空应用侧天气缓存（不删 Open-Meteo Docker volume）
    for cache_dir, label in (
        (WEATHER_CACHE_DIR, "weather"),
        (WEATHERENGINE_CACHE_DIR, "weatherengine"),
    ):
        log.info("Flush", f"清空文件缓存 ({label}): {cache_dir}")
        if cache_dir.exists():
            file_count = sum(1 for f in cache_dir.rglob("*") if f.is_file())
            try:
                shutil.rmtree(cache_dir, ignore_errors=True)
                cache_dir.mkdir(parents=True, exist_ok=True)
                log.ok("Flush", f"{label}: 已清理 {file_count} 个文件")
            except OSError as e:
                log.error("Flush", f"{label} 清理失败: {e}")
        else:
            cache_dir.mkdir(parents=True, exist_ok=True)
            log.info("Flush", f"{label}: 目录已创建")

    log.banner("清空完成")
    log.ok("Flush", "Redis + 应用天气缓存已清空（Open-Meteo named volume 未动）")
    return 0


# ─── 入口 ────────────────────────────────────────────────────────────────────
def main() -> int:
    # 无子命令时默认 start（兼容直接 python launch.py / start.bat）
    if len(sys.argv) == 1:
        sys.argv.append("start")

    parser = argparse.ArgumentParser(
        description="CGDA 跨平台一键启动器（Windows / Linux）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="启动服务")
    p_start.add_argument(
        "component", nargs="?", default="all",
        help="组件: all/docker/fastapi/beat/worker/worker:<name>/frontend（默认 all）",
    )
    p_start.add_argument("--no-frontend", action="store_true", help="不启动前端开发服务器")
    p_start.add_argument("--no-docker", action="store_true", help="不启动 Docker 容器")
    p_start.add_argument(
        "--no-open-meteo",
        action="store_true",
        help="不启动 cgda-open-meteo API（仍启动 Redis/MinIO；同步见 Code/infra/data-sync）",
    )
    p_start.add_argument("--frontend-only", action="store_true", help="仅启动前端（等同 start frontend）")
    p_start.add_argument("--debug", action="store_true", help="调试模式：不隐藏窗口，Celery 日志级别 DEBUG")
    p_start.add_argument(
        "--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT,
        help=f"前端端口（默认 {DEFAULT_FRONTEND_PORT}）",
    )

    # stop
    sub.add_parser("stop", help="停止全部服务")

    # status
    sub.add_parser("status", help="查看服务状态")

    # restart
    p_restart = sub.add_parser("restart", help="重启服务")
    p_restart.add_argument(
        "component", nargs="?", default="all",
        help="组件: all/docker/fastapi/beat/worker/worker:<name>/frontend（默认 all）",
    )
    p_restart.add_argument("--no-frontend", action="store_true")
    p_restart.add_argument("--no-docker", action="store_true")
    p_restart.add_argument("--no-open-meteo", action="store_true")
    p_restart.add_argument("--frontend-only", action="store_true")
    p_restart.add_argument("--debug", action="store_true", help="调试模式")
    p_restart.add_argument(
        "--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT,
        help=f"前端端口（默认 {DEFAULT_FRONTEND_PORT}）",
    )

    # logs
    p_logs = sub.add_parser("logs", help="查看日志")
    p_logs.add_argument(
        "component", nargs="?", default=None,
        help="组件: fastapi/beat/frontend/worker/worker:<name>（默认合并全部）",
    )
    p_logs.add_argument("-n", type=int, default=50, help="显示行数（默认 50）")

    # flush
    sub.add_parser("flush", help="清空 Redis DB + 应用天气文件缓存")

    # sync
    p_sync = sub.add_parser("sync", help="数据面一次性同步（Code/infra/data-sync）")
    p_sync.add_argument(
        "job",
        nargs="?",
        default="open-meteo-sync",
        help="compose service 名（默认 open-meteo-sync）",
    )

    args = parser.parse_args()

    try:
        if args.command == "start":
            return cmd_start(args)
        elif args.command == "stop":
            return cmd_stop()
        elif args.command == "status":
            return cmd_status()
        elif args.command == "restart":
            return cmd_restart(args)
        elif args.command == "logs":
            return cmd_logs(args)
        elif args.command == "flush":
            return cmd_flush()
        elif args.command == "sync":
            return cmd_sync(args.job)
    except KeyboardInterrupt:
        log.warn("Launcher", "用户中断")
        return 130
    finally:
        log.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
