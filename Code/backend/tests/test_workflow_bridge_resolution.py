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
        message = _explain_no_bridge(_bare_analysis_payload("dem-etopo"))
        self.assertIn("dem-etopo", message)
        self.assertIn("no workflow engine", message.lower())
        self.assertIn("Static overlays", message)

    def test_resolve_channel_raises_readable_error_for_overlay(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_workflow_channel(_bare_analysis_payload("dem-etopo"))
        self.assertIn("dem-etopo", str(ctx.exception))
        self.assertIn("no workflow engine", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
