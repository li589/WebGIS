"""天气数据标准瓦片服务。

提供基于 Web Mercator z/x/y 的 GeoJSON 瓦片接口，供前端按瓦片请求天气数据。
职责：
1. 瓦片坐标与 EPSG:4326 bbox 转换。
2. 瓦片级 Redis/内存缓存。
3. 全局并发槽位控制（避免 Open-Meteo 限流）。
4. 调用现有 WeatherEngineService / OpenMeteoClient 生成 GeoJSON。
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import OrderedDict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.redis_client import cache_get_json, cache_set_json
from app.weatherengine.client import OpenMeteoClient
from app.weatherengine.constants import WEATHER_LAYER_SPECS, WeatherLayerSpec
from shared.contracts.api_contracts import BoundingBox

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


def tile_key(
    layer_id: str,
    z: int,
    x: int,
    y: int,
    hour: int,
    model: str | None,
) -> str:
    """生成瓦片缓存键（前后端保持一致）。"""
    model_part = model.replace("/", "_").replace(":", "_") if model else "default"
    return f"{_TILE_REDIS_KEY_PREFIX}{layer_id}:z{z}:x{x}:y{y}:h{hour}:m{model_part}"


def tile_bbox(z: int, x: int, y: int) -> BoundingBox:
    """Web Mercator z/x/y → EPSG:4326 bbox（西南东北）。"""
    n = 2 ** z
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
    """
    if hour <= 0:
        return grid_data

    hourly = grid_data.get("data", {}).get("hourly", {})
    if not hourly:
        logger.warning("[WeatherTileService] hourly data not available for hour=%d, falling back to current", hour)
        return grid_data

    # 检查 hourly 是否有足够时间步
    first_series = next(iter(hourly.values()), None)
    if not isinstance(first_series, list) or hour >= len(first_series):
        logger.warning(
            "[WeatherTileService] hourly data only has %d steps, requested hour=%d, falling back to current",
            len(first_series) if isinstance(first_series, list) else 0,
            hour,
        )
        return grid_data

    # 构建 current 的副本，替换为指定小时的值
    new_current: dict[str, Any] = {}
    for key, values in hourly.items():
        if isinstance(values, list) and hour < len(values):
            new_current[key] = values[hour]
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
        client: OpenMeteoClient | None = None,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT_TILE_REQUESTS,
        in_memory_cache_max: int = _IN_MEMORY_TILE_CACHE_MAX,
    ) -> None:
        # 延迟导入以避免 WeatherEngineService ↔ tile_service 循环依赖
        from app.weatherengine.service import WeatherEngineService

        self._engine = engine_service or WeatherEngineService()
        self._client = client or OpenMeteoClient()
        self._semaphore = asyncio.Semaphore(max_concurrent)
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
            return self._engine.build_precipitation_geojson_from_grid(grid_data, layer_id)
        if layer_id == "humidity":
            return self._engine.build_humidity_geojson_from_grid(grid_data, layer_id)
        if layer_id == "pressure":
            return self._engine.build_pressure_geojson_from_grid(grid_data, layer_id)
        if layer_id == "visibility":
            return self._engine.build_visibility_geojson_from_grid(grid_data, layer_id)

        raise ValueError(f"Unsupported weather tile layer: {layer_id}")

    async def _generate_tile(
        self,
        layer_id: str,
        layer_spec: WeatherLayerSpec,
        z: int,
        x: int,
        y: int,
        hour: int,
        model: str | None,
    ) -> dict[str, Any]:
        """实际生成瓦片（在 semaphore 保护下执行）。"""
        bbox = tile_bbox(z, x, y)
        resolution = zoom_to_resolution(z)

        logger.info(
            "[WeatherTileService] generating tile layer=%s z=%d x=%d y=%d hour=%d resolution=%.2f bbox=(%.4f,%.4f,%.4f,%.4f)",
            layer_id, z, x, y, hour, resolution,
            bbox.west, bbox.south, bbox.east, bbox.north,
        )

        # 在后台线程执行同步的网格获取与 GeoJSON 构建，避免阻塞事件循环
        loop = asyncio.get_event_loop()

        def _fetch_and_build() -> tuple[dict[str, Any], str]:
            grid_data, cache_status = self._client.fetch_grid_forecast(
                bbox=bbox,
                resolution=resolution,
                layer_spec=layer_spec,
                model=model or settings.weather_default_model,
                ttl_seconds=settings.weather_cache_ttl_seconds,
                pressure_levels=layer_spec.pressure_levels if layer_spec else None,
            )
            grid_data_for_hour = _grid_data_for_hour(grid_data, hour)
            geojson = self._build_geojson(grid_data_for_hour, layer_id, layer_spec)
            return geojson, cache_status

        geojson, cache_status = await loop.run_in_executor(None, _fetch_and_build)

        # 注入瓦片元数据，便于前端调试
        geojson["_tile_meta"] = {
            "layer_id": layer_id,
            "z": z,
            "x": x,
            "y": y,
            "hour": hour,
            "model": model or settings.weather_default_model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "upstream_cache_status": cache_status,
        }

        logger.info(
            "[WeatherTileService] tile generated layer=%s z=%d x=%d y=%d hour=%d features=%d upstream_cache=%s",
            layer_id, z, x, y, hour, len(geojson.get("features", [])), cache_status,
        )
        return geojson

    def _read_memory_cache(self, key: str) -> dict[str, Any] | None:
        if key in self._in_memory_cache:
            self._in_memory_cache.move_to_end(key)
            return self._in_memory_cache[key]
        return None

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
    ) -> tuple[dict[str, Any], str]:
        """获取瓦片 GeoJSON，返回 (geojson, cache_status)。

        cache_status 取值：
        - "hit": Redis 或内存缓存命中
        - "miss": 未命中，已生成
        """
        hour = _clamp_hour(hour)
        model = model or settings.weather_default_model
        key = tile_key(layer_id, z, x, y, hour, model)

        layer_spec = WEATHER_LAYER_SPECS.get(layer_id)
        if layer_spec is None:
            raise ValueError(f"Unsupported weather layer: {layer_id}")

        if not (_MIN_TILE_ZOOM <= z <= _MAX_TILE_ZOOM):
            raise ValueError(f"Tile zoom must be between {_MIN_TILE_ZOOM} and {_MAX_TILE_ZOOM}")

        n = 2 ** z
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
            )

        # 4. 写入缓存
        self._write_memory_cache(key, geojson)
        cache_set_json(key, geojson, settings.weather_cache_ttl_seconds)

        return geojson, "miss"


@lru_cache(maxsize=1)
def get_weather_tile_service() -> WeatherTileService:
    """惰性加载 WeatherTileService，避免 WeatherEngineService 循环导入。"""
    return WeatherTileService()
