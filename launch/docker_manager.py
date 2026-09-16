"""Docker infrastructure management for the CGDA launcher.

Extracted from the original ``launch.py``. Owns Docker Compose lifecycle
for the backend runtime stack (Redis + MinIO + Open-Meteo API) and
Redis readiness checks.

Also owns the **交付态（形态 B / 全量容器化）** stack helpers used by
``--mode prod`` and the ``deploy`` subcommand — see
``Docs/04-执行部署/Win10-交接部署与三态启动方案.md`` §3/§4.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from launch.constants import (
    BACKEND_DIR,
    DEFAULT_IMAGE_PREFIX,
    INFRA_COMPOSE_FILE,
    IS_WINDOWS,
    PROD_COMPOSE_FILE,
    PROD_PROJECT,
)
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


def _windows_docker_hint() -> str:
    return (
        "请先以管理员身份启动 Docker Desktop，并确认引擎就绪"
        "（Windows 非管理员可能导致 launch 失败）"
    )


def start_docker_infra(*, start_open_meteo: bool = True) -> bool:
    """启动 Redis + MinIO；可选启动 backend 内的 cgda-open-meteo API。"""
    log.banner("启动 Docker 运行栈 (Redis + MinIO + Open-Meteo API)")
    if not docker_available():
        hint = _windows_docker_hint() if IS_WINDOWS else "请先启动 Docker Engine / 守护进程"
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
            encoding="utf-8",
            errors="replace",
            timeout=180,
            **hidden_kwargs(),
        )
        if r.returncode != 0:
            log.error("Docker", f"docker compose 启动失败:\n{r.stderr}")
            if IS_WINDOWS:
                log.warn("Docker", _windows_docker_hint())
            return False
    except subprocess.TimeoutExpired:
        log.error("Docker", "docker compose 启动超时（180s）")
        return False

    log.ok("Docker", "容器已启动")
    log.info("Docker", "  Redis:  redis://127.0.0.1:16379/0")
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
                encoding="utf-8",
                errors="replace",
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


def wait_for_minio(max_wait: int = 30) -> bool:
    """等待 MinIO 容器健康检查通过（P2-2：此前无 MinIO 探测）。

    用 ``docker inspect`` 读取容器 Health.Status，避免依赖 MinIO CLI/端口可达性
    （端口绑定回环后仍可经 docker inspect 探测）。
    """
    log.info("MinIO", f"等待 MinIO 就绪（最多 {max_wait}s）...")
    for _ in range(max_wait):
        try:
            r = subprocess.run(
                [
                    "docker", "inspect",
                    "-f", "{{.State.Health.Status}}",
                    "cgda-minio",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                **hidden_kwargs(),
            )
            if r.returncode == 0 and r.stdout.strip() == "healthy":
                log.ok("MinIO", "MinIO 就绪")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        time.sleep(1)
    log.warn("MinIO", f"MinIO 未在 {max_wait}s 内就绪，继续启动（可能影响对象存储）")
    return False


def redis_running() -> bool:
    """快速检查 Redis 是否运行（3s 超时）。"""
    try:
        r = subprocess.run(
            ["docker", "exec", "cgda-redis", "redis-cli", "ping"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            **hidden_kwargs(),
        )
        return r.returncode == 0 and "PONG" in r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 交付态（形态 B / 全量容器化）——  由 ``--mode prod`` / ``deploy`` 子命令使用
#
# 编排 = 基础设施 compose + compose.prod.yml 合并（缺一不可）：
#   docker compose -p cgda -f docker-compose.yml -f compose.prod.yml ...
# 两个 ``-f`` 都传**文件名**且 cwd=Code/backend，使 compose 项目目录恒为
# Code/backend —— 这样 compose.prod.yml 里的相对卷路径（./.env、
# ./deployment.config.json、../infra/gateway/maintenance）才能真正解析到预期位置。
# ══════════════════════════════════════════════════════════════════════════════


def read_backend_env_file() -> dict[str, str]:
    """极简解析 ``Code/backend/.env``（仅 launcher 侧校验/取默认值用）。

    不引入 python-dotenv：launch/ 各模块刻意不依赖后端依赖树。只处理
    ``KEY=VALUE`` 单行、忽略注释与空行、剥掉成对引号；不做变量展开。
    """
    path = BACKEND_DIR / ".env"
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_git_short_sha() -> str:
    """当前仓库短 sha；不可用时回退 ``local``（镜像 tag 仍可用，只是不可追溯）。"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(BACKEND_DIR.parent.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            **hidden_kwargs(),
        )
        sha = (r.stdout or "").strip()
        if r.returncode == 0 and sha:
            return sha
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "local"


def resolve_prod_env(
    *, tag: str | None = None, data_root: str | None = None
) -> tuple[dict[str, str], list[str]]:
    """构造 compose 进程环境，并返回缺失的必填项。

    优先级：显式参数 > 进程环境变量 > ``Code/backend/.env``。
    返回值第二项非空表示缺必填项，调用方应报错并给出修复指引。
    只做「是否为空」校验；路径是否合法由 compose / 容器启动时兜底。
    """
    file_env = read_backend_env_file()
    env = os.environ.copy()

    resolved_tag = (tag or env.get("CGDA_TAG") or file_env.get("CGDA_TAG") or "").strip()
    resolved_root = (
        data_root
        or env.get("CGDA_DATA_ROOT")
        or file_env.get("CGDA_DATA_ROOT")
        or ""
    ).strip()

    if resolved_tag:
        env["CGDA_TAG"] = resolved_tag
    if resolved_root:
        env["CGDA_DATA_ROOT"] = resolved_root

    missing: list[str] = []
    if not resolved_tag:
        missing.append("CGDA_TAG")
    if not resolved_root:
        missing.append("CGDA_DATA_ROOT")
    return env, missing


def prod_compose_cmd(*extra: str) -> list[str]:
    """拼装交付态 compose 命令前缀（未含 cwd，调用方补 BACKEND_DIR）。"""
    return [
        "docker",
        "compose",
        "-p",
        PROD_PROJECT,
        "-f",
        INFRA_COMPOSE_FILE.name,
        "-f",
        PROD_COMPOSE_FILE.name,
        *extra,
    ]


# compose.prod.yml 用 ``${CGDA_TAG:?}`` / ``${CGDA_DATA_ROOT:?}`` 做 fail-closed：
# 这两个卷/镜像变量若为空，起栈会挂到错误位置或拉到不存在的镜像。但 compose 的
# 插值发生在**解析期**，连 ``ps`` / ``logs`` / ``down`` 这类只读命令也会被卡住。
# 因此只读动作用本函数填占位值放行——占位值不会参与任何构建/起栈，
# 真正需要真实值的动作（build/up/restart）仍由 launcher 侧强制校验。
_READONLY_PLACEHOLDERS: dict[str, str] = {
    "CGDA_TAG": "local",
    "CGDA_DATA_ROOT": "/data/geo",
}


def readonly_prod_env() -> dict[str, str]:
    """给只读 compose 动作（ps/logs/down/config）用的容错环境。"""
    env = os.environ.copy()
    file_env = read_backend_env_file()
    for key, placeholder in _READONLY_PLACEHOLDERS.items():
        value = (env.get(key) or file_env.get(key) or "").strip()
        env[key] = value or placeholder
    return env


def prod_compose_files_present() -> bool:
    return INFRA_COMPOSE_FILE.is_file() and PROD_COMPOSE_FILE.is_file()


def _run_prod_compose(
    *extra: str,
    env: dict[str, str] | None = None,
    timeout: int = 600,
    capture: bool = True,
) -> subprocess.CompletedProcess[str] | None:
    """执行交付态 compose 命令；返回 CompletedProcess（异常返回 None）。"""
    try:
        return subprocess.run(
            prod_compose_cmd(*extra),
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **hidden_kwargs(),
        )
    except FileNotFoundError:
        log.error("Docker", "docker 命令不可用（Docker Desktop 未安装或不在 PATH）")
        return None
    except subprocess.TimeoutExpired:
        log.error("Docker", f"docker compose {' '.join(extra)} 超时（{timeout}s）")
        return None


def prod_stack_running() -> bool:
    """交付态栈是否有容器存在（按 compose 项目标签探测，不依赖容器名）。"""
    try:
        r = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={PROD_PROJECT}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            **hidden_kwargs(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return r.returncode == 0 and bool((r.stdout or "").strip())


def prod_stack_config_check(
    *, env: dict[str, str]
) -> tuple[bool, str]:
    """``docker compose config`` 干跑：合并语法 / 变量插值 / 相对路径一次性校验。

    比等 ``up`` 失败再排查便宜得多，建议构建前必跑（deploy up 默认会跑）。
    """
    if not prod_compose_files_present():
        return False, (
            f"缺少编排文件：{INFRA_COMPOSE_FILE.name} 或 {PROD_COMPOSE_FILE.name}"
            f"（应在 {BACKEND_DIR}）"
        )
    r = _run_prod_compose("config", env=env, timeout=120)
    if r is None:
        return False, "docker compose config 执行失败"
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "").strip()
    return True, ""


def build_prod_images(*, env: dict[str, str], services: tuple[str, ...] = ()) -> bool:
    """构建 cgda-backend / cgda-web 两个镜像（build 只声明在 backend 与 gateway 上）。"""
    log.info("Docker", "构建交付态镜像（backend + web）...")
    extra = ["build", *services] if services else ["build"]
    r = _run_prod_compose(*extra, env=env)
    if r is None:
        return False
    if r.returncode != 0:
        log.error("Docker", f"镜像构建失败:\n{(r.stderr or r.stdout or '').strip()}")
        return False
    log.ok("Docker", "镜像构建完成")
    return True


def prod_stack_up(
    *,
    env: dict[str, str],
    services: tuple[str, ...] = (),
    build: bool = False,
    wait: bool = True,
) -> bool:
    """拉起交付态栈（基础设施 + 应用层）。``services`` 为空表示全部。"""
    if build and not build_prod_images(env=env):
        return False
    extra = ["up", "-d", "--remove-orphans", *services] if services else [
        "up",
        "-d",
        "--remove-orphans",
    ]
    r = _run_prod_compose(*extra, env=env, timeout=900)
    if r is None:
        return False
    if r.returncode != 0:
        log.error("Docker", f"交付态起栈失败:\n{(r.stderr or r.stdout or '').strip()}")
        if IS_WINDOWS:
            log.warn("Docker", _windows_docker_hint())
        return False
    if wait:
        # 与 bare 态同款就绪探测：Redis 是 worker/beat 的硬前置。
        wait_for_redis(max_wait=30)
        wait_for_minio(max_wait=30)
    return True


def prod_stack_down(
    *, remove_volumes: bool = False, env: dict[str, str] | None = None
) -> None:
    """停止并移除交付态容器（默认**保留**命名卷，数据不丢）。"""
    if not prod_stack_running():
        log.info("Docker", "交付态栈未在运行，跳过")
        return
    extra = ["down", "--remove-orphans"]
    if remove_volumes:
        extra.append("-v")
    r = _run_prod_compose(*extra, env=env or readonly_prod_env(), timeout=180)
    if r is not None and r.returncode == 0:
        log.ok("Docker", "交付态容器已停止")
    else:
        log.warn("Docker", "交付态停止未成功（可手动 docker compose -p cgda down）")


def prod_stack_restart(*, env: dict[str, str], build: bool = False) -> bool:
    """重启交付态：重建镜像（可选）后 ``up -d --force-recreate`` 应用层。"""
    if build and not build_prod_images(env=env):
        return False
    r = _run_prod_compose("up", "-d", "--force-recreate", env=env, timeout=900)
    if r is None or r.returncode != 0:
        log.error(
            "Docker",
            f"交付态重启失败:\n{((r.stderr or r.stdout) if r else '').strip()}",
        )
        return False
    return True


def prod_stack_ps(*, env: dict[str, str] | None = None) -> str:
    """``docker compose ps`` 文本（供 status / deploy ps 展示）。"""
    r = _run_prod_compose("ps", env=env or readonly_prod_env(), timeout=60)
    if r is None:
        return ""
    return (r.stdout or r.stderr or "").strip()


def prod_stack_service_states() -> list[tuple[str, str]]:
    """返回 [(compose 服务名, 容器状态)]，按服务名排序。

    用 compose 的 label 过滤而非容器名：compose.prod.yml 刻意不给应用层服务
    写 container_name（保留水平扩展能力），容器名是 ``cgda-backend-1`` 这类
    自动生成名，写死会随 scale 变化而失效。
    """
    try:
        r = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label=com.docker.compose.project={PROD_PROJECT}",
                "--format",
                '{{.Label "com.docker.compose.service"}}\t{{.State}}',
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            **hidden_kwargs(),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    if r.returncode != 0:
        return []
    rows: list[tuple[str, str]] = []
    for line in (r.stdout or "").splitlines():
        name, _, state = line.partition("\t")
        if name.strip():
            rows.append((name.strip(), state.strip() or "unknown"))
    return sorted(rows)


def prod_stack_logs(
    service: str | None = None, tail: int = 80, *, env: dict[str, str] | None = None
) -> None:
    """打印交付态容器日志（``-f`` 跟随，Ctrl+C 退出）。"""
    extra = ["logs", "--tail", str(tail), "-f"]
    if service:
        extra.append(service)
    log.info("Docker", f"docker compose {' '.join(extra)}（Ctrl+C 退出）")
    r = _run_prod_compose(
        *extra, env=env or readonly_prod_env(), timeout=None, capture=False
    )
    if r is None:
        log.warn("Docker", "日志跟随未能启动")


def prod_image_names(env: dict[str, str]) -> tuple[str, str]:
    """返回 (backend 镜像名, web 镜像名)，用于交付与升级提示。"""
    prefix = (env.get("CGDA_IMAGE_PREFIX") or DEFAULT_IMAGE_PREFIX).strip() or (
        DEFAULT_IMAGE_PREFIX
    )
    tag = (env.get("CGDA_TAG") or "local").strip() or "local"
    return f"{prefix}-backend:{tag}", f"{prefix}-web:{tag}"


def prod_data_root_host_path(env: dict[str, str]) -> Path | None:
    """交付态数据根在宿主上的路径（用于存在性校验 / 展示）。"""
    raw = (env.get("CGDA_DATA_ROOT") or "").strip()
    if not raw:
        return None
    return Path(raw)
