from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from app.core import redis_client


class RedisCircuitBreakerTests(unittest.TestCase):
    def setUp(self) -> None:
        redis_client.reset_redis_client_state()

    def tearDown(self) -> None:
        redis_client.reset_redis_client_state()

    def test_record_metric_trips_circuit_and_skips_subsequent_calls(self) -> None:
        boom = redis_client.redis.RedisError("boom")
        client = MagicMock()
        pipe = MagicMock()
        client.pipeline.return_value = pipe
        pipe.execute.side_effect = boom

        with patch.object(redis_client, "get_redis_client", return_value=client):
            # threshold=3: first two failures increment counter but don't open circuit
            redis_client.record_request_metric("GET", "/docs", 200, 12.0)
            self.assertFalse(redis_client._circuit_is_open())
            redis_client.record_request_metric("GET", "/docs", 200, 13.0)
            self.assertFalse(redis_client._circuit_is_open())
            # third consecutive failure opens the circuit
            redis_client.record_request_metric("GET", "/docs", 200, 14.0)

        self.assertEqual(pipe.execute.call_count, 3)
        self.assertTrue(redis_client._circuit_is_open())

    def test_get_redis_client_returns_none_while_circuit_open(self) -> None:
        redis_client._circuit_open_until = time.monotonic() + 30
        self.assertIsNone(redis_client.get_redis_client())

    def test_mark_failure_clears_sticky_client(self) -> None:
        redis_client._client = MagicMock()
        # threshold=3: need 3 consecutive failures to open circuit
        redis_client._mark_redis_failure("fail1")
        self.assertIsNone(redis_client._client)
        self.assertFalse(redis_client._circuit_is_open())
        redis_client._client = MagicMock()
        redis_client._mark_redis_failure("fail2")
        self.assertIsNone(redis_client._client)
        self.assertFalse(redis_client._circuit_is_open())
        redis_client._client = MagicMock()
        redis_client._mark_redis_failure("fail3")
        self.assertIsNone(redis_client._client)
        self.assertTrue(redis_client._circuit_is_open())

    def test_exponential_backoff_doubles_cooldown_on_repeated_openings(self) -> None:
        """Each repeated circuit opening doubles the cooldown up to max."""
        base = redis_client._CIRCUIT_COOLDOWN_SECONDS
        max_cd = redis_client._CIRCUIT_COOLDOWN_MAX_SECONDS

        # First opening: base cooldown (30s)
        for _ in range(3):
            redis_client._mark_redis_failure("err")
        first_until = redis_client._circuit_open_until
        first_cooldown = first_until - time.monotonic()
        self.assertAlmostEqual(first_cooldown, base, delta=2)

        # Simulate cooldown elapsing, then fail again → second opening: 60s
        redis_client._circuit_open_until = 0.0  # allow reconnect attempt
        redis_client._consecutive_failures = 0  # reset (reconnect "succeeded" then failed)
        for _ in range(3):
            redis_client._mark_redis_failure("err2")
        second_cooldown = redis_client._circuit_open_until - time.monotonic()
        self.assertAlmostEqual(second_cooldown, base * 2, delta=2)

        # Third opening: 120s (hits max)
        redis_client._circuit_open_until = 0.0
        redis_client._consecutive_failures = 0
        for _ in range(3):
            redis_client._mark_redis_failure("err3")
        third_cooldown = redis_client._circuit_open_until - time.monotonic()
        self.assertAlmostEqual(third_cooldown, min(base * 4, max_cd), delta=2)

        # Fourth opening: capped at max
        redis_client._circuit_open_until = 0.0
        redis_client._consecutive_failures = 0
        for _ in range(3):
            redis_client._mark_redis_failure("err4")
        fourth_cooldown = redis_client._circuit_open_until - time.monotonic()
        self.assertAlmostEqual(fourth_cooldown, max_cd, delta=2)

        # Success resets backoff count
        redis_client._mark_redis_success()
        self.assertEqual(redis_client._circuit_open_count, 0)

    # ── L-1：dedup lock owner token 语义 ─────────────────────────────────────

    def test_acquire_dedup_lock_returns_owner_token(self) -> None:
        client = MagicMock()
        client.set.return_value = True  # SET NX 成功
        with patch.object(redis_client, "get_redis_client", return_value=client):
            token = redis_client.acquire_dedup_lock("lock:k", ttl_seconds=30)
        self.assertIsNotNone(token)
        self.assertEqual(len(token), 32)  # uuid4().hex
        args, kwargs = client.set.call_args
        self.assertEqual(args[0], "lock:k")
        self.assertEqual(args[1], token)
        self.assertTrue(kwargs.get("nx"))
        self.assertEqual(kwargs.get("ex"), 30)

    def test_acquire_dedup_lock_returns_none_when_held(self) -> None:
        client = MagicMock()
        client.set.return_value = None  # SET NX 未获取到
        with patch.object(redis_client, "get_redis_client", return_value=client):
            token = redis_client.acquire_dedup_lock("lock:k", ttl_seconds=30)
        self.assertIsNone(token)

    def test_acquire_dedup_lock_redis_down_still_returns_token(self) -> None:
        with patch.object(redis_client, "get_redis_client", return_value=None):
            token = redis_client.acquire_dedup_lock("lock:k", ttl_seconds=30)
        self.assertIsNotNone(token)  # 兼容旧放行语义（None 为假、非空串为真）

    def test_release_dedup_lock_without_token_skips_delete(self) -> None:
        client = MagicMock()
        with patch.object(redis_client, "get_redis_client", return_value=client):
            redis_client.release_dedup_lock("lock:k")  # 无 token → 不 eval、不删
        client.eval.assert_not_called()
        client.delete.assert_not_called()

    def test_release_dedup_lock_token_compare_delete_semantics(self) -> None:
        """用 Python 复刻 Lua 语义：token 不匹配不删除、匹配才删除。"""
        client = MagicMock()
        storage: dict[str, str] = {"lock:sync:a": "token-owner"}

        def fake_eval(script, numkeys, key, token):  # type: ignore[no-untyped-def]
            self.assertEqual(numkeys, 1)
            self.assertIn("redis.call", script)  # 必须是 Lua 比对删除脚本
            if storage.get(key) == token:
                storage.pop(key)
                return 1
            return 0

        client.eval.side_effect = fake_eval
        with patch.object(redis_client, "get_redis_client", return_value=client):
            # token 不匹配：不删除
            redis_client.release_dedup_lock("lock:sync:a", "token-other")
            self.assertIn("lock:sync:a", storage)
            # token 匹配：删除
            redis_client.release_dedup_lock("lock:sync:a", "token-owner")
            self.assertNotIn("lock:sync:a", storage)


if __name__ == "__main__":
    unittest.main()
