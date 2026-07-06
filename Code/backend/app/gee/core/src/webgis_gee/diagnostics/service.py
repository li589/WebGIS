from __future__ import annotations

from typing import Any

from webgis_gee.accounts.pool import InMemoryAccountPool
from webgis_gee.config.settings import Settings
from webgis_gee.domain.models import DiagnosticsReport
from webgis_gee.nodes.registry import NodeRegistry
from webgis_gee.runtime.observability import InMemoryMetricsCollector, StructuredEventSink
from webgis_gee.runtime.resources import RuntimeResourceController
from webgis_gee.storage.factory import create_storage_backend
from webgis_gee.workflow.versioning import WorkflowDefinitionMigrator


class DiagnosticsService:
    """Health checks for registry, storage and account pool."""

    def __init__(
        self,
        registry: NodeRegistry,
        settings: Settings | None = None,
        account_pool: InMemoryAccountPool | None = None,
        resource_controller: RuntimeResourceController | None = None,
        metrics_collector: InMemoryMetricsCollector | None = None,
        event_sink: StructuredEventSink | None = None,
        workflow_migrator: WorkflowDefinitionMigrator | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings or Settings()
        self._account_pool = account_pool
        self._resource_controller = resource_controller
        self._metrics_collector = metrics_collector
        self._event_sink = event_sink
        self._workflow_migrator = workflow_migrator

    def run(self) -> DiagnosticsReport:
        checks: dict[str, Any] = {
            "node_registry": {
                "status": "ok",
                "supported_node_types": self._registry.supported_node_types(),
            },
            "storage": self._check_storage(),
            "gee_dependency": self._check_gee_dependency(),
        }
        if self._account_pool is not None:
            checks["account_pool"] = self._account_pool.health_report()
        else:
            checks["account_pool"] = {
                "status": "error",
                "error": "no account pool configured — GEE credentials not loaded",
            }
        if self._resource_controller is not None:
            checks["resource_control"] = self._resource_controller.snapshot()
        if self._metrics_collector is not None:
            checks["metrics"] = self._metrics_collector.snapshot()
        checks["observability"] = self._check_observability()
        if self._workflow_migrator is not None:
            checks["workflow_schema"] = self._workflow_migrator.describe_support()

        warnings: list[str] = []
        if checks["gee_dependency"]["status"] == "ok":
            warnings.append("earthengine-api is available but runtime authentication may still be required")
        if checks["storage"]["status"] != "ok":
            warnings.append("storage backend is not ready")

        overall_status = "ok" if all(self._status_ok(value) for value in checks.values()) else "degraded"
        return DiagnosticsReport(status=overall_status, checks=checks, warnings=warnings)

    def _check_storage(self) -> dict[str, Any]:
        try:
            backend = create_storage_backend(self._settings)
            return {
                "status": "ok",
                "backend": self._settings.storage_backend,
                "uri_example": backend.build_uri("diagnostics/healthcheck.txt"),
            }
        except Exception as exc:
            return {
                "status": "error",
                "backend": self._settings.storage_backend,
                "error": str(exc),
            }

    @staticmethod
    def _check_gee_dependency() -> dict[str, Any]:
        try:
            import ee  # noqa: F401

            return {"status": "ok"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    @staticmethod
    def _status_ok(value: Any) -> bool:
        if isinstance(value, dict):
            status = value.get("status")
            return status in (None, "ok")
        return True

    def _check_observability(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "structured_event_sink": self._event_sink.describe() if self._event_sink is not None else None,
            "metrics_sink": (
                self._metrics_collector.snapshot().get("external_metrics_sink")
                if self._metrics_collector is not None
                else None
            ),
        }
