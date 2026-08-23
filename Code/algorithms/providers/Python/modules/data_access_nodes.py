"""可执行数据获取与解析节点：下载 / 解压 / 配置 / 变量提取 / 格式转换。"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from contracts.product import ProductManifest, ProductRef
from modules.base import BaseModule
from modules.registry import register_module_decorator
from path_utils import local_path_to_uri
from workflow.schemas import ArtifactRef, NodeExecutionContext, PortSpec


def _materialize_root(ctx: NodeExecutionContext) -> Path:
    override = os.getenv("BACKEND_STATIC_CACHE_ROOT", "").strip()
    if override:
        root = Path(override)
    else:
        root = Path(ctx.workspace) / "data_access" / "materialized"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _store_path_manifest(
    ctx: NodeExecutionContext,
    *,
    module_name: str,
    path: str | Path,
    product_type: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    path_str = str(path)
    manifest = ProductManifest(
        job_id=ctx.request.job_id,
        run_id=ctx.runtime_context.run_id,
        products=[
            ProductRef(
                name=Path(path_str).name or module_name,
                type=product_type,
                uri=path_str,
                variable=None,
                tags={"module": module_name},
            )
        ],
        main_layers=[],
        metadata_uri=None,
        extra={"module_name": module_name, "path": path_str, **(extra or {})},
    )
    artifact = ArtifactRef(
        artifact_id=f"{ctx.runtime_context.run_id}:{ctx.node_id}:manifest",
        artifact_type="product_manifest",
        format="python_object",
        uri=None,
        producer_node_id=ctx.node_id,
        schema_name="ProductManifest",
        metadata={"module_name": module_name},
    )
    ctx.artifact_store.put(artifact, payload=manifest)
    return {"manifest": artifact, "path": path_str}


def _coerce_path(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("path", "input_dir", "local_path", "uri"):
            if value.get(key):
                return str(value[key])
        return None
    text = str(value).strip()
    return text or None


def _resolve_uri_and_path(
    inputs: dict[str, object], params: dict[str, object]
) -> tuple[str | None, str | None]:
    uri = _coerce_path(inputs.get("uri")) or _coerce_path(params.get("uri"))
    path = _coerce_path(inputs.get("path")) or _coerce_path(params.get("path"))
    data = inputs.get("data")
    if isinstance(data, dict):
        uri = uri or _coerce_path(data.get("uri"))
        path = (
            path
            or _coerce_path(data.get("path"))
            or _coerce_path(data.get("input_dir"))
        )
    if path and path.startswith(
        (
            "http://",
            "https://",
            "smb://",
            "sftp://",
            "ftp://",
            "ftps://",
            "gs://",
            "gcs://",
            "file://",
        )
    ):
        uri = uri or path
        path = None
    return uri, path


@register_module_decorator(name="remote_fetch")
class RemoteFetchModule(BaseModule):
    name = "remote_fetch"
    description = (
        "将任意 URI（smb/sftp/ftp/http/https/gs/local）物化到长期缓存；"
        "开放门户下载请优先使用 http_open_data。"
    )
    input_ports = [
        PortSpec(name="uri", kind="value", data_class="string", required=False),
        PortSpec(name="data", kind="data", data_class="source", required=False),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"uri": "", "cred_profile": ""}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from data_access.sources.http import HttpSource
        from data_access.sources.local_fs import LocalFileSource
        from data_access.sources.remote import RemoteSource

        uri, local_hint = _resolve_uri_and_path(inputs, params)
        if not uri and local_hint:
            # Already local
            p = Path(local_hint)
            if not p.exists():
                raise FileNotFoundError(f"Local path not found: {p}")
            return _store_path_manifest(
                ctx, module_name=self.name, path=p, product_type="materialized_path"
            )

        if not uri:
            raise ValueError("remote_fetch requires uri (or data.path/uri)")

        cred = str(params.get("cred_profile") or "").strip()
        if cred and "cred=" not in uri and "?" not in uri:
            sep = "&" if "?" in uri else "?"
            uri = f"{uri}{sep}cred={cred}"
        elif cred and "cred=" not in uri:
            uri = f"{uri}&cred={cred}"

        target = _materialize_root(ctx)
        lower = uri.lower()
        if lower.startswith(("http://", "https://")):
            source: Any = HttpSource()
        elif lower.startswith("file://") or ("://" not in uri and Path(uri).exists()):
            source = LocalFileSource()
        else:
            source = RemoteSource()

        resource = source.locate(uri)
        materialized = source.materialize(resource, target_dir=target)
        local_path = materialized.local_path or materialized.metadata.get("local_path")
        if not local_path:
            raise RuntimeError(f"Materialize did not produce local_path for {uri}")
        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=local_path,
            product_type="materialized_remote",
            extra={"uri": uri},
        )


# Minimal safety-net presets for offline/test scenarios where backend injection
# (datasource_selection.open_data_presets) is unavailable. The canonical source
# lives in backend app.services.data_cache_service.DEFAULT_OPEN_DATA_PRESETS.
_DEFAULT_OPEN_DATA_PRESETS: dict[str, str] = {
    "nasa_earthdata": "https://data.lpdaac.earthdatacloud.nasa.gov/",
    "nsidc_data": "https://data.nsidc.earthdatacloud.nasa.gov/",
}

# earthdata 家族（plan P2e）：命中且已装 earthaccess 时 http_open_data 默认
# 走 earthaccess 认证会话物化；use='legacy' 保持 HttpSource+门户头路径。
_EARTHDATA_FAMILY_KEYS = frozenset(
    {
        "earthdata",
        "nasa_earthdata",
        "nsidc",
        "nsidc_data",
        "nasa_ges_disc",
        "nasa_gldas",
    }
)
_HTTP_OPEN_DATA_USE_VALUES = frozenset({"auto", "earthaccess", "legacy"})


def _earthaccess_available() -> bool:
    try:
        import earthaccess  # noqa: F401

        return True
    except ImportError:
        return False


def _earthaccess_credentials_available(ds: dict[str, object]) -> bool:
    """earthaccess 登录凭据是否可解析（门户账密或环境变量）。

    缺凭据时 auto 保持 legacy 匿名路径，避免破坏公开数据集的免登录下载。
    """
    from modules.download_nodes import _resolve_earthdata_portal_userpass

    username, password = _resolve_earthdata_portal_userpass(ds)
    if username and password:
        return True
    return bool(
        os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")
    )


def _is_earthdata_family(preset: str, cred_profile: str) -> bool:
    key = (cred_profile.strip() or preset.strip()).lower()
    return key in _EARTHDATA_FAMILY_KEYS


def _materialize_via_earthaccess(
    url: str,
    target_dir: Path,
    ds: dict[str, object],
) -> Path:
    """earthaccess 认证会话物化：登录后 get_requests_https_session 下载。

    与 HttpSource 缓存互补：以 URL 原始文件名直落 target_dir（保留
    YYYYDDD 等元信息），续传/重试复用 ``ingest/_http_resume``。
    """
    import earthaccess

    from ingest._http_resume import download_with_retry
    from ingest.nsidc_download import _earthaccess_login
    from modules.download_nodes import _resolve_earthdata_portal_userpass

    username, password = _resolve_earthdata_portal_userpass(ds)
    _earthaccess_login(username, password, persist=True)
    session = earthaccess.get_requests_https_session()

    from urllib.parse import urlparse

    basename = Path(urlparse(url).path).name
    local_path = target_dir / (
        basename if basename.strip() else "earthaccess_download.bin"
    )
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if not download_with_retry(session, url, local_path):
        raise RuntimeError(f"earthaccess materialize failed: {url}")
    return local_path


_PORTAL_CRED_ALIASES: dict[str, tuple[str, ...]] = {
    "earthdata": (
        "earthdata",
        "nasa_earthdata",
        "nasa",
        "nasa_ges_disc",
        "nasa_gldas",
    ),
    "nsidc": ("nsidc", "nsidc_data", "earthdata"),
    "copernicus": ("copernicus", "esa", "esa_download", "esa_copernicus"),
    "nsmc": ("nsmc", "cma_nsmc", "cma_data", "fy"),
}

# URS token 交换：Earthdata 云 CDN（lp-prod-protected / nsidc-cumulus-prod-protected）
# 只认 Bearer token，不认 Basic。basic 凭据经 URS 换 token 后可用。
from ingest.endpoints import (  # noqa: E402
    URS_TOKEN_URL as _URS_TOKEN_URL,
    URS_TOKENS_URL as _URS_TOKENS_URL,
)

_URS_TOKEN_TTL_SECONDS = 100 * 60  # URS token 有效期 2h，提前 20 分钟过期
_urs_token_cache: dict[str, tuple[float, str]] = {}


def _urs_list_tokens(basic_header: str) -> list[dict[str, object]]:
    """列出账号当前有效 token（URS 每用户 token 数量有限，须先复用再新建）。"""
    import urllib.request

    req = urllib.request.Request(
        _URS_TOKENS_URL,
        method="GET",
        headers={"Authorization": basic_header, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    if isinstance(payload, dict):
        payload = payload.get("tokens") or []
    return [t for t in payload if isinstance(t, dict)] if payload else []


def _urs_token_still_valid(entry: dict[str, object]) -> bool:
    """判断 token 未过期（expiration_date 解析失败时按有效处理，URS 只列活跃 token）。"""
    import time
    from datetime import datetime, timezone

    raw = str(entry.get("expiration_date") or "").strip()
    if not raw:
        return True
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(raw.replace("Z", "+0000"), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp() > time.time() + 300
        except ValueError:
            continue
    return True


def _earthdata_bearer_token(username: str, password: str) -> str:
    """用 Earthdata 账密获取 URS Bearer token（进程内缓存，失败抛异常）。

    复用优先：URS 每用户 token 数量有上限，盲目新建很快触发
    403 max_token_limit（provider 侧限流）；先列已存在 token 并复用，
    仅在无可用 token 时新建。交换为幂等只读语义；缓存避免重复打 URS。
    可用 CGDA_URS_TOKEN_EXCHANGE=0 关闭（测试环境）。
    """
    import base64
    import time
    import urllib.error
    import urllib.request

    if os.getenv("CGDA_URS_TOKEN_EXCHANGE", "1").strip() == "0":
        raise RuntimeError("URS token exchange disabled by CGDA_URS_TOKEN_EXCHANGE")

    cache_key = f"{username}:{password}"
    now = time.monotonic()
    cached = _urs_token_cache.get(cache_key)
    if cached and now - cached[0] < _URS_TOKEN_TTL_SECONDS:
        return cached[1]

    basic_header = "Basic " + base64.b64encode(
        f"{username}:{password}".encode()
    ).decode("ascii")

    def _extract(entry_or_payload: object) -> str:
        raw = (
            entry_or_payload.get("access_token")
            if isinstance(entry_or_payload, dict)
            else entry_or_payload
        )
        if isinstance(raw, dict):
            return str(raw.get("token") or "").strip()
        return str(raw or "").strip()

    # 1) 复用已存在的有效 token
    try:
        for entry in _urs_list_tokens(basic_header):
            token = _extract(entry)
            if token and _urs_token_still_valid(entry):
                _urs_token_cache[cache_key] = (now, token)
                return token
    except Exception:  # noqa: BLE001
        pass  # 列表失败不阻断，继续尝试新建

    # 2) 新建 token
    req = urllib.request.Request(
        _URS_TOKEN_URL,
        data=b"",
        method="POST",
        headers={"Authorization": basic_header, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        # 3) 上限触发（并发/多进程竞争）：再列一次并复用
        if exc.code == 403:
            for entry in _urs_list_tokens(basic_header):
                token = _extract(entry)
                if token and _urs_token_still_valid(entry):
                    _urs_token_cache[cache_key] = (now, token)
                    return token
        raise
    # URS 响应两种形态都见过：{"access_token": "..."}（字符串）与
    # {"access_token": {"token": "..."}}（对象）；字符串形态解析失败会静默
    # 回退 Basic → 云 CDN 401，故必须兼容两者。
    token = _extract(payload)
    if not token:
        raise RuntimeError("URS token response missing access_token")
    _urs_token_cache[cache_key] = (now, token)
    return token


# CDSE OIDC token：copernicus 账密换 Bearer（access_token 有效期 ~10 min）。
# 交换与缓存镜像 _earthdata_bearer_token 的 URS 模式；静态 token 条目
# （BACKEND_COPERNICUS_TOKEN / 门户 token）有效期短，账密交换才是主路径。
_CDSE_TOKEN_TTL_SECONDS = 9 * 60
_cdse_token_cache: dict[str, tuple[float, str]] = {}


def _cdse_bearer_token(username: str, password: str) -> str:
    """copernicus 账密换 CDSE OIDC Bearer（进程内缓存，失败抛异常）。"""
    import time

    from ingest.cdse_download import exchange_cdse_token

    cache_key = f"{username}:{password}"
    now = time.monotonic()
    cached = _cdse_token_cache.get(cache_key)
    if cached and now - cached[0] < _CDSE_TOKEN_TTL_SECONDS:
        return cached[1]
    token = exchange_cdse_token(username, password)
    _cdse_token_cache[cache_key] = (now, token)
    return token


def _resolve_portal_headers(
    *,
    cred_profile: str,
    datasource_selection: dict[str, object],
    token_header: str,
    token_value: str,
    accept: str,
) -> dict[str, str]:
    """Build HTTP headers from explicit token params and/or injected portal credentials."""
    headers: dict[str, str] = {}
    if accept.strip():
        headers["Accept"] = accept.strip()
    if token_header.strip() and token_value.strip():
        headers[token_header.strip()] = token_value.strip()

    portal_creds = datasource_selection.get("portal_credentials")
    if not isinstance(portal_creds, dict):
        portal_creds = {}

    # Context-first: prefer portal_credentials already injected by the request
    # builder (python_provider_request_builder.py sets portal_credentials_resolve=True
    # and may inline resolved credentials). Only fall back to lazy backend import
    # when the context is empty and the resolve flag is set.
    if (not portal_creds) and datasource_selection.get("portal_credentials_resolve"):
        # P3 分层收口（2026-08-23）：经 _backend_bridge 边界桥解析门户凭据
        from _backend_bridge import get_portal_credentials

        resolved = get_portal_credentials()
        if isinstance(resolved, dict):
            portal_creds = resolved

    profile = cred_profile.strip().lower()
    if not profile:
        return headers

    # Prefer exact profile id, then aliases
    entry: dict[str, object] | None = None
    raw = portal_creds.get(profile)
    if isinstance(raw, dict):
        entry = raw
    else:
        for canonical, aliases in _PORTAL_CRED_ALIASES.items():
            if profile == canonical or profile in aliases:
                candidate = portal_creds.get(canonical)
                if isinstance(candidate, dict):
                    entry = candidate
                    break

    # NSIDC 回退 Earthdata（统一一处）：条目缺失或无 token/password 时，
    # 若 earthdata 启用且 use_for_nsidc=True，则复用 earthdata 凭证。
    # 非 nsidc profile 也可通过 entry.use_earthdata=True 请求回退。
    wants_earthdata = profile in {"nsidc", "nsidc_data"} or bool(
        isinstance(entry, dict) and entry.get("use_earthdata")
    )
    has_secret = isinstance(entry, dict) and bool(
        str(entry.get("token") or entry.get("access_token") or "").strip()
        or str(entry.get("password") or entry.get("secret") or "").strip()
    )
    if wants_earthdata and not has_secret:
        ed = portal_creds.get("earthdata")
        if (
            isinstance(ed, dict)
            and ed.get("enabled") is not False
            and ed.get("use_for_nsidc", True)
        ):
            entry = ed

    if not entry or entry.get("enabled") is False:
        return headers

    auth_type = str(entry.get("auth_type") or "bearer").lower()
    token = str(entry.get("token") or entry.get("access_token") or "").strip()
    username = str(entry.get("username") or "").strip()
    password = str(entry.get("password") or entry.get("secret") or "").strip()
    header_name = (
        str(entry.get("token_header") or "Authorization").strip() or "Authorization"
    )

    # Copernicus 家族（CDSE $value 下载）：有账密则优先 OIDC 交换 Bearer
    # （CDSE 不接受 Basic；静态 token 有效期仅 ~10 min）。交换失败回退
    # 静态 token / 既有分支语义。
    if profile in _PORTAL_CRED_ALIASES["copernicus"] and username and password:
        try:
            headers["Authorization"] = (
                f"Bearer {_cdse_bearer_token(username, password)}"
            )
            return headers
        except Exception:  # noqa: BLE001
            pass

    if auth_type in {"bearer", "token"} and token:
        value = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        headers[header_name] = value
    elif auth_type == "basic" and username:
        # Earthdata 云 CDN 只认 Bearer：先用账密换 URS token，失败回退 Basic
        # （GES DISC 传统端点仍接受 Basic）。
        bearer = ""
        if profile in {"earthdata", "nsidc", "nsidc_data"} or wants_earthdata:
            try:
                bearer = _earthdata_bearer_token(username, password)
            except Exception:  # noqa: BLE001
                bearer = ""
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        else:
            import base64

            raw_cred = f"{username}:{password}".encode()
            headers["Authorization"] = (
                f"Basic {base64.b64encode(raw_cred).decode('ascii')}"
            )
    elif auth_type == "header" and token:
        headers[header_name] = token
    elif token:
        # 未知 auth_type 的 fallback：直接把 token 放入指定 header
        headers[header_name] = token

    return headers


@register_module_decorator(name="http_open_data")
class HttpOpenDataModule(BaseModule):
    name = "http_open_data"
    description = (
        "门户数据下载（NOAA/NASA/NSIDC/ESA）：按预设 base URL + 相对路径物化到静态缓存；"
        "不负责产品检索。支持 cred_profile / token 鉴权与 force_refresh。"
    )
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="url", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "preset": "noaa_nomads",
        "base_url": "",
        "relative_path": "",
        "query": "",
        "cred_profile": "",
        "token_header": "",
        "token_value": "",
        "force_refresh": False,
        "accept": "",
        "use": "auto",
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from data_access.sources.http import HttpSource

        ds = dict(ctx.request.datasource_selection or {})
        base = str(params.get("base_url") or "").strip()
        preset = str(params.get("preset") or "noaa_nomads")
        if not base:
            presets = dict(_DEFAULT_OPEN_DATA_PRESETS)
            custom = ds.get("open_data_presets")
            if isinstance(custom, dict):
                presets.update({str(k): str(v) for k, v in custom.items()})
            base = str(presets.get(preset) or "")
        if not base:
            raise ValueError("http_open_data requires base_url or a known preset")

        rel = (
            _coerce_path(inputs.get("path"))
            or str(params.get("relative_path") or "").strip()
        )
        if not rel:
            raise ValueError("http_open_data requires relative_path")
        query = str(params.get("query") or "").strip()
        url = urljoin(base if base.endswith("/") else base + "/", rel.lstrip("/"))
        if query:
            url = (
                f"{url}?{query.lstrip('?')}"
                if "?" not in url
                else f"{url}&{query.lstrip('&')}"
            )

        use = str(params.get("use") or "auto").strip().lower()
        if use not in _HTTP_OPEN_DATA_USE_VALUES:
            raise ValueError(
                f"http_open_data: invalid use={use!r} (auto|earthaccess|legacy)"
            )
        cred_profile = str(params.get("cred_profile") or "").strip()
        effective_use = "legacy"
        if use == "earthaccess":
            if not _earthaccess_available():
                raise RuntimeError(
                    "earthaccess requested (use='earthaccess') but not installed"
                )
            effective_use = "earthaccess"
        elif (
            use == "auto"
            and _is_earthdata_family(preset, cred_profile)
            and _earthaccess_available()
            and _earthaccess_credentials_available(ds)
        ):
            effective_use = "earthaccess"

        target = _materialize_root(ctx)
        local_path: str | None = None
        cache_hit = False
        use_note = effective_use
        if effective_use == "earthaccess":
            try:
                local_path = str(_materialize_via_earthaccess(url, target, ds))
            except Exception as exc:  # noqa: BLE001
                # 公开对象（lp-prod-public 等）匿名 GET 可达；earthaccess 登录
                # 失败（token 过期 / 需重置密码）不应阻断免登录下载，回退 legacy。
                # 受保护对象随后会因 401/403 失败并保留原始下载错误语义。
                use_note = f"legacy(earthaccess_auth_fallback: {str(exc)[:160]})"
        if local_path is None:
            headers = _resolve_portal_headers(
                cred_profile=cred_profile,
                datasource_selection=ds,
                token_header=str(params.get("token_header") or ""),
                token_value=str(params.get("token_value") or ""),
                accept=str(params.get("accept") or ""),
            )
            metadata: dict[str, object] = {
                "force_refresh": bool(params.get("force_refresh")),
            }
            if headers:
                metadata["http_headers"] = headers

            source = HttpSource()
            resource = source.locate(url, metadata=metadata)
            materialized = source.materialize(resource, target_dir=target)
            local_path = materialized.local_path or materialized.metadata.get(
                "local_path"
            )
            if not local_path:
                raise RuntimeError(f"HTTP open data materialize failed for {url}")
            cache_hit = bool(materialized.metadata.get("cache_hit"))
        result = _store_path_manifest(
            ctx,
            module_name=self.name,
            path=local_path,
            product_type="open_data_http",
            extra={
                "url": url,
                "preset": preset,
                "cache_hit": cache_hit,
                "cred_profile": cred_profile,
                "use": use_note,
            },
        )
        result["url"] = url
        result["use"] = use_note
        return result


def _fnmatch_member(name: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(name.replace("\\", "/"), pattern) or fnmatch.fnmatch(
        Path(name).name, pattern
    )


def _passthrough_basename(archive_path: Path, inputs: dict[str, object]) -> str:
    """透传时的目标文件名：优先按来源 URL 恢复原始名。

    HttpSource 物化缓存以 sha256 命名，产品文件名中的 YYYYDDD 等元信息丢失
    （如 VNP13C1 HDF 需按文件名解析观测日期），须由 URL 还原。
    """
    url_hint = _coerce_path(inputs.get("url")) or ""
    if url_hint.startswith(("http://", "https://")):
        from urllib.parse import urlparse

        base = Path(urlparse(url_hint).path).name
        if base and "." in base:
            return base
    return archive_path.name


def _find_safe_root(extract_dir: Path) -> Path | None:
    if extract_dir.name.upper().endswith(".SAFE") and extract_dir.is_dir():
        return extract_dir
    safes = [
        p
        for p in extract_dir.iterdir()
        if p.is_dir() and p.name.upper().endswith(".SAFE")
    ]
    if len(safes) == 1:
        return safes[0]
    if safes:
        return safes[0]
    nested = list(extract_dir.glob("**/*.SAFE"))
    dirs = [p for p in nested if p.is_dir()]
    return dirs[0] if dirs else None


def _is_safe_archive_member(member_name: str, extract_dir: Path) -> bool:
    """Reject Zip/Tar Slip: member path must resolve inside extract_dir."""
    name = (member_name or "").replace("\\", "/")
    if (
        not name
        or name.startswith("/")
        or name.startswith("../")
        or "/../" in f"/{name}/"
    ):
        return False
    # Absolute Windows paths / drive letters
    if len(name) >= 2 and name[1] == ":":
        return False
    try:
        dest = (extract_dir / name).resolve()
        root = extract_dir.resolve()
        return dest == root or root in dest.parents
    except (OSError, ValueError, RuntimeError):
        return False


def _safe_zip_extract(zf: zipfile.ZipFile, member_name: str, extract_dir: Path) -> None:
    if not _is_safe_archive_member(member_name, extract_dir):
        raise ValueError(f"Refusing unsafe archive member path: {member_name!r}")
    zf.extract(member_name, extract_dir)


# ─── CMR granule 检索（公共，免凭据） ─────────────────────────────────────────

from ingest.endpoints import CMR_GRANULES_JSON as _CMR_GRANULE_URL  # noqa: E402

_CMR_NON_DATA_SUFFIXES = (
    ".iso.xml",
    ".cmr.xml",
    ".dmrpp",
    ".dmr",
    ".hdr",
    ".qa",
    ".md5",
    ".png",
    ".jpg",
    ".bmp",
    ".txt",
)


def _cmr_data_links(entry: dict[str, object], link_filter: str) -> list[str]:
    """从 CMR granule entry 提取 https 数据链接（跳过 browse/s3/元数据小文件）。"""
    links: list[str] = []
    for link in entry.get("links") or []:
        if not isinstance(link, dict):
            continue
        href = str(link.get("href") or "").strip()
        rel = str(link.get("rel") or "").strip()
        if not href.startswith("https://"):
            continue
        if "data#" not in rel and "data" != rel:
            continue
        if href.lower().endswith(_CMR_NON_DATA_SUFFIXES):
            continue
        if "/s3credentials" in href:
            continue
        if link_filter and link_filter not in href:
            continue
        links.append(href)
    return links


def _norm_cmr_date(raw: str) -> str:
    """YYYYMMDD / YYYY-MM-DD → CMR temporal 需要的 YYYY-MM-DD。"""
    text = raw.strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


@register_module_decorator(name="cmr_granule_search")
class CmrGranuleSearchModule(BaseModule):
    name = "cmr_granule_search"
    description = (
        "NASA CMR granule 检索（公共只读，免凭据）：按产品/版本/时间/范围返回"
        " granule 数据 URL。输出 path（首个 URL，可直连 http_open_data）与 urls 列表。"
        "Earthdata 云 CDN 的对象名含 tile/revolution/时间戳，无法由日期路径直接"
        "构造，须经 CMR 解析真实下载地址。"
    )
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="urls", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params: dict[str, object] = {
        "short_name": "",
        "version": "",
        "start_date": "",
        "end_date": "",
        "bounding_box": "",
        "link_filter": "",
        "max_results": 5,
        "cmr_base": _CMR_GRANULE_URL,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        import urllib.parse
        import urllib.request

        short_name = str(params.get("short_name") or "").strip()
        if not short_name:
            raise ValueError("cmr_granule_search requires short_name")
        start_date = _norm_cmr_date(str(params.get("start_date") or ""))
        end_date = _norm_cmr_date(str(params.get("end_date") or ""))
        if not start_date:
            raise ValueError("cmr_granule_search requires start_date")
        if not end_date:
            end_date = start_date

        query: dict[str, str] = {
            "short_name": short_name,
            "page_size": str(max(1, min(int(params.get("max_results") or 5), 50))),
            "sort_key": "-start_date",
        }
        version = str(params.get("version") or "").strip()
        if version:
            query["version"] = version
        # temporal: 覆盖与请求区间相交的 granule（CMR 语义）
        query["temporal"] = f"{start_date}T00:00:00Z,{end_date}T23:59:59Z"
        bbox = str(params.get("bounding_box") or "").strip()
        if bbox:
            query["bounding_box"] = bbox
        link_filter = str(params.get("link_filter") or "").strip()

        base = str(params.get("cmr_base") or _CMR_GRANULE_URL).strip()
        url = f"{base}?{urllib.parse.urlencode(query)}"
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "CGDA-Backend/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))

        entries = (payload.get("feed") or {}).get("entry") or []
        if isinstance(entries, dict):
            entries = [entries]
        urls: list[str] = []
        titles: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_links = _cmr_data_links(entry, link_filter)
            if entry_links:
                urls.append(entry_links[0])
                titles.append(str(entry.get("title") or ""))
        if not urls:
            raise ValueError(
                f"cmr_granule_search: no data links for {short_name} "
                f"[{start_date}~{end_date}] (hits={len(entries)})"
            )

        result = _store_path_manifest(
            ctx,
            module_name=self.name,
            path=urls[0],
            product_type="cmr_granule_urls",
            extra={
                "url": urls[0],
                "urls": urls,
                "titles": titles,
                "short_name": short_name,
                "version": version,
            },
        )
        result["urls"] = urls
        return result


def _safe_tar_extractall(
    tf: tarfile.TarFile,
    extract_dir: Path,
    members: list[tarfile.TarInfo],
) -> None:
    safe_members: list[tarfile.TarInfo] = []
    for member in members:
        if not _is_safe_archive_member(member.name, extract_dir):
            raise ValueError(f"Refusing unsafe archive member path: {member.name!r}")
        # Block symlink/hardlink escapes
        if member.issym() or member.islnk():
            raise ValueError(f"Refusing archive link member: {member.name!r}")
        safe_members.append(member)
    tf.extractall(extract_dir, members=safe_members)


def _recurse_once_archives(extract_dir: Path) -> None:
    """One-level nested extract for lone .zip / .gz files inside extract_dir."""
    import gzip

    for child in list(extract_dir.rglob("*")):
        if not child.is_file():
            continue
        # Only process files already under extract_dir (defense in depth)
        try:
            child.resolve().relative_to(extract_dir.resolve())
        except ValueError:
            continue
        name = child.name.lower()
        if name.endswith(".zip"):
            nest = child.parent / f"{child.stem}_nested"
            nest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(child, "r") as zf:
                for member_name in zf.namelist():
                    _safe_zip_extract(zf, member_name, nest)
        elif name.endswith(".gz") and not name.endswith(".tar.gz"):
            out_file = child.with_suffix("")
            if out_file.exists():
                continue
            with gzip.open(child, "rb") as src, out_file.open("wb") as dst:
                shutil.copyfileobj(src, dst)


@register_module_decorator(name="archive_extract")
class ArchiveExtractModule(BaseModule):
    name = "archive_extract"
    description = (
        "解压 zip/tar/gz/tgz 归档到目录；非归档数据文件（如 CMR 直下的裸 .h5/.nc）"
        "透传复制进目录，url 输入可恢复原始文件名。支持 member_glob 过滤、"
        "recurse_once 内层压缩、Sentinel SAFE 根目录识别。不支持 7z/rar。"
    )
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
        PortSpec(name="data", kind="data", data_class="source", required=False),
        PortSpec(
            name="url",
            kind="value",
            data_class="string",
            required=False,
            description="来源 URL；透传时用于恢复原始文件名（HTTP 缓存以 sha256 命名）。",
        ),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="extract_dir", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "archive_path": "",
        "output_dirname": "extracted",
        "member_glob": "",
        "recurse_once": False,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        archive = (
            _coerce_path(inputs.get("path"))
            or _coerce_path(inputs.get("data"))
            or str(params.get("archive_path") or "").strip()
        )
        if not archive:
            raise ValueError("archive_extract requires archive path")
        archive_path = Path(archive)
        if not archive_path.is_file():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        out_name = str(params.get("output_dirname") or "extracted")
        extract_dir = (
            Path(ctx.workspace) / "products" / "archives" / f"{ctx.node_id}_{out_name}"
        )
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        member_glob = str(params.get("member_glob") or "").strip()
        name_lower = archive_path.name.lower()
        passthrough = False
        if name_lower.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                members = zf.namelist()
                if member_glob:
                    members = [m for m in members if _fnmatch_member(m, member_glob)]
                for name in members:
                    _safe_zip_extract(zf, name, extract_dir)
        elif name_lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2")):
            with tarfile.open(archive_path, "r:*") as tf:
                members = [m for m in tf.getmembers() if m.isfile() or m.isdir()]
                if member_glob:
                    members = [
                        m for m in members if _fnmatch_member(m.name, member_glob)
                    ]
                _safe_tar_extractall(tf, extract_dir, members)
        elif name_lower.endswith(".gz") and not name_lower.endswith(".tar.gz"):
            import gzip

            out_file = extract_dir / archive_path.stem
            with gzip.open(archive_path, "rb") as src, out_file.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        elif name_lower.endswith((".7z", ".rar")):
            raise ValueError(
                f"Unsupported archive type: {archive_path.suffix}. "
                "Supported: zip/tar/gz/tgz. 7z/rar are not supported."
            )
        else:
            passthrough = True
            dest_name = _passthrough_basename(archive_path, inputs)
            if member_glob and not _fnmatch_member(dest_name, member_glob):
                raise FileNotFoundError(
                    f"passthrough file {dest_name!r} does not match "
                    f"member_glob {member_glob!r}"
                )
            shutil.copy2(archive_path, extract_dir / dest_name)

        if bool(params.get("recurse_once")):
            _recurse_once_archives(extract_dir)

        result_path = extract_dir
        safe_root = _find_safe_root(extract_dir)
        extra: dict[str, object] = {"archive": str(archive_path)}
        if passthrough:
            extra["passthrough"] = True
        if safe_root is not None:
            result_path = safe_root
            extra["safe_root"] = str(safe_root)
            extra["product_layout"] = "sentinel_safe"

        result = _store_path_manifest(
            ctx,
            module_name=self.name,
            path=result_path,
            product_type="extracted_archive",
            extra=extra,
        )
        result["extract_dir"] = str(extract_dir)
        result["path"] = str(result_path)
        return result


@register_module_decorator(name="config_read")
class ConfigReadModule(BaseModule):
    name = "config_read"
    description = "Read JSON/YAML/INI/XML config into a dict."
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
        PortSpec(name="data", kind="data", data_class="source", required=False),
    ]
    output_ports = [
        PortSpec(name="config", kind="config", data_class="dict"),
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"path": "", "format": "auto"}

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        path_str = (
            _coerce_path(inputs.get("path"))
            or _coerce_path(inputs.get("data"))
            or str(params.get("path") or "").strip()
        )
        if not path_str:
            raise ValueError("config_read requires path")
        path = Path(path_str)
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")

        fmt = str(params.get("format") or "auto").lower()
        if fmt == "auto":
            ext = path.suffix.lower()
            fmt = {
                ".json": "json",
                ".yaml": "yaml",
                ".yml": "yaml",
                ".ini": "ini",
                ".xml": "xml",
            }.get(ext, "json")

        text = path.read_text(encoding="utf-8")
        config: dict[str, object]
        if fmt == "json":
            loaded = json.loads(text)
            config = loaded if isinstance(loaded, dict) else {"value": loaded}
        elif fmt == "yaml":
            try:
                import yaml  # type: ignore
            except ImportError as exc:
                raise RuntimeError("PyYAML is required to read YAML configs") from exc
            loaded = yaml.safe_load(text)
            config = loaded if isinstance(loaded, dict) else {"value": loaded}
        elif fmt == "ini":
            import configparser

            parser = configparser.ConfigParser()
            parser.read_string(text)
            config = {
                section: dict(parser.items(section)) for section in parser.sections()
            }
        elif fmt == "xml":
            import xml.etree.ElementTree as ET

            root = ET.fromstring(text)

            def _elem_to_dict(elem: ET.Element) -> dict[str, object]:
                children = list(elem)
                if not children:
                    return {
                        "tag": elem.tag,
                        "text": (elem.text or "").strip(),
                        "attrib": dict(elem.attrib),
                    }
                return {
                    "tag": elem.tag,
                    "attrib": dict(elem.attrib),
                    "children": [_elem_to_dict(c) for c in children],
                }

            config = _elem_to_dict(root)
        else:
            raise ValueError(f"Unsupported config format: {fmt}")

        result = _store_path_manifest(
            ctx,
            module_name=self.name,
            path=path,
            product_type="config_dict",
            extra={"format": fmt, "keys": list(config.keys())[:50]},
        )
        result["config"] = config
        return result


@register_module_decorator(name="variable_extract")
class VariableExtractModule(BaseModule):
    name = "variable_extract"
    description = "Extract a variable via UniversalDataReader with optional bbox/time."
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
        PortSpec(name="data", kind="data", data_class="source", required=False),
        PortSpec(name="bbox", kind="geometry", data_class="bbox", required=False),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="array", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "path": "",
        "variable": "",
        "west": None,
        "south": None,
        "east": None,
        "north": None,
        "time_index": None,
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from data_access.universal_reader import UniversalDataReader

        path_str = (
            _coerce_path(inputs.get("path"))
            or _coerce_path(inputs.get("data"))
            or str(params.get("path") or "").strip()
        )
        if not path_str:
            raise ValueError("variable_extract requires path")
        path = Path(path_str)
        if path.is_dir():
            candidates = sorted(path.glob("**/*.*"))
            # Prefer common scientific formats
            preferred = [
                p
                for p in candidates
                if p.suffix.lower()
                in {
                    ".h5",
                    ".nc",
                    ".tif",
                    ".tiff",
                    ".mat",
                    ".grib",
                    ".grib2",
                    ".grb",
                    ".grb2",
                }
            ]
            if not preferred:
                raise FileNotFoundError(f"No readable data file under {path}")
            path = preferred[0]

        variable = str(params.get("variable") or "").strip()
        if not variable:
            raise ValueError("variable_extract requires variable name")

        bbox = None
        bbox_in = inputs.get("bbox")
        if isinstance(bbox_in, dict):
            try:
                bbox = (
                    float(bbox_in.get("west")),
                    float(bbox_in.get("south")),
                    float(bbox_in.get("east")),
                    float(bbox_in.get("north")),
                )
            except (TypeError, ValueError):
                bbox = None
        if bbox is None:
            try:
                w, s, e, n = (
                    params.get("west"),
                    params.get("south"),
                    params.get("east"),
                    params.get("north"),
                )
                if None not in (w, s, e, n):
                    bbox = (float(w), float(s), float(e), float(n))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                bbox = None

        time_index = params.get("time_index")
        ti = (
            int(time_index)
            if time_index is not None and str(time_index).strip() != ""
            else None
        )

        reader = UniversalDataReader(path)
        data = reader.read_variable(variable, bbox=bbox, time_index=ti)

        out_dir = Path(ctx.workspace) / "products" / "variables"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = (
            out_dir / f"{ctx.node_id}_{Path(variable).name.replace('/', '_')}.npz"
        )
        payload = {
            "values": data.values,
            "lat": data.lat,
            "lon": data.lon,
            "time": data.time,
            "var_name": data.var_name,
            "attrs": data.attrs,
        }
        try:
            import numpy as np

            np.savez_compressed(
                out_path, **{k: v for k, v in payload.items() if v is not None}
            )
        except Exception:
            # Fallback: write shape summary json if numpy save fails for object arrays
            summary_path = out_path.with_suffix(".json")
            summary_path.write_text(
                json.dumps(
                    {
                        "var_name": data.var_name,
                        "shape": list(data.shape),
                        "file_path": data.file_path,
                        "format": data.file_format,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            out_path = summary_path

        result = _store_path_manifest(
            ctx,
            module_name=self.name,
            path=out_path,
            product_type="extracted_variable",
            extra={
                "variable": variable,
                "source": str(path),
                "shape": list(data.shape),
            },
        )
        result["array"] = {
            "var_name": data.var_name,
            "shape": list(data.shape),
            "path": str(out_path),
            "source": str(path),
        }
        return result


@register_module_decorator(name="format_convert", aliases=["preprocess_format_convert"])
class FormatConvertModule(BaseModule):
    name = "format_convert"
    description = "Convert between supported formats via FormatRegistry adapters."
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
        PortSpec(name="data", kind="data", data_class="source", required=False),
        PortSpec(name="raster", kind="data", data_class="raster", required=False),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="raster", kind="data", data_class="raster"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "path": "",
        "target_format": "mat",
        "variable": "",
    }

    def execute(
        self,
        inputs: dict[str, object],
        params: dict[str, object],
        ctx: NodeExecutionContext,
    ) -> dict[str, object]:
        from data_access.contracts import build_resource_ref
        from data_access.format_adapters import build_default_format_registry
        from data_access.universal_reader import UniversalDataReader

        path_str = (
            _coerce_path(inputs.get("path"))
            or _coerce_path(inputs.get("data"))
            or _coerce_path(inputs.get("raster"))
            or str(params.get("path") or "").strip()
        )
        if not path_str:
            raise ValueError("format_convert requires path")
        src = Path(path_str)
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")

        target_format = str(params.get("target_format") or "mat").lower()
        out_dir = Path(ctx.workspace) / "products" / "converted"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{src.stem}.{target_format}"

        # Prefer universal reader → scipy/rasterio write for common scientific targets
        if target_format in {
            "mat",
            "npy",
            "npz",
            "csv",
            "json",
        } and src.suffix.lower() in {
            ".h5",
            ".hdf",
            ".he5",
            ".nc",
            ".tif",
            ".tiff",
            ".mat",
            ".npy",
            ".npz",
            ".grib",
            ".grib2",
            ".grb",
            ".grb2",
        }:
            import numpy as np

            variable = str(params.get("variable") or "").strip()
            # Intermediate extract/variable often writes .npz; load without FormatRegistry
            if src.suffix.lower() == ".npz":
                with np.load(src) as loaded:
                    keys = list(loaded.files)
                    key = variable if variable in keys else (keys[0] if keys else "")
                    if not key:
                        raise ValueError(f"empty npz: {src}")
                    arr = np.asarray(loaded[key])
                    lat = (
                        np.asarray(loaded["lat"])
                        if "lat" in loaded.files
                        else np.arange(arr.shape[-2] if arr.ndim >= 2 else 1)
                    )
                    lon = (
                        np.asarray(loaded["lon"])
                        if "lon" in loaded.files
                        else np.arange(arr.shape[-1] if arr.ndim >= 1 else 1)
                    )
                    var_name = key
                data_values, data_lat, data_lon, data_var = arr, lat, lon, var_name
            else:
                reader = UniversalDataReader(src)
                if not variable:
                    try:
                        vars_ = reader.list_variables()
                        if vars_:
                            variable = str(vars_[0])
                    except Exception:
                        variable = ""
                if not variable:
                    raise ValueError(
                        "format_convert requires variable when converting scientific rasters"
                    )
                data = reader.read_variable(variable)
                data_values, data_lat, data_lon, data_var = (
                    data.values,
                    data.lat,
                    data.lon,
                    data.var_name,
                )
            if target_format == "mat":
                from scipy.io import savemat

                savemat(
                    out_path,
                    {
                        "values": data_values,
                        "lat": data_lat,
                        "lon": data_lon,
                        "var_name": data_var,
                    },
                    do_compression=True,
                )
            elif target_format in {"npy", "npz"}:
                if target_format == "npy":
                    np.save(out_path, data_values)
                else:
                    np.savez_compressed(
                        out_path, values=data_values, lat=data_lat, lon=data_lon
                    )
            elif target_format == "csv":
                flat = np.asarray(data_values).ravel()
                out_path.write_text(
                    "\n".join(str(float(x)) for x in flat[:1_000_000]), encoding="utf-8"
                )
            else:
                out_path.write_text(
                    json.dumps(
                        {
                            "var_name": data_var,
                            "shape": list(np.asarray(data_values).shape),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
        else:
            registry = build_default_format_registry()
            resource = build_resource_ref(
                uri=local_path_to_uri(src, resolve=True),
                source_kind="local",
                local_path=str(src),
            )
            loaded = registry.load(resource)
            if target_format == "json":
                out_path.write_text(
                    json.dumps(loaded, default=str, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            else:
                # Best-effort: copy source if adapter cannot convert
                shutil.copy2(src, out_path)

        result = _store_path_manifest(
            ctx,
            module_name=self.name,
            path=out_path,
            product_type="converted_format",
            extra={"source": str(src), "target_format": target_format},
        )
        result["raster"] = {"path": str(out_path), "format": target_format}
        return result
