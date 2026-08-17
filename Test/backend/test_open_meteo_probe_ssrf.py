"""Open-Meteo 内部探针 SSRF 加固测试（Wave 1 / G1-03）。

覆盖两个探针入口：
- ``app.api.routers.weather_router._probe_local_open_meteo_coverage``
- ``app.services.weather_engine_settings.probe_local_open_meteo_reachable``

验证：
1. URL 属可信内部 Open-Meteo 集合 → 直连 urlopen（既有豁免），网络错误优雅降级
2. URL 不在可信集合 → 强制走 safe_urlopen，环回地址被 SSRF 策略阻断后
   **优雅降级**（local_unreachable / False）而非 500
"""

from __future__ import annotations

import importlib
import os
from unittest.mock import patch

from urllib.error import URLError


def _router_module():
    # 包 __init__ 中 weather_router 名字被 APIRouter 对象遮蔽，必须按模块路径取真模块
    return importlib.import_module("app.api.routers.weather_router")


def _env_without_open_meteo_override():
    return {
        k: v
        for k, v in os.environ.items()
        if k != "BACKEND_OPEN_METEO_LOCAL_URL"
    }


def test_coverage_probe_trusted_url_uses_plain_urlopen() -> None:
    """可信 URL 走直连分支：urlopen 抛 URLError 仍优雅降级。"""
    router = _router_module()

    with (
        patch.dict(os.environ, _env_without_open_meteo_override()),
        patch.object(router, "cache_get_json", return_value=None),
        patch.object(router, "_COVERAGE_CACHE", {}),
        patch.object(
            router,
            "urlopen",
            side_effect=URLError("connection refused"),
        ),
    ):
        coverage, error = router._probe_local_open_meteo_coverage("gfs_global")
    assert coverage is None
    assert error == "local_unreachable"


def test_coverage_probe_untrusted_url_blocked_by_ssrf() -> None:
    """非可信 URL 必须走 safe_urlopen：环回被策略阻断 → local_unreachable。"""
    router = _router_module()

    with (
        patch.dict(os.environ, _env_without_open_meteo_override()),
        patch.object(router, "cache_get_json", return_value=None),
        patch.object(router, "_COVERAGE_CACHE", {}),
        patch("app.core.ssrf.is_trusted_open_meteo_local_url", return_value=False),
        patch.object(
            router,
            "urlopen",
            side_effect=AssertionError("untrusted URL must not use bare urlopen"),
        ),
    ):
        coverage, error = router._probe_local_open_meteo_coverage("gfs_global")
    assert coverage is None
    assert error == "local_unreachable"


def test_reachability_probe_trusted_url_uses_plain_urlopen() -> None:
    from app.services import weather_engine_settings

    with (
        patch.dict(os.environ, _env_without_open_meteo_override()),
        patch.object(
            weather_engine_settings,
            "urlopen",
            side_effect=URLError("connection refused"),
        ),
    ):
        assert weather_engine_settings.probe_local_open_meteo_reachable() is False


def test_reachability_probe_untrusted_url_blocked_by_ssrf() -> None:
    from app.services import weather_engine_settings

    with (
        patch.dict(os.environ, _env_without_open_meteo_override()),
        patch("app.core.ssrf.is_trusted_open_meteo_local_url", return_value=False),
        patch.object(
            weather_engine_settings,
            "urlopen",
            side_effect=AssertionError("untrusted URL must not use bare urlopen"),
        ),
    ):
        assert weather_engine_settings.probe_local_open_meteo_reachable() is False
