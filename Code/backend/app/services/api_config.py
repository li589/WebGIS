"""
统一 API 配置管理模块

提供统一的 API 配置管理，支持切换不同数据源（gee、百度、高德、天地图、open-meteo 等）
"""

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class ApiProvider(Enum):
    """API 提供商枚举"""
    OPEN_METEO = "open-meteo"
    GEE = "gee"
    BAIDU = "baidu"
    GAODE = "gaode"
    TIANDITU = "tianditu"
    CUSTOM = "custom"


class DataType(Enum):
    """数据类型枚举"""
    WEATHER = "weather"
    ELEVATION = "elevation"
    SATELLITE = "satellite"
    TILE = "tile"
    GEOCODING = "geocoding"
    ROUTING = "routing"


@dataclass
class ApiEndpoint:
    """API 端点配置"""
    url: str
    requires_auth: bool = False
    rate_limit: Optional[int] = None  # 每分钟请求数限制
    timeout: int = 15  # 超时秒数
    retry_count: int = 3  # 重试次数
    capabilities: set[DataType] = field(default_factory=set)


@dataclass
class ApiConfig:
    """API 配置"""
    provider: ApiProvider
    name: str
    endpoint: ApiEndpoint
    api_key: Optional[str] = None
    enabled: bool = True
    priority: int = 0  # 优先级，数字越小优先级越高
    metadata: dict = field(default_factory=dict)


class ApiConfigManager:
    """统一管理所有 API 配置，支持动态切换和回退"""

    _instance: Optional["ApiConfigManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._configs: dict[ApiProvider, ApiConfig] = {}
        self._provider_aliases: dict[str, ApiProvider] = {}  # 别名映射
        self._data_type_providers: dict[DataType, list[ApiProvider]] = {}  # 数据类型 → 提供商列表
        self._initialized = True

        self._load_default_configs()
        self._load_from_env()

    def _load_default_configs(self):
        """加载默认配置"""

        # Open-Meteo（无需 API Key）
        self.register_config(ApiConfig(
            provider=ApiProvider.OPEN_METEO,
            name="Open-Meteo (Online)",
            endpoint=ApiEndpoint(
                url="https://api.open-meteo.com/v1/forecast",
                requires_auth=False,
                rate_limit=10000,
                timeout=15,
                capabilities={DataType.WEATHER},
            ),
            priority=0,
        ))

        # 天地图
        self.register_config(ApiConfig(
            provider=ApiProvider.TIANDITU,
            name="天地图",
            endpoint=ApiEndpoint(
                url="https://api.tianditu.gov.cn",
                requires_auth=True,
                rate_limit=500,
                timeout=10,
                capabilities={DataType.TILE, DataType.GEOCODING},
            ),
            priority=10,
        ))

        # 百度地图
        self.register_config(ApiConfig(
            provider=ApiProvider.BAIDU,
            name="百度地图",
            endpoint=ApiEndpoint(
                url="https://api.map.baidu.com",
                requires_auth=True,
                rate_limit=200,
                timeout=10,
                capabilities={DataType.TILE, DataType.GEOCODING, DataType.ROUTING},
            ),
            priority=20,
        ))

        # 高德地图
        self.register_config(ApiConfig(
            provider=ApiProvider.GAODE,
            name="高德地图",
            endpoint=ApiEndpoint(
                url="https://restapi.amap.com",
                requires_auth=True,
                rate_limit=500,
                timeout=10,
                capabilities={DataType.TILE, DataType.GEOCODING, DataType.ROUTING},
            ),
            priority=30,
        ))

        # GEE
        self.register_config(ApiConfig(
            provider=ApiProvider.GEE,
            name="Google Earth Engine",
            endpoint=ApiEndpoint(
                url="https://earthengine.googleapis.com",
                requires_auth=True,
                rate_limit=50,
                timeout=30,
                capabilities={DataType.SATELLITE, DataType.ELEVATION, DataType.WEATHER},
            ),
            priority=5,
        ))

    def _load_from_env(self):
        """从环境变量加载配置"""
        import os

        # 加载天地图 API Key
        tianditu_key = os.getenv("BACKEND_TIANDITU_API_KEY", "")
        if tianditu_key:
            self.update_api_key(ApiProvider.TIANDITU, tianditu_key)
            logger.info("[ApiConfigManager] Loaded Tianditu API key from environment")

        # 加载百度地图 API Key
        baidu_key = os.getenv("BACKEND_BAIDU_API_KEY", "")
        if baidu_key:
            self.update_api_key(ApiProvider.BAIDU, baidu_key)
            logger.info("[ApiConfigManager] Loaded Baidu API key from environment")

        # 加载高德地图 API Key
        gaode_key = os.getenv("BACKEND_GAODE_API_KEY", "")
        if gaode_key:
            self.update_api_key(ApiProvider.GAODE, gaode_key)
            logger.info("[ApiConfigManager] Loaded Gaode API key from environment")

        # 加载 GEE 凭证路径
        gee_credentials = os.getenv("BACKEND_GEE_CREDENTIALS_PATH", "")
        if gee_credentials:
            config = self.get_config(ApiProvider.GEE)
            if config:
                config.metadata["credentials_path"] = gee_credentials
                logger.info("[ApiConfigManager] Loaded GEE credentials path from environment")

        # Open-Meteo online 默认端点（local 由 weather provider registry 管理）
        openmeteo_url = os.getenv("BACKEND_OPEN_METEO_ONLINE_URL", "").strip()
        if openmeteo_url:
            config = self.get_config(ApiProvider.OPEN_METEO)
            if config:
                config.endpoint.url = openmeteo_url
                logger.info(f"[ApiConfigManager] Updated Open-Meteo online URL to {openmeteo_url}")

    def register_config(self, config: ApiConfig):
        """注册 API 配置"""
        self._configs[config.provider] = config

        # 更新数据类型映射
        for data_type in config.endpoint.capabilities:
            if data_type not in self._data_type_providers:
                self._data_type_providers[data_type] = []
            if config.provider not in self._data_type_providers[data_type]:
                self._data_type_providers[data_type].append(config.provider)

        logger.debug(f"[ApiConfigManager] Registered API config for {config.provider.value}")

    def get_config(self, provider: ApiProvider) -> Optional[ApiConfig]:
        """获取指定提供商的配置"""
        return self._configs.get(provider)

    def get_config_by_name(self, name: str) -> Optional[ApiConfig]:
        """通过名称获取配置（支持别名）"""
        # 直接查找
        for config in self._configs.values():
            if config.name == name or config.provider.value == name:
                return config
        # 通过别名查找
        provider = self._provider_aliases.get(name.lower())
        if provider:
            return self._configs.get(provider)
        return None

    def update_api_key(self, provider: ApiProvider, api_key: str):
        """更新 API Key"""
        config = self._configs.get(provider)
        if config:
            config.api_key = api_key
            logger.info(f"[ApiConfigManager] Updated API key for {provider.value}")

    def enable_provider(self, provider: ApiProvider, enabled: bool = True):
        """启用/禁用提供商"""
        config = self._configs.get(provider)
        if config:
            config.enabled = enabled
            logger.info(f"[ApiConfigManager] {'Enabled' if enabled else 'Disabled'} {provider.value}")

    def get_best_available(
        self,
        required_capabilities: Optional[set[DataType]] = None,
        require_auth: bool = False,
    ) -> Optional[ApiConfig]:
        """获取满足需求的最佳可用配置

        Args:
            required_capabilities: 所需的数据类型能力
            require_auth: 是否需要认证

        Returns:
            最佳可用配置，如果没有满足条件的则返回 None
        """
        candidates = []

        for config in self._configs.values():
            if not config.enabled:
                continue

            # 检查认证需求
            if require_auth and not config.endpoint.requires_auth:
                continue

            # 检查能力需求
            if required_capabilities:
                if not required_capabilities.issubset(config.endpoint.capabilities):
                    continue

            candidates.append(config)

        # 按优先级排序
        candidates.sort(key=lambda c: c.priority)

        return candidates[0] if candidates else None

    def get_providers_for_data_type(self, data_type: DataType) -> list[ApiConfig]:
        """获取支持指定数据类型的所有提供商配置"""
        providers = self._data_type_providers.get(data_type, [])
        configs = []
        for provider in providers:
            config = self._configs.get(provider)
            if config and config.enabled:
                configs.append(config)
        return configs

    def register_alias(self, alias: str, provider: ApiProvider):
        """注册提供商别名"""
        self._provider_aliases[alias.lower()] = provider

    def get_all_configs(self) -> dict[ApiProvider, ApiConfig]:
        """获取所有配置"""
        return self._configs.copy()

    def get_config_serializable(self, provider: ApiProvider) -> Optional[dict[str, Any]]:
        """获取可直接 JSON 序列化的 provider 配置（永不包含明文 api_key）。"""
        config = self._configs.get(provider)
        if config is None:
            return None
        return _to_public_config(config)

    def get_all_configs_serializable(self) -> dict[str, dict[str, Any]]:
        """获取所有可直接 JSON 序列化的配置（永不包含明文 api_key）。"""
        return {
            provider.value: _to_public_config(config)
            for provider, config in self._configs.items()
        }

    def get_enabled_configs(self) -> list[ApiConfig]:
        """获取所有已启用的配置"""
        return [c for c in self._configs.values() if c.enabled]

    def validate_config(self, provider: ApiProvider) -> tuple[bool, str]:
        """验证配置是否有效

        Returns:
            (is_valid, message)
        """
        config = self._configs.get(provider)
        if not config:
            return False, f"Provider {provider.value} not registered"

        if not config.enabled:
            return False, f"Provider {provider.value} is disabled"

        if config.endpoint.requires_auth and not config.api_key:
            return False, f"Provider {provider.value} requires API key but none is set"

        return True, "OK"


# 全局单例
api_config_manager = ApiConfigManager()


def _to_jsonable(value: Any) -> Any:
    """递归转换 Enum/dataclass/set，供 FastAPI JSONResponse 使用。"""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            field_info.name: _to_jsonable(getattr(value, field_info.name))
            for field_info in fields(value)
        }
    if isinstance(value, dict):
        return {
            str(_to_jsonable(key)): _to_jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, set):
        return sorted(_to_jsonable(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value


def _resolve_api_key_source(config: ApiConfig) -> str:
    """推断密钥来源展示字段：env | metadata | none（不含明文）。"""
    if config.api_key and str(config.api_key).strip():
        return "env"
    credentials_path = config.metadata.get("credentials_path") if config.metadata else None
    if isinstance(credentials_path, str) and credentials_path.strip():
        return "metadata"
    return "none"


# 热路径真实接线能力（与 capability 登记可宽可窄分离；仅列已有调用方的能力）
_HOT_PATH_WIRED: dict[ApiProvider, tuple[str, ...]] = {
    ApiProvider.OPEN_METEO: ("weather",),
    ApiProvider.TIANDITU: ("tile",),
    ApiProvider.BAIDU: ("tile",),
    ApiProvider.GAODE: ("tile",),  # CDN 瓦片代理可用；key 当前可不注入
    ApiProvider.GEE: ("satellite", "elevation"),  # 经 gee_bridge，不含 weather 热路径
}


def _to_public_config(config: ApiConfig) -> dict[str, Any]:
    """对外投影：剥离明文 api_key，仅暴露是否已配置与来源。"""
    payload = _to_jsonable(config)
    if not isinstance(payload, dict):
        return {}
    key_present = bool(config.api_key and str(config.api_key).strip())
    credentials_path = config.metadata.get("credentials_path") if config.metadata else None
    credentials_present = isinstance(credentials_path, str) and bool(credentials_path.strip())
    payload.pop("api_key", None)
    payload["api_key_configured"] = key_present or credentials_present
    payload["api_key_source"] = _resolve_api_key_source(config) if key_present or credentials_present else "none"
    wired = list(_HOT_PATH_WIRED.get(config.provider, ()))
    payload["wired_in_hot_path"] = wired
    payload["hot_path_notes"] = (
        "Capabilities listed in endpoint may include planned features; "
        "wired_in_hot_path is the actually invoked runtime surface."
    )
    return payload


# 便捷函数
def get_api_config(provider: ApiProvider) -> Optional[ApiConfig]:
    """获取指定提供商的配置"""
    return api_config_manager.get_config(provider)


def get_weather_api_config() -> Optional[ApiConfig]:
    """获取天气数据 API 配置（优先级最高）"""
    return api_config_manager.get_best_available(required_capabilities={DataType.WEATHER})


def get_tile_api_config() -> Optional[ApiConfig]:
    """获取瓦片数据 API 配置"""
    return api_config_manager.get_best_available(required_capabilities={DataType.TILE})


def get_geocoding_api_config() -> Optional[ApiConfig]:
    """获取地理编码 API 配置"""
    return api_config_manager.get_best_available(required_capabilities={DataType.GEOCODING})
