from __future__ import annotations

from typing import Optional

from webgis_gee.config.settings import Settings
from webgis_gee.storage.base import StorageBackend
from webgis_gee.storage.local import LocalStorageBackend
from webgis_gee.storage.minio import MinioStorageBackend


def create_storage_backend(
    settings: Optional[Settings] = None,
    *,
    backend_type: str | None = None,
    local_storage_root: str | None = None,
) -> StorageBackend:
    """根据配置创建相应的存储后端。"""
    settings = settings or Settings()
    effective_backend = backend_type or settings.storage_backend
    if effective_backend == "local":
        return LocalStorageBackend(
            base_path=local_storage_root or settings.local_storage_root
        )
    if effective_backend == "minio":
        if not all(
            [
                settings.minio_endpoint,
                settings.minio_access_key,
                settings.minio_secret_key,
                settings.minio_bucket,
            ]
        ):
            raise ValueError(
                "minio backend requires endpoint, access key, secret key and bucket"
            )
        return MinioStorageBackend(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    raise ValueError(f"Unsupported storage backend: {effective_backend}")
