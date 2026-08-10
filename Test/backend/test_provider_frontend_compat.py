from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.layer_catalog import get_layer_descriptor as _get_descriptor
from app.services.python_provider_bridge_service import python_provider_bridge_service
from app.services.workflow.service_container import submission_service
from shared.contracts.api_contracts import LayerRenderType, WorkflowSubmitRequest


class ProviderFrontendCompatTests(unittest.TestCase):
    """验证 provider 热力图结果符合前端 mapLayerPayload 期望。

    原 lab-output 图层已删除（2026-08-10），对应的 LabOutputProvider 兼容测试已移除。
    """
    pass

    # _submit_provider_workflow 和 _find_map_layer_inline_data 保留供后续 provider 验证用
    def _submit_provider_workflow(self, layer_id: str) -> str:
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

    def _find_map_layer_inline_data(self, result_refs) -> dict | None:
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



if __name__ == "__main__":
    unittest.main()
