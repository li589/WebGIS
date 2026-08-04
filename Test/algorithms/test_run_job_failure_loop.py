"""Dispatch-02: run_job() failure闭环 - exceptions propagate and notify scheduler."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, TimeRange
from runner.dispatch import run_job


class RunJobFailure闭环Tests(unittest.TestCase):
    """Dispatch-02: pipeline failures are caught and reported to scheduler."""

    def test_pipeline_failure_returns_failed_result(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        workspace = tmp_dir / "workspace"
        workspace.mkdir()

        scheduler = MagicMock()
        datasource = MagicMock()
        logger = MagicMock()

        with (
            patch("runner.dispatch.get_pipeline") as mock_get,
            patch("contracts.validation.validate_job_request"),
        ):
            from pipelines.base import BasePipeline, PipelinePlan

            class FailingPipeline(BasePipeline):
                name = "failing_pipeline"

                def plan(self, request, ctx):
                    return PipelinePlan(
                        required_datasets=[],
                        required_variables=[],
                        estimated_outputs=[],
                        parallelizable=False,
                        chunk_strategy="none",
                        cache_requirement="none",
                    )

                def execute(self, request, ctx):
                    raise RuntimeError("Intentional test failure")

            mock_get.return_value = FailingPipeline

            request = JobRequest(
                job_id="failure-test",
                pipeline_name="failing_pipeline",
                task_type="extract",
                time_range=TimeRange(
                    start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)
                ),
                region=RegionSpec(kind="global", value={}),
                datasource_selection={},
                algorithm_params={},
                output_spec=OutputSpec(extra={}),
            )

            result = run_job(
                request, scheduler, datasource, logger, workspace=workspace
            )

        self.assertEqual(result.status, "failed")
        self.assertIn("Intentional test failure", result.error_summary)
        scheduler.complete.assert_called_once()
        call_args = scheduler.complete.call_args[0][0]
        self.assertEqual(call_args.status, "failed")

    def test_workflow_validation_failure_returns_failed_result(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp())
        workspace = tmp_dir / "workspace"
        workspace.mkdir()

        scheduler = MagicMock()
        datasource = MagicMock()
        logger = MagicMock()

        request = JobRequest(
            job_id="wf-validation-fail",
            pipeline_name="workflow",
            workflow_definition={
                "workflow_id": "bad_wf",
                "nodes": [],
                "edges": [],
                "outputs": [],
            },
            task_type="extract",
            time_range=TimeRange(start=datetime(2020, 1, 1), end=datetime(2020, 1, 2)),
            region=RegionSpec(kind="global", value={}),
            datasource_selection={},
            algorithm_params={},
            output_spec=OutputSpec(extra={}),
        )

        result = run_job(request, scheduler, datasource, logger, workspace=workspace)

        self.assertEqual(result.status, "failed")
        self.assertIn("at least one enabled node", result.error_summary)
        scheduler.complete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
