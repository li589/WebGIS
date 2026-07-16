"""Open-Meteo Provider 实现。

将现有 ``OpenMeteoClient`` 包装为 ``WeatherProvider`` 接口实现。

设计策略：**包装而非重构**
- ``OpenMeteoClient`` 仅作 Provider 内部传输实现
- 对外出站统一经 ``fetch_gateway`` / Registry
- ``OpenMeteoProvider`` 内部委托给 ``OpenMeteoClient`` 实例
- 暴露断路器状态、API 预算、缓存统计等监控信息
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

logger = logging.getLogger(__name__)


class OpenMeteoProvider(WeatherProvider):
    """Open-Meteo 免费天气 API 的 Provider 实现。

    特征：
    - 类型：``free_api``（无需 API Key）
    - 能力：``WeatherCapability.ALL``（支持所有已注册图层，因为 Open-Meteo 字段足够丰富）
    - 监控：暴露断路器状态、每日 API 预算使用情况
    - 配置：可调整 base_url（用于代理/镜像站），但默认使用官方端点
    """

    PROVIDER_ID = "open-meteo"
    DISPLAY_NAME = "Open-Meteo"
    HOMEPAGE_URL = "https://open-meteo.com/"
    DESCRIPTION = (
        "Open-Meteo 是开源免费气象数据 API，提供全球 1-16 天预报、"
        "历史数据、气候模型，支持 100+ 天气变量。无需 API Key，每日 10000 次调用限额。"
    )
    VERSION = "1.0.0"

    def __init__(self, client: OpenMeteoClient | None = None) -> None:
        self._client = client or OpenMeteoClient()
        self._base_url_override: str | None = None

    # ── 元数据属性 ───────────────────────────────────────────────────────────

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def provider_type(self) -> str:
        return ProviderType.FREE_API

    @property
    def supported_capabilities(self) -> frozenset[str]:
        # Open-Meteo 字段足够丰富，支持所有已注册图层
        # 用 ALL 通配，避免每次新增图层都要更新这里
        return frozenset({WeatherCapability.ALL})

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
        return False

    @property
    def base_url(self) -> str:
        """当前 API base URL（优先使用运行时覆盖）。"""
        return self._base_url_override or OPEN_METEO_BASE_URL

    # ── 核心数据获取方法（委托给 OpenMeteoClient） ───────────────────────────

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
        return self._client.fetch_point_forecast(
            latitude=latitude,
            longitude=longitude,
            layer_spec=layer_spec,
            model=model,
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
        return self._client.fetch_grid_forecast(
            bbox=bbox,
            resolution=resolution,
            layer_spec=layer_spec,
            model=model,
            ttl_seconds=ttl_seconds,
            pressure_levels=pressure_levels,
        )

    # ── 监控与状态 ───────────────────────────────────────────────────────────

    def get_status(self) -> ProviderStatus:
        """返回 Open-Meteo Provider 运行时状态。

        暴露断路器状态与每日 API 预算使用情况。

        注意：``enabled`` 字段此处无法获知 registry 中的启用状态（避免反向依赖），
        由 ``config_service._provider_to_dict`` 在序列化时用 registry 的实际值覆盖。
        """
        # 断路器状态（通过 property 访问，避免直接触碰私有成员）
        circuit_state = self._client.circuit_state  # closed / open / half_open
        # API 预算
        budget_remaining = self._client.budget_remaining()
        daily_used: int | None = None
        if budget_remaining is not None:
            daily_used = max(0, OPEN_METEO_DAILY_API_LIMIT - budget_remaining)

        # healthy 判定：断路器非 open 状态
        healthy = circuit_state != "open"

        return ProviderStatus(
            provider_id=self.provider_id,
            enabled=True,  # 占位值，由 _provider_to_dict 用 registry 实际值覆盖
            healthy=healthy,
            circuit_state=circuit_state,
            daily_quota=OPEN_METEO_DAILY_API_LIMIT,
            daily_used=daily_used,
            daily_remaining=budget_remaining,
            metadata={
                "base_url": self.base_url,
                "version": self.version,
            },
        )

    # ── 配置 ─────────────────────────────────────────────────────────────────

    def get_config_schema(self) -> list[ConfigFieldSchema]:
        """Open-Meteo 无需 API Key，但可配置 base_url（用于代理/镜像）。

        目前 base_url 仍由 constants.py 常量控制，这里仅作展示。
        未来支持运行时配置时可启用此字段。
        """
        return [
            ConfigFieldSchema(
                key="base_url",
                label="API 端点",
                field_type="string",
                required=False,
                default=self.base_url,
                description="Open-Meteo API 基础 URL，可改为镜像站",
                placeholder="https://api.open-meteo.com/v1/forecast",
            ),
        ]

    def get_current_config(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "requires_api_key": False,
            "daily_quota": OPEN_METEO_DAILY_API_LIMIT,
        }

    def apply_config(self, config: dict[str, Any]) -> None:
        base_url = config.get("base_url")
        if isinstance(base_url, str) and base_url.strip():
            self._base_url_override = base_url.strip().rstrip("?")
            self._client.base_url = self._base_url_override
            logger.info("OpenMeteoProvider base_url override applied: %s", self._base_url_override)
        else:
            # Empty/missing base_url clears override so "reset to defaults" works
            self._base_url_override = None
            from app.weatherengine.constants import OPEN_METEO_BASE_URL

            self._client.base_url = OPEN_METEO_BASE_URL
            logger.info(
                "OpenMeteoProvider.apply_config: cleared base_url override (keys=%s)",
                list(config.keys()),
            )

    # ── 连通性测试 ───────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """测试 Open-Meteo 连通性。

        使用一个轻量级的点查询（forecast_hours=1, ttl=60s）测试端到端连通性。
        """
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
            budget = self._client.budget_remaining()
            budget_msg = f"daily_remaining={budget}" if budget is not None else "budget=n/a"
            return True, f"Connection OK ({budget_msg})"
        except Exception as exc:
            return False, f"Connection failed: {exc}"

    # ── 访问底层 client（供需要 OpenMeteoClient 类型参数的旧代码使用） ───────

    @property
    def client(self) -> OpenMeteoClient:
        """暴露底层 OpenMeteoClient 实例。

        用于过渡期：现有代码若显式需要 OpenMeteoClient 类型，
        可通过 ``provider.client`` 获取，避免一次性重构所有调用点。
        """
        return self._client

    def __repr__(self) -> str:
        circuit_state = self._client.circuit_state
        return (
            f"<OpenMeteoProvider "
            f"provider_id={self.provider_id!r} "
            f"circuit={circuit_state}>"
        )
