"""集中式断路器 CircuitBreaker 单元测试。

覆盖 CLOSED → OPEN → HALF_OPEN → CLOSED/OPEN 状态机全路径。
"""

from __future__ import annotations

import threading
import time
import unittest

from app.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    get_circuit_registry,
)


class CircuitBreakerStateTests(unittest.TestCase):
    """断路器状态机转换测试。"""

    def test_closed_allows_requests(self) -> None:
        breaker = CircuitBreaker("test:closed", failure_threshold=3)
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertTrue(breaker.allow_request())

    def test_opens_after_failure_threshold(self) -> None:
        breaker = CircuitBreaker("test:open", failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.OPEN)
        self.assertFalse(breaker.allow_request())

    def test_success_resets_consecutive_failures(self) -> None:
        breaker = CircuitBreaker("test:reset", failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertEqual(breaker.consecutive_failures, 0)
        # 需要再 3 次失败才 OPEN，而非 1 次
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_open_transitions_to_half_open_after_timeout(self) -> None:
        breaker = CircuitBreaker(
            "test:halfopen", failure_threshold=1, recovery_timeout=0.01
        )
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.OPEN)
        time.sleep(0.1)
        self.assertEqual(breaker.state, CircuitState.HALF_OPEN)

    def test_half_open_probe_success_closes_circuit(self) -> None:
        breaker = CircuitBreaker(
            "test:probe-ok", failure_threshold=1, recovery_timeout=0.01
        )
        breaker.record_failure()
        time.sleep(0.1)
        self.assertTrue(breaker.allow_request())  # 探测请求
        breaker.record_success()
        self.assertEqual(breaker.state, CircuitState.CLOSED)
        self.assertEqual(breaker.consecutive_failures, 0)

    def test_half_open_probe_failure_reopens_circuit(self) -> None:
        breaker = CircuitBreaker(
            "test:probe-fail", failure_threshold=1, recovery_timeout=0.01
        )
        breaker.record_failure()
        time.sleep(0.1)
        self.assertTrue(breaker.allow_request())  # 探测请求
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.OPEN)

    def test_half_open_allows_only_one_probe(self) -> None:
        breaker = CircuitBreaker(
            "test:probe-single", failure_threshold=1, recovery_timeout=0.01
        )
        breaker.record_failure()
        time.sleep(0.1)
        self.assertTrue(breaker.allow_request())  # 第一个探测放行
        self.assertFalse(breaker.allow_request())  # 第二个探测拒绝


class CircuitBreakerCallTests(unittest.TestCase):
    """call() 包装器测试。"""

    def test_call_returns_result_on_success(self) -> None:
        breaker = CircuitBreaker("test:call-ok", failure_threshold=3)

        def add(a: int, b: int) -> int:
            return a + b

        result = breaker.call(add, 2, 3)
        self.assertEqual(result, 5)
        self.assertEqual(breaker.state, CircuitState.CLOSED)

    def test_call_records_failure_and_reraises(self) -> None:
        breaker = CircuitBreaker("test:call-fail", failure_threshold=2)

        def boom() -> None:
            raise RuntimeError("upstream down")

        with self.assertRaises(RuntimeError):
            breaker.call(boom)
        self.assertEqual(breaker.consecutive_failures, 1)
        self.assertEqual(breaker.state, CircuitState.CLOSED)

        with self.assertRaises(RuntimeError):
            breaker.call(boom)
        self.assertEqual(breaker.state, CircuitState.OPEN)

    def test_call_raises_circuit_open_when_open(self) -> None:
        breaker = CircuitBreaker("test:call-blocked", failure_threshold=1)
        breaker.record_failure()
        self.assertEqual(breaker.state, CircuitState.OPEN)

        def should_not_be_called() -> str:
            self.fail("func should not be called when circuit is OPEN")

        with self.assertRaises(CircuitOpenError) as ctx:
            breaker.call(should_not_be_called)
        self.assertEqual(ctx.exception.endpoint, "test:call-blocked")


class CircuitBreakerRegistryTests(unittest.TestCase):
    """注册表测试。"""

    def test_get_or_create_returns_same_instance(self) -> None:
        registry = CircuitBreakerRegistry()
        b1 = registry.get_or_create("svc:a", failure_threshold=5)
        b2 = registry.get_or_create("svc:a", failure_threshold=99)
        self.assertIs(b1, b2)
        # 参数以首次创建为准
        self.assertEqual(b1.failure_threshold, 5)

    def test_get_returns_none_for_unknown(self) -> None:
        registry = CircuitBreakerRegistry()
        self.assertIsNone(registry.get("svc:unknown"))

    def test_reset_clears_all(self) -> None:
        registry = CircuitBreakerRegistry()
        registry.get_or_create("svc:a")
        registry.get_or_create("svc:b")
        registry.reset()
        self.assertIsNone(registry.get("svc:a"))
        self.assertIsNone(registry.get("svc:b"))

    def test_reset_single_endpoint(self) -> None:
        registry = CircuitBreakerRegistry()
        registry.get_or_create("svc:a")
        registry.get_or_create("svc:b")
        registry.reset("svc:a")
        self.assertIsNone(registry.get("svc:a"))
        self.assertIsNotNone(registry.get("svc:b"))

    def test_get_all_diagnostics(self) -> None:
        registry = CircuitBreakerRegistry()
        registry.get_or_create("svc:a", failure_threshold=3)
        registry.get_or_create("svc:b", failure_threshold=5)
        diags = registry.get_all_diagnostics()
        self.assertEqual(len(diags), 2)
        endpoints = {d["endpoint"] for d in diags}
        self.assertEqual(endpoints, {"svc:a", "svc:b"})

    def test_diagnostics_reflects_state(self) -> None:
        breaker = CircuitBreaker("test:diag", failure_threshold=2)
        breaker.record_failure()
        diag = breaker.get_diagnostics()
        self.assertEqual(diag["endpoint"], "test:diag")
        self.assertEqual(diag["state"], "closed")
        self.assertEqual(diag["consecutive_failures"], 1)
        breaker.record_failure()
        diag = breaker.get_diagnostics()
        self.assertEqual(diag["state"], "open")


class CircuitBreakerGlobalRegistryTests(unittest.TestCase):
    """全局单例注册表测试。"""

    def test_get_circuit_breaker_returns_singleton(self) -> None:
        get_circuit_registry().reset()
        b1 = get_circuit_breaker("global:svc", failure_threshold=5)
        b2 = get_circuit_breaker("global:svc")
        self.assertIs(b1, b2)


class CircuitBreakerConcurrencyTests(unittest.TestCase):
    """线程安全测试。"""

    def test_concurrent_failures_dont_exceed_threshold_overshoot(self) -> None:
        # 并发 record_failure 不应导致状态损坏
        breaker = CircuitBreaker("test:conc", failure_threshold=10)
        threads = []
        for _ in range(50):
            t = threading.Thread(target=breaker.record_failure)
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(breaker.state, CircuitState.OPEN)
        # 不会因并发而超过 50（record_failure 每次只 +1）
        self.assertLessEqual(breaker.consecutive_failures, 50)


if __name__ == "__main__":
    unittest.main()
