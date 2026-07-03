from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref


class CacheSource:
    name = "cache"
    supported_schemes = ("cache",)

    def can_handle(self, uri: str) -> bool:
        return urlparse(uri).scheme.lower() == "cache"

    def locate(
        self,
        uri: str,
        *,
        request: DataRequestV2 | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ResourceRef:
        _ = request
        parsed = urlparse(uri)
        merged_metadata = dict(metadata or {})
        cache_key = f"{parsed.netloc}{parsed.path}"
        if cache_key:
            merged_metadata.setdefault("cache_key", cache_key.lstrip("/"))
        local_path = merged_metadata.get("local_path")
        return build_resource_ref(
            uri=uri,
            source_kind="cache",
            storage_backend="cache",
            local_path=None if local_path is None else str(local_path),
            metadata=merged_metadata,
        )

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: Path | None = None,
    ) -> ResourceRef:
        _ = target_dir
        local_path = resource.local_path or resource.metadata.get("local_path")
        if local_path is None:
            return build_resource_ref(
                uri=resource.uri,
                source_kind=resource.source_kind,
                format=resource.format,
                logical_type=resource.logical_type,
                storage_backend="cache",
                metadata=resource.metadata,
            )
        resolved = Path(str(local_path))
        if not resolved.exists():
            raise FileNotFoundError(f"Cached resource does not exist: {resolved}")
        return build_resource_ref(
            uri=resource.uri,
            source_kind=resource.source_kind,
            format=resource.format,
            logical_type=resource.logical_type,
            storage_backend="cache",
            local_path=str(resolved.resolve()),
            metadata=resource.metadata,
        )
