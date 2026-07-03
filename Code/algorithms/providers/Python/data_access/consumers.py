from __future__ import annotations

from pathlib import Path
from typing import Any


def get_prepared_input_payload(
    datasource_selection: dict[str, object],
    dataset_names: tuple[str, ...],
) -> dict[str, Any] | None:
    prepared_inputs = datasource_selection.get("_prepared_inputs")
    if not isinstance(prepared_inputs, dict):
        return None
    for dataset_name in dataset_names:
        payload = prepared_inputs.get(dataset_name)
        if isinstance(payload, dict):
            return payload
    return None


def resolve_prepared_local_directory(
    datasource_selection: dict[str, object],
    dataset_names: tuple[str, ...],
    *,
    preferred_resource_keys: tuple[str, ...] = (),
) -> Path | None:
    prepared_input = get_prepared_input_payload(datasource_selection, dataset_names)
    if prepared_input is None:
        return None

    for resource in _iter_prepared_resources(prepared_input, preferred_resource_keys=preferred_resource_keys):
        if not isinstance(resource, dict):
            continue
        local_path = resource.get("local_path")
        if not local_path:
            continue
        path = Path(str(local_path))
        source_kind = str(resource.get("source_kind", ""))
        if source_kind == "local_dir":
            return path
        if path.exists() and path.is_dir():
            return path
    return None


def resolve_prepared_local_path(
    datasource_selection: dict[str, object],
    dataset_names: tuple[str, ...],
    *,
    preferred_resource_keys: tuple[str, ...] = (),
) -> Path | None:
    prepared_input = get_prepared_input_payload(datasource_selection, dataset_names)
    if prepared_input is None:
        return None

    for resource in _iter_prepared_resources(prepared_input, preferred_resource_keys=preferred_resource_keys):
        if not isinstance(resource, dict):
            continue
        local_path = resource.get("local_path")
        if local_path:
            return Path(str(local_path))
    return None


def _iter_prepared_resources(
    prepared_input: dict[str, Any],
    *,
    preferred_resource_keys: tuple[str, ...] = (),
) -> tuple[dict[str, Any], ...]:
    resources = tuple(
        resource
        for resource in list(prepared_input.get("materialized_resources", ())) + list(prepared_input.get("resources", ()))
        if isinstance(resource, dict)
    )
    if not preferred_resource_keys:
        return resources
    preferred = tuple(
        resource for resource in resources if _matches_preferred_resource_key(resource, preferred_resource_keys)
    )
    if preferred:
        remaining = tuple(resource for resource in resources if resource not in preferred)
        return preferred + remaining
    return resources


def _matches_preferred_resource_key(resource: dict[str, Any], preferred_resource_keys: tuple[str, ...]) -> bool:
    metadata = resource.get("metadata")
    if not isinstance(metadata, dict):
        return False
    preferred = {key.lower() for key in preferred_resource_keys}
    for metadata_key in ("target_key", "source_key", "role", "consumer_key"):
        value = metadata.get(metadata_key)
        if isinstance(value, str) and value.lower() in preferred:
            return True
    return False
