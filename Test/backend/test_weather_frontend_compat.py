"""weather 前端 dataState 兼容性测试。

模拟前端 runWorkflowForCatalog 的 payload（不带 weather_request.workflow，走 fallback 路径），
验证 result_refs 包含 map_layer 类型，且 inline_data 含前端期望的
render_hint / point_feature / layer_assets 字段。
mock Open-Meteo API 避免网络依赖。
"""

from __future__ import annotations

import json
import os
import shutil
import unittest
from typing import Any

from app.services.workflow.service_container import submission_service
from app.weatherengine.provider_registry import get_registry
from app.weatherengine.providers.open_meteo_provider import OpenMeteoProvider
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

    def fetch_grid_forecast(
        self,
        *,
        bbox,
        resolution: float,
        layer_spec,
        model: str,
        ttl_seconds: int,
        pressure_levels: tuple[int, ...] | None = None,
    ) -> tuple[dict[str, Any], str]:
        return (
            {
                "grid": {
                    "bbox": {
                        "west": bbox.west,
                        "south": bbox.south,
                        "east": bbox.east,
                        "north": bbox.north,
                    },
                    "rows": 2,
                    "cols": 2,
                    "resolution": resolution,
                    "lats": [bbox.south + 0.25, bbox.south + 0.75],
                    "lons": [bbox.west + 0.25, bbox.west + 0.75],
                },
                "data": {
                    "current": {
                        "temperature_2m": [26.1, 27.4, 28.2, 29.0],
                        "precipitation": [0.3, 1.1, 2.4, 0.8],
                        "relative_humidity_2m": [65.0, 72.0, 78.0, 81.0],
                        "pressure_msl": [1008.5, 1009.1, 1010.2, 1011.4],
                        "visibility": [9000.0, 8500.0, 7800.0, 7200.0],
                        "wind_speed_10m": [8.2, 7.9, 7.3, 6.8],
                        "wind_direction_10m": [154.0, 150.0, 148.0, 145.0],
                        "wind_gusts_10m": [12.6, 11.8, 11.0, 10.2],
                    }
                },
            },
            "hit",
        )


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
            "time": [
                "2026-07-06T00:00",
                "2026-07-06T01:00",
                "2026-07-06T02:00",
                "2026-07-06T03:00",
                "2026-07-06T04:00",
                "2026-07-06T05:00",
            ],
            "temperature_2m": [25.7, 25.3, 24.9, 24.5, 24.1, 23.8],
            "precipitation": [0.2, 0.7, 0.0, 0.0, 0.1, 0.3],
            "wind_speed_10m": [13.2, 12.9, 13.2, 12.5, 11.8, 11.1],
        },
    }


class WeatherFrontendCompatTests(unittest.TestCase):
    """验证 fallback 路径产出的 map_layer ref 符合前端 extractMapLayerPayload 期望。"""

    @classmethod
    def setUpClass(cls) -> None:
        # 全链路经 fetch_gateway / Registry；注入 Fake 底层 client
        registry = get_registry()
        registry.register(
            OpenMeteoProvider(client=_FakeOpenMeteoClient()),
            priority=0,
            enabled=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        get_registry().clear()

    def setUp(self) -> None:
        cache_dir = os.path.join(os.getcwd(), ".data", "cache", "weatherengine")
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)
        # 确保每测用例仍启用 open-meteo-online（防止其他测试禁用后遗留）
        get_registry().set_enabled("open-meteo-online", True)

    def _submit_fallback_workflow(self, layer_id: str) -> str:
        """模拟前端 runWorkflowForCatalog 提交（无 weather_request.workflow，走 fallback）。"""
        payload = WorkflowSubmitRequest(
            command_type="analysis",
            command_label=f"运行 {layer_id} 分析",
            layer_id=layer_id,
            requested_outputs=["json", "text", "table", "map_layer"],
            parameters={"hour": 0},
            client={"page": "dashboard", "view_id": "map-2d"},
            map_context={"active_layer_id": layer_id, "map_mode": "2d"},
        )
        accepted = submission_service.submit_workflow(payload)
        return accepted.run_id

    def _find_map_layer_ref(self, result_refs) -> dict | None:
        """从 result_refs 中找到 map_layer 类型的 ref，处理 spill 情况。

        兼容本地文件存储和 MinIO 对象存储后端：
        - 本地后端：artifact.file_path 指向磁盘文件
        - MinIO 后端：file_path 为 None，需通过 fetch_artifact_bytes 读取
        """
        from app.services.result_storage import result_storage_service

        for ref in result_refs:
            ref_dict = (
                ref.model_dump(mode="json") if hasattr(ref, "model_dump") else dict(ref)
            )
            if ref_dict.get("result_kind") != "map_layer":
                continue
            inline = ref_dict.get("inline_data") or {}
            if not inline:
                # spill 到 artifact storage（兼容 local 和 minio 后端）
                resource_key = ref_dict.get("resource_key")
                if resource_key:
                    raw_bytes = result_storage_service.fetch_artifact_bytes(
                        resource_key
                    )
                    if raw_bytes is not None:
                        inline = json.loads(raw_bytes.decode("utf-8"))
            if inline:
                return inline
        return None

    def test_wind_field_map_layer_ref(self) -> None:
        """验证 wind-field 图层的 map_layer ref 格式。"""
        run_id = self._submit_fallback_workflow("wind-field")
        status_resp = submission_service.get_workflow_run(run_id)

        self.assertIn(status_resp.status, ("succeeded", "completed"))

        # 必须有 map_layer 类型 ref
        ref_kinds = []
        for ref in status_resp.result_refs:
            ref_dict = (
                ref.model_dump(mode="json") if hasattr(ref, "model_dump") else dict(ref)
            )
            ref_kinds.append(ref_dict.get("result_kind"))
        self.assertIn("map_layer", ref_kinds, f"result_refs kinds: {ref_kinds}")

        inline = self._find_map_layer_ref(status_resp.result_refs)
        self.assertIsNotNone(inline, "未找到 map_layer ref 的 inline_data")

        # render_hint 字段（前端 WeatherLayerRenderHint 期望）
        render_hint = inline.get("render_hint") or {}
        self.assertEqual(render_hint.get("paint_mode"), "particle_flow")
        self.assertEqual(render_hint.get("palette"), "wind-blue")
        self.assertEqual(render_hint.get("primary_metric"), "wind_speed_10m")
        self.assertEqual(render_hint.get("unit_label"), "m/s")

        # point_feature
        point_feature = inline.get("point_feature") or {}
        self.assertEqual(point_feature.get("type"), "Feature")
        geometry = point_feature.get("geometry") or {}
        self.assertEqual(geometry.get("type"), "Point")

        # layer_assets（wind-field 应有 geojson_url，无 cog_url）
        layer_assets = inline.get("layer_assets") or {}
        self.assertTrue(layer_assets.get("geojson_url"), "missing geojson_url")

    def test_temperature_map_layer_ref(self) -> None:
        """验证 temperature 图层的 map_layer ref 格式（含 COG）。"""
        run_id = self._submit_fallback_workflow("temperature")
        status_resp = submission_service.get_workflow_run(run_id)

        self.assertIn(status_resp.status, ("succeeded", "completed"))

        inline = self._find_map_layer_ref(status_resp.result_refs)
        self.assertIsNotNone(inline, "未找到 map_layer ref 的 inline_data")

        render_hint = inline.get("render_hint") or {}
        self.assertEqual(render_hint.get("paint_mode"), "heatmap")
        self.assertEqual(render_hint.get("palette"), "thermal-orange")
        self.assertEqual(render_hint.get("primary_metric"), "temperature_2m")
        self.assertEqual(render_hint.get("unit_label"), "C")

        # layer_assets（temperature 应有 geojson_url + cog_url + cog_bbox）
        layer_assets = inline.get("layer_assets") or {}
        self.assertTrue(layer_assets.get("geojson_url"), "missing geojson_url")
        self.assertTrue(layer_assets.get("cog_url"), "missing cog_url")

        cog_bbox = layer_assets.get("cog_bbox") or {}
        self.assertIsNotNone(cog_bbox.get("west"), "missing cog_bbox.west")
        self.assertIsNotNone(cog_bbox.get("south"), "missing cog_bbox.south")
        self.assertIsNotNone(cog_bbox.get("east"), "missing cog_bbox.east")
        self.assertIsNotNone(cog_bbox.get("north"), "missing cog_bbox.north")
        self.assertEqual(cog_bbox.get("crs"), "EPSG:4326")

    def test_precipitation_map_layer_ref(self) -> None:
        """验证 precipitation 图层的 map_layer ref 格式（含 COG）。"""
        run_id = self._submit_fallback_workflow("precipitation")
        status_resp = submission_service.get_workflow_run(run_id)

        self.assertIn(status_resp.status, ("succeeded", "completed"))

        inline = self._find_map_layer_ref(status_resp.result_refs)
        self.assertIsNotNone(inline, "未找到 map_layer ref 的 inline_data")

        render_hint = inline.get("render_hint") or {}
        self.assertEqual(render_hint.get("paint_mode"), "heatmap")
        self.assertEqual(render_hint.get("palette"), "precip-cyan")
        self.assertEqual(render_hint.get("primary_metric"), "precipitation")
        self.assertEqual(render_hint.get("unit_label"), "mm")

        layer_assets = inline.get("layer_assets") or {}
        self.assertTrue(layer_assets.get("geojson_url"), "missing geojson_url")
        self.assertTrue(layer_assets.get("cog_url"), "missing cog_url")

        cog_bbox = layer_assets.get("cog_bbox") or {}
        self.assertIsNotNone(cog_bbox.get("west"))
        self.assertEqual(cog_bbox.get("crs"), "EPSG:4326")

    def _assert_geojson_only_grid_layer(
        self,
        *,
        layer_id: str,
        expected_palette: str,
        expected_metric: str,
        expected_unit: str,
    ) -> None:
        run_id = self._submit_fallback_workflow(layer_id)
        status_resp = submission_service.get_workflow_run(run_id)

        self.assertIn(status_resp.status, ("succeeded", "completed"))

        inline = self._find_map_layer_ref(status_resp.result_refs)
        self.assertIsNotNone(inline, f"{layer_id} 未找到 map_layer ref 的 inline_data")

        render_hint = inline.get("render_hint") or {}
        self.assertEqual(render_hint.get("paint_mode"), "grid_fill")
        self.assertEqual(render_hint.get("palette"), expected_palette)
        self.assertEqual(render_hint.get("primary_metric"), expected_metric)
        self.assertEqual(render_hint.get("unit_label"), expected_unit)

        layer_assets = inline.get("layer_assets") or {}
        self.assertTrue(
            layer_assets.get("geojson_url"), f"{layer_id} missing geojson_url"
        )
        self.assertFalse(
            layer_assets.get("cog_url"), f"{layer_id} should not include cog_url"
        )
        self.assertFalse(
            layer_assets.get("cog_preview_url"),
            f"{layer_id} should not include cog_preview_url",
        )

    def test_pressure_map_layer_ref(self) -> None:
        self._assert_geojson_only_grid_layer(
            layer_id="pressure",
            expected_palette="pressure-purple",
            expected_metric="pressure_msl",
            expected_unit="hPa",
        )

    def test_humidity_map_layer_ref(self) -> None:
        self._assert_geojson_only_grid_layer(
            layer_id="humidity",
            expected_palette="humidity-green",
            expected_metric="relative_humidity_2m",
            expected_unit="%",
        )

    def test_visibility_map_layer_ref(self) -> None:
        self._assert_geojson_only_grid_layer(
            layer_id="visibility",
            expected_palette="visibility-amber",
            expected_metric="visibility",
            expected_unit="m",
        )

    def test_all_weather_layers_succeed(self) -> None:
        """验证所有 weather 图层 fallback 路径全部成功。"""
        for layer_id in (
            "wind-field",
            "temperature",
            "precipitation",
            "pressure",
            "humidity",
            "visibility",
        ):
            run_id = self._submit_fallback_workflow(layer_id)
            status_resp = submission_service.get_workflow_run(run_id)
            self.assertIn(
                status_resp.status,
                ("succeeded", "completed"),
                f"{layer_id} failed: {status_resp.status}",
            )
            self.assertEqual(status_resp.progress, 100)

            # 验证 result_refs 含 map_layer
            ref_kinds = []
            for ref in status_resp.result_refs:
                ref_dict = (
                    ref.model_dump(mode="json")
                    if hasattr(ref, "model_dump")
                    else dict(ref)
                )
                ref_kinds.append(ref_dict.get("result_kind"))
            self.assertIn("map_layer", ref_kinds, f"{layer_id} missing map_layer ref")


if __name__ == "__main__":
    unittest.main()
