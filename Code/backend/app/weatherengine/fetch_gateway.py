"""Unified weather outbound fetch gateway.

All REST tile / point / DAG node outbound weather I/O should go through this
module so Provider enablement, effective TTL, and base_url overrides stay
consistent. ``OpenMeteoClient`` remains an implementation detail behind
``OpenMeteoProvider``.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.effective_config import get_weather_cache_ttl_seconds
from app.weatherengine.constants import WEATHER_LAYER_SPECS, WeatherLayerSpec
from app.weatherengine.provider_registry import get_registry
from shared.contracts.api_contracts import BoundingBox


class WeatherProviderUnavailableError(ValueError):
    """Raised when no enabled provider supports the requested layer."""


def require_provider_for_layer(layer_id: str):
    provider = get_registry().get_provider_for_layer(layer_id)
    if provider is None:
        raise WeatherProviderUnavailableError(
            f"No enabled weather provider supports layer '{layer_id}'. "
            "Enable a provider in Settings → Weather Providers."
        )
    return provider


def resolve_layer_spec(layer_id: str) -> WeatherLayerSpec:
    spec = WEATHER_LAYER_SPECS.get(layer_id)
    if spec is None:
        raise ValueError(f"Unsupported weather layer: {layer_id}")
    return spec


def fetch_point_forecast(
    *,
    layer_id: str,
    latitude: float,
    longitude: float,
    model: str | None = None,
    forecast_hours: int | None = None,
    ttl_seconds: int | None = None,
    layer_spec: WeatherLayerSpec | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Fetch point forecast via registry.

    Returns:
        (payload, cache_status, provider_id)
    """
    spec = layer_spec or resolve_layer_spec(layer_id)
    provider = require_provider_for_layer(layer_id)
    resolved_model = model or settings.weather_default_model
    resolved_hours = forecast_hours or settings.weather_refresh_forecast_hours
    resolved_ttl = ttl_seconds if ttl_seconds is not None else get_weather_cache_ttl_seconds()
    payload, cache_status = provider.fetch_point_forecast(
        latitude=latitude,
        longitude=longitude,
        layer_spec=spec,
        model=resolved_model,
        forecast_hours=resolved_hours,
        ttl_seconds=resolved_ttl,
        pressure_levels=spec.pressure_levels or None,
    )
    return payload, cache_status, provider.provider_id


def fetch_grid_forecast(
    *,
    layer_id: str,
    bbox: BoundingBox,
    resolution: float,
    model: str | None = None,
    ttl_seconds: int | None = None,
    layer_spec: WeatherLayerSpec | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Fetch grid forecast via registry.

    Returns:
        (grid_data, cache_status, provider_id)
    """
    spec = layer_spec or resolve_layer_spec(layer_id)
    provider = require_provider_for_layer(layer_id)
    resolved_model = model or settings.weather_default_model
    resolved_ttl = ttl_seconds if ttl_seconds is not None else get_weather_cache_ttl_seconds()
    grid_data, cache_status = provider.fetch_grid_forecast(
        bbox=bbox,
        resolution=resolution,
        layer_spec=spec,
        model=resolved_model,
        ttl_seconds=resolved_ttl,
        pressure_levels=spec.pressure_levels or None,
    )
    return grid_data, cache_status, provider.provider_id
