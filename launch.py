#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CGDA 跨平台一键启动器
=====================
支持 Windows / Linux，优先使用 Docker 启动基础设施（Redis + MinIO），
后端服务（FastAPI + Celery Workers + Beat）以隐藏窗口的子进程方式运行。

用法:
    python launch.py start    [--no-frontend] [--no-docker]
    python launch.py stop
    python launch.py status
    python launch.py restart  [--no-frontend] [--no-docker]

选项:
    --no-frontend   不启动前端开发服务器
    --no-docker     不启动 Docker 容器（使用外部 Redis/MinIO）
    --frontend-only 仅启动前端
"""

from __future__ import annotations

import argparse
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ─── 路径常量 ────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR / "Code" / "backend"
FRONTEND_DIR = SCRIPT_DIR / "Code" / "frontend"
LOG_DIR = BACKEND_DIR / ".data" / "logs"
DATA_DIRS = [
    BACKEND_DIR / ".data" / "logs",
    BACKEND_DIR / ".data" / "workflow_state",
    BACKEND_DIR / ".data" / "artifacts",
    BACKEND_DIR / ".data" / "cache",
]
LAUNCHER_LOG = LOG_DIR / "launcher.log"
PID_FILE = LOG_DIR / "launcher_pids.json"

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

# ─── 日志系统 ────────────────────────────────────────────────────────────────
class Log:
    """规范的彩色日志输出器，同时写入控制台和文件。"""

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
        self._file = log_file
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(log_file, "a", encoding="utf-8")
        self._is_tty = sys.stdout.isatty()
        # Windows 启用 ANSI 颜色
        if sys.platform == "win32" and self._is_tty:
            os.system("")  # 激活 VT100

    def _write(self, level: str, category: str, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cat_padded = category.ljust(10)
        line = f"[{ts}] [{level:5s}] [{cat_padded}] {message}"
        # 写文件（无颜色）
        self._fh.write(line + "\n")
        self._fh.flush()
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
        self._fh.close()


log = Log(LAUNCHER_LOG)

# ─── 跨平台子进程工具 ────────────────────────────────────────────────────────
def _hidden_kwargs() -> dict[str, Any]:
    """返回在 Windows 上隐藏控制台窗口的 subprocess 参数。"""
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def _python_executable() -> str:
    """返回当前 Python 解释器路径，确保子进程使用同一环境。"""
    return sys.executable


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


def start_docker_infra() -> bool:
    """启动 Redis + MinIO Docker 容器。"""
    log.banner("启动 Docker 基础设施 (Redis + MinIO)")
    if not docker_available():
        log.error("Docker", "Docker 未运行或未安装，请先启动 Docker Desktop")
        return False

    log.info("Docker", "启动 Redis + MinIO 容器...")
    try:
        r = subprocess.run(
            ["docker", "compose", "up", "-d", "redis", "minio", "minio-init"],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            timeout=120,
            **_hidden_kwargs(),
        )
        if r.returncode != 0:
            log.error("Docker", f"docker compose 启动失败:\n{r.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log.error("Docker", "docker compose 启动超时（120s）")
        return False

    log.ok("Docker", "容器已启动")
    log.info("Docker", "  Redis:  redis://127.0.0.1:6379/0")
    log.info("Docker", "  MinIO:  API http://127.0.0.1:9100 | Console http://127.0.0.1:9101")
    return True


def stop_docker_infra() -> None:
    log.info("Docker", "停止 Redis + MinIO 容器...")
    try:
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            **_hidden_kwargs(),
        )
        log.ok("Docker", "容器已停止")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        log.warn("Docker", "容器停止超时或 Docker 不可用")


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


# ─── 进程管理 ────────────────────────────────────────────────────────────────
class ProcessManager:
    """管理所有子进程的生命周期。"""

    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self._shutting_down = False

    def start_celery_workers(self) -> None:
        """启动 7 个 Celery Worker（隐藏窗口）。"""
        log.banner("启动 Celery Workers (7 个队列)")
        py = _python_executable()
        worker_script = str(BACKEND_DIR / "start_celery_worker.py")
        hostname = platform.node()

        for w in CELERY_WORKERS:
            name = w["name"]
            queues = w["queues"]
            log_file = LOG_DIR / f"worker-{name}.log"
            log.info("Worker", f"启动 worker-{name} (queues={queues})")

            # 清空旧日志
            log_file.write_text("", encoding="utf-8")

            proc = subprocess.Popen(
                [
                    py, worker_script, "worker",
                    "--loglevel=INFO",
                    f"--queues={queues}",
                    f"--hostname=worker-{name}@{hostname}",
                    "-f", str(log_file),
                ],
                stdout=open(log_file, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                **_hidden_kwargs(),
            )
            self.processes[f"worker-{name}"] = proc

        log.ok("Worker", f"7 个 Worker 已启动，日志: .data/logs/worker-*.log")

    def start_celery_beat(self) -> None:
        """启动 Celery Beat 定时调度器。"""
        log.info("Beat", "启动 Celery Beat 调度器...")
        py = _python_executable()
        beat_script = str(BACKEND_DIR / "start_celery_beat.py")
        log_file = LOG_DIR / "beat.log"
        log_file.write_text("", encoding="utf-8")

        proc = subprocess.Popen(
            [
                py, beat_script,
                "--loglevel=INFO",
                "-f", str(log_file),
            ],
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            **_hidden_kwargs(),
        )
        self.processes["beat"] = proc
        log.ok("Beat", "Celery Beat 已启动")

    def start_fastapi(self) -> None:
        """启动 FastAPI 后端服务。"""
        log.info("FastAPI", "启动 FastAPI 后端服务...")
        py = _python_executable()
        fastapi_script = str(BACKEND_DIR / "start_fastapi.py")
        log_file = LOG_DIR / "fastapi.log"
        log_file.write_text("", encoding="utf-8")

        proc = subprocess.Popen(
            [py, fastapi_script],
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            **_hidden_kwargs(),
        )
        self.processes["fastapi"] = proc
        log.ok("FastAPI", "FastAPI 已启动")
        log.info("FastAPI", "  API:  http://127.0.0.1:8000")
        log.info("FastAPI", "  Docs: http://127.0.0.1:8000/docs")
        log.info("FastAPI", f"  日志: {log_file}")

    def start_frontend(self) -> None:
        """启动前端 Vite 开发服务器。"""
        log.info("Frontend", "启动前端 Vite 开发服务器...")
        npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
        log_file = LOG_DIR / "frontend.log"
        log_file.write_text("", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                [npm_cmd, "run", "dev"],
                cwd=str(FRONTEND_DIR),
                stdout=open(log_file, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                **_hidden_kwargs(),
            )
            self.processes["frontend"] = proc
            log.ok("Frontend", "Vite 开发服务器已启动")
            log.info("Frontend", "  URL:  http://localhost:5173")
            log.info("Frontend", f"  日志: {log_file}")
        except FileNotFoundError:
            log.error("Frontend", "npm 未找到，请确保 Node.js 在 PATH 中")

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

    def save_pids(self) -> None:
        """保存 PID 信息到文件，供 stop 命令使用。"""
        import json
        pids = {name: proc.pid for name, proc in self.processes.items()}
        PID_FILE.write_text(json.dumps(pids, indent=2), encoding="utf-8")
        log.debug("Launcher", f"PID 文件已保存: {PID_FILE}")

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


# ─── 停止命令 ────────────────────────────────────────────────────────────────
def cmd_stop() -> int:
    """停止所有 CGDA 服务。"""
    log.banner("停止 CGDA 服务")

    # 1. 从 PID 文件读取进程
    import json
    pm = ProcessManager()
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

    # 2. 兜底：按窗口标题 / 命令行匹配杀进程
    if sys.platform == "win32":
        # taskkill 按窗口标题
        for pattern in ["CGDA-*", "*worker*", "*celery*"]:
            subprocess.run(
                ["taskkill", "/FI", f"WINDOWTITLE eq {pattern}", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **_hidden_kwargs(),
            )
        # 按命令行匹配 python start_celery_worker.py / start_fastapi.py
        subprocess.run(
            'wmic process where "commandline like \'%start_celery_worker.py%\' or commandline like \'%start_fastapi.py%\' or commandline like \'%start_celery_beat.py%\'" call terminate',
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_hidden_kwargs(),
        )
    else:
        # Linux: pkill 按脚本名匹配
        for script in ["start_celery_worker.py", "start_celery_beat.py", "start_fastapi.py"]:
            subprocess.run(
                ["pkill", "-f", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    # 3. 杀前端 node 进程（仅在运行 Vite 时）
    if sys.platform == "win32":
        # 精确匹配 vite dev server，避免杀掉其他 node 进程
        subprocess.run(
            'wmic process where "commandline like \'%vite%\' and commandline like \'%dev%\'" call terminate',
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **_hidden_kwargs(),
        )
    else:
        subprocess.run(["pkill", "-f", "vite"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
    containers = [("cgda-redis", "Redis"), ("cgda-minio", "MinIO")]
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
        req = urllib.request.Request("http://localhost:5173/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            fe_ok = resp.status == 200
    except Exception:
        fe_ok = False
    icon = "✓" if fe_ok else "✗"
    log.info("Status", f"  {icon} Frontend (http://localhost:5173):  {'就绪' if fe_ok else '未响应'}")

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

    return 0


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ─── 启动命令 ────────────────────────────────────────────────────────────────
def cmd_start(args: argparse.Namespace) -> int:
    """启动全部 CGDA 服务。"""
    log.banner("CGDA 一键启动")
    log.info("Launcher", f"操作系统: {sys.platform}")
    log.info("Launcher", f"Python:   {sys.executable}")
    log.info("Launcher", f"后端目录: {BACKEND_DIR}")
    log.info("Launcher", f"前端目录: {FRONTEND_DIR}")

    # 1. 创建数据目录
    for d in DATA_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    log.ok("Launcher", "数据目录已就绪")

    pm = ProcessManager()
    pm.install_signal_handlers()

    # 2. 启动 Docker 基础设施
    if not args.no_docker:
        if not start_docker_infra():
            log.error("Launcher", "Docker 基础设施启动失败，终止")
            return 1
        wait_for_redis(max_wait=30)
        time.sleep(2)  # 额外缓冲确保 Redis 完全就绪
    else:
        log.warn("Launcher", "跳过 Docker（--no-docker），使用外部 Redis/MinIO")

    # 3. 启动 Celery Workers
    if not args.frontend_only:
        pm.start_celery_workers()
        pm.start_celery_beat()
        time.sleep(2)

        # 4. 启动 FastAPI
        pm.start_fastapi()
        pm.wait_for_fastapi(max_wait=30)

    # 5. 启动前端
    if not args.no_frontend:
        pm.start_frontend()
        time.sleep(3)

    # 6. 保存 PID
    pm.save_pids()

    # 7. 汇总
    log.banner("启动完成")
    log.ok("Launcher", "所有服务已启动:")
    if not args.frontend_only:
        log.info("Launcher", "  FastAPI:   http://127.0.0.1:8000")
        log.info("Launcher", "  API Docs:  http://127.0.0.1:8000/docs")
        log.info("Launcher", "  Workers:   7 个 Celery Worker + 1 Beat")
    if not args.no_frontend:
        log.info("Launcher", "  Frontend:  http://localhost:5173")
    log.info("Launcher", f"  日志目录:  {LOG_DIR}")
    log.info("Launcher", "  停止方式:  python launch.py stop  或  Ctrl+C")
    log.info("Launcher", "")

    # 8. 持续监控（阻塞，直到收到信号）
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
    log.banner("重启 CGDA 服务")
    cmd_stop()
    time.sleep(2)
    return cmd_start(args)


# ─── 入口 ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="CGDA 跨平台一键启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="启动全部服务")
    p_start.add_argument("--no-frontend", action="store_true", help="不启动前端开发服务器")
    p_start.add_argument("--no-docker", action="store_true", help="不启动 Docker 容器")
    p_start.add_argument("--frontend-only", action="store_true", help="仅启动前端")

    sub.add_parser("stop", help="停止全部服务")
    sub.add_parser("status", help="查看服务状态")

    p_restart = sub.add_parser("restart", help="重启全部服务")
    p_restart.add_argument("--no-frontend", action="store_true")
    p_restart.add_argument("--no-docker", action="store_true")
    p_restart.add_argument("--frontend-only", action="store_true")

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
    except KeyboardInterrupt:
        log.warn("Launcher", "用户中断")
        return 130
    finally:
        log.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
