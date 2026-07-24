"""Python provider bridge service: algorithm workflow bridge protocol.

Historically a ~789-line god class mixing orchestration, metadata API,
request payload building, result ref construction, and validation
diagnostics. Split (Phase 2 of the architecture review) keeps this file
as the bridge protocol surface (``execute`` / ``supports`` / metadata
API methods / job service loading) and delegates pre-submit and
post-submit concerns to two focused modules:

- :mod:`python_provider_request_builder` — :meth:`build_job_request_payload`,
  :meth:`validate_algorithm_request_shape`,
  :meth:`build_validation_error_message`,
  :meth:`normalize_algorithm_request`.
- :mod:`python_provider_result_builder` — :meth:`build_result_refs`,
  artifact ref construction, URI → local path resolution.

The bridge service owns: stub interception (``_PENDING_IMPLEMENTATION_MODULES``),
job service loading (``_get_job_service`` / ``_load_python_job_service``),
submit/validate dispatch, event/diagnostics assembly, and the metadata
API (list/describe/panel-schema/ui-schema/diagnostics).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
import importlib
import logging
from pathlib import Path
import sys
from typing import Iterator

from app.core.config import settings
from app.services.python_provider_request_builder import (
    ALGORITHM_REQUEST_ENTRY_KEYS,
    PythonProviderRequestBuilder,
    python_provider_request_builder,
)
from app.services.python_provider_result_builder import (
    PythonProviderResultBuilder,
    as_dict,
    python_provider_result_builder,
)
from app.services.workflow_execution import WorkflowExecutionResult
from app.services.workflow_request_resolver import describe_python_provider_resolution
from shared.contracts.api_contracts import WorkflowSubmitRequest

logger = logging.getLogger(__name__)

# 已在节点模板中注册但尚未实现算法的模块。
# 这些模块的 workflow 提交后会返回 pending_implementation 状态，而非调用 provider。
_PENDING_IMPLEMENTATION_MODULES = frozenset(
    {
        "preprocess_reproject",
        "preprocess_resample",
        # preprocess_format_convert implemented as format_convert (alias)
        "preprocess_clip",
        "preprocess_mask",
        "stats_spatial_mean",
        "stats_temporal_trend",
        "stats_anomaly_detect",
        "stats_correlation",
        "stats_histogram",
        "fusion_spatial_interpolate",
        "fusion_multi_source_merge",
        "viz_chart_generate",
        "viz_report_export",
        "viz_statistics_summary",
        "gis_buffer_analysis",
        "gis_zonal_statistics",
        "gis_raster_calculator",
        "gis_vector_to_raster",
        "gis_raster_to_vector",
        "gis_reclassify",
        "gis_contour",
        "gis_slope_aspect",
        "gis_watershed",
    }
)


@contextmanager
def _python_provider_import_path(provider_root: Path) -> Iterator[None]:
    provider_path = str(provider_root)
    inserted = False
    if provider_path not in sys.path:
        sys.path.insert(0, provider_path)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(provider_path)
            except ValueError:
                pass


@lru_cache(maxsize=1)
def _load_python_job_service():
    """M7 修复：与其他 bridge 一致，使用无参 lru_cache 单例。"""
    provider_root = Path(settings.python_provider_root)
    workspace = Path(settings.python_provider_workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    with _python_provider_import_path(provider_root):
        job_api_module = importlib.import_module("service.job_api")
        build_local_persistent_job_service = getattr(
            job_api_module, "build_local_persistent_job_service"
        )
        return build_local_persistent_job_service(
            workspace=workspace, start_worker=False
        )


class PythonProviderBridgeService:
    """Bridge protocol entry point for Python algorithm workflow layers.

    Delegates request building to :class:`PythonProviderRequestBuilder`
    and result building to :class:`PythonProviderResultBuilder`; this
    class owns stub interception, job service loading, submit/validate
    dispatch, and the metadata API.
    """

    def __init__(
        self,
        *,
        request_builder: PythonProviderRequestBuilder | None = None,
        result_builder: PythonProviderResultBuilder | None = None,
    ) -> None:
        # Injected to allow tests to swap builders; defaults to the
        # module-level singletons to preserve original behaviour.
        self._request_builder = request_builder or python_provider_request_builder
        self._result_builder = result_builder or python_provider_result_builder

    # ------------------------------------------------------------------
    # Bridge protocol: supports / execute
    # ------------------------------------------------------------------

    def supports(self, payload: WorkflowSubmitRequest) -> bool:
        # M8 修复：与其他 bridge 对齐 enabled flag 检查
        if not settings.python_provider_enabled:
            return False
        algorithm_request = self._request_builder.normalize_algorithm_request(
            payload.algorithm_request
        )
        return any(key in algorithm_request for key in ALGORITHM_REQUEST_ENTRY_KEYS)

    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        # Stub 拦截：尚未实现的模块返回 pending_implementation 状态，不调用 provider
        algorithm_request = self._request_builder.normalize_algorithm_request(
            payload.algorithm_request
        )
        module_name = (
            algorithm_request.get("module_name")
            or algorithm_request.get("workflow_name")
            or ""
        )
        if module_name in _PENDING_IMPLEMENTATION_MODULES:
            return self._build_pending_implementation_result(
                run_id=run_id,
                module_name=module_name,
                requested_at=requested_at,
                event_factory=event_factory,
            )

        request_payload = self._request_builder.build_job_request_payload(
            run_id=run_id, payload=payload
        )
        service = self._get_job_service()

        # Provider 标准契约模板修复：在 submit_job 前调用 validate_job 做语义校验
        # 修复前：只做 _validate_algorithm_request_shape 结构校验，语义错误要到 run_job 深处才暴露
        # 修复后：调用 provider manifest 的 validate_job_response 提前发现参数错误
        validation_response = service.validate_job_response(request_payload)
        if validation_response.status_code == 200:
            validation_body = dict(validation_response.body)
            if not validation_body.get("is_valid", True):
                errors = validation_body.get("errors", [])
                resolution_diagnostics = describe_python_provider_resolution(payload)
                from app.services.bridge_protocol import BridgeExecutionError
                from shared.contracts.api_contracts import FailureCategory

                raise BridgeExecutionError(
                    category=FailureCategory.validation_error,
                    message=self._request_builder.build_validation_error_message(
                        errors=errors,
                        resolution_diagnostics=resolution_diagnostics,
                    ),
                    details={
                        "validation_errors": errors,
                        "validation_template": validation_body.get("template"),
                        "resolution_diagnostics": resolution_diagnostics,
                    },
                )

        response = service.submit_job(request_payload)
        response_body = dict(response.body)
        if response.status_code >= 400:
            developer_message = str(
                response_body.get("developer_message")
                or response_body.get("user_message")
                or "Python provider job service returned an error."
            )
            # 失败分类修复：区分 4xx（终态）/ 5xx（瞬态）/ 429（限流）
            # 修复前：所有 HTTP >= 400 都抛 ValueError（被分类为 terminal_failure，永不重试）
            # 修复后：5xx/429 抛 BridgeExecutionError(transient_*)，hub 会自动重试
            from app.services.bridge_protocol import BridgeExecutionError
            from app.services.failure_classifier import FailureClassifier

            category = FailureClassifier._classify_http_status(response.status_code)
            raise BridgeExecutionError(
                category=category,
                message=developer_message,
                details={
                    "status_code": response.status_code,
                    "response_body": response_body,
                },
            ) from None

        job_result = as_dict(response_body.get("job_result"))
        result_dto = as_dict(response_body.get("result_dto"))
        result_refs = self._result_builder.build_result_refs(
            run_id=run_id,
            payload=payload,
            requested_at=requested_at,
            request_payload=request_payload,
            job_result=job_result,
            result_dto=result_dto,
        )
        # 协议统一修复：优先使用调用方透传的 workflow_entry_name，避免信息损失
        # 仅当调用方未设置时，才回退到 workflow_name/module_name/"workflow_definition" 重算
        entry_name = (
            request_payload.get("workflow_entry_name")
            or request_payload.get("workflow_name")
            or request_payload.get("module_name")
            or "workflow_definition"
        )
        result_dto["workflow_entry_name"] = entry_name
        events = [
            event_factory(
                channel="log",
                message="Python 算法任务已完成执行。",
                progress=74,
                payload={
                    "job_id": job_result.get("job_id"),
                    "run_id": job_result.get("run_id"),
                    "entry_name": entry_name,
                    "job_status": job_result.get("status"),
                },
            ),
            event_factory(
                channel="data",
                message="算法 result_dto 已映射为 workflow 结果引用。",
                progress=95,
                payload={
                    "result_count": len(result_refs),
                    "manifest_loaded": bool(result_dto.get("manifest_loaded")),
                    "product_count": len(result_dto.get("products") or []),
                    "entry_name": entry_name,
                },
            ),
        ]
        diagnostics = [
            "python_provider_bridge_service 已接入 workflow-runs 主链。",
            f"python_provider_root={settings.python_provider_root}",
            f"python_provider_workspace={settings.python_provider_workspace}",
            f"job_id={job_result.get('job_id')}",
            f"algorithm_status={job_result.get('status')}",
            f"entry_name={entry_name}",
            f"manifest_loaded={bool(result_dto.get('manifest_loaded'))}",
            f"product_count={len(result_dto.get('products') or [])}",
        ]
        manifest_summary = as_dict(result_dto.get("manifest_summary"))
        if manifest_summary:
            diagnostics.extend(
                [
                    f"manifest_product_count={manifest_summary.get('product_count', 0)}",
                    f"conversion_trace_dataset_count={manifest_summary.get('conversion_trace_dataset_count', 0)}",
                    f"conversion_trace_resource_count={manifest_summary.get('conversion_trace_resource_count', 0)}",
                ]
            )

        return WorkflowExecutionResult(
            message=(
                f"Python 算法任务 {entry_name} 执行完成，"
                f"已生成 {len(result_refs)} 个结果引用。"
            ),
            result_refs=result_refs,
            result_dto={
                "workflow_entry_name": entry_name,
                "run_id": run_id,
                "engine_run_id": job_result.get("run_id"),
                "job_id": job_result.get("job_id"),
                "job_status": job_result.get("status"),
                "manifest_loaded": bool(result_dto.get("manifest_loaded")),
                "manifest_summary": manifest_summary,
                "products": result_dto.get("products") or [],
                "main_layers": result_dto.get("main_layers") or [],
                "qc_layers": result_dto.get("qc_layers") or [],
                "tables": result_dto.get("tables") or [],
                "extra": result_dto.get("extra") or {},
                "artifacts": result_dto.get("artifacts") or {},
            },
            diagnostics=diagnostics,
            events=events,
        )

    # ------------------------------------------------------------------
    # Stub interception
    # ------------------------------------------------------------------

    def _build_pending_implementation_result(
        self,
        *,
        run_id: str,
        module_name: str,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        """为尚未实现的模块返回 pending_implementation 状态结果。"""
        message = f"模块 {module_name} 正在开发中，暂不可执行。"
        return WorkflowExecutionResult(
            message=message,
            result_refs=[],
            result_dto={
                "workflow_entry_name": module_name,
                "run_id": run_id,
                "engine_run_id": None,
                "job_id": None,
                "job_status": "pending_implementation",
                "manifest_loaded": False,
                "manifest_summary": {},
                "products": [],
                "main_layers": [],
                "qc_layers": [],
                "tables": [],
                "extra": {"pending_implementation": True, "module_name": module_name},
                "artifacts": {},
            },
            diagnostics=[
                f"module {module_name} is pending implementation",
                f"run_id={run_id}",
            ],
            events=[
                event_factory(
                    channel="log",
                    message=message,
                    progress=100,
                    payload={
                        "module_name": module_name,
                        "status": "pending_implementation",
                        "run_id": run_id,
                    },
                ),
            ],
        )

    # ------------------------------------------------------------------
    # Metadata API (Bridge Protocol)
    # ------------------------------------------------------------------

    def list_workflows_response(self):
        # m25 修复：归一化返回结构，确保包含 workflows/workflow_count/source 字段
        response = self._get_job_service().list_workflows_response()
        return self._normalize_list_response(response, source="python_provider")

    def describe_workflow_response(self, workflow_name: str):
        # m25 修复：归一化返回结构，确保包含 name/node_type/category/source 字段
        response = self._get_job_service().describe_workflow_response(workflow_name)
        return self._normalize_describe_response(
            response, source="python_provider", workflow_name=workflow_name
        )

    @staticmethod
    def _normalize_list_response(response: dict, *, source: str) -> dict:
        """归一化 list_workflows_response 返回结构。"""
        if not isinstance(response, dict) or "status_code" not in response:
            return response  # 非 {status_code, body} 结构，原样返回
        body = response.get("body") or {}
        workflows = body.get("workflows") or body.get("items") or []
        # 若 workflows 为 list[str]，转换为 list[dict]
        normalized_workflows = []
        for item in workflows:
            if isinstance(item, str):
                normalized_workflows.append(
                    {
                        "name": item,
                        "node_type": item,
                        "category": "algorithm",
                    }
                )
            elif isinstance(item, dict):
                if "name" not in item and "workflow_name" in item:
                    item = {**item, "name": item["workflow_name"]}
                if "node_type" not in item and "name" in item:
                    item = {**item, "node_type": item["name"]}
                if "category" not in item:
                    item = {**item, "category": "algorithm"}
                normalized_workflows.append(item)
            else:
                normalized_workflows.append(
                    {"name": str(item), "node_type": str(item), "category": "algorithm"}
                )
        return {
            "status_code": response.get("status_code", 200),
            "body": {
                "workflows": normalized_workflows,
                "workflow_count": len(normalized_workflows),
                "source": source,
            },
        }

    @staticmethod
    def _normalize_describe_response(
        response: dict, *, source: str, workflow_name: str
    ) -> dict:
        """归一化 describe_workflow_response 返回结构。"""
        if not isinstance(response, dict) or "status_code" not in response:
            return response
        body = response.get("body") or {}
        if "name" not in body:
            body = {**body, "name": workflow_name}
        if "node_type" not in body:
            body = {**body, "node_type": workflow_name}
        if "category" not in body:
            body = {**body, "category": "algorithm"}
        if "source" not in body:
            body = {**body, "source": source}
        return {"status_code": response.get("status_code", 200), "body": body}

    def get_workflow_panel_schema_response(self, workflow_name: str):
        return self._get_job_service().get_workflow_panel_schema_response(workflow_name)

    def get_workflow_ui_schema_response(self, workflow_name: str):
        return self._get_job_service().get_workflow_ui_schema_response(workflow_name)

    def get_diagnostics_response(self):
        """返回 Python provider 诊断信息。"""
        try:
            from app.core.config import settings as app_settings

            return {
                "status_code": 200,
                "body": {
                    "source": "python_provider",
                    "python_provider_enabled": app_settings.python_provider_enabled,
                    "python_provider_root": app_settings.python_provider_root,
                    "python_provider_workspace": app_settings.python_provider_workspace,
                },
            }
        except Exception as exc:
            return {
                "status_code": 500,
                "body": {
                    "error_type": "internal_error",
                    "error_code": "python_provider_diagnostics_failed",
                    "user_message": "无法获取 Python provider 诊断信息。",
                    "developer_message": str(exc),
                },
            }

    # ------------------------------------------------------------------
    # Job service loading
    # ------------------------------------------------------------------

    def _get_job_service(self):
        provider_root = Path(settings.python_provider_root)
        if not provider_root.exists():
            raise RuntimeError(f"Python provider root does not exist: {provider_root}")
        try:
            return _load_python_job_service()
        except Exception as exc:  # pragma: no cover - depends on runtime environment
            logger.exception("Failed to initialize Python provider job service")
            raise RuntimeError(
                f"Failed to initialize Python provider job service: {exc}"
            ) from exc


# Module-level singleton preserved for backward compatibility with
# ``from app.services.python_provider_bridge_service import python_provider_bridge_service``.
python_provider_bridge_service = PythonProviderBridgeService()
