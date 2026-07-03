from __future__ import annotations

from pathlib import Path

from data_access.contracts import DataRequestV2, ResourceRef
from data_access.registry import SourceRegistry


class Materializer:
    def __init__(self, source_registry: SourceRegistry) -> None:
        self.source_registry = source_registry

    def materialize(
        self,
        request: DataRequestV2,
        resource: ResourceRef,
        *,
        target_dir: str | Path | None = None,
    ) -> ResourceRef:
        resolved_target = None if target_dir is None else Path(target_dir)
        if request.materialization_mode == "memory":
            return resource
        return self.source_registry.materialize(resource) if resolved_target is None else self.source_registry.find_for_uri(resource.uri).adapter.materialize(resource, target_dir=resolved_target)

    def materialize_many(
        self,
        request: DataRequestV2,
        resources: tuple[ResourceRef, ...] | list[ResourceRef],
        *,
        target_dir: str | Path | None = None,
    ) -> tuple[ResourceRef, ...]:
        return tuple(self.materialize(request, resource, target_dir=target_dir) for resource in resources)
