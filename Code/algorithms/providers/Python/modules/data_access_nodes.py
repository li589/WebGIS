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


# Default open-data base URLs (overridable via params / settings injection)
_DEFAULT_OPEN_DATA_PRESETS: dict[str, str] = {
    "noaa_nomads": "https://nomads.ncep.noaa.gov/",
    "noaa_goes": "https://cdn.star.nesdis.noaa.gov/",
    "nasa_earthdata": "https://data.lpdaac.earthdatacloud.nasa.gov/",
    "nasa_cmr": "https://cmr.earthdata.nasa.gov/",
    "nsidc_data": "https://n5eil01u.ecs.nsidc.org/",
    "nasa_ges_disc": "https://hydro1.gesdisc.eosdis.nasa.gov/",
    "nasa_gldas": "https://hydro1.gesdisc.eosdis.nasa.gov/data/GLDAS/",
    "esa_copernicus": "https://catalogue.dataspace.copernicus.eu/",
    "esa_download": "https://download.dataspace.copernicus.eu/",
}

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
}


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

    # Prefer lazy resolve from backend config over secrets embedded in job payload.
    # Bridge sets portal_credentials_resolve=True and omits plaintext tokens.
    if (not portal_creds) and datasource_selection.get("portal_credentials_resolve"):
        try:
            from app.services.config_service import get_portal_credentials_runtime

            resolved = get_portal_credentials_runtime()
            if isinstance(resolved, dict):
                portal_creds = resolved
        except Exception:  # noqa: BLE001
            portal_creds = {}

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

    if auth_type in {"bearer", "token"} and token:
        value = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        headers[header_name] = value
    elif auth_type == "basic" and username:
        import base64

        raw_cred = f"{username}:{password}".encode("utf-8")
        headers["Authorization"] = f"Basic {base64.b64encode(raw_cred).decode('ascii')}"
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

        headers = _resolve_portal_headers(
            cred_profile=str(params.get("cred_profile") or ""),
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

        target = _materialize_root(ctx)
        source = HttpSource()
        resource = source.locate(url, metadata=metadata)
        materialized = source.materialize(resource, target_dir=target)
        local_path = materialized.local_path or materialized.metadata.get("local_path")
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
                "cred_profile": str(params.get("cred_profile") or ""),
            },
        )
        result["url"] = url
        return result


def _fnmatch_member(name: str, pattern: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(name.replace("\\", "/"), pattern) or fnmatch.fnmatch(
        Path(name).name, pattern
    )


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
        "解压 zip/tar/gz/tgz 归档到目录；支持 member_glob 过滤、recurse_once 内层压缩、"
        "Sentinel SAFE 根目录识别。不支持 7z/rar。"
    )
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
        PortSpec(name="data", kind="data", data_class="source", required=False),
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
        else:
            raise ValueError(
                f"Unsupported archive type: {archive_path.suffix}. "
                "Supported: zip/tar/gz/tgz. 7z/rar are not supported."
            )

        if bool(params.get("recurse_once")):
            _recurse_once_archives(extract_dir)

        result_path = extract_dir
        safe_root = _find_safe_root(extract_dir)
        extra: dict[str, object] = {"archive": str(archive_path)}
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
            ".grib",
            ".grib2",
            ".grb",
            ".grb2",
        }:
            variable = str(params.get("variable") or "").strip()
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
            if target_format == "mat":
                from scipy.io import savemat

                savemat(
                    out_path,
                    {
                        "values": data.values,
                        "lat": data.lat,
                        "lon": data.lon,
                        "var_name": data.var_name,
                    },
                    do_compression=True,
                )
            elif target_format in {"npy", "npz"}:
                import numpy as np

                if target_format == "npy":
                    np.save(out_path, data.values)
                else:
                    np.savez_compressed(
                        out_path, values=data.values, lat=data.lat, lon=data.lon
                    )
            elif target_format == "csv":
                import numpy as np

                flat = np.asarray(data.values).ravel()
                out_path.write_text(
                    "\n".join(str(float(x)) for x in flat[:1_000_000]), encoding="utf-8"
                )
            else:
                out_path.write_text(
                    json.dumps(
                        {"var_name": data.var_name, "shape": list(data.shape)},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
        else:
            registry = build_default_format_registry()
            resource = build_resource_ref(
                uri=src.resolve().as_uri(), source_kind="local", local_path=str(src)
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
