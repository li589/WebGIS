"""L3 抽取：天气值计算与类型工具函数。

从 weatherengine/service.py 的 WeatherEngineService 类中抽取的纯函数集合，
不依赖实例状态，仅依赖参数与标准库。

包含：
- 值空间扰动模型（温度/降水/湿度/气压/能见度/风场）
- 类型强转工具（_as_float / _as_int / _as_string / _coerce_datetime）
- 请求解析（_resolve_point / _resolve_forecast_hours / _pick_series_value）
- 渲染区域解析（_resolve_render_bbox）
"""

from __future__ import annotations

import math
from datetime import datetime

from app.core.config import settings
from shared.contracts.api_contracts import BoundingBox, WorkflowSubmitRequest


# ── 值空间扰动模型 ───────────────────────────────────────────────────────────


def temperature_value_for_location(
    *,
    base_temp: float,
    center_lat: float,
    center_lon: float,
    lat: float,
    lon: float,
    lat_span: float,
    lon_span: float,
) -> float:
    """温度空间扰动：纬度递减 + 经度偏移 + 径向衰减。"""
    lat_norm = (lat - center_lat) / lat_span
    lon_norm = (lon - center_lon) / lon_span
    radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
    return base_temp - lat_norm * 4.8 + lon_norm * 2.2 - radial * 5.5


def precipitation_value_for_location(
    *,
    base_precip: float,
    center_lat: float,
    center_lon: float,
    lat: float,
    lon: float,
    lat_span: float,
    lon_span: float,
) -> float:
    """降水空间扰动：核心 + 带状分量 + 径向衰减，下限 0。"""
    lat_norm = (lat - center_lat) / lat_span
    lon_norm = (lon - center_lon) / lon_span
    radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
    core = max(0.0, 1.28 - radial * 2.15)
    band = max(0.0, 0.72 - abs(lat_norm + lon_norm * 0.55) * 1.4)
    return max(0.0, base_precip + core * 8.5 + band * 4.2 - radial * 1.1)


def humidity_value_for_location(
    *,
    base_humidity: float,
    center_lat: float,
    center_lon: float,
    lat: float,
    lon: float,
    lat_span: float,
    lon_span: float,
) -> float:
    """湿度空间扰动：正弦/余弦波纹，限制 0~100%。"""
    lat_norm = (lat - center_lat) / lat_span
    lon_norm = (lon - center_lon) / lon_span
    noise = (
        math.sin(lat_norm * math.pi) * 0.5 + math.cos(lon_norm * math.pi) * 0.5
    ) * 5.0
    return max(0.0, min(100.0, base_humidity + noise))


def pressure_value_for_location(
    *,
    base_pressure: float,
    center_lat: float,
    center_lon: float,
    lat: float,
    lon: float,
    lat_span: float,
    lon_span: float,
) -> float:
    """气压空间扰动：中心偏高、外围略低（低压系统扰动）。"""
    lat_norm = (lat - center_lat) / lat_span
    lon_norm = (lon - center_lon) / lon_span
    radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
    noise = (
        -radial * 3.2
        + math.sin(lon_norm * math.pi) * 1.5
        - math.cos(lat_norm * math.pi) * 1.2
    )
    return base_pressure + noise


def visibility_value_for_location(
    *,
    base_visibility: float,
    center_lat: float,
    center_lon: float,
    lat: float,
    lon: float,
    lat_span: float,
    lon_span: float,
) -> float:
    """能见度空间扰动：向边缘衰减，下限 0。"""
    lat_norm = (lat - center_lat) / lat_span
    lon_norm = (lon - center_lon) / lon_span
    radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
    noise = -radial * 1200.0 + math.sin((lat_norm + lon_norm) * math.pi) * 600.0
    return max(0.0, base_visibility + noise)


def wind_value_for_location(
    *,
    base_speed: float,
    base_direction: float,
    center_lat: float,
    center_lon: float,
    lat: float,
    lon: float,
    lat_span: float,
    lon_span: float,
) -> tuple[float, float]:
    """风场空间扰动：速度（含正弦波纹 + 径向）+ 方向（线性 + 径向）。

    Returns:
        (speed_mps, direction_degrees)
    """
    lat_norm = (lat - center_lat) / lat_span
    lon_norm = (lon - center_lon) / lon_span
    radial = math.sqrt(lat_norm * lat_norm + lon_norm * lon_norm)
    speed = max(
        0.0,
        base_speed
        + lon_norm * 3.2
        - lat_norm * 1.4
        + math.sin((lat_norm + lon_norm) * math.pi) * 1.2,
    )
    direction = (
        base_direction + lon_norm * 36.0 - lat_norm * 24.0 + radial * 18.0
    ) % 360
    return speed, direction


# ── 类型强转工具 ─────────────────────────────────────────────────────────────


def as_float(value: object) -> float | None:
    """将任意值强转为 float，失败返回 None。"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def as_int(value: object) -> int | None:
    """将任意值强转为 int，失败返回 None。"""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def as_string(value: object) -> str | None:
    """将任意值强转为非空 stripped str，空则返回 None。"""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def coerce_datetime(value: object) -> datetime | None:
    """将 ISO 8601 字符串（含 'Z' 后缀）解析为 datetime。"""
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    return None


# ── 请求解析工具 ─────────────────────────────────────────────────────────────


def resolve_point(
    payload: WorkflowSubmitRequest,
) -> tuple[float, float, str | None]:
    """从 workflow payload 解析目标点坐标。

    优先级：parameters.latitude/longitude → spatial_filter.bbox 中心 → 默认值。
    """
    latitude = as_float(payload.parameters.get("latitude"))
    longitude = as_float(payload.parameters.get("longitude"))
    place_name = as_string(payload.parameters.get("place_name"))
    if latitude is not None and longitude is not None:
        return latitude, longitude, place_name
    if payload.spatial_filter and payload.spatial_filter.bbox:
        bbox = payload.spatial_filter.bbox
        return (
            (bbox.south + bbox.north) / 2,
            (bbox.west + bbox.east) / 2,
            place_name,
        )
    return (
        settings.weather_default_latitude,
        settings.weather_default_longitude,
        place_name or settings.weather_default_place_name,
    )


def resolve_forecast_hours(payload: WorkflowSubmitRequest) -> int:
    """从 payload 解析 forecast_hours，限制 [1, 24]。"""
    requested = as_int(payload.parameters.get("forecast_hours"))
    if requested is None:
        return settings.weather_refresh_forecast_hours
    return max(1, min(24, requested))


def pick_series_value(hourly: dict[str, object], key: str, index: int) -> float | None:
    """从 hourly 字典中按 key + index 取值。"""
    values = hourly.get(key)
    if isinstance(values, list) and index < len(values):
        value = values[index]
        if isinstance(value, (int, float)):
            return float(value)
    return None


# ── 渲染区域解析 ─────────────────────────────────────────────────────────────


def resolve_render_bbox(
    payload: WorkflowSubmitRequest,
    latitude: float,
    longitude: float,
) -> BoundingBox:
    """解析渲染区域 BoundingBox。

    优先级：viewport_bbox → spatial_filter.bbox → center ± (1.6°, 1.2°) fallback。
    处理日界线 wraparound 与极地 clamp。
    """
    vp_bbox = payload.map_context.viewport_bbox
    if vp_bbox is not None:
        return vp_bbox
    if payload.spatial_filter and payload.spatial_filter.bbox is not None:
        return payload.spatial_filter.bbox
    west = longitude - 1.6
    east = longitude + 1.6
    south = latitude - 1.2
    north = latitude + 1.2
    while west < -180:
        west += 360
    while east > 180:
        east -= 360
    north = min(90, max(-90, north))
    south = min(90, max(-90, south))
    return BoundingBox(west=west, south=south, east=east, north=north)
