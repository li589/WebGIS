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
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
        logger.debug("[RedisClient] acquire_dedup_lock error for key=%s: %s", key, exc)
        return True  # On error, allow the request to proceed


def release_dedup_lock(key: str) -> None:
    """Release a distributed lock."""
    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception as exc:
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
        except Exception:
            return False
        time.sleep(poll_interval)
    return False
