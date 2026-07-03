from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref


class MinioSource:
    name = "minio"
    supported_schemes = ("minio", "s3")

    def can_handle(self, uri: str) -> bool:
        parsed = urlparse(uri)
        return parsed.scheme.lower() in {"minio", "s3"}

    def locate(
        self,
        uri: str,
        *,
        request: DataRequestV2 | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ResourceRef:
        _ = request
        parsed = urlparse(uri)
        object_key = parsed.path.lstrip("/")
        return build_resource_ref(
            uri=uri,
            source_kind="object_storage",
            storage_backend=parsed.scheme.lower(),
            bucket=parsed.netloc or None,
            object_key=object_key or None,
            metadata=dict(metadata or {}),
        )

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: Path | None = None,
    ) -> ResourceRef:
        staged_metadata = dict(resource.metadata)
        if target_dir is not None:
            staged_metadata["target_dir"] = str(target_dir)
        staged_metadata["materialization_status"] = "deferred"
        return build_resource_ref(
            uri=resource.uri,
            source_kind=resource.source_kind,
            format=resource.format,
            logical_type=resource.logical_type,
            storage_backend=resource.storage_backend or "minio",
            bucket=resource.bucket,
            object_key=resource.object_key,
            metadata=staged_metadata,
        )
