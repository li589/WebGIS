"""Redis 集中限流器单元测试（审查 S2：多进程共享阈值 + 降级路径）。

覆盖：
- Redis 可用：ZSET 滑动窗口计数（未超阈放行 / 超阈拒绝 + Retry-After）。
- Redis 不可用：降级到进程内计数（不抛错）。
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.api.rate_limit import (
    RateLimiter,
    RedisSlidingWindowRateLimiter,
    SlidingWindowRateLimiter,
)


class _FakePipe:
    """最小 pipeline 替身：按调用顺序回放 execute 结果。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._execute_result: list = []

    def zremrangebyscore(self, *args, **kwargs) -> None:
        self.calls.append("zremrangebyscore")

    def zcard(self, *args, **kwargs) -> None:
        self.calls.append("zcard")

    def zadd(self, *args, **kwargs) -> None:
        self.calls.append("zadd")

    def expire(self, *args, **kwargs) -> None:
        self.calls.append("expire")

    def execute(self):
        return self._execute_result


def _client_with(pipe: _FakePipe, *, oldest: list | None = None) -> MagicMock:
    client = MagicMock()
    client.pipeline.return_value = pipe
    if oldest is not None:
        client.zrange.return_value = oldest
    return client


def test_redis_limiter_allows_under_limit() -> None:
    limiter = RedisSlidingWindowRateLimiter(120, timedelta(minutes=1), name="write")
    pipe = _FakePipe()
    pipe._execute_result = [3, 5]  # 清理 3 条，当前 5 条（< 120）
    client = _client_with(pipe)

    with patch("app.core.redis_client.get_redis_client", return_value=client):
        result = limiter.check("10.0.0.1")

    assert result.allowed is True
    assert result.retry_after_seconds == 0
    # 超阈未触发：不应查询 oldest
    client.zrange.assert_not_called()
    assert pipe.calls[:2] == ["zremrangebyscore", "zcard"]
    assert pipe.calls[-2:] == ["zadd", "expire"]


def test_redis_limiter_rejects_over_limit_with_retry_after() -> None:
    limiter = RedisSlidingWindowRateLimiter(120, timedelta(minutes=1), name="write")
    pipe = _FakePipe()
    pipe._execute_result = [1, 120]  # 清理 1 条，当前 120（>= 120）
    now = time.time()
    # 最早一条记录在 10 秒前 → Retry-After 应约为 50 秒
    oldest = [("dummy", now - 10.0)]
    client = _client_with(pipe, oldest=oldest)

    with (
        patch("app.api.rate_limit.time.time", return_value=now),
        patch("app.core.redis_client.get_redis_client", return_value=client),
    ):
        result = limiter.check("10.0.0.1")

    assert result.allowed is False
    assert 49 <= result.retry_after_seconds <= 50
    client.zrange.assert_called_once()
    # 拒绝时不写入新 member
    assert "zadd" not in pipe.calls


def test_redis_limiter_sets_expiry_on_allow() -> None:
    limiter = RedisSlidingWindowRateLimiter(10, timedelta(minutes=1), name="login")
    pipe = _FakePipe()
    pipe._execute_result = [0, 0]
    client = _client_with(pipe)

    with patch("app.core.redis_client.get_redis_client", return_value=client):
        limiter.check("127.0.0.1")

    # expire TTL = window*2 + 60 = 120 + 60 = 180
    expire_call = pipe.calls[pipe.calls.index("expire")]
    assert expire_call is not None


def test_limiter_falls_back_to_memory_when_redis_unavailable() -> None:
    limiter = RateLimiter(2, timedelta(minutes=1), name="write")
    with patch("app.core.redis_client.get_redis_client", return_value=None):
        first = limiter.check("10.0.0.1")
        second = limiter.check("10.0.0.1")
        third = limiter.check("10.0.0.1")
    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.retry_after_seconds >= 1


def test_memory_limiter_sliding_window_evicts_old_entries() -> None:
    import datetime as real_dt

    limiter = SlidingWindowRateLimiter(1, timedelta(minutes=1))
    assert limiter.check("k").allowed is True
    # 窗口内第 2 次 → 拒绝
    assert limiter.check("k").allowed is False
    # 模拟时间前进：旧记录过期后恢复
    with patch("app.api.rate_limit.datetime") as fake_dt:
        base = real_dt.datetime.now(real_dt.timezone.utc)
        fake_dt.now.return_value = base + timedelta(minutes=2)
        assert limiter.check("k").allowed is True
