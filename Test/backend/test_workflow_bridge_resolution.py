from __future__ import annotations

import unittest

from app.tasks.workflow_tasks import _explain_no_bridge, resolve_workflow_channel
from shared.contracts.api_contracts import (
    ClientIdentity,
    RuntimeMapContext,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


def _bare_analysis_payload(layer_id: str) -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        command_label=f"test {layer_id}",
        layer_id=layer_id,
        priority=WorkflowPriority.normal,
        requested_outputs=["json"],
        client=ClientIdentity(client_id="test-client"),
        map_context=RuntimeMapContext(active_layer_id=layer_id),
    )


class WorkflowBridgeResolutionTests(unittest.TestCase):
    def test_overlay_without_engine_explains_static_layer(self) -> None:
        # catalog 演进：dem-etopo 已绑定 engine=overlay_registry。
        # 校验 engine 已配置但未命中 bridge 的可读说明。
        message = _explain_no_bridge(_bare_analysis_payload("dem-etopo"))
        self.assertIn("ETOPO", message)  # display_name（用户提交 4587c70 改为「ETOPO 地形高程」）
        self.assertIn("overlay_registry", message)
        self.assertIn("did not match", message)

    def test_resolve_channel_raises_readable_error_for_overlay(self) -> None:
        # dem-etopo 现有 engine，但仍无 bridge 匹配 → 可读错误说明 engine 未命中。
        with self.assertRaises(ValueError) as ctx:
            resolve_workflow_channel(_bare_analysis_payload("dem-etopo"))
        self.assertIn("ETOPO", str(ctx.exception))
        self.assertIn("did not match", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
