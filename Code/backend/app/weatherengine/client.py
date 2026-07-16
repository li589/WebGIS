from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
import json
from pathlib import Path
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
import logging

from app.core.config import settings
from app.core.redis_client import (
    cache_get_json,
    cache_set_json,
    acquire_dedup_lock,
    release_dedup_lock,
    wait_for_dedup,
    acquire_api_slot,
    release_api_slot,
    get_redis_client,
)
import redis as redis_lib
from app.weatherengine.constants import (
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_HALF_OPEN_PROBES,
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
    OPEN_METEO_BASE_URL,
    OPEN_METEO_DAILY_API_LIMIT,
    OPEN_METEO_DAILY_API_SOFT_LIMIT,
    WeatherLayerSpec,
)
from shared.contracts.api_contracts import BoundingBox

REDIS_CACHE_PREFIX = "weather:"

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """进程内断路器：在 Open-Meteo API 连续失败时快速降级到 stale cache。

    状态机：
    - CLOSED：正常放行所有请求
    - OPEN：连续失败达到阈值后打开，RECOVERY_TIMEOUT 秒内直接拒绝请求
    - HALF_OPEN：恢复超时后放行探测请求，成功则关闭，失败则重新打开

    线程安全。通过类级别共享实例，同一进程内所有 OpenMeteoClient 实例共用同一断路器。
    """

    _CLOSED = "closed"
    _OPEN = "open"
    _HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout: float = CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        half_open_probes: int = CIRCUIT_BREAKER_HALF_OPEN_PROBES,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_probes = half_open_probes
        self._state = self._CLOSED
        self._failure_count = 0
        self._opened_at: float = 0.0
        self._half_open_probes_in_flight = 0
        self._lock = threading.Lock()

    def can_pass(self) -> bool:
        """检查是否允许请求通过。

        CLOSED：始终允许。
        OPEN：恢复超时前拒绝，超时后转为 HALF_OPEN 并放行探测。
        HALF_OPEN：达到探测上限后拒绝。
        """
        with self._lock:
            if self._state == self._CLOSED:
                return True
            if self._state == self._OPEN:
                if time.monotonic() - self._opened_at >= self._recovery_timeout:
                    self._state = self._HALF_OPEN
                    self._half_open_probes_in_flight = 1
                    logger.info("[CircuitBreaker] OPEN -> HALF_OPEN, allowing probe request")
                    return True
                return False
            # HALF_OPEN
            if self._half_open_probes_in_flight < self._half_open_probes:
                self._half_open_probes_in_flight += 1
                return True
            return False

    def wait_or_pass(self, timeout: float = 30.0) -> bool:
        """等待断路器允许请求通过，最多等待 timeout 秒。

        在 OPEN 状态下，等待恢复超时而不是立即失败。
        这避免了因断路器打开而导致大量瓦片请求同时失败，
        给 API 恢复留出时间，同时避免了线程池饥饿。
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.can_pass():
                return True
            # 等待恢复超时剩余时间，但每次最多等 2 秒以响应状态变化
            wait = min(2.0, deadline - time.monotonic())
            if wait > 0:
                time.sleep(wait)
        return False

    def record_success(self) -> None:
        """记录成功请求，关闭断路器并重置失败计数。"""
        with self._lock:
            if self._state != self._CLOSED:
                logger.info("[CircuitBreaker] %s -> CLOSED after successful request", self._state.upper())
            self._state = self._CLOSED
            self._failure_count = 0
            self._half_open_probes_in_flight = 0

    def record_failure(self) -> None:
        """记录失败请求（429/超时/5xx）。

        CLOSED：递增失败计数，达到阈值后打开断路器。
        HALF_OPEN：立即重新打开断路器。
        """
        with self._lock:
            if self._state == self._HALF_OPEN:
                self._state = self._OPEN
                self._opened_at = time.monotonic()
                self._half_open_probes_in_flight = 0
                logger.warning("[CircuitBreaker] HALF_OPEN -> OPEN (probe failed)")
                return
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = self._OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "[CircuitBreaker] CLOSED -> OPEN after %d consecutive failures",
                    self._failure_count,
                )

    @property
    def state(self) -> str:
        with self._lock:
            return self._state


class _RateLimitedResponse:
    """HTTP 响应包装器，在响应关闭时释放 API 槽位。

    确保无论响应是正常关闭还是因异常退出 with 块，槽位都会被释放。
    """

    __slots__ = ('_response',)

    def __init__(self, response):
        self._response = response

    def __enter__(self):
        self._response.__enter__()
        return self

    def __exit__(self, *exc_info):
        try:
            return self._response.__exit__(*exc_info)
        finally:
            release_api_slot()

    def read(self):
        return self._response.read()


class OpenMeteoClient:
    # 进程内共享断路器：所有实例共用同一状态，协调 API 保护
    _shared_circuit = CircuitBreaker()

    def __init__(
        self,
        cache_root: str | Path | None = None,
        *,
        base_url: str | None = None,
    ) -> None:
        self._cache_root = Path(cache_root or settings.cache_dir) / "weatherengine"
        self._cache_root.mkdir(parents=True, exist_ok=True)
        self._circuit = self._shared_circuit
        self._base_url = (base_url or OPEN_METEO_BASE_URL).rstrip("?")

    # ── 每日 API 预算管理 ──────────────────────────────────────────────
    # Open-Meteo 免费版每日限额 ~10000 次。使用 Redis 跨 worker 共享计数器，
    # 超过 DAILY_API_LIMIT 后降级为只读缓存模式，避免被 API 完全封锁。
    _BUDGET_REDIS_KEY_PREFIX = "weather:api_budget:"
    _BUDGET_REDIS_TTL = 172800  # 48 小时，确保跨时区不会过早过期

    def _budget_key(self) -> str:
        """Redis key 按日期分组，UTC 午夜自动重置"""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{self._BUDGET_REDIS_KEY_PREFIX}{date_str}"

    def _budget_remaining(self) -> int | None:
        """返回今日剩余 API 调用次数，None 表示 Redis 不可用（不限制）"""
        client = get_redis_client()
        if client is None:
            return None
        try:
            key = self._budget_key()
            used = int(client.get(key) or 0)
            return max(0, OPEN_METEO_DAILY_API_LIMIT - used)
        except (ValueError, TypeError, redis_lib.RedisError):
            return None

    # ── Public accessors（供 Provider 包装器使用，避免访问私有成员） ────────

    @property
    def circuit_state(self) -> str:
        """断路器当前状态（closed / open / half_open）。"""
        return self._circuit.state

    @property
    def base_url(self) -> str:
        """API 基础 URL。"""
        return self._base_url

    @base_url.setter
    def base_url(self, value: str) -> None:
        """更新 API 基础 URL（运行时配置覆盖时使用）。"""
        self._base_url = value.rstrip("?")

    def budget_remaining(self) -> int | None:
        """公开方法：返回今日剩余 API 调用次数。"""
        return self._budget_remaining()

    def _budget_record_call(self) -> None:
        """记录一次 API 调用，递增 Redis 计数器"""
        client = get_redis_client()
        if client is None:
            return
        try:
            key = self._budget_key()
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, self._BUDGET_REDIS_TTL)
            used = pipe.execute()[0]
            if used == OPEN_METEO_DAILY_API_SOFT_LIMIT:
                logger.warning(
                    "[OpenMeteoClient] daily API budget soft limit reached: used=%d/%d",
                    used, OPEN_METEO_DAILY_API_LIMIT,
                )
            elif used == OPEN_METEO_DAILY_API_LIMIT:
                logger.error(
                    "[OpenMeteoClient] daily API budget EXHAUSTED: used=%d/%d — switching to cache-only mode",
                    used, OPEN_METEO_DAILY_API_LIMIT,
                )
        except redis_lib.RedisError:
            pass

    def _read_cached_payload(
        self,
        cache_path: Path,
        *,
        now: datetime,
    ) -> tuple[dict[str, Any] | None, bool]:
        if not cache_path.exists():
            return None, False
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            expires_raw = cached.get("expires_at")
            if isinstance(expires_raw, (int, float)):
                expires_at = datetime.fromtimestamp(expires_raw, tz=timezone.utc)
            else:
                expires_at = datetime.fromisoformat(expires_raw)
            payload = cached.get("payload")
            if not isinstance(payload, dict):
                return None, False
            return payload, expires_at > now
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None, False

    def fetch_point_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_spec: WeatherLayerSpec,
        model: str,
        forecast_hours: int,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        cache_key = self._build_cache_key(
            latitude=latitude,
            longitude=longitude,
            layer_id=layer_spec.layer_id,
            model=model,
            forecast_hours=forecast_hours,
            pressure_levels=pressure_levels,
        )
        redis_key = f"{REDIS_CACHE_PREFIX}point:{cache_key}"
        cache_path = self._cache_root / f"{cache_key}.json"
        now = datetime.now(timezone.utc)

        # 1. Check Redis cache first (fast, cross-worker)
        redis_payload = cache_get_json(redis_key)
        if redis_payload is not None:
            return redis_payload, "hit"

        # 2. Check file cache
        cached_payload, cache_is_fresh = self._read_cached_payload(cache_path, now=now)
        if cache_is_fresh and cached_payload is not None:
            # Backfill Redis from file cache
            cache_set_json(redis_key, cached_payload, max(60, ttl_seconds))
            return cached_payload, "hit"

        # Circuit breaker: if OPEN, wait for recovery instead of failing immediately
        if not self._circuit.can_pass():
            if cached_payload is not None:
                logger.warning(
                    "[OpenMeteoClient] circuit open, returning stale cache: lat=%.4f lon=%.4f layer=%s",
                    latitude, longitude, layer_spec.layer_id,
                )
                return cached_payload, "circuit-open-stale"
            if not self._circuit.wait_or_pass(timeout=30.0):
                raise HTTPError(self._base_url, 503, "Circuit breaker open", None, None)

        # 3. Cross-worker request deduplication
        dedup_lock_key = f"{REDIS_CACHE_PREFIX}lock:point:{cache_key}"
        if not acquire_dedup_lock(dedup_lock_key, ttl_seconds=60):
            # Another worker is fetching this data — wait and re-check cache
            if wait_for_dedup(dedup_lock_key, timeout_seconds=30.0):
                redis_payload = cache_get_json(redis_key)
                if redis_payload is not None:
                    return redis_payload, "dedup-hit"
                cached_payload, cache_is_fresh = self._read_cached_payload(cache_path, now=now)
                if cache_is_fresh and cached_payload is not None:
                    return cached_payload, "dedup-hit"

        current_fields = sorted(set(layer_spec.current_fields))
        hourly_fields = sorted(set(layer_spec.hourly_fields))

        # 每日 API 预算检查：超限时降级为 stale cache，避免被 Open-Meteo 完全封锁
        remaining = self._budget_remaining()
        if remaining is not None and remaining <= 0:
            logger.warning("[OpenMeteoClient] daily API budget exhausted for point forecast: lat=%.4f lon=%.4f", latitude, longitude)
            if cached_payload is not None:
                return cached_payload, "budget-exhausted-stale"
            raise HTTPError(self._base_url, 503, "Daily API budget exhausted", None, None)

        query_dict: dict[str, str] = {
            "latitude": f"{latitude:.4f}",
            "longitude": f"{longitude:.4f}",
            "timezone": "auto",
            "forecast_days": 2,
            "current": ",".join(current_fields),
            "hourly": ",".join(hourly_fields),
            "models": model,
        }
        # 气压层变量：layer_spec.notes 第三项可指定需要的气压层（如 850/700/500/200 hPa）
        if pressure_levels:
            query_dict["pressure_levels"] = ",".join(str(level) for level in pressure_levels)
        query = urlencode(query_dict)
        # HTTP 错误处理 + 瞬态失败重试：429/5xx 与 URLError 重试，4xx(非429) 立即抛出
        max_attempts = 5
        backoff = 2
        payload: dict[str, Any] | None = None
        for attempt in range(max_attempts):
            try:
                with self._rate_limited_urlopen(f"{self._base_url}?{query}", timeout=20) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self._circuit.record_success()
                self._budget_record_call()
                break
            except HTTPError as exc:
                # 429/5xx 视为 API 故障，记录到断路器；4xx 客户端错误不计入
                if exc.code == 429 or exc.code >= 500:
                    self._circuit.record_failure()
                if exc.code == 429:
                    # 限流：优先使用 stale cache，否则指数退避重试
                    if cached_payload is not None:
                        logger.warning(
                            "[OpenMeteoClient] point forecast 429 falling back to stale cache: lat=%.4f lon=%.4f layer=%s",
                            latitude, longitude, layer_spec.layer_id,
                        )
                        return cached_payload, "stale-hit"
                    retry_wait = max(backoff * 2, 5)
                    logger.info("[OpenMeteoClient] point forecast rate limited (429), waiting %ds... attempt=%d/%d", retry_wait, attempt + 1, max_attempts)
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(retry_wait)
                    backoff *= 2
                    continue
                if cached_payload is not None and exc.code >= 500:
                    logger.warning(
                        "[OpenMeteoClient] point forecast falling back to stale cache: code=%d lat=%.4f lon=%.4f layer=%s",
                        exc.code,
                        latitude,
                        longitude,
                        layer_spec.layer_id,
                    )
                    return cached_payload, "stale-hit"
                # 4xx 客户端错误（非 429）不重试，直接抛出
                if exc.code < 500 or attempt == max_attempts - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
            except URLError:
                self._circuit.record_failure()
                if cached_payload is not None:
                    logger.warning(
                        "[OpenMeteoClient] point forecast falling back to stale cache after URL error: lat=%.4f lon=%.4f layer=%s",
                        latitude,
                        longitude,
                        layer_spec.layer_id,
                    )
                    return cached_payload, "stale-hit"
                if attempt == max_attempts - 1:
                    raise
                time.sleep(backoff)
                backoff *= 2
        # payload 在 break 后必已赋值；此处仅为类型检查兜底
        assert payload is not None

        # 原子写入缓存：先写临时文件再 rename，避免半写文件被并发读取
        cache_tmp_path = cache_path.with_suffix(".tmp")
        cache_tmp_path.parent.mkdir(parents=True, exist_ok=True)
        cache_tmp_path.write_text(
            json.dumps(
                {
                    "expires_at": datetime.fromtimestamp(now.timestamp() + max(60, ttl_seconds), tz=timezone.utc).isoformat(),
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cache_tmp_path.replace(cache_path)
        # Write to Redis cache for fast cross-worker access
        cache_set_json(redis_key, payload, max(60, ttl_seconds))
        release_dedup_lock(dedup_lock_key)
        return payload, "miss"

    def _build_cache_key(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_id: str,
        model: str,
        forecast_hours: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> str:
        lat_key = str(round(latitude, 3)).replace("-", "m").replace(".", "_")
        lon_key = str(round(longitude, 3)).replace("-", "m").replace(".", "_")
        model_key = model.replace("/", "_").replace(":", "_")
        pl_key = "-pl" + "_".join(str(p) for p in pressure_levels) if pressure_levels else ""
        return f"{layer_id}-{model_key}-{forecast_hours}-{lat_key}-{lon_key}{pl_key}"

    def _rate_limited_urlopen(self, url: str, timeout: float = 30):
        """获取全局 API 槽位后调用 urlopen，确保异常时槽位被释放。

        - urlopen 失败 → 立即释放槽位并 re-raise
        - urlopen 成功 → 槽位在 _RateLimitedResponse 的 __exit__ 中释放
        """
        if not acquire_api_slot(timeout=30.0):
            raise HTTPError(url, 503, "API rate limit: too many concurrent requests", None, None)
        try:
            resp = urlopen(url, timeout=timeout)
            return _RateLimitedResponse(resp)
        except BaseException:
            release_api_slot()
            raise

    def fetch_grid_forecast(
        self,
        *,
        bbox: BoundingBox,
        resolution: float = 0.25,
        layer_spec: WeatherLayerSpec,
        model: str,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """
        批量获取网格化天气预报数据。

        Args:
            bbox: 地理边界框
            resolution: 网格分辨率（度），默认 0.25（约 25km）
            layer_spec: 图层规格定义
            model: 预报模型
            ttl_seconds: 缓存有效期（秒）
            pressure_levels: 气压层（hPa），如 (850, 500, 200)

        Returns:
            (grid_data, cache_status): 网格数据字典和缓存状态（"hit" 或 "miss"）

        返回格式:
            {
                "grid": {
                    "bbox": {"west": float, "south": float, "east": float, "north": float},
                    "rows": int,
                    "cols": int,
                    "resolution": float,
                    "lats": [float, ...],
                    "lons": [float, ...],
                },
                "data": {
                    "current": {
                        "windspeed_10m": [float, ...],
                        "winddirection_10m": [float, ...],
                        ...
                    },
                    "hourly": {...}
                }
            }
        """
        cache_key = self._build_grid_cache_key(
            bbox=bbox,
            resolution=resolution,
            layer_id=layer_spec.layer_id,
            model=model,
            pressure_levels=pressure_levels,
        )
        redis_key = f"{REDIS_CACHE_PREFIX}grid:{cache_key}"
        cache_path = self._cache_root / f"grid-{cache_key}.json"
        now = datetime.now(timezone.utc)

        # 1. Check Redis cache first (fast, cross-worker)
        redis_payload = cache_get_json(redis_key)
        if redis_payload is not None:
            return redis_payload, "hit"

        # 2. Check file cache
        cached_payload, cache_is_fresh = self._read_cached_payload(cache_path, now=now)
        if cache_is_fresh and cached_payload is not None:
            cache_set_json(redis_key, cached_payload, max(60, ttl_seconds))
            return cached_payload, "hit"

        # Circuit breaker: if OPEN, wait for recovery instead of failing immediately.
        # 使用 wait_or_pass 而非 can_pass 避免断路器打开时大面积瓦片请求同时失败，
        # 给 API 恢复留出时间。有 stale cache 时仍直接返回。
        if not self._circuit.can_pass():
            if cached_payload is not None:
                logger.warning(
                    "[OpenMeteoClient] circuit open, returning stale grid cache: layer=%s",
                    layer_spec.layer_id,
                )
                return cached_payload, "circuit-open-stale"
            # 无缓存时等待断路器恢复（最多 30 秒），避免立即失败
            if not self._circuit.wait_or_pass(timeout=30.0):
                logger.error(
                    "[OpenMeteoClient] circuit breaker did not recover within timeout: layer=%s",
                    layer_spec.layer_id,
                )
                raise HTTPError(self._base_url, 503, "Circuit breaker open", None, None)

        # 3. Cross-worker request deduplication
        dedup_lock_key = f"{REDIS_CACHE_PREFIX}lock:grid:{cache_key}"
        if not acquire_dedup_lock(dedup_lock_key, ttl_seconds=120):
            if wait_for_dedup(dedup_lock_key, timeout_seconds=60.0):
                redis_payload = cache_get_json(redis_key)
                if redis_payload is not None:
                    return redis_payload, "dedup-hit"
                cached_payload, cache_is_fresh = self._read_cached_payload(cache_path, now=now)
                if cache_is_fresh and cached_payload is not None:
                    return cached_payload, "dedup-hit"

        # 计算网格点数
        lat_span = bbox.north - bbox.south
        lon_span = bbox.east - bbox.west

        # 每日 API 预算检查：超限时降级为 stale cache，避免被 Open-Meteo 完全封锁
        remaining = self._budget_remaining()
        if remaining is not None and remaining <= 0:
            logger.warning("[OpenMeteoClient] daily API budget exhausted for grid forecast: layer=%s", layer_spec.layer_id)
            if cached_payload is not None:
                return cached_payload, "budget-exhausted-stale"
            raise HTTPError(self._base_url, 503, "Daily API budget exhausted", None, None)

        rows = max(1, ceil(lat_span / resolution))
        cols = max(1, ceil(lon_span / resolution))
        total_points = rows * cols

        # Open-Meteo 批量请求限制：单次最多 150 个点（URL 长度约 2500 字符，避免 414 错误）
        batch_limit = 150

        # [OpenMeteoClient] 调试：打印网格计算
        logger.info(
            "[OpenMeteoClient] fetch_grid_forecast: layer=%s bbox=(%.4f,%.4f,%.4f,%.4f) span=%.4fx%.4f resolution=%.2f rows=%d cols=%d total_points=%d batches=%d",
            layer_spec.layer_id, bbox.west, bbox.south, bbox.east, bbox.north,
            lon_span, lat_span, resolution, rows, cols, total_points,
            (total_points + batch_limit - 1) // batch_limit,
        )

        all_current_data: dict[str, list[float | None]] = {}
        all_hourly_data: dict[str, list[list[float | None]]] = {}

        # 构建经纬度数组（使用网格中心点）
        lat_step = lat_span / rows
        lon_step = lon_span / cols
        lats = [bbox.south + (i + 0.5) * lat_step for i in range(rows)]
        lons = [bbox.west + (j + 0.5) * lon_step for j in range(cols)]

        # 准备请求字段
        current_fields = sorted(set(layer_spec.current_fields))
        hourly_fields = sorted(set(layer_spec.hourly_fields))

        # 全局 API 限流在 _rate_limited_urlopen 中按 HTTP 请求粒度获取/释放

        # 分批请求
        for batch_idx, batch_start in enumerate(range(0, total_points, batch_limit)):
            # Circuit breaker: 如果 API 在批次中途打开断路器，等待恢复而非立即失败
            if not self._circuit.can_pass():
                logger.warning(
                    "[OpenMeteoClient] circuit open during grid fetch, waiting at batch %d",
                    batch_idx,
                )
                if cached_payload is not None:
                    return cached_payload, "circuit-open-stale"
                if not self._circuit.wait_or_pass(timeout=30.0):
                    raise HTTPError(self._base_url, 503, "Circuit breaker open during grid fetch", None, None)

            # 从第二批开始添加延迟，避免 Open-Meteo 免费 API 限流 (429)
            if batch_idx > 0:
                time.sleep(1.0)
            batch_end = min(batch_start + batch_limit, total_points)
            batch_lats = lats * cols  # 展平为 1D 数组
            batch_lons = lons * rows

            # 构建当前批次的经纬度数组
            batch_lats = []
            batch_lons = []
            for i in range(rows):
                for j in range(cols):
                    idx = i * cols + j
                    if batch_start <= idx < batch_end:
                        batch_lats.append(lats[i])
                        batch_lons.append(lons[j])

            query_dict: dict[str, str] = {
                "latitude": ",".join(f"{lat:.4f}" for lat in batch_lats),
                "longitude": ",".join(f"{lon:.4f}" for lon in batch_lons),
                "timezone": "auto",
                "forecast_days": "2",
                "current": ",".join(current_fields),
                "hourly": ",".join(hourly_fields),
                "models": model,
            }
            if pressure_levels:
                query_dict["pressure_levels"] = ",".join(str(level) for level in pressure_levels)

            query = urlencode(query_dict)

            # HTTP 请求（带重试，对 429 限流有更多容忍）
            max_attempts = 5
            backoff = 2
            batch_payload: dict[str, Any] | None = None
            for attempt in range(max_attempts):
                try:
                    # [OpenMeteoClient] 调试：打印请求信息
                    logger.info(
                        "[OpenMeteoClient] HTTP request: batch=%d-%d/%d points=%d url_len=%d attempt=%d",
                        batch_start, batch_end, total_points, len(batch_lats), len(query), attempt + 1,
                    )
                    with self._rate_limited_urlopen(f"{self._base_url}?{query}", timeout=30) as response:
                        raw_data = response.read().decode("utf-8")
                        batch_payload = json.loads(raw_data)
                    # [OpenMeteoClient] 调试：打印响应信息
                    resp_type = "list" if isinstance(batch_payload, list) else "dict"
                    resp_len = len(batch_payload) if isinstance(batch_payload, list) else 1
                    logger.info(
                        "[OpenMeteoClient] HTTP response: status=OK type=%s points=%d size=%d bytes",
                        resp_type, resp_len, len(raw_data),
                    )
                    self._circuit.record_success()
                    self._budget_record_call()
                    break
                except HTTPError as exc:
                    logger.warning("[OpenMeteoClient] HTTP error: code=%d attempt=%d/%d", exc.code, attempt + 1, max_attempts)
                    # 429/5xx 视为 API 故障，记录到断路器；4xx 客户端错误不计入
                    if exc.code == 429 or exc.code >= 500:
                        self._circuit.record_failure()
                    if exc.code == 429:
                        # 限流：使用更长退避时间
                        retry_wait = max(backoff * 2, 5)
                        logger.info("[OpenMeteoClient] Rate limited (429), waiting %ds...", retry_wait)
                        if attempt == max_attempts - 1:
                            raise
                        time.sleep(retry_wait)
                        continue
                    if exc.code < 500 or attempt == max_attempts - 1:
                        raise
                    time.sleep(backoff)
                    backoff *= 2
                except URLError:
                    logger.warning("[OpenMeteoClient] URL error: attempt=%d/%d", attempt + 1, max_attempts)
                    self._circuit.record_failure()
                    if attempt == max_attempts - 1:
                        raise
                    time.sleep(backoff)
                    backoff *= 2

            assert batch_payload is not None

            # Open-Meteo 多点请求返回 JSON 数组（每个元素对应一个点），
            # 单点请求返回字典。统一处理为列表。
            if isinstance(batch_payload, list):
                point_responses = batch_payload
            else:
                point_responses = [batch_payload]

            # 解析批量响应并重新组装到完整网格
            for idx_offset, point_resp in enumerate(point_responses):
                actual_idx = batch_start + idx_offset
                if actual_idx >= total_points:
                    break
                if not isinstance(point_resp, dict):
                    continue
                point_current = point_resp.get("current") or {}
                for field in current_fields:
                    if field not in all_current_data:
                        all_current_data[field] = [None] * total_points
                    val = point_current.get(field)
                    if val is not None:
                        all_current_data[field][actual_idx] = val

                point_hourly = point_resp.get("hourly") or {}
                hourly_times = point_hourly.get("time", [])
                for field in hourly_fields:
                    if field not in all_hourly_data:
                        all_hourly_data[field] = [[] for _ in range(total_points)]
                    field_values = point_hourly.get(field, [])
                    for time_idx in range(len(hourly_times)):
                        val = field_values[time_idx] if time_idx < len(field_values) else None
                        if len(all_hourly_data[field][actual_idx]) <= time_idx:
                            all_hourly_data[field][actual_idx].append(val)
                        else:
                            all_hourly_data[field][actual_idx][time_idx] = val

        # 构建返回数据
        grid_data = {
            "grid": {
                "bbox": {
                    "west": bbox.west,
                    "south": bbox.south,
                    "east": bbox.east,
                    "north": bbox.north,
                },
                "rows": rows,
                "cols": cols,
                "resolution": resolution,
                "lats": lats,
                "lons": lons,
            },
            "data": {
                "current": all_current_data,
                "hourly": all_hourly_data,
            },
        }

        # 写入缓存
        cache_tmp_path = cache_path.with_suffix(".tmp")
        cache_tmp_path.parent.mkdir(parents=True, exist_ok=True)
        cache_tmp_path.write_text(
            json.dumps(
                {
                    "expires_at": datetime.fromtimestamp(now.timestamp() + max(60, ttl_seconds), tz=timezone.utc).isoformat(),
                    "payload": grid_data,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cache_tmp_path.replace(cache_path)
        # Write to Redis cache for fast cross-worker access
        cache_set_json(redis_key, grid_data, max(60, ttl_seconds))
        release_dedup_lock(dedup_lock_key)

        # [OpenMeteoClient] 调试：打印最终数据汇总
        current_fields_summary = {k: f"{len(v)} values, non_none={sum(1 for x in v if x is not None)}" for k, v in all_current_data.items()}
        logger.info(
            "[OpenMeteoClient] fetch_grid_forecast done: rows=%d cols=%d lats=[%.4f..%.4f] lons=[%.4f..%.4f] current_fields=%s",
            rows, cols, lats[0], lats[-1], lons[0], lons[-1], current_fields_summary,
        )

        return grid_data, "miss"

    def _build_grid_cache_key(
        self,
        *,
        bbox: BoundingBox,
        resolution: float,
        layer_id: str,
        model: str,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> str:
        """构建网格数据的缓存键。"""
        # 边界取整到 0.01 度，避免细微差异导致缓存失效
        west = round(bbox.west, 2)
        south = round(bbox.south, 2)
        east = round(bbox.east, 2)
        north = round(bbox.north, 2)
        res_key = str(round(resolution, 3)).replace(".", "_")
        model_key = model.replace("/", "_").replace(":", "_")
        pl_key = "-pl" + "_".join(str(p) for p in pressure_levels) if pressure_levels else ""
        return f"{layer_id}-{model_key}-{res_key}-{west}_{south}_{east}_{north}{pl_key}"
