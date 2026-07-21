"""Unified weather outbound fetch gateway.

All REST tile / point / DAG node outbound weather I/O should go through this
module so Provider enablement, effective TTL, and base_url overrides stay
consistent. ``OpenMeteoClient`` remains an implementation detail behind
``OpenMeteoProvider``.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.weatherengine.default_model import weather_default_model
from app.services.effective_config import get_weather_cache_ttl_seconds
from app.weatherengine.constants import WEATHER_LAYER_SPECS, WeatherLayerSpec
from app.weatherengine.provider_base import ProviderType, WeatherProvider
from app.weatherengine.provider_registry import get_registry
from shared.contracts.api_contracts import BoundingBox

logger = logging.getLogger(__name__)


class WeatherProviderUnavailableError(ValueError):
    """Raised when no enabled provider supports the requested layer."""


def resolve_layer_spec(layer_id: str) -> WeatherLayerSpec:
    spec = WEATHER_LAYER_SPECS.get(layer_id)
    if spec is None:
        raise ValueError(f"Unsupported weather layer: {layer_id}")
    return spec


from app.weatherengine.provider_ids import normalize_provider_id, provider_grid_mode


def resolve_provider_for_layer(
    layer_id: str,
    *,
    provider_id: str | None = None,
    exclude: tuple[str, ...] = (),
) -> WeatherProvider:
    """Resolve an enabled provider for ``layer_id``.

    - If ``provider_id`` is set: must be enabled and support the layer (no silent fallback).
    - Else: registry priority order, honoring ``exclude``.
    Legacy ``open-meteo`` is normalized to ``open-meteo-online``.
    """
    registry = get_registry()
    if provider_id:
        pid = normalize_provider_id(str(provider_id).strip())
        if not pid or pid.lower() in {"auto", "default"}:
            provider_id = None
        else:
            provider = registry.get_provider(pid)
            if provider is None:
                raise WeatherProviderUnavailableError(
                    f"Weather provider '{pid}' is not registered."
                )
            if not registry.is_enabled(pid):
                raise WeatherProviderUnavailableError(
                    f"Weather provider '{pid}' is disabled. "
                    "Enable it in Settings → Weather Providers."
                )
            if not provider.supports_layer(layer_id):
                raise WeatherProviderUnavailableError(
                    f"Weather provider '{pid}' does not support layer '{layer_id}'."
                )
            return provider

    provider = registry.get_provider_for_layer(layer_id, exclude=exclude)
    if provider is None:
        raise WeatherProviderUnavailableError(
            f"No enabled weather provider supports layer '{layer_id}'. "
            "Enable a provider in Settings → Weather Providers."
        )
    return provider


def require_provider_for_layer(layer_id: str, *, provider_id: str | None = None):
    return resolve_provider_for_layer(layer_id, provider_id=provider_id)


def list_providers_for_layer(layer_id: str, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    """UI helper: providers that declare support for ``layer_id``."""
    from app.weatherengine.field_mapping import (
        COMMERCIAL_LAYER_IDS,
        commercial_data_quality,
        commercial_layer_hint,
    )

    registry = get_registry()
    rows: list[dict[str, Any]] = []
    for provider, priority, enabled in registry.list_provider_entries():
        if not provider.supports_layer(layer_id):
            continue
        if not include_disabled and not enabled:
            continue
        row: dict[str, Any] = {
            "provider_id": provider.provider_id,
            "display_name": provider.display_name,
            "enabled": enabled,
            "priority": priority,
            "provider_type": str(provider.provider_type.value)
            if hasattr(provider.provider_type, "value")
            else str(provider.provider_type),
            "grid_mode": provider_grid_mode(provider.provider_id),
        }
        if layer_id in COMMERCIAL_LAYER_IDS and provider.provider_id in ("weatherapi", "openweather"):
            row["data_quality"] = commercial_data_quality(layer_id)
            row["hint"] = commercial_layer_hint(layer_id)
        rows.append(row)
    rows.sort(key=lambda r: (r["priority"], r["provider_id"]))
    return rows


def _call_point(
    provider: WeatherProvider,
    *,
    latitude: float,
    longitude: float,
    spec: WeatherLayerSpec,
    model: str,
    forecast_hours: int,
    ttl_seconds: int,
) -> tuple[dict[str, Any], str]:
    return provider.fetch_point_forecast(
        latitude=latitude,
        longitude=longitude,
        layer_spec=spec,
        model=model,
        forecast_hours=forecast_hours,
        ttl_seconds=ttl_seconds,
        pressure_levels=spec.pressure_levels or None,
    )


def _call_grid(
    provider: WeatherProvider,
    *,
    bbox: BoundingBox,
    resolution: float,
    spec: WeatherLayerSpec,
    model: str,
    ttl_seconds: int,
) -> tuple[dict[str, Any], str]:
    return provider.fetch_grid_forecast(
        bbox=bbox,
        resolution=resolution,
        layer_spec=spec,
        model=model,
        ttl_seconds=ttl_seconds,
        pressure_levels=spec.pressure_levels or None,
    )


def fetch_point_forecast(
    *,
    layer_id: str,
    latitude: float,
    longitude: float,
    model: str | None = None,
    forecast_hours: int | None = None,
    ttl_seconds: int | None = None,
    layer_spec: WeatherLayerSpec | None = None,
    provider_id: str | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Fetch point forecast via registry.

    Returns:
        (payload, cache_status, provider_id)
    """
    spec = layer_spec or resolve_layer_spec(layer_id)
    pinned = bool(provider_id and str(provider_id).strip().lower() not in {"", "auto", "default"})
    provider = resolve_provider_for_layer(layer_id, provider_id=provider_id)
    resolved_model = model or weather_default_model()
    resolved_hours = forecast_hours or settings.weather_refresh_forecast_hours
    resolved_ttl = ttl_seconds if ttl_seconds is not None else get_weather_cache_ttl_seconds()

    try:
        payload, cache_status = _call_point(
            provider,
            latitude=latitude,
            longitude=longitude,
            spec=spec,
            model=resolved_model,
            forecast_hours=resolved_hours,
            ttl_seconds=resolved_ttl,
        )
        return payload, cache_status, provider.provider_id
    except Exception as first_exc:
        if pinned:
            raise
        logger.warning(
            "Point fetch failed for provider=%s layer=%s: %s; trying fallback",
            provider.provider_id,
            layer_id,
            first_exc,
        )
        try:
            fallback = resolve_provider_for_layer(
                layer_id,
                exclude=(provider.provider_id,),
            )
        except WeatherProviderUnavailableError:
            # No alternate source — surface the original upstream failure.
            raise first_exc from first_exc
        payload, cache_status = _call_point(
            fallback,
            latitude=latitude,
            longitude=longitude,
            spec=spec,
            model=resolved_model,
            forecast_hours=resolved_hours,
            ttl_seconds=resolved_ttl,
        )
        return payload, cache_status, fallback.provider_id


def _is_sparse_grid_provider(provider: WeatherProvider) -> bool:
    """商业点采样源不适合地图瓦片网格（点数极少，视觉上像「只加载了一部分」）。"""
    ptype = provider.provider_type
    ptype_str = ptype.value if hasattr(ptype, "value") else str(ptype)
    return ptype_str == ProviderType.COMMERCIAL_API


def fetch_grid_forecast(
    *,
    layer_id: str,
    bbox: BoundingBox,
    resolution: float,
    model: str | None = None,
    ttl_seconds: int | None = None,
    layer_spec: WeatherLayerSpec | None = None,
    provider_id: str | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Fetch grid forecast via registry.

    Map tiles need dense grids. Commercial providers (WeatherAPI / OpenWeather)
    only sample a handful of points per tile — so for grid/tile paths we prefer
    free dense sources (Open-Meteo) even when the UI has pinned a commercial
    provider. Point forecasts still honor the pin.

    Returns:
        (grid_data, cache_status, provider_id)
    """
    spec = layer_spec or resolve_layer_spec(layer_id)
    pinned = bool(provider_id and str(provider_id).strip().lower() not in {"", "auto", "default"})
    provider = resolve_provider_for_layer(layer_id, provider_id=provider_id)

    # 瓦片网格：商业源钉选时改走 registry 优先级中的密集源
    if pinned and _is_sparse_grid_provider(provider):
        try:
            dense = resolve_provider_for_layer(layer_id, exclude=(provider.provider_id,))
            if not _is_sparse_grid_provider(dense):
                logger.info(
                    "Grid tile prefers dense provider=%s over pinned commercial=%s for layer=%s",
                    dense.provider_id,
                    provider.provider_id,
                    layer_id,
                )
                provider = dense
                pinned = False
        except WeatherProviderUnavailableError:
            logger.warning(
                "Pinned commercial provider=%s for grid layer=%s; no dense fallback available",
                provider.provider_id,
                layer_id,
            )

    resolved_model = model or weather_default_model()
    resolved_ttl = ttl_seconds if ttl_seconds is not None else get_weather_cache_ttl_seconds()

    try:
        grid_data, cache_status = _call_grid(
            provider,
            bbox=bbox,
            resolution=resolution,
            spec=spec,
            model=resolved_model,
            ttl_seconds=resolved_ttl,
        )
        return grid_data, cache_status, provider.provider_id
    except Exception as first_exc:
        if pinned:
            raise
        logger.warning(
            "Grid fetch failed for provider=%s layer=%s: %s; trying fallback",
            provider.provider_id,
            layer_id,
            first_exc,
        )
        try:
            fallback = resolve_provider_for_layer(
                layer_id,
                exclude=(provider.provider_id,),
            )
        except WeatherProviderUnavailableError:
            raise first_exc from first_exc
        grid_data, cache_status = _call_grid(
            fallback,
            bbox=bbox,
            resolution=resolution,
            spec=spec,
            model=resolved_model,
            ttl_seconds=resolved_ttl,
        )
        return grid_data, cache_status, fallback.provider_id