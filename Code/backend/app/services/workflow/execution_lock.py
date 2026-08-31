"""工作流执行互斥锁（C-3，2026-08-23）。

背景：``dispatch_workflow_task`` 的 ``apply_async`` 8s 限时只放弃等待、不撤销
投递——慢 broker 下消息可能迟到入队；加上 Beat 每 2min 对"无 task_id 的 queued
run"重派，同一 run 会产生双消息。worker 端 ``process_workflow_run`` 的幂等检查
只挡终态，running 状态的重投会**从头并发执行**（产物覆盖/事件重复）。

方案：执行入口以 Redis ``SET NX`` 抢 ``cgda:workflow:execution_lock:{run_id}``：

- 抢到 → 本 worker 执行；``finally`` 释放（值匹配 Lua，防误删接管者的锁）。
- 未抢到且持有者进程存活（同机 pid 探活）→ 判定为 C-3 双消息，**跳过**。
- 未抢到且持有者进程已死（原 worker 崩溃）→ **接管**（acks_late 重投语义保留），
  经值匹配 CAS 接管后重新持锁执行。
- Redis 不可用 → fail-open 退回原"警告+重执行"行为（不因锁故障卡死任务）。

锁值含 uuid：同 pid 被操作系统复用时不会误释放他人锁。兜底 TTL 略大于任务
hard time_limit（7500s），仅用于 worker 崩溃且无人接管时防 key 泄漏。
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from redis import RedisError

logger = logging.getLogger(__name__)

_LOCK_KEY_PREFIX = "cgda:workflow:execution_lock:"
# 任务 time_limit=7500s（workflow_tasks）；兜底 TTL 放宽 5 分钟
_DEFAULT_TTL_SECONDS = 7800
_WIN_STILL_ACTIVE = 259

# 值匹配删除的 Lua：释放/接管都做 CAS，防止删掉接管者/新持有者的锁
_DELETE_IF_EQUAL_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class _LockRedisClient(Protocol):
    """锁所需的最小 Redis 接口（便于测试注入 fake）。"""

    def set(self, key: str, value: str, nx: bool = ..., ex: int = ...) -> Any: ...

    def get(self, key: str) -> Any: ...

    def eval(self, script: str, numkeys: int, key: str, value: str) -> Any: ...


@dataclass(frozen=True)
class LockAcquireResult:
    """锁获取结果。

    - ``acquired``: 抢到新锁，执行。
    - ``takeover``: 持有者进程已死，CAS 接管成功，执行。
    - ``blocked``: 持有者存活/未知或接管失败，**跳过**执行。
    - ``degraded``: Redis 不可用，按无锁语义执行（fail-open）。
    """

    state: str
    token: str | None = None
    holder: str | None = None


def is_local_process_alive(hostname: str, pid: int) -> bool | None:
    """探活持有者进程。返回 None 表示无法判定（跨机部署）。

    单机部署（当前形态）下 hostname 与本机一致，用 OS 探活；
    跨机部署返回 None，调用方按"存活"保守处理（不接管）。
    """
    if hostname != socket.gethostname():
        return None
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32  # noqa: SLA001
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == _WIN_STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class WorkflowExecutionLock:
    """同 run 执行互斥：双消息跳过、崩溃接管、Redis 故障 fail-open。"""

    def __init__(
        self,
        client_provider: Any,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        alive_checker=is_local_process_alive,
    ) -> None:
        self._client_provider = client_provider
        self._ttl_seconds = ttl_seconds
        self._alive_checker = alive_checker

    def _client(self) -> _LockRedisClient | None:
        try:
            client = self._client_provider()
        except Exception:  # noqa: BLE001 — Redis 故障 fail-open
            logger.warning("[ExecutionLock] redis client unavailable", exc_info=True)
            return None
        return client

    def acquire(self, run_id: str) -> LockAcquireResult:
        client = self._client()
        if client is None:
            return LockAcquireResult(state="degraded")

        key = _LOCK_KEY_PREFIX + run_id
        token = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        try:
            ok = client.set(key, token, nx=True, ex=self._ttl_seconds)
        except RedisError as exc:
            logger.warning("[ExecutionLock] acquire failed (redis error): %s", exc)
            return LockAcquireResult(state="degraded")
        if ok:
            return LockAcquireResult(state="acquired", token=token)

        holder_raw = self._get_holder(client, key)
        if holder_raw is None:
            # 锁在 SET 与 GET 之间被释放——重试一次 SET NX
            try:
                ok = client.set(key, token, nx=True, ex=self._ttl_seconds)
            except RedisError as exc:
                logger.warning("[ExecutionLock] re-acquire failed: %s", exc)
                return LockAcquireResult(state="degraded")
            if ok:
                return LockAcquireResult(state="acquired", token=token)
            holder_raw = self._get_holder(client, key) or ""

        holder_hostname, holder_pid = self._parse_holder(holder_raw)
        alive = None
        if holder_pid is not None:
            alive = self._alive_checker(holder_hostname, holder_pid)

        if alive is None or alive:
            logger.info(
                "[ExecutionLock] run %s: holder alive/unknown (%s) — skip "
                "duplicate delivery",
                run_id,
                holder_raw,
            )
            return LockAcquireResult(state="blocked", holder=holder_raw)

        # 持有者已死：值匹配 CAS 接管
        try:
            taken = client.eval(_DELETE_IF_EQUAL_LUA, 1, key, holder_raw)
        except RedisError as exc:
            logger.warning("[ExecutionLock] takeover eval failed: %s", exc)
            return LockAcquireResult(state="degraded")
        if not taken:
            # 其他重投 worker 已抢先接管
            return LockAcquireResult(state="blocked", holder=holder_raw)
        try:
            ok = client.set(key, token, nx=True, ex=self._ttl_seconds)
        except RedisError as exc:
            logger.warning("[ExecutionLock] takeover set failed: %s", exc)
            return LockAcquireResult(state="degraded")
        if ok:
            logger.warning(
                "[ExecutionLock] run %s: holder %s dead — takeover by %s",
                run_id,
                holder_raw,
                token,
            )
            return LockAcquireResult(state="takeover", token=token)
        return LockAcquireResult(state="blocked", holder=holder_raw)

    def release(self, run_id: str, token: str | None) -> None:
        if not token:
            return
        client = self._client()
        if client is None:
            return
        try:
            client.eval(_DELETE_IF_EQUAL_LUA, 1, _LOCK_KEY_PREFIX + run_id, token)
        except RedisError as exc:
            logger.warning("[ExecutionLock] release failed: %s", exc)

    def _get_holder(self, client: _LockRedisClient, key: str) -> str | None:
        try:
            raw = client.get(key)
        except RedisError:
            return None
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)

    @staticmethod
    def _parse_holder(holder_raw: str) -> tuple[str, int | None]:
        parts = holder_raw.split(":")
        if len(parts) >= 2:
            try:
                return parts[0], int(parts[1])
            except ValueError:
                pass
        return holder_raw, None
