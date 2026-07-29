from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.routers.workflow_router import (
    submit_workflow,
    list_workflow_events,
    submission_service,
)
from app.services.workflow.submission_service import WorkflowValidationError
from shared.contracts.api_contracts import (
    ClientIdentity,
    RuntimeMapContext,
    WorkflowAcceptedResponse,
    WorkflowCommandType,
    WorkflowEventsResponse,
    WorkflowEvent,
    WorkflowPriority,
    WorkflowSubmitRequest,
)
from shared.contracts.api_contracts import EventChannel


class WorkflowRoutesTests(unittest.TestCase):
    def _build_payload(self, *, layer_id: str = "ndvi") -> WorkflowSubmitRequest:
        return WorkflowSubmitRequest(
            command_type=WorkflowCommandType.analysis,
            layer_id=layer_id,
            priority=WorkflowPriority.normal,
            requested_outputs=[],
            client=ClientIdentity(client_id="route-test-client"),
            map_context=RuntimeMapContext(active_layer_id=layer_id),
            parameters={"hour": 12},
        )

    def test_submit_workflow_route_delegates_without_local_enrichment(self) -> None:
        payload = self._build_payload(layer_id="ndvi")
        accepted = WorkflowAcceptedResponse(
            run_id="run-route-1",
            status="accepted",
            message="accepted",
            created_at=datetime.now(timezone.utc),
            status_url="/workflow-runs/run-route-1",
            events_url="/workflow-runs/run-route-1/events",
        )

        with patch.object(
            submission_service,
            "submit_workflow",
            return_value=accepted,
        ) as submit_mock:
            response = submit_workflow(payload)

        self.assertIs(response, accepted)
        submit_mock.assert_called_once()
        forwarded_payload = submit_mock.call_args.args[0]
        self.assertIs(forwarded_payload, payload)
        algorithm_request = (
            forwarded_payload.algorithm_request
            if isinstance(forwarded_payload.algorithm_request, dict)
            else forwarded_payload.algorithm_request.model_dump(mode="json")
        )
        self.assertIsNone(algorithm_request.get("module_name"))
        self.assertIsNone(algorithm_request.get("workflow_name"))
        self.assertIsNone(algorithm_request.get("workflow_definition"))

    def test_submit_workflow_route_returns_422_for_validation_error(self) -> None:
        """提交期预校验失败时，路由应返回 422 + 结构化字段级错误。"""
        payload = self._build_payload(layer_id="ndvi")
        issues = [
            {
                "field": "datasource_selection.input_dir",
                "message": "Missing required datasource key: 'input_dir'",
            }
        ]
        with patch.object(
            submission_service,
            "submit_workflow",
            side_effect=WorkflowValidationError(issues),
        ):
            with self.assertRaises(HTTPException) as ctx:
                submit_workflow(payload)

        self.assertEqual(ctx.exception.status_code, 422)
        detail = ctx.exception.detail
        self.assertEqual(detail["error_type"], "validation")
        self.assertIn("user_message", detail)
        self.assertEqual(detail["issues"], issues)

    def test_submit_workflow_route_returns_429_for_capacity_error(self) -> None:
        """容量超限时仍返回 429（不被 422 校验逻辑拦截）。"""
        payload = self._build_payload(layer_id="ndvi")
        with patch.object(
            submission_service,
            "submit_workflow",
            side_effect=ValueError(
                "Workflow capacity reached: active_runs=4, limit=4"
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                submit_workflow(payload)

        self.assertEqual(ctx.exception.status_code, 429)

    def test_list_workflow_events_route_forwards_cursor(self) -> None:
        event_response = WorkflowEventsResponse(
            run_id="run-route-1",
            items=[
                WorkflowEvent(
                    event_id="evt-2",
                    run_id="run-route-1",
                    channel=EventChannel.status,
                    message="running",
                    created_at=datetime.now(timezone.utc),
                )
            ],
        )
        request = type(
            "Req",
            (),
            {
                "headers": {},
                "client": type("Client", (), {"host": "127.0.0.1"})(),
            },
        )()

        with patch.object(
            submission_service,
            "list_workflow_events",
            return_value=event_response,
        ) as list_mock:
            response = list_workflow_events(
                request, "run-route-1", after_event_id="evt-1", limit=20
            )

        self.assertIs(response, event_response)
        list_mock.assert_called_once_with(
            "run-route-1", after_event_id="evt-1", limit=20
        )


if __name__ == "__main__":
    unittest.main()
