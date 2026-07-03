from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from contracts.data import DataBundle, DataRequest


FORMAT_ALIASES: dict[str, str] = {
    "hdf5": "h5",
    "xlsx": "excel",
    "xls": "excel",
    "geojson": "json",
}

LOGICAL_TYPE_BY_FORMAT: dict[str, str] = {
    "mat": "array",
    "nc": "array",
    "hdf": "array",
    "h5": "array",
    "tif": "raster",
    "tiff": "raster",
    "shp": "vector",
    "csv": "table",
    "excel": "table",
    "txt": "table",
    "json": "document",
    "xml": "document",
}

_WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")


def normalize_format(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().lstrip(".")
    if not normalized:
        return None
    return FORMAT_ALIASES.get(normalized, normalized)


def infer_logical_type(file_format: str | None) -> str:
    normalized = normalize_format(file_format)
    if normalized is None:
        return "blob"
    return LOGICAL_TYPE_BY_FORMAT.get(normalized, "blob")


def is_probable_windows_path(value: str) -> bool:
    return bool(_WINDOWS_DRIVE_PATTERN.match(value))


def infer_format_from_uri(uri: str) -> str | None:
    candidate = uri
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        candidate = unquote(parsed.path)
    suffix = Path(candidate).suffix
    return normalize_format(suffix)


def normalize_local_path(uri: str) -> str:
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        local_path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", local_path):
            return local_path[1:]
        return local_path
    return uri


def detect_source_kind(uri: str) -> str:
    if is_probable_windows_path(uri) or uri.startswith("file://"):
        path = Path(normalize_local_path(uri))
        return "local_dir" if path.suffix == "" else "local_file"
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if scheme == "cache":
        return "cache"
    if scheme in {"http", "https"}:
        return "online"
    if scheme in {"minio", "s3"}:
        return "object_storage"
    if scheme == "memory":
        return "memory"
    return "blob"


@dataclass(slots=True)
class ResourceRef:
    uri: str
    source_kind: str
    logical_type: str
    format: str | None = None
    media_type: str | None = None
    storage_backend: str | None = None
    bucket: str | None = None
    object_key: str | None = None
    local_path: str | None = None
    version: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return self.local_path is not None


@dataclass(slots=True)
class DataRequestV2:
    dataset_name: str
    variables: tuple[str, ...] = ()
    selector: dict[str, Any] = field(default_factory=dict)
    accepted_formats: tuple[str, ...] = ()
    preferred_format: str | None = None
    materialization_mode: str = "auto"
    access_mode: str = "lazy"
    allow_cache: bool = True
    allow_streaming: bool = False
    logical_type: str | None = None
    source_hints: tuple[str, ...] = ()
    converter_hints: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PreparedInput:
    request: DataRequestV2
    resources: tuple[ResourceRef, ...] = ()
    materialized_resources: tuple[ResourceRef, ...] = ()
    warnings: tuple[str, ...] = ()
    conversion_trace: tuple[dict[str, Any], ...] = ()
    cache_hits: tuple[str, ...] = ()


class SourceAdapter(Protocol):
    name: str
    supported_schemes: tuple[str, ...]

    def can_handle(self, uri: str) -> bool:
        ...

    def locate(
        self,
        uri: str,
        *,
        request: DataRequestV2 | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResourceRef:
        ...

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: Path | None = None,
    ) -> ResourceRef:
        ...


def build_resource_ref(
    uri: str,
    *,
    source_kind: str | None = None,
    format: str | None = None,
    logical_type: str | None = None,
    storage_backend: str | None = None,
    bucket: str | None = None,
    object_key: str | None = None,
    local_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ResourceRef:
    normalized_format = normalize_format(format) or infer_format_from_uri(uri)
    normalized_source_kind = source_kind or detect_source_kind(uri)
    normalized_local_path = local_path
    if normalized_local_path is None and normalized_source_kind in {"local_file", "local_dir"}:
        normalized_local_path = normalize_local_path(uri)
    return ResourceRef(
        uri=uri,
        source_kind=normalized_source_kind,
        logical_type=logical_type or infer_logical_type(normalized_format),
        format=normalized_format,
        storage_backend=storage_backend,
        bucket=bucket,
        object_key=object_key,
        local_path=normalized_local_path,
        metadata=dict(metadata or {}),
    )


def build_prepared_input(
    request: DataRequestV2,
    *,
    resources: list[ResourceRef] | tuple[ResourceRef, ...] = (),
    materialized_resources: list[ResourceRef] | tuple[ResourceRef, ...] = (),
    warnings: list[str] | tuple[str, ...] = (),
    conversion_trace: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    cache_hits: list[str] | tuple[str, ...] = (),
) -> PreparedInput:
    return PreparedInput(
        request=request,
        resources=tuple(resources),
        materialized_resources=tuple(materialized_resources),
        warnings=tuple(warnings),
        conversion_trace=tuple(conversion_trace),
        cache_hits=tuple(cache_hits),
    )


def resource_refs_to_legacy_bundle(
    legacy_request: DataRequest,
    resources: list[ResourceRef] | tuple[ResourceRef, ...],
    *,
    bundle_id: str | None = None,
    storage_mode: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DataBundle:
    from contracts.data import DataBundle

    local_paths: list[str] = []
    remote_refs: list[str] = []
    for resource in resources:
        if resource.local_path:
            local_paths.append(resource.local_path)
        else:
            remote_refs.append(resource.uri)
    return DataBundle(
        bundle_id=bundle_id or f"{legacy_request.dataset_name}-bundle",
        dataset_name=legacy_request.dataset_name,
        variables=list(legacy_request.variables),
        time_range=legacy_request.time_range,
        storage_mode=storage_mode or legacy_request.acquire_mode,
        local_paths=local_paths,
        remote_refs=remote_refs,
        metadata=dict(metadata or {}),
        is_materialized=all(resource.local_path for resource in resources),
    )
