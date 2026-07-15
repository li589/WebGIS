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
            redis_client.record_request_metric("GET", "/docs", 200, 12.0)
            redis_client.record_request_metric("GET", "/docs", 200, 13.0)

        self.assertEqual(pipe.execute.call_count, 1)
        self.assertTrue(redis_client._circuit_is_open())

    def test_get_redis_client_returns_none_while_circuit_open(self) -> None:
        redis_client._circuit_open_until = time.monotonic() + 30
        self.assertIsNone(redis_client.get_redis_client())

    def test_mark_failure_clears_sticky_client(self) -> None:
        redis_client._client = MagicMock()
        redis_client._mark_redis_failure("dead")
        self.assertIsNone(redis_client._client)
        self.assertTrue(redis_client._circuit_is_open())


if __name__ == "__main__":
    unittest.main()
