from __future__ import annotations

from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from app.services.gee_bridge_service import GeeBridgeService
from shared.contracts.api_contracts import (
    ClientIdentity,
    GeeWorkflowRequest,
    ResultKind,
    RuntimeMapContext,
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
    # 复用 WorkflowEvent 的最小构造，避免依赖 interaction_hub 的 event_factory
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


class _FakeArtifact:
    def __init__(
        self,
        artifact_id: str,
        storage_uri: str,
        content_type: str = "image/tiff",
        size: int = 1024,
        artifact_type: str = "raster",
    ):
        self.artifact_id = artifact_id
        self.storage_uri = storage_uri
        self.content_type = content_type
        self.size = size
        self.artifact_type = artifact_type

    def model_dump(self, mode: str = "python"):
        return {
            "artifact_id": self.artifact_id,
            "storage_uri": self.storage_uri,
            "content_type": self.content_type,
            "size": self.size,
            "artifact_type": self.artifact_type,
        }


class _FakeSavebackPlan:
    def model_dump(self, mode: str = "python"):
        return {"action": "monitor_only", "reasons": [], "summary": {}}


class _FakeExecutionResponse:
    def __init__(
        self, status: str = "completed", artifacts=None, warnings=None, errors=None
    ):
        self.run_id = "gee-run-1"
        self.workflow_id = "demo-workflow"
        self.status = status
        self.node_results = [{"node_id": "n1", "status": status}]
        self.outputs = {"n1.value": "ok"}
        self.artifacts = artifacts or []
        self.warnings = warnings or []
        self.errors = errors or []
        self.saveback_terminal_plan = _FakeSavebackPlan()
        self.saveback_terminal_plans = {}


class _FakeExportStatusResponse:
    def __init__(self, status: str = "manifest_created", state: str = "LOCAL_ONLY"):
        self.status = status
        self.state = state
        self.task_id = None
        self.started = False
        self.manifest_uri = "file:///tmp/exports/demo.json"
        self.polled_at = None
        self.error_message = None
        self.raw = None

    def model_dump(self, mode: str = "json"):
        return {
            "status": self.status,
            "state": self.state,
            "task_id": self.task_id,
            "started": self.started,
            "manifest_uri": self.manifest_uri,
            "polled_at": self.polled_at,
            "error_message": self.error_message,
            "raw": self.raw,
        }


class _FakeFacade:
    def __init__(self, response=None, export_response=None):
        self.submit_workflow_calls = []
        self._response = response or _FakeExecutionResponse()
        self._export_response = export_response or _FakeExportStatusResponse()

    def submit_workflow(self, workflow, context=None):
        self.submit_workflow_calls.append({"workflow": workflow, "context": context})
        return self._response

    def get_export_task_status(
        self, manifest_uri, *, update_manifest=False, gee_module=None
    ):
        return self._export_response


class GeeBridgeServiceTests(unittest.TestCase):
    def _make_payload(
        self, gee_request: GeeWorkflowRequest | dict | None
    ) -> WorkflowSubmitRequest:
        return WorkflowSubmitRequest(
            command_type=WorkflowCommandType.custom,
            layer_id="gee-demo",
            priority=WorkflowPriority.normal,
            client=ClientIdentity(client_id="test-client"),
            map_context=RuntimeMapContext(active_layer_id="gee-demo"),
            gee_request=gee_request,
        )

    def test_supports_returns_false_when_gee_disabled(self) -> None:
        with patch("app.services.gee_bridge_service.settings") as mock_settings:
            mock_settings.gee_enabled = False
            service = GeeBridgeService()
            payload = self._make_payload(
                GeeWorkflowRequest(workflow={"workflow_id": "x", "nodes": []})
            )
            self.assertFalse(service.supports(payload))

    def test_supports_returns_false_when_gee_request_none(self) -> None:
        service = GeeBridgeService()
        payload = self._make_payload(None)
        self.assertFalse(service.supports(payload))

    def test_supports_returns_true_when_workflow_provided(self) -> None:
        service = GeeBridgeService()
        payload = self._make_payload(
            GeeWorkflowRequest(workflow={"workflow_id": "x", "nodes": []})
        )
        self.assertTrue(service.supports(payload))

    def test_execute_workflow_returns_mapped_result(self) -> None:
        service = GeeBridgeService()
        fake_facade = _FakeFacade(
            response=_FakeExecutionResponse(
                artifacts=[_FakeArtifact("a1", "file:///tmp/a1.tif")]
            )
        )
        with patch.object(service, "_get_facade", return_value=fake_facade):
            payload = self._make_payload(
                GeeWorkflowRequest(
                    workflow={
                        "workflow_id": "demo",
                        "nodes": [
                            {
                                "node_id": "n1",
                                "node_type": "literal",
                                "params": {"value": "ok"},
                            }
                        ],
                    },
                )
            )
            result = service.execute(
                run_id="run-12345678",
                payload=payload,
                requested_at=datetime.now(timezone.utc),
                event_factory=_make_event,
            )
        self.assertIn("GEE 工作流", result.message)
        self.assertEqual(len(result.result_refs), 2)  # 1 json + 1 artifact
        self.assertEqual(result.result_refs[0].result_kind, ResultKind.json)
        self.assertEqual(result.result_refs[1].result_kind, ResultKind.file)
        self.assertEqual(result.result_refs[1].resource_url, "file:///tmp/a1.tif")
        self.assertEqual(result.result_dto["workflow_entry_name"], "demo-workflow")
        self.assertEqual(result.result_dto["job_status"], "completed")
        self.assertTrue(any("gee_bridge_service" in d for d in result.diagnostics))
        self.assertEqual(len(result.events), 2)

    def test_execute_export_poll_returns_status(self) -> None:
        service = GeeBridgeService()
        fake_facade = _FakeFacade(
            export_response=_FakeExportStatusResponse(status="running", state="RUNNING")
        )
        with patch.object(service, "_get_facade", return_value=fake_facade):
            payload = self._make_payload(
                GeeWorkflowRequest(
                    manifest_uri="file:///tmp/exports/demo.json", update_manifest=True
                )
            )
            result = service.execute(
                run_id="run-poll1234",
                payload=payload,
                requested_at=datetime.now(timezone.utc),
                event_factory=_make_event,
            )
        self.assertIn("GEE 导出状态查询完成", result.message)
        self.assertEqual(len(result.result_refs), 1)
        self.assertEqual(result.result_refs[0].inline_data["status"], "running")
        self.assertEqual(result.result_dto["export_status"], "running")
        self.assertEqual(result.result_dto["update_manifest"], True)

    def test_list_workflows_response_returns_node_registry(self) -> None:
        service = GeeBridgeService()

        class _FakeReport:
            def __init__(self):
                self.status = "ok"
                self.checks = {
                    "node_registry": {
                        "status": "ok",
                        "supported_node_types": [
                            "literal",
                            "gee_image",
                            "gee_export_image",
                        ],
                    }
                }
                self.warnings = []

            def model_dump(self, mode: str = "json"):
                return {
                    "status": self.status,
                    "checks": self.checks,
                    "warnings": self.warnings,
                }

        fake_facade = _FakeFacade()
        fake_facade.diagnose = lambda: _FakeReport()
        with patch.object(service, "_get_facade", return_value=fake_facade):
            response = service.list_workflows_response()
        self.assertEqual(response["status_code"], 200)
        self.assertEqual(response["body"]["source"], "webgis_gee")
        self.assertEqual(response["body"]["workflow_count"], 3)
        names = [w["name"] for w in response["body"]["workflows"]]
        self.assertIn("literal", names)
        self.assertIn("gee_image", names)

    def test_describe_workflow_returns_404_for_unknown(self) -> None:
        service = GeeBridgeService()

        class _FakeReport:
            def __init__(self):
                self.status = "ok"
                self.checks = {
                    "node_registry": {
                        "status": "ok",
                        "supported_node_types": ["literal"],
                    }
                }
                self.warnings = []

            def model_dump(self, mode: str = "json"):
                return {
                    "status": self.status,
                    "checks": self.checks,
                    "warnings": self.warnings,
                }

        fake_facade = _FakeFacade()
        fake_facade.diagnose = lambda: _FakeReport()
        with patch.object(service, "_get_facade", return_value=fake_facade):
            response = service.describe_workflow_response("nonexistent_node")
        self.assertEqual(response["status_code"], 404)
        self.assertEqual(response["body"]["error_code"], "gee_workflow_not_found")


if __name__ == "__main__":
    unittest.main()
