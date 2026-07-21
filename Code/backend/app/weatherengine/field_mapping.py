"""Normalize external weather API fields to Open-Meteo-style names.

Downstream tile/render/point parsers expect keys such as ``wind_speed_10m``,
``temperature_2m``, ``precipitation``, ``relative_humidity_2m``.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Literal

from shared.contracts.api_contracts import BoundingBox

logger = logging.getLogger(__name__)

# Near-surface layers with real commercial API fields.
SURFACE_LAYER_IDS: frozenset[str] = frozenset(
    {
        "wind-field",
        "temperature",
        "precipitation",
        "humidity",
        "pressure",
        "visibility",
        "cloud-cover",
        "dewpoint",
    }
)

# Hub-height AGL layers: commercial APIs lack true values → power-law / near-surface proxy.
HEIGHT_LAYER_IDS: frozenset[str] = frozenset(
    {
        "wind-field-80m",
        "wind-field-120m",
        "wind-field-180m",
        "temperature-80m",
        "temperature-120m",
        "temperature-180m",
    }
)

# Pressure-level winds: sparse/unavailable on WeatherAPI & OpenWeather One Call.
PRESSURE_LAYER_IDS: frozenset[str] = frozenset(
    {
        "wind-field-850hPa",
        "wind-field-500hPa",
        "wind-field-200hPa",
    }
)

COMMERCIAL_LAYER_IDS: frozenset[str] = SURFACE_LAYER_IDS | HEIGHT_LAYER_IDS | PRESSURE_LAYER_IDS

DataQuality = Literal["observed", "extrapolated", "sparse"]

_HEIGHT_WIND_SUFFIX: dict[str, str] = {
    "wind-field-80m": "80m",
    "wind-field-120m": "120m",
    "wind-field-180m": "180m",
}
_HEIGHT_TEMP_SUFFIX: dict[str, str] = {
    "temperature-80m": "80m",
    "temperature-120m": "120m",
    "temperature-180m": "180m",
}
_PRESSURE_WIND_SUFFIX: dict[str, str] = {
    "wind-field-850hPa": "850hPa",
    "wind-field-500hPa": "500hPa",
    "wind-field-200hPa": "200hPa",
}

# Hellmann / power-law exponent for open terrain (≈0.14).
_WIND_POWER_LAW_ALPHA = 0.14
_REF_WIND_HEIGHT_M = 10.0


def commercial_data_quality(layer_id: str) -> DataQuality:
    if layer_id in SURFACE_LAYER_IDS:
        return "observed"
    if layer_id in HEIGHT_LAYER_IDS:
        return "extrapolated"
    if layer_id in PRESSURE_LAYER_IDS:
        return "sparse"
    return "observed"


def commercial_layer_hint(layer_id: str) -> str:
    quality = commercial_data_quality(layer_id)
    if quality == "observed":
        return "近地面观测/预报"
    if quality == "extrapolated":
        return "由近地面外推（非真值）"
    return "气压层稀疏/不可用（建议 Open-Meteo）"


def _height_meters_from_suffix(suffix: str) -> float:
    return float(suffix.rstrip("m"))


def extrapolate_wind_speed_power_law(
    speed_10m: float | None,
    *,
    target_height_m: float,
    alpha: float = _WIND_POWER_LAW_ALPHA,
) -> float | None:
    if speed_10m is None:
        return None
    try:
        s = float(speed_10m)
    except (TypeError, ValueError):
        return None
    if target_height_m <= 0 or _REF_WIND_HEIGHT_M <= 0:
        return s
    return s * (target_height_m / _REF_WIND_HEIGHT_M) ** alpha


def apply_commercial_height_extrapolation(payload: dict[str, Any], layer_id: str) -> dict[str, Any]:
    """Mutate OM-style point payload: copy/extrapolate surface → height fields."""
    if layer_id not in HEIGHT_LAYER_IDS:
        return payload
    current = payload.setdefault("current", {})
    hourly = payload.setdefault("hourly", {})

    if layer_id in _HEIGHT_WIND_SUFFIX:
        suffix = _HEIGHT_WIND_SUFFIX[layer_id]
        target_h = _height_meters_from_suffix(suffix)
        speed_key = f"wind_speed_{suffix}"
        dir_key = f"wind_direction_{suffix}"
        base_speed = current.get("wind_speed_10m")
        current[speed_key] = extrapolate_wind_speed_power_law(base_speed, target_height_m=target_h)
        # 仅当 current 真正提供 wind_direction_10m 时才外推方向；否则不写 dir_key，
        # 避免写入 None 让下游误判为“有数据但无值”。与 hourly 部分守卫一致。
        if "wind_direction_10m" in current:
            current[dir_key] = current.get("wind_direction_10m")
        else:
            logger.warning(
                "apply_commercial_height_extrapolation: current.wind_direction_10m "
                "missing for layer_id=%s; skipping %s direction extrapolation",
                layer_id,
                dir_key,
            )
        if "wind_speed_10m" in hourly:
            times = hourly.get("time") or []
            base_speeds = hourly.get("wind_speed_10m") or []
            hourly[speed_key] = [
                extrapolate_wind_speed_power_law(
                    base_speeds[i] if i < len(base_speeds) else None,
                    target_height_m=target_h,
                )
                for i in range(len(times) or len(base_speeds))
            ]
            # 仅当 base 真正提供 wind_direction_10m 时才外推方向；否则不写 dir_key，
            # 避免生成全 None 列表让下游误判为“有数据但无值”。
            if "wind_direction_10m" in hourly:
                base_dirs = hourly.get("wind_direction_10m") or []
                hourly[dir_key] = [
                    base_dirs[i] if i < len(base_dirs) else None
                    for i in range(len(times) or len(base_dirs))
                ]
            else:
                logger.warning(
                    "apply_commercial_height_extrapolation: hourly.wind_direction_10m "
                    "missing for layer_id=%s; skipping %s direction extrapolation",
                    layer_id,
                    dir_key,
                )
    elif layer_id in _HEIGHT_TEMP_SUFFIX:
        suffix = _HEIGHT_TEMP_SUFFIX[layer_id]
        temp_key = f"temperature_{suffix}"
        # Commercial APIs lack hub-height temp → use 2 m as proxy (documented as extrapolated).
        current[temp_key] = current.get("temperature_2m")
        if "temperature_2m" in hourly:
            times = hourly.get("time") or []
            base = hourly.get("temperature_2m") or []
            hourly[temp_key] = [
                base[i] if i < len(base) else None for i in range(len(times) or len(base))
            ]

    payload["data_quality"] = "extrapolated"
    payload["proxy_from"] = "surface"
    return payload


def ensure_hub_height_wind_in_grid_arrays(
    current: dict[str, list[Any]],
    hourly: dict[str, list[Any]],
    layer_id: str,
) -> bool:
    """Fill all-null hub-height wind arrays from 10 m via power law (in-place).

    ECMWF IFS 等模型不提供 ``wind_speed_80m/120m/180m``（返回全 null），
    但提供 ``wind_speed_10m``。与商业源的 ``apply_commercial_height_extrapolation``
    对齐，保证网格瓦片在默认模型下仍可渲染。
    """
    if layer_id not in _HEIGHT_WIND_SUFFIX:
        return False
    suffix = _HEIGHT_WIND_SUFFIX[layer_id]
    target_h = _height_meters_from_suffix(suffix)
    speed_key = f"wind_speed_{suffix}"
    dir_key = f"wind_direction_{suffix}"
    filled = False

    base_speed = current.get("wind_speed_10m")
    speed_series = current.get(speed_key)
    if (
        isinstance(base_speed, list)
        and base_speed
        and (not isinstance(speed_series, list) or not any(v is not None for v in speed_series))
    ):
        current[speed_key] = [
            extrapolate_wind_speed_power_law(
                base_speed[i] if i < len(base_speed) else None,
                target_height_m=target_h,
            )
            for i in range(len(base_speed))
        ]
        if "wind_direction_10m" in current and isinstance(current["wind_direction_10m"], list):
            base_dir = current["wind_direction_10m"]
            current[dir_key] = [
                base_dir[i] if i < len(base_dir) else None for i in range(len(base_speed))
            ]
        filled = True
        logger.info(
            "ensure_hub_height_wind_in_grid_arrays: filled current %s from 10m for layer=%s",
            speed_key,
            layer_id,
        )

    hourly_base = hourly.get("wind_speed_10m")
    hourly_speed = hourly.get(speed_key)
    if isinstance(hourly_base, list) and hourly_base:
        need_hourly = not isinstance(hourly_speed, list) or not any(
            isinstance(pt, list) and any(v is not None for v in pt) for pt in hourly_speed
        )
        if need_hourly:
            hourly[speed_key] = [
                [
                    extrapolate_wind_speed_power_law(v, target_height_m=target_h)
                    for v in (pt if isinstance(pt, list) else [])
                ]
                for pt in hourly_base
            ]
            if "wind_direction_10m" in hourly and isinstance(hourly["wind_direction_10m"], list):
                hourly[dir_key] = [
                    list(pt) if isinstance(pt, list) else []
                    for pt in hourly["wind_direction_10m"]
                ]
            filled = True
            logger.info(
                "ensure_hub_height_wind_in_grid_arrays: filled hourly %s from 10m for layer=%s",
                speed_key,
                layer_id,
            )

    return filled


def backfill_current_from_hourly_step0(
    current: dict[str, list[Any]],
    hourly: dict[str, list[Any]],
) -> None:
    """When ``current`` fields are all-null, promote ``hourly[*][0]`` (pressure levels)."""
    for field, series in list(current.items()):
        if not isinstance(series, list) or any(v is not None for v in series):
            continue
        hourly_series = hourly.get(field)
        if not isinstance(hourly_series, list) or not hourly_series:
            continue
        for i, point_vals in enumerate(hourly_series):
            if i >= len(series):
                break
            if isinstance(point_vals, list) and point_vals:
                series[i] = point_vals[0]


def build_empty_pressure_grid(
    *,
    bbox: BoundingBox,
    resolution: float,
    layer_spec: Any,
) -> dict[str, Any]:
    """Structured empty grid for pressure layers without commercial true values."""
    lats, lons, res = compute_grid_axes(bbox, resolution, max_points=16)
    rows, cols = len(lats), len(lons)
    total = rows * cols
    current_fields = tuple(getattr(layer_spec, "current_fields", ()) or ())
    hourly_fields = tuple(getattr(layer_spec, "hourly_fields", ()) or ())
    return {
        "grid": {
            "bbox": {
                "west": bbox.west,
                "south": bbox.south,
                "east": bbox.east,
                "north": bbox.north,
            },
            "rows": rows,
            "cols": cols,
            "resolution": res,
            "lats": lats,
            "lons": lons,
        },
        "data": {
            "current": {f: [None] * total for f in current_fields},
            "hourly": {f: [[] for _ in range(total)] for f in hourly_fields},
        },
        "data_quality": "sparse",
        "coverage": "sparse_unavailable",
        "proxy_from": None,
    }


def kph_to_ms(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / 3.6
    except (TypeError, ValueError):
        return None


def mph_to_ms(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value) * 0.44704
    except (TypeError, ValueError):
        return None


def km_to_m(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value) * 1000.0
    except (TypeError, ValueError):
        return None


def build_empty_om_point_payload(*, timezone: str | None = "UTC") -> dict[str, Any]:
    return {
        "timezone": timezone,
        "current": {},
        "hourly": {"time": []},
    }


def merge_current_fields(target: dict[str, Any], values: dict[str, Any | None]) -> None:
    for key, value in values.items():
        if value is not None:
            target[key] = value


def append_hourly_series(
    hourly: dict[str, Any],
    *,
    times: list[str],
    series: dict[str, list[Any | None]],
) -> None:
    hourly["time"] = list(times)
    for key, values in series.items():
        hourly[key] = list(values)


# 格心落在 (i+0.5)*res；半开归属避免邻瓦共点。浮点边界用极小 eps。
_GRID_AXIS_EPS = 1e-9


def lon_centers_half_open(west: float, east: float, resolution: float) -> list[float]:
    """经度格心：``west <= lon < east``，全球格网 ``(i+0.5)*res``。"""
    res = float(resolution)
    if res <= 0 or east <= west:
        return []
    i_min = math.ceil(west / res - 0.5 - _GRID_AXIS_EPS)
    i_max = math.floor(east / res - 0.5 - _GRID_AXIS_EPS)
    if i_max < i_min:
        mid = 0.5 * (west + east)
        return [mid] if west <= mid < east else []
    return [(i + 0.5) * res for i in range(i_min, i_max + 1)]


def lat_centers_half_open(south: float, north: float, resolution: float) -> list[float]:
    """纬度格心：``south < lat <= north``（Web Mercator 瓦片 y 向南增），北→南排序。"""
    res = float(resolution)
    if res <= 0 or north <= south:
        return []
    j_min = math.ceil(south / res - 0.5 + _GRID_AXIS_EPS)
    j_max = math.floor(north / res - 0.5 + _GRID_AXIS_EPS)
    if j_max < j_min:
        mid = 0.5 * (south + north)
        return [mid] if south < mid <= north else []
    centers = [(j + 0.5) * res for j in range(j_min, j_max + 1)]
    centers.reverse()
    return centers


def aligned_grid_axes(
    bbox: BoundingBox,
    resolution: float,
) -> tuple[list[float], list[float], float]:
    """按全球对齐格网生成瓦片内格心（不拉伸填满 bbox）。

    旧实现从每块 ``bbox.west/south`` 起算并把步长拉成 ``span/n``，邻瓦边缘格块在
    经纬度矩形外扩后会叠一条「外框」；高纬瓦片 lat 跨度更小，同样度数叠缝在
    Web Mercator 屏幕上更宽。全球 ``(i+0.5)*res`` + 半开归属可严格分割。
    """
    res = max(0.05, float(resolution))
    west, east = float(bbox.west), float(bbox.east)
    south, north = float(bbox.south), float(bbox.north)
    if east <= west:
        east = west + res
    if north <= south:
        north = south + res
    lons = lon_centers_half_open(west, east, res)
    lats = lat_centers_half_open(south, north, res)
    return lats, lons, res


def compute_grid_axes(
    bbox: BoundingBox,
    resolution: float,
    *,
    max_points: int = 36,
) -> tuple[list[float], list[float], float]:
    """Build lat/lon axes on a global lattice; coarsen if point count exceeds ``max_points``."""
    res = max(0.05, float(resolution))
    lats: list[float] = []
    lons: list[float] = []
    for _ in range(12):
        lats, lons, res = aligned_grid_axes(bbox, res)
        if max(1, len(lats)) * max(1, len(lons)) <= max_points:
            break
        res *= 1.6
    if not lats or not lons:
        # 极窄瓦片兜底：至少 1×1
        mid_lon = 0.5 * (float(bbox.west) + float(bbox.east))
        mid_lat = 0.5 * (float(bbox.south) + float(bbox.north))
        return [mid_lat], [mid_lon], res
    return lats, lons, res


def point_in_tile_half_open(
    lon: float,
    lat: float,
    *,
    west: float,
    south: float,
    east: float,
    north: float,
) -> bool:
    """与格网/前端裁剪一致的半开归属。"""
    return west <= lon < east and south < lat <= north


def assemble_grid_from_point_payloads(
    *,
    bbox: BoundingBox,
    resolution: float,
    lats: list[float],
    lons: list[float],
    point_payloads: list[dict[str, Any] | None],
    current_fields: tuple[str, ...],
    hourly_fields: tuple[str, ...],
) -> dict[str, Any]:
    """Assemble OM-style ``grid_data`` from per-point forecast payloads."""
    rows, cols = len(lats), len(lons)
    total = rows * cols
    all_current: dict[str, list[Any | None]] = {f: [None] * total for f in current_fields}
    all_hourly: dict[str, list[list[Any | None]]] = {f: [[] for _ in range(total)] for f in hourly_fields}
    hourly_times_ref: list[str] = []

    for idx, payload in enumerate(point_payloads):
        if idx >= total or not isinstance(payload, dict):
            continue
        current = payload.get("current") or {}
        for field in current_fields:
            if field in current:
                all_current[field][idx] = current.get(field)

        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        if times and not hourly_times_ref:
            hourly_times_ref = list(times)
        for field in hourly_fields:
            series = hourly.get(field) or []
            row_series: list[Any | None] = []
            for t_idx in range(len(hourly_times_ref) or len(series)):
                row_series.append(series[t_idx] if t_idx < len(series) else None)
            all_hourly[field][idx] = row_series

    # Attach shared time axis under hourly for consumers that look there
    if hourly_times_ref:
        all_hourly.setdefault("time", [list(hourly_times_ref) for _ in range(total)])

    return {
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
            "current": all_current,
            "hourly": all_hourly,
        },
    }


def weatherapi_current_to_om(current: dict[str, Any]) -> dict[str, Any]:
    """Map WeatherAPI.com ``current`` object → OM-style current fields."""
    precip = current.get("precip_mm")
    if precip is None:
        precip = current.get("precip_in")
    return {
        "time": current.get("last_updated"),
        "temperature_2m": current.get("temp_c"),
        "apparent_temperature": current.get("feelslike_c"),
        "precipitation": precip,
        "rain": precip,
        "relative_humidity_2m": current.get("humidity"),
        "cloud_cover": current.get("cloud"),
        "pressure_msl": current.get("pressure_mb"),
        "wind_speed_10m": kph_to_ms(current.get("wind_kph")),
        "wind_direction_10m": current.get("wind_degree"),
        "wind_gusts_10m": kph_to_ms(current.get("gust_kph")),
        "visibility": km_to_m(current.get("vis_km")),
        "dew_point_2m": current.get("dewpoint_c"),
    }


def weatherapi_hour_to_om(hour: dict[str, Any]) -> dict[str, Any]:
    precip = hour.get("precip_mm")
    return {
        "time": hour.get("time"),
        "temperature_2m": hour.get("temp_c"),
        "precipitation": precip,
        "relative_humidity_2m": hour.get("humidity"),
        "wind_speed_10m": kph_to_ms(hour.get("wind_kph")),
        "wind_direction_10m": hour.get("wind_degree"),
        "cloud_cover": hour.get("cloud"),
        "pressure_msl": hour.get("pressure_mb"),
        "visibility": km_to_m(hour.get("vis_km")),
        "dew_point_2m": hour.get("dewpoint_c"),
    }


def openweather_current_to_om(current: dict[str, Any]) -> dict[str, Any]:
    """Map OpenWeather One Call ``current`` (metric units) → OM-style fields."""
    rain = current.get("rain") or {}
    snow = current.get("snow") or {}
    precip = None
    if isinstance(rain, dict):
        precip = rain.get("1h")
    if precip is None and isinstance(snow, dict):
        precip = snow.get("1h")
    elif precip is not None and isinstance(snow, dict) and snow.get("1h") is not None:
        precip = float(precip) + float(snow.get("1h") or 0)
    return {
        "time": _unix_to_iso(current.get("dt")),
        "temperature_2m": current.get("temp"),
        "apparent_temperature": current.get("feels_like"),
        "precipitation": precip,
        "rain": rain.get("1h") if isinstance(rain, dict) else None,
        "relative_humidity_2m": current.get("humidity"),
        "cloud_cover": current.get("clouds"),
        "pressure_msl": current.get("pressure"),
        "wind_speed_10m": current.get("wind_speed"),
        "wind_direction_10m": current.get("wind_deg"),
        "wind_gusts_10m": current.get("wind_gust"),
        "visibility": current.get("visibility"),
        "dew_point_2m": current.get("dew_point"),
    }


def openweather_hour_to_om(hour: dict[str, Any]) -> dict[str, Any]:
    rain = hour.get("rain") or {}
    precip = rain.get("1h") if isinstance(rain, dict) else None
    return {
        "time": _unix_to_iso(hour.get("dt")),
        "temperature_2m": hour.get("temp"),
        "precipitation": precip,
        "relative_humidity_2m": hour.get("humidity"),
        "wind_speed_10m": hour.get("wind_speed"),
        "wind_direction_10m": hour.get("wind_deg"),
        "cloud_cover": hour.get("clouds"),
        "pressure_msl": hour.get("pressure"),
        "visibility": hour.get("visibility"),
        "dew_point_2m": hour.get("dew_point"),
    }


def _unix_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(value) if value is not None else None
