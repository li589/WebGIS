"""集中式断路器 CircuitBreaker 单元测试。

覆盖 CLOSED → OPEN → HALF_OPEN → CLOSED/OPEN 状态机全路径。

P1-10: 使用 mock time.monotonic 替代 time.sleep，消除 flaky 测试。
P1-11: 从 unittest.TestCase 转换为 pytest function-based 风格。
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from app.services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    get_circuit_registry,
)


# ── 状态机转换测试 ───────────────────────────────────────────────────────────


def test_closed_allows_requests() -> None:
    """CLOSED 状态允许请求通过。"""
    breaker = CircuitBreaker("test:closed", failure_threshold=3)
    assert breaker.state == CircuitState.CLOSED, "initial state should be CLOSED"
    assert breaker.allow_request(), "CLOSED state should allow requests"


def test_opens_after_failure_threshold() -> None:
    """连续失败达到阈值后转为 OPEN。"""
    breaker = CircuitBreaker("test:open", failure_threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED, "should still be CLOSED after 2 failures"
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN, "should be OPEN after 3 failures"
    assert not breaker.allow_request(), "OPEN state should block requests"


def test_success_resets_consecutive_failures() -> None:
    """成功调用重置连续失败计数。"""
    breaker = CircuitBreaker("test:reset", failure_threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED, "should remain CLOSED after success"
    assert breaker.consecutive_failures == 0, "failures should reset to 0"
    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED, "need 3 more failures, not 1"


def test_open_transitions_to_half_open_after_timeout() -> None:
    """OPEN 超时后转为 HALF_OPEN（使用 mock 时间，不实际 sleep）。"""
    current_time = [100.0]

    with patch(
        "app.services.circuit_breaker.time.monotonic",
        side_effect=lambda: current_time[0],
    ):
        breaker = CircuitBreaker(
            "test:halfopen", failure_threshold=1, recovery_timeout=0.5
        )
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN, "should be OPEN after 1 failure"

        # 模拟时间前进 0.6s（超过 recovery_timeout=0.5s）
        current_time[0] += 0.6
        assert breaker.state == CircuitState.HALF_OPEN, "should be HALF_OPEN after timeout"


def test_half_open_probe_success_closes_circuit() -> None:
    """HALF_OPEN 探测成功后关闭断路器。"""
    current_time = [100.0]

    with patch(
        "app.services.circuit_breaker.time.monotonic",
        side_effect=lambda: current_time[0],
    ):
        breaker = CircuitBreaker(
            "test:probe-ok", failure_threshold=1, recovery_timeout=0.01
        )
        breaker.record_failure()
        current_time[0] += 0.1
        assert breaker.allow_request(), "probe request should be allowed in HALF_OPEN"
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED, "should be CLOSED after probe success"
        assert breaker.consecutive_failures == 0, "failures should reset after close"


def test_half_open_probe_failure_reopens_circuit() -> None:
    """HALF_OPEN 探测失败后重新打开断路器。"""
    current_time = [100.0]

    with patch(
        "app.services.circuit_breaker.time.monotonic",
        side_effect=lambda: current_time[0],
    ):
        breaker = CircuitBreaker(
            "test:probe-fail", failure_threshold=1, recovery_timeout=0.01
        )
        breaker.record_failure()
        current_time[0] += 0.1
        assert breaker.allow_request(), "probe request should be allowed in HALF_OPEN"
        breaker.record_failure()
        assert breaker.state == CircuitState.OPEN, "should be OPEN after probe failure"


def test_half_open_allows_only_one_probe() -> None:
    """HALF_OPEN 只允许一个探测请求。"""
    current_time = [100.0]

    with patch(
        "app.services.circuit_breaker.time.monotonic",
        side_effect=lambda: current_time[0],
    ):
        breaker = CircuitBreaker(
            "test:probe-single", failure_threshold=1, recovery_timeout=0.01
        )
        breaker.record_failure()
        current_time[0] += 0.1
        assert breaker.allow_request(), "first probe should be allowed"
        assert not breaker.allow_request(), "second probe should be rejected"


# ── call() 包装器测试 ─────────────────────────────────────────────────────────


def test_call_returns_result_on_success() -> None:
    """call() 在成功时返回函数结果。"""

    def add(a: int, b: int) -> int:
        return a + b

    breaker = CircuitBreaker("test:call-ok", failure_threshold=3)
    result = breaker.call(add, 2, 3)
    assert result == 5, "call() should return the function result"
    assert breaker.state == CircuitState.CLOSED, "should remain CLOSED after success"


def test_call_records_failure_and_reraises() -> None:
    """call() 捕获异常、记录失败并重新抛出。"""
    breaker = CircuitBreaker("test:call-fail", failure_threshold=2)

    def boom() -> None:
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError, match="upstream down"):
        breaker.call(boom)
    assert breaker.consecutive_failures == 1, "should have 1 failure after first exception"
    assert breaker.state == CircuitState.CLOSED, "should still be CLOSED after 1 failure"

    with pytest.raises(RuntimeError, match="upstream down"):
        breaker.call(boom)
    assert breaker.state == CircuitState.OPEN, "should be OPEN after 2 failures"


def test_call_raises_circuit_open_when_open() -> None:
    """call() 在 OPEN 状态时抛出 CircuitOpenError，不调用被包装函数。"""
    breaker = CircuitBreaker("test:call-blocked", failure_threshold=1)
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN, "should be OPEN after 1 failure"

    def should_not_be_called() -> str:
        raise AssertionError("func should not be called when circuit is OPEN")

    with pytest.raises(CircuitOpenError) as ctx:
        breaker.call(should_not_be_called)
    assert ctx.value.endpoint == "test:call-blocked", "error should carry the endpoint name"


# ── 注册表测试 ─────────────────────────────────────────────────────────────────


def test_get_or_create_returns_same_instance() -> None:
    """get_or_create 对同一 endpoint 返回同一实例，参数以首次为准。"""
    registry = CircuitBreakerRegistry()
    b1 = registry.get_or_create("svc:a", failure_threshold=5)
    b2 = registry.get_or_create("svc:a", failure_threshold=99)
    assert b1 is b2, "same endpoint should return same instance"
    assert b1.failure_threshold == 5, "params from first creation should be kept"


def test_get_returns_none_for_unknown() -> None:
    """get 对未知 endpoint 返回 None。"""
    registry = CircuitBreakerRegistry()
    assert registry.get("svc:unknown") is None, "unknown endpoint should return None"


def test_reset_clears_all() -> None:
    """reset() 清空所有注册的断路器。"""
    registry = CircuitBreakerRegistry()
    registry.get_or_create("svc:a")
    registry.get_or_create("svc:b")
    registry.reset()
    assert registry.get("svc:a") is None, "svc:a should be cleared"
    assert registry.get("svc:b") is None, "svc:b should be cleared"


def test_reset_single_endpoint() -> None:
    """reset(endpoint) 仅清除指定 endpoint。"""
    registry = CircuitBreakerRegistry()
    registry.get_or_create("svc:a")
    registry.get_or_create("svc:b")
    registry.reset("svc:a")
    assert registry.get("svc:a") is None, "svc:a should be cleared"
    assert registry.get("svc:b") is not None, "svc:b should remain"


def test_get_all_diagnostics() -> None:
    """get_all_diagnostics 返回所有断路器的诊断信息。"""
    registry = CircuitBreakerRegistry()
    registry.get_or_create("svc:a", failure_threshold=3)
    registry.get_or_create("svc:b", failure_threshold=5)
    diags = registry.get_all_diagnostics()
    assert len(diags) == 2, "should have 2 diagnostics entries"
    endpoints = {d["endpoint"] for d in diags}
    assert endpoints == {"svc:a", "svc:b"}, "endpoints should match"


def test_diagnostics_reflects_state() -> None:
    """诊断信息反映当前状态。"""
    breaker = CircuitBreaker("test:diag", failure_threshold=2)
    breaker.record_failure()
    diag = breaker.get_diagnostics()
    assert diag["endpoint"] == "test:diag", "endpoint should match"
    assert diag["state"] == "closed", "state should be closed"
    assert diag["consecutive_failures"] == 1, "should have 1 failure"
    breaker.record_failure()
    diag = breaker.get_diagnostics()
    assert diag["state"] == "open", "state should be open after 2 failures"


# ── 全局单例注册表测试 ─────────────────────────────────────────────────────────


def test_get_circuit_breaker_returns_singleton() -> None:
    """全局 get_circuit_breaker 返回单例。"""
    get_circuit_registry().reset()
    b1 = get_circuit_breaker("global:svc", failure_threshold=5)
    b2 = get_circuit_breaker("global:svc")
    assert b1 is b2, "global registry should return same instance"


# ── 线程安全测试 ───────────────────────────────────────────────────────────────


def test_concurrent_failures_dont_exceed_threshold_overshoot() -> None:
    """并发 record_failure 不应导致状态损坏。"""
    breaker = CircuitBreaker("test:conc", failure_threshold=10)
    threads = []
    for _ in range(50):
        t = threading.Thread(target=breaker.record_failure)
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert breaker.state == CircuitState.OPEN, "should be OPEN after 50 concurrent failures"
    assert breaker.consecutive_failures <= 50, "should not exceed 50 failures"
