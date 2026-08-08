from __future__ import annotations

import unittest
from datetime import datetime

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, TimeRange
from contracts.serialization import JobRequestDecodeError
from contracts.validation import JobRequestValidationError, validate_job_request
from contracts.validation_feedback import build_validation_feedback
from workflow.serialization import coerce_workflow_definition
from workflow.validation import (
    WorkflowDefinitionValidationError,
    validate_workflow_definition,
)


class ValidationFeedbackTests(unittest.TestCase):
    def _build_request(self) -> JobRequest:
        return JobRequest(
            job_id="job-feedback",
            pipeline_name="workflow",
            task_type="workflow",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={},
            algorithm_params={},
            output_spec=OutputSpec(),
        )

    def test_build_validation_feedback_maps_job_request_decode_error(self) -> None:
        error = JobRequestDecodeError(
            "Field must be an ISO datetime string: job_request.time_range.start"
        )

        feedback = build_validation_feedback(error)

        self.assertEqual(feedback.error_type, "job_request_decode")
        self.assertEqual(len(feedback.issues), 1)
        issue = feedback.issues[0]
        self.assertEqual(issue.code, "invalid_iso_datetime")
        self.assertEqual(issue.field_path, "job_request.time_range.start")
        self.assertEqual(issue.field_key, "start")
        self.assertEqual(issue.section, "request")

    def test_build_validation_feedback_maps_unknown_field_decode_error(self) -> None:
        error = JobRequestDecodeError(
            "Unknown field(s) not allowed: job_request -> unexpected"
        )

        feedback = build_validation_feedback(error)

        self.assertEqual(feedback.error_type, "job_request_decode")
        self.assertEqual(len(feedback.issues), 1)
        issue = feedback.issues[0]
        self.assertEqual(issue.code, "unknown_field")
        self.assertEqual(issue.field_path, "job_request.unexpected")
        self.assertEqual(issue.field_key, "unexpected")
        self.assertEqual(issue.section, "request")

    def test_build_validation_feedback_maps_inconsistent_timezone_decode_error(
        self,
    ) -> None:
        error = JobRequestDecodeError(
            "Fields must both include timezone info or both omit it: "
            "job_request.time_range.start, job_request.time_range.end"
        )

        feedback = build_validation_feedback(error)

        self.assertEqual(feedback.error_type, "job_request_decode")
        self.assertEqual(len(feedback.issues), 2)
        self.assertEqual(feedback.issues[0].code, "inconsistent_timezone")
        self.assertEqual(feedback.issues[0].field_path, "job_request.time_range.start")
        self.assertEqual(feedback.issues[1].field_path, "job_request.time_range.end")

    def test_build_validation_feedback_maps_job_request_validation_error_to_datasource_field(
        self,
    ) -> None:
        request = self._build_request()
        request.workflow_definition = {
            "workflow_id": "wf-feedback",
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
            "outputs": [
                {"name": "final_manifest", "source": "node:bundle_node.manifest"}
            ],
        }

        with self.assertRaises(JobRequestValidationError) as ctx:
            validate_job_request(request)

        feedback = build_validation_feedback(ctx.exception, request=request)

        self.assertEqual(feedback.error_type, "job_request_validation")
        self.assertEqual(len(feedback.issues), 1)
        issue = feedback.issues[0]
        self.assertEqual(issue.code, "missing_datasource_key")
        self.assertEqual(
            issue.field_path, "job_request.datasource_selection.source_value"
        )
        self.assertEqual(issue.field_key, "source_value")
        self.assertEqual(issue.section, "datasource_selection")
        self.assertEqual(issue.label, "Source Value")
        self.assertEqual(issue.control_type, "file_picker")

    def test_build_validation_feedback_maps_workflow_validation_error_to_binding_path(
        self,
    ) -> None:
        workflow_definition = {
            "workflow_id": "wf-invalid-binding",
            "nodes": [
                {
                    "node_id": "module_node",
                    "node_type": "module",
                    "input_bindings": {"datasource_selection": "request:not_supported"},
                    "params": {"module_name": "daily_bundle"},
                }
            ],
            "outputs": [
                {"name": "final_manifest", "source": "node:module_node.manifest"}
            ],
        }

        with self.assertRaises(WorkflowDefinitionValidationError) as ctx:
            validate_workflow_definition(
                coerce_workflow_definition(workflow_definition)
            )

        feedback = build_validation_feedback(
            ctx.exception, workflow_definition=workflow_definition
        )

        self.assertEqual(feedback.error_type, "workflow_definition_validation")
        self.assertEqual(len(feedback.issues), 1)
        issue = feedback.issues[0]
        self.assertEqual(issue.code, "unsupported_request_binding")
        self.assertEqual(
            issue.field_path,
            "workflow_definition.nodes[module_node].input_bindings.datasource_selection",
        )
        self.assertEqual(issue.field_key, "datasource_selection")
        self.assertEqual(issue.section, "workflow_definition")
        self.assertEqual(issue.details["request_binding"], "not_supported")


if __name__ == "__main__":
    unittest.main()
