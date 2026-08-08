"""Server-side sessions (Redis primary, SQLite fallback)."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.core.redis_client import cache_get_json, cache_set_json, get_redis_client
from app.services.user_repository import get_user_repository

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "cgda:session:"
_USER_SESSIONS_PREFIX = "cgda:user_sessions:"


def _session_ttl_seconds() -> int:
    return max(300, int(settings.session_ttl_hours) * 3600)


def _expires_at_iso() -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=_session_ttl_seconds())
    ).isoformat()


def _track_user_session(user_id: int, token: str) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        key = f"{_USER_SESSIONS_PREFIX}{user_id}"
        client.sadd(key, token)
        client.expire(key, _session_ttl_seconds() + 60)
    except Exception:
        logger.debug("Failed to track user session in Redis for user_id=%s", user_id)


def _untrack_user_session(user_id: int, token: str) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        client.srem(f"{_USER_SESSIONS_PREFIX}{user_id}", token)
    except Exception:
        pass


def create_session(*, user_id: int, username: str, role: str) -> str:
    token = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "expires_at": _expires_at_iso(),
    }
    if cache_set_json(f"{_SESSION_PREFIX}{token}", payload, _session_ttl_seconds()):
        _track_user_session(user_id, token)
        return token
    get_user_repository().upsert_session(
        token=token,
        user_id=user_id,
        username=username,
        role=role,
        expires_at=payload["expires_at"],
    )
    return token


def get_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    cached = cache_get_json(f"{_SESSION_PREFIX}{token}")
    if cached and isinstance(cached, dict):
        expires_raw = cached.get("expires_at")
        if expires_raw:
            expires = datetime.fromisoformat(str(expires_raw))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                revoke_session(token)
                return None
        return cached
    return get_user_repository().get_session(token)


def revoke_session(token: str | None) -> None:
    if not token:
        return
    user_id: int | None = None
    cached = cache_get_json(f"{_SESSION_PREFIX}{token}")
    if cached and isinstance(cached, dict) and cached.get("user_id") is not None:
        user_id = int(cached["user_id"])

    client = get_redis_client()
    if client is not None:
        try:
            client.delete(f"{_SESSION_PREFIX}{token}")
        except Exception:
            pass
    if user_id is not None:
        _untrack_user_session(user_id, token)
    get_user_repository().delete_session(token)


def revoke_sessions_for_user(user_id: int) -> None:
    client = get_redis_client()
    if client is not None:
        try:
            set_key = f"{_USER_SESSIONS_PREFIX}{user_id}"
            tokens = client.smembers(set_key)
            if tokens:
                pipe = client.pipeline()
                for raw in tokens:
                    t = raw if isinstance(raw, str) else raw.decode("utf-8")
                    pipe.delete(f"{_SESSION_PREFIX}{t}")
                pipe.delete(set_key)
                pipe.execute()
        except Exception:
            logger.warning("Failed to revoke Redis sessions for user_id=%s", user_id)

    get_user_repository().delete_sessions_for_user(user_id)

    from app.services.user_token_repository import get_user_token_repository

    get_user_token_repository().revoke_tokens_for_user(user_id)
