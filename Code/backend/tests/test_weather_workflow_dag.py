"""weather workflow 5 节点 DAG 端到端测试。

构造 fetch → parse → 3 个 render (fan-out) 完整 DAG，
通过 submission_service.submit_workflow 走完整主链路，
mock Open-Meteo API 避免网络依赖。
"""
from __future__ import annotations

import json
import os
import shutil
import unittest
from typing import Any
from unittest.mock import patch

from app.services.workflow.service_container import submission_service
from app.weatherengine.service import weather_engine_service
from shared.contracts.api_contracts import WorkflowSubmitRequest


class _FakeOpenMeteoClient:
    """模拟 OpenMeteoClient。"""

    def fetch_point_forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        layer_spec,
        model: str,
        forecast_hours: int,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        return (_build_mock_payload(), "miss")


def _build_mock_payload() -> dict[str, Any]:
    """构造模拟 Open-Meteo 响应 payload。"""
    return {
        "timezone": "Asia/Shanghai",
        "utc_offset_seconds": 28800,
        "generationtime_ms": 0.0123,
        "model": "best_match",
        "current": {
            "time": "2026-07-06T00:00",
            "temperature_2m": 25.7,
            "apparent_temperature": 30.4,
            "precipitation": 0.2,
            "rain": 0.1,
            "weather_code": 3,
            "cloud_cover": 65,
            "wind_speed_10m": 13.2,
            "wind_direction_10m": 154.0,
            "wind_gusts_10m": 27.0,
        },
        "hourly": {
            "time": ["2026-07-06T00:00", "2026-07-06T01:00", "2026-07-06T02:00",
                     "2026-07-06T03:00", "2026-07-06T04:00", "2026-07-06T05:00"],
            "temperature_2m": [25.7, 25.3, 24.9, 24.5, 24.1, 23.8],
            "precipitation": [0.2, 0.7, 0.0, 0.0, 0.1, 0.3],
            "wind_speed_10m": [13.2, 12.9, 13.2, 12.5, 11.8, 11.1],
        },
    }


def _build_5_node_workflow() -> dict[str, Any]:
    """构造 5 节点 weather workflow DAG: fetch → parse → 3 个 render fan-out。"""
    return {
        "workflow_id": "weather-3-render-e2e",
        "version": "1.0.0",
        "inputs": {
            "latitude": 23.1291,
            "longitude": 113.2644,
            "layer_id": "wind-field",
            "forecast_hours": 6,
            "model": "best_match",
            "place_name": "Guangzhou",
        },
        "nodes": [
            {"node_id": "fetch", "node_type": "weather_forecast_fetch", "params": {}},
            {"node_id": "parse", "node_type": "weather_point_parse", "params": {}},
            {"node_id": "wind_render", "node_type": "weather_wind_field", "params": {}},
            {"node_id": "temp_render", "node_type": "weather_temperature_grid", "params": {}},
            {"node_id": "precip_render", "node_type": "weather_precipitation_grid", "params": {}},
        ],
        "edges": [
            {"source_node_id": "fetch", "source_port": "forecast",
             "target_node_id": "parse", "target_port": "forecast"},
            {"source_node_id": "parse", "source_port": "weather_point",
             "target_node_id": "wind_render", "target_port": "weather_point"},
            {"source_node_id": "parse", "source_port": "weather_point",
             "target_node_id": "temp_render", "target_port": "weather_point"},
            {"source_node_id": "parse", "source_port": "weather_point",
             "target_node_id": "precip_render", "target_port": "weather_point"},
        ],
    }


class WeatherWorkflowDagTests(unittest.TestCase):
    """验证 5 节点 DAG 通过 submission_service 完整执行。"""

    def setUp(self) -> None:
        # 清理缓存目录避免干扰
        cache_dir = os.path.join(os.getcwd(), ".data", "cache", "weatherengine")
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)

    @classmethod
    def setUpClass(cls) -> None:
        # 保存原始 client，测试后恢复
        cls._original_client = weather_engine_service._client

    @classmethod
    def tearDownClass(cls) -> None:
        weather_engine_service._client = cls._original_client

    def _submit_workflow(self) -> str:
        """提交 5 节点 DAG workflow，返回 run_id。"""
        payload = WorkflowSubmitRequest(
            command_type="custom",
            layer_id="wind-field",
            parameters={
                "latitude": 23.1291,
                "longitude": 113.2644,
                "place_name": "Guangzhou",
                "forecast_hours": 6,
                "model": "best_match",
            },
            map_context={"active_layer_id": "wind-field", "map_mode": "2d"},
            weather_request={
                "workflow_id": "weather-3-render-e2e",
                "layer_id": "wind-field",
                "workflow": _build_5_node_workflow(),
            },
            requested_outputs=["json", "map_layer"],
        )
        accepted = submission_service.submit_workflow(payload)
        return accepted.run_id

    def _extract_node_results(self, result_refs) -> list[dict]:
        """从 result_refs 中提取 node_results（处理 spill 到 artifact 的情况）。"""
        from app.services.result_storage import result_storage_service

        node_results = []
        for ref in result_refs:
            ref_dict = ref.model_dump(mode="json") if hasattr(ref, "model_dump") else dict(ref)
            inline = ref_dict.get("inline_data") or {}
            if isinstance(inline, dict) and "node_results" in inline:
                node_results.extend(inline["node_results"])
            else:
                # spill 到 artifact storage
                resource_key = ref_dict.get("resource_key")
                if resource_key:
                    artifact = result_storage_service.get_artifact(resource_key)
                    if artifact and artifact.file_path:
                        with open(artifact.file_path, "r", encoding="utf-8") as f:
                            artifact_data = json.load(f)
                        if isinstance(artifact_data, dict) and "node_results" in artifact_data:
                            node_results.extend(artifact_data["node_results"])
        return node_results

    def test_workflow_completes_with_5_nodes(self) -> None:
        """验证 5 节点 DAG 全部 completed。"""
        with patch.object(weather_engine_service, "_client", _FakeOpenMeteoClient()):
            run_id = self._submit_workflow()
            status_resp = submission_service.get_workflow_run(run_id)

        self.assertIsNotNone(status_resp)
        self.assertIn(status_resp.status, ("succeeded", "completed"))
        self.assertEqual(status_resp.progress, 100)

        # 从 diagnostics 提取 engine_node_count
        diag_text = "\n".join(status_resp.diagnostics or [])
        import re
        m = re.search(r"engine_node_count=(\d+)", diag_text)
        node_count = int(m.group(1)) if m else None
        self.assertEqual(node_count, 5, f"diagnostics: {diag_text}")

    def test_workflow_entry_name_passthrough(self) -> None:
        """验证 workflow_entry_name 透传正确。"""
        with patch.object(weather_engine_service, "_client", _FakeOpenMeteoClient()):
            run_id = self._submit_workflow()
            status_resp = submission_service.get_workflow_run(run_id)

        result_dto = status_resp.result_dto
        if hasattr(result_dto, "model_dump"):
            result_dto_dict = result_dto.model_dump(mode="json")
        elif isinstance(result_dto, dict):
            result_dto_dict = result_dto
        else:
            result_dto_dict = {}

        self.assertEqual(
            result_dto_dict.get("workflow_entry_name"),
            "weather-3-render-e2e",
        )

    def test_all_nodes_completed(self) -> None:
        """验证 5 个节点全部 completed。"""
        with patch.object(weather_engine_service, "_client", _FakeOpenMeteoClient()):
            run_id = self._submit_workflow()
            status_resp = submission_service.get_workflow_run(run_id)

        node_results = self._extract_node_results(status_resp.result_refs)
        self.assertEqual(len(node_results), 5)

        completed = [nr for nr in node_results if nr.get("status") == "completed"]
        self.assertEqual(len(completed), 5,
                         f"node statuses: {[nr.get('status') for nr in node_results]}")

    def test_render_nodes_have_outputs(self) -> None:
        """验证 3 个 render 节点都有 outputs（消费上游 weather_point）。"""
        with patch.object(weather_engine_service, "_client", _FakeOpenMeteoClient()):
            run_id = self._submit_workflow()
            status_resp = submission_service.get_workflow_run(run_id)

        node_results = self._extract_node_results(status_resp.result_refs)
        render_node_ids = {"wind_render", "temp_render", "precip_render"}
        render_nodes = [nr for nr in node_results if nr.get("node_id") in render_node_ids]
        self.assertEqual(len(render_nodes), 3)

        for nr in render_nodes:
            self.assertTrue(nr.get("outputs"),
                            f"node {nr.get('node_id')} has empty outputs")

    def test_fetch_node_has_forecast_output(self) -> None:
        """验证 fetch 节点产出 forecast 输出（含真实 mock 数据）。"""
        with patch.object(weather_engine_service, "_client", _FakeOpenMeteoClient()):
            run_id = self._submit_workflow()
            status_resp = submission_service.get_workflow_run(run_id)

        node_results = self._extract_node_results(status_resp.result_refs)
        fetch_node = next((nr for nr in node_results if nr.get("node_id") == "fetch"), None)
        self.assertIsNotNone(fetch_node)

        fetch_outputs = fetch_node.get("outputs") or {}
        # fetch 节点应有 forecast 输出
        forecast_data = fetch_outputs.get("fetch.forecast") or fetch_outputs.get("forecast") or {}
        if isinstance(forecast_data, dict):
            # 验证含 Open-Meteo 响应字段
            self.assertTrue(
                forecast_data.get("current") or forecast_data.get("hourly"),
                f"forecast missing current/hourly: {list(forecast_data.keys())}",
            )

    def test_parse_node_has_weather_point_output(self) -> None:
        """验证 parse 节点产出 weather_point 输出（被 3 个 render 消费）。"""
        with patch.object(weather_engine_service, "_client", _FakeOpenMeteoClient()):
            run_id = self._submit_workflow()
            status_resp = submission_service.get_workflow_run(run_id)

        node_results = self._extract_node_results(status_resp.result_refs)
        parse_node = next((nr for nr in node_results if nr.get("node_id") == "parse"), None)
        self.assertIsNotNone(parse_node)

        parse_outputs = parse_node.get("outputs") or {}
        output_keys = list(parse_outputs.keys())
        self.assertTrue(
            any("weather_point" in k for k in output_keys),
            f"parse outputs missing weather_point: {output_keys}",
        )

    def test_diagnostics_contains_engine_run_id(self) -> None:
        """验证 diagnostics 含 engine_run_id（标识引擎执行）。"""
        with patch.object(weather_engine_service, "_client", _FakeOpenMeteoClient()):
            run_id = self._submit_workflow()
            status_resp = submission_service.get_workflow_run(run_id)

        diag_text = "\n".join(status_resp.diagnostics or [])
        self.assertIn("engine_run_id=", diag_text)
        self.assertIn("engine_status=", diag_text)


if __name__ == "__main__":
    unittest.main()
