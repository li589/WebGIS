from __future__ import annotations

import unittest

from app.services.workflow_request_resolver import describe_layer_run_readiness


class WorkflowRequestResolverTests(unittest.TestCase):
    def test_lab_output_is_exposed_as_runnable_sample_provider(self) -> None:
        readiness = describe_layer_run_readiness("lab-output")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "ready")
        # P3.2 文案更新：“样板” → “实验”。这里允许 “实验” 或 “联调” 关键词命中。
        summary = readiness["run_readiness_summary"] or ""
        self.assertTrue(
            "实验" in summary or "联调" in summary,
            msg=f"summary 应包含实验/联调关键词，实际为: {summary!r}",
        )
        # 既有 note 仍包含 “样板” 或 “实验” 关键词
        self.assertTrue(
            any(
                "样板" in note or "实验" in note
                for note in readiness["run_readiness_notes"]
            ),
            msg=f"notes 应包含样板/实验关键词，实际为: {readiness['run_readiness_notes']!r}",
        )

    def test_placeholder_python_provider_remains_blocked(self) -> None:
        # P2.2 修复后 smap-soil 已从 placeholder 变更为 available，
        # 这里改用仍处于 placeholder 的 ndvi 图层验证 blocked 语义。
        readiness = describe_layer_run_readiness("ndvi")

        self.assertIsNotNone(readiness)
        self.assertEqual(readiness["run_readiness"], "blocked")
        # 占位图层在 describe_layer_run_readiness 中会追加含 “占位状态”/“尚未接入” 的 note
        notes_text = "\n".join(readiness["run_readiness_notes"])
        self.assertIn("占位状态", notes_text)
        self.assertIn("尚未接入", notes_text)


if __name__ == "__main__":
    unittest.main()
