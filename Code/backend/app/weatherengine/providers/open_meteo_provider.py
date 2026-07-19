"""Open-Meteo Provider 实现。

将现有 ``OpenMeteoClient`` 包装为 ``WeatherProvider`` 接口实现。
同一实现类可实例化为 online / local 两个 provider_id。
"""

from __future__ import annotations

import logging
from typing import Any

from shared.contracts.api_contracts import BoundingBox

from app.weatherengine.client import OpenMeteoClient
from app.weatherengine.constants import (
    OPEN_METEO_BASE_URL,
    OPEN_METEO_DAILY_API_LIMIT,
    WEATHER_LAYER_SPECS,
    WeatherLayerSpec,
)
from app.weatherengine.provider_base import (
    ConfigFieldSchema,
    ProviderStatus,
    ProviderType,
    WeatherCapability,
    WeatherProvider,
)
from app.weatherengine.provider_ids import (
    OPEN_METEO_LOCAL_ID,
    OPEN_METEO_LOCAL_URL,
    OPEN_METEO_ONLINE_ID,
    OPEN_METEO_ONLINE_URL,
    resolve_open_meteo_model,
)

logger = logging.getLogger(__name__)


class OpenMeteoProvider(WeatherProvider):
    """Open-Meteo 天气 API 的 Provider 实现（online 或 local）。"""

    HOMEPAGE_URL = "https://open-meteo.com/"
    VERSION = "1.0.0"

    def __init__(
        self,
        *,
        provider_id: str = OPEN_METEO_ONLINE_ID,
        display_name: str = "Open-Meteo (Online)",
        default_base_url: str = OPEN_METEO_ONLINE_URL,
        description: str | None = None,
        client: OpenMeteoClient | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._display_name = display_name
        self._default_base_url = (default_base_url or OPEN_METEO_BASE_URL).rstrip("?").rstrip("/")
        if self._default_base_url.endswith("/v1/forecast"):
            pass
        self._description = description or (
            "Open-Meteo 开源气象 API：全球预报与多变量。无需 API Key。"
        )
        self._client = client or OpenMeteoClient(base_url=self._default_base_url)
        self._base_url_override: str | None = None

    @classmethod
    def create_online(cls, client: OpenMeteoClient | None = None) -> OpenMeteoProvider:
        return cls(
            provider_id=OPEN_METEO_ONLINE_ID,
            display_name="Open-Meteo (Online)",
            default_base_url=OPEN_METEO_ONLINE_URL,
            description=(
                "公网 Open-Meteo（api.open-meteo.com）。免费限额约每日 10000 次。"
            ),
            client=client,
        )

    @classmethod
    def create_local(
        cls,
        *,
        base_url: str | None = None,
        client: OpenMeteoClient | None = None,
    ) -> OpenMeteoProvider:
        url = (base_url or OPEN_METEO_LOCAL_URL).strip() or OPEN_METEO_LOCAL_URL
        return cls(
            provider_id=OPEN_METEO_LOCAL_ID,
            display_name="Open-Meteo (Local)",
            default_base_url=url,
            description=(
                "自建 Open-Meteo（Docker，默认 http://127.0.0.1:8080）。"
                "需先 sync 气象库；未启动时请求会失败并可回退到其它源。"
            ),
            client=client,
        )

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider_type(self) -> str:
        return ProviderType.FREE_API

    @property
    def supported_capabilities(self) -> frozenset[str]:
        return frozenset({WeatherCapability.ALL})

    @property
    def version(self) -> str:
        return self.VERSION

    @property
    def description(self) -> str:
        return self._description

    @property
    def homepage_url(self) -> str | None:
        return self.HOMEPAGE_URL

    @property
    def requires_api_key(self) -> bool:
        return False

    @property
    def base_url(self) -> str:
        return self._base_url_override or self._default_base_url

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
        resolved_model = resolve_open_meteo_model(model, provider_id=self._provider_id)
        if resolved_model != model:
            logger.info(
                "[OpenMeteoProvider] remap model %s → %s for %s",
                model,
                resolved_model,
                self._provider_id,
            )
        return self._client.fetch_point_forecast(
            latitude=latitude,
            longitude=longitude,
            layer_spec=layer_spec,
            model=resolved_model,
            forecast_hours=forecast_hours,
            ttl_seconds=ttl_seconds,
            pressure_levels=pressure_levels,
        )

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
        resolved_model = resolve_open_meteo_model(model, provider_id=self._provider_id)
        if resolved_model != model:
            logger.info(
                "[OpenMeteoProvider] remap model %s → %s for %s",
                model,
                resolved_model,
                self._provider_id,
            )
        return self._client.fetch_grid_forecast(
            bbox=bbox,
            resolution=resolution,
            layer_spec=layer_spec,
            model=resolved_model,
            ttl_seconds=ttl_seconds,
            pressure_levels=pressure_levels,
        )

    def get_status(self) -> ProviderStatus:
        circuit_state = self._client.circuit_state
        budget_remaining = self._client.budget_remaining()
        daily_used: int | None = None
        if budget_remaining is not None:
            daily_used = max(0, OPEN_METEO_DAILY_API_LIMIT - budget_remaining)
        healthy = circuit_state != "open"
        return ProviderStatus(
            provider_id=self.provider_id,
            enabled=True,
            healthy=healthy,
            circuit_state=circuit_state,
            daily_quota=OPEN_METEO_DAILY_API_LIMIT if self.provider_id == OPEN_METEO_ONLINE_ID else None,
            daily_used=daily_used if self.provider_id == OPEN_METEO_ONLINE_ID else None,
            daily_remaining=budget_remaining if self.provider_id == OPEN_METEO_ONLINE_ID else None,
            metadata={
                "base_url": self.base_url,
                "version": self.version,
            },
        )

    def get_config_schema(self) -> list[ConfigFieldSchema]:
        return [
            ConfigFieldSchema(
                key="base_url",
                label="API 端点",
                field_type="string",
                required=False,
                default=self.base_url,
                description="Open-Meteo API 基础 URL",
                placeholder=self._default_base_url,
            ),
        ]

    def get_current_config(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "requires_api_key": False,
            "daily_quota": OPEN_METEO_DAILY_API_LIMIT if self.provider_id == OPEN_METEO_ONLINE_ID else None,
        }

    def apply_config(self, config: dict[str, Any]) -> None:
        base_url = config.get("base_url")
        if isinstance(base_url, str) and base_url.strip():
            self._base_url_override = base_url.strip().rstrip("?")
            self._client.base_url = self._base_url_override
            logger.info(
                "OpenMeteoProvider(%s) base_url override: %s",
                self.provider_id,
                self._base_url_override,
            )
        else:
            self._base_url_override = None
            self._client.base_url = self._default_base_url
            logger.info(
                "OpenMeteoProvider(%s).apply_config: cleared override -> %s",
                self.provider_id,
                self._default_base_url,
            )

    def test_connection(self) -> tuple[bool, str]:
        try:
            layer_spec = WEATHER_LAYER_SPECS.get("wind-field")
            if layer_spec is None:
                layer_spec = next(iter(WEATHER_LAYER_SPECS.values()))
            self._client.fetch_point_forecast(
                latitude=23.1291,
                longitude=113.2644,
                layer_spec=layer_spec,
                model="best_match",
                forecast_hours=1,
                ttl_seconds=60,
            )
            return True, f"Connection OK (base_url={self.base_url})"
        except Exception as exc:
            return False, f"Connection failed: {exc}"

    @property
    def client(self) -> OpenMeteoClient:
        return self._client

    def __repr__(self) -> str:
        return (
            f"<OpenMeteoProvider "
            f"provider_id={self.provider_id!r} "
            f"circuit={self._client.circuit_state}>"
        )
