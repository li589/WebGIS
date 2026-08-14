from __future__ import annotations

import pytest
from datetime import datetime, timezone
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


def _build_payload(*, layer_id: str = "ndvi") -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        layer_id=layer_id,
        priority=WorkflowPriority.normal,
        requested_outputs=[],
        client=ClientIdentity(client_id="route-test-client"),
        map_context=RuntimeMapContext(active_layer_id=layer_id),
        parameters={"hour": 12},
    )


def test_submit_workflow_route_delegates_without_local_enrichment() -> None:
    payload = _build_payload(layer_id="ndvi")
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

    assert response is accepted, 'response is accepted'
    submit_mock.assert_called_once()
    forwarded_payload = submit_mock.call_args.args[0]
    assert forwarded_payload is payload, 'forwarded_payload is payload'
    algorithm_request = (
        forwarded_payload.algorithm_request
        if isinstance(forwarded_payload.algorithm_request, dict)
        else forwarded_payload.algorithm_request.model_dump(mode="json")
    )
    assert algorithm_request.get("module_name") is None, 'algorithm_request.get("module_name") is None'
    assert algorithm_request.get("workflow_name") is None, 'algorithm_request.get("workflow_name") is None'
    assert algorithm_request.get("workflow_definition") is None, 'algorithm_request.get("workflow_definition") is None'


def test_submit_workflow_route_returns_422_for_validation_error() -> None:
    """提交期预校验失败时，路由应返回 422 + 结构化字段级错误。"""
    payload = _build_payload(layer_id="ndvi")
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
        with pytest.raises(HTTPException) as ctx:
            submit_workflow(payload)

    assert ctx.value.status_code == 422, 'ctx.exception.status_code == 422'
    detail = ctx.value.detail
    assert detail["error_type"] == "validation", 'detail["error_type"] == "validation"'
    assert "user_message" in detail, '"user_message" in detail'
    assert detail["issues"] == issues, 'detail["issues"] == issues'


def test_submit_workflow_route_returns_429_for_capacity_error() -> None:
    """容量超限时仍返回 429（不被 422 校验逻辑拦截）。"""
    payload = _build_payload(layer_id="ndvi")
    with patch.object(
        submission_service,
        "submit_workflow",
        side_effect=ValueError(
            "Workflow capacity reached: active_runs=4, limit=4"
        ),
    ):
        with pytest.raises(HTTPException) as ctx:
            submit_workflow(payload)

    assert ctx.value.status_code == 429, 'ctx.exception.status_code == 429'


def test_list_workflow_events_route_forwards_cursor() -> None:
    from app.services.credential_resolver import CredentialContext

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
    admin_cred = CredentialContext(source="session", role="admin", user_id=1)

    with patch.object(
        submission_service,
        "list_workflow_events",
        return_value=event_response,
    ) as list_mock:
        response = list_workflow_events(
            request,
            "run-route-1",
            after_event_id="evt-1",
            limit=20,
            cred=admin_cred,
        )

    assert response is event_response, 'response is event_response'
    list_mock.assert_called_once_with(
        "run-route-1", after_event_id="evt-1", limit=20
    )
