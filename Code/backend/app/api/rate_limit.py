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

    ★ 2026-11-08：``X-Real-IP`` **优先于** ``X-Forwarded-For``，且只取 XFF 的
    **最后一段**以外的值也不信任——原因：``geoflow.cgdas.dpdns.org`` 走
    Cloudflare，网关（nginx）用 ``real_ip_header CF-Connecting-IP`` 把真实客户端
    地址还原进 ``$remote_addr``，再以 ``proxy_set_header X-Real-IP $remote_addr``
    传给后端，这个头是**网关自己覆盖写的**，客户端伪造无效。
    而 ``X-Forwarded-For`` 是 ``$proxy_add_x_forwarded_for`` 追加的，第一段来自
    客户端，随手就能填。
    """
    from app.core.config import settings

    if settings.trust_proxy:
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # 网关追加模式下，最后一段才是网关看到的对端地址
            return forwarded.split(",")[-1].strip()
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

#: 第二道：同一出口 IP 每日总量。第一道按浏览器访客号计，清 localStorage / 换
#: 浏览器 / 无痕窗口都能重置，所以补一道绑在网络上、换号换不掉的上限。
#: 值要比单人额度宽，否则同一个办公室/实验室共用出口的人会互相挤占。
_GUEST_IP_QUOTA_LIMIT = int(os.getenv("BACKEND_AGENT_GUEST_IP_DAILY_QUOTA", "100"))

#: 第三道：全站游客每日总量（最终熔断）。不管换多少访客号、多少 IP，总量封顶，
#: 直接卡住账单。一次提问约 1.8 万 tokens，按 0.23 元/百万 token 约 0.004 元，
#: 300 次 ≈ 1.2 元/天、36 元/月。
_GUEST_GLOBAL_QUOTA_LIMIT = int(
    os.getenv("BACKEND_AGENT_GUEST_GLOBAL_DAILY_QUOTA", "300")
)


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


def _guest_ip_quota_key(ip: str) -> str:
    """同一出口 IP 的当日计数键（换浏览器/清缓存换不掉这个桶）。"""
    day, _ttl = _beijing_day_and_ttl()
    digest = hashlib.sha1(ip.encode("utf-8")).hexdigest()[:16]
    return f"cgda:quota:guestip:{digest}:{day}"


def _guest_global_quota_key() -> str:
    """全站游客当日总量键（不分人、不分 IP，最终熔断）。"""
    day, _ttl = _beijing_day_and_ttl()
    return f"cgda:quota:guestall:{day}"


def _daily_peek(key: str) -> int:
    """只读当前计数（Redis 优先，异常降级进程内）。"""
    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    if client is not None:
        try:
            raw = client.get(key)
            return int(raw) if raw else 0
        except Exception as exc:  # noqa: BLE001 — 降级读进程内
            logger.warning("日额度读取降级为进程内: %s", exc)
    with _guest_quota_memory_lock:
        return _guest_quota_memory.get(key, 0)


def _daily_incr(key: str, ttl: int) -> int:
    """计数 +1；Redis 首次写入时把过期时间设到北京次日 0 点之后。"""
    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    if client is not None:
        try:
            count = int(client.incr(key))
            if count == 1:
                client.expire(key, ttl + 120)
            return count
        except Exception as exc:  # noqa: BLE001 — 降级为进程内计数
            logger.warning("日额度计数降级为进程内: %s", exc)
    with _guest_quota_memory_lock:
        if len(_guest_quota_memory) > 4096:
            day, _ = _beijing_day_and_ttl()
            for stale in [k for k in _guest_quota_memory if day not in k]:
                _guest_quota_memory.pop(stale, None)
        count = _guest_quota_memory.get(key, 0) + 1
        _guest_quota_memory[key] = count
        return count


#: 三道闸的标识（供中间件挑提示语、日志定位）。
QUOTA_SCOPE_VISITOR = "visitor"
QUOTA_SCOPE_IP = "ip"
QUOTA_SCOPE_GLOBAL = "global"


def _guest_quota_layers(visitor_id: str | None, ip: str) -> list[tuple[str, str, int]]:
    """三道闸的 (作用域, 计数键, 上限)，上限 <=0 的道视为关闭、直接剔除。"""
    layers = [
        (QUOTA_SCOPE_VISITOR, _guest_quota_key(visitor_id, ip), _GUEST_QUOTA_LIMIT),
        (QUOTA_SCOPE_IP, _guest_ip_quota_key(ip), _GUEST_IP_QUOTA_LIMIT),
        (QUOTA_SCOPE_GLOBAL, _guest_global_quota_key(), _GUEST_GLOBAL_QUOTA_LIMIT),
    ]
    return [item for item in layers if item[2] > 0]


def check_agent_guest_quota_layers(
    visitor_id: str | None, ip: str
) -> tuple[RateLimitResult, str | None]:
    """三道闸联合判定：**任意一道满额即拒**，三道都有余额才扣次数。

    顺序 访客号 → 同 IP → 全站。实现上先全部只读预检、通过后再统一落计数，
    避免「前一道已扣、后一道把人拦住」让用户白掉一次额度。并发抢跑时允许
    极小超发（防的是滥用，不是精确计费）。

    返回 ``(判定, 拦截作用域)``；放行时作用域为 ``None``。
    """
    _day, ttl = _beijing_day_and_ttl()
    layers = _guest_quota_layers(visitor_id, ip)
    if not layers:
        return RateLimitResult(True, 0), None
    for scope, key, limit in layers:
        if _daily_peek(key) >= limit:
            return RateLimitResult(False, ttl), scope
    for _scope, key, _limit in layers:
        _daily_incr(key, ttl)
    return RateLimitResult(True, 0), None


def peek_agent_guest_quota_layers(
    visitor_id: str | None, ip: str
) -> dict[str, tuple[int, int]]:
    """只读探三道闸各自的 ``(已用, 上限)``；已关闭的道不出现在结果里。"""
    result: dict[str, tuple[int, int]] = {}
    for scope, key, limit in _guest_quota_layers(visitor_id, ip):
        result[scope] = (_daily_peek(key), limit)
    return result


def session_role(request) -> str | None:  # type: ignore[no-untyped-def]
    """请求背后的**会话角色**；没有有效会话返回 ``None``。

    为什么要角色而不只是"有没有会话"：前端「以游客身份进入」用的是共享的 demo
    账号（``stores/auth.ts`` 的 guest 凭证），登录成功后同样拿得到一个**完全合法**
    的会话 Cookie。只看 Cookie 存在与否，这批人会被判成"已登录"从而完全不限额——
    而他们恰恰是最需要限额的那批人。实测确认过：游客登录后 ``/agent/quota``
    直接返回 ``scope=account``，20 次额度一次也用不上。

    所以判据落到角色上：``demo`` / ``guest`` 一律按游客计。会话校验异常时返回
    ``None``（fail-closed：宁可多限一次也不漏限）。
    """
    from app.core.config import settings
    from app.services.session_service import get_session

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    try:
        sess = get_session(token)
    except Exception as exc:  # noqa: BLE001 — fail-closed：当作没有会话
        logger.warning("会话校验失败，按游客处理: %s", exc)
        return None
    if not isinstance(sess, dict):
        return None
    role = str(sess.get("role") or "").strip().lower()
    return role or None


#: 哪些角色算「游客」——共享账号，必须按浏览器匿名号限次。
#:
#: ``demo`` 是前端「以游客身份进入」用的共享账号；``guest`` 留给以后真正的匿名
#: 游客角色。admin / standard 是实名账号，不占这份额度。
_GUEST_ROLES = frozenset({"demo", "guest"})


def is_guest_request(request) -> bool:  # type: ignore[no-untyped-def]
    """这个请求要不要按游客额度限次。

    * 没有会话（含伪造 Cookie 校验不过）→ 是；
    * 会话角色是 demo / guest（含「以游客身份进入」）→ 是；
    * admin / standard → 否。
    """
    role = session_role(request)
    if role is None:
        return True
    return role in _GUEST_ROLES


def has_valid_session(request) -> bool:  # type: ignore[no-untyped-def]
    """请求是否带着**有效**的登录会话（不区分角色，保持向后兼容）。

    只看 Cookie 存不存在是不够的：随手塞一个 `cgda_session=fake` 就能骗过
    「已登录」判定，从而完全跳过游客额度。

    也不用 ``resolve_credential``：它在 development 下会走 dev_bypass，把所有
    请求当成 standard 已登录——线上就跑在 development，用它等于额度永不生效。

    这里直接校验会话本身（Redis 缓存优先，未命中才落库）；校验异常时按游客
    处理，宁可多限一次也不漏限。

    ★ 2026-11-08：判定额度**不要**用这个函数，用 ``is_guest_request``。这个
    只看"有没有会话"，游客登录（demo 账号）同样算"有"，会把该限的人放过去。
    """
    from app.core.config import settings
    from app.services.session_service import get_session

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return False
    try:
        return get_session(token) is not None
    except Exception as exc:  # noqa: BLE001 — fail-closed：当作游客
        logger.warning("会话校验失败，按游客处理: %s", exc)
        return False


def beijing_quota_reset_at() -> str:
    """下一次额度恢复时刻（北京次日 0 点，ISO 8601 带时区）。"""
    now = datetime.now(UTC).astimezone(timezone(timedelta(hours=8)))
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return tomorrow.isoformat()


def peek_agent_guest_daily_quota(visitor_id: str | None, ip: str) -> tuple[int, int]:
    """只读查询**访客号那一维**的当日已用次数（不计数）。

    返回 ``(已用, 上限)``；额度关闭时返回 ``(0, 0)``。
    正式判定请看 ``peek_agent_guest_quota_layers``——它同时反映同 IP / 全站两道。
    """
    if _GUEST_QUOTA_LIMIT <= 0:
        return 0, 0
    key = _guest_quota_key(visitor_id, ip)
    return max(0, _daily_peek(key)), _GUEST_QUOTA_LIMIT


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
