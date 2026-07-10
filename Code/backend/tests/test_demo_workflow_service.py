from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.services.demo_workflow_service import demo_workflow_service
from shared.contracts.api_contracts import ClientIdentity, RuntimeMapContext, WorkflowCommandType, WorkflowPriority, WorkflowSubmitRequest


class DemoWorkflowServiceTests(unittest.TestCase):
    def test_demo_service_self_identifies_as_legacy_compatibility(self) -> None:
        payload = WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id="wind-field",
            priority=WorkflowPriority.normal,
            requested_outputs=[],
            client=ClientIdentity(client_id="test-client"),
            map_context=RuntimeMapContext(active_layer_id="wind-field"),
            parameters={"hour": 12},
        )

        result = demo_workflow_service.execute(
            run_id="run-demo-compat",
            payload=payload,
            requested_at=datetime.now(timezone.utc),
            event_factory=lambda **kwargs: kwargs,
        )

        self.assertIn("兼容 Demo 工作流执行完成", result.message)
        self.assertIn("legacy_demo_service=true", result.diagnostics)
        self.assertIsNotNone(result.result_dto)
        assert result.result_dto is not None
        self.assertEqual(result.result_dto["compatibility_mode"], "legacy-demo")
        self.assertEqual(result.result_dto["result_category"], "analysis")
        self.assertEqual(result.result_dto["workflow_entry_name"], "demo_workflow")
        self.assertIn("summary", result.result_dto)
        self.assertIn("status_label", result.result_dto)
        self.assertIn("results", result.result_dto)
        self.assertTrue(any(event.get("payload", {}).get("compatibility_mode") == "legacy-demo" for event in result.events))


if __name__ == "__main__":
    unittest.main()
