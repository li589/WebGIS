from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref

logger = logging.getLogger(__name__)


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
        """Download object from MinIO/S3 to a local path.

        Requires ``minio`` package and endpoint credentials via env:
        ``MINIO_ENDPOINT`` / ``MINIO_ACCESS_KEY`` / ``MINIO_SECRET_KEY``
        (or ``BACKEND_MINIO_*``). Never returns deferred-as-ready.
        """
        destination_root = (
            Path(target_dir)
            if target_dir is not None
            else Path.cwd() / ".data" / "minio_cache"
        )
        destination_root.mkdir(parents=True, exist_ok=True)

        bucket = resource.bucket or urlparse(resource.uri).netloc
        object_key = resource.object_key or urlparse(resource.uri).path.lstrip("/")
        if not bucket or not object_key:
            raise ValueError(
                f"MinIO materialize requires bucket and object_key for {resource.uri}"
            )

        safe_name = object_key.replace("/", "_")
        local_path = destination_root / safe_name

        endpoint = (
            os.getenv("BACKEND_MINIO_ENDPOINT") or os.getenv("MINIO_ENDPOINT") or ""
        ).strip()
        access_key = (
            os.getenv("BACKEND_MINIO_ACCESS_KEY") or os.getenv("MINIO_ACCESS_KEY") or ""
        ).strip()
        secret_key = (
            os.getenv("BACKEND_MINIO_SECRET_KEY") or os.getenv("MINIO_SECRET_KEY") or ""
        ).strip()
        secure = (
            os.getenv("BACKEND_MINIO_SECURE") or os.getenv("MINIO_SECURE") or "false"
        ).lower() == "true"

        if not endpoint or not access_key or not secret_key:
            raise ValueError(
                "MinIO materialize requires BACKEND_MINIO_ENDPOINT / ACCESS_KEY / SECRET_KEY "
                f"(refusing deferred status for {resource.uri})"
            )

        try:
            from minio import Minio  # type: ignore
        except ImportError as exc:
            raise ValueError(
                "minio package is required to materialize s3/minio URIs"
            ) from exc

        client = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure
        )
        logger.info("Materializing MinIO %s/%s -> %s", bucket, object_key, local_path)
        try:
            client.fget_object(bucket, object_key, str(local_path))
        except Exception as exc:
            local_path.unlink(missing_ok=True)
            raise ValueError(
                f"MinIO materialize failed for {resource.uri}: {exc}"
            ) from exc

        staged_metadata = dict(resource.metadata)
        staged_metadata["materialization_status"] = "ready"
        staged_metadata["local_path"] = str(local_path)
        if target_dir is not None:
            staged_metadata["target_dir"] = str(target_dir)

        return build_resource_ref(
            uri=local_path.as_uri(),
            source_kind=resource.source_kind,
            format=resource.format,
            logical_type=resource.logical_type,
            storage_backend="local",
            bucket=bucket,
            object_key=object_key,
            metadata=staged_metadata,
        )
