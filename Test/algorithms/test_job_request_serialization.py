from __future__ import annotations

import json
import unittest
from datetime import timedelta

from contracts.job import JobRequest
from contracts.serialization import (
    JobRequestDecodeError,
    coerce_job_request,
    get_job_request_json_schema,
)
from contracts.runtime import CachePolicy, ResourceHint
from workflow.graph import WorkflowDefinition


class JobRequestSerializationTests(unittest.TestCase):
    def test_coerce_job_request_accepts_mapping_and_applies_defaults(self) -> None:
        payload = {
            "job_id": "job-http-001",
            "pipeline_name": "workflow",
            "task_type": "workflow",
            "time_range": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-02T00:00:00Z",
            },
            "region": {
                "kind": "bbox",
                "value": {"xmin": 73, "ymin": 18, "xmax": 135, "ymax": 54},
            },
            "datasource_selection": {
                "source_value": "demo-http",
            },
            "algorithm_params": {
                "mode": "omega",
            },
            "workflow_definition": {
                "workflow_id": "wf-http-demo",
                "nodes": [
                    {
                        "node_id": "module_node",
                        "node_type": "module",
                        "input_bindings": {
                            "input_value": "input:source_value",
                        },
                        "params": {
                            "module_name": "acceptance_module",
                        },
                    }
                ],
                "outputs": [
                    {"name": "final_manifest", "source": "node:module_node.manifest"},
                ],
            },
        }

        request = coerce_job_request(payload)

        self.assertIsInstance(request, JobRequest)
        self.assertEqual(request.job_id, "job-http-001")
        self.assertEqual(request.time_range.start.utcoffset(), timedelta(0))
        self.assertEqual(request.output_spec.raster_format, "COG")
        self.assertEqual(request.output_spec.table_format, "parquet")
        self.assertTrue(request.output_spec.include_qc)
        self.assertTrue(request.output_spec.include_manifest)
        self.assertEqual(request.output_spec.extra, {})
        self.assertIsNone(request.resource_hint)
        self.assertIsNone(request.cache_policy)
        self.assertIsInstance(request.workflow_definition, WorkflowDefinition)
        self.assertEqual(request.workflow_definition.workflow_id, "wf-http-demo")

    def test_coerce_job_request_accepts_json_string_and_parses_runtime_options(
        self,
    ) -> None:
        payload = json.dumps(
            {
                "job_id": "job-http-002",
                "pipeline_name": "workflow",
                "task_type": "ndvi_daily",
                "time_range": {
                    "start": "2025-01-01T00:00:00",
                    "end": "2025-01-16T00:00:00",
                    "step": "P1D",
                },
                "region": {
                    "kind": "global",
                    "value": {},
                },
                "datasource_selection": {},
                "algorithm_params": {},
                "output_spec": {
                    "include_manifest": False,
                    "extra": {"publish": False},
                },
                "resource_hint": {
                    "cpu_cores": 8,
                    "memory_gb": 32,
                },
                "cache_policy": {
                    "mode": "full",
                    "enabled": False,
                },
                "tags": {
                    "scene": "acceptance",
                },
                "module_name": "ndvi_daily",
            }
        )

        request = coerce_job_request(payload)

        self.assertEqual(request.time_range.step, "P1D")
        self.assertFalse(request.output_spec.include_manifest)
        self.assertEqual(request.output_spec.extra["publish"], False)
        self.assertIsInstance(request.resource_hint, ResourceHint)
        self.assertEqual(request.resource_hint.cpu_cores, 8)
        self.assertEqual(request.resource_hint.memory_gb, 32.0)
        self.assertIsInstance(request.cache_policy, CachePolicy)
        self.assertEqual(request.cache_policy.mode, "full")
        self.assertFalse(request.cache_policy.enabled)
        self.assertEqual(request.tags["scene"], "acceptance")
        self.assertEqual(request.module_name, "ndvi_daily")

    def test_coerce_job_request_rejects_invalid_iso_datetime(self) -> None:
        payload = {
            "job_id": "job-invalid-time",
            "pipeline_name": "workflow",
            "task_type": "workflow",
            "time_range": {
                "start": "not-a-datetime",
                "end": "2025-01-02T00:00:00",
            },
            "region": {
                "kind": "global",
                "value": {},
            },
            "datasource_selection": {},
            "algorithm_params": {},
        }

        with self.assertRaises(JobRequestDecodeError) as ctx:
            coerce_job_request(payload)

        self.assertIn("job_request.time_range.start", str(ctx.exception))

    def test_coerce_job_request_rejects_region_value_that_is_not_object(self) -> None:
        payload = {
            "job_id": "job-invalid-region",
            "pipeline_name": "workflow",
            "task_type": "workflow",
            "time_range": {
                "start": "2025-01-01T00:00:00",
                "end": "2025-01-02T00:00:00",
            },
            "region": {
                "kind": "global",
                "value": "not-an-object",
            },
            "datasource_selection": {},
            "algorithm_params": {},
        }

        with self.assertRaises(JobRequestDecodeError) as ctx:
            coerce_job_request(payload)

        self.assertIn("job_request.region.value", str(ctx.exception))

    def test_coerce_job_request_rejects_unknown_top_level_field(self) -> None:
        payload = {
            "job_id": "job-unknown-field",
            "pipeline_name": "workflow",
            "task_type": "workflow",
            "time_range": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-02T00:00:00Z",
            },
            "region": {
                "kind": "global",
                "value": {},
            },
            "datasource_selection": {},
            "algorithm_params": {},
            "unexpected": "ignored-before",
        }

        with self.assertRaises(JobRequestDecodeError) as ctx:
            coerce_job_request(payload)

        self.assertIn("job_request", str(ctx.exception))
        self.assertIn("unexpected", str(ctx.exception))

    def test_coerce_job_request_rejects_mixed_timezone_awareness(self) -> None:
        payload = {
            "job_id": "job-mixed-timezone",
            "pipeline_name": "workflow",
            "task_type": "workflow",
            "time_range": {
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-01-02T00:00:00",
            },
            "region": {
                "kind": "global",
                "value": {},
            },
            "datasource_selection": {},
            "algorithm_params": {},
        }

        with self.assertRaises(JobRequestDecodeError) as ctx:
            coerce_job_request(payload)

        self.assertIn("timezone", str(ctx.exception))

    def test_job_request_json_schema_exposes_http_fields(self) -> None:
        schema = get_job_request_json_schema()

        self.assertEqual(schema["title"], "JobRequest")
        self.assertIn("time_range", schema["properties"])
        self.assertIn("output_spec", schema["properties"])
        self.assertIn("resource_hint", schema["properties"])


if __name__ == "__main__":
    unittest.main()
