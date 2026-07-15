"""Lightweight Redis client for caching and distributed locks.

Provides a singleton Redis client with graceful degradation when Redis is
unavailable. Used for weather data caching and cross-worker request
deduplication.
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
_client_init_failed = False


def get_redis_client() -> redis.Redis | None:
    """Return a singleton Redis client, or None if Redis is unavailable."""
    global _client, _client_init_failed
    if _client is not None:
        return _client
    if _client_init_failed:
        return None
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        client.ping()
        _client = client
        logger.info("[RedisClient] connected to %s", settings.redis_url)
        return _client
    except Exception as exc:
        _client_init_failed = True
        logger.warning("[RedisClient] unavailable, falling back to file cache: %s", exc)
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
        return json.loads(raw)
    except (redis.RedisError, json.JSONDecodeError) as exc:
        logger.debug("[RedisClient] cache_get_json error for key=%s: %s", key, exc)
        return None


def cache_set_json(key: str, value: Any, ttl_seconds: int) -> bool:
    """Set a JSON value in Redis cache with TTL. Returns False on error."""
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
        return True
    except (redis.RedisError, TypeError, ValueError) as exc:
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
        return result is not None
    except redis.RedisError as exc:
        logger.debug("[RedisClient] acquire_dedup_lock error for key=%s: %s", key, exc)
        return True  # On error, allow the request to proceed


def release_dedup_lock(key: str) -> None:
    """Release a distributed lock."""
    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(key)
    except redis.RedisError as exc:
        logger.debug("[RedisClient] release_dedup_lock error for key=%s: %s", key, exc)


def wait_for_dedup(key: str, timeout_seconds: float = 30.0, poll_interval: float = 0.5) -> bool:
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
                return True
        except redis.RedisError:
            return False
        time.sleep(poll_interval)
    return False


# ─── Open-Meteo API 全局限流 ──────────────────────────────────────────────────

_API_CONCURRENT_KEY = "weather:api_concurrent"
_MAX_CONCURRENT_API_CALLS = 2
_API_SLOT_TTL = 60  # 秒，防止 worker 崩溃后计数器卡住


def acquire_api_slot(timeout: float = 30.0) -> bool:
    """获取一个全局 API 调用槽位，限制跨 worker 的 Open-Meteo 并发请求数。

    使用 Redis INCR 原子计数器实现分布式信号量。
    当并发数超过 _MAX_CONCURRENT_API_CALLS 时，调用方会等待直到有槽位释放或超时。

    Returns:
        True 如果获得槽位（或 Redis 不可用时降级放行），
        False 如果超时未获得槽位。
    """
    client = get_redis_client()
    if client is None:
        return True  # Redis 不可用时降级放行
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current = client.incr(_API_CONCURRENT_KEY)
            if current == 1:
                # 首个调用者设置 TTL，防止 worker 崩溃后计数器卡住
                client.expire(_API_CONCURRENT_KEY, _API_SLOT_TTL)
            if current <= _MAX_CONCURRENT_API_CALLS:
                return True
            # 超过限制，回退计数并等待
            client.decr(_API_CONCURRENT_KEY)
        except redis.RedisError:
            return True  # Redis 出错时降级放行
        time.sleep(0.5)
    return False


def release_api_slot() -> None:
    """释放一个 API 调用槽位。"""
    client = get_redis_client()
    if client is None:
        return
    try:
        current = client.decr(_API_CONCURRENT_KEY)
        if current < 0:
            # 计数器异常（如 TTL 过期后 DECR），重置为 0
            client.set(_API_CONCURRENT_KEY, 0, ex=_API_SLOT_TTL)
    except redis.RedisError:
        pass


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
    Redis 不可用时静默跳过。
    """
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
    except redis.RedisError as exc:
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
        keys = sorted(client.keys(pattern))
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
            endpoints.append({
                "method": method,
                "path": path,
                "count": count,
                "p50_ms": round(p50, 1),
                "p95_ms": round(p95, 1),
                "avg_ms": round(avg, 1),
                "min_ms": round(timings[0], 1),
                "max_ms": round(timings[-1], 1),
            })
        endpoints.sort(key=lambda e: e["p95_ms"], reverse=True)
        return {
            "available": True,
            "date": date_str,
            "endpoints": endpoints,
        }
    except redis.RedisError as exc:
        return {"available": False, "error": str(exc)}
