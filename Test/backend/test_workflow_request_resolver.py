from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.workflow_request_resolver import describe_layer_run_readiness


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


if __name__ == "__main__":
    unittest.main()
