from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from app.services.weather_bridge_service import WeatherBridgeService
from shared.contracts.api_contracts import (
    ClientIdentity,
    ResultKind,
    RuntimeMapContext,
    WeatherWorkflowRequest,
    WorkflowCommandType,
    WorkflowPriority,
    WorkflowSubmitRequest,
)


def _make_event(
    channel: str = "log",
    message: str = "",
    progress: int = 0,
    payload: dict | None = None,
):
    from shared.contracts.api_contracts import EventChannel, LogLevel, WorkflowEvent

    return WorkflowEvent(
        event_id=f"evt-{channel}",
        run_id="run-test",
        channel=EventChannel(channel),
        level=LogLevel.info,
        message=message,
        created_at=datetime.now(timezone.utc),
        progress=progress,
        payload=payload or {},
    )


class _FakeRunResult:
    """模拟 RunResult，避免依赖完整的工作流执行。"""

    def __init__(
        self,
        status="completed",
        outputs=None,
        errors=None,
        warnings=None,
        node_results=None,
    ):
        self.run_id = "weather-run-1"
        self.workflow_id = "test-weather-workflow"
        self.status = (
            type("FakeStatus", (), {"value": status})()
            if isinstance(status, str)
            else status
        )
        self.outputs = outputs or {"n1.summary": "test summary"}
        self.errors = errors or []
        self.warnings = warnings or []
        self.node_results = node_results or []
        self.artifacts = []


class _FakeNodeResult:
    def __init__(self, node_id="n1", status="completed", outputs=None, warnings=None):
        self.node_id = node_id
        self.status = (
            type("FakeStatus", (), {"value": status})()
            if isinstance(status, str)
            else status
        )
        self.outputs = outputs or {}
        self.warnings = warnings or []


def _make_payload(
    weather_request: WeatherWorkflowRequest | dict | None
) -> WorkflowSubmitRequest:
    return WorkflowSubmitRequest(
        command_type=WorkflowCommandType.custom,
        layer_id="wind-field",
        priority=WorkflowPriority.normal,
        client=ClientIdentity(client_id="test-client"),
        map_context=RuntimeMapContext(active_layer_id="wind-field"),
        weather_request=weather_request,
    )


def test_supports_returns_false_when_disabled() -> None:
    with patch("app.services.weather_bridge_service.settings") as mock_settings:
        mock_settings.weather_workflow_enabled = False
        service = WeatherBridgeService()
        payload = _make_payload(
            WeatherWorkflowRequest(workflow={"workflow_id": "x", "nodes": []})
        )
        assert not service.supports(payload), 'service.supports(payload) is falsy'


def test_supports_returns_false_when_weather_request_none() -> None:
    service = WeatherBridgeService()
    payload = _make_payload(None)
    assert not service.supports(payload), 'service.supports(payload) is falsy'


def test_supports_returns_true_when_workflow_provided() -> None:
    service = WeatherBridgeService()
    payload = _make_payload(
        WeatherWorkflowRequest(workflow={"workflow_id": "x", "nodes": []})
    )
    assert service.supports(payload), 'service.supports(payload) is truthy'


def test_execute_workflow_returns_mapped_result() -> None:
    service = WeatherBridgeService()
    fake_result = _FakeRunResult(
        outputs={
            "n1.summary": "风速 5.2 m/s",
            "n1.diagnostics": ["provider=open-meteo-online"],
        },
        node_results=[
            _FakeNodeResult(node_id="n1", outputs={"summary": "风速 5.2 m/s"})
        ],
    )
    fake_service = type(
        "FakeService",
        (),
        {
            "execute_workflow": lambda self, workflow, context: fake_result,
            "diagnose": lambda self: {
                "status": "ok",
                "node_registry": {
                    "status": "ok",
                    "supported_node_types": ["weather_forecast_fetch"],
                },
            },
        },
    )()
    with patch.object(service, "_get_service", return_value=fake_service):
        payload = _make_payload(
            WeatherWorkflowRequest(
                workflow={
                    "workflow_id": "test-weather-wf",
                    "nodes": [
                        {
                            "node_id": "n1",
                            "node_type": "weather_summary_generate",
                            "params": {},
                        }
                    ],
                },
                workflow_id="test-weather-wf",
            )
        )
        result = service.execute(
            run_id="run-12345678",
            payload=payload,
            requested_at=datetime.now(timezone.utc),
            event_factory=_make_event,
        )
    assert "天气工作流" in result.message, '"天气工作流" in result.message'
    assert len(result.result_refs) == 1, 'len(result.result_refs) == 1'
    assert result.result_refs[0].result_kind == ResultKind.json, 'result.result_refs[0].result_kind == ResultKind.json'
    assert result.result_dto["workflow_entry_name"] == "test-weather-wf", 'result.result_dto["workflow_entry_name"] == "test-weather-wf"'
    assert any("weather_bridge_service" in d for d in result.diagnostics), 'any("weather_bridge_service" in d for d in result.diagnostics) is truthy'
    assert len(result.events) == 2, 'len(result.events) == 2'


def test_list_workflows_response_returns_node_types() -> None:
    service = WeatherBridgeService()
    fake_service = type(
        "FakeService",
        (),
        {
            "diagnose": lambda self: {
                "status": "ok",
                "node_registry": {
                    "status": "ok",
                    "supported_node_types": [
                        "weather_forecast_fetch",
                        "weather_point_parse",
                        "weather_wind_field",
                    ],
                },
            },
        },
    )()
    with patch.object(service, "_get_service", return_value=fake_service):
        response = service.list_workflows_response()
    assert response["status_code"] == 200, 'response["status_code"] == 200'
    assert response["body"]["source"] == "weatherengine", 'response["body"]["source"] == "weatherengine"'
    assert response["body"]["workflow_count"] == 3, 'response["body"]["workflow_count"] == 3'
    names = [w["name"] for w in response["body"]["workflows"]]
    assert "weather_forecast_fetch" in names, '"weather_forecast_fetch" in names'


def test_describe_workflow_returns_404_for_unknown() -> None:
    service = WeatherBridgeService()
    fake_service = type(
        "FakeService",
        (),
        {
            "diagnose": lambda self: {
                "status": "ok",
                "node_registry": {
                    "status": "ok",
                    "supported_node_types": ["weather_forecast_fetch"],
                },
            },
        },
    )()
    with patch.object(service, "_get_service", return_value=fake_service):
        response = service.describe_workflow_response("nonexistent_node")
    assert response["status_code"] == 404, 'response["status_code"] == 404'
    assert response["body"]["error_code"] == "weather_workflow_not_found", 'response["body"]["error_code"] == "weather_workflow_not_found"'
