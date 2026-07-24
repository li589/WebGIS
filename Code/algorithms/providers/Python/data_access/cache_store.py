"""CacheStore with optional TTL for static materialize entries.

BACKEND_STATIC_CACHE_TTL_SECONDS=0 (default) means never expire.
"""

from __future__ import annotations

import os
import shutil
import time
from hashlib import sha256
from pathlib import Path

from data_access.contracts import ResourceRef, build_resource_ref


def _ttl_seconds() -> int:
    raw = os.getenv("BACKEND_STATIC_CACHE_TTL_SECONDS", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


class CacheStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def build_cache_key(self, resource: ResourceRef) -> str:
        # Prefer HTTP-aware key when headers are present (align with HttpSource)
        headers = {}
        raw = (resource.metadata or {}).get("http_headers")
        if isinstance(raw, dict):
            headers = {
                str(k): str(v) for k, v in raw.items() if str(k).strip() and str(v)
            }
        if headers:
            from data_access.sources.http import build_http_cache_key

            key = build_http_cache_key(resource.uri, headers)
        else:
            key = sha256(resource.uri.encode("utf-8")).hexdigest()
        suffix = ""
        if resource.format:
            suffix = f".{resource.format}"
        return f"{key}{suffix}"

    def resolve_cache_path(self, resource: ResourceRef) -> Path:
        return self.root_dir / self.build_cache_key(resource)

    def _is_fresh(self, cache_path: Path) -> bool:
        if not cache_path.exists():
            return False
        ttl = _ttl_seconds()
        if ttl <= 0:
            return True
        try:
            age = time.time() - cache_path.stat().st_mtime
        except OSError:
            return False
        return age <= ttl

    def has(self, resource: ResourceRef) -> bool:
        path = self.resolve_cache_path(resource)
        return self._is_fresh(path)

    def get(self, resource: ResourceRef) -> ResourceRef | None:
        cache_path = self.resolve_cache_path(resource)
        if not self._is_fresh(cache_path):
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
