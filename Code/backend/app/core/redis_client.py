"""Lightweight Redis client for caching and distributed locks.

Provides a singleton Redis client with graceful degradation when Redis is
unavailable. Used for weather data caching, request metrics, and cross-worker
request deduplication.

When Redis flaps or goes down after a successful connect, a short circuit
breaker skips further Redis calls for a cooldown window so HTTP middleware
(and other hot paths) do not pay a full socket timeout on every request.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None

# Circuit breaker: after Redis errors, skip reconnect/ops until cooldown elapses.
_circuit_open_until: float = 0.0
_consecutive_failures: int = 0
_CIRCUIT_FAILURE_THRESHOLD = 1
_CIRCUIT_COOLDOWN_SECONDS = 30.0
# Keep connect/read short so a single probe after cooldown cannot stall the API for long.
_SOCKET_CONNECT_TIMEOUT = 0.5
_SOCKET_TIMEOUT = 0.5


def _circuit_is_open() -> bool:
    return time.monotonic() < _circuit_open_until


def _mark_redis_success() -> None:
    global _consecutive_failures
    _consecutive_failures = 0


def _mark_redis_failure(reason: str) -> None:
    """Invalidate sticky client and open the circuit after consecutive failures."""
    global _client, _circuit_open_until, _consecutive_failures
    _client = None
    _consecutive_failures += 1
    if _consecutive_failures < _CIRCUIT_FAILURE_THRESHOLD:
        return
    _circuit_open_until = time.monotonic() + _CIRCUIT_COOLDOWN_SECONDS
    logger.warning(
        "[RedisClient] circuit open for %.0fs after failure: %s",
        _CIRCUIT_COOLDOWN_SECONDS,
        reason,
    )


def reset_redis_client_state() -> None:
    """Test helper: clear singleton client and circuit breaker state."""
    global _client, _circuit_open_until, _consecutive_failures
    _client = None
    _circuit_open_until = 0.0
    _consecutive_failures = 0


def get_redis_client() -> redis.Redis | None:
    """Return a singleton Redis client, or None if Redis is unavailable / circuit open."""
    global _client
    if _circuit_is_open():
        return None
    if _client is not None:
        return _client
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=_SOCKET_CONNECT_TIMEOUT,
            socket_timeout=_SOCKET_TIMEOUT,
            decode_responses=True,
        )
        client.ping()
        _client = client
        _mark_redis_success()
        logger.info("[RedisClient] connected to %s", settings.redis_url)
        return _client
    except Exception as exc:
        _mark_redis_failure(str(exc))
        logger.warning(
            "[RedisClient] unavailable, falling back to local cache: %s", exc
        )
        return None


def cache_get_json(key: str) -> Any | None:
    """Get a JSON value from Redis cache. Returns None on miss or error."""
    client = get_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(key)
        if raw is None:
            return None
        _mark_redis_success()
        return json.loads(raw)
    except (redis.RedisError, json.JSONDecodeError) as exc:
        _mark_redis_failure(f"cache_get_json:{exc}")
        logger.debug("[RedisClient] cache_get_json error for key=%s: %s", key, exc)
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: int) -> bool:
    """Set a JSON value in Redis cache with TTL. Returns False on error."""
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
        _mark_redis_success()
        return True
    except (redis.RedisError, TypeError, ValueError) as exc:
        _mark_redis_failure(f"cache_set_json:{exc}")
        logger.debug("[RedisClient] cache_set_json error for key=%s: %s", key, exc)
        return False


def acquire_dedup_lock(key: str, ttl_seconds: int = 30) -> bool:
    """Try to acquire a distributed lock using SET NX.

    Returns True if the lock was acquired, False if another worker is already
    processing this key.
    """
    client = get_redis_client()
    if client is None:
        return True  # No Redis — allow the request to proceed
    try:
        result = client.set(key, "1", nx=True, ex=ttl_seconds)
        _mark_redis_success()
        return result is not None
    except redis.RedisError as exc:
        _mark_redis_failure(f"acquire_dedup_lock:{exc}")
        logger.debug("[RedisClient] acquire_dedup_lock error for key=%s: %s", key, exc)
        return True  # On error, allow the request to proceed


def release_dedup_lock(key: str) -> None:
    """Release a distributed lock."""
    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(key)
        _mark_redis_success()
    except redis.RedisError as exc:
        _mark_redis_failure(f"release_dedup_lock:{exc}")
        logger.debug("[RedisClient] release_dedup_lock error for key=%s: %s", key, exc)


def wait_for_dedup(
    key: str, timeout_seconds: float = 30.0, poll_interval: float = 0.5
) -> bool:
    """Wait for a dedup lock to be released.

    Returns True if the lock was released within the timeout, False otherwise.
    """
    client = get_redis_client()
    if client is None:
        return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if client.get(key) is None:
                _mark_redis_success()
                return True
        except redis.RedisError as exc:
            _mark_redis_failure(f"wait_for_dedup:{exc}")
            return False
        time.sleep(poll_interval)
    return False


# ─── Weather API 限流（按 pool 隔离：online / local / commercial 互不抢槽）────

_API_CONCURRENT_KEY_PREFIX = "weather:api_concurrent:"
# 商业源更严；Open-Meteo 与前端瓦片并发 cap(=4) / tile semaphore 对齐
_MAX_CONCURRENT_API_CALLS_DEFAULT = 2
_MAX_CONCURRENT_API_CALLS_OPEN_METEO = 4
_API_SLOT_TTL = 60  # 秒，防止 worker 崩溃后计数器卡住

# 兼容旧测试/引用名
_MAX_CONCURRENT_API_CALLS = _MAX_CONCURRENT_API_CALLS_DEFAULT


# 进程内信号量：按 pool 隔离；Redis 不可用时的有限降级
_local_api_slots: dict[str, int] = {}
_local_api_slots_lock = None


def _normalize_api_pool(pool: str | None) -> str:
    raw = (pool or "default").strip() or "default"
    # Redis key 安全：去掉空白与控制字符
    return "".join(ch if ch.isalnum() or ch in "-_.:/" else "_" for ch in raw)[:180]


def _max_concurrent_for_pool(pool: str) -> int:
    """Open-Meteo（含 base_url / provider id）放宽到 4；其余池保持 2。

    本地 Open-Meteo Docker（http://127.0.0.1:8080）的 base_url 不含
    "open-meteo" 字符串，需额外匹配 localhost / 127.0.0.1 端口 8080
    （OPEN_METEO_API_PORT 默认 8080）以及 provider_id 形式的 pool key。
    """
    lowered = pool.lower()
    if "open-meteo" in lowered or "openmeteo" in lowered:
        return _MAX_CONCURRENT_API_CALLS_OPEN_METEO
    # 本地 Docker Open-Meteo API（http://127.0.0.1:8080 或 localhost:8080）
    # 不限速，放宽并发
    if (
        "127.0.0.1:8080" in lowered or "localhost:8080" in lowered
    ) and "/forecast" in lowered:
        return _MAX_CONCURRENT_API_CALLS_OPEN_METEO
    # provider_id 形式的 pool key
    if "open-meteo-local" in lowered or "open_meteo_local" in lowered:
        return _MAX_CONCURRENT_API_CALLS_OPEN_METEO
    return _MAX_CONCURRENT_API_CALLS_DEFAULT


def _get_local_slot_lock():
    global _local_api_slots_lock
    if _local_api_slots_lock is None:
        import threading

        _local_api_slots_lock = threading.Lock()
    return _local_api_slots_lock


def _acquire_local_api_slot(timeout: float, pool: str) -> bool:
    deadline = time.monotonic() + timeout
    lock = _get_local_slot_lock()
    limit = _max_concurrent_for_pool(pool)
    while time.monotonic() < deadline:
        with lock:
            used = _local_api_slots.get(pool, 0)
            if used < limit:
                _local_api_slots[pool] = used + 1
                return True
        time.sleep(0.05)
    return False


def _release_local_api_slot(pool: str) -> None:
    with _get_local_slot_lock():
        _local_api_slots[pool] = max(0, _local_api_slots.get(pool, 0) - 1)


def acquire_api_slot(timeout: float = 30.0, *, pool: str | None = None) -> bool:
    """获取一个 API 调用槽位（按 ``pool`` 隔离，默认 ``default``）。

    使用 Redis INCR 原子计数器实现分布式信号量。
    Redis 不可用时回落到进程内有限信号量（不再 unconditional 放行）。

    Returns:
        True 如果获得槽位，False 如果超时未获得槽位。
    """
    pool_key = _normalize_api_pool(pool)
    redis_key = f"{_API_CONCURRENT_KEY_PREFIX}{pool_key}"
    limit = _max_concurrent_for_pool(pool_key)
    client = get_redis_client()
    if client is None:
        return _acquire_local_api_slot(timeout, pool_key)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current = client.incr(redis_key)
            if current == 1:
                # 首个调用者设置 TTL，防止 worker 崩溃后计数器卡住
                client.expire(redis_key, _API_SLOT_TTL)
            if current <= limit:
                _mark_redis_success()
                return True
            # 超过限制，回退计数并等待
            client.decr(redis_key)
        except redis.RedisError as exc:
            _mark_redis_failure(f"acquire_api_slot:{exc}")
            return _acquire_local_api_slot(
                max(0.0, deadline - time.monotonic()), pool_key
            )
        time.sleep(0.5)
    return False


def release_api_slot(*, pool: str | None = None) -> None:
    """释放一个 API 调用槽位（须与 acquire 使用同一 ``pool``）。"""
    pool_key = _normalize_api_pool(pool)
    redis_key = f"{_API_CONCURRENT_KEY_PREFIX}{pool_key}"
    client = get_redis_client()
    if client is None:
        _release_local_api_slot(pool_key)
        return
    try:
        current = client.decr(redis_key)
        if current < 0:
            # 计数器异常（如 TTL 过期后 DECR），重置为 0
            client.set(redis_key, 0, ex=_API_SLOT_TTL)
        _mark_redis_success()
    except redis.RedisError as exc:
        _mark_redis_failure(f"release_api_slot:{exc}")
        _release_local_api_slot(pool_key)


def scan_keys(client: redis.Redis, pattern: str, *, count: int = 200) -> list[str]:
    """使用 SCAN 收集匹配 key，避免生产环境 KEYS 阻塞。"""
    matched: list[str] = []
    cursor: int | str = 0
    while True:
        cursor, batch = client.scan(cursor=cursor, match=pattern, count=count)
        matched.extend(batch)
        if cursor == 0 or cursor == "0":
            break
    return matched


# ─── 请求耗时指标 ─────────────────────────────────────────────────────────────

_METRICS_KEY_PREFIX = "metrics"
_METRICS_LIST_CAP = 1000
_METRICS_TTL_SECONDS = 90000  # 25h，覆盖整天 + 1h 缓冲


def record_request_metric(
    method: str,
    path_pattern: str,
    status_code: int,
    duration_ms: float,
) -> None:
    """记录一次请求的耗时到 Redis（按天分桶、按端点分组）。

    使用 LPUSH + LTRIM 保持每端点每天最多 1000 条采样，TTL 25h。
    Redis 不可用或 circuit open 时立即跳过，不阻塞 HTTP 响应路径。
    """
    if _circuit_is_open():
        return
    client = get_redis_client()
    if client is None:
        return
    try:
        date_str = time.strftime("%Y-%m-%d", time.gmtime())
        key = f"{_METRICS_KEY_PREFIX}:{date_str}:{method}:{path_pattern}"
        pipe = client.pipeline()
        pipe.lpush(key, f"{duration_ms:.1f}")
        pipe.ltrim(key, 0, _METRICS_LIST_CAP - 1)
        pipe.expire(key, _METRICS_TTL_SECONDS)
        pipe.execute()
        _mark_redis_success()
    except redis.RedisError as exc:
        _mark_redis_failure(f"record_request_metric:{exc}")
        logger.debug("[RedisClient] record_request_metric error: %s", exc)


def get_metrics_summary(date_str: str | None = None) -> dict[str, Any]:
    """获取指定日期所有端点的 P50/P95/avg/min/max 耗时统计。

    Args:
        date_str: YYYY-MM-DD 格式日期，默认当天（UTC）。

    Returns:
        {"available": True, "date": "...", "endpoints": [...]} 或
        {"available": False, "reason": "..."}
    """
    client = get_redis_client()
    if client is None:
        return {"available": False, "reason": "redis_unavailable"}
    if date_str is None:
        date_str = time.strftime("%Y-%m-%d", time.gmtime())
    try:
        pattern = f"{_METRICS_KEY_PREFIX}:{date_str}:*"
        keys = sorted(scan_keys(client, pattern))
        endpoints: list[dict[str, Any]] = []
        for key in keys:
            # 解析 key: metrics:{date}:{method}:{path}
            parts = key.split(":", 4)
            if len(parts) < 4:
                continue
            method = parts[2]
            path = parts[3]
            raw_values = client.lrange(key, 0, -1)
            timings: list[float] = []
            for raw in raw_values:
                try:
                    timings.append(float(raw))
                except (ValueError, TypeError):
                    continue
            if not timings:
                continue
            timings.sort()
            count = len(timings)
            p50 = timings[int(count * 0.5)]
            p95 = timings[min(int(count * 0.95), count - 1)]
            avg = sum(timings) / count
            endpoints.append(
                {
                    "method": method,
                    "path": path,
                    "count": count,
                    "p50_ms": round(p50, 1),
                    "p95_ms": round(p95, 1),
                    "avg_ms": round(avg, 1),
                    "min_ms": round(timings[0], 1),
                    "max_ms": round(timings[-1], 1),
                }
            )
        endpoints.sort(key=lambda e: e["p95_ms"], reverse=True)
        _mark_redis_success()
        return {
            "available": True,
            "date": date_str,
            "endpoints": endpoints,
        }
    except redis.RedisError as exc:
        _mark_redis_failure(f"get_metrics_summary:{exc}")
        return {"available": False, "error": str(exc)}
