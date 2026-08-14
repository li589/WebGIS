from __future__ import annotations

from unittest.mock import patch

from app.services.layer_catalog import get_layer_descriptor as _get_descriptor
from app.services.python_provider_bridge_service import python_provider_bridge_service
from app.services.workflow.service_container import submission_service
from shared.contracts.api_contracts import LayerRenderType, WorkflowSubmitRequest


def _submit_provider_workflow(layer_id: str) -> str:
    payload = WorkflowSubmitRequest(
        command_type="analysis",
        command_label=f"运行 {layer_id} 分析",
        layer_id=layer_id,
        requested_outputs=["json", "text", "table", "map_layer"],
        parameters={
            "hour": 12,
            "latitude": 23.1291,
            "longitude": 113.2644,
        },
        client={"page": "dashboard", "view_id": "map-2d"},
        map_context={
            "active_layer_id": layer_id,
            "map_mode": "2d",
            "viewport_bbox": {
                "west": 108.0,
                "south": 20.0,
                "east": 118.0,
                "north": 26.0,
                "crs": "EPSG:4326",
            },
        },
    )
    accepted = submission_service.submit_workflow(payload)
    return accepted.run_id


def _find_map_layer_inline_data(result_refs) -> dict | None:
    for ref in result_refs:
        ref_dict = (
            ref.model_dump(mode="json") if hasattr(ref, "model_dump") else dict(ref)
        )
        if ref_dict.get("result_kind") != "map_layer":
            continue
        inline_data = ref_dict.get("inline_data") or {}
        if inline_data:
            return inline_data
    return None
