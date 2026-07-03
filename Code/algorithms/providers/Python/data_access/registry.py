from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable
from urllib.parse import urlparse

from data_access.contracts import DataRequestV2, ResourceRef, SourceAdapter, is_probable_windows_path


_SCHEME_PATTERN = re.compile(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*):")


def infer_uri_scheme(uri: str) -> str:
    if is_probable_windows_path(uri):
        return "local"
    if uri.startswith("file://"):
        return "file"
    if "://" not in uri:
        match = _SCHEME_PATTERN.match(uri)
        if match is None:
            return "local"
    parsed = urlparse(uri)
    return parsed.scheme.lower() or "local"


@dataclass(slots=True)
class SourceMatch:
    scheme: str
    adapter: SourceAdapter


class SourceRegistry:
    def __init__(self) -> None:
        self._adapters_by_name: dict[str, SourceAdapter] = {}
        self._adapters_by_scheme: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        self._adapters_by_name[adapter.name] = adapter
        for scheme in adapter.supported_schemes:
            self._adapters_by_scheme[scheme.lower()] = adapter

    def register_many(self, adapters: Iterable[SourceAdapter]) -> None:
        for adapter in adapters:
            self.register(adapter)

    def get(self, name: str) -> SourceAdapter:
        return self._adapters_by_name[name]

    def find_for_uri(self, uri: str) -> SourceMatch:
        scheme = infer_uri_scheme(uri)
        adapter = self._adapters_by_scheme.get(scheme)
        if adapter is None:
            raise KeyError(f"No data source adapter registered for scheme '{scheme}'")
        return SourceMatch(scheme=scheme, adapter=adapter)

    def locate(
        self,
        uri: str,
        *,
        request: DataRequestV2 | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ResourceRef:
        match = self.find_for_uri(uri)
        return match.adapter.locate(uri, request=request, metadata=metadata)

    def materialize(self, resource: ResourceRef) -> ResourceRef:
        match = self.find_for_uri(resource.uri)
        return match.adapter.materialize(resource)

    def registered_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters_by_name))

    def registered_schemes(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters_by_scheme))


def build_default_source_registry() -> SourceRegistry:
    from data_access.sources.cache import CacheSource
    from data_access.sources.http import HttpSource
    from data_access.sources.local_fs import LocalFileSource
    from data_access.sources.minio import MinioSource

    registry = SourceRegistry()
    registry.register_many(
        [
            LocalFileSource(),
            HttpSource(),
            MinioSource(),
            CacheSource(),
        ]
    )
    return registry
