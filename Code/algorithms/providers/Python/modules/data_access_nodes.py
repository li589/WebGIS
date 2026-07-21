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


def _resolve_uri_and_path(inputs: dict[str, object], params: dict[str, object]) -> tuple[str | None, str | None]:
    uri = _coerce_path(inputs.get("uri")) or _coerce_path(params.get("uri"))
    path = _coerce_path(inputs.get("path")) or _coerce_path(params.get("path"))
    data = inputs.get("data")
    if isinstance(data, dict):
        uri = uri or _coerce_path(data.get("uri"))
        path = path or _coerce_path(data.get("path")) or _coerce_path(data.get("input_dir"))
    if path and path.startswith(("http://", "https://", "smb://", "sftp://", "ftp://", "ftps://", "gs://", "gcs://", "file://")):
        uri = uri or path
        path = None
    return uri, path


@register_module_decorator(name="remote_fetch")
class RemoteFetchModule(BaseModule):
    name = "remote_fetch"
    description = "Materialize smb/sftp/ftp/http/https/gs/local URI into long-lived cache."
    input_ports = [
        PortSpec(name="uri", kind="value", data_class="string", required=False),
        PortSpec(name="data", kind="data", data_class="source", required=False),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"uri": "", "cred_profile": ""}

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        from data_access.sources.http import HttpSource
        from data_access.sources.local_fs import LocalFileSource
        from data_access.sources.remote import RemoteSource

        uri, local_hint = _resolve_uri_and_path(inputs, params)
        if not uri and local_hint:
            # Already local
            p = Path(local_hint)
            if not p.exists():
                raise FileNotFoundError(f"Local path not found: {p}")
            return _store_path_manifest(ctx, module_name=self.name, path=p, product_type="materialized_path")

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
    "esa_copernicus": "https://catalogue.dataspace.copernicus.eu/",
}


@register_module_decorator(name="http_open_data")
class HttpOpenDataModule(BaseModule):
    name = "http_open_data"
    description = "Download NOAA/NASA/ESA open HTTP data using preset base + relative path."
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {
        "preset": "noaa_nomads",
        "base_url": "",
        "relative_path": "",
        "query": "",
        "token_header": "",
        "token_value": "",
    }

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
        from data_access.sources.http import HttpSource

        base = str(params.get("base_url") or "").strip()
        if not base:
            preset = str(params.get("preset") or "noaa_nomads")
            # Allow runtime override via request tags / datasource
            presets = dict(_DEFAULT_OPEN_DATA_PRESETS)
            ds = dict(ctx.request.datasource_selection or {})
            custom = ds.get("open_data_presets")
            if isinstance(custom, dict):
                presets.update({str(k): str(v) for k, v in custom.items()})
            base = presets.get(preset, "")
        if not base:
            raise ValueError("http_open_data requires base_url or a known preset")

        rel = _coerce_path(inputs.get("path")) or str(params.get("relative_path") or "").strip()
        if not rel:
            raise ValueError("http_open_data requires relative_path")
        query = str(params.get("query") or "").strip()
        url = urljoin(base if base.endswith("/") else base + "/", rel.lstrip("/"))
        if query:
            url = f"{url}?{query.lstrip('?')}" if "?" not in url else f"{url}&{query.lstrip('&')}"

        metadata: dict[str, object] = {}
        header_name = str(params.get("token_header") or "").strip()
        token = str(params.get("token_value") or "").strip()
        if header_name and token:
            metadata["http_headers"] = {header_name: token}

        target = _materialize_root(ctx)
        source = HttpSource()
        resource = source.locate(url, metadata=metadata)
        materialized = source.materialize(resource, target_dir=target)
        local_path = materialized.local_path or materialized.metadata.get("local_path")
        if not local_path:
            raise RuntimeError(f"HTTP open data materialize failed for {url}")
        return _store_path_manifest(
            ctx,
            module_name=self.name,
            path=local_path,
            product_type="open_data_http",
            extra={"url": url, "preset": str(params.get("preset") or "")},
        )


@register_module_decorator(name="archive_extract")
class ArchiveExtractModule(BaseModule):
    name = "archive_extract"
    description = "Extract zip/tar/gz/tgz archives to a directory."
    input_ports = [
        PortSpec(name="path", kind="value", data_class="string", required=False),
        PortSpec(name="data", kind="data", data_class="source", required=False),
    ]
    output_ports = [
        PortSpec(name="path", kind="value", data_class="string"),
        PortSpec(name="extract_dir", kind="value", data_class="string"),
        PortSpec(name="manifest", kind="artifact", data_class="product_manifest"),
    ]
    default_params = {"archive_path": "", "output_dirname": "extracted"}

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
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
        extract_dir = Path(ctx.workspace) / "products" / "archives" / f"{ctx.node_id}_{out_name}"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)

        name_lower = archive_path.name.lower()
        if name_lower.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)
        elif name_lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2")):
            with tarfile.open(archive_path, "r:*") as tf:
                tf.extractall(extract_dir)
        elif name_lower.endswith(".gz") and not name_lower.endswith(".tar.gz"):
            import gzip

            out_file = extract_dir / archive_path.stem
            with gzip.open(archive_path, "rb") as src, out_file.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            raise ValueError(f"Unsupported archive type: {archive_path.suffix}")

        result = _store_path_manifest(
            ctx,
            module_name=self.name,
            path=extract_dir,
            product_type="extracted_archive",
            extra={"archive": str(archive_path)},
        )
        result["extract_dir"] = str(extract_dir)
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

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
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
            fmt = {".json": "json", ".yaml": "yaml", ".yml": "yaml", ".ini": "ini", ".xml": "xml"}.get(ext, "json")

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
            config = {section: dict(parser.items(section)) for section in parser.sections()}
        elif fmt == "xml":
            import xml.etree.ElementTree as ET

            root = ET.fromstring(text)

            def _elem_to_dict(elem: ET.Element) -> dict[str, object]:
                children = list(elem)
                if not children:
                    return {"tag": elem.tag, "text": (elem.text or "").strip(), "attrib": dict(elem.attrib)}
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

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
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
            preferred = [p for p in candidates if p.suffix.lower() in {".h5", ".nc", ".tif", ".tiff", ".mat"}]
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
                w, s, e, n = params.get("west"), params.get("south"), params.get("east"), params.get("north")
                if None not in (w, s, e, n):
                    bbox = (float(w), float(s), float(e), float(n))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                bbox = None

        time_index = params.get("time_index")
        ti = int(time_index) if time_index is not None and str(time_index).strip() != "" else None

        reader = UniversalDataReader(path)
        data = reader.read_variable(variable, bbox=bbox, time_index=ti)

        out_dir = Path(ctx.workspace) / "products" / "variables"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ctx.node_id}_{Path(variable).name.replace('/', '_')}.npz"
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

            np.savez_compressed(out_path, **{k: v for k, v in payload.items() if v is not None})
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
            extra={"variable": variable, "source": str(path), "shape": list(data.shape)},
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

    def execute(self, inputs: dict[str, object], params: dict[str, object], ctx: NodeExecutionContext) -> dict[str, object]:
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
        if target_format in {"mat", "npy", "npz", "csv", "json"} and src.suffix.lower() in {
            ".h5",
            ".hdf",
            ".he5",
            ".nc",
            ".tif",
            ".tiff",
            ".mat",
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
                raise ValueError("format_convert requires variable when converting scientific rasters")
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
                    np.savez_compressed(out_path, values=data.values, lat=data.lat, lon=data.lon)
            elif target_format == "csv":
                import numpy as np

                flat = np.asarray(data.values).ravel()
                out_path.write_text("\n".join(str(float(x)) for x in flat[:1_000_000]), encoding="utf-8")
            else:
                out_path.write_text(
                    json.dumps({"var_name": data.var_name, "shape": list(data.shape)}, ensure_ascii=False),
                    encoding="utf-8",
                )
        else:
            registry = build_default_format_registry()
            resource = build_resource_ref(uri=src.resolve().as_uri(), source_kind="local", local_path=str(src))
            loaded = registry.load(resource)
            if target_format == "json":
                out_path.write_text(json.dumps(loaded, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
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
