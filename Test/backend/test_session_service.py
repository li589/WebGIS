"""Tests for app.services.session_service (Redis-primary, SQLite-fallback sessions).

All Redis and user-repository dependencies are mocked; no real services required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock, patch

import app.services.session_service as session_service


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


@patch("app.services.session_service.get_user_repository")
@patch("app.services.session_service.get_redis_client")
@patch("app.services.session_service.cache_set_json")
def test_create_session_returns_token_when_redis_available(
    mock_cache_set, mock_get_redis, mock_get_user_repo
):
    """When cache_set_json succeeds, a token is returned and the session tracked in Redis."""
    mock_cache_set.return_value = True
    mock_client = MagicMock()
    mock_get_redis.return_value = mock_client

    token = session_service.create_session(user_id=1, username="alice", role="admin")

    assert isinstance(token, str) and len(token) > 20, "token must be a non-trivial string"
    mock_cache_set.assert_called_once(), "session payload must be written to cache"
    # _track_user_session adds the token to the user's Redis set.
    mock_client.sadd.assert_called_once(), "token must be tracked via sadd"
    mock_client.expire.assert_called_once(), "set expiry must be set"
    # SQLite fallback must NOT be used when Redis succeeded.
    mock_get_user_repo.return_value.upsert_session.assert_not_called(), (
        "SQLite upsert must not run when Redis write succeeds"
    )


@patch("app.services.session_service.get_user_repository")
@patch("app.services.session_service.get_redis_client")
@patch("app.services.session_service.cache_set_json")
def test_create_session_falls_back_to_sqlite_when_redis_unavailable(
    mock_cache_set, mock_get_redis, mock_get_user_repo
):
    """When cache_set_json fails, the session is persisted via the user repository."""
    mock_cache_set.return_value = False
    mock_get_redis.return_value = None
    mock_repo = mock_get_user_repo.return_value

    token = session_service.create_session(user_id=2, username="bob", role="standard")

    assert isinstance(token, str), "a token must still be returned in fallback mode"
    mock_repo.upsert_session.assert_called_once(), (
        "SQLite upsert_session must run when Redis write fails"
    )
    call_kwargs = mock_repo.upsert_session.call_args.kwargs
    assert call_kwargs["user_id"] == 2, "user_id must be forwarded to upsert_session"
    assert call_kwargs["username"] == "bob", "username must be forwarded"
    assert call_kwargs["role"] == "standard", "role must be forwarded"


# ---------------------------------------------------------------------------
# get_session
# ---------------------------------------------------------------------------


def test_get_session_returns_none_for_empty_token():
    """A None/empty token short-circuits to None without touching Redis."""
    with patch("app.services.session_service.cache_get_json") as mock_cache_get:
        assert session_service.get_session(None) is None, "None token must return None"
        assert session_service.get_session("") is None, "empty token must return None"
        mock_cache_get.assert_not_called(), "cache must not be queried for empty token"


@patch("app.services.session_service.cache_get_json")
def test_get_session_returns_cached_payload_when_valid(mock_cache_get):
    """A non-expired cached session is returned as-is."""
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    mock_cache_get.return_value = {
        "user_id": 1,
        "username": "alice",
        "role": "admin",
        "expires_at": future,
    }
    result = session_service.get_session("some-token")
    assert result is not None, "valid cached session must be returned"
    assert result["username"] == "alice", "cached payload must be passed through"


@patch("app.services.session_service.revoke_session")
@patch("app.services.session_service.cache_get_json")
def test_get_session_revokes_expired_session(mock_cache_get, mock_revoke):
    """An expired cached session is revoked and None is returned."""
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    mock_cache_get.return_value = {
        "user_id": 1,
        "username": "alice",
        "role": "admin",
        "expires_at": past,
    }
    result = session_service.get_session("expired-token")
    assert result is None, "expired session must return None"
    mock_revoke.assert_called_once_with("expired-token"), (
        "expired session must be revoked"
    )


@patch("app.services.session_service.get_user_repository")
@patch("app.services.session_service.cache_get_json")
def test_get_session_falls_back_to_user_repo_when_cache_miss(
    mock_cache_get, mock_get_user_repo
):
    """A cache miss delegates to the user repository's get_session."""
    mock_cache_get.return_value = None
    mock_get_user_repo.return_value.get_session.return_value = {"user_id": 9, "from": "db"}
    result = session_service.get_session("missing-in-cache")
    assert result == {"user_id": 9, "from": "db"}, "must return DB session on cache miss"


# ---------------------------------------------------------------------------
# revoke_session
# ---------------------------------------------------------------------------


@patch("app.services.session_service.get_user_repository")
@patch("app.services.session_service.get_redis_client")
@patch("app.services.session_service.cache_get_json")
def test_revoke_session_deletes_from_redis_and_db(
    mock_cache_get, mock_get_redis, mock_get_user_repo
):
    """revoking deletes the Redis key, untracks the user session, and deletes from DB."""
    mock_cache_get.return_value = {"user_id": 7, "username": "u", "role": "standard"}
    mock_client = MagicMock()
    mock_get_redis.return_value = mock_client

    session_service.revoke_session("tok-1")

    mock_client.delete.assert_called_once_with("cgda:session:tok-1"), (
        "Redis session key must be deleted"
    )
    mock_client.srem.assert_called_once(), "token must be untracked from user set"
    mock_get_user_repo.return_value.delete_session.assert_called_once_with("tok-1"), (
        "DB session must be deleted"
    )


def test_revoke_session_noop_for_empty_token():
    """An empty token is a no-op."""
    with patch("app.services.session_service.cache_get_json") as mock_cache_get:
        session_service.revoke_session(None)
        session_service.revoke_session("")
        mock_cache_get.assert_not_called(), "empty token must not query cache"


@patch("app.services.session_service.get_user_repository")
@patch("app.services.session_service.get_redis_client")
@patch("app.services.session_service.cache_get_json")
def test_revoke_session_without_cached_user_id_skips_untrack(
    mock_cache_get, mock_get_redis, mock_get_user_repo
):
    """If the cached payload has no user_id, _untrack_user_session is skipped."""
    mock_cache_get.return_value = {}  # no user_id
    mock_client = MagicMock()
    mock_get_redis.return_value = mock_client

    session_service.revoke_session("tok-2")

    mock_client.delete.assert_called_once_with("cgda:session:tok-2"), (
        "Redis key still deleted even without user_id"
    )
    mock_client.srem.assert_not_called(), (
        "untrack must be skipped when user_id is absent"
    )


# ---------------------------------------------------------------------------
# revoke_sessions_for_user
# ---------------------------------------------------------------------------


@patch("app.services.user_token_repository.get_user_token_repository")
@patch("app.services.session_service.get_user_repository")
@patch("app.services.session_service.get_redis_client")
def test_revoke_sessions_for_user_clears_redis_set_and_db(
    mock_get_redis, mock_get_user_repo, mock_get_token_repo
):
    """revoke_sessions_for_user deletes all tokens in the user's Redis set and DB."""
    mock_client = MagicMock()
    mock_client.smembers.return_value = {b"tok-a", b"tok-b"}
    mock_get_redis.return_value = mock_client

    session_service.revoke_sessions_for_user(user_id=5)

    # Pipeline deletes each session key plus the set key itself.
    pipe = mock_client.pipeline.return_value
    assert pipe.delete.call_count == 3, (
        "must delete 2 tokens + 1 set key via pipeline"
    )
    pipe.execute.assert_called_once(), "pipeline must be executed"
    mock_get_user_repo.return_value.delete_sessions_for_user.assert_called_once_with(5), (
        "DB sessions for user must be deleted"
    )
    mock_get_token_repo.return_value.revoke_tokens_for_user.assert_called_once_with(5), (
        "user tokens must be revoked"
    )


@patch("app.services.user_token_repository.get_user_token_repository")
@patch("app.services.session_service.get_user_repository")
@patch("app.services.session_service.get_redis_client")
def test_revoke_sessions_for_user_with_no_redis_client_still_clears_db(
    mock_get_redis, mock_get_user_repo, mock_get_token_repo
):
    """When Redis is unavailable, DB + token revocation still proceeds."""
    mock_get_redis.return_value = None

    session_service.revoke_sessions_for_user(user_id=6)

    mock_get_user_repo.return_value.delete_sessions_for_user.assert_called_once_with(6), (
        "DB sessions must still be cleared without Redis"
    )
    mock_get_token_repo.return_value.revoke_tokens_for_user.assert_called_once_with(6), (
        "tokens must still be revoked without Redis"
    )
