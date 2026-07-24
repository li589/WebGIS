from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

from webgis_gee.accounts.pool import InMemoryAccountPool
from webgis_gee.config.settings import Settings
from webgis_gee.diagnostics.service import DiagnosticsService
from webgis_gee.domain.models import (
    DiagnosticsReport,
    ExecutionContext,
    RunResult,
    RunStatus,
    WorkflowDefinition,
)
from webgis_gee.gee.context import GeeContext
from webgis_gee.gee.errors import classify_gee_error
from webgis_gee.gee.nodes import (
    GeeClipNode,
    GeeCloudMaskNode,
    GeeExportImageNode,
    GeeExportTableNode,
    GeeImageNode,
    GeeImageCollectionCompositeNode,
    GeeRasterAlgebraNode,
    GeeReclassifyNode,
    GeeRegionStatsNode,
    GeeSelectBandsNode,
    GeeSpectralIndexNode,
    GeeThresholdClassifyNode,
    GeeTimeSeriesStatsNode,
)
from webgis_gee.gee.tasks import GeeExportTaskService
from webgis_gee.nodes.registry import NodeRegistry
from webgis_gee.nodes.sample_nodes import (
    BatchCollectNode,
    BatchFilterNode,
    BatchFlattenNode,
    BatchMapNode,
    BatchSplitByRegionsNode,
    BatchSplitByTimeNode,
    IdentityNode,
    LiteralNode,
    SampleComputeNode,
    SampleInputNode,
    SampleOutputNode,
)
from webgis_gee.runtime.observability import (
    InMemoryMetricsCollector,
    MetricsSink,
    StructuredEventSink,
    log_structured_event,
)
from webgis_gee.storage.base import StorageBackend
from webgis_gee.storage.factory import create_storage_backend
from webgis_gee.runtime.resources import RuntimeResourceController
from webgis_gee.runtime.resources import ResourceQuotaCoordinator
from webgis_gee.workflow.executor import WorkflowExecutor
from webgis_gee.workflow.validator import WorkflowValidator
from webgis_gee.workflow.versioning import WorkflowDefinitionMigrator

logger = logging.getLogger(__name__)


class WorkflowService:
    """Application service used by FastAPI or Celery integration layers."""

    def __init__(
        self,
        registry: NodeRegistry | None = None,
        settings: Settings | None = None,
        account_pool: InMemoryAccountPool | None = None,
        storage_backend: StorageBackend | None = None,
        resource_controller: RuntimeResourceController | None = None,
        quota_coordinator: ResourceQuotaCoordinator | None = None,
        metrics_collector: InMemoryMetricsCollector | None = None,
        event_sink: StructuredEventSink | None = None,
        metrics_sink: MetricsSink | None = None,
    ) -> None:
        self._registry = registry or NodeRegistry()
        self._settings = settings or Settings()
        self._account_pool = account_pool
        self._storage_backend = storage_backend
        self._event_sink = event_sink
        self._resource_controller = resource_controller or RuntimeResourceController(
            max_parallel_exports=self._settings.max_parallel_exports,
            max_parallel_uploads=self._settings.max_parallel_uploads,
            max_parallel_downloads=self._settings.max_parallel_downloads,
            max_local_write_bytes=self._settings.max_local_write_bytes,
            quota_coordinator=quota_coordinator,
        )
        self._metrics = metrics_collector or InMemoryMetricsCollector(
            metrics_sink=metrics_sink
        )
        self._migrator = WorkflowDefinitionMigrator(self._registry)
        self._validator = WorkflowValidator(self._registry, migrator=self._migrator)
        self._executor = WorkflowExecutor(self._registry)
        self._diagnostics = DiagnosticsService(
            registry=self._registry,
            settings=self._settings,
            account_pool=self._account_pool,
            resource_controller=self._resource_controller,
            metrics_collector=self._metrics,
            event_sink=self._event_sink,
            workflow_migrator=self._migrator,
        )
        self._task_service = GeeExportTaskService(
            settings=self._settings,
            storage_backend=self._storage_backend,
            resource_controller=self._resource_controller,
        )
        self._register_default_nodes()

    def _register_default_nodes(self) -> None:
        default_nodes = (
            SampleInputNode,
            SampleComputeNode,
            SampleOutputNode,
            LiteralNode,
            IdentityNode,
            BatchCollectNode,
            BatchFilterNode,
            BatchFlattenNode,
            BatchMapNode,
            BatchSplitByRegionsNode,
            BatchSplitByTimeNode,
            GeeImageNode,
            GeeCloudMaskNode,
            GeeClipNode,
            GeeSelectBandsNode,
            GeeSpectralIndexNode,
            GeeRasterAlgebraNode,
            GeeThresholdClassifyNode,
            GeeReclassifyNode,
            GeeImageCollectionCompositeNode,
            GeeRegionStatsNode,
            GeeTimeSeriesStatsNode,
            GeeExportImageNode,
            GeeExportTableNode,
        )
        for node_cls in default_nodes:
            if not self._registry.has(node_cls.node_type):
                self._registry.register(node_cls)

    def validate_workflow(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        workflow = self.normalize_workflow_definition(workflow)
        self._validator.validate(workflow)
        self._executor.topological_sort(workflow.nodes, workflow.edges)
        return workflow

    def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        context: ExecutionContext | None = None,
    ) -> RunResult:
        workflow = self.normalize_workflow_definition(workflow)
        self._validator.validate(workflow)
        context = context or ExecutionContext(workflow_id=workflow.workflow_id)
        context.metadata.setdefault("resource_controller", self._resource_controller)
        context.metadata.setdefault("metrics_collector", self._metrics)
        context.metadata.setdefault("event_sink", self._event_sink)

        leased_account_id: str | None = None
        gee_context = context.metadata.get("gee_context")
        created_gee_context = False
        workflow_started_at = perf_counter()
        workflow_temp_dir = self._resolve_workflow_temp_root(context) / context.run_id
        context.temp_dir = str(workflow_temp_dir)
        context.metadata["workflow_temp_dir"] = str(workflow_temp_dir)
        context.metadata["storage_backend"] = self._resolve_storage_backend(
            workflow=workflow,
            context=context,
        )
        self._metrics.increment("workflow.execute.started")
        log_structured_event(
            logger,
            logging.INFO,
            "workflow.execute.started",
            sink=self._event_sink,
            run_id=context.run_id,
            workflow_id=workflow.workflow_id,
            account_id=context.account_id,
        )
        if self._account_pool is not None and context.account_id is None:
            lease = self._account_pool.acquire()
            leased_account_id = lease.account_id
            context.account_id = lease.account_id
            # 把账号池中 lease 携带的凭证/project_id 透传到后续 GeeContext 构造
            leased_credentials = lease.credentials
            leased_project_id = lease.project_id
            self._metrics.increment("account.lease.acquired")
            log_structured_event(
                logger,
                logging.INFO,
                "account.lease.acquired",
                sink=self._event_sink,
                run_id=context.run_id,
                workflow_id=workflow.workflow_id,
                account_id=lease.account_id,
            )
        else:
            leased_credentials = None
            leased_project_id = None

        if context.account_id and gee_context is None:
            # 优先用账号池 lease 携带的凭证；否则查 pool.get(account_id) 兜底
            credentials = leased_credentials
            project_id = leased_project_id
            if credentials is None and self._account_pool is not None:
                try:
                    pool_lease = self._account_pool.get(context.account_id)
                    credentials = pool_lease.credentials
                    project_id = pool_lease.project_id
                except Exception:
                    pass
            gee_context = GeeContext(
                account_id=context.account_id,
                credentials=credentials,
                project_id=project_id,
            )
            context.metadata["gee_context"] = gee_context
            created_gee_context = True

        try:
            with self._resource_controller.workflow_scope(
                run_id=context.run_id,
                temp_root=str(self._resolve_workflow_temp_root(context)),
            ) as workflow_temp_dir:
                context.temp_dir = workflow_temp_dir
                context.metadata["workflow_temp_dir"] = workflow_temp_dir
                result = self._executor.execute(workflow, context)
        except Exception as exc:
            duration_ms = (perf_counter() - workflow_started_at) * 1000
            self._metrics.increment("workflow.execute.failed")
            self._metrics.observe_duration("workflow.execute.duration_ms", duration_ms)
            log_structured_event(
                logger,
                logging.ERROR,
                "workflow.execute.failed",
                sink=self._event_sink,
                run_id=context.run_id,
                workflow_id=workflow.workflow_id,
                account_id=context.account_id,
                duration_ms=round(duration_ms, 3),
                error=str(exc),
            )
            if leased_account_id is not None:
                self._finalize_account_exception(leased_account_id, exc)
            raise
        finally:
            if created_gee_context and gee_context is not None:
                gee_context.close()

        if leased_account_id is not None:
            self._finalize_account_lease(leased_account_id, result)
        duration_ms = (perf_counter() - workflow_started_at) * 1000
        if result.status == RunStatus.COMPLETED:
            self._metrics.increment("workflow.execute.completed")
        else:
            self._metrics.increment("workflow.execute.failed")
        self._metrics.observe_duration("workflow.execute.duration_ms", duration_ms)
        log_structured_event(
            logger,
            logging.INFO if result.status == RunStatus.COMPLETED else logging.WARNING,
            "workflow.execute.finished",
            sink=self._event_sink,
            run_id=context.run_id,
            workflow_id=workflow.workflow_id,
            account_id=context.account_id,
            status=result.status.value,
            node_count=len(result.node_results),
            error_count=len(result.errors),
            warning_count=len(result.warnings),
            duration_ms=round(duration_ms, 3),
        )
        return result

    def normalize_workflow_definition(
        self,
        workflow: WorkflowDefinition | dict[str, object],
    ) -> WorkflowDefinition:
        return self._migrator.to_workflow_definition(workflow)

    def diagnose(self) -> DiagnosticsReport:
        return self._diagnostics.run()

    def poll_export_task(
        self,
        manifest_uri: str | None = None,
        task_ref: dict[str, object] | None = None,
        gee_module: object | None = None,
        update_manifest: bool = True,
    ) -> dict[str, object]:
        return self._task_service.poll_task(
            manifest_uri=manifest_uri,
            task_ref=task_ref,
            gee_module=gee_module,
            update_manifest=update_manifest,
        )

    def _finalize_account_lease(self, account_id: str, result: RunResult) -> None:
        if result.status == RunStatus.COMPLETED:
            self._account_pool.release(account_id)
            self._metrics.increment("account.lease.released")
            log_structured_event(
                logger,
                logging.INFO,
                "account.lease.released",
                sink=self._event_sink,
                account_id=account_id,
                outcome="success",
            )
            return

        decision = classify_gee_error(*(result.errors + result.warnings))
        if decision.should_cooldown_account:
            self._account_pool.mark_failure(
                account_id,
                seconds=self._settings.account_cooldown_seconds,
                reason=decision.reason,
            )
            self._metrics.increment("account.lease.cooldown")
            log_structured_event(
                logger,
                logging.WARNING,
                "account.lease.cooldown",
                sink=self._event_sink,
                account_id=account_id,
                reason=decision.reason,
                cooldown_seconds=self._settings.account_cooldown_seconds,
            )
            return

        self._account_pool.release(account_id)
        self._metrics.increment("account.lease.released")
        log_structured_event(
            logger,
            logging.INFO,
            "account.lease.released",
            sink=self._event_sink,
            account_id=account_id,
            outcome="non_account_failure",
        )

    def _finalize_account_exception(self, account_id: str, exc: Exception) -> None:
        decision = classify_gee_error(str(exc))
        if decision.should_cooldown_account:
            self._account_pool.mark_failure(
                account_id,
                seconds=self._settings.account_cooldown_seconds,
                reason=decision.reason,
            )
            self._metrics.increment("account.lease.cooldown")
            log_structured_event(
                logger,
                logging.WARNING,
                "account.lease.cooldown",
                sink=self._event_sink,
                account_id=account_id,
                reason=decision.reason,
                cooldown_seconds=self._settings.account_cooldown_seconds,
            )
            return
        self._account_pool.release(account_id)
        self._metrics.increment("account.lease.released")
        log_structured_event(
            logger,
            logging.INFO,
            "account.lease.released",
            sink=self._event_sink,
            account_id=account_id,
            outcome="exception_release",
        )

    def _resolve_workflow_temp_root(self, context: ExecutionContext) -> Path:
        default_temp_dir = ExecutionContext.model_fields["temp_dir"].default
        temp_root = (
            context.temp_dir
            if context.temp_dir != default_temp_dir
            else self._settings.temp_dir
        )
        return Path(temp_root).resolve()

    def _wrap_existing_storage_backend(
        self,
        backend: StorageBackend,
        *,
        context: ExecutionContext,
    ) -> StorageBackend:
        return self._resource_controller.wrap_storage_backend(
            backend,
            run_id=context.run_id,
        )

    def _resolve_storage_backend(
        self,
        *,
        workflow: WorkflowDefinition,
        context: ExecutionContext,
    ) -> StorageBackend:
        existing_backend = context.metadata.get("storage_backend")
        if isinstance(existing_backend, StorageBackend):
            return self._wrap_existing_storage_backend(
                existing_backend, context=context
            )
        if self._storage_backend is not None:
            return self._wrap_existing_storage_backend(
                self._storage_backend, context=context
            )

        backend_type = (
            workflow.storage_policy.backend
            or context.storage_backend
            or self._settings.storage_backend
        )
        local_storage_root = (
            workflow.storage_policy.base_path or self._settings.local_storage_root
        )
        return self._resource_controller.wrap_storage_backend(
            create_storage_backend(
                self._settings,
                backend_type=backend_type,
                local_storage_root=local_storage_root,
            ),
            run_id=context.run_id,
        )
