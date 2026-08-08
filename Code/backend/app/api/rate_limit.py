"""写接口 IP 级限流（发布就绪 P1-2，P0-10 宽松化）。

`/config/*` 与 `/import/*` 写接口此前无任何限流/失败锁定，可被滥用（批量写、爆破
API key——尽管鉴权用 compare_digest，限流仍是必要的纵深防御）。按客户端 IP 做滑动
窗口限流，超阈返回 429。

P0-10 产品定位决策：目标用户为课题组/大气研究院研究员，访问量小——限流做宽松处理
（默认 120 次/分钟/IP），且 development/test 环境整体旁路（开发、调试时关闭 IP 限制，
仅 production 生效）。阈值经 ``BACKEND_WRITE_RATE_LIMIT_PER_MINUTE`` 配置。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from threading import Lock

logger = logging.getLogger(__name__)


class SlidingWindowRateLimiter:
    """按 key（此处为客户端 IP）的滑动窗口限流器（线程安全，进程内）。"""

    def __init__(self, limit: int, window: timedelta) -> None:
        self._limit = limit
        self._window = window
        self._lock = Lock()
        self._requests: dict[str, list[datetime]] = {}

    def check(self, key: str) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = now - self._window
        with self._lock:
            timestamps = self._requests.pop(key, None) or []
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._limit:
                self._requests[key] = timestamps
                return False
            timestamps.append(now)
            self._requests[key] = timestamps
            return True


_write_limiter = SlidingWindowRateLimiter(
    int(os.getenv("BACKEND_WRITE_RATE_LIMIT_PER_MINUTE", "120")),
    timedelta(minutes=1),
)

# 需限流的写路径前缀（含 workflow 提交/取消/重试，防容量池滥用）
_WRITE_LIMITED_PREFIXES = (
    "/config",
    "/import",
    "/workflow-runs",
    "/cleanup",
    "/runtime",
    "/workflow-timers",
    "/weather/sync",
)
_WRITE_METHODS = ("POST", "PUT", "DELETE", "PATCH")

# 天气瓦片 GET：公开读面，宽松 per-IP 限流（防上游/CPU 放大）
_login_limiter = SlidingWindowRateLimiter(
    int(os.getenv("BACKEND_LOGIN_RATE_LIMIT_PER_MINUTE", "10")),
    timedelta(minutes=1),
)

_LOGIN_LIMITED_PREFIXES = ("/auth/login",)

_tile_limiter = SlidingWindowRateLimiter(
    int(os.getenv("BACKEND_WEATHER_TILE_RATE_LIMIT_PER_MINUTE", "240")),
    timedelta(minutes=1),
)


def client_ip(request) -> str:  # type: ignore[no-untyped-def]
    """解析限流用客户端 IP。

    审查 BUG-3：默认不信任 ``X-Forwarded-For`` / ``X-Real-IP``（可被客户端伪造）。
    仅当 ``settings.trust_proxy``（``BACKEND_TRUST_PROXY``）为真时才解析转发头。
    """
    from app.core.config import settings

    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


def should_rate_limit_write(path: str, method: str) -> bool:
    """是否对该请求应用写限流（仅写方法 + 指定前缀）。"""
    if method not in _WRITE_METHODS:
        return False
    return any(path == p or path.startswith(p + "/") for p in _WRITE_LIMITED_PREFIXES)


def should_rate_limit_weather_tile(path: str, method: str) -> bool:
    """公开天气瓦片 GET 限流。"""
    if method != "GET":
        return False
    return path == "/weather/tiles" or path.startswith("/weather/tiles/")


def check_write_rate_limit(ip: str) -> bool:
    """返回 True 表示放行，False 表示超阈。"""
    allowed = _write_limiter.check(ip)
    if not allowed:
        logger.warning("写接口限流触发 ip=%s", ip)
    return allowed


def should_rate_limit_login(path: str, method: str) -> bool:
    if method != "POST":
        return False
    return any(path == p or path.startswith(p + "/") for p in _LOGIN_LIMITED_PREFIXES)


def check_login_rate_limit(ip: str) -> bool:
    allowed = _login_limiter.check(ip)
    if not allowed:
        logger.warning("登录限流触发 ip=%s", ip)
    return allowed


def check_weather_tile_rate_limit(ip: str) -> bool:
    """返回 True 表示放行，False 表示超阈。"""
    allowed = _tile_limiter.check(ip)
    if not allowed:
        logger.warning("天气瓦片限流触发 ip=%s", ip)
    return allowed
