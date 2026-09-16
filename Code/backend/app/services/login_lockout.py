"""按「账号」维度的登录失败锁定（P2-2，纵深防御）。

背景
----
``app.api.rate_limit`` 已有 ``/auth/login`` 的 **IP 级** 限流（默认 10 次/分钟），
但存在两个缺口：

1. **换 IP 无效**：攻击者用僵尸网络/代理池轮 IP，每个 IP 只试 1~2 次，IP 限流
   永远不会触发，弱口令账号可被慢慢磨出来。
2. **development/test 整体旁路**：``BACKEND_ENV=development`` 时 IP 限流完全关闭
   （P0-10 的宽松化决策），本部署当前正是 development，等同于无登录限流。

因此补一层 **账号维度** 的失败计数：同一 username 连续失败 N 次后锁定 M 分钟，
与 IP 限流正交、互补，且默认在所有环境生效（可用环境变量关闭）。

语义
----
* 键：``cgda:loginfail:<sha256(username_lower)>`` → 失败计数（Redis，TTL=锁定窗口）。
* 计数达到阈值即锁定；锁定期间每次继续失败都 **刷新 TTL**（防止「边锁边试」把
  锁定窗口耗穿——否则攻击者等 15 分钟窗口尾端再试即可绕过）。
* 登录成功即清零（正常用户输错几次不会累积）。
* 管理员改口令/解锁接口可显式清零（口令换了，锁定没有意义）。

降级
----
Redis 不可用（或未部署）时降级为 **进程内** 计数（``threading.Lock`` + 单调时钟
字典），语义与 Redis 路径一致，只是多进程下为「尽力而为」（更宽松而非失效），
与 ``rate_limit.RateLimiter`` 的降级口径保持一致。
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

_PREFIX = "cgda:loginfail:"


def _enabled() -> bool:
    return os.getenv("BACKEND_LOGIN_LOCKOUT_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _threshold() -> int:
    try:
        value = int(os.getenv("BACKEND_LOGIN_LOCKOUT_THRESHOLD", "5"))
    except ValueError:
        value = 5
    return max(1, value)


def _window_seconds() -> int:
    try:
        minutes = float(os.getenv("BACKEND_LOGIN_LOCKOUT_MINUTES", "15"))
    except ValueError:
        minutes = 15.0
    return max(60, int(minutes * 60))


def _bucket(username: str) -> str:
    """归一化账号名 → 存储键片段（SHA-256 摘要，避免特殊字符/超长名污染 key）。"""
    return hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()


# 进程内降级状态：bucket -> (失败次数, 到期 monotonic 秒)
_memory: dict[str, list] = {}
_memory_lock = threading.Lock()


def _memory_prune_locked(bucket: str) -> None:
    entry = _memory.get(bucket)
    if entry and entry[1] <= time.monotonic():
        _memory.pop(bucket, None)


def lockout_status(username: str) -> tuple[bool, int]:
    """返回 ``(是否锁定, 剩余锁定秒数)``。未锁定返回 ``(False, 0)``。

    只读判定，不改变计数——用于登录前先拦截。
    """
    if not username or not _enabled():
        return (False, 0)
    bucket = _bucket(username)
    threshold = _threshold()

    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.get(_PREFIX + bucket)
            pipe.ttl(_PREFIX + bucket)
            raw, ttl = pipe.execute()
            count = int(raw) if raw is not None else 0
            if count >= threshold:
                return (
                    True,
                    max(1, int(ttl)) if ttl and ttl > 0 else _window_seconds(),
                )
            return (False, 0)
        except Exception:  # noqa: BLE001 — Redis 异常降级到进程内
            logger.debug("login lockout lookup degraded to in-memory", exc_info=True)

    with _memory_lock:
        _memory_prune_locked(bucket)
        entry = _memory.get(bucket)
        if entry and entry[0] >= threshold:
            return (True, max(1, int(entry[1] - time.monotonic())))
    return (False, 0)


def record_failure(username: str) -> int:
    """记录一次登录失败，返回当前剩余锁定秒数（未达阈值时为 0）。

    锁定期间继续失败会刷新 TTL——见模块 docstring。
    """
    if not username or not _enabled():
        return 0
    bucket = _bucket(username)
    threshold = _threshold()
    window = _window_seconds()

    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    if client is not None:
        try:
            key = _PREFIX + bucket
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window)  # 每次失败都续满窗口（覆盖式刷新）
            count, _ = pipe.execute()
            count = int(count)
            if count >= threshold:
                logger.warning(
                    "登录失败锁定触发 username=%s failures=%d/%d window=%ds",
                    username.strip(),
                    count,
                    threshold,
                    window,
                )
                return window
            return 0
        except Exception:  # noqa: BLE001 — Redis 异常降级到进程内
            logger.debug("login lockout record degraded to in-memory", exc_info=True)

    now = time.monotonic()
    with _memory_lock:
        _memory_prune_locked(bucket)
        entry = _memory.get(bucket)
        count = (entry[0] if entry else 0) + 1
        _memory[bucket] = [count, now + window]
        if count >= threshold:
            logger.warning(
                "登录失败锁定触发（进程内降级） username=%s failures=%d/%d window=%ds",
                username.strip(),
                count,
                threshold,
                window,
            )
            return window
    return 0


def clear_failures(username: str) -> None:
    """清零该账号的失败计数（登录成功 / 管理员改口令 / 管理员解锁时调用）。"""
    if not username:
        return
    bucket = _bucket(username)

    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    if client is not None:
        try:
            client.delete(_PREFIX + bucket)
        except Exception:  # noqa: BLE001 — 清 Redis 失败仍需清进程内副本
            logger.debug("login lockout clear failed on Redis", exc_info=True)

    with _memory_lock:
        _memory.pop(bucket, None)


def lockout_config() -> dict[str, object]:
    """暴露当前锁定策略（运维自检/文档核对用）。"""
    return {
        "enabled": _enabled(),
        "threshold": _threshold(),
        "window_seconds": _window_seconds(),
    }
