from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from app.api import routes
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

        with patch("app.api.routes.interaction_hub.submit_workflow", return_value=accepted) as submit_mock:
            response = routes.submit_workflow(payload)

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

        with patch("app.api.routes.interaction_hub.list_workflow_events", return_value=event_response) as list_mock:
            response = routes.list_workflow_events(request, "run-route-1", after_event_id="evt-1", limit=20)

        self.assertIs(response, event_response)
        list_mock.assert_called_once_with("run-route-1", after_event_id="evt-1", limit=20)


if __name__ == "__main__":
    unittest.main()
