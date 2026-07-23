from webgis_gee.diagnostics.service import DiagnosticsService
from webgis_gee.accounts.pool import InMemoryAccountPool
from webgis_gee.application.services import WorkflowService
from webgis_gee.config.settings import Settings
from webgis_gee.domain.models import EdgeSpec, NodeSpec, WorkflowDefinition
from webgis_gee.runtime.observability import (
    InMemoryMetricsSink,
    InMemoryStructuredEventSink,
)


def test_diagnostics_reports_registry_storage_and_account_pool(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(
            storage_backend="local",
            local_storage_root=str(tmp_path),
            max_parallel_exports=3,
            max_local_write_bytes=2048,
        ),
        account_pool=InMemoryAccountPool(["acc-1", "acc-2"]),
    )

    report = service.diagnose()

    assert report.status == "ok"
    assert report.checks["storage"]["status"] == "ok"
    assert "literal" in report.checks["node_registry"]["supported_node_types"]
    assert report.checks["account_pool"]["total_accounts"] == 2
    assert report.checks["resource_control"]["max_parallel_exports"] == 3
    assert report.checks["resource_control"]["max_parallel_uploads"] == 4
    assert report.checks["resource_control"]["max_parallel_downloads"] == 4
    assert report.checks["resource_control"]["gee_runtime_mode"] == "serialized"
    assert report.checks["resource_control"]["max_local_write_bytes"] == 2048
    assert report.checks["resource_control"]["active_temp_dirs"] == 0
    assert (
        report.checks["resource_control"]["quota_coordinator"]["type"]
        == "NoopResourceQuotaCoordinator"
    )


def test_diagnostics_warns_when_gee_dependency_is_available(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        DiagnosticsService,
        "_check_gee_dependency",
        staticmethod(lambda: {"status": "ok"}),
    )
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )

    report = service.diagnose()

    assert any("runtime authentication" in warning for warning in report.warnings)


def test_diagnostics_exposes_external_observability_sinks(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
        event_sink=InMemoryStructuredEventSink(),
        metrics_sink=InMemoryMetricsSink(),
    )

    report = service.diagnose()

    assert report.checks["observability"]["status"] == "ok"
    assert (
        report.checks["observability"]["structured_event_sink"]["type"]
        == "InMemoryStructuredEventSink"
    )
    assert (
        report.checks["observability"]["metrics_sink"]["type"] == "InMemoryMetricsSink"
    )


def test_diagnostics_exposes_metrics_snapshot(tmp_path) -> None:
    service = WorkflowService(
        settings=Settings(storage_backend="local", local_storage_root=str(tmp_path)),
    )
    workflow = WorkflowDefinition(
        workflow_id="metrics-demo",
        nodes=[
            NodeSpec(node_id="n1", node_type="literal", params={"value": "gee"}),
            NodeSpec(node_id="n2", node_type="identity"),
        ],
        edges=[
            EdgeSpec(
                source_node_id="n1",
                source_port="value",
                target_node_id="n2",
                target_port="value",
            )
        ],
    )

    service.execute_workflow(workflow)
    report = service.diagnose()

    assert report.checks["metrics"]["counters"]["workflow.execute.started"] == 1
    assert report.checks["metrics"]["counters"]["workflow.execute.completed"] == 1
    assert report.checks["metrics"]["counters"]["node.execute.started"] == 2
    assert (
        report.checks["metrics"]["timers"]["workflow.execute.duration_ms"]["count"] == 1
    )
