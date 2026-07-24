from __future__ import annotations

from abc import ABC, abstractmethod
from io import BytesIO
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from minio import Minio
except ImportError:  # pragma: no cover - optional dependency in local-only mode
    Minio = None


@dataclass
class StoredObject:
    object_key: str
    file_path: Path | None
    content_type: str
    content_length: int
    metadata: dict[str, Any] = field(default_factory=dict)
    public_url: str | None = None


class ObjectStore(ABC):
    backend_name: str

    @abstractmethod
    def put_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> StoredObject: ...

    @abstractmethod
    def get_object(self, object_key: str) -> StoredObject | None: ...

    def fetch_bytes(self, object_key: str) -> bytes | None:
        """Return raw bytes for an object, or None if not found.

        Default implementation reads from ``file_path``; MinIO overrides
        to stream from the remote bucket. Used by preview routes when
        ``file_path`` is None (MinIO-backed artifacts).
        """
        stored = self.get_object(object_key)
        if stored is None or stored.file_path is None:
            return None
        return stored.file_path.read_bytes()


class LocalObjectStore(ObjectStore):
    backend_name = "local"

    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir)
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> StoredObject:
        file_path = self._root_dir / object_key
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写入：先写临时文件再 rename，避免半写文件被并发读取
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        tmp_path.write_bytes(data)
        tmp_path.replace(file_path)
        meta_path = self._meta_path(object_key)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
        meta_tmp_path.write_text(
            json.dumps(
                {
                    "object_key": object_key,
                    "content_type": content_type,
                    "content_length": len(data),
                    "metadata": metadata or {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        meta_tmp_path.replace(meta_path)
        return StoredObject(
            object_key=object_key,
            file_path=file_path,
            content_type=content_type,
            content_length=len(data),
            metadata=metadata or {},
        )

    def get_object(self, object_key: str) -> StoredObject | None:
        file_path = self._root_dir / object_key
        meta_path = self._meta_path(object_key)
        if not file_path.exists() or not meta_path.exists():
            return None
        metadata_payload = json.loads(meta_path.read_text(encoding="utf-8"))
        return StoredObject(
            object_key=object_key,
            file_path=file_path,
            content_type=metadata_payload["content_type"],
            content_length=int(metadata_payload["content_length"]),
            metadata=metadata_payload.get("metadata", {}),
        )

    def _meta_path(self, object_key: str) -> Path:
        object_path = Path(object_key)
        return self._root_dir / object_path.parent / f"{object_path.name}.meta.json"


class MinioObjectStore(ObjectStore):
    backend_name = "minio"

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
    ) -> None:
        if Minio is None:
            raise RuntimeError(
                "MinIO dependency is not installed. Add 'minio' to backend requirements."
            )
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    def put_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> StoredObject:
        self._client.put_object(
            self._bucket,
            object_key,
            data=BytesIO(data),
            length=len(data),
            content_type=content_type,
            metadata={key: str(value) for key, value in (metadata or {}).items()},
        )
        return StoredObject(
            object_key=object_key,
            file_path=None,
            content_type=content_type,
            content_length=len(data),
            metadata=metadata or {},
            public_url=self._client.presigned_get_object(self._bucket, object_key),
        )

    def get_object(self, object_key: str) -> StoredObject | None:
        try:
            stat = self._client.stat_object(self._bucket, object_key)
        except Exception as exc:
            logger.warning("MinIO get_object failed for %s: %s", object_key, exc)
            return None
        return StoredObject(
            object_key=object_key,
            file_path=None,
            content_type=stat.content_type or "application/octet-stream",
            content_length=stat.size,
            metadata={
                key: value for key, value in getattr(stat, "metadata", {}).items()
            },
            public_url=self._client.presigned_get_object(self._bucket, object_key),
        )

    def fetch_bytes(self, object_key: str) -> bytes | None:
        try:
            response = self._client.get_object(self._bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            logger.warning("MinIO fetch_bytes failed for %s: %s", object_key, exc)
            return None


def build_object_store() -> ObjectStore:
    backend = settings.object_store_backend.lower()
    if backend == "local":
        return LocalObjectStore(settings.result_artifact_dir)
    if backend == "minio":
        if (
            not settings.minio_endpoint
            or not settings.minio_access_key
            or not settings.minio_secret_key
        ):
            raise ValueError(
                "MinIO backend requires endpoint, access key, and secret key."
            )
        return MinioObjectStore(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    raise ValueError(
        f"Unsupported object store backend: {settings.object_store_backend}"
    )


object_store = build_object_store()
