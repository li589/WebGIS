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

import hashlib
import logging
import os
import secrets
import threading
from contextlib import suppress
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC, timezone
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


# Agent chat：独立滑动窗口（默认 30/分钟/IP），与写接口限流键分离。
_agent_chat_limiter = RateLimiter(
    int(os.getenv("BACKEND_AGENT_CHAT_RATE_LIMIT_PER_MINUTE", "30")),
    timedelta(minutes=1),
    name="agent_chat",
)

# Agent models/refresh：独立限流（默认 20/分钟/IP），防外呼放大。
_agent_models_refresh_limiter = RateLimiter(
    int(os.getenv("BACKEND_AGENT_MODELS_REFRESH_RATE_LIMIT_PER_MINUTE", "20")),
    timedelta(minutes=1),
    name="agent_models_refresh",
)


def should_rate_limit_agent_chat(path: str, method: str) -> bool:
    return method == "POST" and (
        path == "/agent/chat" or path.startswith("/agent/chat/")
    )


def check_agent_chat_rate_limit(ip: str) -> RateLimitResult:
    result = _agent_chat_limiter.check(ip)
    if not result.allowed:
        logger.warning(
            "Agent chat 限流触发 ip=%s retry_after=%ss",
            ip,
            result.retry_after_seconds,
        )
    return result


def should_rate_limit_agent_models_refresh(path: str, method: str) -> bool:
    return method == "POST" and path.rstrip("/") == "/agent/models/refresh"


def check_agent_models_refresh_rate_limit(ip: str) -> RateLimitResult:
    result = _agent_models_refresh_limiter.check(ip)
    if not result.allowed:
        logger.warning(
            "Agent models/refresh 限流触发 ip=%s retry_after=%ss",
            ip,
            result.retry_after_seconds,
        )
    return result


# ---------------------------------------------------------------------------
# Agent 游客「按天」额度（未登录访客）
# ---------------------------------------------------------------------------
# 背景：本项目所有未登录访客共用同一个 demo 账号，服务端无法按「人」区分，
# 所以按登录账号做日额度会退化成「全站共享一份额度」。改用**浏览器侧生成的
# 匿名访客号**（前端 localStorage 里的随机串，随请求头 ``X-Visitor-Id`` 上报）
# 作为计数键：
#   - 有访客号   → 按 ``visitor:<hash>`` 计数
#   - 没上报（旧缓存）→ 退化为按客户端 IP 计数，保证仍然生效
# 切分口径为**北京时间自然日**，跨日自动清零（Redis TTL 到次日 0 点）。
# 额度 <= 0 表示关闭（自动化测试/本机探针用）。
#
# 注意与「每分钟 30 次」的区别：那是防连点的滑动窗口，这是防一天总量过大
# 的日累计，两者叠加生效。

_GUEST_QUOTA_LIMIT = int(os.getenv("BACKEND_AGENT_GUEST_DAILY_QUOTA", "20"))
_guest_quota_memory: dict[str, int] = {}
_guest_quota_memory_lock = Lock()


def guest_quota_limit() -> int:
    """当前生效的游客日额度（0 = 关闭）。"""
    return _GUEST_QUOTA_LIMIT


def _beijing_day_and_ttl() -> tuple[str, int]:
    """返回 (北京日期 YYYY-MM-DD, 距次日 0 点秒数)。"""
    now = datetime.now(UTC).astimezone(timezone(timedelta(hours=8)))
    day = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return day, max(60, int((tomorrow - now).total_seconds()))


def _guest_quota_key(visitor_id: str | None, ip: str) -> str:
    day, _ttl = _beijing_day_and_ttl()
    raw = f"v:{visitor_id}" if visitor_id else f"ip:{ip}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"cgda:quota:guest:{digest}:{day}"


def check_agent_guest_daily_quota(visitor_id: str | None, ip: str) -> RateLimitResult:
    """游客当日额度判定：每次调用消耗 1 次。

    超限时 ``retry_after_seconds`` 为距北京次日 0 点的秒数。
    """
    if _GUEST_QUOTA_LIMIT <= 0:
        return RateLimitResult(True, 0)

    day, ttl = _beijing_day_and_ttl()
    key = _guest_quota_key(visitor_id, ip)

    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    if client is not None:
        try:
            count = int(client.incr(key))
            if count == 1:
                # 首次计数：存活到次日 0 点后再留 2 分钟余量
                client.expire(key, ttl + 120)
            if count > _GUEST_QUOTA_LIMIT:
                # 超额不再累加，避免计数无上限增长
                with suppress(Exception):
                    client.decr(key)
                return RateLimitResult(False, ttl)
            return RateLimitResult(True, 0)
        except Exception as exc:  # noqa: BLE001 — Redis 异常降级为进程内计数
            logger.warning("游客日额度计数降级为进程内: %s", exc)

    with _guest_quota_memory_lock:
        if len(_guest_quota_memory) > 4096:
            # 只留当天的桶，防降级期间内存无限增长
            for stale in [k for k in _guest_quota_memory if day not in k]:
                _guest_quota_memory.pop(stale, None)
        count = _guest_quota_memory.get(key, 0) + 1
        if count > _GUEST_QUOTA_LIMIT:
            return RateLimitResult(False, ttl)
        _guest_quota_memory[key] = count
    return RateLimitResult(True, 0)


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
