from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import datetime
from functools import lru_cache
import importlib
import logging
from pathlib import Path
import sys
from typing import Any, Iterator

from app.core.config import settings
from app.services.workflow_execution import WorkflowExecutionResult
from shared.contracts.api_contracts import (
    GeeWorkflowRequest,
    ResultKind,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)


def reload_gee_facade() -> None:
    """清空 _load_gee_facade 的 lru_cache，让下次访问时重建 facade（含账号池）。

    在账号增删/启用/禁用后调用，使新的凭证配置生效。
    """
    _load_gee_facade.cache_clear()


def _build_account_pool_from_repository(
    gee_module_import_path_ctx,
    *,
    pool_cls,
    account_config_cls,
    credentials_loader_cls,
):
    """从 GeeCredentialsRepository 加载账号并构造 InMemoryAccountPool。

    返回 (account_pool, account_count)。失败时返回 (None, 0) 并记录 warning。
    """
    try:
        from app.services.gee_credentials_repository import GeeCredentialsRepository

        repo = GeeCredentialsRepository(
            db_path=settings.gee_credentials_db_path,
            encryption_key=settings.gee_credentials_encryption_key,
        )
        accounts_with_creds = repo.list_enabled_accounts_with_credentials()
    except Exception as exc:
        logger.warning(
            "Failed to load GEE credentials repository (%s); "
            "falling back to global ~/.config/earthengine/ credentials",
            exc,
        )
        return None, 0

    if not accounts_with_creds:
        logger.warning(
            "GEE account pool is empty; workflows will fall back to "
            "ee.Initialize() without credentials (requires ~/.config/earthengine/)"
        )
        return None, 0

    configs = []
    for account_id, sa_json, project_id in accounts_with_creds:
        try:
            with gee_module_import_path_ctx:
                creds = credentials_loader_cls.load_service_account_credentials(
                    sa_json, project_id=project_id
                )
            display_name = sa_json.get("client_email") if isinstance(sa_json, dict) else account_id
            configs.append(
                account_config_cls(
                    account_id=account_id,
                    credentials=creds,
                    project_id=project_id,
                    account_type="service_account",
                    display_name=display_name,
                )
            )
        except Exception as exc:
            logger.exception(
                "Failed to load credentials for GEE account %s",
                account_id,
            )

    if not configs:
        return None, 0

    pool = pool_cls(accounts=configs)
    logger.info("Loaded %d GEE account(s) into pool", len(configs))
    return pool, len(configs)


def _is_account_unavailable_error(exc: BaseException) -> bool:
    global _AccountUnavailableError_cls
    if _AccountUnavailableError_cls is not None:
        return isinstance(exc, _AccountUnavailableError_cls)
    try:
        from webgis_gee.runtime.exceptions import AccountUnavailableError as _cls
        _AccountUnavailableError_cls = _cls
        return isinstance(exc, _cls)
    except Exception:
        return False


_AccountUnavailableError_cls: type | None = None


@contextmanager
def _gee_module_import_path(module_root: Path) -> Iterator[None]:
    module_path = str(module_root)
    inserted = False
    if module_path not in sys.path:
        sys.path.insert(0, module_path)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(module_path)
            except ValueError:
                pass


@lru_cache(maxsize=1)
def _load_gee_facade():
    """惰性加载 webgis_gee 并构造默认 facade。

    M7 修复：与其他 bridge 一致，使用无参 lru_cache 单例。
    配置全部从 settings 全局读取，无需作为 cache key。
    通过 lru_cache 保证进程内只初始化一次，避免重复注册节点。
    """

    module_root = Path(settings.gee_module_root)
    if not module_root.exists():
        raise RuntimeError(f"GEE module root does not exist: {module_root}")

    Path(settings.gee_local_storage_root).mkdir(parents=True, exist_ok=True)

    with _gee_module_import_path(module_root):
        settings_module = importlib.import_module("webgis_gee.config.settings")
        services_module = importlib.import_module("webgis_gee.application.services")
        facade_module = importlib.import_module("webgis_gee.api.facade")
        contracts_module = importlib.import_module("webgis_gee.api.contracts")

        gee_settings_cls = getattr(settings_module, "Settings")
        contract_adapter_cls = getattr(contracts_module, "WorkflowContractAdapter")
        workflow_service_cls = getattr(services_module, "WorkflowService")

        gee_settings = gee_settings_cls(
            storage_backend=settings.gee_storage_backend,
            local_storage_root=settings.gee_local_storage_root,
            minio_endpoint=settings.gee_minio_endpoint or None,
            minio_access_key=settings.gee_minio_access_key or None,
            minio_secret_key=settings.gee_minio_secret_key or None,
            minio_bucket=settings.gee_minio_bucket or None,
            minio_secure=settings.gee_minio_secure,
            account_cooldown_seconds=settings.gee_account_cooldown_seconds,
            max_parallel_exports=settings.gee_max_parallel_exports,
            max_parallel_uploads=settings.gee_max_parallel_uploads,
            max_parallel_downloads=settings.gee_max_parallel_downloads,
            max_local_write_bytes=settings.gee_max_local_write_bytes,
        )

        # Build account pool from the credentials repository; fall back to pool=None
        # on any failure so facade construction still succeeds. nullcontext is safe
        # here because we are already inside _gee_module_import_path, and it can be
        # re-entered per-account within _build_account_pool_from_repository.
        pool = None
        account_count = 0
        try:
            pool_module = importlib.import_module("webgis_gee.accounts.pool")
            credentials_module = importlib.import_module("webgis_gee.accounts.credentials")
            pool, account_count = _build_account_pool_from_repository(
                nullcontext(),
                pool_cls=getattr(pool_module, "InMemoryAccountPool"),
                account_config_cls=getattr(pool_module, "AccountConfig"),
                credentials_loader_cls=getattr(credentials_module, "GeeCredentialsLoader"),
            )
        except Exception as exc:
            logger.warning("Failed to build GEE account pool (%s); continuing without pool", exc)
            pool = None
            account_count = 0
        logger.info("GEE account pool prepared: %d account(s) loaded", account_count)

        # 用 gee_settings + account_pool 构造 WorkflowService，确保 resource_controller、
        # task_service、storage_backend 等内部组件使用正确的配置
        service = workflow_service_cls(settings=gee_settings, account_pool=pool)

        adapter = contract_adapter_cls(service)
        api_facade_cls = getattr(facade_module, "WorkflowApiFacade")
        return api_facade_cls(adapter=adapter)


class GeeBridgeService:
    """把 webgis_gee 引擎桥接到 workflow-runs 主链。

    与 PythonProviderBridgeService 平行：
    - supports(payload) 通过 gee_request 字段判断是否接管
    - execute() 调用 facade.submit_workflow_response，映射为 WorkflowExecutionResult
    - 额外暴露 list_workflows / describe / panel-schema / diagnostics / export_status
    """

    def supports(self, payload: WorkflowSubmitRequest) -> bool:
        if not settings.gee_enabled:
            return False
        gee_request = self._normalize_gee_request(payload.gee_request)
        if not gee_request:
            return False
        # 接管条件：显式提供了 workflow 或 manifest_uri
        return bool(gee_request.get("workflow") or gee_request.get("manifest_uri"))

    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        gee_request = self._normalize_gee_request(payload.gee_request)
        manifest_uri = gee_request.get("manifest_uri")

        # 导出状态轮询分支：当只提供 manifest_uri 而无 workflow 时，走轮询路径
        if manifest_uri and not gee_request.get("workflow"):
            return self._execute_export_poll(
                run_id=run_id,
                payload=payload,
                requested_at=requested_at,
                event_factory=event_factory,
                manifest_uri=str(manifest_uri),
                update_manifest=bool(gee_request.get("update_manifest", False)),
            )

        return self._execute_workflow(
            run_id=run_id,
            payload=payload,
            requested_at=requested_at,
            event_factory=event_factory,
            gee_request=gee_request,
        )

    # ------------------------------------------------------------------ workflow 执行

    def _execute_workflow(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
        gee_request: dict[str, Any],
    ) -> WorkflowExecutionResult:
        facade = self._get_facade()
        workflow = gee_request.get("workflow")
        context = gee_request.get("context") or self._build_default_context(payload, run_id)

        try:
            response = facade.submit_workflow(workflow, context)
        except Exception as exc:
            if _is_account_unavailable_error(exc):
                logger.warning(
                    "GEE workflow %s failed: no account pool/credentials available (%s)",
                    run_id,
                    exc,
                )
                return self._credentials_error_result(
                    run_id=run_id, exc=exc, event_factory=event_factory
                )
            raise
        result_refs = self._build_result_refs(
            run_id=run_id,
            payload=payload,
            requested_at=requested_at,
            response=response,
        )
        entry_name = response.workflow_id or gee_request.get("workflow_id") or "gee_workflow"
        # C3 修复：run_id 统一为 outer-side（主链 run_id），engine-side 用 engine_run_id
        # 与 weather_bridge_service 保持一致语义
        result_dto = {
            "workflow_entry_name": entry_name,
            "run_id": run_id,
            "engine_run_id": response.run_id,
            "job_status": response.status,
            "node_count": len(response.node_results),
            "artifact_count": len(response.artifacts),
            "outputs": response.outputs,
            "warnings": list(response.warnings),
            "errors": list(response.errors),
            "saveback_terminal_plan": (
                response.saveback_terminal_plan.model_dump(mode="python")
                if response.saveback_terminal_plan
                else None
            ),
        }
        events = [
            event_factory(
                channel="log",
                message=f"GEE 工作流 {entry_name} 已完成执行，status={response.status}。",
                progress=74,
                payload={
                    "run_id": response.run_id,
                    "workflow_id": response.workflow_id,
                    "status": response.status,
                    "node_count": len(response.node_results),
                },
            ),
            event_factory(
                channel="data",
                message="GEE 结果已映射为 workflow 结果引用。",
                progress=95,
                payload={
                    "result_count": len(result_refs),
                    "artifact_count": len(response.artifacts),
                    "entry_name": entry_name,
                },
            ),
        ]
        diagnostics = [
            "gee_bridge_service 已接入 workflow-runs 主链。",
            f"gee_module_root={settings.gee_module_root}",
            f"gee_storage_backend={settings.gee_storage_backend}",
            f"engine_run_id={response.run_id}",
            f"engine_workflow_id={response.workflow_id}",
            f"engine_status={response.status}",
            f"engine_node_count={len(response.node_results)}",
            f"engine_artifact_count={len(response.artifacts)}",
        ]
        if response.warnings:
            diagnostics.append(f"gee_warnings={len(response.warnings)}")
        if response.errors:
            diagnostics.append(f"gee_errors={len(response.errors)}")

        message = (
            f"GEE 工作流 {entry_name} 执行完成，"
            f"status={response.status}，已生成 {len(result_refs)} 个结果引用。"
        )
        if response.errors:
            # 保留 errors 但仍返回结果引用，由上层决定状态机
            diagnostics.extend([f"gee_error={err}" for err in response.errors[:5]])

        return WorkflowExecutionResult(
            message=message,
            result_refs=result_refs,
            result_dto=result_dto,
            diagnostics=diagnostics,
            events=events,
        )

    def _execute_export_poll(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
        manifest_uri: str,
        update_manifest: bool,
    ) -> WorkflowExecutionResult:
        facade = self._get_facade()
        status_response = facade.get_export_task_status(
            manifest_uri=manifest_uri,
            update_manifest=update_manifest,
        )
        result_refs = [
            WorkflowResultReference(
                result_id=f"gee-export-{run_id[-8:]}",
                result_kind=ResultKind.json,
                title="GEE 导出状态",
                mime_type="application/json",
                inline_data=status_response.model_dump(mode="json"),
                updated_at=requested_at,
            )
        ]
        result_dto = {
            "workflow_entry_name": "gee_export_poll",
            "run_id": run_id,
            "manifest_uri": manifest_uri,
            "export_status": status_response.status,
            "export_state": status_response.state,
            "update_manifest": update_manifest,
        }
        events = [
            event_factory(
                channel="log",
                message=f"GEE 导出状态查询完成，status={status_response.status}，state={status_response.state}。",
                progress=95,
                payload={
                    "manifest_uri": manifest_uri,
                    "status": status_response.status,
                    "state": status_response.state,
                },
            ),
        ]
        diagnostics = [
            "gee_bridge_service.export_poll 已接入 workflow-runs 主链。",
            f"manifest_uri={manifest_uri}",
            f"export_status={status_response.status}",
            f"export_state={status_response.state}",
            f"update_manifest={update_manifest}",
        ]
        return WorkflowExecutionResult(
            message=f"GEE 导出状态查询完成，status={status_response.status}。",
            result_refs=result_refs,
            result_dto=result_dto,
            diagnostics=diagnostics,
            events=events,
        )

    # ------------------------------------------------------------------ 元数据接口

    def list_workflows_response(self):
        facade = self._get_facade()
        report = facade.diagnose()
        checks = report.checks or {}
        node_registry = checks.get("node_registry", {})
        # node_registry 结构：{"status": "ok", "supported_node_types": list[str]}
        supported_types = []
        if isinstance(node_registry, dict):
            supported_types = node_registry.get("supported_node_types", []) or []
        workflows = [
            {
                "name": node_type,
                "node_type": node_type,
                "category": "gee" if node_type.startswith("gee_") else "sample",
            }
            for node_type in supported_types
        ]
        return {
            "status_code": 200,
            "body": {
                "workflows": workflows,
                "workflow_count": len(workflows),
                "source": "webgis_gee",
            },
        }

    def describe_workflow_response(self, workflow_name: str):
        facade = self._get_facade()
        report = facade.diagnose()
        checks = report.checks or {}
        node_registry = checks.get("node_registry", {})
        supported_types = []
        if isinstance(node_registry, dict):
            supported_types = node_registry.get("supported_node_types", []) or []
        if workflow_name not in supported_types:
            return {
                "status_code": 404,
                "body": {
                    "error_type": "not_found",
                    "error_code": "gee_workflow_not_found",
                    "user_message": f"GEE 节点类型不存在: {workflow_name}",
                    "developer_message": f"workflow_name not in supported_node_types: {workflow_name}",
                },
            }
        return {
            "status_code": 200,
            "body": {
                "name": workflow_name,
                "node_type": workflow_name,
                "category": "gee" if workflow_name.startswith("gee_") else "sample",
                "source": "webgis_gee",
            },
        }

    def get_workflow_panel_schema_response(self, workflow_name: str):
        # GEE core 当前未提供独立 panel-schema 接口，返回最小占位
        return {
            "status_code": 200,
            "body": {
                "workflow_name": workflow_name,
                "panel_schema": {"fields": []},
                "source": "webgis_gee",
            },
        }

    def get_workflow_ui_schema_response(self, workflow_name: str):
        # GEE core 当前未提供独立 ui-schema 接口，返回空 schema
        return {
            "status_code": 200,
            "body": {
                "workflow_name": workflow_name,
                "ui_schema": {},
                "source": "webgis_gee",
            },
        }

    def get_diagnostics_response(self):
        facade = self._get_facade()
        report = facade.diagnose()
        return {
            "status_code": 200,
            "body": report.model_dump(mode="json"),
        }

    def get_export_status_response(self, manifest_uri: str, update_manifest: bool = False):
        facade = self._get_facade()
        response = facade.get_export_task_status(
            manifest_uri=manifest_uri,
            update_manifest=update_manifest,
        )
        return {
            "status_code": 200,
            "body": response.model_dump(mode="json"),
        }

    # ------------------------------------------------------------------ 内部工具

    def _get_facade(self):
        if not settings.gee_enabled:
            raise RuntimeError("GEE bridge is disabled by BACKEND_GEE_ENABLED=false.")
        try:
            return _load_gee_facade()
        except Exception as exc:
            logger.exception("Failed to initialize GEE facade")
            raise RuntimeError(f"Failed to initialize GEE facade: {exc}") from exc

    def _credentials_error_result(
        self,
        *,
        run_id: str,
        exc: Exception,
        event_factory,
    ) -> WorkflowExecutionResult:
        """Build a clear error result when GEE credentials/account pool is unavailable."""
        message = (
            "GEE credentials not configured — set BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY "
            "and seed credentials via /gee/accounts"
        )
        result_dto = {
            "workflow_entry_name": "gee_workflow",
            "run_id": run_id,
            "error_type": "credentials_not_configured",
            "error_code": "gee_credentials_missing",
            "user_message": message,
            "developer_message": str(exc),
        }
        events = [
            event_factory(
                channel="log",
                message=message,
                progress=95,
                payload={"run_id": run_id, "error_code": "gee_credentials_missing"},
            ),
        ]
        diagnostics = [
            "gee_bridge_service: GEE credentials not configured.",
            f"error={exc}",
            "Set BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY and seed credentials via /gee/accounts.",
        ]
        return WorkflowExecutionResult(
            message=message,
            result_refs=[],
            result_dto=result_dto,
            diagnostics=diagnostics,
            events=events,
        )

    def _build_default_context(self, payload: WorkflowSubmitRequest, run_id: str) -> dict[str, Any]:
        gee_request = self._normalize_gee_request(payload.gee_request)
        metadata: dict[str, Any] = {
            "request_id": run_id,
            "workflow_run_id": run_id,
            "command_type": payload.command_type.value,
        }
        if payload.layer_id:
            metadata["layer_id"] = payload.layer_id
        if payload.correlation_id:
            metadata["correlation_id"] = payload.correlation_id
        context = {
            "workflow_id": gee_request.get("workflow_id"),
            "account_id": None,
            "storage_backend": settings.gee_storage_backend,
            "metadata": metadata,
        }
        return context

    def _build_result_refs(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        response,
    ) -> list[WorkflowResultReference]:
        result_refs: list[WorkflowResultReference] = [
            WorkflowResultReference(
                result_id=f"gee-result-{run_id[-8:]}",
                result_kind=ResultKind.json,
                title="GEE 工作流结果",
                mime_type="application/json",
                inline_data={
                    "workflow": {
                        "run_id": run_id,
                        "engine_run_id": response.run_id,
                        "workflow_id": response.workflow_id,
                        "command_type": payload.command_type.value,
                        "layer_id": payload.layer_id,
                    },
                    "status": response.status,
                    "node_results": response.node_results,
                    "outputs": response.outputs,
                    "warnings": list(response.warnings),
                    "errors": list(response.errors),
                },
                updated_at=requested_at,
            )
        ]

        # artifacts 映射为 file 引用
        for index, artifact in enumerate(response.artifacts):
            artifact_dict = artifact if isinstance(artifact, dict) else artifact.model_dump(mode="python")
            storage_uri = str(artifact_dict.get("storage_uri") or artifact_dict.get("uri") or "")
            if not storage_uri:
                continue
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"gee-artifact-{run_id[-8:]}-{index}",
                    result_kind=ResultKind.file,
                    title=f"GEE artifact {artifact_dict.get('artifact_type', index)}",
                    mime_type=str(artifact_dict.get("content_type") or "application/octet-stream"),
                    resource_url=storage_uri,
                    resource_backend=settings.gee_storage_backend,
                    resource_key=str(artifact_dict.get("artifact_id") or storage_uri),
                    resource_size_bytes=artifact_dict.get("size"),
                    updated_at=requested_at,
                )
            )
        return result_refs

    def _normalize_gee_request(self, value: GeeWorkflowRequest | dict[str, Any] | Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, GeeWorkflowRequest):
            return value.model_dump(mode="json", exclude_none=True)
        if isinstance(value, dict):
            return dict(value)
        return {}


gee_bridge_service = GeeBridgeService()
