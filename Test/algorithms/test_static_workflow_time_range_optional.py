"""2026-08-23 修复回归：静态数据集工作流（aridity-cn 等）time_range 可选。

背景：``contracts/serialization.py`` 曾对 job_request.time_range 硬必填
（``_require_mapping``），而静态数据集（dataset_config ``time_range=None``、
descriptor ``supports_time=false``）的工作流种子无 time_range 节点 → 前端
提交"干旱指数 AI"运行时必报
``Missing required field: job_request.time_range``。
修复 = time_range 可选化（decode None；类型链 JobRequest/DataRequest/
DataBundle 放宽）。
"""

from __future__ import annotations

import unittest

from contracts.job import JobRequest
from contracts.serialization import coerce_job_request


def _base_payload(**overrides) -> dict:
    payload = {
        "job_id": "job-static-aridity-001",
        "pipeline_name": "workflow",
        "task_type": "workflow",
        "region": {
            "kind": "bbox",
            "value": {"xmin": 73, "ymin": 15, "xmax": 137, "ymax": 59},
        },
        "datasource_selection": {"open_data_presets": ["aridity"]},
        "algorithm_params": {},
        "output_spec": {"include_manifest": False, "extra": {"publish": False}},
        "workflow_name": "retrieval_workflow",  # 算法包 presets 真实存在的 workflow
    }
    payload.update(overrides)
    return payload


class StaticWorkflowTimeRangeOptionalTests(unittest.TestCase):
    def test_missing_time_range_decodes_to_none(self) -> None:
        """核心回归：静态工作流不传 time_range 也能解码（此前必炸）。"""
        request = coerce_job_request(_base_payload())
        self.assertIsNone(request.time_range)

    def test_null_time_range_decodes_to_none(self) -> None:
        request = coerce_job_request(_base_payload(time_range=None))
        self.assertIsNone(request.time_range)

    def test_present_time_range_still_decodes(self) -> None:
        """带 time_range 的时序工作流行为不变（回归）。"""
        request = coerce_job_request(
            _base_payload(
                time_range={
                    "start": "2025-01-01T00:00:00Z",
                    "end": "2025-01-02T00:00:00Z",
                }
            )
        )
        assert request.time_range is not None
        self.assertEqual(request.time_range.start.isoformat(), "2025-01-01T00:00:00+00:00")
        self.assertEqual(request.time_range.end.isoformat(), "2025-01-02T00:00:00+00:00")

    def test_missing_time_range_workflow_still_validates(self) -> None:
        """time_range=None 的请求能通过 validate_job_request（workflow 模板校验）。"""
        from contracts.validation import validate_job_request

        request = coerce_job_request(_base_payload())
        validated = validate_job_request(request)
        self.assertIsNone(validated.time_range)

    def test_schema_marks_time_range_optional(self) -> None:
        """JSON schema：time_range 不在 required 且允许 null。"""
        from contracts.serialization import get_job_request_json_schema

        schema = get_job_request_json_schema()
        self.assertNotIn("time_range", schema["required"])
        tr_schema = schema["properties"]["time_range"]
        self.assertEqual(tr_schema["anyOf"][1], {"type": "null"})


if __name__ == "__main__":
    unittest.main()
