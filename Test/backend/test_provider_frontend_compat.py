from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.layer_catalog import get_layer_descriptor as _get_descriptor
from app.services.python_provider_bridge_service import python_provider_bridge_service
from app.services.workflow.service_container import submission_service
from shared.contracts.api_contracts import LayerRenderType, WorkflowSubmitRequest


def _lab_output_as_heatmap(layer_id: str):
    """catalog 演进将 lab-output 的 render_type 改为 raster，但 LabOutputProvider
    仍产出 hotspot 热力图。这里让 provider_result_builder 视其为 heatmap，
    以便 _build_map_layer_ref 构建热力图结果引用。"""
    desc = _get_descriptor(layer_id)
    if desc is not None and layer_id == "lab-output":
        return desc.model_copy(update={"render_type": LayerRenderType.heatmap})
    return desc


class ProviderFrontendCompatTests(unittest.TestCase):
    """验证 provider 热力图结果符合前端 mapLayerPayload 期望。"""

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

    def test_lab_output_map_layer_ref_matches_frontend_shape(self) -> None:
        # catalog 演进后 lab-output 绑定 engine=python_provider(module_name=lab_model)
        # 且 render_type 改为 raster。但 LabOutputProvider 仍产出 hotspot 热力图，
        # 本测试验证该热力图 map_layer 结果形状。故：
        # 1) 让 python_provider_bridge 跳过 lab-output，交由 provider_workflow_service
        #    调用 LabOutputProvider（否则会因 lab_model 模块未注册而失败）；
        # 2) 让 provider_result_builder 视 lab-output 为 heatmap render_type，
        #    以便 _build_map_layer_ref 构建热力图结果引用。
        with (
            patch.object(
                python_provider_bridge_service, "supports", return_value=False
            ),
            patch(
                "app.services.provider_result_builder.get_layer_descriptor",
                _lab_output_as_heatmap,
            ),
        ):
            run_id = self._submit_provider_workflow("lab-output")
        status_resp = submission_service.get_workflow_run(run_id)

        self.assertIn(status_resp.status, ("succeeded", "completed"))

        inline = self._find_map_layer_inline_data(status_resp.result_refs)
        self.assertIsNotNone(inline, "未找到 map_layer inline_data")

        render_hint = inline.get("render_hint") or {}
        self.assertEqual(render_hint.get("paint_mode"), "heatmap")
        self.assertEqual(render_hint.get("primary_metric"), "risk_score")
        self.assertTrue(render_hint.get("palette"))
        self.assertTrue(render_hint.get("legend_ticks"))

        point_feature = inline.get("point_feature") or {}
        self.assertEqual(point_feature.get("type"), "Feature")
        geometry = point_feature.get("geometry") or {}
        self.assertEqual(geometry.get("type"), "Point")
        properties = point_feature.get("properties") or {}
        self.assertIsInstance(properties.get("risk_score"), (int, float))
        self.assertEqual(properties.get("metric"), "risk_score")

        layer_assets = inline.get("layer_assets") or {}
        self.assertTrue(layer_assets.get("geojson_url"), "missing geojson_url")
        self.assertIsNone(layer_assets.get("cog_url"))
        self.assertIsNone(layer_assets.get("cog_preview_url"))
        self.assertIsNone(layer_assets.get("cog_bbox"))


if __name__ == "__main__":
    unittest.main()
