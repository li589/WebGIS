from __future__ import annotations

import pytest
import types
import time
from unittest.mock import MagicMock, patch

from app.core import redis_client


@pytest.fixture
def _redis_circuit_breaker_tests_env():
    ns = types.SimpleNamespace()
    redis_client.reset_redis_client_state()
    yield ns
    redis_client.reset_redis_client_state()


def test_record_metric_trips_circuit_and_skips_subsequent_calls(_redis_circuit_breaker_tests_env) -> None:
    self = _redis_circuit_breaker_tests_env
    boom = redis_client.redis.RedisError("boom")
    client = MagicMock()
    pipe = MagicMock()
    client.pipeline.return_value = pipe
    pipe.execute.side_effect = boom

    with patch.object(redis_client, "get_redis_client", return_value=client):
        # threshold=3: first two failures increment counter but don't open circuit
        redis_client.record_request_metric("GET", "/docs", 200, 12.0)
        assert not redis_client._circuit_is_open(), 'redis_client._circuit_is_open() is falsy'
        redis_client.record_request_metric("GET", "/docs", 200, 13.0)
        assert not redis_client._circuit_is_open(), 'redis_client._circuit_is_open() is falsy'
        # third consecutive failure opens the circuit
        redis_client.record_request_metric("GET", "/docs", 200, 14.0)

    assert pipe.execute.call_count == 3, 'pipe.execute.call_count == 3'
    assert redis_client._circuit_is_open(), 'redis_client._circuit_is_open() is truthy'


def test_get_redis_client_returns_none_while_circuit_open(_redis_circuit_breaker_tests_env) -> None:
    self = _redis_circuit_breaker_tests_env
    redis_client._circuit_open_until = time.monotonic() + 30
    assert redis_client.get_redis_client() is None, 'redis_client.get_redis_client() is None'


def test_mark_failure_clears_sticky_client(_redis_circuit_breaker_tests_env) -> None:
    self = _redis_circuit_breaker_tests_env
    redis_client._client = MagicMock()
    # threshold=3: need 3 consecutive failures to open circuit
    redis_client._mark_redis_failure("fail1")
    assert redis_client._client is None, 'redis_client._client is None'
    assert not redis_client._circuit_is_open(), 'redis_client._circuit_is_open() is falsy'
    redis_client._client = MagicMock()
    redis_client._mark_redis_failure("fail2")
    assert redis_client._client is None, 'redis_client._client is None'
    assert not redis_client._circuit_is_open(), 'redis_client._circuit_is_open() is falsy'
    redis_client._client = MagicMock()
    redis_client._mark_redis_failure("fail3")
    assert redis_client._client is None, 'redis_client._client is None'
    assert redis_client._circuit_is_open(), 'redis_client._circuit_is_open() is truthy'


def test_exponential_backoff_doubles_cooldown_on_repeated_openings(_redis_circuit_breaker_tests_env) -> None:
    """Each repeated circuit opening doubles the cooldown up to max."""
    self = _redis_circuit_breaker_tests_env
    base = redis_client._CIRCUIT_COOLDOWN_SECONDS
    max_cd = redis_client._CIRCUIT_COOLDOWN_MAX_SECONDS

    # First opening: base cooldown (30s)
    for _ in range(3):
        redis_client._mark_redis_failure("err")
    first_until = redis_client._circuit_open_until
    first_cooldown = first_until - time.monotonic()
    assert round(first_cooldown, 7) == round(base, 7), 'round(first_cooldown, 7) == round(base, 7)'

    # Simulate cooldown elapsing, then fail again → second opening: 60s
    redis_client._circuit_open_until = 0.0  # allow reconnect attempt
    redis_client._consecutive_failures = 0  # reset (reconnect "succeeded" then failed)
    for _ in range(3):
        redis_client._mark_redis_failure("err2")
    second_cooldown = redis_client._circuit_open_until - time.monotonic()
    assert round(second_cooldown, 7) == round(base * 2, 7), 'round(second_cooldown, 7) == round(base * 2, 7)'

    # Third opening: 120s (hits max)
    redis_client._circuit_open_until = 0.0
    redis_client._consecutive_failures = 0
    for _ in range(3):
        redis_client._mark_redis_failure("err3")
    third_cooldown = redis_client._circuit_open_until - time.monotonic()
    assert round(third_cooldown, 7) == round(min(base * 4, max_cd), 7), 'round(third_cooldown, 7) == round(min(base * 4, max_cd), 7)'

    # Fourth opening: capped at max
    redis_client._circuit_open_until = 0.0
    redis_client._consecutive_failures = 0
    for _ in range(3):
        redis_client._mark_redis_failure("err4")
    fourth_cooldown = redis_client._circuit_open_until - time.monotonic()
    assert round(fourth_cooldown, 7) == round(max_cd, 7), 'round(fourth_cooldown, 7) == round(max_cd, 7)'

    # Success resets backoff count
    redis_client._mark_redis_success()
    assert redis_client._circuit_open_count == 0, 'redis_client._circuit_open_count == 0'


def test_acquire_dedup_lock_returns_owner_token(_redis_circuit_breaker_tests_env) -> None:
    self = _redis_circuit_breaker_tests_env
    client = MagicMock()
    client.set.return_value = True  # SET NX 成功
    with patch.object(redis_client, "get_redis_client", return_value=client):
        token = redis_client.acquire_dedup_lock("lock:k", ttl_seconds=30)
    assert token is not None, 'token is not None'
    assert len(token) == 32, 'len(token) == 32'  # uuid4().hex
    args, kwargs = client.set.call_args
    assert args[0] == "lock:k", 'args[0] == "lock:k"'
    assert args[1] == token, 'args[1] == token'
    assert kwargs.get("nx"), 'kwargs.get("nx") is truthy'
    assert kwargs.get("ex") == 30, 'kwargs.get("ex") == 30'


def test_acquire_dedup_lock_returns_none_when_held(_redis_circuit_breaker_tests_env) -> None:
    self = _redis_circuit_breaker_tests_env
    client = MagicMock()
    client.set.return_value = None  # SET NX 未获取到
    with patch.object(redis_client, "get_redis_client", return_value=client):
        token = redis_client.acquire_dedup_lock("lock:k", ttl_seconds=30)
    assert token is None, 'token is None'


def test_acquire_dedup_lock_redis_down_still_returns_token(_redis_circuit_breaker_tests_env) -> None:
    self = _redis_circuit_breaker_tests_env
    with patch.object(redis_client, "get_redis_client", return_value=None):
        token = redis_client.acquire_dedup_lock("lock:k", ttl_seconds=30)
    assert token is not None, 'token is not None'


def test_release_dedup_lock_without_token_skips_delete(_redis_circuit_breaker_tests_env) -> None:
    self = _redis_circuit_breaker_tests_env
    client = MagicMock()
    with patch.object(redis_client, "get_redis_client", return_value=client):
        redis_client.release_dedup_lock("lock:k")  # 无 token → 不 eval、不删
    client.eval.assert_not_called()
    client.delete.assert_not_called()


def test_release_dedup_lock_token_compare_delete_semantics(_redis_circuit_breaker_tests_env) -> None:
    """用 Python 复刻 Lua 语义：token 不匹配不删除、匹配才删除。"""
    self = _redis_circuit_breaker_tests_env
    client = MagicMock()
    storage: dict[str, str] = {"lock:sync:a": "token-owner"}

    def fake_eval(script, numkeys, key, token):  # type: ignore[no-untyped-def]
        assert numkeys == 1, 'numkeys == 1'
        assert "redis.call" in script, '"redis.call" in script'  # 必须是 Lua 比对删除脚本
        if storage.get(key) == token:
            storage.pop(key)
            return 1
        return 0

    client.eval.side_effect = fake_eval
    with patch.object(redis_client, "get_redis_client", return_value=client):
        # token 不匹配：不删除
        redis_client.release_dedup_lock("lock:sync:a", "token-other")
        assert "lock:sync:a" in storage, '"lock:sync:a" in storage'
        # token 匹配：删除
        redis_client.release_dedup_lock("lock:sync:a", "token-owner")
        assert "lock:sync:a" not in storage, '"lock:sync:a" not in storage'
