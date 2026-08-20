"""开放门户目录：内置/自定义门户、URL 覆盖、连通性测试与 CMR 检索。

目录是门户元数据（组织/凭据/搜索能力）的单一真源；
``open_data_presets`` KV 继续作为 base URL 覆盖层（现有语义不变），
``portal_catalog_custom`` KV 存自定义门户，``portal_alt_urls`` KV 存备用地址覆盖。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from app.core.ssrf import safe_urlopen, validate_url_for_storage
from app.services.portal_credentials import load_portal_credentials_secret

logger = logging.getLogger(__name__)

_PORTAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")

VALID_AUTH_TYPES = frozenset({"bearer", "basic", "header", "token", "none"})
VALID_SEARCH_CAPABILITIES = frozenset({"cmr", "cdse_odata", "cds", "none"})
VALID_REGIONS = frozenset({"international", "china"})

# CMR 数据集（collection）检索模板（数据集化改造阶段 2/6：granule 文件级 →
# collection 数据集级，keyword 检索；page_size 由调用方注入）
_CMR_SEARCH_TEMPLATE = (
    "{base}/search/collections.json?keyword={query}&page_size={page_size}"
)
# Copernicus Data Space OData V2 产品检索（公共，无鉴权；2026-08-16 活体探针确认契约：
# 响应 {"value": [{Id, Name, ContentLength, Online, SensingStartDate, ...}]}）。
# 数据集化改造：检索仍按产品，但解析层聚合为「任务_产品级」数据集条目。
_CDSE_ODATA_SEARCH_TEMPLATE = (
    "{base}/odata/v1/Products?$filter=contains(Name,'{query}')&$top={page_size}"
)
# ECMWF 新版 CDS STAC 风格目录（公共；探针确认：/api/catalogue/v1/collections?q=&limit=
# 返回 {"collections": [{id, title, description, ...}]}；collection 即数据集级）
_CDS_SEARCH_TEMPLATE = "{base}/api/catalogue/v1/collections?q={query}&limit={page_size}"

# CDSE 产品内容下载固定走下载域（与目录域不同 host）
_CDSE_DOWNLOAD_ORIGIN = "https://download.dataspace.copernicus.eu"

_SEARCH_TEMPLATES_BY_CAPABILITY: dict[str, str] = {
    "cmr": _CMR_SEARCH_TEMPLATE,
    "cdse_odata": _CDSE_ODATA_SEARCH_TEMPLATE,
    "cds": _CDS_SEARCH_TEMPLATE,
}


class PortalCatalogError(ValueError):
    """目录操作校验失败（portal_id 未知/字段非法）。"""


class PortalSearchUnsupported(PortalCatalogError):
    """该门户不支持在线检索（search_capability=none）。"""


@dataclass(frozen=True)
class PortalDef:
    portal_id: str
    name: str
    base_url: str
    organization: str = ""
    region: str = "international"
    alt_url: str | None = None
    website: str = ""
    description: str = ""
    requires_credentials: bool = False
    auth_type: str = "none"
    token_header: str | None = None
    credential_profile: str = ""  # 凭据键；空 = 自身 portal_id
    credentials_hint: str = ""
    search_capability: str = "none"
    search_url_template: str | None = None
    builtin: bool = True

    def cred_key(self) -> str:
        return self.credential_profile or self.portal_id

    def to_public(self) -> dict[str, Any]:
        return {
            "portal_id": self.portal_id,
            "name": self.name,
            "organization": self.organization,
            "region": self.region,
            "base_url": self.base_url,
            "alt_url": self.alt_url,
            "website": self.website,
            "description": self.description,
            "requires_credentials": self.requires_credentials,
            "auth_type": self.auth_type,
            "token_header": self.token_header,
            "credential_profile": self.cred_key(),
            "credentials_hint": self.credentials_hint,
            "search_capability": self.search_capability,
            "builtin": self.builtin,
        }


_ED = "https://urs.earthdata.nasa.gov/home"

DEFAULT_PORTAL_CATALOG: dict[str, PortalDef] = {
    p.portal_id: p
    for p in (
        # ── 国际组织 ──
        PortalDef(
            portal_id="nasa_earthdata",
            name="NASA Earthdata / LP DAAC 云端对象",
            organization="NASA EOSDIS LP DAAC",
            region="international",
            base_url="https://data.lpdaac.earthdatacloud.nasa.gov/",
            website=_ED,
            description="LP DAAC 云端对象存储（HDF/COG 产品直下）。",
            requires_credentials=True,
            auth_type="bearer",
            credential_profile="earthdata",
            credentials_hint="Earthdata Login（urs.earthdata.nasa.gov）生成 token。",
            search_capability="none",
        ),
        PortalDef(
            portal_id="nasa_cmr",
            name="NASA CMR 元数据检索",
            organization="NASA EOSDIS",
            region="international",
            base_url="https://cmr.earthdata.nasa.gov/",
            website="https://cmr.earthdata.nasa.gov/",
            description="通用元数据仓库（granule/collection 检索，公共只读）。",
            requires_credentials=False,
            auth_type="none",
            credential_profile="earthdata",
            search_capability="cmr",
            search_url_template=_CMR_SEARCH_TEMPLATE,
        ),
        PortalDef(
            portal_id="nasa_ges_disc",
            name="NASA GES DISC 水文数据",
            organization="NASA GES DISC",
            region="international",
            base_url="https://hydro1.gesdisc.eosdis.nasa.gov/",
            website="https://disc.gsfc.nasa.gov/",
            description="GES DISC 水文/大气再分析产品（GPM、MERRA-2 等）。",
            requires_credentials=True,
            auth_type="bearer",
            credential_profile="earthdata",
            credentials_hint="Earthdata Login token（与 Earthdata 同一凭据）。",
        ),
        PortalDef(
            portal_id="nasa_gldas",
            name="NASA GLDAS 全球陆面数据",
            organization="NASA GES DISC",
            region="international",
            base_url="https://hydro1.gesdisc.eosdis.nasa.gov/data/GLDAS/",
            website="https://disc.gsfc.nasa.gov/datasets?keywords=GLDAS",
            description="GLDAS Noah/VIC 陆面同化产品目录。",
            requires_credentials=True,
            auth_type="bearer",
            credential_profile="earthdata",
            credentials_hint="Earthdata Login token（与 Earthdata 同一凭据）。",
        ),
        PortalDef(
            portal_id="nsidc_data",
            name="NSIDC 数据下载",
            organization="NSIDC",
            region="international",
            # 2026-08 迁移：旧 ECS 主机 n5eil01u.ecs.nsidc.org 已被官方云 CDN 取代
            # （且旧主机对部分地区网络 TCP 拒绝）。新结构：
            # /nsidc-cumulus-prod-protected/<PROG>/<VER>/YYYY/MM/<granule>。
            base_url="https://data.nsidc.earthdatacloud.nasa.gov/",
            website="https://nsidc.org/",
            description="NSIDC 极地/冰冻圈产品云 CDN（可回退 Earthdata 凭据）。",
            requires_credentials=True,
            auth_type="bearer",
            credential_profile="nsidc",
            credentials_hint="NSIDC 或 Earthdata token（登录页 earthdata.nasa.gov）。",
        ),
        PortalDef(
            portal_id="noaa_nomads",
            name="NOAA NOMADS 数值产品",
            organization="NOAA NCEP",
            region="international",
            base_url="https://nomads.ncep.noaa.gov/",
            website="https://nomads.ncep.noaa.gov/",
            description="NCEP 数值预报产品开放目录（免凭据）。",
            requires_credentials=False,
            auth_type="none",
        ),
        PortalDef(
            portal_id="noaa_goes",
            name="NOAA GOES 影像 CDN",
            organization="NOAA NESDIS",
            region="international",
            base_url="https://cdn.star.nesdis.noaa.gov/",
            website="https://www.star.nesdis.noaa.gov/",
            description="GOES 卫星影像 CDN（免凭据）。",
            requires_credentials=False,
            auth_type="none",
        ),
        PortalDef(
            portal_id="esa_copernicus",
            name="欧空局 Copernicus 目录",
            organization="ESA Copernicus Data Space",
            region="international",
            base_url="https://catalogue.dataspace.copernicus.eu/",
            website="https://dataspace.copernicus.eu/",
            description="Copernicus Sentinel 产品目录（OData/API）。",
            requires_credentials=True,
            auth_type="bearer",
            credential_profile="copernicus",
            credentials_hint="Copernicus Data Space 控制台生成 Access Token。",
            search_capability="cdse_odata",
            search_url_template=_CDSE_ODATA_SEARCH_TEMPLATE,
        ),
        PortalDef(
            portal_id="esa_download",
            name="欧空局 Copernicus 下载 CDN",
            organization="ESA Copernicus Data Space",
            region="international",
            base_url="https://download.dataspace.copernicus.eu/odata/v1/",
            website="https://dataspace.copernicus.eu/",
            description="Copernicus 产品下载 CDN（凭据同目录）。",
            requires_credentials=True,
            auth_type="bearer",
            credential_profile="copernicus",
            credentials_hint="Copernicus Data Space Access Token（与目录同一凭据）。",
        ),
        PortalDef(
            portal_id="ecmwf_cds",
            name="ECMWF 气候数据存储 CDS",
            organization="ECMWF",
            region="international",
            base_url="https://cds.climate.copernicus.eu/",
            website="https://cds.climate.copernicus.eu/",
            description="ERA5/ORAS5 等再分析产品（新版 CDS API 使用 Bearer key）。",
            requires_credentials=True,
            auth_type="bearer",
            credential_profile="ecmwf_cds",
            credentials_hint="CDS 个人主页 API key（形如 xxxxxx-xxxx-xxxx）。",
            search_capability="cds",
            search_url_template=_CDS_SEARCH_TEMPLATE,
        ),
        PortalDef(
            portal_id="usgs_earthexplorer",
            name="USGS EarthExplorer",
            organization="USGS",
            region="international",
            base_url="https://earthexplorer.usgs.gov/",
            website="https://earthexplorer.usgs.gov/",
            description="Landsat/DEM 等陆地卫星产品门户（账号密码）。",
            requires_credentials=True,
            auth_type="basic",
            credential_profile="usgs_earthexplorer",
            credentials_hint="EarthExplorer 注册账号（用户名 + 密码）。",
        ),
        PortalDef(
            portal_id="jaxa_gportal",
            name="JAXA G-Portal",
            organization="JAXA",
            region="international",
            base_url="https://gportal.jaxa.jp/",
            website="https://gportal.jaxa.jp/",
            description="JAXA 卫星（GPM/AMSR2 等）产品门户（账号密码）。",
            requires_credentials=True,
            auth_type="basic",
            credential_profile="jaxa_gportal",
            credentials_hint="G-Portal 注册账号（用户名 + 密码）。",
        ),
        # ── 国内机构 ──
        PortalDef(
            portal_id="cma_nsmc",
            name="国家卫星气象中心 NSMC 门户",
            organization="国家卫星气象中心（NSMC）",
            region="china",
            base_url="https://satellite.nsmc.org.cn/",
            website="https://satellite.nsmc.org.cn/",
            description="风云卫星产品门户（FY-3/FY-4 各级产品）。",
            requires_credentials=True,
            auth_type="token",
            token_header="token",
            credential_profile="nsmc",
            credentials_hint="NSMC 门户注册后在「个人中心」获取 token。",
        ),
        PortalDef(
            portal_id="cma_data",
            name="国家卫星气象中心数据平台",
            organization="国家卫星气象中心（NSMC）",
            region="china",
            base_url="https://data.nsmc.org.cn/",
            website="https://data.nsmc.org.cn/",
            description="风云卫星数据服务平台（凭据与 NSMC 门户共用）。",
            requires_credentials=True,
            auth_type="token",
            token_header="token",
            credential_profile="nsmc",
            credentials_hint="NSMC 门户 token（与 satellite.nsmc.org.cn 共用）。",
        ),
        PortalDef(
            portal_id="cma_mdc",
            name="国家气象科学数据中心",
            organization="中国气象局",
            region="china",
            base_url="https://data.cma.cn/",
            website="https://data.cma.cn/",
            description="地面/高空/辐射等气象观测数据（data.cma.cn）。",
            requires_credentials=True,
            auth_type="token",
            token_header="token",
            credential_profile="cma_mdc",
            credentials_hint="data.cma.cn 注册账号后生成的接口 token。",
        ),
        PortalDef(
            portal_id="tpdc",
            name="国家青藏高原科学数据中心",
            organization="中科院青藏高原研究所",
            region="china",
            base_url="https://data.tpdc.ac.cn/",
            website="https://data.tpdc.ac.cn/",
            description="青藏高原观测/再分析/冰川冻土数据。",
            requires_credentials=True,
            auth_type="token",
            token_header="token",
            credential_profile="tpdc",
            credentials_hint="TPDC 注册账号的 API token（个人中心申请）。",
        ),
        PortalDef(
            portal_id="geodata_nessdc",
            name="国家地球系统科学数据中心",
            organization="国家地球系统科学数据中心",
            region="china",
            base_url="https://www.geodata.cn/",
            website="https://www.geodata.cn/",
            description="地球系统多学科数据共享（geodata.cn）。",
            requires_credentials=True,
            auth_type="token",
            token_header="token",
            credential_profile="geodata_nessdc",
            credentials_hint="geodata.cn 账号授权后的下载 token。",
        ),
        PortalDef(
            portal_id="resdc",
            name="中科院资源环境科学数据中心",
            organization="中科院地理资源所",
            region="china",
            base_url="https://www.resdc.cn/",
            website="https://www.resdc.cn/",
            description="资源环境时空序列数据（土地利用/植被/人口等）。",
            requires_credentials=True,
            auth_type="token",
            token_header="token",
            credential_profile="resdc",
            credentials_hint="RESDC 注册账号（部分数据需申请授权）。",
        ),
        PortalDef(
            portal_id="noda",
            name="国家对地观测科学数据中心",
            organization="科技部国家遥感中心",
            region="china",
            base_url="https://www.noda.org.cn/",
            website="https://www.noda.org.cn/",
            description="对地观测数据共享（光学/SAR/无人机）。",
            requires_credentials=True,
            auth_type="token",
            token_header="token",
            credential_profile="noda",
            credentials_hint="NODA 注册账号的接口 token。",
        ),
    )
}


# ── KV 存储 ──────────────────────────────────────────────────────────────────

_CUSTOM_PORTALS_KEY = "portal_catalog_custom"
_ALT_URLS_KEY = "portal_alt_urls"


def _repo() -> Any:
    from app.services.config_service import _research_data_repo

    return _research_data_repo()


def _load_custom_raw(repo: Any) -> dict[str, dict[str, Any]]:
    raw = repo.get_json(_CUSTOM_PORTALS_KEY, {})
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _portal_def_from_raw(pid: str, raw: dict[str, Any]) -> PortalDef:
    return PortalDef(
        portal_id=pid,
        name=str(raw.get("name") or pid),
        organization=str(raw.get("organization") or ""),
        region=str(raw.get("region") or "international"),
        base_url=str(raw.get("base_url") or ""),
        alt_url=str(raw["alt_url"]) if raw.get("alt_url") else None,
        website=str(raw.get("website") or ""),
        description=str(raw.get("description") or ""),
        requires_credentials=bool(raw.get("requires_credentials")),
        auth_type=str(raw.get("auth_type") or "none"),
        token_header=str(raw["token_header"]) if raw.get("token_header") else None,
        credential_profile=str(raw.get("credential_profile") or ""),
        credentials_hint=str(raw.get("credentials_hint") or ""),
        search_capability=str(raw.get("search_capability") or "none"),
        search_url_template=(
            str(raw["search_url_template"]) if raw.get("search_url_template") else None
        ),
        builtin=False,
    )


def builtin_portal_catalog() -> dict[str, PortalDef]:
    return dict(DEFAULT_PORTAL_CATALOG)


def custom_portal_catalog(*, repo: Any = None) -> dict[str, PortalDef]:
    r = repo if repo is not None else _repo()
    return {
        pid: _portal_def_from_raw(pid, raw) for pid, raw in _load_custom_raw(r).items()
    }


def list_portal_defs(*, repo: Any = None) -> dict[str, PortalDef]:
    r = repo if repo is not None else _repo()
    defs = builtin_portal_catalog()
    defs.update(custom_portal_catalog(repo=r))
    return defs


def known_portal_ids(*, repo: Any = None) -> set[str]:
    """凭据 upsert 的动态白名单：目录键 ∪ 规范凭据键 ∪ 遗留三键。"""
    r = repo if repo is not None else _repo()
    defs = list_portal_defs(repo=r)
    ids: set[str] = set(defs.keys())
    ids.update(d.cred_key() for d in defs.values())
    # 遗留规范键（PORTAL_IDS 时代已存数据迁移安全）
    ids.update({"earthdata", "nsidc", "copernicus"})
    return ids


def portal_profile_aliases(*, repo: Any = None) -> dict[str, str]:
    """portal_id → credential_profile 别名表（共享凭据族的规范键归一用）。

    前端凭据对话框按 portal_id 保存（如 ``esa_copernicus``/``cdse``），而目录
    状态徽标、凭据回填与 worker 运行时解析都按 credential_profile（如
    ``copernicus``）查询。本表供 ``load_portal_credentials_secret`` 把
    portal_id 键的存储投影到规范键，消除写入/读取键错位。仅含 profile
    非空且不等于自身 portal_id 的条目。
    """
    r = repo if repo is not None else _repo()
    return {
        pid: d.cred_key()
        for pid, d in list_portal_defs(repo=r).items()
        if d.credential_profile and d.credential_profile != pid
    }


def preset_labels_from_catalog(*, repo: Any = None) -> dict[str, str]:
    """目录生成的 preset 标签（供 open_data_preset_labels 合并，键名向后兼容）。"""
    return {pid: d.name for pid, d in list_portal_defs(repo=repo).items()}


def effective_base_urls(*, repo: Any = None) -> dict[str, str]:
    """目录默认 base URL + ``open_data_presets`` 覆盖 + 自定义门户 base_url。"""
    r = repo if repo is not None else _repo()
    defs = list_portal_defs(repo=r)
    out = {pid: d.base_url for pid, d in defs.items()}
    overrides = r.get_json("open_data_presets", {})
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            key = str(k).strip()
            val = str(v or "").strip()
            if key and val:
                out[key] = val
    return out


def alt_url_overrides(*, repo: Any = None) -> dict[str, str]:
    r = repo if repo is not None else _repo()
    raw = r.get_json(_ALT_URLS_KEY, {})
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if str(v or "").strip()}


# ── 凭据状态 ─────────────────────────────────────────────────────────────────


def _runtime_credentials(repo: Any) -> dict[str, dict[str, Any]]:
    from app.core.config import settings

    try:
        loaded = load_portal_credentials_secret(
            repo=repo,
            encryption_key=settings.gee_credentials_encryption_key,
        )
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("portal catalog: load credentials failed: %s", exc)
        return {}


def _entry_has_secret(entry: dict[str, Any]) -> bool:
    return bool(
        str(entry.get("token") or entry.get("access_token") or "").strip()
        or str(entry.get("password") or entry.get("secret") or "").strip()
        or _entry_account_count(entry) > 0
    )


def _entry_account_count(entry: dict[str, Any]) -> int:
    accounts = entry.get("accounts")
    return len(accounts) if isinstance(accounts, list) else 0


def _credential_status(
    defn: PortalDef, creds: dict[str, dict[str, Any]]
) -> tuple[bool, str, int]:
    """返回 (has_credentials, credential_source, account_count)。"""
    entry = creds.get(defn.cred_key())
    if not isinstance(entry, dict) or entry.get("enabled") is False:
        return False, "none", 0
    if not _entry_has_secret(entry):
        return False, str(entry.get("source") or "none"), 0
    return True, str(entry.get("source") or "db"), _entry_account_count(entry)


# ── 目录载荷（API 投影） ──────────────────────────────────────────────────────


def get_portal_catalog() -> list[dict[str, Any]]:
    repo = _repo()
    defs = list_portal_defs(repo=repo)
    bases = effective_base_urls(repo=repo)
    alts = alt_url_overrides(repo=repo)
    presets = repo.get_json("open_data_presets", {})
    presets = presets if isinstance(presets, dict) else {}
    creds = _runtime_credentials(repo)

    entries: list[dict[str, Any]] = []
    for pid, defn in defs.items():
        entry = defn.to_public()
        overridden = bool(str(presets.get(pid) or "").strip())
        entry["effective_base_url"] = bases.get(pid) or defn.base_url
        entry["base_url_overridden"] = overridden
        alt_override = alts.get(pid)
        entry["effective_alt_url"] = alt_override or defn.alt_url
        has_creds, cred_source, account_count = _credential_status(defn, creds)
        entry["has_credentials"] = has_creds
        entry["credential_source"] = cred_source
        entry["account_count"] = account_count
        entries.append(entry)
    entries.sort(
        key=lambda e: (0 if e["region"] == "international" else 1, e["portal_id"])
    )
    return entries


# ── 目录写操作 ────────────────────────────────────────────────────────────────


def normalize_portal_id(raw: str) -> str:
    pid = str(raw or "").strip().lower()
    if not _PORTAL_ID_RE.match(pid):
        raise PortalCatalogError(
            f"Invalid portal_id: {raw!r} (expected [a-z0-9][a-z0-9_-]{{2,63}})"
        )
    return pid


def _validated_url(raw: str) -> str:
    try:
        return validate_url_for_storage(raw)
    except ValueError as exc:
        raise PortalCatalogError(str(exc)) from exc


def upsert_portal(portal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """创建/更新自定义门户，或覆盖内置门户 URL。

    - builtin 门户：仅允许覆盖 base_url（写 ``open_data_presets``）与 alt_url；
      传空字符串清除对应覆盖。
    - 自定义门户：全字段创建/更新，base_url 必填且过存储校验。
    """
    pid = normalize_portal_id(portal_id)
    repo = _repo()

    if pid in DEFAULT_PORTAL_CATALOG:
        base_override = str(payload.get("base_url") or "").strip()
        if base_override:
            _validated_url(base_override)
            presets = repo.get_json("open_data_presets", {})
            if not isinstance(presets, dict):
                presets = {}
            presets[pid] = base_override
            repo.set_json("open_data_presets", presets)
        else:
            presets = repo.get_json("open_data_presets", {})
            if isinstance(presets, dict) and pid in presets:
                presets.pop(pid, None)
                repo.set_json("open_data_presets", presets)

        alt_override = str(payload.get("alt_url") or "").strip()
        alts = repo.get_json(_ALT_URLS_KEY, {})
        if not isinstance(alts, dict):
            alts = {}
        if alt_override:
            _validated_url(alt_override)
            alts[pid] = alt_override
            repo.set_json(_ALT_URLS_KEY, alts)
        elif pid in alts:
            alts.pop(pid, None)
            repo.set_json(_ALT_URLS_KEY, alts)

        defs = list_portal_defs(repo=repo)
        entry = defs[pid].to_public()
        entry["effective_base_url"] = effective_base_urls(repo=repo).get(pid)
        entry["base_url_overridden"] = bool(
            str((repo.get_json("open_data_presets", {}) or {}).get(pid) or "").strip()
        )
        return entry

    name = str(payload.get("name") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()
    if not name:
        raise PortalCatalogError("Custom portal requires 'name'")
    if not base_url:
        raise PortalCatalogError("Custom portal requires 'base_url'")
    _validated_url(base_url)

    auth_type = str(payload.get("auth_type") or "none").strip().lower()
    if auth_type not in VALID_AUTH_TYPES:
        raise PortalCatalogError(
            f"Invalid auth_type: {auth_type}; expected one of {sorted(VALID_AUTH_TYPES)}"
        )
    region = str(payload.get("region") or "international").strip().lower()
    if region not in VALID_REGIONS:
        raise PortalCatalogError(
            f"Invalid region: {region}; expected one of {sorted(VALID_REGIONS)}"
        )
    search_capability = str(payload.get("search_capability") or "none").strip().lower()
    if search_capability not in VALID_SEARCH_CAPABILITIES:
        raise PortalCatalogError(
            "Invalid search_capability: "
            f"{search_capability}; expected one of {sorted(VALID_SEARCH_CAPABILITIES)}"
        )
    alt_url = str(payload.get("alt_url") or "").strip()
    if alt_url:
        _validated_url(alt_url)

    custom = _load_custom_raw(repo)
    prev = custom.get(pid, {})
    record: dict[str, Any] = {
        "name": name,
        "organization": str(
            payload.get("organization") or prev.get("organization") or ""
        ),
        "region": region,
        "base_url": base_url,
        "alt_url": alt_url or None,
        "website": str(payload.get("website") or prev.get("website") or ""),
        "description": str(payload.get("description") or prev.get("description") or ""),
        "requires_credentials": bool(
            payload.get("requires_credentials", prev.get("requires_credentials", False))
        ),
        "auth_type": auth_type,
        "token_header": str(
            payload.get("token_header") or prev.get("token_header") or ""
        )
        or None,
        "credential_profile": str(
            payload.get("credential_profile") or prev.get("credential_profile") or ""
        ),
        "credentials_hint": str(
            payload.get("credentials_hint") or prev.get("credentials_hint") or ""
        ),
        "search_capability": search_capability,
        "search_url_template": _SEARCH_TEMPLATES_BY_CAPABILITY.get(search_capability),
    }
    custom[pid] = record
    repo.set_json(_CUSTOM_PORTALS_KEY, custom)

    defn = _portal_def_from_raw(pid, record)
    entry = defn.to_public()
    entry["effective_base_url"] = base_url
    entry["base_url_overridden"] = False
    has_creds, cred_source, account_count = _credential_status(
        defn, _runtime_credentials(repo)
    )
    entry["has_credentials"] = has_creds
    entry["credential_source"] = cred_source
    entry["account_count"] = account_count
    return entry


def delete_portal(portal_id: str) -> bool:
    """仅自定义门户可删除（连带清除其 URL 覆盖与凭据）。"""
    pid = normalize_portal_id(portal_id)
    if pid in DEFAULT_PORTAL_CATALOG:
        raise PortalCatalogError(
            f"Built-in portal '{pid}' cannot be deleted; clear URL overrides instead"
        )
    repo = _repo()
    custom = _load_custom_raw(repo)
    if pid not in custom:
        return False
    del custom[pid]
    repo.set_json(_CUSTOM_PORTALS_KEY, custom)

    presets = repo.get_json("open_data_presets", {})
    if isinstance(presets, dict) and pid in presets:
        presets.pop(pid, None)
        repo.set_json("open_data_presets", presets)
    alts = repo.get_json(_ALT_URLS_KEY, {})
    if isinstance(alts, dict) and pid in alts:
        alts.pop(pid, None)
        repo.set_json(_ALT_URLS_KEY, alts)
    return True


# ── 连通性测试 ────────────────────────────────────────────────────────────────


def _auth_headers_for_portal(
    defn: PortalDef, creds: dict[str, dict[str, Any]]
) -> dict[str, str]:
    entry = creds.get(defn.cred_key())
    if not isinstance(entry, dict) or entry.get("enabled") is False:
        return {}
    token = str(entry.get("token") or entry.get("access_token") or "").strip()
    password = str(entry.get("password") or entry.get("secret") or "").strip()
    username = str(entry.get("username") or "").strip()
    auth_type = str(entry.get("auth_type") or defn.auth_type or "none").lower()
    token_header = str(entry.get("token_header") or defn.token_header or "").strip()

    if auth_type == "bearer" and token:
        return {"Authorization": f"Bearer {token}"}
    if auth_type == "basic" and username and password:
        import base64

        cred = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
            "ascii"
        )
        return {"Authorization": f"Basic {cred}"}
    if auth_type in {"header", "token"} and token:
        header = token_header or ("Authorization" if auth_type == "header" else "token")
        return {header: token}
    return {}


def _test_url_for(defn: PortalDef, base: str) -> str:
    if defn.search_capability == "cmr":
        # 数据集化改造（阶段 2/6）：连通性探针同步换 collections 端点
        return f"{base.rstrip('/')}/search/collections.json?page_size=1"
    if defn.search_capability == "cdse_odata":
        return f"{base.rstrip('/')}/odata/v1/Products?$top=1"
    if defn.search_capability == "cds":
        return f"{base.rstrip('/')}/api/catalogue/v1/collections?limit=1"
    return base


def test_portal(portal_id: str) -> dict[str, Any]:
    """门户连通性测试（带凭据构造请求头；全程过 SSRF 校验）。"""
    import http.client
    from urllib.error import HTTPError, URLError

    from app.core.ssrf import SSRFBlockedError

    pid = normalize_portal_id(portal_id)
    repo = _repo()
    defs = list_portal_defs(repo=repo)
    defn = defs.get(pid)
    if defn is None:
        raise PortalCatalogError(f"Unknown portal: {pid}")
    base = effective_base_urls(repo=repo).get(pid) or defn.base_url
    url = _test_url_for(defn, base)
    creds = _runtime_credentials(repo)
    headers = _auth_headers_for_portal(defn, creds)
    via_credentials = bool(headers)

    try:
        with safe_urlopen(url, timeout=12.0, headers=headers or None) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            return {
                "portal_id": pid,
                "ok": 200 <= status < 400,
                "status_code": status,
                "via_credentials": via_credentials,
                "message": f"HTTP {status}",
                "tested_url": url,
            }
    except HTTPError as exc:
        code = int(exc.code)
        hint = ""
        if code in {401, 403} and defn.requires_credentials:
            hint = (
                "（未配置凭据或凭据无效）"
                if not via_credentials
                else "（凭据可能无效）"
            )
        return {
            "portal_id": pid,
            "ok": False,
            "status_code": code,
            "via_credentials": via_credentials,
            "message": f"HTTP {code}{hint}",
            "tested_url": url,
        }
    except (URLError, SSRFBlockedError, http.client.HTTPException, OSError) as exc:
        return {
            "portal_id": pid,
            "ok": False,
            "status_code": None,
            "via_credentials": via_credentials,
            "message": str(exc),
            "tested_url": url,
        }


# ── 在线检索（数据集级 provider，plan §2） ──────────────────────────────────


def _parse_cmr_collection_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """CMR collection（数据集级）→ 统一数据集条目（plan §2）。

    真实 collections.json 契约（2026-08-21 活体探针确认）：
    entry_id="GLDAS_NOAH025_3H_2.1"（短名_版本）、dataset_id=完整标题、
    version_id、time_start/end、data_center、summary。dataset_key 取
    entry_id 去掉 "_{version_id}" 后缀；缺失字段防御性回退。
    """
    title = str(entry.get("dataset_id") or entry.get("entry_title") or "").strip()
    version = str(entry.get("version_id") or "").strip()
    entry_id = str(entry.get("entry_id") or entry.get("short_name") or "").strip()
    dataset_key = entry_id
    if version and dataset_key.endswith(f"_{version}"):
        dataset_key = dataset_key[: -len(version) - 1]
    if not dataset_key:
        dataset_key = re.sub(r"\s+", "_", title)
    return {
        "dataset_key": dataset_key,
        "title": title,
        "description": str(entry.get("summary") or "").strip(),
        "time_start": str(entry.get("time_start") or ""),
        "time_end": str(entry.get("time_end") or ""),
        "provider_kind": "cmr",
        "extra": {
            "collection_id": str(entry.get("id") or entry_id),
            "version": version,
            "data_center": str(entry.get("data_center") or ""),
        },
    }


_CDSE_LEVEL_SEGMENT_RE = re.compile(r"^\d[A-Z]{0,3}$")
_CDSE_TIMESTAMP_SEGMENT_RE = re.compile(r"^\d{8}T")


def _cdse_dataset_pattern(name: str) -> str:
    """CDSE 产品名 → 「任务_产品级」模式（数据集标识）。

    按级别段（形如 1SDV/1SDH）截断并去掉时间戳段，最多取 3 段：
    - S1A_IW_GRDH_1SDV_20150412T… → S1A_IW_GRDH
    - S2A_MSIL1C_20240101T…       → S2A_MSIL1C
    """
    parts = [p for p in str(name or "").strip().split("_") if p]
    if not parts:
        return ""
    for i, seg in enumerate(parts):
        if i > 0 and _CDSE_LEVEL_SEGMENT_RE.match(seg):
            parts = parts[:i]
            break
    parts = [p for p in parts if not _CDSE_TIMESTAMP_SEGMENT_RE.match(p)]
    return "_".join(parts[:3]) if len(parts) > 3 else "_".join(parts)


def _aggregate_cdse_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """CDSE 产品级条目聚合为数据集级（数据集化改造阶段 2/6）。

    按产品名前两段（任务_产品级）分组，每组一条数据集条目；
    extra 携带产品数与示例产品 ID，产品级细节不再直接暴露。
    """
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for product in products:
        name = str(product.get("title") or "")
        pattern = _cdse_dataset_pattern(name)
        if not pattern:
            continue
        if pattern not in groups:
            order.append(pattern)
            groups[pattern] = {
                "dataset_key": pattern,
                "title": pattern,
                "description": f"Copernicus Data Space 产品集 {pattern}",
                "time_start": str(product.get("time_start") or ""),
                "time_end": str(product.get("time_end") or ""),
                "provider_kind": "cdse_odata",
                "extra": {"count": 0, "sample_product_id": "", "sample_link": ""},
            }
        g = groups[pattern]
        g["extra"]["count"] += 1
        if not g["extra"]["sample_product_id"]:
            g["extra"]["sample_product_id"] = str(product.get("granule_id") or "")
            g["extra"]["sample_link"] = str(product.get("data_link") or "")
        if not g["time_start"] and product.get("time_start"):
            g["time_start"] = str(product["time_start"])
    return [groups[k] for k in order]


def _parse_cdse_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """CDSE 产品级解析（供聚合步骤消费，不再直接作为检索结果）。"""
    try:
        size_bytes = int(float(entry.get("ContentLength") or 0))
    except (TypeError, ValueError):
        size_bytes = 0
    product_id = str(entry.get("Id") or "")
    data_link = (
        f"{_CDSE_DOWNLOAD_ORIGIN}/odata/v1/Products({product_id})/$value"
        if product_id
        else ""
    )
    return {
        "title": str(entry.get("Name") or ""),
        "granule_id": product_id,
        "producer_granule_id": "",
        "size_bytes": size_bytes,
        "time_start": str(entry.get("SensingStartDate") or ""),
        "time_end": str(entry.get("SensingEndDate") or ""),
        "data_link": data_link,
        "browse_link": "",
        "online": bool(entry.get("Online")),
    }


def _parse_cds_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """CDS collection（数据集级）→ 统一数据集条目（字段重排，阶段 2/6）。"""
    dataset_id = str(entry.get("id") or "")
    return {
        "dataset_key": dataset_id,
        "title": str(entry.get("title") or dataset_id),
        "description": str(entry.get("description") or "").strip(),
        "time_start": str(
            entry.get("extent", {}).get("temporal", {}).get("interval", [[""]])[0][0]
            if isinstance(entry.get("extent"), dict)
            else ""
        ),
        "time_end": "",
        "provider_kind": "cds",
        "extra": {
            # CDS 数据集页；实际取数须经 cdsapi（download/cds_download 节点）
            "data_link": (
                f"https://cds.climate.copernicus.eu/datasets/{dataset_id}"
                if dataset_id
                else ""
            ),
        },
    }


_SEARCH_ITEM_EXTRACTORS: dict[str, str] = {
    # capability -> payload 内条目数组的取值键
    "cmr": "feed.entry",
    "cdse_odata": "value",
    "cds": "collections",
}

_SEARCH_ITEM_PARSERS: dict[str, Any] = {
    "cmr": _parse_cmr_collection_entry,
    "cdse_odata": _parse_cdse_entry,
    "cds": _parse_cds_entry,
}


def _extract_search_items(capability: str, payload: Any) -> list[dict[str, Any]]:
    """按 capability 从检索响应中提取条目数组（CMR 兼容单条对象形态）。"""
    if not isinstance(payload, dict):
        return []
    if capability == "cmr":
        feed = payload.get("feed")
        entries = feed.get("entry") if isinstance(feed, dict) else None
        if entries is None:
            entries = []
        if isinstance(entries, dict):  # 单条结果时 CMR 返回对象而非数组
            entries = [entries]
        return [e for e in entries if isinstance(e, dict)]
    node: Any = payload
    for key in _SEARCH_ITEM_EXTRACTORS[capability].split("."):
        node = node.get(key) if isinstance(node, dict) else None
        if node is None:
            return []
    if not isinstance(node, list):
        return []
    return [e for e in node if isinstance(e, dict)]


def search_portal(
    portal_id: str,
    *,
    query: str,
    page_size: int = 20,
) -> dict[str, Any]:
    """门户在线检索：按 search_capability 分发 provider（cmr/cdse_odata/cds）。"""
    from urllib.error import HTTPError, URLError

    from app.core.ssrf import SSRFBlockedError

    pid = normalize_portal_id(portal_id)
    repo = _repo()
    defs = list_portal_defs(repo=repo)
    defn = defs.get(pid)
    if defn is None:
        raise PortalCatalogError(f"Unknown portal: {pid}")
    capability = defn.search_capability
    if capability not in _SEARCH_ITEM_PARSERS or not defn.search_url_template:
        raise PortalSearchUnsupported(
            f"Portal '{pid}' does not support online search (search_capability="
            f"{defn.search_capability})"
        )

    q = str(query or "").strip()
    if not q:
        raise PortalCatalogError("Search query must not be empty")
    size = max(1, min(int(page_size or 20), 100))

    base = effective_base_urls(repo=repo).get(pid) or defn.base_url
    url = defn.search_url_template.format(
        base=base.rstrip("/"), query=quote_plus(q), page_size=size
    )
    headers = {"Accept": "application/json"}
    # 公共只读检索（requires_credentials=False，如 CMR）不携带凭据：
    # CMR 对携带的 Authorization 头会做校验，无效 Basic 凭据会把本来
    # 公共可用的检索直接打成 401。cdse_odata / cds 检索端点亦为公共只读，
    # 同样不携带凭据（凭据仅在下载链使用）。
    if capability == "cmr" and defn.requires_credentials:
        creds = _runtime_credentials(repo)
        headers.update(_auth_headers_for_portal(defn, creds))

    try:
        with safe_urlopen(url, timeout=20.0, headers=headers) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise PortalCatalogError(f"Portal search failed: HTTP {exc.code}") from exc
    except (URLError, SSRFBlockedError, OSError) as exc:
        raise PortalCatalogError(f"Portal search failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PortalCatalogError("Portal search returned non-JSON payload") from exc

    entries = _extract_search_items(capability, payload)
    parser = _SEARCH_ITEM_PARSERS[capability]
    items = [parser(e) for e in entries]
    # 数据集化改造（阶段 2/6）：CDSE 产品级条目聚合为「任务_产品级」数据集
    if capability == "cdse_odata":
        items = _aggregate_cdse_products(items)
    return {
        "portal_id": pid,
        "query": q,
        "page_size": size,
        "count": len(items),
        "items": items,
    }
