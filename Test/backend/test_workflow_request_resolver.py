from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.workflow_request_resolver import describe_layer_run_readiness


class WorkflowRequestResolverTests(unittest.TestCase):
    def test_lab_output_is_exposed_as_runnable_sample_provider(self) -> None:
        # catalog 演进：lab-output 现为 status=available（非 sample），
        # summary="实验室自研模型产出就绪。"，notes 为数据源路径。
        # 测试 env 中 LAB_OUTPUT_RASTER 无法解析为真实路径，故 patch 解析器
        # 以验证 catalog 事实（ready + summary/note 文案）。
        with patch(
            "app.services.workflow_request_resolver._resolve_data_access_source_uri",
            return_value="D:/synthetic/LAB_OUTPUT_RASTER",
        ):
            readiness = describe_layer_run_readiness("lab-output")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "ready")
        # catalog summary "实验室自研模型产出就绪。" 命中 "实验" 关键词
        summary = readiness["run_readiness_summary"] or ""
        self.assertTrue(
            "实验" in summary or "联调" in summary,
            msg=f"summary 应包含实验/联调关键词，实际为: {summary!r}",
        )
        # catalog notes 现为数据源路径，校验 Lab_Daily 关键词
        self.assertTrue(
            any(
                "Lab_Daily" in note
                for note in readiness["run_readiness_notes"]
            ),
            msg=f"notes 应包含 Lab_Daily 关键词，实际为: {readiness['run_readiness_notes']!r}",
        )

    def test_placeholder_python_provider_remains_blocked(self) -> None:
        # catalog 演进：ndvi 已从 placeholder 变更为 available，
        # 改用仍处于 placeholder 的 fy-mwri 图层验证 blocked 语义。
        readiness = describe_layer_run_readiness("fy-mwri")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "blocked")
        # 占位图层在 describe_layer_run_readiness 中会追加含 “占位状态”/“尚未接入” 的 note
        notes_text = "\n".join(readiness["run_readiness_notes"])
        self.assertIn("占位状态", notes_text)
        self.assertIn("尚未接入", notes_text)


if __name__ == "__main__":
    unittest.main()
