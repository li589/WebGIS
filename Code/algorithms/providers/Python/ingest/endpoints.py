"""算法包外部服务端点单点定义（硬编码清理 2026-08-20 A5）。

此前 NSMC 门户 URL 与 NASA CMR/URS 端点在 nsmc_portal / nsidc_download /
gldas_download / data_access_nodes 四处重复硬编码——服务方换域名或接口
路径时需同步改多处。收敛到本模块，全部支持 env 覆盖（默认值与原硬编码
逐字一致，行为零变化）。

env 清单：
- ``CGDA_NSMC_PORTAL_BASE``（默认 https://satellite.nsmc.org.cn/DataPortal）
- ``CGDA_NSMC_CENTER_BASE``（默认 http://fy4.nsmc.org.cn/center/v1/user）
- ``CGDA_NSMC_TOKENSYNC_URL``（默认 data.nsmc.org.cn tokensync 端点）
- ``CGDA_CMR_SEARCH_URL`` / ``CGDA_CMR_SEARCH_URL_JSON``（granules 查询）
- ``CGDA_URS_TOKEN_URL`` / ``CGDA_URS_TOKENS_URL`` / ``CGDA_URS_PROFILE_URL``
"""

from __future__ import annotations

import os


def _env(key: str, default: str) -> str:
    """读 env 并去尾部斜杠（端点拼接一律无尾斜杠）。"""
    return os.getenv(key, default).rstrip("/")


# ── NSMC 国家卫星气象中心门户 ────────────────────────────────────────────────
NSMC_PORTAL_BASE = _env(
    "CGDA_NSMC_PORTAL_BASE", "https://satellite.nsmc.org.cn/DataPortal"
)
NSMC_HOME_URL = NSMC_PORTAL_BASE + "/cn/home/index.html"
NSMC_LOGIN_ENTRY = NSMC_PORTAL_BASE + "/v1/data/user/login"
NSMC_CENTER_BASE = _env(
    "CGDA_NSMC_CENTER_BASE", "http://fy4.nsmc.org.cn/center/v1/user"
)
NSMC_TOKENSYNC_URL = _env(
    "CGDA_NSMC_TOKENSYNC_URL",
    "https://data.nsmc.org.cn/portalsite/sup/user/tokensync.aspx",
)

# ── NASA CMR（Common Metadata Repository）granule 查询 ─────────────────────
CMR_GRANULES_UMM_JSON = _env(
    "CGDA_CMR_SEARCH_URL",
    "https://cmr.earthdata.nasa.gov/search/granules.umm_json",
)
CMR_GRANULES_JSON = _env(
    "CGDA_CMR_SEARCH_URL_JSON",
    "https://cmr.earthdata.nasa.gov/search/granules.json",
)

# ── NASA URS（Earthdata Login）令牌接口 ────────────────────────────────────
URS_TOKEN_URL = _env(
    "CGDA_URS_TOKEN_URL", "https://urs.earthdata.nasa.gov/api/users/token"
)
URS_TOKENS_URL = _env(
    "CGDA_URS_TOKENS_URL", "https://urs.earthdata.nasa.gov/api/users/tokens"
)
URS_PROFILE_URL = _env("CGDA_URS_PROFILE_URL", "https://urs.earthdata.nasa.gov/profile")
