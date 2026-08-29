"""Process lifecycle manager for the CGDA launcher.

Extracted from the original ``launch.py``. The :class:`ProcessManager` owns
all long-lived child processes (Celery Workers, Beat, FastAPI, Frontend)
and provides start / stop / monitor / signal-handling methods.

The manager is instantiated per-launch (not a singleton) because it
carries mutable state (the ``processes`` dict, the ``_shutting_down``
flag) that must not be shared across launches.
"""

from __future__ import annotations

import json
import platform
import psutil
import signal
import subprocess
import sys
import time
from typing import Any

from launch.constants import (
    BACKEND_DIR,
    CELERY_WORKERS,
    DEFAULT_FRONTEND_PORT,
    FRONTEND_DIR,
    LOG_DIR,
    PID_FILE,
    VITE_BEHIND_GATEWAY_PORT,
)
from launch.logging_setup import log, rotate_subprocess_log_if_needed
from launch.subprocess_utils import (
    child_env,
    frontend_dev_command,
    hidden_kwargs,
    python_executable,
)


class ProcessManager:
    """管理所有子进程的生命周期。"""

    def __init__(
        self,
        debug: bool = False,
        frontend_port: int = DEFAULT_FRONTEND_PORT,
        *,
        behind_gateway: bool = False,
    ):
        self.processes: dict[str, subprocess.Popen] = {}
        self._shutting_down = False
        self.debug = debug
        self.behind_gateway = behind_gateway
        if behind_gateway:
            self.frontend_port = VITE_BEHIND_GATEWAY_PORT
        else:
            self.frontend_port = frontend_port

    def _frontend_env(self) -> dict[str, str]:
        env = child_env()
        if self.behind_gateway:
            env["VITE_BEHIND_GATEWAY"] = "1"
            env["VITE_GATEWAY_PORT"] = str(DEFAULT_FRONTEND_PORT)
        return env

    @property
    def _loglevel(self) -> str:
        """Celery 日志级别，debug 模式下为 DEBUG。"""
        return "DEBUG" if self.debug else "INFO"

    def _proc_kwargs(self) -> dict[str, Any]:
        """返回子进程参数；debug 模式下不隐藏窗口。"""
        if self.debug:
            return {}
        return hidden_kwargs()

    def start_celery_workers(self, worker_names: list[str] | None = None) -> None:
        """启动 Celery Worker。worker_names 为 None 时启动全部队列。

        每队列按 instances（env CGDA_WORKER_INSTANCES_<NAME> 可覆盖）启动
        N 个独立进程——Windows solo 池下单进程串行是「同时只能跑一个工作流」
        的根因；多实例实现进程级真并行（2026-08-21 需求4）。
        """
        from launch.constants import worker_instance_count

        if worker_names is None:
            workers_to_start = CELERY_WORKERS
            log.banner(f"启动 Celery Workers ({len(workers_to_start)} 个队列)")
        else:
            workers_to_start = [
                w for w in CELERY_WORKERS if str(w["name"]) in worker_names
            ]
            log.banner(f"启动 Celery Workers ({len(workers_to_start)} 个)")

        py = python_executable()
        worker_script = str(BACKEND_DIR / "start_celery_worker.py")
        hostname = platform.node()
        env = child_env()

        total = 0
        for w in workers_to_start:
            name = str(w["name"])
            queues = str(w["queues"])
            instances = worker_instance_count(name)
            for idx in range(1, instances + 1):
                # 单实例保持旧 pid key（worker-{name}）；多实例 worker-{name}-{i}
                proc_key = f"worker-{name}" if idx == 1 else f"worker-{name}-{idx}"
                log_file = (
                    LOG_DIR / f"worker-{name}.log"
                    if idx == 1
                    else LOG_DIR / f"worker-{name}-{idx}.log"
                )
                log.info(
                    "Worker",
                    f"启动 {proc_key} (queues={queues}, 实例 {idx}/{instances})",
                )

                rotate_subprocess_log_if_needed(log_file)
                if not log_file.exists():
                    log_file.write_text("", encoding="utf-8")

                proc = subprocess.Popen(
                    [
                        py,
                        worker_script,
                        "worker",
                        f"--loglevel={self._loglevel}",
                        f"--queues={queues}",
                        f"--hostname={proc_key}@{hostname}",
                        "-f",
                        str(log_file),
                    ],
                    cwd=str(BACKEND_DIR),
                    # 每进程独立 app 日志文件：多实例并发写同一 RotatingFileHandler
                    # 在 Windows 轮转时 PermissionError 互杀（app/core/logging.py）
                    env={**env, "CGDA_LOG_FILE_ROLE": proc_key},
                    stdout=open(log_file, "a", encoding="utf-8"),
                    stderr=subprocess.STDOUT,
                    **self._proc_kwargs(),
                )
                self.processes[proc_key] = proc
                total += 1

        log.ok(
            "Worker",
            f"{total} 个 Worker 已启动（{len(workers_to_start)} 个队列），"
            "日志: .data/logs/worker-*.log",
        )

    def start_celery_beat(self) -> None:
        """启动 Celery Beat 定时调度器。"""
        log.info("Beat", "启动 Celery Beat 调度器...")
        py = python_executable()
        beat_script = str(BACKEND_DIR / "start_celery_beat.py")
        log_file = LOG_DIR / "beat.log"
        rotate_subprocess_log_if_needed(log_file)
        if not log_file.exists():
            log_file.write_text("", encoding="utf-8")

        proc = subprocess.Popen(
            [
                py,
                beat_script,
                f"--loglevel={self._loglevel}",
                "-f",
                str(log_file),
            ],
            cwd=str(BACKEND_DIR),
            env=child_env(),
            stdout=open(log_file, "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            **self._proc_kwargs(),
        )
        self.processes["beat"] = proc
        log.ok("Beat", "Celery Beat 已启动")

    def start_fastapi(self) -> None:
        """启动 FastAPI 后端服务。"""
        log.info("FastAPI", "启动 FastAPI 后端服务...")
        py = python_executable()
        fastapi_script = str(BACKEND_DIR / "start_fastapi.py")
        log_file = LOG_DIR / "fastapi.log"
        rotate_subprocess_log_if_needed(log_file)
        if not log_file.exists():
            log_file.write_text("", encoding="utf-8")

        proc = subprocess.Popen(
            [py, fastapi_script],
            cwd=str(BACKEND_DIR),
            env=child_env(),
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
        mode = "behind Gateway HMR" if self.behind_gateway else "direct"
        log.info(
            "Frontend",
            f"启动前端 Vite 开发服务器 (port={self.frontend_port}, {mode})...",
        )
        cmd = frontend_dev_command(self.frontend_port)
        if not cmd:
            log.error("Frontend", "未找到 pnpm/npx，请安装 Node.js 并确保在 PATH 中")
            return
        log_file = LOG_DIR / "frontend.log"
        rotate_subprocess_log_if_needed(log_file)
        if not log_file.exists():
            log_file.write_text("", encoding="utf-8")
        fe_env = self._frontend_env()
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(FRONTEND_DIR),
                env=fe_env,
                stdout=open(log_file, "a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                **self._proc_kwargs(),
            )
            self.processes["frontend"] = proc
            log.ok("Frontend", f"Vite 已启动（{cmd[0]}）")
            if self.behind_gateway:
                log.info(
                    "Frontend",
                    f"  本机: http://127.0.0.1:{self.frontend_port}  → 公开入口 http://localhost:{DEFAULT_FRONTEND_PORT}",
                )
            else:
                log.info("Frontend", f"  URL:  http://localhost:{self.frontend_port}")
            log.info("Frontend", f"  日志: {log_file}")
        except FileNotFoundError:
            fallback = None
            from launch.constants import IS_WINDOWS

            for cand in ("npx.cmd", "npx.exe", "npx") if IS_WINDOWS else ("npx",):
                import shutil

                if shutil.which(cand):
                    fallback = [
                        cand,
                        "vite",
                        "--port",
                        str(self.frontend_port),
                        "--host",
                    ]
                    break
            if not fallback or fallback[0] == cmd[0]:
                log.error("Frontend", f"启动命令不可用: {cmd[0]}")
                return
            log.warn("Frontend", f"{cmd[0]} 不可执行，回退 {fallback[0]}")
            try:
                proc = subprocess.Popen(
                    fallback,
                    cwd=str(FRONTEND_DIR),
                    env=fe_env,
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
        """停止所有子进程。

        兼容 subprocess.Popen 与 psutil.Process 两种句柄：monitor() 检测到
        外部重启时会把句柄替换成 psutil.Process（无 poll() 方法，且其
        wait(timeout) 超时抛 psutil.TimeoutExpired 而非 subprocess.TimeoutExpired），
        因此存活探测与超时捕获都必须双兼容，否则 Ctrl+C 优雅停止会崩。
        """
        log.banner("停止所有服务")
        for name, proc in reversed(list(self.processes.items())):
            if self._poll_proc(proc) is not None:
                log.info("Stop", f"{name} 已退出")
                continue
            log.info("Stop", f"停止 {name} (pid={proc.pid})...")
            proc.terminate()
            try:
                proc.wait(timeout=10)
                log.ok("Stop", f"{name} 已停止")
            except (subprocess.TimeoutExpired, psutil.TimeoutExpired):
                log.warn("Stop", f"{name} 10s 内未退出，强制 kill")
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except (subprocess.TimeoutExpired, psutil.TimeoutExpired):
                    log.warn("Stop", f"{name} kill 后仍未退出")
        self.processes.clear()

    @staticmethod
    def _poll_proc(proc: Any) -> int | None:
        """兼容 subprocess.Popen 与 psutil.Process 的存活探测。

        返回 None=仍在运行；退出码（psutil 拿不到精确码时用 -1 占位）。
        2026-08-22 修复：外部重启把监视句柄切到 psutil.Process 后，
        ``proc.poll()`` 抛 AttributeError 使 monitor 主循环整体崩溃
        （用户实测 launch 退出码 1）。
        """
        if hasattr(proc, "poll"):
            return proc.poll()
        try:
            return None if proc.is_running() else -1
        except Exception:
            return -1

    def monitor(self) -> None:
        """监控所有进程，有进程异常退出时报告。

        兼容外部重启（2026-08-22 用户报障）：在其它终端 ``launch.py restart
        backend`` 等操作会替换 pid 文件里的进程。本监视器持有的旧 proc 退出
        时先读 pid 文件——若该服务的 pid 已变更且新 pid 存活，判定为「外部
        重启」：INFO 提示一次并把监视句柄切到新进程，不再刷红色 ERROR；
        仅当 pid 文件未变（真正崩溃/被杀）才报异常退出。
        """
        for name, proc in list(self.processes.items()):
            rc = self._poll_proc(proc)
            if rc is None:
                continue
            if self._shutting_down:
                continue

            new_pid = self._external_pid_for(name)
            if new_pid is not None:
                self.processes[name] = new_pid  # psutil.Process，is_running 探测
                log.info(
                    "Monitor",
                    f"{name} 已被外部重启（旧 pid 退出 code={rc}），"
                    f"监视切换到新 pid={new_pid.pid}",
                )
                continue

            log.error("Monitor", f"{name} 异常退出 (code={rc})")
            log_file = LOG_DIR / f"{name}.log"
            if name.startswith("worker-"):
                log_file = LOG_DIR / f"worker-{name.replace('worker-', '')}.log"
            if log_file.exists():
                lines = log_file.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                tail = "\n".join(lines[-5:]) if lines else "(空日志)"
                log.error("Monitor", f"{name} 日志尾部:\n{tail}")
            # 已退出进程从监视表移除，避免每 5s 重复刷同一 ERROR
            self.processes.pop(name, None)

    def _external_pid_for(self, name: str):
        """读 pid 文件：该服务 pid 已变更且新 pid 存活时返回其 psutil 句柄。

        pid 文件不存在/解析失败/服务名缺失/pid 未变，均返回 None（真异常）。
        """
        try:
            data = json.loads(PID_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
        recorded = data.get(name)
        if not isinstance(recorded, int):
            return None
        old_pid = self.processes.get(name)
        old_pid_val = old_pid.pid if old_pid is not None else None
        if recorded == old_pid_val:
            return None  # pid 未变：真异常退出
        try:
            proc = psutil.Process(recorded)
            if proc.is_running():
                return proc
        except Exception:
            return None
        return None

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
