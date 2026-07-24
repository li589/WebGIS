"""Python provider request builder: pre-submit payload construction + validation.

Extracted from the original ``python_provider_bridge_service.py`` god class.
Owns all "before ``service.submit_job()``" concerns:

- :meth:`build_job_request_payload` normalises the algorithm_request,
  injects defaults (job_id, pipeline_name, datasource_selection,
  algorithm_params, output_spec, tags), merges open-data presets +
  portal credential resolution flags, and resolves region / time_range /
  priority from the workflow payload.
- :meth:`validate_algorithm_request_shape` enforces structural contracts
  on the assembled payload (dict types for datasource_selection /
  algorithm_params / output_spec / tags, time_range / region sub-shapes,
  workflow_definition vs module_name exclusivity).
- :meth:`build_validation_error_message` formats provider template
  validation errors with resolution diagnostics for the
  :class:`BridgeExecutionError` raised on validation failure.
- :meth:`normalize_algorithm_request` coerces the
  :class:`AlgorithmWorkflowRequest` model or dict form to a plain dict.

The bridge service calls :meth:`build_job_request_payload` before
``validate_job_response`` / ``submit_job``; this module is unaware of
result ref construction or job service loading — those live in
:mod:`python_provider_result_builder` and the bridge service itself.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.contracts.api_contracts import (
    AlgorithmWorkflowRequest,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)

# Keys that identify an algorithm_request as a valid Python provider entry.
# At least one must be present for supports() to return True.
ALGORITHM_REQUEST_ENTRY_KEYS: tuple[str, ...] = (
    "module_name",
    "workflow_name",
    "workflow_definition",
)

# Workflow priority → algorithm priority int. Mirrors the Python provider
# job service's expected priority scale.
_ALGORITHM_PRIORITY_MAP: dict[str, int] = {
    "low": 1,
    "normal": 5,
    "high": 8,
    "critical": 9,
}


class PythonProviderRequestBuilder:
    """Builds and validates Python provider job request payloads."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_job_request_payload(
        self, *, run_id: str, payload: WorkflowSubmitRequest
    ) -> dict[str, Any]:
        """Assemble the full job request payload for ``submit_job``.

        Merges ``algorithm_request`` with workflow-level defaults and
        injects open-data presets + portal credential resolution flags.
        Calls :meth:`validate_algorithm_request_shape` before returning.
        """
        algorithm_request = self.normalize_algorithm_request(payload.algorithm_request)
        if not any(key in algorithm_request for key in ALGORITHM_REQUEST_ENTRY_KEYS):
            raise ValueError(
                "algorithm_request 必须至少包含 module_name、workflow_name 或 workflow_definition 之一。"
            )

        request_payload = dict(algorithm_request)
        request_payload.setdefault("job_id", run_id)
        request_payload.setdefault("pipeline_name", "workflow")
        request_payload.setdefault(
            "task_type",
            algorithm_request.get("task_type") or payload.command_type.value,
        )
        request_payload.setdefault("datasource_selection", {})
        request_payload.setdefault("algorithm_params", {})
        request_payload.setdefault(
            "output_spec", {"include_manifest": True, "extra": {}}
        )
        request_payload.setdefault("tags", {})
        if isinstance(request_payload["tags"], dict):
            request_payload["tags"].setdefault("workflow_run_id", run_id)
            request_payload["tags"].setdefault(
                "workflow_command_type", payload.command_type.value
            )
            if payload.layer_id:
                request_payload["tags"].setdefault(
                    "workflow_layer_id", payload.layer_id
                )

        # Inject open-data presets + portal credentials for http_open_data nodes
        try:
            from app.services.config_service import (
                get_data_source_config,
            )

            presets = get_data_source_config().get("open_data_presets") or {}
            ds = request_payload.get("datasource_selection")
            if not isinstance(ds, dict):
                ds = {}
                request_payload["datasource_selection"] = ds
            if isinstance(presets, dict) and presets:
                ds.setdefault("open_data_presets", presets)
            # Do NOT embed plaintext portal tokens in the job payload (persisted /
            # logged). Nodes resolve secrets lazily via portal_credentials_resolve.
            ds.setdefault("portal_credentials_resolve", True)
            ds.pop("portal_credentials", None)
        except Exception:  # noqa: BLE001
            pass

        if payload.time_range is not None and "time_range" not in request_payload:
            request_payload["time_range"] = {
                "start": payload.time_range.start_at.isoformat(),
                "end": payload.time_range.end_at.isoformat(),
            }

        if "region" not in request_payload:
            request_payload["region"] = self._build_region_payload(payload)

        if request_payload.get("priority") is None:
            request_payload["priority"] = _ALGORITHM_PRIORITY_MAP[
                payload.priority.value
            ]

        algorithm_params = request_payload.get("algorithm_params")
        if not isinstance(algorithm_params, dict):
            request_payload["algorithm_params"] = {}
            algorithm_params = request_payload["algorithm_params"]
        for key, value in payload.parameters.items():
            algorithm_params.setdefault(key, value)

        output_spec = request_payload.get("output_spec")
        if not isinstance(output_spec, dict):
            output_spec = {"include_manifest": True, "extra": {}}
            request_payload["output_spec"] = output_spec
        output_spec.setdefault("include_manifest", True)
        output_spec.setdefault("include_qc", True)
        output_spec.setdefault("raster_format", "COG")
        output_spec.setdefault("table_format", "parquet")
        if not isinstance(output_spec.get("extra"), dict):
            output_spec["extra"] = {}

        self.validate_algorithm_request_shape(request_payload)
        return request_payload

    def validate_algorithm_request_shape(self, request_payload: dict[str, Any]) -> None:
        """Enforce structural contracts on the assembled request payload.

        Raises ``ValueError`` with a Chinese-language message (preserved
        from the original) when any field has the wrong type or missing
        sub-fields. Called by :meth:`build_job_request_payload` before
        returning, and may be called independently for early validation.
        """
        if not isinstance(request_payload.get("datasource_selection"), dict):
            raise ValueError("algorithm_request.datasource_selection 必须为 object。")
        if not isinstance(request_payload.get("algorithm_params"), dict):
            raise ValueError("algorithm_request.algorithm_params 必须为 object。")
        if not isinstance(request_payload.get("output_spec"), dict):
            raise ValueError("algorithm_request.output_spec 必须为 object。")
        if not isinstance(request_payload.get("tags"), dict):
            raise ValueError("algorithm_request.tags 必须为 object。")

        # 协议统一增强：校验 time_range 内部结构，提前在 bridge 层暴露错误
        # Python provider 侧 TimeRange 要求 {start: str, end: str, step?: str}
        time_range = request_payload.get("time_range")
        if time_range is not None:
            if not isinstance(time_range, dict):
                raise ValueError("algorithm_request.time_range 必须为 object。")
            if "start" not in time_range or "end" not in time_range:
                raise ValueError(
                    "algorithm_request.time_range 必须包含 'start' 和 'end' 字段（ISO 8601 字符串）。"
                )

        # 协议统一增强：校验 region 内部结构
        # Python provider 侧 RegionSpec 要求 {kind: str, value: dict}
        region = request_payload.get("region")
        if region is not None:
            if not isinstance(region, dict):
                raise ValueError("algorithm_request.region 必须为 object。")
            if "kind" not in region or "value" not in region:
                raise ValueError(
                    "algorithm_request.region 必须包含 'kind' 和 'value' 字段。"
                )

        if (
            request_payload.get("workflow_definition") is not None
            and request_payload.get("module_name") is not None
        ):
            raise ValueError(
                "algorithm_request.workflow_definition 与 module_name 不能同时出现。"
            )

    def build_validation_error_message(
        self,
        *,
        errors: list[str],
        resolution_diagnostics: dict[str, Any] | None,
    ) -> str:
        """Format a provider template validation error message.

        When ``resolution_diagnostics`` carries ``unresolved_default_datasets``,
        appends a human-readable breakdown of which datasets failed to
        resolve and their candidate sources, so the operator can see
        which layer / module / data-source configuration is at fault.
        """
        base_message = f"Provider template validation failed: {'; '.join(errors)}"
        if not resolution_diagnostics:
            return base_message

        unresolved_datasets = (
            resolution_diagnostics.get("unresolved_default_datasets") or []
        )
        if not unresolved_datasets:
            return base_message

        dataset_text = "; ".join(
            f"{item['dataset_name']} <= {', '.join(item.get('candidate_sources') or [])}"
            for item in unresolved_datasets
        )
        layer_id = resolution_diagnostics.get("layer_id") or "unknown-layer"
        module_name = resolution_diagnostics.get("module_name") or "unknown-module"
        layer_status = resolution_diagnostics.get("layer_status") or "unknown"
        return (
            f"{base_message} Default data sources are not ready for layer '{layer_id}' "
            f"(module={module_name}, status={layer_status}): {dataset_text}"
        )

    def normalize_algorithm_request(
        self, value: AlgorithmWorkflowRequest | dict[str, Any] | Any
    ) -> dict[str, Any]:
        """Coerce the algorithm_request field to a plain dict.

        Handles three input forms:
        - :class:`AlgorithmWorkflowRequest` pydantic model (serialised
          with ``exclude_none=True`` to drop empty optionals).
        - ``dict`` (shallow-copied to avoid mutating the caller's dict).
        - Anything else (returns ``{}``).
        """
        if isinstance(value, AlgorithmWorkflowRequest):
            return value.model_dump(mode="json", exclude_none=True)
        if isinstance(value, dict):
            return dict(value)
        return {}

    # ------------------------------------------------------------------
    # Region payload
    # ------------------------------------------------------------------

    def _build_region_payload(self, payload: WorkflowSubmitRequest) -> dict[str, Any]:
        """Build the ``region`` field from the workflow's spatial_filter.

        Returns ``{"kind": "bbox", "value": {...}}`` when a bbox is
        present, or ``{"kind": "global", "value": {}}`` as fallback.
        """
        bbox = payload.spatial_filter.bbox if payload.spatial_filter else None
        if bbox is not None:
            return {
                "kind": "bbox",
                "value": {
                    "xmin": bbox.west,
                    "ymin": bbox.south,
                    "xmax": bbox.east,
                    "ymax": bbox.north,
                    "crs": bbox.crs,
                },
            }
        return {"kind": "global", "value": {}}


# Module-level singleton: request builder is stateless apart from the
# settings singleton, so a single shared instance mirrors the original
# bridge service behaviour.
python_provider_request_builder = PythonProviderRequestBuilder()
