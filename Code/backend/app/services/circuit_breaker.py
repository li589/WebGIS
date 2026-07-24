"""集中式断路器。

按服务端点维度管理断路器状态（CLOSED / OPEN / HALF_OPEN），
各外部调用点（Open-Meteo、GEE、NSIDC、GES-DISC 等）共享同一注册表。

此前 Open-Meteo 的断路器逻辑（5 次连续失败 → OPEN，60s 超时，HALF_OPEN 探测）
分散在 weatherengine 内部，其他外部服务无断路器保护。本模块提供统一实现，
供各 bridge / fetch gateway 按端点名获取断路器实例。

状态机：
- CLOSED：正常放行。连续失败达 failure_threshold 时 → OPEN。
- OPEN：快速失败（抛 CircuitOpenError），不发起实际请求，避免级联故障。
  经过 recovery_timeout 秒后 → HALF_OPEN。
- HALF_OPEN：放行一次探测请求。成功 → CLOSED（计数清零）；失败 → OPEN。

线程安全：使用 threading.Lock 保护状态转换。
作用域：进程内单例（每个 Celery worker 进程独立）。多 worker 间不共享状态，
但每个 worker 各自的断路器能保护自身的外部调用，已足够防止单 worker 雪崩。

使用方式：
    from app.services.circuit_breaker import get_circuit_breaker

    breaker = get_circuit_breaker("open-meteo:forecast")
    try:
        result = breaker.call(fetch_forecast, lat, lon)
    except CircuitOpenError:
        # 降级：使用过期缓存或返回默认值
        result = load_stale_cache()
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """断路器状态。"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """断路器开启时抛出。

    调用方应捕获此异常并执行降级逻辑（如返回过期缓存、默认值或友好错误）。
    不应重试同一端点（断路器会在 recovery_timeout 后自动进入 HALF_OPEN）。
    """

    def __init__(self, endpoint: str, state: CircuitState) -> None:
        super().__init__(
            f"Circuit breaker OPEN for endpoint '{endpoint}' "
            f"(state={state.value}); fast-failing to avoid cascading failures"
        )
        self.endpoint = endpoint
        self.state = state


@dataclass
class _BreakerInternal:
    """断路器内部可变状态（受 Lock 保护）。"""

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0  # time.monotonic() 记录进入 OPEN 的时刻
    probe_in_flight: bool = False  # HALF_OPEN 时是否有探测请求进行中


class CircuitBreaker:
    """单端点断路器。

    Args:
        endpoint: 端点标识（如 "open-meteo:forecast" / "gee:compute"）
        failure_threshold: 连续失败次数阈值，达到后转为 OPEN
        recovery_timeout: OPEN → HALF_OPEN 的等待秒数
        half_open_max_calls: HALF_OPEN 状态允许的并发探测数（默认 1）
    """

    def __init__(
        self,
        endpoint: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.endpoint = endpoint
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._internal = _BreakerInternal()
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """当前状态（会自动检查是否该从 OPEN → HALF_OPEN）。"""
        with self._lock:
            self._maybe_transition_to_half_open_locked()
            return self._internal.state

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._internal.consecutive_failures

    def allow_request(self) -> bool:
        """检查是否允许发起请求。

        - CLOSED：总是允许
        - OPEN：拒绝（返回 False）
        - HALF_OPEN：允许探测请求（受 half_open_max_calls 限制）
        """
        with self._lock:
            self._maybe_transition_to_half_open_locked()
            if self._internal.state == CircuitState.OPEN:
                return False
            if self._internal.state == CircuitState.HALF_OPEN:
                if self._internal.probe_in_flight:
                    return False
                self._internal.probe_in_flight = True
                return True
            return True

    def record_success(self) -> None:
        """记录一次成功调用。

        HALF_OPEN 探测成功 → CLOSED（计数清零）。
        CLOSED 状态下重置连续失败计数（恢复正常）。
        """
        with self._lock:
            if self._internal.state == CircuitState.HALF_OPEN:
                logger.info(
                    "Circuit breaker '%s' probe succeeded: HALF_OPEN → CLOSED",
                    self.endpoint,
                )
            self._internal = _BreakerInternal(state=CircuitState.CLOSED)

    def record_failure(self) -> None:
        """记录一次失败调用。

        HALF_OPEN 探测失败 → 回到 OPEN。
        CLOSED 连续失败达阈值 → OPEN。
        """
        with self._lock:
            self._internal.consecutive_failures += 1
            if self._internal.state == CircuitState.HALF_OPEN:
                self._internal.state = CircuitState.OPEN
                self._internal.opened_at = time.monotonic()
                self._internal.probe_in_flight = False
                logger.warning(
                    "Circuit breaker '%s' probe failed: HALF_OPEN → OPEN",
                    self.endpoint,
                )
                return
            if self._internal.consecutive_failures >= self.failure_threshold:
                self._internal.state = CircuitState.OPEN
                self._internal.opened_at = time.monotonic()
                logger.warning(
                    "Circuit breaker '%s' OPEN after %d consecutive failures "
                    "(threshold=%d)",
                    self.endpoint,
                    self._internal.consecutive_failures,
                    self.failure_threshold,
                )

    def _maybe_transition_to_half_open_locked(self) -> None:
        """若 OPEN 状态已过 recovery_timeout，转为 HALF_OPEN（调用方持锁）。"""
        if self._internal.state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._internal.opened_at
        if elapsed >= self.recovery_timeout:
            self._internal.state = CircuitState.HALF_OPEN
            self._internal.probe_in_flight = False
            logger.info(
                "Circuit breaker '%s' recovery timeout elapsed (%.1fs): "
                "OPEN → HALF_OPEN",
                self.endpoint,
                elapsed,
            )

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """在断路器保护下执行 func。

        - OPEN 时抛 CircuitOpenError（不调用 func）
        - func 抛异常时 record_failure 并重新抛出
        - func 成功时 record_success 并返回结果

        注意：调用方应区分 CircuitOpenError（断路器开启，应降级）与
        func 自身抛出的异常（实际请求失败，应按 FailureClassifier 处理）。
        """
        if not self.allow_request():
            raise CircuitOpenError(self.endpoint, self.state)
        try:
            result = func(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    def get_diagnostics(self) -> dict[str, Any]:
        """返回断路器诊断信息（供 /diagnostics 端点使用）。"""
        with self._lock:
            self._maybe_transition_to_half_open_locked()
            return {
                "endpoint": self.endpoint,
                "state": self._internal.state.value,
                "consecutive_failures": self._internal.consecutive_failures,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_seconds": self.recovery_timeout,
                "half_open_max_calls": self.half_open_max_calls,
            }


class CircuitBreakerRegistry:
    """断路器注册表：按端点名管理多个断路器，进程内单例。"""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_or_create(
        self,
        endpoint: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> CircuitBreaker:
        """获取或创建端点的断路器。

        同一 endpoint 多次调用返回同一实例（参数以首次创建为准）。
        若需修改已有断路器参数，使用 reset() 后重新创建。
        """
        with self._lock:
            if endpoint not in self._breakers:
                self._breakers[endpoint] = CircuitBreaker(
                    endpoint,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    half_open_max_calls=half_open_max_calls,
                )
            return self._breakers[endpoint]

    def get(self, endpoint: str) -> CircuitBreaker | None:
        with self._lock:
            return self._breakers.get(endpoint)

    def get_all_diagnostics(self) -> list[dict[str, Any]]:
        """返回所有断路器的诊断信息（供全局 diagnostics 端点使用）。"""
        with self._lock:
            return [b.get_diagnostics() for b in self._breakers.values()]

    def reset(self, endpoint: str | None = None) -> None:
        """重置断路器状态（排障用）。

        - endpoint=None：清空所有断路器
        - 指定 endpoint：仅移除该端点（下次访问时按新参数重建）
        """
        with self._lock:
            if endpoint is None:
                count = len(self._breakers)
                self._breakers.clear()
                logger.info("Reset all %d circuit breakers", count)
            elif endpoint in self._breakers:
                del self._breakers[endpoint]
                logger.info("Reset circuit breaker '%s'", endpoint)


# 进程级单例注册表
_circuit_registry = CircuitBreakerRegistry()


def get_circuit_breaker(
    endpoint: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """获取或创建端点的断路器（进程内单例）。

    各外部调用点应使用稳定的 endpoint 标识，如：
    - "open-meteo:forecast" / "open-meteo:grid"
    - "gee:compute" / "gee:export"
    - "nsidc:download" / "ges-disc:download"
    """
    return _circuit_registry.get_or_create(
        endpoint,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
    )


def get_circuit_registry() -> CircuitBreakerRegistry:
    """返回进程级断路器注册表单例。"""
    return _circuit_registry
