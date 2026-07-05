from __future__ import annotations

from pathlib import Path
from typing import Any

from webgis_gee.runtime.exceptions import StorageOperationError
from webgis_gee.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    """本地文件系统存储后端。"""

    def __init__(self, base_path: str = "./artifacts") -> None:
        self._base_path = Path(base_path).resolve()
        self._base_path.mkdir(parents=True, exist_ok=True)

    def put(self, path: str, content: bytes) -> str:
        full_path = self._full_path(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        return f"file://{full_path}"

    def get(self, path: str) -> bytes:
        full_path = self._full_path(path)
        return full_path.read_bytes()

    def exists(self, path: str) -> bool:
        return self._full_path(path).exists()

    def delete(self, path: str) -> None:
        full_path = self._full_path(path)
        full_path.unlink(missing_ok=True)

    def list(self, prefix: str = "") -> list[str]:
        base_dir = self._full_path(prefix or ".")
        if not base_dir.exists():
            return []
        if base_dir.is_file():
            return [base_dir.relative_to(self._base_path).as_posix()]
        files = []
        for f in base_dir.rglob("*"):
            if f.is_file():
                files.append(f.relative_to(self._base_path).as_posix())
        return files

    def stat(self, path: str) -> dict[str, Any]:
        full_path = self._full_path(path)
        stat = full_path.stat()
        return {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }

    def build_uri(self, path: str) -> str:
        return f"file://{self._full_path(path)}"

    @property
    def base_path(self) -> Path:
        return self._base_path

    def _full_path(self, path: str) -> Path:
        safe_path = Path(path.lstrip("/\\"))
        full_path = (self._base_path / safe_path).resolve()
        try:
            full_path.relative_to(self._base_path)
        except ValueError as exc:
            raise StorageOperationError(f"path escapes storage root: {path}") from exc
        return full_path
