from __future__ import annotations

import unittest
from datetime import datetime

from contracts.api_errors import build_api_error_response
from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, TimeRange
from contracts.serialization import JobRequestDecodeError
from contracts.validation import JobRequestValidationError, validate_job_request


class ApiErrorResponseTests(unittest.TestCase):
    def _build_request(self) -> JobRequest:
        return JobRequest(
            job_id="job-api-error",
            pipeline_name="workflow",
            task_type="workflow",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={},
            algorithm_params={},
            output_spec=OutputSpec(),
        )

    def test_build_api_error_response_maps_decode_error_to_400(self) -> None:
        error = JobRequestDecodeError("Field must be an ISO datetime string: job_request.time_range.start")

        response = build_api_error_response(error)

        self.assertEqual(response.http_status, 400)
        self.assertEqual(response.error_code, "job_request_decode_failed")
        self.assertFalse(response.retryable)
        self.assertEqual(response.issues[0].code, "invalid_iso_datetime")
        self.assertEqual(response.suggested_fixes[0].code, "use_iso_datetime")

    def test_build_api_error_response_maps_unknown_field_decode_error(self) -> None:
        error = JobRequestDecodeError("Unknown field(s) not allowed: job_request -> unexpected")

        response = build_api_error_response(error)

        self.assertEqual(response.http_status, 400)
        self.assertEqual(response.issues[0].code, "unknown_field")
        self.assertEqual(response.issues[0].field_path, "job_request.unexpected")
        self.assertEqual(response.suggested_fixes[0].code, "remove_unknown_field")

    def test_build_api_error_response_maps_inconsistent_timezone_decode_error(self) -> None:
        error = JobRequestDecodeError(
            "Fields must both include timezone info or both omit it: "
            "job_request.time_range.start, job_request.time_range.end"
        )

        response = build_api_error_response(error)

        self.assertEqual(response.http_status, 400)
        self.assertEqual(len(response.issues), 2)
        self.assertEqual(response.issues[0].code, "inconsistent_timezone")
        self.assertEqual(response.suggested_fixes[0].code, "use_consistent_timezone")

    def test_build_api_error_response_maps_validation_error_to_422(self) -> None:
        request = self._build_request()
        request.workflow_definition = {
            "workflow_id": "wf-api-error",
            "inputs": {
                "source_value": {
                    "source_type": "file",
                    "format": "mat",
                }
            },
            "nodes": [
                {
                    "node_id": "bundle_node",
                    "node_type": "module",
                    "input_bindings": {"datasource_selection": "input:source_value"},
                    "params": {"module_name": "daily_bundle"},
                }
            ],
            "outputs": [{"name": "final_manifest", "source": "node:bundle_node.manifest"}],
        }

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        response = build_api_error_response(ctx.exception, request=request)

        self.assertEqual(response.http_status, 422)
        self.assertEqual(response.error_code, "job_request_validation_failed")
        self.assertFalse(response.retryable)
        self.assertEqual(response.issues[0].code, "missing_datasource_key")
        self.assertEqual(response.issues[0].label, "Source Value")
        self.assertEqual(response.suggested_fixes[0].code, "provide_datasource_key")
        self.assertIn("source_value", response.suggested_fixes[0].message)

    def test_build_api_error_response_maps_unknown_exception_to_500(self) -> None:
        response = build_api_error_response(RuntimeError("unexpected"))

        self.assertEqual(response.http_status, 500)
        self.assertEqual(response.error_code, "internal_server_error")
        self.assertTrue(response.retryable)
        self.assertEqual(response.user_message, "服务器处理请求时发生未预期错误。")
        self.assertEqual(response.developer_message, "unexpected")
        self.assertFalse(response.issues)


if __name__ == "__main__":
    unittest.main()
