from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from contracts.job import JobResult


def build_job_result_dto(result: JobResult) -> dict[str, Any]:
    manifest_payload = _load_manifest_payload(result.manifest_uri)
    manifest_loaded = manifest_payload is not None
    manifest_summary = _build_manifest_summary(result.manifest_uri, manifest_payload)
    products = _build_products_view(manifest_payload)
    conversion_trace = _resolve_conversion_trace_payload(result, manifest_payload)
    conversion_trace_panel = _build_conversion_trace_panel(conversion_trace)
    artifacts = _build_artifacts_view(
        manifest_uri=result.manifest_uri,
        log_uri=result.log_uri,
        metadata_uri=None
        if manifest_payload is None
        else manifest_payload.get("metadata_uri"),
    )

    return {
        "job_id": result.job_id,
        "run_id": result.run_id,
        "status": result.status,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "duration_ms": _build_duration_ms(result),
        "error_summary": result.error_summary,
        "artifacts": artifacts,
        "manifest_loaded": manifest_loaded,
        "manifest_summary": manifest_summary,
        "products": products,
        "main_layers": []
        if manifest_payload is None
        else list(manifest_payload.get("main_layers") or []),
        "qc_layers": []
        if manifest_payload is None
        else list(manifest_payload.get("qc_layers") or []),
        "tables": []
        if manifest_payload is None
        else list(manifest_payload.get("tables") or []),
        "metrics": dict(result.metrics),
        "conversion_trace": conversion_trace,
        "conversion_trace_panel": conversion_trace_panel,
        "extra": {}
        if manifest_payload is None
        else dict(manifest_payload.get("extra") or {}),
    }


def _build_duration_ms(result: JobResult) -> int:
    duration = result.finished_at - result.started_at
    return max(0, int(duration.total_seconds() * 1000))


def _load_manifest_payload(manifest_uri: str | None) -> dict[str, Any] | None:
    if not manifest_uri:
        return None
    manifest_path = Path(manifest_uri)
    if not manifest_path.exists() or manifest_path.suffix.lower() != ".json":
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _build_manifest_summary(
    manifest_uri: str | None, manifest_payload: dict[str, Any] | None
) -> dict[str, Any]:
    products = (
        [] if manifest_payload is None else list(manifest_payload.get("products") or [])
    )
    extra = (
        {} if manifest_payload is None else dict(manifest_payload.get("extra") or {})
    )
    conversion_trace = extra.get("conversion_trace")
    return {
        "manifest_uri": manifest_uri,
        "loaded": manifest_payload is not None,
        "product_count": len(products),
        "main_layer_count": 0
        if manifest_payload is None
        else len(list(manifest_payload.get("main_layers") or [])),
        "qc_layer_count": 0
        if manifest_payload is None
        else len(list(manifest_payload.get("qc_layers") or [])),
        "table_count": 0
        if manifest_payload is None
        else len(list(manifest_payload.get("tables") or [])),
        "created_at": None
        if manifest_payload is None
        else manifest_payload.get("created_at"),
        "conversion_trace_dataset_count": _extract_conversion_trace_dataset_count(
            conversion_trace
        ),
        "conversion_trace_resource_count": _extract_conversion_trace_entry_count(
            conversion_trace
        ),
    }


def _resolve_conversion_trace_payload(
    result: JobResult, manifest_payload: dict[str, Any] | None
) -> dict[str, Any]:
    if manifest_payload is not None:
        extra = manifest_payload.get("extra")
        if isinstance(extra, dict):
            conversion_trace = extra.get("conversion_trace")
            if isinstance(conversion_trace, dict):
                return dict(conversion_trace)
    metrics_conversion_trace = result.metrics.get("conversion_trace")
    if isinstance(metrics_conversion_trace, dict):
        return dict(metrics_conversion_trace)
    return {}


def _build_conversion_trace_panel(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "available": False,
            "dataset_count": 0,
            "resource_count": 0,
            "adapters": [],
            "formats": [],
            "logical_types": [],
            "highlights": [],
            "warnings": [],
            "datasets": [],
        }

    datasets_payload = value.get("datasets")
    datasets: list[dict[str, Any]] = []
    adapters: set[str] = set()
    formats: set[str] = set()
    logical_types: set[str] = set()
    dataset_warning_items: list[dict[str, Any]] = []

    if isinstance(datasets_payload, list):
        for item in datasets_payload:
            dataset_panel = _build_conversion_trace_panel_dataset(item)
            if dataset_panel is None:
                continue
            datasets.append(dataset_panel)
            adapters.update(dataset_panel["adapters"])
            formats.update(dataset_panel["formats"])
            logical_types.update(dataset_panel["logical_types"])
            dataset_warning_items.extend(dataset_panel["warnings"])

    dataset_count = _extract_conversion_trace_dataset_count(value) or len(datasets)
    resource_count = _extract_conversion_trace_entry_count(value) or sum(
        int(dataset["resource_count"]) for dataset in datasets
    )

    return {
        "available": bool(datasets) or dataset_count > 0 or resource_count > 0,
        "dataset_count": dataset_count,
        "resource_count": resource_count,
        "adapters": sorted(adapters),
        "formats": sorted(formats),
        "logical_types": sorted(logical_types),
        "highlights": [
            _build_panel_highlight("dataset_count", "Datasets", dataset_count),
            _build_panel_highlight("resource_count", "Resources", resource_count),
            _build_panel_highlight("adapter_count", "Adapters", len(adapters)),
            _build_panel_highlight("format_count", "Formats", len(formats)),
        ],
        "warnings": _aggregate_panel_warnings(dataset_warning_items),
        "datasets": datasets,
    }


def _build_conversion_trace_panel_dataset(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    resources_payload = value.get("resources")
    resources: list[dict[str, Any]] = []
    resource_warning_items: list[dict[str, Any]] = []

    if isinstance(resources_payload, list):
        for item in resources_payload:
            resource_panel = _build_conversion_trace_panel_resource(item)
            if resource_panel is None:
                continue
            resources.append(resource_panel)
            resource_warning_items.extend(resource_panel["warnings"])

    adapters = _coerce_text_list(value.get("adapters"))
    if not adapters:
        adapters = sorted(
            {str(item["adapter"]) for item in resources if item.get("adapter")}
        )
    formats = _coerce_text_list(value.get("formats"))
    if not formats:
        formats = sorted(
            {str(item["format"]) for item in resources if item.get("format")}
        )
    logical_types = _coerce_text_list(value.get("logical_types"))
    if not logical_types:
        logical_types = sorted(
            {
                str(item["logical_type"])
                for item in resources
                if item.get("logical_type")
            }
        )

    dataset_name = _coerce_text(value.get("dataset_name")) or "dataset"
    resource_count = _coerce_nonnegative_int(value.get("resource_count"))
    if resource_count is None:
        resource_count = len(resources)
    entry_count = _coerce_nonnegative_int(value.get("entry_count"))
    if entry_count is None:
        entry_count = resource_count

    return {
        "dataset_name": dataset_name,
        "title": dataset_name,
        "resource_count": resource_count,
        "entry_count": entry_count,
        "adapters": adapters,
        "formats": formats,
        "logical_types": logical_types,
        "highlights": _build_conversion_trace_panel_dataset_highlights(
            resource_count=resource_count,
            adapters=adapters,
            formats=formats,
            logical_types=logical_types,
        ),
        "warnings": _aggregate_panel_warnings(resource_warning_items),
        "resources": resources,
    }


def _build_conversion_trace_panel_resource(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    loaded_summary = value.get("loaded_summary")
    summary = loaded_summary if isinstance(loaded_summary, dict) else {}
    title = _coerce_text(
        summary.get("title")
    ) or _build_conversion_trace_panel_resource_title(value)

    return {
        "title": title,
        "uri": _coerce_text(value.get("uri")),
        "origin_uri": _coerce_text(value.get("origin_uri")),
        "local_path": _coerce_text(value.get("local_path")),
        "adapter": _coerce_text(value.get("adapter")),
        "format": _coerce_text(value.get("format")),
        "logical_type": _coerce_text(value.get("logical_type")),
        "summary": {
            "counts": _normalize_panel_section(summary.get("counts")),
            "schema": _normalize_panel_section(summary.get("schema")),
            "document": _normalize_panel_section(summary.get("document")),
            "spatial": _normalize_panel_section(summary.get("spatial")),
        },
        "highlights": _normalize_panel_highlights(summary.get("highlights")),
        "warnings": _normalize_panel_warnings(summary.get("warnings")),
    }


def _build_conversion_trace_panel_dataset_highlights(
    *,
    resource_count: int,
    adapters: list[str],
    formats: list[str],
    logical_types: list[str],
) -> list[dict[str, Any]]:
    highlights = [_build_panel_highlight("resource_count", "Resources", resource_count)]
    if adapters:
        highlights.append(
            _build_panel_highlight("adapters", "Adapters", ", ".join(adapters))
        )
    if formats:
        highlights.append(
            _build_panel_highlight("formats", "Formats", ", ".join(formats))
        )
    if logical_types:
        highlights.append(
            _build_panel_highlight(
                "logical_types", "Logical Types", ", ".join(logical_types)
            )
        )
    return highlights


def _build_conversion_trace_panel_resource_title(value: dict[str, Any]) -> str:
    format_name = _coerce_text(value.get("format"))
    logical_type = _coerce_text(value.get("logical_type"))
    adapter = _coerce_text(value.get("adapter"))
    return format_name or logical_type or adapter or "Prepared resource"


def _build_panel_highlight(key: str, label: str, value: object) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": _normalize_panel_value(value),
    }


def _normalize_panel_highlights(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        key = _coerce_text(item.get("key"))
        label = _coerce_text(item.get("label"))
        if not key or not label:
            continue
        items.append(
            {
                "key": key,
                "label": label,
                "value": _normalize_panel_value(item.get("value")),
            }
        )
    return items


def _normalize_panel_warnings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        code = _coerce_text(item.get("code"))
        label = _coerce_text(item.get("label"))
        severity = _coerce_text(item.get("severity"))
        message = _coerce_text(item.get("message"))
        if not code or not label or not severity or not message:
            continue
        count = _coerce_nonnegative_int(item.get("count"))
        normalized = {
            "code": code,
            "label": label,
            "severity": severity,
            "message": message,
        }
        if count is not None:
            normalized["count"] = count
        items.append(normalized)
    return items


def _aggregate_panel_warnings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregated: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in items:
        code = _coerce_text(item.get("code"))
        label = _coerce_text(item.get("label"))
        severity = _coerce_text(item.get("severity"))
        message = _coerce_text(item.get("message"))
        if not code or not label or not severity or not message:
            continue
        key = (code, label, severity, message)
        normalized = aggregated.get(key)
        if normalized is None:
            normalized = {
                "code": code,
                "label": label,
                "severity": severity,
                "message": message,
                "count": 0,
            }
            aggregated[key] = normalized
        normalized["count"] += _coerce_nonnegative_int(item.get("count")) or 1
    return sorted(
        aggregated.values(),
        key=lambda item: (str(item["severity"]), str(item["label"]), str(item["code"])),
    )


def _normalize_panel_section(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _normalize_panel_value(item) for key, item in value.items()}


def _normalize_panel_value(value: object) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _normalize_panel_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_panel_value(item) for item in value]
    return str(value)


def _coerce_text_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _coerce_text(item)
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return sorted(normalized)


def _coerce_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _extract_conversion_trace_dataset_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    dataset_count = value.get("dataset_count")
    if isinstance(dataset_count, int):
        return dataset_count
    return 0


def _extract_conversion_trace_entry_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    entry_count = value.get("entry_count")
    if isinstance(entry_count, int):
        return entry_count
    return 0


def _build_products_view(
    manifest_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if manifest_payload is None:
        return []
    products = manifest_payload.get("products") or []
    normalized: list[dict[str, Any]] = []
    for item in products:
        if not isinstance(item, dict):
            continue
        tags = _normalize_tags(item.get("tags"))
        normalized.append(
            {
                "name": item.get("name"),
                "type": item.get("type"),
                "uri": item.get("uri"),
                "variable": item.get("variable"),
                "tags": tags,
                "is_previewable": _is_previewable_product(item),
                **_build_storage_fields(item, tags),
            }
        )
    return normalized


def _build_artifacts_view(
    *,
    manifest_uri: str | None,
    log_uri: str | None,
    metadata_uri: str | None,
) -> dict[str, Any]:
    return {
        "manifest_uri": manifest_uri,
        "log_uri": log_uri,
        "metadata_uri": metadata_uri,
        "manifest": _build_uri_view(manifest_uri),
        "log": _build_uri_view(log_uri),
        "metadata": _build_uri_view(metadata_uri),
    }


def _normalize_tags(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return dict(value)


def _build_uri_view(
    uri: str | None, *, tags: dict[str, Any] | None = None
) -> dict[str, Any]:
    normalized_tags = {} if tags is None else dict(tags)
    return {
        "uri": uri,
        **_build_storage_fields({"uri": uri}, normalized_tags),
    }


def _build_storage_fields(item: dict[str, Any], tags: dict[str, Any]) -> dict[str, Any]:
    uri = _coerce_text(item.get("uri"))
    storage_backend = _first_nonempty_text(
        item.get("storage_backend"), tags.get("storage_backend")
    )
    bucket = _first_nonempty_text(item.get("bucket"), tags.get("bucket"))
    object_key = _first_nonempty_text(item.get("object_key"), tags.get("object_key"))
    preview_url = _first_nonempty_text(item.get("preview_url"), tags.get("preview_url"))
    download_url = _first_nonempty_text(
        item.get("download_url"), tags.get("download_url")
    )

    if not uri:
        return {
            "storage_backend": storage_backend,
            "bucket": bucket,
            "object_key": object_key,
            "preview_url": preview_url,
            "download_url": download_url,
        }

    if _looks_like_local_path(uri):
        file_uri = _as_file_uri(uri)
        return {
            "storage_backend": storage_backend or "file",
            "bucket": bucket,
            "object_key": object_key or _normalize_local_path(uri),
            "preview_url": preview_url or file_uri,
            "download_url": download_url or file_uri,
        }

    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    if scheme in {"http", "https"}:
        return {
            "storage_backend": storage_backend or scheme,
            "bucket": bucket,
            "object_key": object_key,
            "preview_url": preview_url or uri,
            "download_url": download_url or uri,
        }

    if scheme == "file":
        local_path = _local_path_from_file_uri(parsed)
        file_uri = _as_file_uri(local_path) if local_path else uri
        return {
            "storage_backend": storage_backend or "file",
            "bucket": bucket,
            "object_key": object_key or _normalize_local_path(local_path),
            "preview_url": preview_url or file_uri,
            "download_url": download_url or file_uri,
        }

    return {
        "storage_backend": storage_backend or scheme or None,
        "bucket": bucket or (parsed.netloc or None),
        "object_key": object_key or _coerce_object_key(parsed.path),
        "preview_url": preview_url,
        "download_url": download_url,
    }


def _coerce_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _first_nonempty_text(*values: object) -> str | None:
    for value in values:
        text = _coerce_text(value)
        if text:
            return text
    return None


def _looks_like_local_path(value: str) -> bool:
    if _looks_like_windows_path(value):
        return True
    if "://" in value:
        return False
    try:
        return Path(value).is_absolute()
    except OSError:
        return False


def _looks_like_windows_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}


def _normalize_local_path(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return Path(value).as_posix()
    except OSError:
        return value


def _as_file_uri(value: str | None) -> str | None:
    if not value:
        return None
    try:
        path = Path(value)
        if not path.is_absolute():
            return None
        return path.as_uri()
    except (OSError, ValueError):
        return None


def _local_path_from_file_uri(parsed) -> str | None:
    path_value = unquote(parsed.path or "")
    if not path_value:
        return None
    if path_value.startswith("/") and _looks_like_windows_path(path_value[1:]):
        path_value = path_value[1:]
    return path_value


def _coerce_object_key(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unquote(value).lstrip("/")
    return normalized or None


def _is_previewable_product(item: dict[str, Any]) -> bool:
    uri = str(item.get("uri") or "")
    product_type = str(item.get("type") or "").lower()
    if uri.startswith(("http://", "https://", "s3://", "minio://")):
        return True
    if product_type in {
        "raster",
        "platform_raster",
        "omega_block_mat",
        "omega_daily_mat",
    }:
        return True
    return False
