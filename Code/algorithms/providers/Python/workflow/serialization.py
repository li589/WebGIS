from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from workflow.graph import WorkflowDefinition, WorkflowEdge, WorkflowNodeSpec, WorkflowOutputSpec
from workflow.schemas import InputSourceSpec


WORKFLOW_DEFINITION_JSON_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "WorkflowDefinition",
    "type": "object",
    "additionalProperties": False,
    "required": ["workflow_id", "nodes", "outputs"],
    "properties": {
        "workflow_id": {"type": "string", "minLength": 1},
        "version": {"type": "string", "default": "1.0"},
        "name": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "inputs": {
            "type": "object",
            "default": {},
            "additionalProperties": {"$ref": "#/$defs/InputSourceSpec"},
        },
        "nodes": {
            "type": "array",
            "items": {"$ref": "#/$defs/WorkflowNodeSpec"},
        },
        "edges": {
            "type": "array",
            "default": [],
            "items": {"$ref": "#/$defs/WorkflowEdge"},
        },
        "outputs": {
            "type": "array",
            "items": {"$ref": "#/$defs/WorkflowOutputSpec"},
        },
        "defaults": {
            "type": "object",
            "default": {},
            "additionalProperties": True,
        },
        "metadata": {
            "type": "object",
            "default": {},
            "additionalProperties": True,
        },
    },
    "$defs": {
        "InputSourceSpec": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source_type", "format"],
            "properties": {
                "source_type": {"type": "string", "minLength": 1},
                "format": {"type": "string", "minLength": 1},
                "path": {"type": ["string", "null"]},
                "pattern": {"type": ["string", "null"]},
                "field_map": {
                    "type": "object",
                    "default": {},
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "selector": {
                    "type": "object",
                    "default": {},
                    "additionalProperties": True,
                },
                "options": {
                    "type": "object",
                    "default": {},
                    "additionalProperties": True,
                },
            },
        },
        "WorkflowNodeSpec": {
            "type": "object",
            "additionalProperties": False,
            "required": ["node_id", "node_type"],
            "properties": {
                "node_id": {"type": "string", "minLength": 1},
                "node_type": {"type": "string", "minLength": 1},
                "version": {"type": "string", "default": "1.0"},
                "label": {"type": ["string", "null"]},
                "input_bindings": {
                    "type": "object",
                    "default": {},
                    "additionalProperties": {"type": "string"},
                },
                "params": {
                    "type": "object",
                    "default": {},
                    "additionalProperties": True,
                },
                "cache_policy": {
                    "type": ["object", "null"],
                    "additionalProperties": True,
                },
                "retry_policy": {
                    "type": ["object", "null"],
                    "additionalProperties": True,
                },
                "enabled": {"type": "boolean", "default": True},
            },
        },
        "WorkflowEdge": {
            "type": "object",
            "additionalProperties": False,
            "required": ["from_node", "from_port", "to_node", "to_port"],
            "properties": {
                "from_node": {"type": "string", "minLength": 1},
                "from_port": {"type": "string", "minLength": 1},
                "to_node": {"type": "string", "minLength": 1},
                "to_port": {"type": "string", "minLength": 1},
            },
        },
        "WorkflowOutputSpec": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "source"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "source": {"type": "string", "minLength": 1},
            },
        },
    },
}


class WorkflowDefinitionDecodeError(ValueError):
    """Raised when a JSON-like workflow payload cannot be converted."""


def get_workflow_definition_json_schema() -> dict[str, object]:
    return deepcopy(WORKFLOW_DEFINITION_JSON_SCHEMA)


def coerce_workflow_definition(value: object) -> WorkflowDefinition:
    if isinstance(value, WorkflowDefinition):
        return value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkflowDefinitionDecodeError(f"workflow_definition JSON decode failed: {exc.msg}") from exc
        if not isinstance(payload, Mapping):
            raise WorkflowDefinitionDecodeError("workflow_definition JSON payload must decode to an object")
        return workflow_definition_from_mapping(payload)
    if isinstance(value, Mapping):
        return workflow_definition_from_mapping(value)
    raise TypeError(
        "workflow_definition must be a WorkflowDefinition, a JSON object mapping, or a JSON string payload"
    )


def workflow_definition_from_mapping(payload: Mapping[str, object]) -> WorkflowDefinition:
    _reject_unknown_fields(
        payload,
        {"workflow_id", "version", "name", "description", "inputs", "nodes", "edges", "outputs", "defaults", "metadata"},
        path="workflow_definition",
    )
    workflow_id = _require_string(payload, "workflow_id", "workflow_definition")
    version = _optional_string(payload, "version", "workflow_definition.version") or "1.0"
    name = _optional_string(payload, "name", "workflow_definition.name")
    description = _optional_string(payload, "description", "workflow_definition.description")
    inputs_payload = _optional_mapping(payload, "inputs", "workflow_definition.inputs", default={})
    nodes_payload = _require_list(payload, "nodes", "workflow_definition")
    edges_payload = _optional_list(payload, "edges", "workflow_definition.edges", default=[])
    outputs_payload = _require_list(payload, "outputs", "workflow_definition")
    defaults = _optional_mapping(payload, "defaults", "workflow_definition.defaults", default={})
    metadata = _optional_mapping(payload, "metadata", "workflow_definition.metadata", default={})

    inputs = {
        input_name: _parse_input_source_spec(input_value, path=f"workflow_definition.inputs.{input_name}")
        for input_name, input_value in inputs_payload.items()
    }
    nodes = [
        _parse_workflow_node_spec(node_payload, path=f"workflow_definition.nodes[{index}]")
        for index, node_payload in enumerate(nodes_payload)
    ]
    edges = [
        _parse_workflow_edge(edge_payload, path=f"workflow_definition.edges[{index}]")
        for index, edge_payload in enumerate(edges_payload)
    ]
    outputs = [
        _parse_workflow_output_spec(output_payload, path=f"workflow_definition.outputs[{index}]")
        for index, output_payload in enumerate(outputs_payload)
    ]

    return WorkflowDefinition(
        workflow_id=workflow_id,
        version=version,
        name=name,
        description=description,
        inputs=inputs,
        nodes=nodes,
        edges=edges,
        outputs=outputs,
        defaults=dict(defaults),
        metadata=dict(metadata),
    )


def _parse_input_source_spec(value: object, *, path: str) -> InputSourceSpec:
    payload = _as_mapping(value, path)
    _reject_unknown_fields(
        payload,
        {"source_type", "format", "path", "pattern", "field_map", "selector", "options"},
        path=path,
    )
    field_map_payload = _optional_mapping(payload, "field_map", f"{path}.field_map", default={})
    return InputSourceSpec(
        source_type=_require_string(payload, "source_type", path),
        format=_require_string(payload, "format", path),
        path=_optional_string(payload, "path", f"{path}.path"),
        pattern=_optional_string(payload, "pattern", f"{path}.pattern"),
        field_map={
            alias_name: _as_string_list(alias_value, path=f"{path}.field_map.{alias_name}")
            for alias_name, alias_value in field_map_payload.items()
        },
        selector=dict(_optional_mapping(payload, "selector", f"{path}.selector", default={})),
        options=dict(_optional_mapping(payload, "options", f"{path}.options", default={})),
    )


def _parse_workflow_node_spec(value: object, *, path: str) -> WorkflowNodeSpec:
    payload = _as_mapping(value, path)
    _reject_unknown_fields(
        payload,
        {
            "node_id",
            "node_type",
            "version",
            "label",
            "input_bindings",
            "params",
            "cache_policy",
            "retry_policy",
            "enabled",
        },
        path=path,
    )
    return WorkflowNodeSpec(
        node_id=_require_string(payload, "node_id", path),
        node_type=_require_string(payload, "node_type", path),
        version=_optional_string(payload, "version", f"{path}.version") or "1.0",
        label=_optional_string(payload, "label", f"{path}.label"),
        input_bindings=_as_string_mapping(
            _optional_mapping(payload, "input_bindings", f"{path}.input_bindings", default={}),
            path=f"{path}.input_bindings",
        ),
        params=dict(_optional_mapping(payload, "params", f"{path}.params", default={})),
        cache_policy=_optional_mapping_or_none(payload, "cache_policy", f"{path}.cache_policy"),
        retry_policy=_optional_mapping_or_none(payload, "retry_policy", f"{path}.retry_policy"),
        enabled=_optional_bool(payload, "enabled", f"{path}.enabled", default=True),
    )


def _parse_workflow_edge(value: object, *, path: str) -> WorkflowEdge:
    payload = _as_mapping(value, path)
    _reject_unknown_fields(payload, {"from_node", "from_port", "to_node", "to_port"}, path=path)
    return WorkflowEdge(
        from_node=_require_string(payload, "from_node", path),
        from_port=_require_string(payload, "from_port", path),
        to_node=_require_string(payload, "to_node", path),
        to_port=_require_string(payload, "to_port", path),
    )


def _parse_workflow_output_spec(value: object, *, path: str) -> WorkflowOutputSpec:
    payload = _as_mapping(value, path)
    _reject_unknown_fields(payload, {"name", "source"}, path=path)
    return WorkflowOutputSpec(
        name=_require_string(payload, "name", path),
        source=_require_string(payload, "source", path),
    )


def _require_string(payload: Mapping[str, object], key: str, path: str) -> str:
    if key not in payload:
        raise WorkflowDefinitionDecodeError(f"Missing required field: {path}.{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise WorkflowDefinitionDecodeError(f"Field must be a non-empty string: {path}.{key}")
    return value


def _optional_string(payload: Mapping[str, object], key: str, path: str) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str):
        raise WorkflowDefinitionDecodeError(f"Field must be a string or null: {path}")
    return value


def _optional_bool(payload: Mapping[str, object], key: str, path: str, *, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise WorkflowDefinitionDecodeError(f"Field must be a boolean: {path}")
    return value


def _require_list(payload: Mapping[str, object], key: str, path: str) -> list[object]:
    if key not in payload:
        raise WorkflowDefinitionDecodeError(f"Missing required field: {path}.{key}")
    return _as_list(payload[key], f"{path}.{key}")


def _optional_list(payload: Mapping[str, object], key: str, path: str, *, default: list[object]) -> list[object]:
    if key not in payload or payload[key] is None:
        return list(default)
    return _as_list(payload[key], path)


def _optional_mapping(
    payload: Mapping[str, object],
    key: str,
    path: str,
    *,
    default: Mapping[str, object],
) -> dict[str, object]:
    if key not in payload or payload[key] is None:
        return dict(default)
    return dict(_as_mapping(payload[key], path))


def _optional_mapping_or_none(
    payload: Mapping[str, object],
    key: str,
    path: str,
) -> dict[str, object] | None:
    if key not in payload or payload[key] is None:
        return None
    return dict(_as_mapping(payload[key], path))


def _as_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WorkflowDefinitionDecodeError(f"Field must be an object: {path}")
    for key in value.keys():
        if not isinstance(key, str):
            raise WorkflowDefinitionDecodeError(f"Object keys must be strings: {path}")
    return value


def _as_list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkflowDefinitionDecodeError(f"Field must be an array: {path}")
    return value


def _as_string_list(value: object, *, path: str) -> list[str]:
    items = _as_list(value, path)
    result: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise WorkflowDefinitionDecodeError(f"Array item must be a string: {path}[{index}]")
        result.append(item)
    return result


def _as_string_mapping(value: Mapping[str, object], *, path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise WorkflowDefinitionDecodeError(f"Mapping value must be a string binding: {path}.{key}")
        result[key] = item
    return result


def _reject_unknown_fields(payload: Mapping[str, object], allowed_keys: set[str], *, path: str) -> None:
    unknown_keys = sorted(key for key in payload.keys() if key not in allowed_keys)
    if unknown_keys:
        unknown_text = ", ".join(unknown_keys)
        raise WorkflowDefinitionDecodeError(f"Unknown field(s) not allowed: {path} -> {unknown_text}")
