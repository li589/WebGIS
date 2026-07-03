from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

from data_access.contracts import ResourceRef, build_resource_ref


class CacheStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def build_cache_key(self, resource: ResourceRef) -> str:
        digest = sha256(resource.uri.encode("utf-8")).hexdigest()
        suffix = ""
        if resource.format:
            suffix = f".{resource.format}"
        return f"{digest}{suffix}"

    def resolve_cache_path(self, resource: ResourceRef) -> Path:
        return self.root_dir / self.build_cache_key(resource)

    def has(self, resource: ResourceRef) -> bool:
        return self.resolve_cache_path(resource).exists()

    def get(self, resource: ResourceRef) -> ResourceRef | None:
        cache_path = self.resolve_cache_path(resource)
        if not cache_path.exists():
            return None
        return build_resource_ref(
            uri=f"cache://materialized/{cache_path.name}",
            source_kind="cache",
            format=resource.format,
            logical_type=resource.logical_type,
            storage_backend="cache",
            local_path=str(cache_path.resolve()),
            metadata={
                "cache_key": cache_path.name,
                "origin_uri": resource.uri,
            },
        )

    def put_file(self, resource: ResourceRef, source_path: str | Path) -> ResourceRef:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Fetch source does not exist: {source}")
        target_path = self.resolve_cache_path(resource)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_path)
        return build_resource_ref(
            uri=f"cache://materialized/{target_path.name}",
            source_kind="cache",
            format=resource.format,
            logical_type=resource.logical_type,
            storage_backend="cache",
            local_path=str(target_path.resolve()),
            metadata={
                "cache_key": target_path.name,
                "origin_uri": resource.uri,
            },
        )
