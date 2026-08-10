from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

from app.services.workflow_request_resolver import (
    describe_layer_run_readiness,
    normalize_workflow_submit_request,
)
from shared.contracts.api_contracts import (
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowSubmitRequest,
)


class WorkflowRequestResolverTests(unittest.TestCase):
    def test_unresolved_default_datasets_remains_blocked(self) -> None:
        # catalog 演进：所有内置图层均已 available（无 placeholder 残留），
        # 改用「默认数据源无法解析 → blocked」路径验证 blocked 语义：
        # patch _resolve_data_access_source_uri 返回 None 使 ref-fy-tb-202512-mwri 默认数据集不可解析。
        with patch(
            "app.services.workflow_request_resolver._resolve_data_access_source_uri",
            return_value=None,
        ):
            readiness = describe_layer_run_readiness("ref-fy-tb-202512-mwri")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "blocked")
        # 数据源未就绪时 describe_layer_run_readiness 追加 “缺少默认数据集” note
        notes_text = "\n".join(readiness["run_readiness_notes"])
        self.assertIn("缺少默认数据集", notes_text)

    def test_normalize_fills_time_range_from_canvas_when_layer_missing(self) -> None:
        """编辑器提交常带 workflow_definition 但 linked_layer 可能不在 catalog。"""
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            command_label="run canvas",
            layer_id="method-smap-omega-doy-dynamic-MISSING",
            map_context=RuntimeMapContext(
                active_layer_id="method-smap-omega-doy-dynamic-MISSING"
            ),
            algorithm_request={
                "workflow_definition": {
                    "nodes": [
                        {
                            "id": 1,
                            "type": "data/time_range",
                            "properties": {
                                "start_at": "2025-12-01T00:00:00",
                                "end_at": "2025-12-31T00:00:00",
                                "granularity": "day",
                            },
                        },
                        {
                            "id": 2,
                            "type": "module/omega_sf_fenkuai",
                            "properties": {
                                "module_name": "omega_sf_fenkuai",
                                "algorithm_params": {"tb_source": "SMAP"},
                            },
                        },
                    ],
                    "links": [],
                },
                "workflow_entry_name": "omega_sf_fenkuai_smap_single",
                "tags": {"workflow_id": "omega_sf_fenkuai_smap_single"},
            },
        )
        with patch(
            "app.services.workflow_request_resolver.get_layer_descriptor",
            return_value=None,
        ):
            normalized = normalize_workflow_submit_request(payload)

        self.assertIsNotNone(normalized.time_range)
        assert normalized.time_range is not None
        self.assertEqual(normalized.time_range.start_at, datetime(2025, 12, 1, 0, 0, 0))
        self.assertEqual(normalized.time_range.end_at, datetime(2025, 12, 31, 0, 0, 0))
        algo = normalized.algorithm_request or {}
        self.assertEqual(algo.get("module_name"), "omega_sf_fenkuai")

    def test_normalize_fills_time_range_from_seed_via_restored_layer(self) -> None:
        """关联图层重新入库后，仅 layer_id 提交也应从种子补齐 time_range。"""
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            command_label="run layer",
            layer_id="method-smap-omega-doy-dynamic",
            map_context=RuntimeMapContext(
                active_layer_id="method-smap-omega-doy-dynamic"
            ),
        )
        normalized = normalize_workflow_submit_request(payload)
        self.assertIsNotNone(normalized.time_range)
        assert normalized.time_range is not None
        self.assertEqual(normalized.time_range.start_at.year, 2025)
        self.assertEqual(normalized.time_range.start_at.month, 12)
        algo = normalized.algorithm_request or {}
        self.assertEqual(algo.get("module_name"), "omega_sf_fenkuai")

    def test_normalize_multi_module_keeps_definition_without_module_name(self) -> None:
        """多模块 DAG 保留 workflow_definition，且不得同时带 module_name（bridge 互斥）。"""
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            command_label="run multi",
            algorithm_request={
                "workflow_definition": {
                    "nodes": [
                        {
                            "id": 1,
                            "type": "stats/histogram",
                            "properties": {"bins": 10},
                        },
                        {
                            "id": 2,
                            "type": "viz/chart_generate",
                            "properties": {"chart_type": "bar"},
                        },
                    ],
                    "links": [[1, 1, 0, 2, 1]],
                }
            },
        )
        with patch(
            "app.services.workflow_request_resolver.get_layer_descriptor",
            return_value=None,
        ):
            # Synthetic descriptor path needs entry keys — workflow_definition present.
            normalized = normalize_workflow_submit_request(payload)
        algo = normalized.algorithm_request or {}
        self.assertIsInstance(algo.get("workflow_definition"), dict)
        self.assertNotIn("module_name", algo)


if __name__ == "__main__":
    unittest.main()
