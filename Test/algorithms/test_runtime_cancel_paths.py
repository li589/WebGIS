"""Tests for workflow-aligned runtime tmp_dir and cancel flag paths."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, TimeRange
from runner.runtime import build_runtime_context


def _build_request(*, job_id: str, module_name: str = "omega_sf_fenkuai") -> JobRequest:
    return JobRequest(
        job_id=job_id,
        pipeline_name="workflow",
        task_type="analysis",
        time_range=TimeRange(start=datetime(2025, 1, 1, tzinfo=UTC), end=datetime(2025, 1, 2, tzinfo=UTC)),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
        module_name=module_name,
    )


def test_build_runtime_context_uses_stable_tmp_for_workflow_runs(tmp_path: Path) -> None:
    run_id = "run-abc123def456"
    request = _build_request(job_id=run_id)
    ctx = build_runtime_context(request, tmp_path)
    assert ctx.run_id == run_id
    assert ctx.tmp_dir == tmp_path / "tmp" / run_id
    assert ctx.env["cancel_flag_path"] == str(tmp_path / "tmp" / run_id / "cancel.requested")


def test_build_runtime_context_non_workflow_job_gets_unique_run_id(tmp_path: Path) -> None:
    request = _build_request(job_id="job-local-1", module_name="demo")
    ctx = build_runtime_context(request, tmp_path)
    assert ctx.run_id.startswith("job-local-1-")
    assert ctx.tmp_dir == tmp_path / "tmp" / ctx.run_id
