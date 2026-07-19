"""WeatherAPI.com commercial weather Provider."""

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
    SURFACE_LAYER_IDS,
    append_hourly_series,
    assemble_grid_from_point_payloads,
    build_empty_om_point_payload,
    compute_grid_axes,
    merge_current_fields,
    weatherapi_current_to_om,
    weatherapi_hour_to_om,
)
from app.weatherengine.provider_base import (
    ConfigFieldSchema,
    ProviderStatus,
    ProviderType,
    WeatherProvider,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.weatherapi.com/v1"
_DEFAULT_DAILY_QUOTA = 1_000_000  # free-tier varies; exposed for UI only


class WeatherApiProvider(WeatherProvider):
    PROVIDER_ID = "weatherapi"
    DISPLAY_NAME = "WeatherAPI.com"
    HOMEPAGE_URL = "https://www.weatherapi.com/"
    DESCRIPTION = (
        "WeatherAPI.com 商业天气 API。首批支持近地面风场、温度、降水与湿度"
        "（点查 + 网格采样）。需在设置中配置 API Key 并启用。"
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
        return frozenset(SURFACE_LAYER_IDS)

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
                description="WeatherAPI.com key（设置页保存后加密入库）",
                placeholder="your-weatherapi-key",
            ),
            ConfigFieldSchema(
                key="base_url",
                label="Base URL",
                field_type="string",
                required=False,
                default=_DEFAULT_BASE_URL,
                description="可覆盖为代理/镜像",
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
            # Ignore masked placeholder re-saves
            if key and "…" not in key and key != "****":
                self._api_key = key
        if "base_url" in config and config["base_url"]:
            self._base_url = str(config["base_url"]).rstrip("/")
        with self._lock:
            self._memory_cache.clear()
        logger.info("WeatherApiProvider.apply_config: base_url=%s has_key=%s", self._base_url, bool(self._api_key))

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
            payload, _ = self.fetch_point_forecast(
                latitude=23.1291,
                longitude=113.2644,
                layer_spec=_dummy_spec(),
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
        del model, pressure_levels  # unused — surface-only provider
        if layer_spec.layer_id not in SURFACE_LAYER_IDS:
            raise ValueError(f"WeatherAPI does not support layer '{layer_spec.layer_id}'")
        if not self._api_key:
            raise RuntimeError("WeatherAPI API Key is not configured")

        cache_key = f"point:{latitude:.4f},{longitude:.4f}:h{forecast_hours}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            self._cache_hits += 1
            return cached, "hit"

        days = max(1, min(3, (max(1, forecast_hours) + 23) // 24))
        raw = self._http_get(
            "/forecast.json",
            {
                "key": self._api_key,
                "q": f"{latitude},{longitude}",
                "days": days,
                "aqi": "no",
                "alerts": "no",
            },
        )
        payload = self._map_forecast_payload(raw, forecast_hours=forecast_hours)
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
        if layer_spec.layer_id not in SURFACE_LAYER_IDS:
            raise ValueError(f"WeatherAPI does not support layer '{layer_spec.layer_id}'")
        if not self._api_key:
            raise RuntimeError("WeatherAPI API Key is not configured")

        lats, lons, res = compute_grid_axes(bbox, resolution, max_points=64)
        cache_key = (
            f"grid:{bbox.west:.2f},{bbox.south:.2f},{bbox.east:.2f},{bbox.north:.2f}"
            f":r{res:.3f}:{layer_spec.layer_id}"
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
                    logger.warning("WeatherAPI grid sample failed at %.3f,%.3f: %s", lat, lon, exc)
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
        self._cache_set(cache_key, grid, ttl_seconds)
        self._cache_misses += 1
        return grid, "miss"

    def _map_forecast_payload(self, raw: dict[str, Any], *, forecast_hours: int) -> dict[str, Any]:
        payload = build_empty_om_point_payload(timezone=(raw.get("location") or {}).get("tz_id"))
        current_src = raw.get("current") or {}
        merge_current_fields(payload["current"], weatherapi_current_to_om(current_src))

        hours: list[dict[str, Any]] = []
        for day in (raw.get("forecast") or {}).get("forecastday") or []:
            hours.extend(day.get("hour") or [])
        hours = hours[: max(1, forecast_hours)]
        times: list[str] = []
        series: dict[str, list[Any | None]] = {
            "temperature_2m": [],
            "precipitation": [],
            "relative_humidity_2m": [],
            "wind_speed_10m": [],
            "wind_direction_10m": [],
        }
        for hour in hours:
            mapped = weatherapi_hour_to_om(hour)
            times.append(str(mapped.get("time") or ""))
            for key in series:
                series[key].append(mapped.get(key))
        append_hourly_series(payload["hourly"], times=times, series=series)
        return payload

    def _http_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        self._roll_daily_counter()
        with self._lock:
            if self._daily_used >= self._daily_quota:
                raise RuntimeError("WeatherAPI daily quota exhausted")
            self._daily_used += 1

        url = f"{self._base_url}{path}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "QingTian-WeatherEngine/1.0"})
        try:
            with urlopen(req, timeout=self._timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, dict):
                raise RuntimeError("WeatherAPI returned non-object JSON")
            self._last_error = None
            return data
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            self._last_error = f"HTTP {exc.code}: {detail[:200]}"
            raise RuntimeError(self._last_error) from exc
        except URLError as exc:
            self._last_error = str(exc.reason)
            raise RuntimeError(f"WeatherAPI network error: {exc.reason}") from exc

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


def _dummy_spec() -> WeatherLayerSpec:
    from app.weatherengine.constants import WEATHER_LAYER_SPECS

    return WEATHER_LAYER_SPECS["temperature"]


def bootstrap_api_key_from_env(provider: WeatherApiProvider) -> None:
    key = os.getenv("BACKEND_WEATHERAPI_API_KEY", "").strip()
    if key:
        provider.apply_config({"api_key": key})
