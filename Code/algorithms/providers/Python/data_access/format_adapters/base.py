from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
from typing import Any, Protocol

from data_access.contracts import ResourceRef, normalize_format


class FormatAdapter(Protocol):
    name: str
    supported_formats: tuple[str, ...]

    def can_handle(self, resource: ResourceRef) -> bool:
        ...

    def probe(self, resource: ResourceRef) -> bool:
        ...

    def load(self, resource: ResourceRef) -> Any:
        ...

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: str | Path | None = None,
    ) -> ResourceRef:
        ...


class LocalFileFormatAdapter:
    name = "local_file"
    supported_formats: tuple[str, ...] = ()

    def can_handle(self, resource: ResourceRef) -> bool:
        return normalize_format(resource.format) in set(self.supported_formats)

    def probe(self, resource: ResourceRef) -> bool:
        if not self.can_handle(resource):
            return False
        local_path = self._require_local_path(resource)
        return local_path.is_file()

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: str | Path | None = None,
    ) -> ResourceRef:
        source_path = self._require_local_path(resource)
        if target_dir is None:
            return replace(resource, local_path=str(source_path))
        destination_dir = Path(target_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination_path = destination_dir / source_path.name
        if source_path.resolve() != destination_path.resolve():
            shutil.copy2(source_path, destination_path)
        return replace(resource, local_path=str(destination_path))

    @staticmethod
    def _require_local_path(resource: ResourceRef) -> Path:
        if not resource.local_path:
            raise ValueError(f"Resource '{resource.uri}' is not materialized locally")
        return Path(resource.local_path)
