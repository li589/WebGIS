"""天气源 Provider 抽象基类。

定义统一的天气数据获取接口，支持多源接入（免费 API、付费商业 API、本地数据源）。
与 ``app.services.api_config.ApiConfigManager`` 互补：
- ``ApiConfigManager``：配置层，管理"有哪些 Provider 可用"（API Key、URL、启用状态）
- ``WeatherProvider``：运行时层，定义"如何调用 Provider 获取数据"（HTTP 调用、缓存、断路器）
- ``WeatherProviderRegistry``：注册运行时 Provider 实例，按图层能力路由

设计原则：
1. 抽象方法最小化 —— 仅 ``fetch_point_forecast`` 和 ``fetch_grid_forecast`` 是必须实现的
2. 元数据通过 abstractproperty 暴露，便于注册表索引与 UI 展示
3. ``get_status`` / ``get_config_schema`` / ``test_connection`` 提供默认实现，Provider 可按需覆盖
4. 同步接口（与现有 OpenMeteoClient 一致），避免引入 asyncio 复杂度
5. ``supported_capabilities`` 用 frozenset[str]，元素为 ``WeatherLayerSpec.layer_id`` 或类别名
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from shared.contracts.api_contracts import BoundingBox

from app.weatherengine.constants import WeatherLayerSpec

logger = logging.getLogger(__name__)


# ── Provider 类型枚举（字符串常量，避免强类型耦合） ─────────────────────────────


class ProviderType:
    """Provider 类型常量。

    用字符串而非 Enum，便于第三方 Provider 扩展自定义类型而无需修改本文件。
    """

    FREE_API = "free_api"  # 免费公开 API（如 Open-Meteo、NOAA、ERA5）
    COMMERCIAL_API = "commercial_api"  # 付费商业 API（如 AccuWeather、WeatherAPI）
    LOCAL_DATA = "local_data"  # 本地数据源（如 GRIB 文件、本地气象站）


# ── 能力常量（与 WeatherLayerSpec.layer_id 对齐） ───────────────────────────────


class WeatherCapability:
    """天气图层能力常量。

    元素值与 ``WeatherLayerSpec.layer_id`` 一致，Provider 通过 ``supported_capabilities``
    声明自己支持哪些图层。也支持通配能力：
    - ``"all"``：支持所有图层（默认 fallback）
    - ``"point_query"``：支持点查询（不一定支持网格）
    - ``"grid_query"``：支持网格查询
    """

    ALL = "all"
    POINT_QUERY = "point_query"
    GRID_QUERY = "grid_query"


# ── Provider 状态数据类 ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    """Provider 运行时状态快照。用于 UI 展示与监控。"""

    provider_id: str
    enabled: bool
    healthy: bool  # 是否健康（最近一次调用成功）
    circuit_state: str = "closed"  # closed / open / half_open / n/a
    last_error: str | None = None  # 最近一次错误信息
    last_tested_at: str | None = None  # ISO8601 时间戳
    last_test_status: str | None = None  # "ok" / "failed" / None
    # 用量监控（可选，免费 API 关心每日预算；付费 API 关心计费；本地数据关心读取次数）
    daily_quota: int | None = None  # 每日总配额，None 表示无限制
    daily_used: int | None = None  # 今日已用次数
    daily_remaining: int | None = None  # 今日剩余次数
    # 缓存统计
    cache_hits: int = 0
    cache_misses: int = 0
    # 自定义元数据（Provider 特定信息，如版本号、数据更新时间等）
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Provider 配置 Schema ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ConfigFieldSchema:
    """单个配置字段的 UI 渲染 schema。"""

    key: str  # 配置键名
    label: str  # UI 展示标签
    field_type: str  # "string" / "password" / "int" / "float" / "bool" / "select"
    required: bool = False
    default: Any = None
    description: str = ""
    options: tuple[str, ...] = ()  # field_type="select" 时的可选项
    placeholder: str = ""


# ── 抽象基类 ───────────────────────────────────────────────────────────────────


class WeatherProvider(ABC):
    """天气源 Provider 抽象基类。

    所有天气数据源（Open-Meteo、NOAA、AccuWeather、本地 GRIB 等）都应实现本接口，
    并通过 ``WeatherProviderRegistry.register`` 注册，供系统按图层能力路由调用。

    实现要点：
    - ``provider_id`` 必须全局唯一，建议用小写连字符格式（如 ``"open-meteo-online"``）
    - ``supported_capabilities`` 决定了哪些图层会路由到本 Provider
    - ``fetch_point_forecast`` 和 ``fetch_grid_forecast`` 必须线程安全
    - 失败时应抛出异常，由调用方决定降级策略（如 fallback 到其他 Provider 或 stale cache）
    """

    # ── 元数据属性（必须实现） ─────────────────────────────────────────────────

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Provider 唯一标识，如 ``"open-meteo-online"``、``"weatherapi"``、``"openweather"``。"""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """UI 展示名称，如 ``"Open-Meteo"``、``"NOAA GFS"``。"""

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider 类型，取 ``ProviderType`` 常量。"""

    @property
    @abstractmethod
    def supported_capabilities(self) -> frozenset[str]:
        """支持的图层能力集。

        元素为 ``WeatherLayerSpec.layer_id`` 或 ``WeatherCapability`` 通配常量。
        例如：``frozenset({"wind-field", "wind-field-80m", "temperature"})``
        或 ``frozenset({WeatherCapability.ALL})`` 表示支持所有图层。
        """

    @property
    def version(self) -> str:
        """Provider 版本号，用于日志与 UI 展示。默认 ``"1.0"``。"""
        return "1.0"

    @property
    def description(self) -> str:
        """Provider 描述文本，用于 UI 展示。默认空字符串。"""
        return ""

    @property
    def homepage_url(self) -> str | None:
        """Provider 主页 URL，用于 UI 展示链接。默认 None。"""
        return None

    @property
    def requires_api_key(self) -> bool:
        """是否需要 API Key。免费 API 通常返回 False。默认 False。"""
        return False

    # ── 核心数据获取方法（必须实现） ───────────────────────────────────────────

    @abstractmethod
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
        """获取单点预报数据。

        Args:
            latitude: 纬度
            longitude: 经度
            layer_spec: 图层规格（决定请求字段与渲染方式）
            model: 预报模型（如 ``"best_match"``、``"gfs_global"``）
            forecast_hours: 预报小时数
            ttl_seconds: 缓存有效期（秒）
            pressure_levels: 气压层（hPa），如 ``(850, 500, 200)``；None 表示不需要

        Returns:
            (payload, cache_status): payload 为原始预报数据字典；
            cache_status 为 ``"hit"`` / ``"miss"`` / ``"stale"`` 等标识

        Raises:
            Exception: 调用失败时抛出，由调用方决定降级策略
        """

    @abstractmethod
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
        """批量获取网格化预报数据。

        Args:
            bbox: 地理边界框
            resolution: 网格分辨率（度），如 0.25 约 25km
            layer_spec: 图层规格
            model: 预报模型
            ttl_seconds: 缓存有效期（秒）
            pressure_levels: 气压层（hPa）

        Returns:
            (grid_data, cache_status): grid_data 包含 ``grid``、``current``、``hourly`` 等字段；
            cache_status 为 ``"hit"`` / ``"miss"`` / ``"stale"``

        Raises:
            Exception: 调用失败时抛出
        """

    # ── 可选方法（有默认实现，Provider 可覆盖） ───────────────────────────────

    def get_status(self) -> ProviderStatus:
        """返回 Provider 运行时状态快照。

        默认实现返回最小化状态（healthy=True, circuit_state="n/a"）。
        Provider 应覆盖此方法以提供真实的监控数据（断路器状态、配额使用等）。
        """
        return ProviderStatus(
            provider_id=self.provider_id,
            enabled=True,
            healthy=True,
            circuit_state="n/a",
        )

    def get_config_schema(self) -> list[ConfigFieldSchema]:
        """返回 Provider 配置字段的 UI 渲染 schema。

        默认实现返回空列表（无配置项）。
        需要 API Key 的 Provider 应覆盖此方法，声明 Key 字段。
        """
        return []

    def get_current_config(self) -> dict[str, Any]:
        """返回 Provider 当前配置（脱敏后，用于 UI 展示）。

        默认实现返回空字典。包含 API Key 等敏感字段时应做掩码处理。
        """
        return {}

    def apply_config(self, config: dict[str, Any]) -> None:
        """应用新配置（来自 UI 编辑）。

        默认实现忽略配置变更。Provider 应覆盖此方法以支持运行时配置更新。
        注意：应在应用后清除相关缓存，确保新配置立即生效。
        """
        # 默认无操作；子类覆盖时应记录日志
        logger.debug("Provider %s applied config (no-op by default)", self.provider_id)

    def test_connection(self) -> tuple[bool, str]:
        """测试 Provider 连通性。

        Returns:
            (success, message): success=True 表示连通正常；message 包含详细信息

        默认实现尝试调用 ``fetch_point_forecast`` 获取一个默认点的数据。
        Provider 可覆盖此方法以使用更轻量的测试方式（如 ping 健康检查端点）。
        """
        try:
            # 默认测试：获取广州的一个简单预报
            from app.weatherengine.constants import (
                WEATHER_LAYER_SPECS,
                DEFAULT_LAYER_ID,
            )

            layer_spec = WEATHER_LAYER_SPECS.get(DEFAULT_LAYER_ID)
            if layer_spec is None:
                # fallback：取第一个可用的 layer spec
                layer_spec = next(iter(WEATHER_LAYER_SPECS.values()))
            self.fetch_point_forecast(
                latitude=23.1291,
                longitude=113.2644,
                layer_spec=layer_spec,
                model="best_match",
                forecast_hours=1,
                ttl_seconds=60,
            )
            return True, "Connection test passed"
        except Exception as exc:
            return False, f"Connection test failed: {exc}"

    def supports_layer(self, layer_id: str) -> bool:
        """判断本 Provider 是否支持指定图层。

        默认实现：若 ``supported_capabilities`` 包含 ``WeatherCapability.ALL`` 或
        包含 ``layer_id`` 本身，则视为支持。
        """
        caps = self.supported_capabilities
        return WeatherCapability.ALL in caps or layer_id in caps

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"provider_id={self.provider_id!r} "
            f"type={self.provider_type} "
            f"caps={set(self.supported_capabilities)}>"
        )
