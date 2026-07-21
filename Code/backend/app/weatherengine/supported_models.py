"""Open-Meteo / 天气引擎支持的预报模型白名单（前后端共用语义）。"""

from __future__ import annotations

from typing import TypedDict


class SupportedWeatherModel(TypedDict):
    id: str
    label: str
    region: str
    update_interval: str
    native_resolution: str
    forecast_horizon: str


SUPPORTED_WEATHER_MODELS: tuple[SupportedWeatherModel, ...] = (
    {
        "id": "ecmwf_ifs025",
        "label": "ECMWF IFS 0.25°（欧洲中期天气预报中心，全球，15 天）",
        "region": "global",
        "update_interval": "6h",
        "native_resolution": "0.25°",
        "forecast_horizon": "15d",
    },
    {
        "id": "gfs_global",
        "label": "GFS 0.25°（美国 NCEP，全球，16 天）",
        "region": "global",
        "update_interval": "6h",
        "native_resolution": "0.25°",
        "forecast_horizon": "16d",
    },
    {
        "id": "icon_global",
        "label": "ICON 0.25°（德国 DWD，全球，7.5 天）",
        "region": "global",
        "update_interval": "6h",
        "native_resolution": "0.25°",
        "forecast_horizon": "7.5d",
    },
    {
        "id": "icon_eu",
        "label": "ICON-EU 0.0625°（德国 DWD，欧洲区域）",
        "region": "europe",
        "update_interval": "3h",
        "native_resolution": "0.0625°",
        "forecast_horizon": "regional",
    },
    {
        "id": "jma_seamless",
        "label": "JMA（日本气象厅，全球，11 天）",
        "region": "global",
        "update_interval": "6h",
        "native_resolution": "seamless",
        "forecast_horizon": "11d",
    },
    {
        "id": "meteofrance_seamless",
        "label": "Météo-France（法国，全球，4 天）",
        "region": "global",
        "update_interval": "6h",
        "native_resolution": "seamless",
        "forecast_horizon": "4d",
    },
    {
        "id": "gem_seamless",
        "label": "GEM（加拿大环境部，全球，10 天）",
        "region": "global",
        "update_interval": "6h",
        "native_resolution": "seamless",
        "forecast_horizon": "10d",
    },
)

SUPPORTED_WEATHER_MODEL_IDS: frozenset[str] = frozenset(m["id"] for m in SUPPORTED_WEATHER_MODELS)


def is_supported_weather_model(model_id: str) -> bool:
    return (model_id or "").strip() in SUPPORTED_WEATHER_MODEL_IDS


def list_supported_weather_models() -> list[SupportedWeatherModel]:
    return [dict(m) for m in SUPPORTED_WEATHER_MODELS]  # type: ignore[misc]
