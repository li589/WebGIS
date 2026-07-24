from __future__ import annotations

from data_access.contracts import DataRequestV2, ResourceRef, normalize_format


class Resolver:
    def resolve(
        self,
        request: DataRequestV2,
        resources: tuple[ResourceRef, ...] | list[ResourceRef],
    ) -> tuple[ResourceRef, ...]:
        selected = tuple(
            resource
            for resource in resources
            if self._matches_request(request, resource)
        )
        if not selected:
            return ()
        if request.preferred_format is None:
            return selected
        preferred_format = normalize_format(request.preferred_format)
        preferred = tuple(
            resource for resource in selected if resource.format == preferred_format
        )
        fallback = tuple(
            resource for resource in selected if resource.format != preferred_format
        )
        return preferred + fallback

    @staticmethod
    def _matches_request(request: DataRequestV2, resource: ResourceRef) -> bool:
        if request.logical_type and resource.logical_type != request.logical_type:
            return False
        if request.accepted_formats:
            accepted = {normalize_format(value) for value in request.accepted_formats}
            if resource.format not in accepted:
                return False
        if request.source_hints and resource.source_kind not in set(
            request.source_hints
        ):
            return False
        return True
