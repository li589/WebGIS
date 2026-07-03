from __future__ import annotations

from pathlib import Path

from data_access.cache_store import CacheStore
from data_access.contracts import DataRequestV2, ResourceRef


class Fetcher:
    def __init__(self, cache_store: CacheStore) -> None:
        self.cache_store = cache_store

    def fetch(self, request: DataRequestV2, resource: ResourceRef) -> tuple[ResourceRef, bool]:
        if resource.local_path:
            return resource, False

        if request.allow_cache:
            cached = self.cache_store.get(resource)
            if cached is not None:
                return cached, True

        source_path = self._resolve_mock_source_path(resource)
        if source_path is None:
            return resource, False

        fetched = self.cache_store.put_file(resource, source_path)
        return fetched, False

    @staticmethod
    def _resolve_mock_source_path(resource: ResourceRef) -> str | None:
        for key in ("mock_local_path", "source_local_path", "download_path"):
            value = resource.metadata.get(key)
            if value:
                return str(value)
        return None

    def fetch_many(
        self,
        request: DataRequestV2,
        resources: tuple[ResourceRef, ...] | list[ResourceRef],
    ) -> tuple[tuple[ResourceRef, ...], tuple[str, ...]]:
        fetched_resources: list[ResourceRef] = []
        cache_hits: list[str] = []
        for resource in resources:
            fetched, hit = self.fetch(request, resource)
            fetched_resources.append(fetched)
            if hit:
                cache_hits.append(resource.uri)
        return tuple(fetched_resources), tuple(cache_hits)
