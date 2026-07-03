from __future__ import annotations

from pathlib import Path

from data_access.contracts import DataRequestV2, ResourceRef, build_resource_ref, is_probable_windows_path, normalize_local_path


class LocalFileSource:
    name = "local_fs"
    supported_schemes = ("local", "file")

    def can_handle(self, uri: str) -> bool:
        return is_probable_windows_path(uri) or uri.startswith("file://") or "://" not in uri

    def locate(
        self,
        uri: str,
        *,
        request: DataRequestV2 | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ResourceRef:
        _ = request
        local_path = Path(normalize_local_path(uri))
        source_kind = "local_dir" if self._looks_like_directory(local_path) else "local_file"
        return build_resource_ref(
            uri=str(local_path),
            source_kind=source_kind,
            local_path=str(local_path),
            metadata=dict(metadata or {}),
        )

    def materialize(
        self,
        resource: ResourceRef,
        *,
        target_dir: Path | None = None,
    ) -> ResourceRef:
        _ = target_dir
        local_path = Path(resource.local_path or normalize_local_path(resource.uri))
        if not local_path.exists():
            raise FileNotFoundError(f"Local resource does not exist: {local_path}")
        source_kind = "local_dir" if local_path.is_dir() else "local_file"
        return build_resource_ref(
            uri=str(local_path.resolve()),
            source_kind=source_kind,
            format=resource.format,
            logical_type=resource.logical_type,
            local_path=str(local_path.resolve()),
            metadata=resource.metadata,
        )

    @staticmethod
    def _looks_like_directory(path: Path) -> bool:
        if path.exists():
            return path.is_dir()
        return path.suffix == ""
