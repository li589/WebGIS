from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.parse import urlparse

from webgis_gee.config.settings import Settings
from webgis_gee.runtime.resources import RuntimeResourceController
from webgis_gee.storage.base import StorageBackend
from webgis_gee.storage.factory import create_storage_backend
from webgis_gee.storage.local import LocalStorageBackend
from webgis_gee.storage.minio import MinioStorageBackend


MANIFEST_STORAGE_PREFIX = "exports"


class GeeExportTaskService:
    """Polls export task state from manifest snapshots and optional EE runtime."""

    def __init__(
        self,
        settings: Settings | None = None,
        storage_backend: StorageBackend | None = None,
        resource_controller: RuntimeResourceController | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._storage_backend = storage_backend
        self._resource_controller = resource_controller

    def poll_task(
        self,
        manifest_uri: str | None = None,
        task_ref: dict[str, Any] | None = None,
        gee_module: Any | None = None,
        update_manifest: bool = True,
    ) -> dict[str, Any]:
        manifest_payload: dict[str, Any] | None = None
        if manifest_uri is not None:
            manifest_payload = self._load_manifest(manifest_uri)
            task_ref = task_ref or manifest_payload.get("task_ref")

        if task_ref is None:
            raise ValueError("must provide manifest_uri or task_ref")

        polled_at = datetime.now(timezone.utc).isoformat()
        status_payload = self._build_status_payload(
            task_ref=task_ref, gee_module=gee_module
        )
        status_payload["polled_at"] = polled_at
        status_payload["manifest_uri"] = manifest_uri or task_ref.get("manifest_uri")

        if manifest_payload is not None and update_manifest:
            manifest_payload["task_ref"] = {
                **manifest_payload.get("task_ref", {}),
                "status": status_payload["status"],
                "last_polled_at": polled_at,
            }
            manifest_payload["task_status"] = status_payload
            self._save_manifest(manifest_uri, manifest_payload)

        return status_payload

    def _build_status_payload(
        self,
        task_ref: dict[str, Any],
        gee_module: Any | None,
    ) -> dict[str, Any]:
        task_id = task_ref.get("task_id")
        started = bool(task_ref.get("started"))
        if not started:
            return {
                "status": task_ref.get("status", "manifest_created"),
                "state": "LOCAL_ONLY",
                "task_id": task_id,
                "started": False,
                "raw": None,
            }

        if not task_id:
            return {
                "status": task_ref.get("status", "submitted"),
                "state": "SUBMITTED",
                "task_id": None,
                "started": True,
                "raw": None,
            }

        if gee_module is None:
            return {
                "status": task_ref.get("status", "submitted"),
                "state": "SUBMITTED",
                "task_id": task_id,
                "started": True,
                "raw": None,
            }

        raw_status = self._fetch_task_status(gee_module=gee_module, task_id=task_id)
        state = str(raw_status.get("state", "UNKNOWN")).upper()
        return {
            "status": self._normalize_status(state),
            "state": state,
            "task_id": task_id,
            "started": True,
            "error_message": raw_status.get("error_message")
            or raw_status.get("error_message".upper()),
            "raw": raw_status,
        }

    @staticmethod
    def _fetch_task_status(gee_module: Any, task_id: str) -> dict[str, Any]:
        status_result = gee_module.data.getTaskStatus(task_id)
        if isinstance(status_result, list):
            if not status_result:
                return {"state": "UNKNOWN"}
            first = status_result[0]
            return first if isinstance(first, dict) else {"state": str(first)}
        if isinstance(status_result, dict):
            return status_result
        return {"state": str(status_result)}

    @staticmethod
    def _normalize_status(state: str) -> str:
        if state in {"COMPLETED", "SUCCEEDED"}:
            return "completed"
        if state in {"FAILED", "CANCELLED", "CANCELED"}:
            return "failed"
        if state in {"RUNNING", "READY", "PENDING"}:
            return "running"
        return "unknown"

    def _load_manifest(self, manifest_uri: str) -> dict[str, Any]:
        payload = self._read_uri_bytes(manifest_uri)
        return json.loads(payload.decode("utf-8"))

    def _save_manifest(self, manifest_uri: str | None, payload: dict[str, Any]) -> None:
        if manifest_uri is None:
            return
        body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
        self._write_uri_bytes(manifest_uri, body)

    def _read_uri_bytes(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            owner_id = self._resource_owner_id(uri)
            if self._resource_controller is not None:
                with self._resource_controller.download_slot(run_id=owner_id):
                    return self._file_uri_to_path(uri).read_bytes()
            return self._file_uri_to_path(uri).read_bytes()
        if parsed.scheme == "s3":
            backend = self._resolve_backend(parsed.scheme)
            bucket, path = self._parse_s3_uri(uri)
            self._ensure_bucket_matches(backend, bucket)
            owner_id = self._resource_owner_id(uri)
            if self._resource_controller is not None:
                with self._resource_controller.download_slot(run_id=owner_id):
                    return backend.get(path)
            return backend.get(path)
        raise ValueError(f"unsupported manifest uri scheme: {parsed.scheme}")

    def _write_uri_bytes(self, uri: str, content: bytes) -> None:
        parsed = urlparse(uri)
        if parsed.scheme == "file":
            owner_id = self._resource_owner_id(uri)
            target_path = self._file_uri_to_path(uri)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if self._resource_controller is not None:
                with self._resource_controller.upload_slot(run_id=owner_id):
                    with self._resource_controller.transient_local_write(
                        byte_count=len(content)
                    ):
                        self._atomic_write_file(target_path, content)
                    return
            self._atomic_write_file(target_path, content)
            return
        if parsed.scheme == "s3":
            backend = self._resolve_backend(parsed.scheme)
            bucket, path = self._parse_s3_uri(uri)
            self._ensure_bucket_matches(backend, bucket)
            owner_id = self._resource_owner_id(uri)
            if self._resource_controller is not None:
                with self._resource_controller.upload_slot(run_id=owner_id):
                    backend.put(path, content)
                    return
            backend.put(path, content)
            return
        raise ValueError(f"unsupported manifest uri scheme: {parsed.scheme}")

    def _resolve_backend(self, scheme: str) -> StorageBackend:
        if self._storage_backend is not None:
            return self._storage_backend
        if scheme == "s3":
            return create_storage_backend(self._settings, backend_type="minio")
        return create_storage_backend(self._settings)

    @staticmethod
    def _parse_s3_uri(uri: str) -> tuple[str, str]:
        parsed = urlparse(uri)
        if parsed.scheme != "s3":
            raise ValueError(f"unsupported manifest uri scheme: {parsed.scheme}")
        bucket = parsed.netloc
        path = parsed.path.lstrip("/")
        if not bucket or not path:
            raise ValueError(f"invalid s3 manifest uri: {uri}")
        if not path.startswith(f"{MANIFEST_STORAGE_PREFIX}/"):
            raise ValueError(
                "s3 manifest uri must stay within the managed exports/ prefix"
            )
        return bucket, path

    @staticmethod
    def _ensure_bucket_matches(backend: StorageBackend, bucket: str) -> None:
        if not isinstance(backend, MinioStorageBackend):
            raise ValueError("s3 manifest uri requires MinIO storage backend")
        if backend.bucket != bucket:
            raise ValueError(
                f"manifest uri bucket {bucket} does not match configured backend bucket {backend.bucket}"
            )

    def _file_uri_to_path(self, uri: str) -> Path:
        raw_path = Path(uri.removeprefix("file://"))
        if not raw_path.is_absolute():
            raise ValueError("file manifest uri must use an absolute path")
        resolved_path = raw_path.resolve(strict=False)
        local_storage_root = self._local_storage_root()
        try:
            relative_path = resolved_path.relative_to(local_storage_root)
        except ValueError as exc:
            raise ValueError(
                "file manifest uri must stay within the configured local storage root"
            ) from exc
        if not relative_path.parts or relative_path.parts[0] != MANIFEST_STORAGE_PREFIX:
            raise ValueError(
                "file manifest uri must stay within the managed exports directory"
            )
        return resolved_path

    def _local_storage_root(self) -> Path:
        if isinstance(self._storage_backend, LocalStorageBackend):
            return self._storage_backend.base_path
        return Path(self._settings.local_storage_root).resolve()

    @staticmethod
    def _resource_owner_id(uri: str) -> str:
        return uri

    @staticmethod
    def _atomic_write_file(path: Path, content: bytes) -> None:
        temp_file_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as temp_file:
                temp_file.write(content)
                temp_file_path = Path(temp_file.name)
            temp_file_path.replace(path)
        finally:
            if temp_file_path is not None and temp_file_path.exists():
                temp_file_path.unlink(missing_ok=True)
