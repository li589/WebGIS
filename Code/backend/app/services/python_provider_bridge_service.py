from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
import importlib
import logging
from pathlib import Path
import sys
from typing import Any, Iterator
from urllib.parse import unquote, urlparse

from app.core.config import settings
from app.services.result_storage import result_storage_service
from app.services.workflow_execution import WorkflowExecutionResult
from app.services.workflow_request_resolver import describe_python_provider_resolution
from shared.contracts.api_contracts import (
    AlgorithmWorkflowRequest,
    ResultKind,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)

logger = logging.getLogger(__name__)

_ALGORITHM_REQUEST_ENTRY_KEYS = ("module_name", "workflow_name", "workflow_definition")
_ALGORITHM_PRIORITY_MAP = {
    "low": 1,
    "normal": 5,
    "high": 8,
    "critical": 9,
}
_ARTIFACT_MIME_TYPES = {
    "manifest": "application/json",
    "metadata": "application/json",
    "log": "text/plain",
}

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
    def supports(self, payload: WorkflowSubmitRequest) -> bool:
        # M8 修复：与其他 bridge 对齐 enabled flag 检查
        if not settings.python_provider_enabled:
            return False
        algorithm_request = self._normalize_algorithm_request(payload.algorithm_request)
        return any(key in algorithm_request for key in _ALGORITHM_REQUEST_ENTRY_KEYS)

    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        # Stub 拦截：尚未实现的模块返回 pending_implementation 状态，不调用 provider
        algorithm_request = self._normalize_algorithm_request(payload.algorithm_request)
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

        request_payload = self._build_job_request_payload(
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
                    message=self._build_validation_error_message(
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

        job_result = self._as_dict(response_body.get("job_result"))
        result_dto = self._as_dict(response_body.get("result_dto"))
        result_refs = self._build_result_refs(
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
        manifest_summary = self._as_dict(result_dto.get("manifest_summary"))
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

    def _build_job_request_payload(
        self, *, run_id: str, payload: WorkflowSubmitRequest
    ) -> dict[str, Any]:
        algorithm_request = self._normalize_algorithm_request(payload.algorithm_request)
        if not any(key in algorithm_request for key in _ALGORITHM_REQUEST_ENTRY_KEYS):
            raise ValueError(
                "algorithm_request 必须至少包含 module_name、workflow_name 或 workflow_definition 之一。"
            )

        request_payload = dict(algorithm_request)
        request_payload.setdefault("job_id", run_id)
        request_payload.setdefault("pipeline_name", "workflow")
        request_payload.setdefault(
            "task_type",
            algorithm_request.get("task_type") or payload.command_type.value,
        )
        request_payload.setdefault("datasource_selection", {})
        request_payload.setdefault("algorithm_params", {})
        request_payload.setdefault(
            "output_spec", {"include_manifest": True, "extra": {}}
        )
        request_payload.setdefault("tags", {})
        if isinstance(request_payload["tags"], dict):
            request_payload["tags"].setdefault("workflow_run_id", run_id)
            request_payload["tags"].setdefault(
                "workflow_command_type", payload.command_type.value
            )
            if payload.layer_id:
                request_payload["tags"].setdefault(
                    "workflow_layer_id", payload.layer_id
                )

        # Inject open-data presets + portal credentials for http_open_data nodes
        try:
            from app.services.config_service import (
                get_data_source_config,
            )

            presets = get_data_source_config().get("open_data_presets") or {}
            ds = request_payload.get("datasource_selection")
            if not isinstance(ds, dict):
                ds = {}
                request_payload["datasource_selection"] = ds
            if isinstance(presets, dict) and presets:
                ds.setdefault("open_data_presets", presets)
            # Do NOT embed plaintext portal tokens in the job payload (persisted /
            # logged). Nodes resolve secrets lazily via portal_credentials_resolve.
            ds.setdefault("portal_credentials_resolve", True)
            ds.pop("portal_credentials", None)
        except Exception:  # noqa: BLE001
            pass

        if payload.time_range is not None and "time_range" not in request_payload:
            request_payload["time_range"] = {
                "start": payload.time_range.start_at.isoformat(),
                "end": payload.time_range.end_at.isoformat(),
            }

        if "region" not in request_payload:
            request_payload["region"] = self._build_region_payload(payload)

        if request_payload.get("priority") is None:
            request_payload["priority"] = _ALGORITHM_PRIORITY_MAP[
                payload.priority.value
            ]

        algorithm_params = request_payload.get("algorithm_params")
        if not isinstance(algorithm_params, dict):
            request_payload["algorithm_params"] = {}
            algorithm_params = request_payload["algorithm_params"]
        for key, value in payload.parameters.items():
            algorithm_params.setdefault(key, value)

        output_spec = request_payload.get("output_spec")
        if not isinstance(output_spec, dict):
            output_spec = {"include_manifest": True, "extra": {}}
            request_payload["output_spec"] = output_spec
        output_spec.setdefault("include_manifest", True)
        output_spec.setdefault("include_qc", True)
        output_spec.setdefault("raster_format", "COG")
        output_spec.setdefault("table_format", "parquet")
        if not isinstance(output_spec.get("extra"), dict):
            output_spec["extra"] = {}

        self._validate_algorithm_request_shape(request_payload)
        return request_payload

    def _build_region_payload(self, payload: WorkflowSubmitRequest) -> dict[str, Any]:
        bbox = payload.spatial_filter.bbox if payload.spatial_filter else None
        if bbox is not None:
            return {
                "kind": "bbox",
                "value": {
                    "xmin": bbox.west,
                    "ymin": bbox.south,
                    "xmax": bbox.east,
                    "ymax": bbox.north,
                    "crs": bbox.crs,
                },
            }
        return {"kind": "global", "value": {}}

    def _build_result_refs(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        request_payload: dict[str, Any],
        job_result: dict[str, Any],
        result_dto: dict[str, Any],
    ) -> list[WorkflowResultReference]:
        requested_output_kinds = {
            item.value if isinstance(item, ResultKind) else str(item)
            for item in payload.requested_outputs
        }

        result_refs: list[WorkflowResultReference] = [
            WorkflowResultReference(
                result_id=f"algorithm-result-{run_id[-8:]}",
                result_kind=ResultKind.json,
                title="Algorithm Task Result",
                mime_type="application/json",
                inline_data={
                    "workflow": {
                        "run_id": run_id,
                        "command_type": payload.command_type.value,
                        "layer_id": payload.layer_id,
                    },
                    "algorithm_request": request_payload,
                    "job_result": job_result,
                    "result_dto": result_dto,
                },
                updated_at=requested_at,
            )
        ]

        if ResultKind.text.value in requested_output_kinds:
            summary = self._build_text_summary(
                request_payload=request_payload,
                job_result=job_result,
                result_dto=result_dto,
            )
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"algorithm-summary-{run_id[-8:]}",
                    result_kind=ResultKind.text,
                    title="Algorithm Task Summary",
                    mime_type="text/plain",
                    inline_data={"text": summary},
                    updated_at=requested_at,
                )
            )

        result_refs.extend(
            self._build_artifact_refs(
                run_id=run_id,
                requested_at=requested_at,
                result_dto=result_dto,
            )
        )
        return result_refs

    def _build_text_summary(
        self,
        *,
        request_payload: dict[str, Any],
        job_result: dict[str, Any],
        result_dto: dict[str, Any],
    ) -> str:
        entry_name = (
            request_payload.get("workflow_name")
            or request_payload.get("module_name")
            or "workflow_definition"
        )
        manifest_summary = self._as_dict(result_dto.get("manifest_summary"))
        return (
            f"算法任务 {entry_name} 已执行完成，"
            f"job_status={job_result.get('status')}，"
            f"manifest_loaded={bool(result_dto.get('manifest_loaded'))}，"
            f"products={manifest_summary.get('product_count', 0)}。"
        )

    def _build_artifact_refs(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        result_dto: dict[str, Any],
    ) -> list[WorkflowResultReference]:
        artifacts = self._as_dict(result_dto.get("artifacts"))
        artifact_refs: list[WorkflowResultReference] = []
        for artifact_name in ("manifest", "metadata", "log"):
            artifact_view = self._as_dict(artifacts.get(artifact_name))
            if not artifact_view:
                continue
            artifact_ref = self._build_artifact_ref(
                run_id=run_id,
                requested_at=requested_at,
                artifact_name=artifact_name,
                artifact_view=artifact_view,
            )
            if artifact_ref is not None:
                artifact_refs.append(artifact_ref)
        return artifact_refs

    def _build_artifact_ref(
        self,
        *,
        run_id: str,
        requested_at: datetime,
        artifact_name: str,
        artifact_view: dict[str, Any],
    ) -> WorkflowResultReference | None:
        title = f"Algorithm {artifact_name}"
        uri = str(
            artifact_view.get("download_url")
            or artifact_view.get("preview_url")
            or artifact_view.get("uri")
            or ""
        ).strip()
        if not uri:
            return None

        local_path = self._uri_to_local_path(uri)
        if local_path is not None and local_path.exists() and local_path.is_file():
            payload = local_path.read_bytes()
            return result_storage_service.create_artifact_result_ref(
                run_id=run_id,
                result_id=f"algorithm-{artifact_name}-{local_path.stem}",
                result_kind=ResultKind.file,
                title=title,
                mime_type=_ARTIFACT_MIME_TYPES[artifact_name],
                updated_at=requested_at,
                payload=payload,
            )

        parsed = urlparse(uri)
        resource_backend = str(
            artifact_view.get("storage_backend") or parsed.scheme or "external"
        )
        resource_key = str(artifact_view.get("object_key") or parsed.path or uri)
        if resource_backend == "file" and not resource_key.startswith("/"):
            resource_key = f"/{resource_key.lstrip('/')}"
        return WorkflowResultReference(
            result_id=f"algorithm-{artifact_name}-{run_id[-8:]}",
            result_kind=ResultKind.file,
            title=title,
            mime_type=_ARTIFACT_MIME_TYPES[artifact_name],
            resource_url=uri,
            resource_backend=resource_backend,
            resource_key=resource_key,
            updated_at=requested_at,
        )

    def _uri_to_local_path(self, uri: str) -> Path | None:
        parsed = urlparse(uri)
        if parsed.scheme not in {"", "file"}:
            return None
        if parsed.scheme == "file":
            raw_path = unquote(f"{parsed.netloc}{parsed.path}")
        else:
            raw_path = unquote(uri)
        if raw_path.startswith("/") and len(raw_path) > 2 and raw_path[2] == ":":
            raw_path = raw_path[1:]
        if not raw_path:
            return None
        return Path(raw_path)

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {}

    def _normalize_algorithm_request(
        self, value: AlgorithmWorkflowRequest | dict[str, Any] | Any
    ) -> dict[str, Any]:
        if isinstance(value, AlgorithmWorkflowRequest):
            return value.model_dump(mode="json", exclude_none=True)
        if isinstance(value, dict):
            return dict(value)
        return {}

    @staticmethod
    def _build_validation_error_message(
        *,
        errors: list[str],
        resolution_diagnostics: dict[str, Any] | None,
    ) -> str:
        base_message = f"Provider template validation failed: {'; '.join(errors)}"
        if not resolution_diagnostics:
            return base_message

        unresolved_datasets = (
            resolution_diagnostics.get("unresolved_default_datasets") or []
        )
        if not unresolved_datasets:
            return base_message

        dataset_text = "; ".join(
            f"{item['dataset_name']} <= {', '.join(item.get('candidate_sources') or [])}"
            for item in unresolved_datasets
        )
        layer_id = resolution_diagnostics.get("layer_id") or "unknown-layer"
        module_name = resolution_diagnostics.get("module_name") or "unknown-module"
        layer_status = resolution_diagnostics.get("layer_status") or "unknown"
        return (
            f"{base_message} Default data sources are not ready for layer '{layer_id}' "
            f"(module={module_name}, status={layer_status}): {dataset_text}"
        )

    def _validate_algorithm_request_shape(
        self, request_payload: dict[str, Any]
    ) -> None:
        if not isinstance(request_payload.get("datasource_selection"), dict):
            raise ValueError("algorithm_request.datasource_selection 必须为 object。")
        if not isinstance(request_payload.get("algorithm_params"), dict):
            raise ValueError("algorithm_request.algorithm_params 必须为 object。")
        if not isinstance(request_payload.get("output_spec"), dict):
            raise ValueError("algorithm_request.output_spec 必须为 object。")
        if not isinstance(request_payload.get("tags"), dict):
            raise ValueError("algorithm_request.tags 必须为 object。")

        # 协议统一增强：校验 time_range 内部结构，提前在 bridge 层暴露错误
        # Python provider 侧 TimeRange 要求 {start: str, end: str, step?: str}
        time_range = request_payload.get("time_range")
        if time_range is not None:
            if not isinstance(time_range, dict):
                raise ValueError("algorithm_request.time_range 必须为 object。")
            if "start" not in time_range or "end" not in time_range:
                raise ValueError(
                    "algorithm_request.time_range 必须包含 'start' 和 'end' 字段（ISO 8601 字符串）。"
                )

        # 协议统一增强：校验 region 内部结构
        # Python provider 侧 RegionSpec 要求 {kind: str, value: dict}
        region = request_payload.get("region")
        if region is not None:
            if not isinstance(region, dict):
                raise ValueError("algorithm_request.region 必须为 object。")
            if "kind" not in region or "value" not in region:
                raise ValueError(
                    "algorithm_request.region 必须包含 'kind' 和 'value' 字段。"
                )

        if (
            request_payload.get("workflow_definition") is not None
            and request_payload.get("module_name") is not None
        ):
            raise ValueError(
                "algorithm_request.workflow_definition 与 module_name 不能同时出现。"
            )


python_provider_bridge_service = PythonProviderBridgeService()
