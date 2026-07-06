from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import CachePolicy, RegionSpec, ResourceHint, TimeRange
from workflow.serialization import coerce_workflow_definition


JOB_REQUEST_JSON_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "JobRequest",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "job_id",
        "pipeline_name",
        "task_type",
        "time_range",
        "region",
        "datasource_selection",
        "algorithm_params",
    ],
    "properties": {
        "job_id": {"type": "string", "minLength": 1},
        "pipeline_name": {"type": "string", "minLength": 1},
        "task_type": {"type": "string", "minLength": 1},
        "time_range": {"$ref": "#/$defs/TimeRange"},
        "region": {"$ref": "#/$defs/RegionSpec"},
        "datasource_selection": {
            "type": "object",
            "default": {},
            "additionalProperties": True,
        },
        "algorithm_params": {
            "type": "object",
            "default": {},
            "additionalProperties": True,
        },
        "output_spec": {"$ref": "#/$defs/OutputSpec"},
        "resource_hint": {"anyOf": [{"$ref": "#/$defs/ResourceHint"}, {"type": "null"}]},
        "cache_policy": {"anyOf": [{"$ref": "#/$defs/CachePolicy"}, {"type": "null"}]},
        "resume_policy": {
            "type": ["object", "null"],
            "default": None,
            "additionalProperties": True,
        },
        "priority": {"type": ["integer", "null"], "default": None},
        "tags": {
            "type": "object",
            "default": {},
            "additionalProperties": {"type": "string"},
        },
        "module_name": {"type": ["string", "null"], "default": None},
        "workflow_name": {"type": ["string", "null"], "default": None},
        "workflow_definition": {
            "oneOf": [
                {"type": "object"},
                {"type": "string"},
                {"type": "null"},
            ],
            "default": None,
        },
    },
    "$defs": {
        "TimeRange": {
            "type": "object",
            "additionalProperties": False,
            "required": ["start", "end"],
            "properties": {
                "start": {"type": "string", "minLength": 1},
                "end": {"type": "string", "minLength": 1},
                "step": {"type": ["string", "null"], "default": None},
            },
        },
        "RegionSpec": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "value"],
            "properties": {
                "kind": {"type": "string", "minLength": 1},
                "value": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
        },
        "OutputSpec": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "raster_format": {"type": "string", "default": "COG"},
                "table_format": {"type": "string", "default": "parquet"},
                "include_qc": {"type": "boolean", "default": True},
                "include_manifest": {"type": "boolean", "default": True},
                "extra": {
                    "type": "object",
                    "default": {},
                    "additionalProperties": True,
                },
            },
        },
        "ResourceHint": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "cpu_cores": {"type": ["integer", "null"], "default": None},
                "memory_gb": {"type": ["number", "null"], "default": None},
                "gpu_count": {"type": ["integer", "null"], "default": None},
                "tmp_disk_gb": {"type": ["number", "null"], "default": None},
                "preferred_chunk_size": {"type": ["integer", "null"], "default": None},
            },
        },
        "CachePolicy": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {"type": "string", "default": "metadata_only"},
                "enabled": {"type": "boolean", "default": True},
            },
        },
    },
}


class JobRequestDecodeError(ValueError):
    """Raised when a JSON-like job request cannot be converted."""


def get_job_request_json_schema() -> dict[str, object]:
    return deepcopy(JOB_REQUEST_JSON_SCHEMA)


def coerce_job_request(value: object) -> JobRequest:
    if isinstance(value, JobRequest):
        return value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise JobRequestDecodeError(f"job_request JSON decode failed: {exc.msg}") from exc
        if not isinstance(payload, Mapping):
            raise JobRequestDecodeError("job_request JSON payload must decode to an object")
        return job_request_from_mapping(payload)
    if isinstance(value, Mapping):
        return job_request_from_mapping(value)
    raise TypeError("job_request must be a JobRequest, a JSON object mapping, or a JSON string payload")


def job_request_from_mapping(payload: Mapping[str, object]) -> JobRequest:
    _reject_unknown_fields(
        payload,
        {
            "job_id",
            "pipeline_name",
            "task_type",
            "time_range",
            "region",
            "datasource_selection",
            "algorithm_params",
            "output_spec",
            "resource_hint",
            "cache_policy",
            "resume_policy",
            "priority",
            "tags",
            "module_name",
            "workflow_name",
            "workflow_definition",
            "workflow_entry_name",
        },
        path="job_request",
    )
    return JobRequest(
        job_id=_require_string(payload, "job_id", "job_request"),
        pipeline_name=_require_string(payload, "pipeline_name", "job_request"),
        task_type=_require_string(payload, "task_type", "job_request"),
        time_range=_parse_time_range(_require_mapping(payload, "time_range", "job_request"), path="job_request.time_range"),
        region=_parse_region_spec(_require_mapping(payload, "region", "job_request"), path="job_request.region"),
        datasource_selection=dict(
            _require_mapping(payload, "datasource_selection", "job_request")
        ),
        algorithm_params=dict(_require_mapping(payload, "algorithm_params", "job_request")),
        output_spec=_parse_output_spec(
            _optional_mapping(payload, "output_spec", "job_request.output_spec", default={}),
            path="job_request.output_spec",
        ),
        resource_hint=_parse_resource_hint(
            _optional_mapping_or_none(payload, "resource_hint", "job_request.resource_hint"),
            path="job_request.resource_hint",
        ),
        cache_policy=_parse_cache_policy(
            _optional_mapping_or_none(payload, "cache_policy", "job_request.cache_policy"),
            path="job_request.cache_policy",
        ),
        resume_policy=_optional_mapping_or_none(payload, "resume_policy", "job_request.resume_policy"),
        priority=_optional_int(payload, "priority", "job_request.priority"),
        tags=_as_string_mapping(
            _optional_mapping(payload, "tags", "job_request.tags", default={}),
            path="job_request.tags",
        ),
        module_name=_optional_string(payload, "module_name", "job_request.module_name"),
        workflow_name=_optional_string(payload, "workflow_name", "job_request.workflow_name"),
        workflow_definition=_parse_workflow_definition(payload.get("workflow_definition")),
        workflow_entry_name=_optional_string(payload, "workflow_entry_name", "job_request.workflow_entry_name"),
    )


def _parse_time_range(payload: Mapping[str, object], *, path: str) -> TimeRange:
    _reject_unknown_fields(payload, {"start", "end", "step"}, path=path)
    start = _parse_datetime(_require_string(payload, "start", path), path=f"{path}.start")
    end = _parse_datetime(_require_string(payload, "end", path), path=f"{path}.end")
    step = _optional_string(payload, "step", f"{path}.step")
    if (start.tzinfo is None) != (end.tzinfo is None):
        raise JobRequestDecodeError(
            f"Fields must both include timezone info or both omit it: {path}.start, {path}.end"
        )
    if start > end:
        raise JobRequestDecodeError(f"Field must satisfy start <= end: {path}")
    return TimeRange(start=start, end=end, step=step)


def _parse_region_spec(payload: Mapping[str, object], *, path: str) -> RegionSpec:
    _reject_unknown_fields(payload, {"kind", "value"}, path=path)
    return RegionSpec(
        kind=_require_string(payload, "kind", path),
        value=dict(_require_mapping(payload, "value", path)),
    )


def _parse_output_spec(payload: Mapping[str, object], *, path: str) -> OutputSpec:
    _reject_unknown_fields(
        payload,
        {"raster_format", "table_format", "include_qc", "include_manifest", "extra"},
        path=path,
    )
    return OutputSpec(
        raster_format=_optional_string(payload, "raster_format", f"{path}.raster_format") or "COG",
        table_format=_optional_string(payload, "table_format", f"{path}.table_format") or "parquet",
        include_qc=_optional_bool(payload, "include_qc", f"{path}.include_qc", default=True),
        include_manifest=_optional_bool(payload, "include_manifest", f"{path}.include_manifest", default=True),
        extra=dict(_optional_mapping(payload, "extra", f"{path}.extra", default={})),
    )


def _parse_resource_hint(payload: Mapping[str, object] | None, *, path: str) -> ResourceHint | None:
    if payload is None:
        return None
    _reject_unknown_fields(
        payload,
        {"cpu_cores", "memory_gb", "gpu_count", "tmp_disk_gb", "preferred_chunk_size"},
        path=path,
    )
    return ResourceHint(
        cpu_cores=_optional_int(payload, "cpu_cores", f"{path}.cpu_cores"),
        memory_gb=_optional_number(payload, "memory_gb", f"{path}.memory_gb"),
        gpu_count=_optional_int(payload, "gpu_count", f"{path}.gpu_count"),
        tmp_disk_gb=_optional_number(payload, "tmp_disk_gb", f"{path}.tmp_disk_gb"),
        preferred_chunk_size=_optional_int(payload, "preferred_chunk_size", f"{path}.preferred_chunk_size"),
    )


def _parse_cache_policy(payload: Mapping[str, object] | None, *, path: str) -> CachePolicy | None:
    if payload is None:
        return None
    _reject_unknown_fields(payload, {"mode", "enabled"}, path=path)
    return CachePolicy(
        mode=_optional_string(payload, "mode", f"{path}.mode") or "metadata_only",
        enabled=_optional_bool(payload, "enabled", f"{path}.enabled", default=True),
    )


def _parse_workflow_definition(value: object) -> object | None:
    if value is None:
        return None
    return coerce_workflow_definition(value)


def _parse_datetime(value: str, *, path: str) -> datetime:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise JobRequestDecodeError(f"Field must be an ISO datetime string: {path}") from exc


def _require_string(payload: Mapping[str, object], key: str, path: str) -> str:
    if key not in payload:
        raise JobRequestDecodeError(f"Missing required field: {path}.{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise JobRequestDecodeError(f"Field must be a non-empty string: {path}.{key}")
    return value


def _optional_string(payload: Mapping[str, object], key: str, path: str) -> str | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, str):
        raise JobRequestDecodeError(f"Field must be a string or null: {path}")
    return value


def _optional_bool(payload: Mapping[str, object], key: str, path: str, *, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise JobRequestDecodeError(f"Field must be a boolean: {path}")
    return value


def _optional_int(payload: Mapping[str, object], key: str, path: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise JobRequestDecodeError(f"Field must be an integer or null: {path}")
    return value


def _optional_number(payload: Mapping[str, object], key: str, path: str) -> float | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobRequestDecodeError(f"Field must be a number or null: {path}")
    return float(value)


def _require_mapping(payload: Mapping[str, object], key: str, path: str) -> Mapping[str, object]:
    if key not in payload:
        raise JobRequestDecodeError(f"Missing required field: {path}.{key}")
    return _as_mapping(payload[key], f"{path}.{key}")


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
        raise JobRequestDecodeError(f"Field must be an object: {path}")
    for key in value.keys():
        if not isinstance(key, str):
            raise JobRequestDecodeError(f"Object keys must be strings: {path}")
    return value


def _as_string_mapping(value: Mapping[str, object], *, path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise JobRequestDecodeError(f"Mapping value must be a string: {path}.{key}")
        result[key] = item
    return result


def _reject_unknown_fields(payload: Mapping[str, object], allowed_keys: set[str], *, path: str) -> None:
    unknown_keys = sorted(key for key in payload.keys() if key not in allowed_keys)
    if unknown_keys:
        unknown_text = ", ".join(unknown_keys)
        raise JobRequestDecodeError(f"Unknown field(s) not allowed: {path} -> {unknown_text}")
