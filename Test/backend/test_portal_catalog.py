"""Phase B：开放门户目录 / 动态凭据 / test & search 端点。"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_PROVIDER = _REPO_ROOT / "Code" / "algorithms" / "providers" / "Python"
for _p in (_PYTHON_PROVIDER, _REPO_ROOT / "Code"):
    _s = str(_p)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)


@contextmanager
def _temp_repo():
    from app.services.research_data_settings_repository import (
        ResearchDataSettingsRepository,
    )

    with tempfile.TemporaryDirectory() as tmp:
        repo = ResearchDataSettingsRepository(Path(tmp) / "settings.sqlite3")
        try:
            yield repo
        finally:
            repo.close()


@pytest.fixture()
def repo_env(monkeypatch):
    """portal_catalog._repo() 指向临时 KV 仓库。"""
    from app.services import portal_catalog

    with _temp_repo() as repo:
        monkeypatch.setattr(portal_catalog, "_repo", lambda: repo)
        yield repo


# ── 目录完整性 ───────────────────────────────────────────────────────────────


def test_catalog_builtin_entries_and_regions() -> None:
    from app.services.portal_catalog import (
        DEFAULT_PORTAL_CATALOG,
        VALID_AUTH_TYPES,
        VALID_REGIONS,
    )

    assert len(DEFAULT_PORTAL_CATALOG) >= 19
    regions: set[str] = set()
    for pid, defn in DEFAULT_PORTAL_CATALOG.items():
        assert defn.builtin is True
        assert defn.base_url.startswith(("http://", "https://"))
        assert defn.auth_type in VALID_AUTH_TYPES
        assert defn.region in VALID_REGIONS
        regions.add(defn.region)
    assert regions == {"international", "china"}


def test_catalog_credential_key_mapping() -> None:
    from app.services.portal_catalog import DEFAULT_PORTAL_CATALOG as cat

    assert cat["nasa_earthdata"].cred_key() == "earthdata"
    assert cat["nasa_cmr"].cred_key() == "earthdata"
    assert cat["cma_data"].cred_key() == "nsmc"
    assert cat["esa_download"].cred_key() == "copernicus"
    # 自持凭据门户：cred_key = 自身
    assert cat["ecmwf_cds"].cred_key() == "ecmwf_cds"
    assert cat["tpdc"].cred_key() == "tpdc"


def test_catalog_cmr_search_capability_only_cmr() -> None:
    from app.services.portal_catalog import DEFAULT_PORTAL_CATALOG as cat

    assert cat["nasa_cmr"].search_capability == "cmr"
    assert cat["nasa_cmr"].search_url_template is not None
    cmr_count = sum(
        1 for d in cat.values() if d.search_capability == "cmr"
    )
    assert 1 <= cmr_count <= 3


# ── known ids / 白名单 ────────────────────────────────────────────────────────


def test_known_portal_ids_includes_catalog_and_legacy(repo_env) -> None:
    from app.services.portal_catalog import known_portal_ids, upsert_portal

    ids = known_portal_ids(repo=repo_env)
    # 目录键
    assert "nasa_earthdata" in ids
    assert "ecmwf_cds" in ids
    assert "tpdc" in ids
    # 规范凭据键（非 portal_id 的 cred_key）
    assert "earthdata" in ids
    assert "nsmc" in ids
    # 遗留三键
    assert {"nsidc", "copernicus"} <= ids

    upsert_portal(
        "my_lab_portal",
        {"name": "实验室门户", "base_url": "https://lab.example.org/"},
    )
    assert "my_lab_portal" in known_portal_ids(repo=repo_env)


def test_portal_credential_upsert_accepts_new_portal_ids(repo_env) -> None:
    from app.services.portal_credentials import upsert_portal_credential

    for pid in ("ecmwf_cds", "nsmc", "tpdc"):
        public = upsert_portal_credential(
            repo=repo_env,
            encryption_key="",
            portal_id=pid,
            payload={"enabled": True, "auth_type": "bearer", "token": "tok-1"},
        )
        assert pid in public

    with pytest.raises(ValueError, match="Unknown portal_id"):
        upsert_portal_credential(
            repo=repo_env,
            encryption_key="",
            portal_id="definitely_not_a_portal",
            payload={"token": "x"},
        )


# ── 自定义门户 CRUD ──────────────────────────────────────────────────────────


def test_upsert_custom_portal_roundtrip(repo_env) -> None:
    from app.services.portal_catalog import (
        PortalCatalogError,
        list_portal_defs,
        upsert_portal,
    )

    entry = upsert_portal(
        "my_lab_portal",
        {
            "name": "实验室数据门户",
            "organization": "Lab",
            "region": "china",
            "base_url": "https://lab.example.org/",
            "auth_type": "token",
            "token_header": "X-API-Key",
            "requires_credentials": True,
        },
    )
    assert entry["builtin"] is False
    assert entry["credential_profile"] == "my_lab_portal"

    defs = list_portal_defs(repo=repo_env)
    assert "my_lab_portal" in defs
    defn = defs["my_lab_portal"]
    assert defn.base_url == "https://lab.example.org/"
    assert defn.auth_type == "token"

    with pytest.raises(PortalCatalogError):
        upsert_portal("bad id!", {"name": "x", "base_url": "https://a.b/"})
    with pytest.raises(PortalCatalogError):
        upsert_portal("no_base_url", {"name": "x", "base_url": ""})
    with pytest.raises(PortalCatalogError):
        upsert_portal(
            "bad_scheme",
            {"name": "x", "base_url": "file:///etc/passwd"},
        )
    with pytest.raises(PortalCatalogError):
        upsert_portal(
            "bad_auth",
            {"name": "x", "base_url": "https://a.b/", "auth_type": "digest"},
        )


def test_builtin_portal_url_override_via_presets(repo_env) -> None:
    from app.services.portal_catalog import (
        effective_base_urls,
        upsert_portal,
    )

    # builtin：base_url 覆盖写 open_data_presets
    entry = upsert_portal(
        "noaa_nomads", {"base_url": "https://mirror.example.gov/"}
    )
    assert entry["base_url_overridden"] is True
    assert entry["effective_base_url"] == "https://mirror.example.gov/"
    assert (
        effective_base_urls(repo=repo_env)["noaa_nomads"]
        == "https://mirror.example.gov/"
    )

    # 空串清除覆盖 → 回到目录默认
    entry = upsert_portal("noaa_nomads", {"base_url": ""})
    assert entry["base_url_overridden"] is False
    assert (
        effective_base_urls(repo=repo_env)["noaa_nomads"]
        == "https://nomads.ncep.noaa.gov/"
    )


def test_delete_portal_custom_only(repo_env) -> None:
    from app.services.portal_catalog import (
        PortalCatalogError,
        delete_portal,
        upsert_portal,
    )

    with pytest.raises(PortalCatalogError, match="cannot be deleted"):
        delete_portal("nasa_earthdata")

    upsert_portal(
        "tmp_portal", {"name": "t", "base_url": "https://t.example.org/"}
    )
    assert delete_portal("tmp_portal") is True
    assert delete_portal("tmp_portal") is False


def test_get_portal_catalog_entry_projection(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog
    from app.services.portal_catalog import get_portal_catalog, upsert_portal

    monkeypatch.setattr(
        portal_catalog,
        "load_portal_credentials_secret",
        lambda **_kw: {
            "earthdata": {
                "enabled": True,
                "auth_type": "bearer",
                "token": "tok",
                "source": "db",
            }
        },
    )

    entries = get_portal_catalog()
    by_id = {e["portal_id"]: e for e in entries}
    assert "nasa_earthdata" in by_id
    assert by_id["nasa_earthdata"]["has_credentials"] is True
    assert by_id["nasa_earthdata"]["credential_source"] == "db"
    # 无凭据门户（noaa_nomads）不误报
    assert by_id["noaa_nomads"]["has_credentials"] is False

    upsert_portal(
        "noaa_nomads", {"base_url": "https://mirror.example.gov/"}
    )
    entries = get_portal_catalog()
    by_id = {e["portal_id"]: e for e in entries}
    assert by_id["noaa_nomads"]["base_url_overridden"] is True


# ── 连通性测试 ────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self._buf = io.BytesIO(b"{}")

    def read(self) -> bytes:
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_test_portal_success_and_http_error(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog

    calls: list[dict] = []

    def fake_urlopen(url, **kw):
        calls.append({"url": url, "headers": kw.get("headers")})
        return _FakeResponse(200)

    monkeypatch.setattr(portal_catalog, "safe_urlopen", fake_urlopen)
    result = portal_catalog.test_portal("noaa_nomads")
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["via_credentials"] is False
    assert calls[0]["url"].startswith("https://nomads.ncep.noaa.gov/")

    def raise_401(url, **kw):
        raise HTTPError(url, 401, "Unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr(portal_catalog, "safe_urlopen", raise_401)
    result = portal_catalog.test_portal("nasa_earthdata")
    assert result["ok"] is False
    assert result["status_code"] == 401

    with pytest.raises(portal_catalog.PortalCatalogError):
        portal_catalog.test_portal("unknown_portal")


def test_test_portal_injects_credentials(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog

    monkeypatch.setattr(
        portal_catalog,
        "load_portal_credentials_secret",
        lambda **_kw: {
            "earthdata": {
                "enabled": True,
                "auth_type": "bearer",
                "token": "tok-abc",
                "source": "db",
            }
        },
    )
    seen: dict = {}

    def fake_urlopen(url, **kw):
        seen["headers"] = kw.get("headers")
        return _FakeResponse(200)

    monkeypatch.setattr(portal_catalog, "safe_urlopen", fake_urlopen)
    result = portal_catalog.test_portal("nasa_earthdata")
    assert result["via_credentials"] is True
    assert seen["headers"]["Authorization"] == "Bearer tok-abc"


def test_test_portal_cmr_uses_search_endpoint(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog

    def fake_urlopen(url, **kw):
        assert "search/granules.json" in url
        return _FakeResponse(200)

    monkeypatch.setattr(portal_catalog, "safe_urlopen", fake_urlopen)
    result = portal_catalog.test_portal("nasa_cmr")
    assert result["ok"] is True
    assert "granules.json" in result["tested_url"]


# ── CMR 检索 ─────────────────────────────────────────────────────────────────


def _cmr_payload() -> dict:
    return {
        "feed": {
            "entry": [
                {
                    "title": "MOD09GQ.A2025001.h23v03.061",
                    "id": "G123-LPDAAC-abc",
                    "producer_granule_id": "MOD09GQ.A2025001.h23v03.061.hdf",
                    "granule_size": "2.5",
                    "time_start": "2025-01-01T00:00:00Z",
                    "time_end": "2025-01-01T23:59:59Z",
                    "links": [
                        {
                            "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                            "href": "https://data.lpdaac.earthdatacloud.nasa.gov/MOD09GQ.hdf",
                        },
                        {
                            "rel": "http://esipfed.org/ns/fedsearch/1.1/browse#",
                            "href": "https://browse.example.org/1.jpg",
                        },
                    ],
                }
            ]
        }
    }


def test_search_portal_cmr_parsing(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog

    payload = _cmr_payload()

    class _JsonResponse(_FakeResponse):
        def __init__(self) -> None:
            super().__init__(200)
            self._buf = io.BytesIO(
                json.dumps(payload).encode("utf-8")
            )

    monkeypatch.setattr(
        portal_catalog, "safe_urlopen", lambda url, **kw: _JsonResponse()
    )
    result = portal_catalog.search_portal("nasa_cmr", query="MOD09GQ", page_size=5)
    assert result["count"] == 1
    item = result["items"][0]
    assert item["title"].startswith("MOD09GQ")
    assert item["size_bytes"] == 2
    assert item["data_link"].endswith("MOD09GQ.hdf")
    assert item["browse_link"].endswith("1.jpg")


def test_search_portal_single_entry_dict(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog

    payload = {"feed": {"entry": _cmr_payload()["feed"]["entry"][0]}}

    class _JsonResponse(_FakeResponse):
        def __init__(self) -> None:
            super().__init__(200)
            self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(
        portal_catalog, "safe_urlopen", lambda url, **kw: _JsonResponse()
    )
    result = portal_catalog.search_portal("nasa_cmr", query="MOD09GQ")
    assert result["count"] == 1


def test_search_portal_public_portal_skips_credentials(repo_env, monkeypatch) -> None:
    """CMR 公共检索不应携带凭据：无效 Basic 头会把公共检索打成 401。"""
    from app.services import portal_catalog

    monkeypatch.setattr(
        portal_catalog,
        "load_portal_credentials_secret",
        lambda **_kw: {
            "earthdata": {
                "enabled": True,
                "auth_type": "basic",
                "username": "user",
                "password": "bad-pass",
                "source": "db",
            }
        },
    )
    seen: dict = {}

    class _JsonResponse(_FakeResponse):
        def __init__(self) -> None:
            super().__init__(200)
            self._buf = io.BytesIO(json.dumps(_cmr_payload()).encode("utf-8"))

    def fake_urlopen(url, **kw):
        seen["headers"] = kw.get("headers")
        return _JsonResponse()

    monkeypatch.setattr(portal_catalog, "safe_urlopen", fake_urlopen)
    result = portal_catalog.search_portal("nasa_cmr", query="MOD09GQ")
    assert result["count"] == 1
    assert "Authorization" not in (seen["headers"] or {})


def test_search_portal_unsupported_and_empty_query(repo_env) -> None:
    from app.services.portal_catalog import (
        PortalCatalogError,
        PortalSearchUnsupported,
        search_portal,
    )

    with pytest.raises(PortalSearchUnsupported):
        search_portal("noaa_nomads", query="anything")
    with pytest.raises(PortalSearchUnsupported):
        search_portal("tpdc", query="anything")
    with pytest.raises(PortalCatalogError, match="query"):
        search_portal("nasa_cmr", query="  ")


# ── CDSE OData / CDS 目录检索（P1 扩展 provider） ─────────────────────────────


def _cdse_payload() -> dict:
    return {
        "value": [
            {
                "Id": "427be276-cf42-419e-9dd3-c6544a2f4d46",
                "Name": "S1A_IW_GRDH_1SDV_20150412T174535.SAFE",
                "ContentLength": 1004000225,
                "Online": True,
                "SensingStartDate": "2015-04-12T17:45:35Z",
                "SensingEndDate": "2015-04-12T17:46:00Z",
            }
        ]
    }


def _cds_payload() -> dict:
    return {
        "collections": [
            {
                "id": "reanalysis-era5-single-levels",
                "title": "ERA5 hourly data on single levels from 1940 to present",
                "type": "Collection",
            }
        ]
    }


def test_catalog_new_search_capabilities_declared() -> None:
    from app.services.portal_catalog import DEFAULT_PORTAL_CATALOG as cat

    assert cat["esa_copernicus"].search_capability == "cdse_odata"
    assert cat["esa_copernicus"].search_url_template is not None
    assert cat["ecmwf_cds"].search_capability == "cds"
    assert cat["ecmwf_cds"].search_url_template is not None


def _json_response(payload: dict):
    class _JsonResponse(_FakeResponse):
        def __init__(self) -> None:
            super().__init__(200)
            self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    return _JsonResponse()


def test_search_portal_cdse_odata_parsing(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog

    seen: dict = {}
    monkeypatch.setattr(
        portal_catalog,
        "load_portal_credentials_secret",
        lambda **_kw: {
            "copernicus": {
                "enabled": True,
                "auth_type": "bearer",
                "token": "tok-cdse",
                "source": "db",
            }
        },
    )

    def fake_urlopen(url, **kw):
        seen["url"] = url
        seen["headers"] = kw.get("headers")
        return _json_response(_cdse_payload())

    monkeypatch.setattr(portal_catalog, "safe_urlopen", fake_urlopen)
    result = portal_catalog.search_portal(
        "esa_copernicus", query="S1A_IW_GRDH_1SDV", page_size=5
    )
    assert result["count"] == 1
    item = result["items"][0]
    assert item["title"].startswith("S1A_IW_GRDH")
    assert item["granule_id"] == "427be276-cf42-419e-9dd3-c6544a2f4d46"
    assert item["size_bytes"] == 1004000225
    assert item["online"] is True
    assert item["data_link"] == (
        "https://download.dataspace.copernicus.eu/odata/v1/Products"
        "(427be276-cf42-419e-9dd3-c6544a2f4d46)/$value"
    )
    # OData 检索为公共端点：即使门户配置了凭据也不携带
    assert "Authorization" not in (seen["headers"] or {})
    assert "odata/v1/Products" in seen["url"]


def test_search_portal_cds_parsing(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog

    seen: dict = {}

    def fake_urlopen(url, **kw):
        seen["url"] = url
        return _json_response(_cds_payload())

    monkeypatch.setattr(portal_catalog, "safe_urlopen", fake_urlopen)
    result = portal_catalog.search_portal("ecmwf_cds", query="ERA5", page_size=3)
    assert result["count"] == 1
    item = result["items"][0]
    assert item["granule_id"] == "reanalysis-era5-single-levels"
    assert item["title"].startswith("ERA5 hourly")
    assert item["data_link"] == (
        "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels"
    )
    assert "api/catalogue/v1/collections" in seen["url"]
    assert "limit=3" in seen["url"]


def test_test_portal_new_capability_probe_urls(repo_env, monkeypatch) -> None:
    from app.services import portal_catalog

    urls: list[str] = []

    def fake_urlopen(url, **kw):
        urls.append(url)
        return _FakeResponse(200)

    monkeypatch.setattr(portal_catalog, "safe_urlopen", fake_urlopen)
    assert portal_catalog.test_portal("esa_copernicus")["ok"] is True
    assert portal_catalog.test_portal("ecmwf_cds")["ok"] is True
    assert any("odata/v1/Products" in u for u in urls)
    assert any("api/catalogue/v1/collections" in u for u in urls)


def test_custom_portal_new_capability_gets_template(repo_env) -> None:
    from app.services.portal_catalog import list_portal_defs, upsert_portal

    upsert_portal(
        "cds_mirror",
        {
            "name": "CDS 镜像",
            "base_url": "https://cds-mirror.example.org/",
            "search_capability": "cds",
        },
    )
    defn = list_portal_defs(repo=repo_env)["cds_mirror"]
    assert defn.search_capability == "cds"
    assert defn.search_url_template is not None


# ── presets / labels 联动 ────────────────────────────────────────────────────


def test_effective_base_urls_merge_order(repo_env) -> None:
    from app.services.portal_catalog import (
        effective_base_urls,
        upsert_portal,
    )

    repo_env.set_json(
        "open_data_presets", {"cma_nsmc": "https://nsmc-mirror.example.cn/"}
    )
    upsert_portal(
        "my_lab_portal", {"name": "Lab", "base_url": "https://lab.example.org/"}
    )
    urls = effective_base_urls(repo=repo_env)
    # KV 覆盖优先
    assert urls["cma_nsmc"] == "https://nsmc-mirror.example.cn/"
    # 自定义门户进入 presets 域
    assert urls["my_lab_portal"] == "https://lab.example.org/"
    # 未覆盖的目录默认保留
    assert urls["noaa_goes"] == "https://cdn.star.nesdis.noaa.gov/"


def test_get_data_source_config_labels_from_catalog(repo_env, monkeypatch) -> None:
    from app.services import config_service
    from app.services.portal_catalog import upsert_portal

    upsert_portal(
        "my_lab_portal",
        {"name": "实验室数据门户", "base_url": "https://lab.example.org/"},
    )
    # get_data_source_config 内部经 _research_data_repo() 取仓库 → 同样指向临时仓库
    monkeypatch.setattr(config_service, "_research_data_repo", lambda: repo_env)

    cfg = config_service.get_data_source_config()
    assert cfg["open_data_preset_labels"]["my_lab_portal"] == "实验室数据门户"
    assert "ecmwf_cds" in cfg["open_data_presets"]
    assert cfg["open_data_presets"]["my_lab_portal"] == "https://lab.example.org/"
    # 遗留标签仍存在
    assert cfg["open_data_preset_labels"]["noaa_nomads"]


# ── 节点模板动态 options ─────────────────────────────────────────────────────


def test_node_templates_dynamic_portal_options(repo_env) -> None:
    from app.services import node_template_registry as ntr
    from app.services.portal_catalog import upsert_portal

    upsert_portal(
        "my_lab_portal",
        {"name": "Lab", "base_url": "https://lab.example.org/"},
    )
    ntr.invalidate_portal_options_cache()

    tpl = ntr.get_node_template("download/http_open_data")
    assert tpl is not None
    params = {p["key"]: p for p in tpl["params"]}
    presets = params["preset"]["options"]
    assert "my_lab_portal" in presets
    assert "ecmwf_cds" in presets
    assert "nasa_earthdata" in presets
    # cred_profile options 含目录凭据键
    cred_opts = params["cred_profile"]["options"]
    assert "earthdata" in cred_opts
    assert "nsmc" in cred_opts


def test_node_templates_ssh_sync_profile_server_options(repo_env, monkeypatch, tmp_path):
    """ssh_sync server_type 动态注入：启用 profile（ssh/sftp/filebrowser）+ 遗留三台。"""
    from app.services import node_template_registry as ntr
    from app.services.remote_storage_credentials_repository import (
        RemoteStorageCredentialsRepository,
    )

    repo = RemoteStorageCredentialsRepository(tmp_path / "rs.sqlite3", encryption_key="")
    monkeypatch.setattr(
        "app.services.config_remote_storage._get_remote_storage_repository",
        lambda: repo,
    )
    repo.upsert(profile_id="lab-nas", protocol="filebrowser", host="", extra={"base_url": "https://nas.local"})
    repo.upsert(profile_id="lab-hpc", protocol="sftp", host="172.16.98.184")
    repo.upsert(profile_id="lab-smb", protocol="smb", host="files")  # 不支持同步 → 不注入
    repo.upsert(profile_id="disabled-fb", protocol="filebrowser", host="", enabled=False)
    ntr.invalidate_portal_options_cache()

    tpl = ntr.get_node_template("download/ssh_sync")
    assert tpl is not None
    params = {p["key"]: p for p in tpl["params"]}
    opts = params["server_type"]["options"]
    assert opts[:3] == ["hpc", "win11", "nas"]
    assert "lab-nas" in opts and "lab-hpc" in opts
    assert "lab-smb" not in opts
    assert "disabled-fb" not in opts
    assert params["server_type"].get("allow_custom") is True


def test_node_templates_dynamic_options_fallback_on_catalog_error(
    monkeypatch,
) -> None:
    """catalog 不可用时回退硬编码列表（import 失败路径）。"""
    from app.services import node_template_registry as ntr

    def boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "app.services.portal_catalog.list_portal_defs",
        boom,
    )
    ntr.invalidate_portal_options_cache()
    tpl = ntr.get_node_template("download/http_open_data")
    assert tpl is not None
    params = {p["key"]: p for p in tpl["params"]}
    presets = params["preset"]["options"]
    assert "noaa_nomads" in presets
    assert "nasa_earthdata" in presets


# ── 路由鉴权 ─────────────────────────────────────────────────────────────────


def _route_dependency_callables(route) -> list:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return []
    return [
        dep.call for dep in (dependant.dependencies or []) if getattr(dep, "call", None)
    ]


def test_portal_routes_auth_guards() -> None:
    from app.api import config_routes
    from app.api.deps import (
        require_config_management_access,
        require_config_read_access,
    )

    expected: dict[tuple[str, str], object] = {
        ("GET", "/config/portals"): require_config_read_access,
        ("PUT", "/config/portals/{portal_id}"): require_config_management_access,
        ("DELETE", "/config/portals/{portal_id}"): require_config_management_access,
        ("POST", "/config/portals/{portal_id}/test"): require_config_management_access,
        ("GET", "/config/portals/{portal_id}/search"): require_config_read_access,
    }
    found: set[tuple[str, str]] = set()
    for route in config_routes.router.routes:
        key = (getattr(route, "methods", None) and next(iter(route.methods)), route.path)
        if key not in expected:
            continue
        found.add(key)
        guards = _route_dependency_callables(route)
        assert expected[key] in guards, f"{key} missing guard {expected[key]}"
    assert found == set(expected.keys()), f"missing routes: {set(expected) - found}"


# ── 动态 options 缓存失效（node_template_registry） ─────────────────────────


@pytest.fixture()
def _fresh_options_cache():
    from app.services import node_template_registry as ntr

    ntr.invalidate_portal_options_cache()
    yield ntr
    ntr.invalidate_portal_options_cache()


def test_portal_upsert_invalidates_options_cache(repo_env, _fresh_options_cache) -> None:
    ntr = _fresh_options_cache
    options0 = ntr._dynamic_portal_options()
    assert "custom_opts_portal" not in options0["presets"]

    from app.services.config_service import upsert_portal

    upsert_portal(
        "custom_opts_portal",
        {
            "name": "缓存失效测试门户",
            "base_url": "https://example.test/",
            "auth_type": "none",
        },
    )
    options1 = ntr._dynamic_portal_options()
    assert "custom_opts_portal" in options1["presets"], (
        "upsert_portal 后动态 options 缓存未失效"
    )


def test_portal_delete_invalidates_options_cache(repo_env, _fresh_options_cache) -> None:
    from app.services.config_service import delete_portal, upsert_portal

    upsert_portal(
        "custom_del_portal",
        {
            "name": "删除失效测试",
            "base_url": "https://example.test/",
            "auth_type": "none",
        },
    )
    ntr = _fresh_options_cache
    assert "custom_del_portal" in ntr._dynamic_portal_options()["presets"]

    delete_portal("custom_del_portal")
    assert "custom_del_portal" not in ntr._dynamic_portal_options()["presets"], (
        "delete_portal 后动态 options 缓存未失效"
    )


def test_remote_storage_profile_write_invalidates_options_cache(
    repo_env, _fresh_options_cache, monkeypatch
) -> None:
    from app.services import config_remote_storage as crs

    ntr = _fresh_options_cache

    # 有状态仓储打桩：签名对齐 RemoteStorageCredentialsRepository（关键字 upsert /
    # include_disabled 过滤），并隔离真实仓储中已存在的 profile（如 seahpc）。
    class _FakeRepo:
        def __init__(self):
            self.profiles: dict[str, dict] = {}

        def upsert(
            self,
            *,
            profile_id,
            protocol,
            host="",
            port=None,
            username=None,
            secret=None,
            private_key_pem=None,
            domain=None,
            extra=None,
            display_name=None,
            enabled=None,
        ):
            info = {
                "profile_id": profile_id,
                "protocol": protocol,
                "host": host,
                "port": port,
                "username": username,
                "extra": dict(extra or {}),
                "enabled": enabled if enabled is not None else True,
            }
            self.profiles[profile_id] = info
            return dict(info)

        def get_profile_info(self, profile_id):
            info = self.profiles.get(profile_id)
            return dict(info) if info is not None else None

        def delete(self, profile_id):
            return self.profiles.pop(profile_id, None) is not None

        def set_enabled(self, profile_id, enabled):
            info = self.profiles.get(profile_id)
            if info is None:
                return False
            info["enabled"] = enabled
            return True

        def list_profiles(self, include_disabled=True):
            items = [dict(p) for p in self.profiles.values()]
            if not include_disabled:
                items = [p for p in items if p.get("enabled") is not False]
            return items

        def list_history(self, profile_id):
            return []

    fake = _FakeRepo()
    monkeypatch.setattr(crs, "_get_remote_storage_repository", lambda: fake)

    base = {"hpc", "win11", "nas"}
    assert set(ntr._dynamic_portal_options()["ssh_servers"]) == base

    crs.upsert_remote_storage_profile(
        profile_id="seahpc_probe",
        protocol="ssh",
        host="hpc.example.test",
        port=22,
        username="u",
        secret={"kind": "password", "password": "p"},
    )
    got = ntr._dynamic_portal_options()
    assert "seahpc_probe" in got["ssh_servers"], (
        "upsert_remote_storage_profile 后 ssh_servers 缓存未失效"
    )
