"""Normalize external weather API fields to Open-Meteo-style names.

Downstream tile/render/point parsers expect keys such as ``wind_speed_10m``,
``temperature_2m``, ``precipitation``, ``relative_humidity_2m``.
"""

from __future__ import annotations

import math
from typing import Any

from shared.contracts.api_contracts import BoundingBox

# First-wave commercial layers (surface only; no 80m / pressure levels).
SURFACE_LAYER_IDS: frozenset[str] = frozenset(
    {
        "wind-field",
        "temperature",
        "precipitation",
        "humidity",
    }
)


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


def compute_grid_axes(
    bbox: BoundingBox,
    resolution: float,
    *,
    max_points: int = 36,
) -> tuple[list[float], list[float], float]:
    """Build lat/lon axes; coarsen resolution if point count would exceed ``max_points``."""
    res = max(0.05, float(resolution))
    west, east = float(bbox.west), float(bbox.east)
    south, north = float(bbox.south), float(bbox.north)
    if east <= west:
        east = west + res
    if north <= south:
        north = south + res

    for _ in range(12):
        cols = max(1, int(math.floor((east - west) / res)) + 1)
        rows = max(1, int(math.floor((north - south) / res)) + 1)
        if rows * cols <= max_points:
            break
        res *= 1.6

    cols = max(1, int(math.floor((east - west) / res)) + 1)
    rows = max(1, int(math.floor((north - south) / res)) + 1)
    lons = [west + (i + 0.5) * res for i in range(cols)]
    lats = [south + (j + 0.5) * res for j in range(rows)]
    # Keep north→south order consistent with Open-Meteo client (high lat first)
    lats = list(reversed(lats))
    return lats, lons, res


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
    }


def _unix_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(value) if value is not None else None
