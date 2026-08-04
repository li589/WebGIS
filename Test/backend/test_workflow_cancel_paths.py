"""Tests for workflow cancel flag path helpers."""

from __future__ import annotations

from app.services.python_provider_request_builder import PythonProviderRequestBuilder
from app.services.workflow.cancel_paths import workflow_cancel_flag_path, workflow_cancel_tmp_dir
from shared.contracts.api_contracts import (
    AlgorithmWorkflowRequest,
    WorkflowCommandType,
    WorkflowSubmitRequest,
)


def test_workflow_cancel_paths() -> None:
    run_id = "run-abc123def456"
    flag = workflow_cancel_flag_path(run_id)
    assert flag.name == "cancel.requested"
    assert flag.parent == workflow_cancel_tmp_dir(run_id)


def test_build_job_request_injects_cancel_flag_path() -> None:
    builder = PythonProviderRequestBuilder()
    run_id = "run-test001"
    payload = WorkflowSubmitRequest(
        command_type=WorkflowCommandType.analysis,
        algorithm_request=AlgorithmWorkflowRequest(module_name="omega_sf_fenkuai"),
    )
    job = builder.build_job_request_payload(run_id=run_id, payload=payload)
    cancel = job["algorithm_params"]["cancel_flag_path"]
    assert cancel.endswith("cancel.requested")
    assert run_id in cancel
