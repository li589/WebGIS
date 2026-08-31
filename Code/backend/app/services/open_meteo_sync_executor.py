"""
Open-Meteo 同步执行器（纯逻辑，无 Celery 依赖）。

2026-08-23 分层重构（P3 god-facade/分层异味）：原 ``app/tasks/open_meteo_sync_tasks``
混杂「锁原语/命令构建/容器管理/同步执行」纯逻辑与 Celery 任务封装，导致
``weather_sync_service`` 需要侧向导入 tasks 层才能复用执行逻辑。本模块
承接全部纯逻辑；tasks 模块只留 Celery 任务封装并 re-export 本模块符号
（既有测试/调用方零改动）。

分层方向：tasks → services（正常）；services 不再 import tasks 的执行逻辑
（Celery 任务对象 ``sync_open_meteo_data`` 的派发导入除外——编排必需）。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import uuid
from datetime import UTC
from typing import Any

from app.core.config import settings
from app.core.redis_client import (
    acquire_dedup_lock,
    get_redis_client,
    release_dedup_lock,
)

logger = logging.getLogger(__name__)

# 同步任务超时（秒）：ECMWF IFS 0.25° 全球同步约 10-30 分钟
_SYNC_TIMEOUT_SECONDS = 3600

# ─── 全局同步互斥（C1 + L-1 + B-N3）─────────────────────────────────
# 三入口（API trigger / Celery Beat task / launch.py sync）共用同一组锁：
# - 按「单域」加锁 sync:domain:{d}：不同域集合只要相交即互斥，无交集可并行
#   （集合键 sync:{a,b} 只能防完全相同的域集合，a 与 a,b 重叠时仍并发写同一 volume）
# - 归一化（排序 + 去重 + 去空白，B-R3）：``a,b`` 与 ``b,a`` 解析为同一域列表
# - all-or-nothing：任一域获取失败 → 逆序释放已获取域 → 返回 None
# - Redis 可用：每域 SET NX（value=owner token，Lua 比对后删除；
#   TTL=7200s > 最长同步时长 3600s，避免锁在同步期间过期被他人接管后误删他人锁）
# - Redis 不可用：进程内 threading 互斥兜底（仅单进程内串行）
_SYNC_LOCK_TTL_SECONDS = 7200
_sync_local_lock = threading.Lock()
_sync_local_holders: set[str] = set()


def _sync_domains(domains: str | None) -> list[str]:
    """解析并归一化 domains（排序 + 去重 + 去空白；空 → ["default"]，B-R3）。"""
    parts = sorted({p.strip() for p in (domains or "").split(",") if p.strip()})
    return parts or ["default"]


def _sync_domain_key(domain: str) -> str:
    return f"sync:domain:{domain}"


def acquire_open_meteo_sync_lock(
    domains: str, ttl_seconds: int = _SYNC_LOCK_TTL_SECONDS
) -> str | None:
    """按单域 all-or-nothing 获取同步锁（B-N3）。

    Returns:
        聚合 token（JSON 串 ``{"domain": token}``）：获取成功；None：任一域已被
        其他入口持有（已获取的域已逆序回滚释放）。
    """
    domain_list = _sync_domains(domains)
    if get_redis_client() is not None:
        acquired: dict[str, str] = {}
        for domain in domain_list:
            token = acquire_dedup_lock(
                _sync_domain_key(domain), ttl_seconds=ttl_seconds
            )
            if token is None:
                for held in reversed(list(acquired)):
                    release_dedup_lock(_sync_domain_key(held), acquired[held])
                return None
            acquired[domain] = token
        return json.dumps(acquired)
    with _sync_local_lock:
        keys = [_sync_domain_key(d) for d in domain_list]
        if any(k in _sync_local_holders for k in keys):
            return None
        _sync_local_holders.update(keys)
        return f"local-{uuid.uuid4().hex}"


def release_open_meteo_sync_lock(domains: str, token: str | None = None) -> None:
    """释放同步锁（须与 acquire 返回的聚合 token 配对，逐域 compare-and-delete）。"""
    domain_list = _sync_domains(domains)
    if get_redis_client() is not None:
        if not token:
            logger.warning(
                "release_open_meteo_sync_lock called without token; "
                "locks will expire via TTL (domains=%s)",
                domain_list,
            )
            return
        try:
            tokens = json.loads(token)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "release_open_meteo_sync_lock: invalid token format; skip (domains=%s)",
                domain_list,
            )
            return
        if not isinstance(tokens, dict):
            logger.warning(
                "release_open_meteo_sync_lock: token is not a domain map; skip (domains=%s)",
                domain_list,
            )
            return
        for domain in domain_list:
            domain_token = tokens.get(domain)
            if isinstance(domain_token, str):
                release_dedup_lock(_sync_domain_key(domain), domain_token)
        return
    with _sync_local_lock:
        for domain in domain_list:
            _sync_local_holders.discard(_sync_domain_key(domain))


def is_open_meteo_sync_locked(domains: str) -> bool:
    """只读探测任一域是否被持有（API 用于快速 409，不实际获取锁）。"""
    domain_list = _sync_domains(domains)
    client = get_redis_client()
    if client is not None:
        try:
            return any(client.get(_sync_domain_key(d)) is not None for d in domain_list)
        except Exception:  # noqa: BLE001 - 探测失败按未持有处理
            return False
    with _sync_local_lock:
        return any(_sync_domain_key(d) in _sync_local_holders for d in domain_list)


def _build_sync_command(domains: str | None = None) -> list[str]:
    """构建 docker compose sync 命令。

    数据栈：`Code/infra/data-sync`（`-p data-sync`）；API 在 backend（`cgda-open-meteo`）。
    官方镜像：`sync <domains> <variables>`（尾部参数覆盖 compose 默认 command）。
    ``domains`` 可临时覆盖环境默认（不改持久配置）。
    """
    project = settings.open_meteo_sync_compose_project
    domains = (domains or settings.open_meteo_sync_domains or "").strip()
    variables = settings.open_meteo_sync_variables
    compose_file = os.path.join(
        settings.open_meteo_sync_compose_dir, "docker-compose.yml"
    )
    env_file = os.path.join(settings.open_meteo_sync_compose_dir, ".env")

    cmd = [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        compose_file,
    ]
    if os.path.isfile(env_file):
        cmd.extend(["--env-file", env_file])
    cmd.extend(
        [
            "--profile",
            "sync",
            "run",
            "--rm",
            "open-meteo-sync",
            "sync",
            domains,
            variables,
        ]
    )
    return cmd


def kill_orphan_sync_containers() -> int:
    """C-5：强制清除孤儿 sync 容器，返回清除数量。

    ``subprocess.run(timeout=...)`` 超时（或 worker 被 hard time_limit 杀）只终止
    ``docker compose run`` **客户端**；run 出的容器在 daemon 里继续跑（已实验
    实证：客户端 SIGKILL 后容器仍 Up），继续写 shared volume 并与下轮 sync 并发。

    注意：``docker compose stop/rm <service>`` 对 run 创建的容器**无效**（实验
    证伪，compose 只管理 up 创建的服务容器）——须按 compose project/service
    label 精确定位后 ``docker rm -f``。调用前提：**已持同步锁**（正常 sync 的
    容器不会被误杀，因为互斥锁保证了拿锁时不存在合法的进行中 sync）。
    """
    project = settings.open_meteo_sync_compose_project
    list_cmd = [
        "docker",
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        "label=com.docker.compose.service=open-meteo-sync",
    ]
    try:
        listing = subprocess.run(
            list_cmd, capture_output=True, text=True, timeout=15, check=False
        )
        cids = [c.strip() for c in (listing.stdout or "").splitlines() if c.strip()]
        for cid in cids:
            kill = subprocess.run(
                ["docker", "rm", "-f", cid],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if kill.returncode != 0:
                logger.warning(
                    "C-5 orphan cleanup: docker rm -f %s failed: %s",
                    cid,
                    (kill.stderr or "")[-200:],
                )
        if cids:
            logger.warning(
                "C-5: removed %d orphan sync container(s): %s", len(cids), cids
            )
        return len(cids)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("C-5 orphan cleanup skipped: %s", exc)
        return 0


def _ensure_sync_volume() -> None:
    """Ensure shared named volume exists (data-sync compose marks it external)."""
    vol = "backend_open-meteo-data"
    env_file = os.path.join(settings.open_meteo_sync_compose_dir, ".env")
    if os.path.isfile(env_file):
        try:
            with open(env_file, encoding="utf-8") as fh:
                for line in fh:
                    s = line.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    key, _, val = s.partition("=")
                    if key.strip() == "OPEN_METEO_DATA_VOLUME":
                        name = val.strip().strip('"').strip("'")
                        if name:
                            vol = name
                        break
        except OSError:
            pass
    try:
        inspect = subprocess.run(
            ["docker", "volume", "inspect", vol],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if inspect.returncode == 0:
            return
        create = subprocess.run(
            ["docker", "volume", "create", vol],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if create.returncode != 0:
            logger.warning(
                "Failed to create volume %s: %s",
                vol,
                (create.stderr or create.stdout or "")[-300:],
            )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Volume ensure skipped: %s", exc)


def execute_open_meteo_sync(domains: str | None = None) -> dict[str, Any]:
    """执行 Open-Meteo 同步（非 Celery 入口，可供 API 直接调用）。

    同步期间旧数据继续可用：open-meteo 容器读取的是 named volume，
    sync 容器覆盖文件时 open-meteo 容器不会中断服务。

    ``domains``：逗号分隔模型 id，临时覆盖 ``OPEN_METEO_SYNC_DOMAINS``（不落库）。
    返回同步结果摘要。失败时抛 RuntimeError。
    """
    from datetime import datetime

    from app.services.weather_engine_settings import record_open_meteo_sync_result

    domains_eff = (domains or settings.open_meteo_sync_domains or "").strip()
    if not domains_eff:
        raise RuntimeError(
            "Open-Meteo sync domains empty; set OPEN_METEO_SYNC_DOMAINS or pass domains="
        )

    # C1：全局互斥——锁被持有（另一进程/线程正在同步）时直接跳过，不重复跑 docker。
    lock_token = acquire_open_meteo_sync_lock(domains_eff)
    if lock_token is None:
        logger.warning("Open-Meteo sync skipped: lock held for domains=%s", domains_eff)
        return {
            "status": "skipped",
            "domains": domains_eff,
            "message": "another sync is already running for these domains",
            "finished_at": datetime.now(UTC).isoformat(),
        }

    try:
        # C-5 防御：拿锁成功说明无进行中的合法 sync——此时仍存在的 run 容器
        # 只能是上次超时/worker 被杀遗留的孤儿，先清掉再起新 sync，
        # 避免新旧容器并发写同一 volume。
        kill_orphan_sync_containers()
        _ensure_sync_volume()
        cmd = _build_sync_command(domains=domains_eff)
        logger.info("Open-Meteo sync starting: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                cwd=settings.open_meteo_sync_compose_dir,
                timeout=_SYNC_TIMEOUT_SECONDS,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            record_open_meteo_sync_result(
                ok=False,
                domains=domains_eff,
                message="docker command not found; ensure Docker is installed",
                exit_code=None,
            )
            raise RuntimeError(
                "docker command not found; ensure Docker is installed"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            # C-5：subprocess.run 超时只杀了 compose 客户端，run 容器已成孤儿
            # 继续写 volume——释锁（finally）前必须先清掉，否则下轮 sync 拿锁
            # 后与孤儿并发写。
            kill_orphan_sync_containers()
            record_open_meteo_sync_result(
                ok=False,
                domains=domains_eff,
                message=f"Open-Meteo sync timed out after {_SYNC_TIMEOUT_SECONDS}s",
                exit_code=None,
            )
            raise RuntimeError(
                f"Open-Meteo sync timed out after {_SYNC_TIMEOUT_SECONDS}s"
            ) from exc

        if result.returncode != 0:
            stderr_tail = result.stderr[-2000:] if result.stderr else ""
            logger.error(
                "Open-Meteo sync failed (exit=%d): stderr=%s",
                result.returncode,
                stderr_tail,
            )
            record_open_meteo_sync_result(
                ok=False,
                domains=domains_eff,
                message=f"exit code {result.returncode}",
                exit_code=result.returncode,
                stderr_tail=stderr_tail,
            )
            raise RuntimeError(
                f"Open-Meteo sync failed with exit code {result.returncode}: "
                f"{result.stderr[-500:] if result.stderr else 'no stderr'}"
            )

        finished_at = datetime.now(UTC).isoformat()
        logger.info("Open-Meteo sync completed successfully")
        record_open_meteo_sync_result(
            ok=True,
            domains=domains_eff,
            message="ok",
            exit_code=0,
            stderr_tail=result.stderr[-500:] if result.stderr else "",
        )
        # R-1：Celery worker 内同步成功后主动失效 coverage 探针缓存（读端 Redis 优先），
        # 避免各 worker 继续读旧 coverage 直至 TTL 过期。
        # P3 分层（2026-08-23）：原从 app.api.routers.weather_router 反向导入（tasks→API 层
        # 异味）；函数已在 services 层（weather_coverage_cache），此处直接正向引用。
        try:
            from app.services.weather_coverage_cache import (
                invalidate_weather_coverage_cache,
            )

            invalidate_weather_coverage_cache()
        except Exception:  # noqa: BLE001 - 失效失败由 TTL 兜底，不影响同步结果
            logger.debug(
                "Open-Meteo sync: coverage cache invalidation failed", exc_info=True
            )
        return {
            "status": "succeeded",
            "domains": domains_eff,
            "stdout_tail": result.stdout[-1000:] if result.stdout else "",
            "finished_at": finished_at,
        }
    finally:
        release_open_meteo_sync_lock(domains_eff, lock_token)


# ─── re-export 供 tasks 薄层兼容（测试/调用方零改动）────────────────────
