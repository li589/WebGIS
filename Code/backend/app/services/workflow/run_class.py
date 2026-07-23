"""Workflow run capacity class helpers.

Splits active-run capacity into:
- business: analysis / GEE / non-tile weather DAGs / point / provider jobs
- weather_tile: payloads whose weather DAG contains weather_tile_render
"""

from __future__ import annotations

from typing import Any

from shared.contracts.api_contracts import WorkflowSubmitRequest

RUN_CLASS_BUSINESS = "business"
RUN_CLASS_WEATHER_TILE = "weather_tile"

WEATHER_TILE_NODE_TYPE = "weather_tile_render"


def is_weather_tile_workflow_request(weather_request: dict[str, Any] | None) -> bool:
    """Return True if weather_request DAG contains a weather_tile_render node."""
    if not weather_request:
        return False
    workflow = weather_request.get("workflow") or {}
    nodes = workflow.get("nodes") or []
    return any(
        (
            node.get("node_type")
            if isinstance(node, dict)
            else getattr(node, "node_type", None)
        )
        == WEATHER_TILE_NODE_TYPE
        for node in nodes
    )


def _normalize_weather_request(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return dict(value)
    return {}


def resolve_workflow_run_class(payload: WorkflowSubmitRequest) -> str:
    """Classify a submit request into a capacity pool."""
    weather_request = _normalize_weather_request(payload.weather_request)
    if is_weather_tile_workflow_request(weather_request):
        return RUN_CLASS_WEATHER_TILE
    return RUN_CLASS_BUSINESS
