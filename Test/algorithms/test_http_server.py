from __future__ import annotations

import http.client
import json
import threading
import unittest

from service.http_server import create_server
from service.job_api import ServiceResponse


class _FakeJobService:
    def __init__(self) -> None:
        self.submitted_payloads: list[object] = []
        self.async_submitted_payloads: list[object] = []
        self.validated_payloads: list[object] = []

    def get_health_response(self) -> ServiceResponse:
        return ServiceResponse(200, {"status": "ok"})

    def get_job_request_schema_response(self) -> ServiceResponse:
        return ServiceResponse(200, {"title": "JobRequest"})

    def get_workflow_definition_schema_response(self) -> ServiceResponse:
        return ServiceResponse(200, {"title": "WorkflowDefinition"})

    def submit_job(self, payload: object) -> ServiceResponse:
        self.submitted_payloads.append(payload)
        return ServiceResponse(200, {"accepted": True})

    def submit_job_async(self, payload: object) -> ServiceResponse:
        self.async_submitted_payloads.append(payload)
        return ServiceResponse(202, {"accepted": True, "submission_id": "sub-001"})

    def validate_job(self, payload: object) -> ServiceResponse:
        self.validated_payloads.append(payload)
        return ServiceResponse(200, {"valid": True})

    def get_job_status(self, submission_id: str) -> ServiceResponse:
        return ServiceResponse(
            200, {"submission_id": submission_id, "state": "completed"}
        )

    def list_modules_response(self) -> ServiceResponse:
        return ServiceResponse(200, {"modules": [{"name": "omega_block"}], "count": 1})

    def describe_module_response(self, module_name: str) -> ServiceResponse:
        return ServiceResponse(200, {"name": module_name, "entry_kind": "module"})

    def list_workflows_response(self) -> ServiceResponse:
        return ServiceResponse(
            200, {"workflows": [{"name": "retrieval_workflow"}], "count": 1}
        )

    def describe_workflow_response(self, workflow_name: str) -> ServiceResponse:
        return ServiceResponse(
            200, {"name": workflow_name, "workflow_id": workflow_name}
        )

    def get_workflow_panel_schema_response(self, workflow_name: str) -> ServiceResponse:
        return ServiceResponse(
            200, {"workflow_id": workflow_name, "datasource_fields": []}
        )

    def get_workflow_ui_schema_response(self, workflow_name: str) -> ServiceResponse:
        return ServiceResponse(200, {"workflow_id": workflow_name, "sections": []})


class HttpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job_service = _FakeJobService()
        self.server = create_server(
            host="127.0.0.1", port=0, job_service=self.job_service
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_endpoint_returns_json(self) -> None:
        status, body = self._request("GET", "/health")

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_submit_job_endpoint_forwards_raw_body_to_service(self) -> None:
        payload = json.dumps({"job_id": "job-http-1"})

        status, body = self._request("POST", "/jobs", payload)

        self.assertEqual(status, 200)
        self.assertTrue(body["accepted"])
        self.assertEqual(self.job_service.submitted_payloads, [payload])

    def test_validate_endpoint_forwards_raw_body_to_service(self) -> None:
        payload = json.dumps({"job_id": "job-http-2"})

        status, body = self._request("POST", "/jobs/validate", payload)

        self.assertEqual(status, 200)
        self.assertTrue(body["valid"])
        self.assertEqual(self.job_service.validated_payloads, [payload])

    def test_async_submit_and_status_endpoints_are_wired(self) -> None:
        payload = json.dumps({"job_id": "job-http-3"})

        submit_status, submit_body = self._request("POST", "/jobs/async", payload)
        query_status, query_body = self._request("GET", "/jobs/sub-001")

        self.assertEqual(submit_status, 202)
        self.assertTrue(submit_body["accepted"])
        self.assertEqual(self.job_service.async_submitted_payloads, [payload])
        self.assertEqual(query_status, 200)
        self.assertEqual(query_body["submission_id"], "sub-001")
        self.assertEqual(query_body["state"], "completed")

    def test_unknown_route_returns_404_payload(self) -> None:
        status, body = self._request("GET", "/unknown")

        self.assertEqual(status, 404)
        self.assertEqual(body["error_code"], "route_not_found")

    def test_catalog_endpoints_are_wired(self) -> None:
        modules_status, modules_body = self._request("GET", "/api/v1/modules")
        module_status, module_body = self._request("GET", "/api/v1/modules/omega_block")
        workflows_status, workflows_body = self._request("GET", "/api/v1/workflows")
        workflow_status, workflow_body = self._request(
            "GET", "/api/v1/workflows/retrieval_workflow"
        )
        panel_status, panel_body = self._request(
            "GET", "/api/v1/workflows/retrieval_workflow/panel-schema"
        )
        ui_status, ui_body = self._request(
            "GET", "/api/v1/workflows/retrieval_workflow/ui-schema"
        )

        self.assertEqual(modules_status, 200)
        self.assertEqual(modules_body["count"], 1)
        self.assertEqual(module_status, 200)
        self.assertEqual(module_body["name"], "omega_block")
        self.assertEqual(workflows_status, 200)
        self.assertEqual(workflows_body["count"], 1)
        self.assertEqual(workflow_status, 200)
        self.assertEqual(workflow_body["workflow_id"], "retrieval_workflow")
        self.assertEqual(panel_status, 200)
        self.assertEqual(panel_body["workflow_id"], "retrieval_workflow")
        self.assertEqual(ui_status, 200)
        self.assertEqual(ui_body["workflow_id"], "retrieval_workflow")

    def _request(
        self, method: str, path: str, body: str | None = None
    ) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection(
            self.server.server_address[0], self.server.server_address[1], timeout=5
        )
        try:
            headers = {}
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
