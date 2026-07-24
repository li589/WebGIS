from __future__ import annotations

from typing import Any, Iterable

from data_access.contracts import DataRequestV2, ResourceRef
from data_access.registry import SourceRegistry


class Locator:
    def __init__(self, source_registry: SourceRegistry) -> None:
        self.source_registry = source_registry

    def locate(self, request: DataRequestV2) -> tuple[ResourceRef, ...]:
        candidates = self._extract_candidates(request)
        return tuple(
            self.source_registry.locate(
                candidate["uri"], request=request, metadata=candidate.get("metadata")
            )
            for candidate in candidates
        )

    @staticmethod
    def _extract_candidates(request: DataRequestV2) -> list[dict[str, Any]]:
        raw_uris = request.selector.get("uris", ())
        if not raw_uris:
            return []
        candidates: list[dict[str, Any]] = []
        for value in raw_uris:
            if isinstance(value, str):
                candidates.append({"uri": value, "metadata": {}})
                continue
            if isinstance(value, dict):
                uri = str(value["uri"])
                metadata = dict(value.get("metadata", {}))
                candidates.append({"uri": uri, "metadata": metadata})
                continue
            raise TypeError(f"Unsupported selector uri entry: {type(value)!r}")
        return candidates

    def locate_from_uris(
        self,
        uris: Iterable[str],
        *,
        request: DataRequestV2 | None = None,
    ) -> tuple[ResourceRef, ...]:
        resolved_request = request or DataRequestV2(dataset_name="ad_hoc")
        return tuple(
            self.source_registry.locate(uri, request=resolved_request) for uri in uris
        )
