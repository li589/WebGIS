"""写接口/登录/天气瓦片 IP 级限流（发布就绪 P1-2，P0-10 宽松化）。

``/config/*``、``/import/*`` 等写接口此前无任何限流/失败锁定，可被滥用（批量写、
爆破 API key——尽管鉴权用 compare_digest，限流仍是必要的纵深防御）。按客户端 IP
做限流，超阈返回 429 + ``Retry-After``。

P0-10 产品定位决策：目标用户为课题组/大气研究院研究员，访问量小——限流做宽松
处理（默认 120 次/分钟/IP），且 development/test 环境整体旁路（开发、调试时关闭
IP 限制），仅 production 生效。阈值经 ``BACKEND_WRITE_RATE_LIMIT_PER_MINUTE`` 配置。

多进程语义（审查 S2 修复）：限流计数从「进程内内存」升级为「Redis 集中计数」，
多 worker/多实例部署下仍保持「N 次/分钟/IP」的全局口径（每进程各自 120 会稀释
阈值）。Redis 不可用/熔断时自动降级为进程内计数并告警——单进程下语义不变，
多进程下为尽力而为（更宽松而非失效）。

实现：滑动窗口用 Redis ZSET（member=时间戳+随机后缀，score=时间戳）；进程内
降级路径保留原有滑动窗口（thread-safe，list[datetime]）。
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from contextlib import suppress
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitResult:
    """限流判定结果。"""

    allowed: bool
    #: 超阈时建议的 Retry-After 秒数（滑动窗口最早记录剩余时间），放行时为 0。
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    """按 key（此处为客户端 IP）的滑动窗口限流器（线程安全，进程内，降级路径）。"""

    def __init__(self, limit: int, window: timedelta) -> None:
        self._limit = limit
        self._window = window
        self._lock = Lock()
        self._requests: dict[str, list[datetime]] = {}

    def check(self, key: str) -> RateLimitResult:
        now = datetime.now(UTC)
        cutoff = now - self._window
        with self._lock:
            timestamps = self._requests.pop(key, None) or []
            timestamps[:] = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._limit:
                self._requests[key] = timestamps
                retry_after = max(
                    1,
                    int((timestamps[0] + self._window - now).total_seconds()),
                )
                return RateLimitResult(False, retry_after)
            timestamps.append(now)
            self._requests[key] = timestamps
            return RateLimitResult(True, 0)


class RedisSlidingWindowRateLimiter:
    """Redis ZSET 滑动窗口限流器（多进程/多实例共享计数）。

    member 为 ``f"{now_ts}:{随机后缀}"``（唯一，避免同一毫秒覆盖）；score 为时间戳。
    每次判定：清理窗口外 member → 计数；超阈返回 False + 建议 Retry-After；
    否则写入本请求 member 并刷新 TTL（窗口 ×2 + 余量）。
    """

    def __init__(self, limit: int, window: timedelta, *, name: str) -> None:
        self._limit = limit
        self._window = window
        self._window_seconds = window.total_seconds()
        self._prefix = "cgda:ratelimit"
        self._name = name

    def _key(self, bucket: str) -> str:
        return f"{self._prefix}:{self._name}:{bucket}"

    def check(self, key: str) -> RateLimitResult:
        from app.core.redis_client import get_redis_client

        client = get_redis_client()
        if client is None:
            raise RuntimeError("Redis unavailable; caller should fall back in-memory")
        zkey = self._key(key)
        now = time.time()
        cutoff = now - self._window_seconds
        try:
            # 清理 + 计数在同一 pipeline 中执行，保证多进程并发下计数一致。
            pipe = client.pipeline()
            pipe.zremrangebyscore(zkey, "-inf", cutoff)
            pipe.zcard(zkey)
            _removed, count = pipe.execute()
            if count >= self._limit:
                # 最早一条 member 的 score 决定 Retry-After（窗口余量）。
                oldest = client.zrange(zkey, 0, 0, withscores=True)
                retry_after = self._window_seconds
                if oldest:
                    retry_after = self._window_seconds - (now - float(oldest[0][1]))
                return RateLimitResult(False, max(1, int(retry_after)))
            member = f"{now:.6f}:{secrets.token_hex(4)}"
            pipe = client.pipeline()
            pipe.zadd(zkey, {member: now})
            pipe.expire(zkey, int(self._window_seconds * 2) + 60)
            pipe.execute()
            return RateLimitResult(True, 0)
        except Exception as exc:  # noqa: BLE001 — Redis 异常统一交给上层降级
            from app.core.redis_client import _mark_redis_failure

            with suppress(Exception):  # pragma: no cover - defensive
                _mark_redis_failure(f"ratelimit:{self._name}:{exc}")
            raise


class RateLimiter:
    """统一入口：Redis 集中计数优先，不可用时降级进程内滑动窗口。

    降级时机与 Redis 客户端熔断（``app.core.redis_client``）协同：Redis 故障时
    ``get_redis_client()`` 返回 None 或抛错，此处回退内存计数——单进程语义不变，
    多进程语义为尽力而为（更宽松而非失效），并输出告警（限频避免刷屏）。
    """

    def __init__(self, limit: int, window: timedelta, *, name: str) -> None:
        self._memory = SlidingWindowRateLimiter(limit, window)
        self._redis = RedisSlidingWindowRateLimiter(limit, window, name=name)
        self._degraded_logged: float = 0.0
        self._degraded_lock = threading.Lock()

    def check(self, key: str) -> RateLimitResult:
        from app.core.redis_client import get_redis_client

        if get_redis_client() is not None:
            try:
                return self._redis.check(key)
            except Exception:  # noqa: BLE001 — 降级到内存计数
                self._log_degraded()
        return self._memory.check(key)

    def _log_degraded(self) -> None:
        now = time.monotonic()
        with self._degraded_lock:
            if now - self._degraded_logged < 30:
                return
            self._degraded_logged = now
        logger.warning(
            "Rate limiter [%s] degraded to in-process counting "
            "(Redis unavailable); multi-process threshold is best-effort",
            self._redis._name,
        )


# 滑动窗口窗口期固定 1 分钟；阈值可配。
_write_limiter = RateLimiter(
    int(os.getenv("BACKEND_WRITE_RATE_LIMIT_PER_MINUTE", "120")),
    timedelta(minutes=1),
    name="write",
)

# 需限流的写路径前缀（含 workflow 提交/取消/重试，防容量池滥用）
# P3 补齐：/workspace（PUT 布局持久化）、/analysis（POST 提交分析）此前漏限流
_WRITE_LIMITED_PREFIXES = (
    "/config",
    "/import",
    "/workflow-runs",
    "/cleanup",
    "/runtime",
    "/workflow-timers",
    "/weather/sync",
    "/workspace",
    "/analysis",
)
_WRITE_METHODS = ("POST", "PUT", "DELETE", "PATCH")

_login_limiter = RateLimiter(
    int(os.getenv("BACKEND_LOGIN_RATE_LIMIT_PER_MINUTE", "10")),
    timedelta(minutes=1),
    name="login",
)

_LOGIN_LIMITED_PREFIXES = ("/auth/login",)

# 天气瓦片 GET：公开读面，宽松 per-IP 限流（防上游/CPU 放大）
_tile_limiter = RateLimiter(
    int(os.getenv("BACKEND_WEATHER_TILE_RATE_LIMIT_PER_MINUTE", "240")),
    timedelta(minutes=1),
    name="tile",
)

# 问题反馈匿名上传（/feedback/api/reports，multipart）：公开写面且无鉴权，
# 较写接口更严（默认 5 次/分钟/IP），防灌垃圾文件占满磁盘。
_feedback_upload_limiter = RateLimiter(
    int(os.getenv("BACKEND_FEEDBACK_UPLOAD_RATE_LIMIT_PER_MINUTE", "5")),
    timedelta(minutes=1),
    name="feedback-upload",
)


def client_ip(request) -> str:  # type: ignore[no-untyped-def]
    """解析限流用客户端 IP。

    默认不信任 ``X-Forwarded-For`` / ``X-Real-IP``（可被客户端伪造）。
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


def check_write_rate_limit(ip: str) -> RateLimitResult:
    """返回限流判定结果（allowed + Retry-After）。"""
    result = _write_limiter.check(ip)
    if not result.allowed:
        logger.warning(
            "写接口限流触发 ip=%s retry_after=%ss",
            ip,
            result.retry_after_seconds,
        )
    return result


def should_rate_limit_login(path: str, method: str) -> bool:
    if method != "POST":
        return False
    return any(path == p or path.startswith(p + "/") for p in _LOGIN_LIMITED_PREFIXES)


def check_login_rate_limit(ip: str) -> RateLimitResult:
    result = _login_limiter.check(ip)
    if not result.allowed:
        logger.warning(
            "登录限流触发 ip=%s retry_after=%ss",
            ip,
            result.retry_after_seconds,
        )
    return result


def check_weather_tile_rate_limit(ip: str) -> RateLimitResult:
    """返回限流判定结果（allowed + Retry-After）。"""
    result = _tile_limiter.check(ip)
    if not result.allowed:
        logger.warning(
            "天气瓦片限流触发 ip=%s retry_after=%ss",
            ip,
            result.retry_after_seconds,
        )
    return result


def should_rate_limit_feedback_upload(path: str, method: str) -> bool:
    """问题反馈匿名上传限流（仅 POST /feedback/api/reports 精确匹配）。"""
    return method == "POST" and path == "/feedback/api/reports"


def check_feedback_upload_rate_limit(ip: str) -> RateLimitResult:
    result = _feedback_upload_limiter.check(ip)
    if not result.allowed:
        logger.warning(
            "反馈上传限流触发 ip=%s retry_after=%ss",
            ip,
            result.retry_after_seconds,
        )
    return result


def rate_limited_response(
    retry_after_seconds: int,
    *,
    message: str,
    request_id: str | None = None,
) -> JSONResponse:
    """构造统一的 429 限流响应：``C429001`` + ``Retry-After``（架构契约 BD-03）。

    响应体与全局异常处理器口径一致：``{"detail", "error_code", "request_id"}``。
    """
    from fastapi.responses import JSONResponse

    from app.api.error_codes import C429001

    return JSONResponse(
        status_code=429,
        content={
            "detail": message,
            "error_code": C429001.code,
            "request_id": request_id,
        },
        headers={"Retry-After": str(max(1, int(retry_after_seconds)))},
    )
