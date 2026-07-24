from __future__ import annotations

from pathlib import Path
from typing import Any

from data_access.cache_store import CacheStore
from data_access.contracts import DataRequestV2, PreparedInput, build_prepared_input
from data_access.fetcher import Fetcher
from data_access.format_adapters import FormatRegistry, build_default_format_registry
from data_access.locator import Locator
from data_access.materializer import Materializer
from data_access.registry import SourceRegistry, build_default_source_registry
from data_access.resolver import Resolver


class DataAccessCoordinator:
    def __init__(
        self,
        *,
        locator: Locator,
        resolver: Resolver,
        fetcher: Fetcher,
        materializer: Materializer,
        format_registry: FormatRegistry | None = None,
    ) -> None:
        self.locator = locator
        self.resolver = resolver
        self.fetcher = fetcher
        self.materializer = materializer
        self.format_registry = format_registry

    def prepare(
        self,
        request: DataRequestV2,
        *,
        target_dir: str | Path | None = None,
    ) -> PreparedInput:
        located_resources = self.locator.locate(request)
        resolved_resources = self.resolver.resolve(request, located_resources)
        fetched_resources, cache_hits = self.fetcher.fetch_many(
            request, resolved_resources
        )
        materialized_resources = self.materializer.materialize_many(
            request,
            fetched_resources,
            target_dir=target_dir,
        )
        conversion_trace = self._build_conversion_trace(materialized_resources)
        warnings: list[str] = []
        if not resolved_resources:
            warnings.append(
                f"No resources resolved for dataset '{request.dataset_name}'"
            )
        return build_prepared_input(
            request,
            resources=resolved_resources,
            materialized_resources=materialized_resources,
            warnings=warnings,
            conversion_trace=conversion_trace,
            cache_hits=cache_hits,
        )

    def _build_conversion_trace(
        self,
        resources: tuple[object, ...] | list[object],
    ) -> tuple[dict[str, Any], ...]:
        if self.format_registry is None:
            return ()
        trace_entries: list[dict[str, Any]] = []
        for resource in resources:
            try:
                adapter = self.format_registry.find_for_resource(resource)
            except LookupError:
                continue
            try:
                if not adapter.probe(resource):
                    continue
                loaded = adapter.load(resource)
            except Exception:
                # Conversion tracing must never break the data preparation main path.
                continue
            trace_entries.append(
                {
                    "uri": resource.uri,
                    "origin_uri": resource.metadata.get("origin_uri"),
                    "local_path": resource.local_path,
                    "format": resource.format,
                    "logical_type": resource.logical_type,
                    "adapter": adapter.name,
                    "loaded_summary": _summarize_loaded_value(loaded),
                }
            )
        return tuple(trace_entries)


def build_default_coordinator(
    cache_root: str | Path,
    *,
    source_registry: SourceRegistry | None = None,
    format_registry: FormatRegistry | None = None,
) -> DataAccessCoordinator:
    registry = source_registry or build_default_source_registry()
    return DataAccessCoordinator(
        locator=Locator(registry),
        resolver=Resolver(),
        fetcher=Fetcher(CacheStore(cache_root)),
        materializer=Materializer(registry),
        format_registry=format_registry or build_default_format_registry(),
    )


def _summarize_loaded_value(value: Any) -> dict[str, object]:
    if isinstance(value, dict):
        summary: dict[str, object] = {
            "kind": "dict",
            "keys": tuple(sorted(str(key) for key in value.keys())),
            "counts": {},
            "schema": {},
            "document": {},
            "spatial": {},
            "title": "Structured resource",
            "highlights": [],
            "warnings": [],
        }
        if "rows" in value and isinstance(value["rows"], tuple):
            summary["counts"]["row_count"] = len(value["rows"])
        if "variables" in value and isinstance(value["variables"], tuple):
            summary["counts"]["variable_count"] = len(value["variables"])
        if "datasets" in value and isinstance(value["datasets"], tuple):
            summary["counts"]["dataset_count"] = len(value["datasets"])
        if "worksheets" in value and isinstance(value["worksheets"], tuple):
            summary["counts"]["worksheet_count"] = len(value["worksheets"])
        if "lines" in value and isinstance(value["lines"], tuple):
            summary["counts"]["line_count"] = len(value["lines"])
        if "group_names" in value and isinstance(value["group_names"], tuple):
            summary["counts"]["group_count"] = len(value["group_names"])
        if "dimension_names" in value and isinstance(value["dimension_names"], tuple):
            summary["counts"]["dimension_count"] = len(value["dimension_names"])
        if "band_count" in value:
            summary["counts"]["band_count"] = int(value["band_count"])
        if "feature_count" in value and value["feature_count"] is not None:
            summary["counts"]["feature_count"] = int(value["feature_count"])
        if "headers" in value and isinstance(value["headers"], tuple):
            summary["schema"]["headers"] = tuple(
                str(header) for header in value["headers"]
            )
        if "sheet_names" in value and isinstance(value["sheet_names"], tuple):
            summary["schema"]["sheet_names"] = tuple(
                str(sheet_name) for sheet_name in value["sheet_names"]
            )
        if "variable_names" in value and isinstance(value["variable_names"], tuple):
            summary["schema"]["variable_names"] = tuple(
                str(name) for name in value["variable_names"]
            )
        if "dataset_names" in value and isinstance(value["dataset_names"], tuple):
            summary["schema"]["dataset_names"] = tuple(
                str(name) for name in value["dataset_names"]
            )
        if "dimension_names" in value and isinstance(value["dimension_names"], tuple):
            summary["schema"]["dimension_names"] = tuple(
                str(name) for name in value["dimension_names"]
            )
        if "group_names" in value and isinstance(value["group_names"], tuple):
            summary["schema"]["group_names"] = tuple(
                str(name) for name in value["group_names"]
            )
        if "geometry_type" in value:
            summary["spatial"]["geometry_type"] = str(value["geometry_type"])
        if "root_tag" in value:
            summary["document"]["root_tag"] = str(value["root_tag"])
        if "width" in value:
            summary["spatial"]["width"] = int(value["width"])
        if "height" in value:
            summary["spatial"]["height"] = int(value["height"])
        if "crs" in value:
            summary["spatial"]["crs"] = (
                None if value["crs"] is None else str(value["crs"])
            )
        if "bounds" in value and isinstance(value["bounds"], dict):
            summary["spatial"]["bounds"] = dict(value["bounds"])
        if "bbox" in value and isinstance(value["bbox"], dict):
            summary["spatial"]["bbox"] = dict(value["bbox"])
        if "document" in value:
            document = value["document"]
            if isinstance(document, dict):
                summary["document"]["kind"] = "object"
                summary["document"]["keys"] = tuple(
                    sorted(str(key) for key in document.keys())
                )
            elif isinstance(document, list):
                summary["document"]["kind"] = "array"
                summary["document"]["length"] = len(document)
            else:
                summary["document"]["kind"] = type(document).__name__
        summary["counts"] = dict(summary["counts"])
        summary["schema"] = dict(summary["schema"])
        summary["document"] = dict(summary["document"])
        summary["spatial"] = dict(summary["spatial"])
        summary["title"] = _build_loaded_value_title(summary)
        summary["highlights"] = _build_loaded_value_highlights(summary)
        summary["warnings"] = _build_loaded_value_warnings(summary)
        return summary
    return {"kind": type(value).__name__}


def _build_loaded_value_title(summary: dict[str, object]) -> str:
    spatial = summary.get("spatial", {})
    document = summary.get("document", {})
    schema = summary.get("schema", {})
    counts = summary.get("counts", {})
    if isinstance(spatial, dict) and spatial.get("geometry_type"):
        return f"Vector {spatial['geometry_type']}"
    if isinstance(counts, dict) and counts.get("band_count"):
        return "Raster resource"
    if isinstance(document, dict) and document.get("root_tag"):
        return f"XML document {document['root_tag']}"
    if isinstance(schema, dict) and schema.get("sheet_names"):
        return "Excel workbook"
    if isinstance(schema, dict) and schema.get("dimension_names"):
        return "NetCDF dataset"
    if isinstance(schema, dict) and schema.get("dataset_names"):
        return "HDF dataset"
    if isinstance(schema, dict) and schema.get("variable_names"):
        return "MAT resource"
    if isinstance(counts, dict) and counts.get("row_count"):
        return "Tabular resource"
    if isinstance(counts, dict) and counts.get("line_count"):
        return "Text resource"
    if isinstance(document, dict) and document.get("kind"):
        return "Document resource"
    return "Structured resource"


def _build_loaded_value_highlights(
    summary: dict[str, object],
) -> list[dict[str, object]]:
    counts = summary.get("counts", {})
    schema = summary.get("schema", {})
    document = summary.get("document", {})
    spatial = summary.get("spatial", {})
    highlights: list[dict[str, object]] = []
    if isinstance(counts, dict):
        if counts.get("row_count") is not None:
            highlights.append(
                _build_highlight_item("row_count", "Rows", counts["row_count"])
            )
        if counts.get("worksheet_count") is not None:
            highlights.append(
                _build_highlight_item(
                    "worksheet_count", "Worksheets", counts["worksheet_count"]
                )
            )
        if counts.get("variable_count") is not None:
            highlights.append(
                _build_highlight_item(
                    "variable_count", "Variables", counts["variable_count"]
                )
            )
        if counts.get("dataset_count") is not None:
            highlights.append(
                _build_highlight_item(
                    "dataset_count", "Datasets", counts["dataset_count"]
                )
            )
        if counts.get("dimension_count") is not None:
            highlights.append(
                _build_highlight_item(
                    "dimension_count", "Dimensions", counts["dimension_count"]
                )
            )
        if counts.get("band_count") is not None:
            highlights.append(
                _build_highlight_item("band_count", "Bands", counts["band_count"])
            )
        if counts.get("feature_count") is not None:
            highlights.append(
                _build_highlight_item(
                    "feature_count", "Features", counts["feature_count"]
                )
            )
        if counts.get("line_count") is not None:
            highlights.append(
                _build_highlight_item("line_count", "Lines", counts["line_count"])
            )
    if isinstance(schema, dict):
        headers = schema.get("headers")
        if isinstance(headers, tuple) and headers:
            highlights.append(
                _build_highlight_item(
                    "headers", "Headers", ", ".join(str(value) for value in headers[:3])
                )
            )
        sheet_names = schema.get("sheet_names")
        if isinstance(sheet_names, tuple) and sheet_names:
            highlights.append(
                _build_highlight_item("sheet_name", "Sheet", str(sheet_names[0]))
            )
        dimension_names = schema.get("dimension_names")
        if isinstance(dimension_names, tuple) and dimension_names:
            highlights.append(
                _build_highlight_item(
                    "dimension_names",
                    "Dimension Names",
                    ", ".join(str(value) for value in dimension_names[:3]),
                )
            )
        variable_names = schema.get("variable_names")
        if isinstance(variable_names, tuple) and variable_names:
            highlights.append(
                _build_highlight_item(
                    "variable_names",
                    "Variable Names",
                    ", ".join(str(value) for value in variable_names[:3]),
                )
            )
    if isinstance(document, dict) and document.get("root_tag"):
        highlights.append(
            _build_highlight_item("root_tag", "Root Tag", str(document["root_tag"]))
        )
    if isinstance(spatial, dict):
        if spatial.get("crs"):
            highlights.append(_build_highlight_item("crs", "CRS", str(spatial["crs"])))
        if spatial.get("geometry_type"):
            highlights.append(
                _build_highlight_item(
                    "geometry_type", "Geometry", str(spatial["geometry_type"])
                )
            )
    return highlights[:4]


def _build_highlight_item(key: str, label: str, value: object) -> dict[str, object]:
    return {
        "key": key,
        "label": label,
        "value": value,
    }


def _build_loaded_value_warnings(summary: dict[str, object]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    counts = summary.get("counts", {})
    spatial = summary.get("spatial", {})
    if isinstance(counts, dict):
        if counts.get("row_count") == 0:
            warnings.append(
                _build_warning_item("no_rows", "No rows", "warning", "No rows detected")
            )
        if counts.get("variable_count") == 0:
            warnings.append(
                _build_warning_item(
                    "no_variables", "No variables", "warning", "No variables detected"
                )
            )
        if counts.get("dataset_count") == 0:
            warnings.append(
                _build_warning_item(
                    "no_datasets", "No datasets", "warning", "No datasets detected"
                )
            )
        if counts.get("feature_count") == 0:
            warnings.append(
                _build_warning_item(
                    "no_features", "No features", "warning", "No features detected"
                )
            )
    if isinstance(spatial, dict) and "crs" in spatial and not spatial.get("crs"):
        warnings.append(
            _build_warning_item(
                "missing_crs", "Missing CRS", "warning", "Spatial reference is missing"
            )
        )
    return warnings


def _build_warning_item(
    code: str, label: str, severity: str, message: str
) -> dict[str, str]:
    return {
        "code": code,
        "label": label,
        "severity": severity,
        "message": message,
    }
