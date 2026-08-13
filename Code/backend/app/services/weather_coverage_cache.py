"""天气覆盖范围缓存管理（router 与 sync service 共享）。

从 weather_router 抽取，消除 weather_sync_service → weather_router 的反向依赖。
Router 和 sync service 均从此模块导入缓存状态和失效函数。
"""

from __future__ import annotations

import logging
from contextlib import suppress

from app.core.redis_client import get_redis_client, scan_keys

logger = logging.getLogger(__name__)

# ── 缓存常量 ─────────────────────────────────────────────────────────────────

# 进程内 dict 仅作 Redis 不可用时的降级缓存
COVERAGE_CACHE: dict[str, dict] = {}
COVERAGE_CACHE_TTL_SECONDS = 600  # 10 分钟
COVERAGE_REDIS_PREFIX = "weather:coverage:"
COVERAGE_REDIS_TTL_SECONDS = 300


def invalidate_weather_coverage_cache(model: str | None = None) -> None:
    """同步成功后清除探针缓存（本地 + Redis）。

    - ``model`` 给定：删该模型的本地/Redis 键。
    - ``model`` 未给定（无参调用）：清空本地 dict，并按前缀扫描删除全部 Redis coverage 键
      （R-1 修复：此前无参版只清进程内 dict，而读端 Redis 优先，导致同步后各 worker
      仍会读到旧 coverage 直到 TTL 过期）。
    """
    client = get_redis_client()
    if model:
        COVERAGE_CACHE.pop(f"local:{model}", None)
        if client is not None:
            with suppress(Exception):  # noqa: BLE001 - best-effort
                client.delete(f"{COVERAGE_REDIS_PREFIX}{model}")
        return
    COVERAGE_CACHE.clear()
    if client is None:
        return
    try:
        keys = scan_keys(client, f"{COVERAGE_REDIS_PREFIX}*")
        if keys:
            client.delete(*keys)
    except Exception:  # noqa: BLE001 - best-effort，失效失败由 TTL 兜底
        logger.debug(
            "invalidate_weather_coverage_cache scan/delete failed", exc_info=True
        )
