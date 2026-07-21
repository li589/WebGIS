"""OpenWeather One Call API commercial weather Provider."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shared.contracts.api_contracts import BoundingBox

from app.weatherengine.constants import WeatherLayerSpec
from app.weatherengine.field_mapping import (
    COMMERCIAL_LAYER_IDS,
    HEIGHT_LAYER_IDS,
    PRESSURE_LAYER_IDS,
    append_hourly_series,
    apply_commercial_height_extrapolation,
    assemble_grid_from_point_payloads,
    build_empty_om_point_payload,
    build_empty_pressure_grid,
    commercial_data_quality,
    compute_grid_axes,
    merge_current_fields,
    openweather_current_to_om,
    openweather_hour_to_om,
)
from app.weatherengine.provider_base import (
    ConfigFieldSchema,
    ProviderStatus,
    ProviderType,
    WeatherProvider,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openweathermap.org/data/3.0"
_DEFAULT_DAILY_QUOTA = 1_000


class OpenWeatherProvider(WeatherProvider):
    PROVIDER_ID = "openweather"
    DISPLAY_NAME = "OpenWeather One Call"
    HOMEPAGE_URL = "https://openweathermap.org/api/one-call-3"
    DESCRIPTION = (
        "OpenWeather One Call API 3.0。覆盖 catalog 全部图层："
        "近地面真值网格、高度层近地面外推、气压层稀疏不可用提示。需配置 API Key 并启用。"
    )
    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._api_key: str = ""
        self._base_url: str = _DEFAULT_BASE_URL
        self._timeout_seconds: float = 20.0
        self._daily_quota: int = _DEFAULT_DAILY_QUOTA
        self._lock = threading.RLock()
        self._day_key: str = ""
        self._daily_used: int = 0
        self._last_error: str | None = None
        self._cache_hits = 0
        self._cache_misses = 0
        self._memory_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def provider_type(self) -> str:
        return ProviderType.COMMERCIAL_API

    @property
    def supported_capabilities(self) -> frozenset[str]:
        return frozenset(COMMERCIAL_LAYER_IDS)

    @property
    def version(self) -> str:
        return self.VERSION

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def homepage_url(self) -> str | None:
        return self.HOMEPAGE_URL

    @property
    def requires_api_key(self) -> bool:
        return True

    def get_config_schema(self) -> list[ConfigFieldSchema]:
        return [
            ConfigFieldSchema(
                key="api_key",
                label="API Key",
                field_type="password",
                required=True,
                description="OpenWeather API Key",
                placeholder="your-openweather-key",
            ),
            ConfigFieldSchema(
                key="base_url",
                label="Base URL",
                field_type="string",
                required=False,
                default=_DEFAULT_BASE_URL,
                description="One Call 3.0 base（可覆盖代理）",
            ),
        ]

    def get_current_config(self) -> dict[str, Any]:
        masked = ""
        if self._api_key:
            masked = self._api_key[:4] + "…" if len(self._api_key) > 4 else "****"
        return {"api_key": masked, "base_url": self._base_url}

    def apply_config(self, config: dict[str, Any]) -> None:
        if not isinstance(config, dict):
            return
        if "api_key" in config and config["api_key"] is not None:
            key = str(config["api_key"]).strip()
            if key and "…" not in key and key != "****":
                self._api_key = key
        if "base_url" in config and config["base_url"]:
            self._base_url = str(config["base_url"]).rstrip("/")
        with self._lock:
            self._memory_cache.clear()
        logger.info("OpenWeatherProvider.apply_config: base_url=%s has_key=%s", self._base_url, bool(self._api_key))

    def get_status(self) -> ProviderStatus:
        self._roll_daily_counter()
        remaining = max(0, self._daily_quota - self._daily_used)
        return ProviderStatus(
            provider_id=self.provider_id,
            enabled=True,
            healthy=self._last_error is None or bool(self._api_key),
            circuit_state="n/a",
            last_error=self._last_error,
            daily_quota=self._daily_quota,
            daily_used=self._daily_used,
            daily_remaining=remaining,
            cache_hits=self._cache_hits,
            cache_misses=self._cache_misses,
            metadata={"base_url": self._base_url, "version": self.version},
        )

    def test_connection(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, "API Key is not configured"
        try:
            from app.weatherengine.constants import WEATHER_LAYER_SPECS

            payload, _ = self.fetch_point_forecast(
                latitude=23.1291,
                longitude=113.2644,
                layer_spec=WEATHER_LAYER_SPECS["temperature"],
                model="best_match",
                forecast_hours=1,
                ttl_seconds=60,
            )
            temp = (payload.get("current") or {}).get("temperature_2m")
            return True, f"OK (temperature_2m={temp})"
        except Exception as exc:
            return False, str(exc)

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
        del model, pressure_levels
        layer_id = layer_spec.layer_id
        if layer_id not in COMMERCIAL_LAYER_IDS:
            raise ValueError(f"OpenWeather does not support layer '{layer_id}'")
        if layer_id in PRESSURE_LAYER_IDS:
            empty = build_empty_om_point_payload()
            empty["data_quality"] = "sparse"
            empty["coverage"] = "sparse_unavailable"
            return empty, "miss"
        if not self._api_key:
            raise RuntimeError("OpenWeather API Key is not configured")

        cache_key = f"point:{latitude:.4f},{longitude:.4f}:h{forecast_hours}:{layer_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            self._cache_hits += 1
            return cached, "hit"

        raw = self._http_get(
            "/onecall",
            {
                "lat": f"{latitude:.6f}",
                "lon": f"{longitude:.6f}",
                "appid": self._api_key,
                "units": "metric",
                "exclude": "minutely,daily,alerts",
            },
        )
        payload = self._map_onecall_payload(raw, forecast_hours=forecast_hours)
        if layer_id in HEIGHT_LAYER_IDS:
            apply_commercial_height_extrapolation(payload, layer_id)
        else:
            payload["data_quality"] = commercial_data_quality(layer_id)
        self._cache_set(cache_key, payload, ttl_seconds)
        self._cache_misses += 1
        return payload, "miss"

    def fetch_grid_forecast(
        self,
        *,
        bbox: BoundingBox,
        resolution: float,
        layer_spec: WeatherLayerSpec,
        model: str,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        del model, pressure_levels
        layer_id = layer_spec.layer_id
        if layer_id not in COMMERCIAL_LAYER_IDS:
            raise ValueError(f"OpenWeather does not support layer '{layer_id}'")
        if not self._api_key and layer_id not in PRESSURE_LAYER_IDS:
            raise RuntimeError("OpenWeather API Key is not configured")

        if layer_id in PRESSURE_LAYER_IDS:
            empty = build_empty_pressure_grid(bbox=bbox, resolution=resolution, layer_spec=layer_spec)
            return empty, "miss"

        max_points = 25 if layer_id in HEIGHT_LAYER_IDS else 49
        lats, lons, res = compute_grid_axes(bbox, resolution, max_points=max_points)
        cache_key = (
            f"grid:{bbox.west:.2f},{bbox.south:.2f},{bbox.east:.2f},{bbox.north:.2f}"
            f":r{res:.3f}:{layer_id}"
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            self._cache_hits += 1
            return cached, "hit"

        point_payloads: list[dict[str, Any] | None] = []
        for lat in lats:
            for lon in lons:
                try:
                    payload, _ = self.fetch_point_forecast(
                        latitude=lat,
                        longitude=lon,
                        layer_spec=layer_spec,
                        model="best_match",
                        forecast_hours=6,
                        ttl_seconds=ttl_seconds,
                    )
                    point_payloads.append(payload)
                except Exception as exc:
                    logger.warning("OpenWeather grid sample failed at %.3f,%.3f: %s", lat, lon, exc)
                    point_payloads.append(None)

        grid = assemble_grid_from_point_payloads(
            bbox=bbox,
            resolution=res,
            lats=lats,
            lons=lons,
            point_payloads=point_payloads,
            current_fields=tuple(layer_spec.current_fields),
            hourly_fields=tuple(layer_spec.hourly_fields),
        )
        grid["data_quality"] = commercial_data_quality(layer_id)
        if layer_id in HEIGHT_LAYER_IDS:
            grid["proxy_from"] = "surface"
        self._cache_set(cache_key, grid, ttl_seconds)
        self._cache_misses += 1
        return grid, "miss"

    def _map_onecall_payload(self, raw: dict[str, Any], *, forecast_hours: int) -> dict[str, Any]:
        payload = build_empty_om_point_payload(timezone=raw.get("timezone"))
        merge_current_fields(payload["current"], openweather_current_to_om(raw.get("current") or {}))

        hours = list(raw.get("hourly") or [])[: max(1, forecast_hours)]
        times: list[str] = []
        series: dict[str, list[Any | None]] = {
            "temperature_2m": [],
            "precipitation": [],
            "relative_humidity_2m": [],
            "wind_speed_10m": [],
            "wind_direction_10m": [],
            "cloud_cover": [],
            "pressure_msl": [],
            "visibility": [],
            "dew_point_2m": [],
        }
        for hour in hours:
            mapped = openweather_hour_to_om(hour)
            times.append(str(mapped.get("time") or ""))
            for key in series:
                series[key].append(mapped.get(key))
        append_hourly_series(payload["hourly"], times=times, series=series)
        return payload

    def _http_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self._roll_daily_counter()
        with self._lock:
            if self._daily_used >= self._daily_quota:
                raise RuntimeError("OpenWeather daily quota exhausted")
            self._daily_used += 1

        url = f"{self._base_url}{path}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "QingTian-WeatherEngine/1.0"})
        try:
            with urlopen(req, timeout=self._timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise RuntimeError("OpenWeather returned non-object JSON")
            self._last_error = None
            return data
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            self._last_error = f"HTTP {exc.code}: {detail[:200]}"
            raise RuntimeError(self._last_error) from exc
        except URLError as exc:
            self._last_error = str(exc.reason)
            raise RuntimeError(f"OpenWeather network error: {exc.reason}") from exc

    def _roll_daily_counter(self) -> None:
        today = date.today().isoformat()
        with self._lock:
            if self._day_key != today:
                self._day_key = today
                self._daily_used = 0

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._memory_cache.get(key)
            if entry is None:
                return None
            expires_at, payload = entry
            if time.time() >= expires_at:
                self._memory_cache.pop(key, None)
                return None
            return payload

    def _cache_set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        with self._lock:
            self._memory_cache[key] = (time.time() + max(60, ttl_seconds), payload)
            while len(self._memory_cache) > 256:
                self._memory_cache.pop(next(iter(self._memory_cache)))


def bootstrap_api_key_from_env(provider: OpenWeatherProvider) -> None:
    key = os.getenv("BACKEND_OPENWEATHER_API_KEY", "").strip()
    if key:
        provider.apply_config({"api_key": key})
