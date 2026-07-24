"""Command implementations for the CGDA launcher.

Extracted from the original ``launch.py``. Each ``cmd_*`` function
corresponds to a CLI subcommand (start / stop / status / restart / logs /
sync / flush / reset-db) and returns an exit code.

The command functions import infrastructure from sibling modules:
- :mod:`docker_manager` for Docker / Redis lifecycle
- :mod:`process_manager` for Worker / Beat / FastAPI / Frontend lifecycle
- :mod:`subprocess_utils` for cross-platform process termination
- :mod:`debug_utils` for log file resolution and debug diagnostics
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from launch.constants import (
    BACKEND_DIR,
    DATA_SYNC_DIR,
    DEFAULT_FRONTEND_PORT,
    FRONTEND_DIR,
    IS_WINDOWS,
    LOG_DIR,
    PID_FILE,
    SNAPSHOT_ROOT,
    VALID_WORKER_NAMES,
    WEATHER_CACHE_DIR,
    WEATHERENGINE_CACHE_DIR,
    WORKFLOW_DEFINITIONS_DIR,
    WORKFLOW_SEEDS_DIR,
    WORKFLOW_STATE_DB_STEM,
    WORKFLOW_STATE_DIR,
)
from launch.debug_utils import get_log_files, parse_log_timestamp, print_debug_info
from launch.docker_manager import (
    docker_available,
    redis_running,
    start_docker_infra,
    stop_docker_infra,
    wait_for_redis,
)
from launch.logging_setup import log
from launch.process_manager import ProcessManager
from launch.subprocess_utils import (
    ensure_named_volume,
    ensure_project_initialized,
    hidden_kwargs,
    pid_alive,
    resolve_open_meteo_volume_name,
    terminate_by_cmdline_patterns,
)


# ─── 启动命令 ────────────────────────────────────────────────────────────────
def cmd_start(args: argparse.Namespace) -> int:
    """启动 CGDA 服务（全部或指定组件）。"""
    component = args.component
    if component is None:
        component = "all"

    if getattr(args, "frontend_only", False) and component == "all":
        component = "frontend"

    ensure_project_initialized()

    if args.debug:
        print_debug_info()

    if component == "all":
        return _start_all(args)

    pm = ProcessManager(debug=args.debug, frontend_port=args.frontend_port)
    pm.install_signal_handlers()

    if component == "docker":
        if not start_docker_infra(
            start_open_meteo=not getattr(args, "no_open_meteo", False)
        ):
            return 1
        wait_for_redis(max_wait=30)
        log.ok("Launcher", "Docker 基础设施已启动（不进入监控循环）")
        return 0

    if component == "fastapi":
        if not redis_running():
            log.warn(
                "FastAPI",
                "Redis 未检测到，FastAPI 可能无法正常工作（请先 start docker）",
            )
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
    log.info(
        "Launcher",
        "可用组件: all, docker, fastapi, beat, worker, worker:<name>, frontend",
    )
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

    if not args.no_docker:
        if not start_docker_infra(
            start_open_meteo=not getattr(args, "no_open_meteo", False)
        ):
            log.error("Launcher", "Docker 基础设施启动失败，终止")
            return 1
        wait_for_redis(max_wait=30)
        time.sleep(2)
    else:
        log.warn("Launcher", "跳过 Docker（--no-docker），使用外部 Redis/MinIO")

    if not args.frontend_only:
        pm.start_celery_workers()
        pm.start_celery_beat()
        time.sleep(2)
        pm.start_fastapi()
        pm.wait_for_fastapi(max_wait=30)

    if not args.no_frontend:
        pm.start_frontend()
        time.sleep(3)

    pm.save_pids()

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

    try:
        while not pm._shutting_down:
            time.sleep(5)
            pm.monitor()
    except KeyboardInterrupt:
        pass

    pm.stop_all()
    log.banner("已停止")
    return 0


# ─── 停止命令 ────────────────────────────────────────────────────────────────
def cmd_stop() -> int:
    """停止所有 CGDA 服务。"""
    log.banner("停止 CGDA 服务")

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

    terminate_by_cmdline_patterns(
        [
            "start_celery_worker.py",
            "start_celery_beat.py",
            "start_fastapi.py",
        ]
    )

    terminate_by_cmdline_patterns(
        [
            str(FRONTEND_DIR),
            f"vite --port {DEFAULT_FRONTEND_PORT}",
        ]
    )

    time.sleep(1)
    stop_docker_infra()
    log.ok("Stop", "所有服务已停止")
    return 0


# ─── 状态命令 ────────────────────────────────────────────────────────────────
def cmd_status() -> int:
    """检查所有服务运行状态。"""
    log.banner("CGDA 服务状态")

    log.info("Status", "Docker 容器:")
    containers = [
        ("cgda-redis", "Redis"),
        ("cgda-minio", "MinIO"),
        ("cgda-open-meteo", "Open-Meteo"),
    ]
    for cid, label in containers:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", cid],
            capture_output=True,
            text=True,
            **hidden_kwargs(),
        )
        state = r.stdout.strip() if r.returncode == 0 else "未运行"
        icon = "✓" if state == "running" else "✗"
        log.info("Status", f"  {icon} {label:8s} ({cid}): {state}")

    import urllib.request

    try:
        req = urllib.request.Request("http://127.0.0.1:8000/health")
        with urllib.request.urlopen(req, timeout=3) as resp:
            ok = resp.status == 200
    except Exception:
        ok = False
    icon = "✓" if ok else "✗"
    log.info(
        "Status",
        f"  {icon} FastAPI  (http://127.0.0.1:8000): {'就绪' if ok else '未响应'}",
    )

    try:
        req = urllib.request.Request(f"http://localhost:{DEFAULT_FRONTEND_PORT}/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            fe_ok = resp.status == 200
    except Exception:
        fe_ok = False
    icon = "✓" if fe_ok else "✗"
    log.info(
        "Status",
        f"  {icon} Frontend (http://localhost:{DEFAULT_FRONTEND_PORT}):  {'就绪' if fe_ok else '未响应'}",
    )

    if PID_FILE.exists():
        try:
            pids = json.loads(PID_FILE.read_text(encoding="utf-8"))
            log.info("Status", "子进程 PID:")
            for name, pid in pids.items():
                alive = pid_alive(pid)
                icon = "✓" if alive else "✗"
                log.info(
                    "Status",
                    f"  {icon} {name:20s} pid={pid} {'运行中' if alive else '已退出'}",
                )
        except (json.JSONDecodeError, OSError):
            pass
    else:
        log.info("Status", "无 PID 文件（服务可能未通过 launch.py 启动）")

    vol = resolve_open_meteo_volume_name()
    vol_ok = False
    try:
        r = subprocess.run(
            ["docker", "volume", "inspect", vol],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            **hidden_kwargs(),
        )
        vol_ok = r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    icon = "✓" if vol_ok else "✗"
    log.info(
        "Status", f"  {icon} data-sync volume ({vol}): {'存在' if vol_ok else '缺失'}"
    )
    sync_compose = DATA_SYNC_DIR / "docker-compose.yml"
    icon = "✓" if sync_compose.is_file() else "✗"
    log.info("Status", f"  {icon} data-sync compose: {DATA_SYNC_DIR}")

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

    files = get_log_files(component)
    if not files:
        log.error("Logs", f"未知组件: {component}")
        log.info("Logs", "可用: all, fastapi, beat, frontend, worker, worker:<name>")
        return 1

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
                ts = parse_log_timestamp(line)
                if ts is None:
                    ts = mtime
                entries.append((ts, label, line))

        entries.sort(key=lambda x: x[0])
        for ts, label, line in entries[-n:]:
            print(f"[{label:15s}] {line}")
        return 0

    existing = [(lbl, fp) for lbl, fp in files if fp.exists()]
    if not existing:
        log.error("Logs", f"日志文件不存在: {component}")
        log.info("Logs", f"期望路径: {files[0][1]}")
        return 1

    if sys.platform != "win32":
        cmd = ["tail", "-n", str(n), "-f"] + [str(fp) for _, fp in existing]
        log.info("Logs", f"跟踪 {len(existing)} 个文件（Ctrl+C 退出）...")
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass
        return 0

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

    vol = resolve_open_meteo_volume_name()
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
                    domains = (
                        line.split("=", 1)[1].strip().strip('"').strip("'") or domains
                    )
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
        _record_cli_sync_result(
            ok=False, domains=domains, message="sync timeout 3600s", exit_code=1
        )
        return 1
    except FileNotFoundError:
        log.error("Sync", "docker 命令未找到")
        _record_cli_sync_result(
            ok=False, domains=domains, message="docker not found", exit_code=127
        )
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
    _record_cli_sync_result(
        ok=True, domains=domains, message=f"{job} completed via launch.py", exit_code=0
    )
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


# ─── 重置 workflow_state 命令 ────────────────────────────────────────────────
def _create_workflow_snapshot() -> Path | None:
    """创建带时间戳的 workflow_state + workflow_definitions 快照。"""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot_dir = SNAPSHOT_ROOT / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    copied_any = False
    for src, label in (
        (WORKFLOW_STATE_DIR, "workflow_state"),
        (WORKFLOW_DEFINITIONS_DIR, "workflow_definitions"),
    ):
        if not src.is_dir():
            continue
        dest = snapshot_dir / label
        try:
            shutil.copytree(src, dest, dirs_exist_ok=True)
            file_count = sum(1 for f in dest.rglob("*") if f.is_file())
            log.info("Snapshot", f"  {label}: {file_count} 个文件 → {dest}")
            copied_any = True
        except OSError as exc:
            log.warn("Snapshot", f"  {label}: 备份失败 ({exc})")

    if not copied_any:
        try:
            snapshot_dir.rmdir()
        except OSError:
            pass
        return None

    return snapshot_dir


def _rotate_snapshots(max_keep: int) -> int:
    """保留最近 max_keep 份快照，删除更旧的。返回被删除的数量。"""
    if not SNAPSHOT_ROOT.is_dir():
        return 0
    snapshots = sorted(
        [d for d in SNAPSHOT_ROOT.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    to_remove = snapshots[max_keep:]
    for old in to_remove:
        try:
            shutil.rmtree(old, ignore_errors=True)
            log.info("Snapshot", f"轮转删除旧快照: {old.name}")
        except OSError:
            pass
    return len(to_remove)


def _clear_workflow_state() -> int:
    """删除工作流执行状态数据库 workflow_state.sqlite3 及其 WAL/SHM 侧车文件。"""
    if not WORKFLOW_STATE_DIR.is_dir():
        WORKFLOW_STATE_DIR.mkdir(parents=True, exist_ok=True)
        return 0

    targets = [
        WORKFLOW_STATE_DIR / WORKFLOW_STATE_DB_STEM,
        WORKFLOW_STATE_DIR / f"{WORKFLOW_STATE_DB_STEM}-wal",
        WORKFLOW_STATE_DIR / f"{WORKFLOW_STATE_DB_STEM}-shm",
        WORKFLOW_STATE_DIR / f"{WORKFLOW_STATE_DB_STEM}-journal",
    ]
    file_count = 0
    for item in targets:
        if not item.exists():
            continue
        try:
            item.unlink()
            file_count += 1
        except OSError as exc:
            log.warn("Reset", f"  无法删除 {item.name}: {exc}")
    return file_count


def _reseed_workflow_definitions(*, clear_user: bool = False) -> tuple[int, int]:
    """清空并重新 seed workflow_definitions。"""
    system_dir = WORKFLOW_DEFINITIONS_DIR / "system"
    user_dir = WORKFLOW_DEFINITIONS_DIR / "user"

    system_dir.mkdir(parents=True, exist_ok=True)
    user_dir.mkdir(parents=True, exist_ok=True)

    for item in system_dir.iterdir():
        try:
            if item.is_file():
                item.unlink()
        except OSError as exc:
            log.warn("Reset", f"  无法删除 system/{item.name}: {exc}")

    seed_count = 0
    if WORKFLOW_SEEDS_DIR.is_dir():
        for src in sorted(WORKFLOW_SEEDS_DIR.glob("*.json")):
            dest = system_dir / src.name
            try:
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                seed_count += 1
            except OSError as exc:
                log.warn("Reset", f"  无法 seed {src.name}: {exc}")

    user_cleared = 0
    if clear_user:
        for item in user_dir.iterdir():
            try:
                if item.is_file() and item.name != ".gitkeep":
                    item.unlink()
                    user_cleared += 1
            except OSError as exc:
                log.warn("Reset", f"  无法删除 user/{item.name}: {exc}")

    return seed_count, user_cleared


def _verify_workflow_state_empty() -> bool:
    """验证工作流执行状态数据库已被清空。"""
    if not WORKFLOW_STATE_DIR.is_dir():
        return True
    targets = [
        WORKFLOW_STATE_DIR / WORKFLOW_STATE_DB_STEM,
        WORKFLOW_STATE_DIR / f"{WORKFLOW_STATE_DB_STEM}-wal",
        WORKFLOW_STATE_DIR / f"{WORKFLOW_STATE_DB_STEM}-shm",
        WORKFLOW_STATE_DIR / f"{WORKFLOW_STATE_DB_STEM}-journal",
    ]
    return not any(t.exists() for t in targets)


def _backend_services_running() -> bool:
    """检测后端服务（FastAPI / Celery）是否正在运行。"""
    if not PID_FILE.exists():
        return False
    try:
        pids = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    backend_names = [n for n in pids if n != "frontend"]
    alive = [n for n in backend_names if pid_alive(pids[n])]
    return len(alive) > 0


def cmd_reset_db(args: argparse.Namespace) -> int:
    """reset-db: 清空 workflow_state 运行时数据库并重新 seed 工作流定义。"""
    log.banner("重置 workflow_state")

    if not getattr(args, "force", False) and _backend_services_running():
        log.error("Reset", "后端服务正在运行，SQLite 文件被锁定无法删除。")
        log.info("Reset", "  请先停止服务:  python launch.py stop")
        log.info("Reset", "  然后重置:      python launch.py reset-db")
        log.info(
            "Reset",
            "  或强制执行（部分文件可能删除失败）:  python launch.py reset-db --force",
        )
        return 1

    if not args.yes:
        print()
        print("  ⚠  此操作将清空以下运行时数据：")
        print(
            f"    • workflow_state.sqlite3（工作流执行状态 + 定时器）  {WORKFLOW_STATE_DIR}"
        )
        print("    • workflow_definitions/system/  （重新 seed）")
        if args.clear_user:
            print("    • workflow_definitions/user/    （用户自定义工作流也将被清空）")
        print()
        print("  保留：同目录下的凭据 / 配置 DB（api_keys / gee_credentials /")
        print(
            "        remote_storage_credentials / weather_engine / weather_providers 等）"
        )
        print(
            "  快照将自动创建到 .data/workflow_state_snapshots/（可用 --no-snapshot 跳过）"
        )
        print()
        try:
            answer = input("  确认继续？输入 yes 执行: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("yes", "y"):
            log.warn("Reset", "用户取消，未做任何更改")
            return 0

    if not args.no_snapshot:
        log.info("Snapshot", "创建快照备份...")
        snapshot_path = _create_workflow_snapshot()
        if snapshot_path:
            log.ok("Snapshot", f"快照已保存: {snapshot_path}")
            removed = _rotate_snapshots(args.keep_snapshots)
            if removed > 0:
                log.info("Snapshot", f"轮转清理了 {removed} 个旧快照")
        else:
            log.info("Snapshot", "无运行时数据需要备份（源目录为空或不存在）")
    else:
        log.warn("Snapshot", "已跳过快照备份（--no-snapshot）")

    log.info("Reset", f"清空 workflow_state: {WORKFLOW_STATE_DIR}")
    cleared = _clear_workflow_state()
    log.ok("Reset", f"已删除 {cleared} 个文件/目录")

    log.info("Reset", "重新 seed workflow_definitions/system ...")
    seed_count, user_cleared = _reseed_workflow_definitions(clear_user=args.clear_user)
    log.ok("Reset", f"已 seed {seed_count} 个系统工作流模板")
    if args.clear_user:
        log.ok("Reset", f"已清空 {user_cleared} 个用户自定义工作流")
    else:
        log.info("Reset", "用户自定义工作流已保留（--clear-user 可同时清空）")

    log.banner("验证")
    state_empty = _verify_workflow_state_empty()
    if state_empty:
        log.ok("Verify", "workflow_state 已清空（工作流状态数据库已删除）")
    else:
        remaining = [
            name
            for name in (
                WORKFLOW_STATE_DB_STEM,
                f"{WORKFLOW_STATE_DB_STEM}-wal",
                f"{WORKFLOW_STATE_DB_STEM}-shm",
                f"{WORKFLOW_STATE_DB_STEM}-journal",
            )
            if (WORKFLOW_STATE_DIR / name).exists()
        ]
        log.error("Verify", f"workflow_state 仍有数据库文件: {remaining}")

    system_dir = WORKFLOW_DEFINITIONS_DIR / "system"
    seeded_files = list(system_dir.glob("*.json")) if system_dir.is_dir() else []
    if seeded_files:
        log.ok(
            "Verify", f"workflow_definitions/system: {len(seeded_files)} 个种子文件就位"
        )
    else:
        log.warn(
            "Verify",
            "workflow_definitions/system 无种子文件（检查 workflow_seeds/system 是否存在）",
        )

    log.banner("重置完成")
    if state_empty:
        log.ok("Reset", "workflow_state 已清空，工作流定义已重新 seed")
        log.info("Reset", "  下次启动后端时 SQLite 表会自动重建（schema 由代码初始化）")
        log.info("Reset", f"  快照目录: {SNAPSHOT_ROOT}")
        return 0
    else:
        log.error("Reset", "workflow_state 清空不完整，请检查上方错误信息")
        log.info("Reset", f"  可从快照恢复: {SNAPSHOT_ROOT}")
        return 1


# ─── 清空缓存命令 ────────────────────────────────────────────────────────────
def cmd_flush(args: argparse.Namespace) -> int:
    """清空 Redis DB + 文件缓存。"""
    dry_run = getattr(args, "dry_run", False)
    log.banner("预览待清空对象" if dry_run else "清空缓存")

    redis_keys: str | None = None
    try:
        probe = subprocess.run(
            ["docker", "exec", "cgda-redis", "redis-cli", "DBSIZE"],
            capture_output=True,
            text=True,
            timeout=10,
            **hidden_kwargs(),
        )
        if probe.returncode == 0:
            redis_keys = probe.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        redis_keys = None

    cache_targets = []
    for cache_dir, label in (
        (WEATHER_CACHE_DIR, "weather"),
        (WEATHERENGINE_CACHE_DIR, "weatherengine"),
    ):
        file_count = (
            sum(1 for f in cache_dir.rglob("*") if f.is_file())
            if cache_dir.exists()
            else 0
        )
        cache_targets.append((cache_dir, label, file_count))

    if dry_run or not args.yes:
        print()
        print("  ⚠  此操作将清空以下对象：")
        if redis_keys is not None:
            print(
                f"    • Redis DB（FLUSHDB）  当前约 {redis_keys} 个 key  容器 cgda-redis"
            )
        else:
            print(
                "    • Redis DB（FLUSHDB）  无法探测 key 数量（容器未运行？）  容器 cgda-redis"
            )
        for cache_dir, label, file_count in cache_targets:
            print(f"    • 文件缓存 {label}  {file_count} 个文件  {cache_dir}")
        print()
        print("  保留：Open-Meteo named volume（backend_open-meteo-data）不受影响")
        print()

    if dry_run:
        log.ok("Flush", "dry-run 预览完成，未做任何更改")
        return 0

    if not args.yes:
        try:
            answer = input("  确认继续？输入 yes 执行: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("yes", "y"):
            log.warn("Flush", "用户取消，未做任何更改")
            return 0

    log.info("Flush", "清空 Redis DB (FLUSHDB)...")
    try:
        r = subprocess.run(
            ["docker", "exec", "cgda-redis", "redis-cli", "FLUSHDB"],
            capture_output=True,
            text=True,
            timeout=10,
            **hidden_kwargs(),
        )
        if r.returncode == 0:
            log.ok("Flush", f"Redis DB 已清空 (响应: {r.stdout.strip()})")
        else:
            log.error("Flush", f"Redis 清空失败: {r.stderr.strip()}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.error("Flush", f"Redis 清空异常: {e}")

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
