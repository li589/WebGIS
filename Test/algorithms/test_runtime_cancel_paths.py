"""Tests for workflow-aligned runtime tmp_dir and cancel flag paths."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from contracts.job import JobRequest
from contracts.product import OutputSpec
from contracts.runtime import RegionSpec, TimeRange
from runner.runtime import build_runtime_context


def _build_request(*, job_id: str, module_name: str = "omega_sf_fenkuai") -> JobRequest:
    return JobRequest(
        job_id=job_id,
        pipeline_name="workflow",
        task_type="analysis",
        time_range=TimeRange(
            start=datetime(2025, 1, 1, tzinfo=UTC), end=datetime(2025, 1, 2, tzinfo=UTC)
        ),
        region=RegionSpec(kind="global", value={}),
        datasource_selection={},
        algorithm_params={},
        output_spec=OutputSpec(),
        module_name=module_name,
    )


def test_build_runtime_context_uses_stable_tmp_for_workflow_runs(
    tmp_path: Path,
) -> None:
    run_id = "run-abc123def456"
    request = _build_request(job_id=run_id)
    ctx = build_runtime_context(request, tmp_path)
    assert ctx.run_id == run_id
    assert ctx.tmp_dir == tmp_path / "tmp" / run_id
    assert ctx.env["cancel_flag_path"] == str(
        tmp_path / "tmp" / run_id / "cancel.requested"
    )


def test_build_runtime_context_non_workflow_job_gets_unique_run_id(
    tmp_path: Path,
) -> None:
    request = _build_request(job_id="job-local-1", module_name="demo")
    ctx = build_runtime_context(request, tmp_path)
    assert ctx.run_id.startswith("job-local-1-")
    assert ctx.tmp_dir == tmp_path / "tmp" / ctx.run_id


def test_omega_sf_fenkuai_uses_run_isolated_output_dir(tmp_path: Path) -> None:
    """Regression: a new FY/SMAP run must not overwrite another run's shared product dir."""
    import contracts.job  # noqa: F401
    from modules.omega_sf_fenkuai import OmegaSfFenkuaiModule
    from workflow.schemas import NodeExecutionContext

    workspace = tmp_path / "workspace"
    anc_root = tmp_path / "anc"
    anc_root.mkdir()

    class _FakeArtifactStore:
        def put(self, artifact, payload=None):
            self.artifact = artifact
            self.payload = payload
            return artifact

    class _FakeLogger:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def emit_stage_start(self, _stage: str, message: str) -> None:
            self.messages.append(message)

        def emit_progress(self, *_args, **_kwargs) -> None:
            return None

        def emit_artifact(self, *_args, **_kwargs) -> None:
            return None

        def emit_stage_end(self, *_args, **_kwargs) -> None:
            return None

    runtime = SimpleNamespace(
        run_id="run-isolated-001",
        workspace=str(workspace),
        tmp_dir=tmp_path / "tmp" / "run-isolated-001",
        env={},
    )
    request = SimpleNamespace(job_id="run-isolated-001")
    artifact_store = _FakeArtifactStore()
    logger = _FakeLogger()
    ctx = NodeExecutionContext(
        workflow_id="wf",
        node_id="module_node",
        request=request,  # type: ignore[arg-type]
        runtime_context=runtime,  # type: ignore[arg-type]
        workspace=workspace,
        artifact_store=artifact_store,  # type: ignore[arg-type]
        logger_adapter=logger,
    )

    captured: dict[str, str] = {}

    def _fake_retrieve(**kwargs):
        captured["output_dir"] = str(kwargs["output_dir"])
        return SimpleNamespace(
            output_paths={
                "block_dir": str(kwargs["output_dir"]),
                "omega_pixel": "",
                "omega_pft": "",
            },
            n_pixels_success=1,
            n_pixels_total=1,
            n_pixels_failed=0,
            sm_maps=[{}],
        )

    with (
        patch(
            "modules.omega_sf_fenkuai._resolve_omega_sf_datasource_selection",
            return_value={"smap_folder": "smap", "anc_root": str(anc_root)},
        ),
        patch(
            "modules.omega_sf_fenkuai._resolve_grid_shape",
            return_value=(2, 2),
        ),
        patch(
            "algorithms.omega_sf.retrieve_omega_sf_daily",
            side_effect=_fake_retrieve,
        ),
    ):
        OmegaSfFenkuaiModule().execute(
            {
                "datasource_selection": {},
                "algorithm_params": {},
                "output_spec_extra": {},
            },
            {},
            ctx,
        )

    expected = workspace / "products" / "omega_sf_fenkuai" / "run-isolated-001"
    assert captured["output_dir"] == str(expected)
    assert expected.is_dir()
    manifest = artifact_store.payload
    assert manifest.extra["output_dir"] == str(expected)
    assert any("Using isolated output directory" in m for m in logger.messages)
