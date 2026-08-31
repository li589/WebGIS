"""端点单点定义与网络参数 env 覆盖测试（硬编码清理 2026-08-20 A5+E1）。"""

from __future__ import annotations

import importlib

import pytest


_ENDPOINT_DEFAULTS = {
    "NSMC_PORTAL_BASE": "https://satellite.nsmc.org.cn/DataPortal",
    "NSMC_CENTER_BASE": "http://fy4.nsmc.org.cn/center/v1/user",
    "CMR_GRANULES_UMM_JSON": "https://cmr.earthdata.nasa.gov/search/granules.umm_json",
    "CMR_GRANULES_JSON": "https://cmr.earthdata.nasa.gov/search/granules.json",
    "URS_TOKEN_URL": "https://urs.earthdata.nasa.gov/api/users/token",
    "URS_TOKENS_URL": "https://urs.earthdata.nasa.gov/api/users/tokens",
    "URS_PROFILE_URL": "https://urs.earthdata.nasa.gov/profile",
}


class TestEndpointsDefaults:
    def test_default_values_match_original_hardcoded(self):
        from ingest import endpoints

        for name, expected in _ENDPOINT_DEFAULTS.items():
            assert getattr(endpoints, name) == expected, name

    def test_env_override_takes_effect(self, monkeypatch):
        monkeypatch.setenv(
            "CGDA_NSMC_PORTAL_BASE", "https://mirror.example.org/DataPortal/"
        )
        from ingest import endpoints

        reloaded = importlib.reload(endpoints)
        assert (
            reloaded.NSMC_PORTAL_BASE == "https://mirror.example.org/DataPortal"
        )  # 尾斜杠已去
        # 还原（reload 会污染模块状态，回 reload 一次默认 env）
        monkeypatch.delenv("CGDA_NSMC_PORTAL_BASE")
        importlib.reload(reloaded)

    def test_derived_urls_follow_portal_base(self):
        from ingest import endpoints

        assert endpoints.NSMC_HOME_URL.startswith(endpoints.NSMC_PORTAL_BASE)
        assert endpoints.NSMC_LOGIN_ENTRY.startswith(endpoints.NSMC_PORTAL_BASE)


class TestNetworkParamsEnvOverride:
    """E1：下载/HTTP 超时与重试 env 覆盖（默认值不变）。"""

    def test_nsidc_defaults(self):
        from ingest import nsidc_download as nd

        assert nd.MAX_RETRIES == 3
        assert nd.REQUEST_TIMEOUT == 60
        assert nd.DOWNLOAD_TIMEOUT == 3600
        assert nd.MIN_DISK_FREE_GB == 5.0

    def test_nsidc_env_override(self, monkeypatch):
        monkeypatch.setenv("CGDA_DOWNLOAD_RETRIES", "7")
        monkeypatch.setenv("CGDA_HTTP_TIMEOUT", "120")
        from ingest import nsidc_download as nd

        reloaded = importlib.reload(nd)
        assert reloaded.MAX_RETRIES == 7
        assert reloaded.REQUEST_TIMEOUT == 120
        for key in ("CGDA_DOWNLOAD_RETRIES", "CGDA_HTTP_TIMEOUT"):
            monkeypatch.delenv(key)
        importlib.reload(reloaded)

    def test_nsmc_download_timeout_default(self):
        from ingest import nsmc_portal

        assert nsmc_portal._DOWNLOAD_TIMEOUT == 600.0

    def test_remote_sync_timeouts_default(self):
        from ingest import remote_sync

        assert remote_sync._HTTP_TIMEOUT == 30.0
        assert remote_sync._DOWNLOAD_TIMEOUT_SFTP == 300.0


class TestNoDuplicateEndpointLiterals:
    """算法包内不再散落重复端点字面量（nsmc_portal/nsidc/gldas/data_access_nodes）。"""

    @pytest.mark.parametrize(
        ("module_path", "literal"),
        [
            ("ingest/nsidc_download.py", "urs.earthdata.nasa.gov/profile"),
            ("ingest/nsidc_download.py", "cmr.earthdata.nasa.gov/search/granules"),
            ("ingest/gldas_download.py", "cmr.earthdata.nasa.gov/search/granules"),
            ("modules/data_access_nodes.py", "urs.earthdata.nasa.gov/api/users"),
            ("modules/data_access_nodes.py", "cmr.earthdata.nasa.gov/search/granules"),
        ],
    )
    def test_endpoint_literals_removed(self, module_path, literal):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2]
            / "Code"
            / "algorithms"
            / "providers"
            / "Python"
            / module_path
        ).read_text(encoding="utf-8")
        assert literal not in src, f"{module_path} 仍含散落端点 {literal}"

    def test_nsmc_portal_no_hardcoded_assignment(self):
        """nsmc_portal 允许 docstring 协议文档含域名，但不得再有硬编码赋值。"""
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2]
            / "Code"
            / "algorithms"
            / "providers"
            / "Python"
            / "ingest"
            / "nsmc_portal.py"
        ).read_text(encoding="utf-8")
        assert '_PORTAL_BASE = "https://' not in src
        assert '_CENTER_BASE = "http' not in src
        assert '_TOKENSYNC = "https://' not in src
