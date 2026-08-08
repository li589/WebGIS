"""Tests for workflow retry block-cache reuse resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.workflow.reuse_cache import (
    inject_retry_reuse_params,
    resolve_reuse_output_dir,
)
from app.services.workflow_repository import SQLiteWorkflowRepository
from shared.contracts.api_contracts import (
    ExecutionStatus,
    WorkflowCommandType,
    WorkflowRunStatusResponse,
)


@pytest.fixture()
def repo(tmp_path: Path) -> SQLiteWorkflowRepository:
    return SQLiteWorkflowRepository(state_dir=tmp_path)


def _save_run(
    repo: SQLiteWorkflowRepository,
    *,
    run_id: str,
    request_json: str,
    result_dto: dict | None = None,
    executor_metadata: dict | None = None,
) -> None:
    now = "2026-08-04T00:00:00+00:00"
    from datetime import datetime, timezone

    ts = datetime.fromisoformat(now)
    status = WorkflowRunStatusResponse(
        run_id=run_id,
        command_type=WorkflowCommandType.analysis,
        status=ExecutionStatus.failed,
        progress=100,
        message="failed",
        created_at=ts,
        updated_at=ts,
        result_dto=result_dto,
        executor_metadata=executor_metadata or {},
    )
    repo.save_run(
        status,
        request_json=request_json,
        result_dto_override=result_dto,
    )


def test_resolve_reuse_from_executor_metadata(repo: SQLiteWorkflowRepository, tmp_path: Path) -> None:
    out_dir = tmp_path / "blocks"
    out_dir.mkdir()
    _save_run(
        repo,
        run_id="run-a",
        request_json="{}",
        executor_metadata={"reuse_output_dir": str(out_dir)},
    )
    resolved, _ = resolve_reuse_output_dir(repo, "run-a")
    assert resolved == str(out_dir)


def test_resolve_reuse_from_result_products(repo: SQLiteWorkflowRepository, tmp_path: Path) -> None:
    block_dir = tmp_path / "products" / "omega_sf_fenkuai" / "blocks"
    block_dir.mkdir(parents=True)
    mat = block_dir / "20251227_20251231.mat"
    mat.write_text("stub", encoding="utf-8")
    _save_run(
        repo,
        run_id="run-b",
        request_json="{}",
        result_dto={
            "products": [
                {
                    "uri": str(mat),
                    "type": "omega_sf_block",
                    "tags": {"layer": "BLOCK"},
                }
            ]
        },
    )
    resolved, _ = resolve_reuse_output_dir(repo, "run-b")
    assert resolved == str(block_dir)


def test_inject_retry_reuse_params_merges_algorithm_params() -> None:
    payload = {
        "algorithm_request": {
            "module_name": "omega_sf_fenkuai",
            "algorithm_params": {"start_date": "20251227"},
        }
    }
    merged = inject_retry_reuse_params(payload, reuse_output_dir="/data/out")
    params = merged["algorithm_request"]["algorithm_params"]
    assert params["reuse_block_cache"] is True
    assert params["reuse_output_dir"] == "/data/out"
    assert params["start_date"] == "20251227"


def test_resolve_reuse_from_request_output_dir(repo: SQLiteWorkflowRepository, tmp_path: Path) -> None:
    out_dir = tmp_path / "custom_out"
    out_dir.mkdir()
    request = {
        "command_type": "analysis",
        "algorithm_request": {
            "module_name": "omega_sf_fenkuai",
            "algorithm_params": {"output_dir": str(out_dir)},
        },
    }
    _save_run(repo, run_id="run-c", request_json=json.dumps(request))
    resolved, module = resolve_reuse_output_dir(repo, "run-c")
    assert resolved == str(out_dir)
    assert module == "omega_sf_fenkuai"
