from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.workflow_request_resolver import describe_layer_run_readiness


class WorkflowRequestResolverTests(unittest.TestCase):
    def test_lab_output_is_exposed_as_available_provider(self) -> None:
        # catalog 演进：lab-output 现为 status=available（非 sample/placeholder），
        # summary="课题组模型产出按 Inversion_Results 解析"，notes 为数据源路径。
        # 测试 env 中 LAB_OUTPUT_RASTER 无法解析为真实路径，故 patch 解析器
        # 以验证 catalog 事实（ready + summary/note 文案）。
        with patch(
            "app.services.workflow_request_resolver._resolve_data_access_source_uri",
            return_value="D:/synthetic/LAB_OUTPUT_RASTER",
        ):
            readiness = describe_layer_run_readiness("lab-output")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "ready")
        # catalog summary "课题组模型产出按 Inversion_Results 解析"
        summary = readiness["run_readiness_summary"] or ""
        self.assertTrue(
            "Inversion_Results" in summary,
            msg=f"summary 应包含 Inversion_Results 关键词，实际为: {summary!r}",
        )
        # catalog notes 现为数据源路径，校验 Inversion_Results/smap_avg 关键词
        self.assertTrue(
            any(
                "Inversion_Results/smap_avg" in note
                for note in readiness["run_readiness_notes"]
            ),
            msg=f"notes 应包含 Inversion_Results/smap_avg 关键词，实际为: {readiness['run_readiness_notes']!r}",
        )

    def test_unresolved_default_datasets_remains_blocked(self) -> None:
        # catalog 演进：所有内置图层均已 available（无 placeholder 残留），
        # 改用「默认数据源无法解析 → blocked」路径验证 blocked 语义：
        # patch _resolve_data_access_source_uri 返回 None 使 fy-mwri 默认数据集不可解析。
        with patch(
            "app.services.workflow_request_resolver._resolve_data_access_source_uri",
            return_value=None,
        ):
            readiness = describe_layer_run_readiness("fy-mwri")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "blocked")
        # 数据源未就绪时 describe_layer_run_readiness 追加 “缺少默认数据集” note
        notes_text = "\n".join(readiness["run_readiness_notes"])
        self.assertIn("缺少默认数据集", notes_text)


if __name__ == "__main__":
    unittest.main()
