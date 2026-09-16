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

from launch.cache_hygiene import apply_prepare_from_args, prepare_launch_caches
from launch.constants import (
    BACKEND_DIR,
    DATA_SYNC_DIR,
    DEFAULT_FRONTEND_PORT,
    DEFAULT_MODE,
    FRONTEND_DIR,
    IS_WINDOWS,
    LOG_DIR,
    MODE_DEV,
    MODE_PROD,
    PID_FILE,
    PROD_APP_SERVICES,
    PROD_GATEWAY_CONTAINER,
    PROD_PROJECT,
    SCRIPT_DIR,
    SNAPSHOT_ROOT,
    VALID_MODES,
    VALID_WORKER_NAMES,
    VITE_BEHIND_GATEWAY_PORT,
    WEATHER_CACHE_DIR,
    WEATHERENGINE_CACHE_DIR,
    WORKFLOW_DEFINITIONS_DIR,
    WORKFLOW_SEEDS_DIR,
    WORKFLOW_STATE_DB_STEM,
    WORKFLOW_STATE_DIR,
)
from launch.debug_utils import get_log_files, parse_log_timestamp, print_debug_info
from launch.docker_manager import (
    _windows_docker_hint,
    build_prod_images,
    docker_available,
    prod_compose_files_present,
    prod_data_root_host_path,
    prod_image_names,
    prod_stack_config_check,
    prod_stack_down,
    prod_stack_logs,
    prod_stack_ps,
    prod_stack_restart,
    prod_stack_running,
    prod_stack_service_states,
    prod_stack_up,
    readonly_prod_env,
    redis_running,
    resolve_git_short_sha,
    resolve_prod_env,
    start_docker_infra,
    stop_docker_infra,
    wait_for_minio,
    wait_for_redis,
)
from launch.gateway_manager import (
    GATEWAY_CONTAINER,
    GATEWAY_PORT,
    gateway_hmr_active,
    gateway_running,
    reload_gateway_nginx,
    start_gateway_infra,
    stop_gateway_infra,
    stop_vite_behind_gateway,
)
from launch.logging_setup import log
from launch.process_manager import ProcessManager
from launch.subprocess_utils import (
    ensure_named_volume,
    ensure_project_initialized,
    enumerate_cmdline_rows,
    hidden_kwargs,
    netstat_listening_pids,
    pid_alive,
    port_listening,
    python_executable,
    resolve_open_meteo_volume_name,
    terminate_by_cmdline_patterns,
    tree_kill_pid,
    wait_for_pattern_exit,
)


# ─── 启动命令 ────────────────────────────────────────────────────────────────
def _regenerate_catalog_seeds() -> None:
    """X1 codegen：开启/重启系统时自动刷新前端图层目录。

    后端 ``catalog_seeds/*.json`` 是图层目录唯一真源；每次启动/重启时自动重跑
    ``Tools/generate_catalog_seeds.py`` 生成 ``catalog-seeds.generated.json``，
    避免手动执行 ``npm run gen:catalog``，保证前端兜底目录与后端一致。
    失败仅告警不阻塞启动（前端运行时仍以后端 ``GET /layers`` 为准）。
    """
    script = SCRIPT_DIR / "Tools" / "generate_catalog_seeds.py"
    if not script.is_file():
        log.warn("Launcher", f"catalog codegen 脚本缺失，跳过: {script}")
        return
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            **hidden_kwargs(),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warn("Launcher", f"catalog codegen 执行异常（跳过）: {exc}")
        return
    if r.returncode != 0:
        log.warn(
            "Launcher",
            f"catalog codegen 失败（跳过）: {(r.stderr or r.stdout).strip()}",
        )
        return
    log.ok("Launcher", "已自动刷新图层目录 catalog-seeds.generated.json")


def cmd_start(args: argparse.Namespace) -> int:
    """启动 CGDA 服务（全部或指定组件）。"""
    component = args.component
    if component is None:
        component = "all"

    if getattr(args, "frontend_only", False) and component == "all":
        component = "frontend"

    # 三态解析（bare / dev / prod）先于任何副作用（缓存清理/建目录）：
    # 参数非法时不应已经动过用户环境。只有全量启动才区分形态，
    # 单组件命令语义保持不变，避免把历史脚本与肌肉记忆带偏。
    mode = _resolve_mode(args)
    if mode is None:
        return 2
    if mode == MODE_PROD and component != "all":
        log.error(
            "Launcher",
            f"--mode prod 只能用于全量启动（start all）；收到组件: {component}",
        )
        log.info(
            "Launcher",
            "  交付态请用: launch.py deploy up    或    launch.py start --mode prod",
        )
        return 2

    if not getattr(args, "_cache_prepare_done", False):
        apply_prepare_from_args(args, component)
        args._cache_prepare_done = True

    ensure_project_initialized()

    if mode == MODE_PROD:
        # 交付态源码在镜像内，catalog codegen 属于宿主构建期步骤，不在这里跑。
        return _start_all_prod(args)

    _regenerate_catalog_seeds()

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
        # P2-2：检查 wait_for_redis 返回值并探测 MinIO（docker 组件仅警告，不阻塞）
        if not wait_for_redis(max_wait=30):
            log.warn("Launcher", "Redis 未就绪，后续 fastapi/worker 启动会失败")
        wait_for_minio(max_wait=30)
        log.ok("Launcher", "Docker 基础设施已启动（不进入监控循环）")
        return 0

    if component == "backend":
        return _start_backend_app_processes(args)

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
        if gateway_running():
            log.info("Launcher", "检测到 Nginx Gateway 占用 :5175，先停止 gateway")
            stop_gateway_infra()
        pm.start_frontend()
        time.sleep(2)
        pm.save_pids(merge=True)
        log.ok("Launcher", "前端已启动（不进入监控循环）")
        return 0

    if component == "gateway":
        # 同域入口：默认静态 dist；``--vite`` 时切 HMR 剖面并拉起本机 Vite :5174
        import urllib.request

        try:
            req = urllib.request.Request("http://127.0.0.1:8000/health")
            with urllib.request.urlopen(req, timeout=3) as resp:
                api_ok = resp.status == 200
        except Exception:
            api_ok = False
        if not api_ok:
            log.warn(
                "Gateway",
                "FastAPI :8000 未响应；网关可启动但 API 反代会失败。"
                " 建议先: launch.py start docker && launch.py start fastapi",
            )
        use_hmr = bool(getattr(args, "vite", False))
        if not start_gateway_infra(
            rebuild_frontend=bool(getattr(args, "rebuild_frontend", False)),
            hmr=use_hmr,
        ):
            return 1
        if use_hmr:
            pm = ProcessManager(
                debug=args.debug,
                frontend_port=args.frontend_port,
                behind_gateway=True,
            )
            pm.start_frontend()
            time.sleep(2)
            pm.save_pids(merge=True)
            log.ok(
                "Launcher",
                f"Nginx Gateway HMR 已启动（入口 http://localhost:{GATEWAY_PORT}，"
                f"Vite :{VITE_BEHIND_GATEWAY_PORT}）",
            )
        else:
            log.ok(
                "Launcher",
                f"Nginx Gateway 已启动（http://localhost:{GATEWAY_PORT}，不进入监控循环）",
            )
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
        "可用组件: all, docker, fastapi, beat, worker, worker:<name>, frontend, gateway, backend",
    )
    return 1


# ─── 三态与交付态（形态 B）───────────────────────────────────────────────────
# 只读 deploy 动作：不构建、不起栈、不落盘，允许在缺 CGDA_* 变量时用占位值放行。
_READONLY_DEPLOY_ACTIONS = frozenset({"ps", "logs", "down", "config"})


def _resolve_mode(args: argparse.Namespace) -> str | None:
    """解析 ``--mode``，并完成兼容与互斥校验。

    兼容规则（保证历史命令行行为不变）：
      · 不给 ``--mode``：``--vite`` 仍表示开发态，其余 = 裸机态（历史上唯一形态）。
      · ``--mode dev``：等价于 ``--vite``（自动补齐，便于只用一种心智模型）。
      · ``--mode prod``：与 ``--vite`` / ``--no-docker`` 互斥。

    返回 None 表示校验失败（错误已打印），调用方应返回退出码 2。
    """
    raw = (getattr(args, "mode", None) or "").strip().lower()
    if not raw:
        return MODE_DEV if getattr(args, "vite", False) else DEFAULT_MODE
    if raw not in VALID_MODES:
        log.error("Launcher", f"未知 --mode: {raw}（可选: {'/'.join(VALID_MODES)}）")
        return None
    if raw == MODE_DEV:
        args.vite = True
    if raw == MODE_PROD:
        if getattr(args, "vite", False):
            log.error(
                "Launcher",
                "--mode prod 与 --vite 互斥：交付态用镜像内已构建的静态 dist，无 HMR",
            )
            return None
        if getattr(args, "no_docker", False):
            log.error(
                "Launcher",
                "--mode prod 不能与 --no-docker 同用：交付态本身就是容器栈",
            )
            return None
    return raw


def _resolve_prod_env_or_fail(
    args: argparse.Namespace, *, placeholders: bool = False
) -> dict[str, str] | None:
    """取交付态 compose 环境；缺必填项时打印可照抄的修复指引并返回 None。

    ``placeholders=True``（只读动作）用占位值补齐，避免 ``deploy ps`` /
    ``deploy down`` 这类命令被 compose 的 fail-closed 插值挡住。
    """
    env, missing = resolve_prod_env(
        tag=getattr(args, "tag", None),
        data_root=getattr(args, "data_root", None),
    )
    if not missing:
        return env
    if placeholders:
        return readonly_prod_env()
    log.error("Launcher", f"交付态缺少必填变量: {', '.join(missing)}")
    log.info("Launcher", f"  方式一：写入 {BACKEND_DIR / '.env'}")
    log.info("Launcher", f"    CGDA_TAG={resolve_git_short_sha()}")
    log.info("Launcher", "    CGDA_DATA_ROOT=D:/geo      # Windows 用盘符形式，勿写 /d/geo")
    log.info(
        "Launcher",
        "  方式二：命令行传入  launch.py deploy up --tag <sha> --data-root D:/geo",
    )
    return None


def _prod_host_conflict(mode_label: str) -> str | None:
    """交付态与自己/裸机态的端口冲突探测（返回冲突描述，无冲突返回 None）。"""
    if prod_stack_running():
        # 同形态重复启动是幂等的（up -d），不算冲突。
        return None
    if port_listening("127.0.0.1", BACKEND_API_PORT):
        return (
            f"端口 {BACKEND_API_PORT} 已被占用（疑似{mode_label} FastAPI 在运行）。"
            "裸机与交付态互斥，请先 stop.bat / launch.py stop"
        )
    if port_listening("127.0.0.1", DEFAULT_FRONTEND_PORT):
        return (
            f"端口 {DEFAULT_FRONTEND_PORT} 已被占用（疑似{mode_label} Nginx Gateway 在运行）。"
            "请先 stop.bat / launch.py stop"
        )
    return None


def _print_prod_summary(env: dict[str, str]) -> None:
    backend_img, web_img = prod_image_names(env)
    log.banner("交付态启动完成（全量容器化）")
    log.ok("Docker", "容器栈已就绪:")
    log.info(
        "Launcher",
        f"  Frontend:  http://localhost:{DEFAULT_FRONTEND_PORT}"
        f"  [{PROD_GATEWAY_CONTAINER}]",
    )
    log.info("Launcher", f"  FastAPI:   http://127.0.0.1:{BACKEND_API_PORT}（仅回环，排障直连）")
    log.info("Launcher", f"  API Docs:  http://localhost:{DEFAULT_FRONTEND_PORT}/docs")
    log.info("Launcher", f"  镜像:      {backend_img} / {web_img}")
    log.info("Launcher", "  查看状态:  launch.py deploy ps    （或 docker compose -p cgda ps）")
    log.info("Launcher", "  查看日志:  launch.py deploy logs backend")
    log.info("Launcher", "  停止:      launch.py deploy down   （保留卷）")
    log.info(
        "Launcher",
        "  提示: 容器带 restart: unless-stopped，无需监控循环；改码需重建镜像",
    )


def _start_all_prod(args: argparse.Namespace) -> int:
    """交付态（形态 B）：校验 → 构建镜像 → 拉起容器栈（不进入监控循环）。"""
    log.banner("CGDA 交付态启动（全量容器化 / --mode prod）")

    if not prod_compose_files_present():
        log.error("Launcher", f"交付态编排文件缺失（应在 {BACKEND_DIR}）:")
        log.error("Launcher", "  docker-compose.yml（基础设施）+ compose.prod.yml（应用层）")
        return 1

    if not docker_available():
        hint = _windows_docker_hint() if IS_WINDOWS else "请先启动 Docker Engine"
        log.error("Docker", f"Docker 未运行或未安装，{hint}")
        return 1

    env = _resolve_prod_env_or_fail(args)
    if env is None:
        return 2

    root = prod_data_root_host_path(env)
    if root is None or not root.exists():
        log.error("Launcher", f"宿主数据根不存在: {root}")
        log.info(
            "Launcher",
            "  容器化前请先建好数据目录（Docker 会建目录，但不会替你准备数据）",
        )
        return 2

    conflict = _prod_host_conflict("裸机")
    if conflict:
        log.error("Launcher", conflict)
        return 1

    ok, err = prod_stack_config_check(env=env)
    if not ok:
        log.error("Docker", f"compose 配置校验失败:\n{err}")
        log.info("Launcher", "  排查：Code/backend/.env 中 CGDA_* 是否齐全、数据根路径是否合法")
        return 1

    if not getattr(args, "no_build", False):
        if not build_prod_images(env=env):
            return 1
    else:
        log.warn("Launcher", "--no-build：跳过镜像构建，直接使用已有 ${CGDA_TAG} 镜像")

    if not prod_stack_up(env=env):
        return 1

    # 端口可达性复核（容器健康检查之外的最终确认）
    if not port_listening("127.0.0.1", DEFAULT_FRONTEND_PORT):
        log.warn(
            "Launcher",
            f"网关 :{DEFAULT_FRONTEND_PORT} 暂未监听（容器可能仍在启动）。"
            "稍后用 launch.py deploy ps 复核",
        )
    _print_prod_summary(env)
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    """交付态（形态 B）运维入口：build / up / down / restart / ps / logs / config。

    与 ``start --mode prod`` 的分工：
      · ``deploy build`` 只构建镜像，不起栈（离线分发/预构建场景）
      · ``deploy up``    = 校验 + 构建（可 --no-build）+ 起栈
      · 其余动作是日常运维（看状态、跟随日志、停栈）
    """
    action = (getattr(args, "deploy_action", None) or "up").strip().lower()

    if not prod_compose_files_present():
        log.error("Launcher", f"交付态编排文件缺失（应在 {BACKEND_DIR}）")
        return 1
    if not docker_available():
        hint = _windows_docker_hint() if IS_WINDOWS else "请先启动 Docker Engine"
        log.error("Docker", f"Docker 未运行或未安装，{hint}")
        return 1

    # 只读动作（ps/logs/down/config）不参与构建/起栈，用占位值放行 compose 插值；
    # 会真正落盘或拉镜像的动作（build/up/restart）仍强制要求真实 CGDA_TAG/DATA_ROOT。
    env = _resolve_prod_env_or_fail(
        args, placeholders=action in _READONLY_DEPLOY_ACTIONS
    )
    if env is None:
        return 2

    if action == "ps":
        text = prod_stack_ps(env=env)
        log.banner("交付态容器状态")
        if text:
            for line in text.splitlines():
                log.info("Status", f"  {line}")
        else:
            log.warn("Status", "交付态栈未在运行（或项目 cgda 不存在）")
        return 0

    if action == "logs":
        # 注意：不要用 `log` 作局部变量名——会遮蔽模块级 logger 对象。
        extra_services = list(getattr(args, "services", None) or [])
        target = extra_services[0] if extra_services else None
        prod_stack_logs(
            target, tail=int(getattr(args, "lines", 80) or 80), env=env
        )
        return 0

    if action == "config":
        ok, err = prod_stack_config_check(env=env)
        if ok:
            log.ok("Docker", "compose 配置校验通过（docker compose config）")
            return 0
        log.error("Docker", f"compose 配置校验失败:\n{err}")
        return 1

    if action == "build":
        return 0 if build_prod_images(env=env) else 1

    if action == "down":
        remove_volumes = bool(getattr(args, "volumes", False))
        prod_stack_down(remove_volumes=remove_volumes, env=env)
        if remove_volumes:
            log.warn(
                "Docker",
                "已同时移除命名卷（-v）：MinIO 产物 / Redis 队列 / beat 调度库均已删除",
            )
        return 0

    if action == "restart":
        conflict = _prod_host_conflict("裸机")
        if conflict:
            log.error("Launcher", conflict)
            return 1
        if not prod_stack_restart(env=env, build=not getattr(args, "no_build", False)):
            return 1
        _print_prod_summary(env)
        return 0

    if action == "up":
        root = prod_data_root_host_path(env)
        if root is None or not root.exists():
            log.error("Launcher", f"宿主数据根不存在: {root}")
            return 2
        conflict = _prod_host_conflict("裸机")
        if conflict:
            log.error("Launcher", conflict)
            return 1
        ok, err = prod_stack_config_check(env=env)
        if not ok:
            log.error("Docker", f"compose 配置校验失败:\n{err}")
            return 1
        # 兼容裸机态写法 worker:weather → compose 服务名 worker-weather
        services = tuple(
            s.replace("worker:", "worker-", 1)
            for s in (getattr(args, "services", None) or ())
        )
        unknown = [s for s in services if s not in PROD_APP_SERVICES]
        if unknown:
            log.error("Launcher", f"未知交付态服务: {', '.join(unknown)}")
            log.info("Launcher", f"  可选: {', '.join(PROD_APP_SERVICES)}")
            return 2
        if not prod_stack_up(
            env=env, services=services, build=not getattr(args, "no_build", False)
        ):
            return 1
        _print_prod_summary(env)
        return 0

    log.error("Launcher", f"未知 deploy 动作: {action}")
    log.info(
        "Launcher",
        "  可用: up / down / restart / build / ps / logs / config",
    )
    return 2


def _start_all(args: argparse.Namespace) -> int:
    """启动全部服务并进入监控循环。"""
    log.banner("CGDA 一键启动")
    log.info("Launcher", f"操作系统: {sys.platform}")
    log.info("Launcher", f"Python:   {sys.executable}")
    try:
        from launch.env_python import is_running_env_python312

        if is_running_env_python312():
            log.ok("Launcher", "已使用约定运行时 Env/Python312")
        else:
            log.warn(
                "Launcher",
                "当前解释器不是 Env/Python312；本地联调请改用 start.bat 或 Env\\Python312\\python.exe",
            )
    except Exception:
        pass
    log.info("Launcher", f"后端目录: {BACKEND_DIR}")
    log.info("Launcher", f"前端目录: {FRONTEND_DIR}")
    log.info("Launcher", f"数据同步: {DATA_SYNC_DIR}")
    if args.debug:
        log.info("Launcher", "调试模式: ON（窗口可见，Celery 日志级别 DEBUG）")
    log.ok("Launcher", "初始化完成（数据目录 / data-sync .env）")

    pm = ProcessManager(
        debug=args.debug,
        frontend_port=args.frontend_port,
        behind_gateway=bool(getattr(args, "vite", False)),
    )
    pm.install_signal_handlers()

    if not args.no_docker:
        if not start_docker_infra(
            start_open_meteo=not getattr(args, "no_open_meteo", False)
        ):
            log.error("Launcher", "Docker 基础设施启动失败，终止")
            return 1
        # P2-2：此前 wait_for_redis 返回值被丢弃，Redis 未就绪仍拉起 7 worker+beat
        # 导致 crash-loop。现检查返回值 fail-fast。
        if not wait_for_redis(max_wait=30):
            log.error(
                "Launcher", "Redis 未就绪，终止启动（避免 worker/beat crash-loop）"
            )
            log.info(
                "Launcher",
                "  排查：docker logs cgda-redis；或 launch.py start docker 单独诊断",
            )
            return 1
        # P2-2：新增 MinIO 探测（warn-only，对象存储未就绪时部分功能降级但不阻塞启动）
        wait_for_minio(max_wait=30)
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
        use_vite = bool(getattr(args, "vite", False))
        if use_vite:
            # Gateway :5175 同域入口 + 本机 Vite :5174 HMR（不再互斥停 Gateway）
            if not start_gateway_infra(
                rebuild_frontend=bool(getattr(args, "rebuild_frontend", False)),
                hmr=True,
            ):
                log.error("Launcher", "Nginx Gateway HMR 启动失败，终止")
                return 1
            pm.start_frontend()
            time.sleep(3)
        else:
            if not start_gateway_infra(
                rebuild_frontend=bool(getattr(args, "rebuild_frontend", False)),
                hmr=False,
            ):
                log.error("Launcher", "Nginx Gateway 启动失败，终止")
                return 1
            time.sleep(2)

    pm.save_pids()

    log.banner("启动完成")
    log.ok("Launcher", "所有服务已启动:")
    if not args.frontend_only:
        log.info("Launcher", "  FastAPI:   http://127.0.0.1:8000")
        log.info("Launcher", "  API Docs:  http://127.0.0.1:8000/docs")
        log.info("Launcher", "  Workers:   7 个 Celery Worker + 1 Beat")
    if not args.no_frontend:
        if getattr(args, "vite", False):
            log.info(
                "Launcher",
                f"  Frontend:  http://localhost:{GATEWAY_PORT}  [Gateway + Vite HMR]",
            )
            log.info(
                "Launcher",
                f"  Vite:      http://127.0.0.1:{VITE_BEHIND_GATEWAY_PORT}（经网关反代）",
            )
        else:
            log.info(
                "Launcher",
                f"  Frontend:  http://localhost:{GATEWAY_PORT}  [Nginx Gateway 静态]",
            )
            log.info(
                "Launcher",
                "  静态:     Code/frontend/dist（改前端后需 --rebuild-frontend 或 npm run build）",
            )
            log.info(
                "Launcher",
                "  HMR:      launch.py start --vite（同域入口不变）",
            )
    log.info("Launcher", f"  日志目录:  {LOG_DIR}")
    log.info("Launcher", "  停止方式:  python launch.py stop  或  Ctrl+C")
    log.info("Launcher", "  配置热重载: python launch.py reload gateway")
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
def cmd_stop(args: argparse.Namespace | None = None) -> int:
    """停止全部 CGDA 服务，或仅停止 gateway。"""
    component = getattr(args, "component", None) if args is not None else None
    if component in (None, "", "all"):
        component = None
    if component == "gateway":
        log.banner("停止 Nginx Gateway")
        stop_vite_behind_gateway()
        stop_gateway_infra()
        log.ok("Stop", "Gateway 已停止（未执行 flush/clean-cache）")
        return 0
    if component is not None:
        log.error("Stop", f"未知组件: {component}（stop 支持: 全部 / gateway）")
        return 1

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
            f"vite --port {VITE_BEHIND_GATEWAY_PORT}",
        ]
    )

    time.sleep(1)
    # 交付态（-p cgda）与裸机态（-p backend / -p gateway）是两套 compose 项目，
    # 各自的 down 不会互相清理；这里两条路径都走一遍，按存在性跳过。
    # 顺序：先交付态（它占 5175 + 8000），再裸机网关与基础设施。
    if prod_stack_running():
        log.info("Stop", "检测到交付态容器栈（项目 cgda），一并停止...")
        prod_stack_down()
    stop_gateway_infra()
    stop_docker_infra()
    log.ok("Stop", "所有服务已停止（未执行 flush/clean-cache；下次 start/restart 会按矩阵自动 clean）")
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
        (GATEWAY_CONTAINER, "Nginx Gateway"),
    ]
    for cid, label in containers:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", cid],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_kwargs(),
        )
        state = r.stdout.strip() if r.returncode == 0 else "未运行"
        icon = "✓" if state == "running" else "✗"
        log.info("Status", f"  {icon} {label:14s} ({cid}): {state}")

    # 交付态（形态 B）应用层：只在项目 cgda 存在时展示，避免裸机态刷一堆噪音。
    prod_rows = prod_stack_service_states()
    if prod_rows:
        log.info("Status", f"交付态容器栈（项目 {PROD_PROJECT}）:")
        for name, state in prod_rows:
            icon = "✓" if state == "running" else "✗"
            log.info("Status", f"  {icon} {name:18s}: {state}")
    else:
        log.info("Status", "  交付态容器栈（项目 cgda）: 未部署 / 未运行")

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

    gw_up = gateway_running()
    try:
        req = urllib.request.Request(f"http://localhost:{DEFAULT_FRONTEND_PORT}/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            fe_ok = resp.status == 200
    except Exception:
        fe_ok = False
    icon = "✓" if fe_ok else "✗"
    if gw_up and gateway_hmr_active():
        fe_mode = "Gateway + Vite HMR"
    elif gw_up:
        fe_mode = "Nginx Gateway"
    elif fe_ok:
        fe_mode = "Vite"
    else:
        fe_mode = "未响应"
    log.info(
        "Status",
        f"  {icon} Frontend (http://localhost:{DEFAULT_FRONTEND_PORT}):  "
        f"{'就绪' if fe_ok else '未响应'} [{fe_mode}]",
    )
    if gw_up and gateway_hmr_active():
        vite_ok = port_listening(VITE_BEHIND_GATEWAY_PORT)
        icon = "✓" if vite_ok else "✗"
        log.info(
            "Status",
            f"  {icon} Vite HMR  (http://127.0.0.1:{VITE_BEHIND_GATEWAY_PORT}): "
            f"{'监听中' if vite_ok else '未监听'}",
        )

    log.info(
        "Status",
        "缓存约定: start/restart 默认按组件清理本地编译缓存（--no-clean-cache 可跳过）；"
        "Redis/天气仅 launch.py flush；手册 Docs/07-工程保障/联调缓存与生效边界.md",
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
# backend 进程面的命令行清扫特征（父进程：start_*.py）与 API 端口。
BACKEND_STOP_PATTERNS = [
    "start_celery_worker.py",
    "start_celery_beat.py",
    "start_fastapi.py",
]
BACKEND_API_PORT = 8000


def _iter_backend_pid_file_entries() -> list[tuple[str, int]]:
    """读取 PID 文件中的 backend 条目（worker-* / fastapi / beat）。"""
    if not PID_FILE.exists():
        return []
    try:
        pids = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(pids, dict):
        return []
    out: list[tuple[str, int]] = []
    for name, pid in pids.items():
        if not (
            str(name).startswith("worker-")
            or str(name) in {"fastapi", "beat", "celery-beat"}
        ):
            continue
        try:
            out.append((str(name), int(pid)))
        except (ValueError, TypeError):
            continue
    return out


def _terminate_cgda_spawn_children() -> int:
    """树杀 CGDA Python multiprocessing spawn 孤儿子进程。

    uvicorn 多 worker 与 celery pool 的子进程 cmdline 是
    ``python -c "from multiprocessing.spawn import spawn_main ..."``，
    不含 ``start_*.py`` 路径；父进程被单独击杀（Windows 下 ``os.kill``
    等效 TerminateProcess，不杀树）后它们会孤儿化，继续占用 8000 端口
    或消费队列——即世代堆积的残余形态。识别标记：spawn_main +
    Env/Python312 解释器路径。
    """
    py_marker = python_executable().lower()
    if not py_marker:
        return 0
    ok, rows = enumerate_cmdline_rows()
    if not ok:
        return 0
    killed = 0
    for pid, cmdline in rows:
        if pid == os.getpid():
            continue
        cl = cmdline.lower()
        if "spawn_main" in cl and py_marker in cl:
            tree_kill_pid(pid)
            killed += 1
    return killed


def _kill_port_owner_if_backend(port: int) -> bool:
    """端口属主可识别为 CGDA 后端进程时树杀；无关进程不动，仅告警。"""
    if not IS_WINDOWS:
        try:
            subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (FileNotFoundError, OSError):
            log.warn("Stop", "fuser 不可用，无法清除端口属主")
            return False

    pids = netstat_listening_pids(port)
    if not pids:
        return False
    ok, rows = enumerate_cmdline_rows()
    cmdlines = dict(rows) if ok else {}
    py_marker = python_executable().lower()
    killed_any = False
    identified_any = False
    for pid in pids:
        cl = cmdlines.get(pid, "")
        cl_l = cl.lower()
        is_cgda = (
            "start_fastapi.py" in cl_l
            or "uvicorn" in cl_l
            or "app.main" in cl_l
            or str(BACKEND_DIR).lower() in cl_l
            or (bool(py_marker) and py_marker in cl_l)
        )
        if is_cgda:
            log.warn("Stop", f"树杀端口 {port} 属主 (pid={pid})")
            tree_kill_pid(pid)
            killed_any = True
            identified_any = True
        elif cl:
            identified_any = True
            log.error(
                "Stop",
                f"端口 {port} 被疑似无关进程占用，不自动击杀 (pid={pid}): {cl[:160]}",
            )
    if not identified_any:
        log.error(
            "Stop",
            f"端口 {port} 有监听但属主无法识别（进程枚举失败），"
            f"需手工排查: netstat -ano | findstr :{port}",
        )
    return killed_any


def _verify_backend_stop() -> bool:
    """清扫后死亡验证：无匹配进程存活 + PID 文件条目全死 + 端口可绑定。

    存活时升级击杀一轮；仍不干净则返回 False（调用方应拒绝启动新世代，
    否则复现 2026-08-16 的世代堆叠）。
    """
    survivors = wait_for_pattern_exit(BACKEND_STOP_PATTERNS, timeout=10.0)
    if survivors is None:
        log.warn("Stop", "进程枚举不可用，无法验证命令行清扫结果")
        # 枚举失败兜底：PID 文件条目逐个树杀后按 pid_alive 复查
        alive = [
            pid for _name, pid in _iter_backend_pid_file_entries() if pid_alive(pid)
        ]
        for pid in alive:
            tree_kill_pid(pid)
        time.sleep(1.0)
        still = [
            pid for _name, pid in _iter_backend_pid_file_entries() if pid_alive(pid)
        ]
        if still:
            log.error("Stop", f"PID 文件兜底击杀后仍存活: {still}")
            return False
    elif survivors:
        log.warn(
            "Stop", f"{len(survivors)} 个 backend 进程未退出，升级强制击杀: {survivors}"
        )
        terminate_by_cmdline_patterns(BACKEND_STOP_PATTERNS)
        _terminate_cgda_spawn_children()
        survivors = wait_for_pattern_exit(BACKEND_STOP_PATTERNS, timeout=5.0)
        if survivors:
            log.error(
                "Stop",
                f"强制击杀后仍存活（可能需要管理员权限）: {survivors}",
            )
            return False

    if port_listening("127.0.0.1", BACKEND_API_PORT):
        log.warn("Stop", f"端口 {BACKEND_API_PORT} 仍被占用，尝试识别并清除属主")
        _kill_port_owner_if_backend(BACKEND_API_PORT)
        time.sleep(1.0)
        if port_listening("127.0.0.1", BACKEND_API_PORT):
            log.error(
                "Stop",
                f"端口 {BACKEND_API_PORT} 仍被占用，重启中止以免世代堆叠",
            )
            return False
    return True


def _stop_backend_app_processes() -> bool:
    """仅停止 FastAPI / Celery worker / Beat（不动 Docker、Vite、gateway）。

    返回是否**验证清洁**（无匹配进程存活且 8000 端口可绑定）。

    三层清扫 + 死亡验证（对应 2026-08-16 世代堆积事故）：
    1. 命令行模式清扫：taskkill /T /F 整树击杀，覆盖 PID 文件未收录的
       旧世代；枚举失败（PATH 缺 System32 等）会被哨兵识别而非静默 no-op。
    2. PID 文件条目 SIGTERM 兜底（os.kill 走 Win32 API，不依赖 PATH）。
    3. spawn 孤儿子进程清除 + 死亡验证 + 端口属主核对（见
       ``_verify_backend_stop``）。
    """
    terminate_by_cmdline_patterns(BACKEND_STOP_PATTERNS)

    for name, pid in _iter_backend_pid_file_entries():
        try:
            os.kill(pid, signal.SIGTERM)
            log.info("Stop", f"已发送 SIGTERM 到 {name} (pid={pid})")
        except (ProcessLookupError, PermissionError, ValueError, OSError):
            log.debug("Stop", f"{name} (pid={pid}) 已不存在")

    _terminate_cgda_spawn_children()
    clean = _verify_backend_stop()

    # Drop stale PID entries for backend procs if present
    if PID_FILE.exists():
        try:
            pids = json.loads(PID_FILE.read_text(encoding="utf-8"))
            if isinstance(pids, dict):
                backend_names = {
                    name for name, _pid in _iter_backend_pid_file_entries()
                }
                keep = {
                    name: pid for name, pid in pids.items() if name not in backend_names
                }
                if keep:
                    PID_FILE.write_text(json.dumps(keep, indent=2), encoding="utf-8")
                else:
                    PID_FILE.unlink(missing_ok=True)
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    return clean


def _start_backend_app_processes(args: argparse.Namespace) -> int:
    """启动 worker → beat → fastapi（不进入监控循环）。"""
    pm = ProcessManager(debug=args.debug, frontend_port=args.frontend_port)
    # 2026-08-25 自愈：Redis 不可达时自动拉起 Docker 栈（幂等）——
    # 此前仅 warn 后照常启动，broker 缺失下 worker 全部 crash-loop /
    # 任务派发 500（「任务长期卡排队中」根因之一）。
    if not redis_running():
        log.warn("Launcher", "Redis 未运行，自动拉起 Docker 基础设施（自愈）...")
        if start_docker_infra(
            start_open_meteo=not getattr(args, "no_open_meteo", False)
        ):
            wait_for_redis(max_wait=30)
            wait_for_minio(max_wait=30)
        else:
            log.error(
                "Launcher",
                "Docker 基础设施拉起失败；worker/beat/fastapi 可能失败"
                "（排查: docker ps / launch.py start docker）",
            )
    pm.start_celery_workers()
    pm.start_celery_beat()
    pm.start_fastapi()
    ready = pm.wait_for_fastapi(max_wait=45)
    fastapi_proc = pm.processes.get("fastapi")
    if ready and fastapi_proc is not None and fastapi_proc.poll() is not None:
        log.error(
            "Launcher",
            "端口 8000 已响应但本次启动的 FastAPI 进程已退出——"
            "疑似旧世代僵尸进程仍在占用端口，请排查 start_fastapi 进程",
        )
        return 1
    pm.save_pids(merge=True)
    log.ok("Launcher", "backend（worker+beat+fastapi）已启动")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """重启 CGDA 服务（全部或指定组件）。

    ``backend``：仅重启 FastAPI + Worker + Beat，保留 Docker / Gateway / Vite。
    ``--mode prod``：交付态重建镜像并 ``up -d --force-recreate``（不进入监控循环）。
    """
    component = getattr(args, "component", None) or "all"

    # 形态校验先于任何副作用（与 cmd_start 同规则）：参数非法时不动用户环境。
    mode = _resolve_mode(args)
    if mode is None:
        return 2
    if mode == MODE_PROD and component != "all":
        log.error("Launcher", f"--mode prod 只能用于全量重启；收到组件: {component}")
        return 2

    was_hmr = False
    if component in ("gateway", "all"):
        was_hmr = gateway_hmr_active()
    if not getattr(args, "_cache_prepare_done", False):
        apply_prepare_from_args(args, component, was_gateway_hmr=was_hmr)
        args._cache_prepare_done = True

    # 交付态重启：镜像不可变 ⇒ 必须「重建镜像 + force-recreate」才能让代码变更生效。
    if mode == MODE_PROD:
        log.banner("重启交付态（全量容器化）")
        if not prod_compose_files_present() or not docker_available():
            log.error("Launcher", "交付态编排文件缺失或 Docker 未就绪")
            return 1
        env = _resolve_prod_env_or_fail(args)
        if env is None:
            return 2
        conflict = _prod_host_conflict("裸机")
        if conflict:
            log.error("Launcher", conflict)
            return 1
        if not prod_stack_restart(env=env, build=not getattr(args, "no_build", False)):
            return 1
        _print_prod_summary(env)
        return 0

    if component == "backend":
        log.banner("重启 backend（FastAPI + Worker + Beat）")
        ensure_project_initialized()
        # 2026-08-25 Redis 反复"挂掉"根因修复：restart gateway/全量 restart 走
        # cmd_stop() 会 stop_docker_infra() 停掉 Redis/MinIO；且 restart backend
        # 从不检查 Redis——worker 在 broker 缺失下启动 → 任务派发 500/卡 accepted。
        # 自愈：Redis 不可达时自动拉起 Docker 栈（compose up -d 幂等）。
        if not redis_running():
            log.warn(
                "Restart", "Redis 未运行，自动拉起 Docker 基础设施（自愈）..."
            )
            if not start_docker_infra(
                start_open_meteo=not getattr(args, "no_open_meteo", False)
            ):
                log.error("Restart", "Docker 基础设施拉起失败，继续重启（worker 将 crash-loop 重连）")
            else:
                wait_for_redis(max_wait=30)
                wait_for_minio(max_wait=30)
        clean = _stop_backend_app_processes()
        if not clean:
            log.error(
                "Restart",
                "旧 backend 进程未清扫干净（仍存活或端口被占），已中止重启以防世代堆叠",
            )
            log.info(
                "Restart",
                f"  排查: netstat -ano | findstr :{BACKEND_API_PORT}；"
                "任务管理器搜索 start_fastapi / start_celery / spawn_main",
            )
            log.info(
                "Restart",
                "  清理后重试: Env\\Python312\\python.exe launch.py restart backend",
            )
            return 1
        _regenerate_catalog_seeds()
        time.sleep(2)
        return _start_backend_app_processes(args)

    if component == "fastapi":
        # 2026-08-25 修复：此前 restart fastapi 落入全量分支（cmd_stop 停 Docker
        # 栈后仅 start fastapi 不清旧进程）——新旧进程共存同端口，请求随机打到
        # 旧进程（代码更新后行为分裂，本日 NSIDC/GLDAS access_mode 排查实证）。
        # 语义收敛：restart fastapi = 完整 backend 清扫+重启（worker/beat 也需
        # 消费新代码），且不动 Docker/gateway。
        log.banner("重启 backend（FastAPI + Worker + Beat）")
        ensure_project_initialized()
        if not redis_running():
            log.warn("Restart", "Redis 未运行，自动拉起 Docker 基础设施（自愈）...")
            if not start_docker_infra(
                start_open_meteo=not getattr(args, "no_open_meteo", False)
            ):
                log.error(
                    "Restart", "Docker 基础设施拉起失败，继续重启（worker 将 crash-loop 重连）"
                )
            else:
                wait_for_redis(max_wait=30)
                wait_for_minio(max_wait=30)
        clean = _stop_backend_app_processes()
        if not clean:
            log.error(
                "Restart", "旧 backend 进程未清扫干净，已中止重启以防世代堆叠"
            )
            return 1
        _regenerate_catalog_seeds()
        time.sleep(2)
        return _start_backend_app_processes(args)

    if component == "gateway":
        # 2026-08-25 修复：此前 restart gateway 落入全量分支 → cmd_stop() 停掉
        # Docker 栈（Redis/MinIO）后只重启 gateway 不恢复 Docker——Redis 反复
        # "挂掉"的根因。gateway 重启应精准：只 stop/start gateway 容器。
        use_hmr = bool(getattr(args, "vite", False))
        log.banner(
            "重启 gateway（Nginx"
            + (" + Vite HMR" if use_hmr else "")
            + "，不动 Docker 基础设施/backend）"
        )
        if use_hmr or was_hmr:
            stop_vite_behind_gateway()
        stop_gateway_infra()
        time.sleep(1)
        if not start_gateway_infra(
            rebuild_frontend=bool(getattr(args, "rebuild_frontend", False)),
            hmr=use_hmr,
        ):
            log.error("Restart", "Nginx Gateway 重启失败")
            return 1
        if use_hmr:
            pm = ProcessManager(
                debug=getattr(args, "debug", False),
                frontend_port=getattr(args, "frontend_port", DEFAULT_FRONTEND_PORT),
                behind_gateway=True,
            )
            pm.start_frontend()
            time.sleep(2)
            pm.save_pids(merge=True)
        log.ok("Restart", "Gateway 已重启")
        return 0

    log.banner("重启 CGDA 服务")
    cmd_stop()
    time.sleep(2)
    # prepare 已在本函数入口执行；委托 start 时勿再清一遍
    return cmd_start(args)


def cmd_reload(args: argparse.Namespace) -> int:
    """热重载指定组件配置（当前仅 gateway → nginx -s reload）。"""
    component = getattr(args, "component", None) or "gateway"
    if component != "gateway":
        log.error("Reload", f"未知组件: {component}（reload 仅支持 gateway）")
        return 1
    log.banner("热重载 Nginx Gateway 配置")
    if not reload_gateway_nginx():
        return 1
    return 0


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

    # C1 + L-1：与 API trigger / Celery Beat 共用全局互斥锁（owner token 释放），
    # 避免 CLI 与定时同步并发跑 docker、也避免误删他人锁。
    acquire_sync_lock = None
    release_sync_lock = None
    try:
        from app.tasks.open_meteo_sync_tasks import (
            acquire_open_meteo_sync_lock,
            release_open_meteo_sync_lock,
        )

        acquire_sync_lock = acquire_open_meteo_sync_lock
        release_sync_lock = release_open_meteo_sync_lock
    except Exception as exc:
        log.warn("Sync", f"未能加载同步互斥锁（降级为不互斥）: {exc}")

    lock_token = acquire_sync_lock(domains) if acquire_sync_lock is not None else None
    if lock_token is None and acquire_sync_lock is not None:
        log.error("Sync", f"另一同步正在进行（domains={domains}），本次 CLI 同步跳过")
        return 1

    try:
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
            ok=True,
            domains=domains,
            message=f"{job} completed via launch.py",
            exit_code=0,
        )
        return 0
    finally:
        if release_sync_lock is not None:
            try:
                release_sync_lock(domains, lock_token)
            except Exception as exc:
                log.warn("Sync", f"释放同步锁失败: {exc}")


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


# ─── 编译 / Vite 缓存清理（与 flush 隔离：不碰 Redis / 天气文件缓存）──────────
def cmd_clean_cache(args: argparse.Namespace) -> int:
    """清理本地 ``__pycache__`` / ``*.pyc`` 与 Vite ``node_modules/.vite``。

    与 ``flush`` 不同：本命令**不**清空 Redis，也**不**删除天气文件缓存。
    start/restart 会按组件矩阵自动调用；亦可手动执行本命令。
    """
    dry_run = bool(getattr(args, "dry_run", False))
    do_pycache = bool(getattr(args, "pycache", False))
    do_vite = bool(getattr(args, "vite", False))
    do_all = bool(getattr(args, "all", False)) or (not do_pycache and not do_vite)
    if do_all:
        do_pycache = True
        do_vite = True
    return prepare_launch_caches(
        pycache=do_pycache, vite=do_vite, dry_run=dry_run
    )


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
            encoding="utf-8",
            errors="replace",
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
            encoding="utf-8",
            errors="replace",
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
