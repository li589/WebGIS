from __future__ import annotations

from io import BytesIO
from typing import Any

from minio import Minio
from minio.error import S3Error

from webgis_gee.runtime.exceptions import StorageOperationError
from webgis_gee.storage.base import StorageBackend


class MinioStorageBackend(StorageBackend):
    """MinIO object storage backend."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
        client: Minio | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = client or Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._ensure_bucket()

    def put(self, path: str, content: bytes) -> str:
        object_name = self._normalize_path(path)
        try:
            self._client.put_object(
                self._bucket,
                object_name,
                BytesIO(content),
                length=len(content),
            )
        except S3Error as exc:
            raise StorageOperationError(f"minio put failed: {exc}") from exc
        return self.build_uri(object_name)

    def get(self, path: str) -> bytes:
        object_name = self._normalize_path(path)
        try:
            response = self._client.get_object(self._bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as exc:
            raise StorageOperationError(f"minio get failed: {exc}") from exc

    def exists(self, path: str) -> bool:
        object_name = self._normalize_path(path)
        try:
            self._client.stat_object(self._bucket, object_name)
            return True
        except S3Error:
            return False

    def delete(self, path: str) -> None:
        object_name = self._normalize_path(path)
        try:
            self._client.remove_object(self._bucket, object_name)
        except S3Error as exc:
            raise StorageOperationError(f"minio delete failed: {exc}") from exc

    def list(self, prefix: str = "") -> list[str]:
        object_prefix = self._normalize_path(prefix)
        return [
            obj.object_name
            for obj in self._client.list_objects(self._bucket, prefix=object_prefix, recursive=True)
        ]

    def stat(self, path: str) -> dict[str, Any]:
        object_name = self._normalize_path(path)
        try:
            stat = self._client.stat_object(self._bucket, object_name)
        except S3Error as exc:
            raise StorageOperationError(f"minio stat failed: {exc}") from exc
        return {
            "size": stat.size,
            "etag": stat.etag,
            "last_modified": stat.last_modified,
        }

    def build_uri(self, path: str) -> str:
        return f"s3://{self._bucket}/{self._normalize_path(path)}"

    @property
    def bucket(self) -> str:
        return self._bucket

    def _ensure_bucket(self) -> None:
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
        except S3Error as exc:
            raise StorageOperationError(f"minio bucket check failed: {exc}") from exc

    @staticmethod
    def _normalize_path(path: str) -> str:
        return path.lstrip("/")
