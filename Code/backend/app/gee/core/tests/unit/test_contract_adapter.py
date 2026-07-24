import json

from webgis_gee.api.contracts import (
    SavebackTerminalPlanPayload,
    WorkflowContractAdapter,
    WorkflowExecutionResponse,
)
from webgis_gee.api.facade import (
    WorkflowApiFacade,
    create_default_api_facade,
    create_default_contract_adapter,
)
from webgis_gee.application.services import WorkflowService
from webgis_gee.config.settings import Settings
from webgis_gee.domain.enums import RunStatus
from webgis_gee.domain.models import RunResult, WorkflowDefinition


def test_submit_workflow_accepts_serialized_payload(tmp_path) -> None:
    adapter = WorkflowContractAdapter(
        WorkflowService(
            settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
        )
    )

    result = adapter.submit_workflow(
        workflow={
            "workflow_id": "submit-demo",
            "nodes": [
                {"node_id": "n1", "node_type": "literal", "params": {"value": "gee"}},
                {"node_id": "n2", "node_type": "identity"},
            ],
            "edges": [
                {
                    "source_node_id": "n1",
                    "source_port": "value",
                    "target_node_id": "n2",
                    "target_port": "value",
                }
            ],
        },
        context={
            "workflow_id": "submit-demo",
            "metadata": {"request_id": "req-1"},
        },
    )

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n2.value"] == "gee"


def test_run_workflow_job_accepts_celery_style_payload(tmp_path) -> None:
    adapter = WorkflowContractAdapter(
        WorkflowService(
            settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
        )
    )

    result = adapter.run_workflow_job(
        {
            "workflow": {
                "workflow_id": "worker-demo",
                "nodes": [
                    {"node_id": "n1", "node_type": "literal", "params": {"value": 42}},
                ],
            },
            "context": {
                "workflow_id": "worker-demo",
                "account_id": "acc-1",
            },
        }
    )

    assert result.status == RunStatus.COMPLETED
    assert result.outputs["n1.value"] == 42


def test_get_export_task_status_uses_existing_polling_contract(tmp_path) -> None:
    adapter = WorkflowContractAdapter(
        WorkflowService(
            settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
        )
    )
    manifest_path = tmp_path / "exports" / "adapter.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "workflow_id": "adapter-demo",
                "task_ref": {
                    "started": False,
                    "status": "manifest_created",
                },
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    result = adapter.get_export_task_status(
        manifest_uri=f"file://{manifest_path}",
        update_manifest=True,
    )

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "manifest_created"
    assert saved_manifest["task_status"]["state"] == "LOCAL_ONLY"


def test_create_default_contract_adapter_returns_runnable_adapter() -> None:
    adapter = create_default_contract_adapter()

    result = adapter.submit_workflow(
        workflow={
            "workflow_id": "factory-demo",
            "nodes": [
                {"node_id": "n1", "node_type": "literal", "params": {"value": "ok"}},
            ],
        }
    )

    assert result.status == RunStatus.COMPLETED


def test_workflow_execution_response_extracts_saveback_terminal_plans_from_workflow_metadata() -> (
    None
):
    workflow = WorkflowDefinition.model_validate(
        {
            "workflow_id": "saveback-response-demo",
            "nodes": [
                {
                    "node_id": "export",
                    "node_type": "gee_export_image",
                    "params": {"task_name": "legacy-export"},
                }
            ],
            "metadata": {
                "saveback_terminal_plan": {
                    "node_terminals": [
                        {
                            "node_id": "export",
                            "action": "writeback_required",
                            "reasons": [
                                "requires_review_receipt",
                                "terminal_writeback_pending",
                            ],
                            "summary": {
                                "receipt_summary": "review_receipt_recorded",
                                "writeback_summary": "terminal_writeback_required",
                                "terminal_state": "closed_reviewed",
                            },
                        }
                    ]
                }
            },
        }
    )
    result = RunResult(
        run_id="run-1",
        workflow_id="saveback-response-demo",
        status=RunStatus.COMPLETED,
    )

    response = WorkflowExecutionResponse.from_run_result(result, workflow=workflow)

    assert response.saveback_terminal_plan == SavebackTerminalPlanPayload(
        action="writeback_required",
        reasons=["requires_review_receipt", "terminal_writeback_pending"],
        summary={
            "receipt_summary": "review_receipt_recorded",
            "writeback_summary": "terminal_writeback_required",
            "terminal_state": "closed_reviewed",
        },
    )
    assert (
        response.saveback_terminal_plans["export"].summary.terminal_state
        == "closed_reviewed"
    )


def test_workflow_execution_response_prefers_writeback_required_terminal_plan_over_monitor_only() -> (
    None
):
    workflow = WorkflowDefinition.model_validate(
        {
            "workflow_id": "saveback-priority-demo",
            "nodes": [
                {
                    "node_id": "a_monitor",
                    "node_type": "literal",
                    "params": {"value": "ok"},
                },
                {
                    "node_id": "z_export",
                    "node_type": "gee_export_image",
                    "params": {"task_name": "export"},
                },
            ],
            "metadata": {
                "saveback_terminal_plan": {
                    "node_terminals": [
                        {
                            "node_id": "a_monitor",
                            "action": "monitor_only",
                            "reasons": ["writeback_can_be_deferred"],
                            "summary": {
                                "receipt_summary": "no_receipt_recorded",
                                "writeback_summary": "no_terminal_writeback_required",
                                "terminal_state": "no_terminal_update",
                            },
                        },
                        {
                            "node_id": "z_export",
                            "action": "writeback_required",
                            "reasons": [
                                "requires_review_receipt",
                                "terminal_writeback_pending",
                            ],
                            "summary": {
                                "receipt_summary": "review_receipt_recorded",
                                "writeback_summary": "terminal_writeback_required",
                                "terminal_state": "closed_reviewed",
                            },
                        },
                    ]
                }
            },
        }
    )
    result = RunResult(
        run_id="run-priority",
        workflow_id="saveback-priority-demo",
        status=RunStatus.COMPLETED,
    )

    response = WorkflowExecutionResponse.from_run_result(result, workflow=workflow)

    assert response.saveback_terminal_plan is not None
    assert response.saveback_terminal_plan.action == "writeback_required"
    assert response.saveback_terminal_plan.summary.terminal_state == "closed_reviewed"


def test_api_facade_submit_workflow_returns_route_friendly_response_model() -> None:
    facade = create_default_api_facade()

    response = facade.submit_workflow(
        workflow={
            "workflow_id": "api-facade-demo",
            "nodes": [
                {"node_id": "n1", "node_type": "literal", "params": {"value": "ok"}},
            ],
        }
    )

    assert response.status == "completed"
    assert response.outputs["n1.value"] == "ok"
    assert response.saveback_terminal_plan is not None
    assert response.saveback_terminal_plan.action == "monitor_only"
    assert (
        response.saveback_terminal_plans["n1"].summary.terminal_state
        == "no_terminal_update"
    )


def test_api_facade_get_export_task_status_returns_route_friendly_response_model(
    tmp_path,
) -> None:
    facade = WorkflowApiFacade(
        WorkflowContractAdapter(
            WorkflowService(
                settings=Settings(
                    storage_backend="local", local_storage_root=str(tmp_path)
                )
            )
        )
    )
    manifest_path = tmp_path / "exports" / "api-facade.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "workflow_id": "api-facade-export-demo",
                "task_ref": {
                    "started": False,
                    "status": "manifest_created",
                },
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )

    response = facade.get_export_task_status(manifest_uri=f"file://{manifest_path}")

    assert response.status == "manifest_created"
    assert response.state == "LOCAL_ONLY"
    assert response.started is False


def test_get_export_task_status_is_read_only_by_default(tmp_path) -> None:
    adapter = WorkflowContractAdapter(
        WorkflowService(
            settings=Settings(storage_backend="local", local_storage_root=str(tmp_path))
        )
    )
    manifest_path = tmp_path / "exports" / "adapter-read-only.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    original_payload = {
        "workflow_id": "adapter-read-only-demo",
        "task_ref": {
            "started": False,
            "status": "manifest_created",
        },
    }
    manifest_path.write_text(
        json.dumps(original_payload, ensure_ascii=True),
        encoding="utf-8",
    )

    result = adapter.get_export_task_status(manifest_uri=f"file://{manifest_path}")

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["status"] == "manifest_created"
    assert saved_manifest == original_payload
