"""天气数据标准瓦片服务。

提供基于 Web Mercator z/x/y 的 GeoJSON 瓦片接口，供前端按瓦片请求天气数据。
职责：
1. 瓦片坐标与 EPSG:4326 bbox 转换。
2. 瓦片级 Redis/内存缓存。
3. 全局并发槽位控制（避免 Open-Meteo 限流）。
4. 经 fetch_gateway（WeatherProviderRegistry）拉取网格并生成 GeoJSON。
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from functools import lru_cache
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError

from app.weatherengine.default_model import weather_default_model
from app.core.redis_client import cache_get_json, cache_set_json
from app.services.effective_config import get_weather_cache_ttl_seconds
from app.weatherengine.constants import WEATHER_LAYER_SPECS, WeatherLayerSpec
from app.weatherengine.field_mapping import point_in_tile_half_open
from app.weatherengine.fetch_gateway import fetch_grid_forecast
from shared.contracts.api_contracts import BoundingBox

if TYPE_CHECKING:
    from app.weatherengine.service import WeatherEngineService

logger = logging.getLogger(__name__)

# Web Mercator 最大纬度（投影边界）
_WEB_MERCATOR_MAX_LAT = 85.0511287798066

# 瓦片 zoom 范围
_MIN_TILE_ZOOM = 0
_MAX_TILE_ZOOM = 12

# 全局并发槽位：与前端保持一致，减少 Open-Meteo 429 概率
_DEFAULT_MAX_CONCURRENT_TILE_REQUESTS = 4

# 内存 LRU 缓存上限（每个服务实例）
_IN_MEMORY_TILE_CACHE_MAX = 256

# 瓦片 Redis 缓存键前缀
_TILE_REDIS_KEY_PREFIX = "weather:tile:"


class TileDataEmptyError(Exception):
    """上游网格主变量全 null（本地库未 sync 该变量 / 模型不支持该变量）。

    与 503（服务不可达，前端应退避重试）区分：路由层返回 422，
    前端识别为 data-empty 后停止重排，避免「无数据图层一直加载」。
    """


def normalize_provider_id(provider_id: str | None) -> str:
    """Normalize provider for cache keys / query params (auto = registry priority)."""
    if provider_id is None:
        return "auto"
    pid = str(provider_id).strip()
    if not pid or pid.lower() in {"auto", "default"}:
        return "auto"
    return pid


def tile_key(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    hour: int,
    model: str | None,
    provider_id: str | None = None,
) -> str:
    """生成瓦片缓存键（前后端保持一致；含 provider_id 避免换源脏缓存）。"""
    model_part = model.replace("/", "_").replace(":", "_") if model else "default"
    provider_part = (
        normalize_provider_id(provider_id).replace("/", "_").replace(":", "_")
    )
    return (
        f"{_TILE_REDIS_KEY_PREFIX}{layer_id}:z{z}:x{x}:y{y}:h{hour}"
        f":m{model_part}:p{provider_part}"
    )


def tile_bbox(z: int, x: int, y: int) -> BoundingBox:
    """Web Mercator z/x/y → EPSG:4326 bbox（西南东北）。"""
    n = 2**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    def _tile_y_to_lat(y_tile: int) -> float:
        lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y_tile / n)))
        return lat_rad * 180.0 / math.pi

    north = _tile_y_to_lat(y)
    south = _tile_y_to_lat(y + 1)

    # 限制在有效地理范围内
    north = min(_WEB_MERCATOR_MAX_LAT, max(-_WEB_MERCATOR_MAX_LAT, north))
    south = min(_WEB_MERCATOR_MAX_LAT, max(-_WEB_MERCATOR_MAX_LAT, south))

    return BoundingBox(
        west=west,
        south=south,
        east=east,
        north=north,
        crs="EPSG:4326",
    )


def lonlat_to_tile(z: int, longitude: float, latitude: float) -> tuple[int, int]:
    """EPSG:4326 → Web Mercator 瓦片坐标 (x, y)。"""
    n = 2**z
    lon = ((longitude + 180.0) % 360.0 + 360.0) % 360.0 - 180.0
    lat = max(-_WEB_MERCATOR_MAX_LAT, min(_WEB_MERCATOR_MAX_LAT, latitude))
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi)
        / 2.0
        * n
    )
    return x % n, max(0, min(n - 1, y))


def zoom_to_resolution(z: int) -> float:
    """根据瓦片 zoom 固定分辨率，保证相邻瓦片分辨率一致。

    低 zoom 级别使用粗分辨率以控制每瓦片请求点数，
    避免触发 Open-Meteo 免费层 429 限流（单请求 ~10000 坐标上限）。
    z=1 瓦片覆盖 180°x180°，resolution=10.0 时约 18x18=324 点。
    """
    if z <= 1:
        return 10.0
    if z <= 2:
        return 5.0
    if z <= 3:
        return 2.5
    if z <= 5:
        return 1.0
    if z <= 7:
        return 0.5
    return 0.25


def _stamp_and_clip_tile_geojson(
    geojson: dict[str, Any],
    *,
    bbox: BoundingBox,
    resolution: float,
) -> dict[str, Any]:
    """为要素写入 resolution，并按半开 bbox 裁掉越界点（防旧缓存/上游越界）。"""
    features = geojson.get("features")
    if not isinstance(features, list):
        return geojson
    clipped: list[Any] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if (
            geom.get("type") == "Point"
            and isinstance(coords, (list, tuple))
            and len(coords) >= 2
        ):
            lon = float(coords[0])
            lat = float(coords[1])
            if not point_in_tile_half_open(
                lon,
                lat,
                west=bbox.west,
                south=bbox.south,
                east=bbox.east,
                north=bbox.north,
            ):
                continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            props = {}
            feature["properties"] = props
        props["resolution"] = resolution
        props["grid_resolution"] = resolution
        clipped.append(feature)
    geojson["features"] = clipped
    return geojson


def _clamp_hour(hour: int | None, max_hours: int = 47) -> int:
    """将 hour 限制在有效预报小时范围内。"""
    if hour is None:
        return 0
    return max(0, min(max_hours, hour))


def _grid_data_for_hour(grid_data: dict[str, Any], hour: int) -> dict[str, Any]:
    """将网格数据调整为指定预报小时。

    fetch_grid_forecast 返回的 grid_data 包含 current（当前小时）和 hourly（逐小时）。
    当 hour > 0 时，将 current 段替换为 hourly 段中对应小时的值，使 build_*_geojson_from_grid
    能直接复用。

    注意：hourly 中每个字段的 values 是 total_points 个时间序列的列表，
    需要为每个点取第 hour 个时间步，而不是取第 hour 个点的时间序列。
    """
    # hour <= 0 时使用 current；若 current 目标字段全 null（气压层偶发只在 hourly），
    # 提升 hourly[0]。hour > 0 时从 hourly 取对应时间步替换 current。
    hourly = grid_data.get("data", {}).get("hourly", {})
    current = grid_data.get("data", {}).get("current", {})
    if hour <= 0:
        needs_backfill = False
        if isinstance(current, dict) and hourly:
            for key, values in current.items():
                if (
                    isinstance(values, list)
                    and values
                    and not any(v is not None for v in values)
                    and key in hourly
                ):
                    needs_backfill = True
                    break
        if not needs_backfill:
            return grid_data
        hour = 0
        logger.info(
            "[WeatherTileService] current all-null for some fields — promoting hourly[0]",
        )

    if not hourly:
        logger.warning(
            "[WeatherTileService] hourly data not available for hour=%d, falling back to current",
            hour,
        )
        return grid_data

    # 检查 hourly 是否有足够时间步
    first_series = next(iter(hourly.values()), None)
    if not isinstance(first_series, list) or len(first_series) == 0:
        logger.warning(
            "[WeatherTileService] hourly data empty for hour=%d, falling back to current",
            hour,
        )
        return grid_data

    # 第一个点的时间序列长度表示可用时间步数
    first_point_series = first_series[0]
    if not isinstance(first_point_series, list) or hour >= len(first_point_series):
        available_steps = (
            len(first_point_series) if isinstance(first_point_series, list) else 0
        )
        logger.warning(
            "[WeatherTileService] hourly data only has %d steps, requested hour=%d, falling back to current",
            available_steps,
            hour,
        )
        return grid_data

    # 构建 current 的副本：为每个点取第 hour 个时间步的值
    new_current: dict[str, Any] = {}
    for key, values in hourly.items():
        if isinstance(values, list):
            new_current[key] = []
            for point_values in values:
                if isinstance(point_values, list) and hour < len(point_values):
                    new_current[key].append(point_values[hour])
                else:
                    new_current[key].append(None)
        else:
            new_current[key] = values

    new_data = {
        **grid_data,
        "data": {
            **grid_data.get("data", {}),
            "current": new_current,
        },
    }
    return new_data


class WeatherTileService:
    """天气 GeoJSON 瓦片服务。"""

    def __init__(
        self,
        *,
        engine_service: "WeatherEngineService" | None = None,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT_TILE_REQUESTS,
        in_memory_cache_max: int = _IN_MEMORY_TILE_CACHE_MAX,
    ) -> None:
        # 延迟导入以避免 WeatherEngineService ↔ tile_service 循环依赖
        from app.weatherengine.service import WeatherEngineService

        self._engine = engine_service or WeatherEngineService()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # sync workflow（weather_tile_render）与 async REST 共用同一并发上限，避免绕过闸
        self._sync_semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._in_memory_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._in_memory_cache_max = in_memory_cache_max

    def _build_geojson(
        self,
        grid_data: dict[str, Any],
        layer_id: str,
        layer_spec: WeatherLayerSpec,
    ) -> dict[str, Any]:
        """根据图层类型调用对应的 build_*_geojson_from_grid。"""
        if layer_id.startswith("wind-field"):
            return self._engine.build_wind_geojson_from_grid(grid_data, layer_id)
        if layer_id.startswith("temperature"):
            return self._engine.build_temperature_geojson_from_grid(grid_data, layer_id)
        if layer_id == "precipitation":
            return self._engine.build_precipitation_geojson_from_grid(
                grid_data, layer_id
            )
        if layer_id == "humidity":
            return self._engine.build_humidity_geojson_from_grid(grid_data, layer_id)
        if layer_id == "pressure":
            return self._engine.build_pressure_geojson_from_grid(grid_data, layer_id)
        if layer_id == "visibility":
            return self._engine.build_visibility_geojson_from_grid(grid_data, layer_id)
        if layer_id == "cloud-cover":
            return self._engine.build_cloud_cover_geojson_from_grid(grid_data, layer_id)
        if layer_id == "dewpoint":
            return self._engine.build_dewpoint_geojson_from_grid(grid_data, layer_id)

        raise ValueError(f"Unsupported weather tile layer: {layer_id}")

    def generate_tile_payload(
        self,
        layer_id: str,
        layer_spec: WeatherLayerSpec,
        z: int,
        x: int,
        y: int,
        hour: int,
        model: str | None,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        """同步生成瓦片 GeoJSON（不含服务级缓存 / 并发闸）。

        REST 热路径与 ``weather_tile_render`` 节点共用此实现，保证网格与元数据一致。
        """
        bbox = tile_bbox(z, x, y)
        resolution = zoom_to_resolution(z)

        logger.info(
            "[WeatherTileService] generating tile layer=%s z=%d x=%d y=%d hour=%d resolution=%.2f provider=%s bbox=(%.4f,%.4f,%.4f,%.4f)",
            layer_id,
            z,
            x,
            y,
            hour,
            resolution,
            normalize_provider_id(provider_id),
            bbox.west,
            bbox.south,
            bbox.east,
            bbox.north,
        )

        # 与 /grid、DAG grid_fetch 共用 OpenMeteoClient grid Redis/文件缓存；
        # 同 bbox+resolution 命中时不会连环打上游。
        resolved_model = model or layer_spec.preferred_model or weather_default_model()
        try:
            grid_data, cache_status, resolved_provider = fetch_grid_forecast(
                layer_id=layer_id,
                bbox=bbox,
                resolution=resolution,
                model=resolved_model,
                layer_spec=layer_spec,
                provider_id=provider_id,
            )
        except HTTPError as exc:
            # client 的「主变量全 null」422 → 转为专用异常，让路由层透传 422，
            # 避免被统一包成 503 导致前端无限重试。
            if exc.code == 422:
                raise TileDataEmptyError(str(exc)) from exc
            raise
        grid_data_for_hour = _grid_data_for_hour(grid_data, hour)
        geojson = self._build_geojson(grid_data_for_hour, layer_id, layer_spec)
        effective_res = float(
            (grid_data.get("grid") or {}).get("resolution") or resolution
        )
        geojson = _stamp_and_clip_tile_geojson(
            geojson,
            bbox=bbox,
            resolution=effective_res,
        )

        geojson["_tile_meta"] = {
            "layer_id": layer_id,
            "z": z,
            "x": x,
            "y": y,
            "hour": hour,
            "model": resolved_model,
            "provider_id": resolved_provider,
            "requested_provider": normalize_provider_id(provider_id),
            "resolution": effective_res,
            "bbox": bbox.model_dump(mode="json"),
            "feature_count": len(geojson.get("features", [])),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "upstream_cache_status": cache_status,
        }

        logger.info(
            "[WeatherTileService] tile generated layer=%s z=%d x=%d y=%d hour=%d features=%d upstream_cache=%s provider=%s",
            layer_id,
            z,
            x,
            y,
            hour,
            len(geojson.get("features", [])),
            cache_status,
            resolved_provider,
        )
        return geojson

    async def _generate_tile(
        self,
        layer_id: str,
        layer_spec: WeatherLayerSpec,
        z: int,
        x: int,
        y: int,
        hour: int,
        model: str | None,
        provider_id: str | None = None,
    ) -> dict[str, Any]:
        """在线程池中执行同步生成，避免阻塞事件循环。"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.generate_tile_payload(
                layer_id=layer_id,
                layer_spec=layer_spec,
                z=z,
                x=x,
                y=y,
                hour=hour,
                model=model,
                provider_id=provider_id,
            ),
        )

    def get_or_generate_tile_sync(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        *,
        hour: int | None = None,
        model: str | None = None,
        provider_id: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """同步版 get_tile：供 workflow 节点复用同一套缓存与生成逻辑。"""
        hour = _clamp_hour(hour)
        layer_spec = WEATHER_LAYER_SPECS.get(layer_id)
        if layer_spec is None:
            raise ValueError(f"Unsupported weather layer: {layer_id}")
        model = model or layer_spec.preferred_model or weather_default_model()
        key = tile_key(layer_id, z, x, y, hour, model, provider_id)

        if not (_MIN_TILE_ZOOM <= z <= _MAX_TILE_ZOOM):
            raise ValueError(
                f"Tile zoom must be between {_MIN_TILE_ZOOM} and {_MAX_TILE_ZOOM}"
            )

        n = 2**z
        if not (0 <= x < n and 0 <= y < n):
            raise ValueError("Invalid tile coordinates for zoom level")

        cached = self._read_memory_cache(key)
        if cached is not None:
            return cached, "hit"

        redis_cached = cache_get_json(key)
        if redis_cached is not None:
            self._write_memory_cache(key, redis_cached)
            return redis_cached, "hit"

        acquired = self._sync_semaphore.acquire(timeout=60.0)
        if not acquired:
            raise TimeoutError(
                f"Tile sync semaphore timeout (max_concurrent={self._max_concurrent})"
            )
        try:
            # 双重检查：进入闸后可能其他线程已写入缓存（含 grid 上游缓存命中）
            cached = self._read_memory_cache(key)
            if cached is not None:
                return cached, "hit"
            redis_cached = cache_get_json(key)
            if redis_cached is not None:
                self._write_memory_cache(key, redis_cached)
                return redis_cached, "hit"

            geojson = self.generate_tile_payload(
                layer_id=layer_id,
                layer_spec=layer_spec,
                z=z,
                x=x,
                y=y,
                hour=hour,
                model=model,
                provider_id=provider_id,
            )
        finally:
            self._sync_semaphore.release()

        self._write_memory_cache(key, geojson)
        cache_set_json(key, geojson, get_weather_cache_ttl_seconds())
        return geojson, "miss"

    def _read_memory_cache(self, key: str) -> dict[str, Any] | None:
        if key in self._in_memory_cache:
            self._in_memory_cache.move_to_end(key)
            return self._in_memory_cache[key]
        return None

    def peek_cached_tile(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        *,
        hour: int = 0,
        model: str | None = None,
        provider_id: str | None = None,
    ) -> dict[str, Any] | None:
        """只读缓存（内存 / Redis），不触发上游拉取。供点查询降级采样。"""
        layer_spec = WEATHER_LAYER_SPECS.get(layer_id)
        model = (
            model
            or (layer_spec.preferred_model if layer_spec else None)
            or weather_default_model()
        )
        key = tile_key(
            layer_id=layer_id,
            z=z,
            x=x,
            y=y,
            hour=_clamp_hour(hour),
            model=model,
            provider_id=provider_id,
        )
        cached = self._read_memory_cache(key)
        if cached is not None:
            return cached
        redis_cached = cache_get_json(key)
        if redis_cached is not None:
            self._write_memory_cache(key, redis_cached)
            return redis_cached
        return None

    def peek_any_hour_cached_tile(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        *,
        model: str | None = None,
        provider_id: str | None = None,
    ) -> dict[str, Any] | None:
        """优先 hour=0；否则扫描 Redis 同 z/x/y 任意 hour 的缓存瓦片。"""
        hit = self.peek_cached_tile(
            layer_id,
            z,
            x,
            y,
            hour=0,
            model=model,
            provider_id=provider_id,
        )
        if hit is not None:
            return hit

        layer_spec = WEATHER_LAYER_SPECS.get(layer_id)
        model = (
            model
            or (layer_spec.preferred_model if layer_spec else None)
            or weather_default_model()
        )
        model_part = model.replace("/", "_").replace(":", "_")
        provider_part = (
            normalize_provider_id(provider_id).replace("/", "_").replace(":", "_")
        )
        pattern = (
            f"{_TILE_REDIS_KEY_PREFIX}{layer_id}:z{z}:x{x}:y{y}:h*"
            f":m{model_part}:p{provider_part}"
        )
        client = None
        try:
            from app.core.redis_client import get_redis_client

            client = get_redis_client()
        except Exception:  # noqa: BLE001
            client = None
        if client is None:
            # 退回内存：任意 hour 匹配前缀
            prefix = f"{_TILE_REDIS_KEY_PREFIX}{layer_id}:z{z}:x{x}:y{y}:h"
            suffix = f":m{model_part}:p{provider_part}"
            for key, value in self._in_memory_cache.items():
                if key.startswith(prefix) and key.endswith(suffix):
                    return value
            return None

        try:
            for key in client.scan_iter(match=pattern, count=32):
                key_str = (
                    key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
                )
                redis_cached = cache_get_json(key_str)
                if redis_cached is not None:
                    self._write_memory_cache(key_str, redis_cached)
                    return redis_cached
        except Exception as exc:  # noqa: BLE001
            logger.debug("[WeatherTileService] peek_any_hour scan failed: %s", exc)
        return None

    def sample_nearest_feature(
        self,
        *,
        layer_id: str,
        latitude: float,
        longitude: float,
        model: str | None = None,
        provider_id: str | None = None,
        zooms: tuple[int, ...] = (5, 6, 7, 4),
    ) -> dict[str, Any] | None:
        """从已缓存瓦片中取距点击点最近的要素属性（无上游请求）。"""
        best: dict[str, Any] | None = None
        best_dist = float("inf")
        for z in zooms:
            x, y = lonlat_to_tile(z, longitude, latitude)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    geojson = self.peek_any_hour_cached_tile(
                        layer_id,
                        z,
                        x + dx,
                        y + dy,
                        model=model,
                        provider_id=provider_id,
                    )
                    if not geojson:
                        continue
                    for feature in geojson.get("features") or []:
                        geom = feature.get("geometry") or {}
                        coords = geom.get("coordinates")
                        gtype = geom.get("type")
                        if gtype == "Point" and coords and len(coords) >= 2:
                            flon, flat = float(coords[0]), float(coords[1])
                        elif gtype == "Polygon" and coords and coords[0]:
                            ring = coords[0]
                            if not ring:
                                continue
                            flon = sum(float(p[0]) for p in ring) / len(ring)
                            flat = sum(float(p[1]) for p in ring) / len(ring)
                        else:
                            continue
                        dist = (flon - longitude) ** 2 + (flat - latitude) ** 2
                        if dist < best_dist:
                            best_dist = dist
                            props = dict(feature.get("properties") or {})
                            props["_sample_lon"] = flon
                            props["_sample_lat"] = flat
                            best = props
            if best is not None:
                break
        return best

    def _write_memory_cache(self, key: str, value: dict[str, Any]) -> None:
        self._in_memory_cache[key] = value
        self._in_memory_cache.move_to_end(key)
        while len(self._in_memory_cache) > self._in_memory_cache_max:
            self._in_memory_cache.popitem(last=False)

    async def get_tile(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        *,
        hour: int | None = None,
        model: str | None = None,
        provider_id: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        """获取瓦片 GeoJSON，返回 (geojson, cache_status)。

        cache_status 取值：
        - "hit": Redis 或内存缓存命中
        - "miss": 未命中，已生成
        """
        hour = _clamp_hour(hour)
        layer_spec = WEATHER_LAYER_SPECS.get(layer_id)
        if layer_spec is None:
            raise ValueError(f"Unsupported weather layer: {layer_id}")
        model = model or layer_spec.preferred_model or weather_default_model()
        key = tile_key(layer_id, z, x, y, hour, model, provider_id)

        if not (_MIN_TILE_ZOOM <= z <= _MAX_TILE_ZOOM):
            raise ValueError(
                f"Tile zoom must be between {_MIN_TILE_ZOOM} and {_MAX_TILE_ZOOM}"
            )

        n = 2**z
        if not (0 <= x < n and 0 <= y < n):
            raise ValueError("Invalid tile coordinates for zoom level")

        # 1. 内存缓存
        cached = self._read_memory_cache(key)
        if cached is not None:
            return cached, "hit"

        # 2. Redis 缓存
        redis_cached = cache_get_json(key)
        if redis_cached is not None:
            self._write_memory_cache(key, redis_cached)
            return redis_cached, "hit"

        # 3. 生成瓦片（受全局并发槽位限制）
        async with self._semaphore:
            # 双重检查：进入 semaphore 后可能其他任务已写入缓存
            cached = self._read_memory_cache(key)
            if cached is not None:
                return cached, "hit"
            redis_cached = cache_get_json(key)
            if redis_cached is not None:
                self._write_memory_cache(key, redis_cached)
                return redis_cached, "hit"

            geojson = await self._generate_tile(
                layer_id=layer_id,
                layer_spec=layer_spec,
                z=z,
                x=x,
                y=y,
                hour=hour,
                model=model,
                provider_id=provider_id,
            )

        # 4. 写入缓存
        self._write_memory_cache(key, geojson)
        cache_set_json(key, geojson, get_weather_cache_ttl_seconds())

        return geojson, "miss"


@lru_cache(maxsize=1)
def get_weather_tile_service() -> WeatherTileService:
    """惰性加载 WeatherTileService，避免 WeatherEngineService 循环导入。"""
    return WeatherTileService()
