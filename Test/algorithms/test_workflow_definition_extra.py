"""2026-08-23 修复回归：workflow_definition 的 extra 元数据字段放行。

背景：种子/画布编译产物显式携带 ``extra``（purpose/group_title/output_labels，
2026-08-22 需求2 的前端建组命名依赖），而算法侧 ``_reject_unknown_fields``
白名单缺失 ``extra`` → 静态图层（干旱指数 AI / GOSAT CO₂ / GPCP 月降水）提交
工作流必报 ``Unknown field(s) not allowed: workflow_definition -> extra``。
修复 = 白名单加 extra + decode 并入 metadata 保真透传。
"""

from __future__ import annotations

import unittest

from workflow.serialization import (
    WorkflowDefinitionDecodeError,
    coerce_workflow_definition,
)


def _base_definition(**overrides) -> dict:
    definition = {
        "workflow_id": "static_local_read_aridity",
        "nodes": [
            {
                "node_id": "n1",
                "node_type": "data/source",
                "params": {"path": "{DATA_ROOT}/x.mat"},
            }
        ],
        "edges": [],
        "outputs": [{"name": "result", "source": "node:n1.out"}],
    }
    definition.update(overrides)
    return definition


class WorkflowDefinitionExtraTests(unittest.TestCase):
    def test_extra_field_accepted(self) -> None:
        """核心回归：带 extra 的 definition 不再被拒。"""
        definition = coerce_workflow_definition(
            _base_definition(
                extra={
                    "purpose": "static_local_read",
                    "group_title": "干旱指数 AI",
                    "output_labels": {"result": "干旱指数 AI"},
                }
            )
        )
        self.assertEqual(definition.workflow_id, "static_local_read_aridity")
        # extra 并入 metadata 保真透传
        self.assertEqual(definition.metadata["extra"]["group_title"], "干旱指数 AI")
        self.assertEqual(definition.metadata["extra"]["output_labels"]["result"], "干旱指数 AI")

    def test_extra_null_or_missing_ok(self) -> None:
        definition = coerce_workflow_definition(_base_definition(extra=None))
        self.assertEqual(definition.workflow_id, "static_local_read_aridity")
        self.assertNotIn("extra", definition.metadata)

    def test_unknown_field_still_rejected(self) -> None:
        """白名单外的字段仍拒绝（防回归过度放行）。"""
        with self.assertRaises(WorkflowDefinitionDecodeError):
            coerce_workflow_definition(_base_definition(totally_unknown_field=1))


if __name__ == "__main__":
    unittest.main()
