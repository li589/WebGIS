"""天气源 Provider 注册表。

管理运行时 Provider 实例，提供按图层能力的路由能力。

设计要点：
1. 单例模式（``get_registry()`` 返回全局唯一实例）
2. 线程安全（注册/查询用 RLock 保护）
3. 支持 Provider 优先级（priority 数字越小越优先）
4. 支持 enable/disable（不卸载注册，仅跳过路由）
5. ``get_provider_for_layer`` 实现能力路由：在已启用 Provider 中按优先级选择首个支持该图层的
6. 不负责 Provider 持久化（由 ``weather_providers_repository`` 处理）

典型用法：
    from app.weatherengine.provider_registry import get_registry
    from app.weatherengine.providers.open_meteo_provider import OpenMeteoProvider

    registry = get_registry()
    registry.register(OpenMeteoProvider(), priority=0)

    # 按图层路由
    provider = registry.get_provider_for_layer("wind-field")
    if provider:
        payload, status = provider.fetch_point_forecast(...)
"""

from __future__ import annotations

import logging
import threading
from typing import Iterable

from app.weatherengine.provider_base import WeatherProvider, WeatherCapability

logger = logging.getLogger(__name__)


class WeatherProviderRegistry:
    """Provider 注册表与路由器。

    线程安全。单例通过 ``get_registry()`` 获取。
    """

    _instance: WeatherProviderRegistry | None = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> WeatherProviderRegistry:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        # 存储：(provider, priority, enabled)
        self._providers: dict[str, tuple[WeatherProvider, int, bool]] = {}
        self._lock = threading.RLock()
        self._initialized = True

    # ── 注册管理 ─────────────────────────────────────────────────────────────

    def register(
        self,
        provider: WeatherProvider,
        *,
        priority: int = 100,
        enabled: bool = True,
    ) -> None:
        """注册 Provider。

        若 ``provider.provider_id`` 已存在，覆盖旧实例并更新 priority/enabled。

        Args:
            provider: Provider 实例
            priority: 优先级（数字越小越优先），默认 100
            enabled: 是否启用，默认 True
        """
        pid = provider.provider_id
        with self._lock:
            existing = self._providers.get(pid)
            self._providers[pid] = (provider, priority, enabled)
        if existing is None:
            logger.info(
                "WeatherProvider registered: id=%s type=%s priority=%d enabled=%s",
                pid, provider.provider_type, priority, enabled,
            )
        else:
            logger.info(
                "WeatherProvider re-registered: id=%s priority=%d enabled=%s (replaced previous)",
                pid, priority, enabled,
            )

    def unregister(self, provider_id: str) -> bool:
        """注销 Provider。返回是否成功移除。"""
        with self._lock:
            if provider_id in self._providers:
                del self._providers[provider_id]
                logger.info("WeatherProvider unregistered: id=%s", provider_id)
                return True
            return False

    def set_enabled(self, provider_id: str, enabled: bool) -> bool:
        """启用/禁用 Provider（不卸载注册）。返回是否存在该 Provider。"""
        with self._lock:
            entry = self._providers.get(provider_id)
            if entry is None:
                return False
            provider, priority, _ = entry
            self._providers[provider_id] = (provider, priority, enabled)
            logger.info(
                "WeatherProvider %s -> enabled=%s",
                provider_id, enabled,
            )
            return True

    def set_priority(self, provider_id: str, priority: int) -> bool:
        """调整 Provider 优先级。返回是否存在该 Provider。"""
        with self._lock:
            entry = self._providers.get(provider_id)
            if entry is None:
                return False
            provider, _, enabled = entry
            self._providers[provider_id] = (provider, priority, enabled)
            return True

    # ── 查询 ─────────────────────────────────────────────────────────────────

    def list_providers(self, *, include_disabled: bool = False) -> list[WeatherProvider]:
        """列出所有已注册 Provider。默认仅返回已启用的。"""
        with self._lock:
            entries = list(self._providers.values())
        if include_disabled:
            return [e[0] for e in entries]
        return [e[0] for e in entries if e[2]]

    def list_provider_entries(self) -> list[tuple[WeatherProvider, int, bool]]:
        """列出所有 (provider, priority, enabled) 三元组（含禁用项）。"""
        with self._lock:
            return list(self._providers.values())

    def get_provider(self, provider_id: str) -> WeatherProvider | None:
        """按 ID 获取 Provider（无论启用状态）。"""
        with self._lock:
            entry = self._providers.get(provider_id)
        return entry[0] if entry else None

    def is_enabled(self, provider_id: str) -> bool:
        """检查 Provider 是否启用。未注册返回 False。"""
        with self._lock:
            entry = self._providers.get(provider_id)
        return bool(entry and entry[2])

    # ── 能力路由 ─────────────────────────────────────────────────────────────

    def get_provider_for_layer(
        self,
        layer_id: str,
        *,
        exclude: Iterable[str] = (),
    ) -> WeatherProvider | None:
        """按图层能力路由到首选可用 Provider。

        算法：
        1. 在已启用 Provider 中筛选出 ``supports_layer(layer_id)`` 为 True 的
        2. 按 priority 升序排序，返回首个
        3. 若无匹配，返回 None

        Args:
            layer_id: 图层 ID（对应 ``WeatherLayerSpec.layer_id``）
            exclude: 要排除的 provider_id 集合（用于 fallback 链）

        Returns:
            首选 Provider 或 None
        """
        exclude_set = set(exclude)
        with self._lock:
            candidates = [
                (provider, priority)
                for provider, priority, enabled in self._providers.values()
                if enabled and provider.provider_id not in exclude_set
            ]
        # 筛选支持该图层的
        supporting = [
            (provider, priority)
            for provider, priority in candidates
            if provider.supports_layer(layer_id)
        ]
        if not supporting:
            return None
        # 按 priority 升序，相同 priority 按 provider_id 字典序（保证稳定排序）
        supporting.sort(key=lambda x: (x[1], x[0].provider_id))
        return supporting[0][0]

    def get_providers_for_layer(self, layer_id: str) -> list[WeatherProvider]:
        """获取所有支持指定图层且已启用的 Provider 列表（按优先级排序）。

        用于 UI 展示"该图层可用哪些源"或实现 fallback 链。
        """
        with self._lock:
            candidates = [
                (provider, priority)
                for provider, priority, enabled in self._providers.values()
                if enabled
            ]
        supporting = [
            (provider, priority)
            for provider, priority in candidates
            if provider.supports_layer(layer_id)
        ]
        supporting.sort(key=lambda x: (x[1], x[0].provider_id))
        return [p for p, _ in supporting]

    # ── 批量操作 ─────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """清空所有注册（主要用于测试）。"""
        with self._lock:
            count = len(self._providers)
            self._providers.clear()
        logger.warning("WeatherProviderRegistry cleared: %d provider(s) removed", count)

    def __len__(self) -> int:
        with self._lock:
            return len(self._providers)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"<WeatherProviderRegistry "
                f"count={len(self._providers)} "
                f"enabled={sum(1 for _, _, e in self._providers.values() if e)}>"
            )


# ── 单例访问 ───────────────────────────────────────────────────────────────────

def get_registry() -> WeatherProviderRegistry:
    """获取全局 Provider 注册表单例。"""
    return WeatherProviderRegistry()


def register_default_providers() -> None:
    """注册默认 Provider（应用启动时调用）。

    - ``open-meteo`` priority=0，默认 enabled
    - ``weatherapi`` / ``openweather`` priority=10/20，默认 enabled=False（无 Key 不抢路由）
    已存在的 Provider 不会被覆盖（保留运行时/DB 覆盖）。
    """
    registry = get_registry()

    try:
        import os

        from app.weatherengine.providers.open_meteo_provider import OpenMeteoProvider
        from app.services.api_config import ApiProvider, api_config_manager

        if registry.get_provider("open-meteo") is None:
            provider = OpenMeteoProvider()
            openmeteo_url = os.getenv("BACKEND_OPEN_METEO_URL", "").strip()
            if not openmeteo_url:
                api_cfg = api_config_manager.get_config(ApiProvider.OPEN_METEO)
                if api_cfg and api_cfg.endpoint.url:
                    openmeteo_url = str(api_cfg.endpoint.url).strip()
            if openmeteo_url:
                provider.apply_config({"base_url": openmeteo_url})
            registry.register(provider, priority=0, enabled=True)
            logger.info("Registered weather provider: open-meteo")
    except Exception:
        logger.exception("Failed to register OpenMeteoProvider")

    try:
        from app.weatherengine.providers.weatherapi_provider import (
            WeatherApiProvider,
            bootstrap_api_key_from_env as bootstrap_weatherapi,
        )

        if registry.get_provider("weatherapi") is None:
            wapi = WeatherApiProvider()
            bootstrap_weatherapi(wapi)
            registry.register(wapi, priority=10, enabled=False)
            logger.info("Registered weather provider: weatherapi (disabled by default)")
    except Exception:
        logger.exception("Failed to register WeatherApiProvider")

    try:
        from app.weatherengine.providers.openweather_provider import (
            OpenWeatherProvider,
            bootstrap_api_key_from_env as bootstrap_openweather,
        )

        if registry.get_provider("openweather") is None:
            owm = OpenWeatherProvider()
            bootstrap_openweather(owm)
            registry.register(owm, priority=20, enabled=False)
            logger.info("Registered weather provider: openweather (disabled by default)")
    except Exception:
        logger.exception("Failed to register OpenWeatherProvider")
