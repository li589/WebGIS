from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import logging
from typing import Any

from app.core.config import settings
from app.services.workflow_execution import WorkflowExecutionResult
from app.workflow_engine.models import ExecutionContext, WorkflowDefinition
from shared.contracts.api_contracts import (
    ResultKind,
    WeatherWorkflowRequest,
    WorkflowResultReference,
    WorkflowSubmitRequest,
)
from app.weatherengine.workflow_manager import (
    WorkflowLifecycleManager,
    WorkflowPriority,
    WorkflowState,
    workflow_lifecycle_manager,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_weather_workflow_service():
    """惰性加载 WeatherWorkflowService，避免循环导入和启动时开销。"""
    from app.weatherengine.workflow_service import WeatherWorkflowService
    return WeatherWorkflowService()


class WeatherBridgeService:
    """把天气工作流引擎桥接到 workflow-runs 主链。

    与 GeeBridgeService / PythonProviderBridgeService 平行：
    - supports(payload) 通过 weather_request 字段判断是否接管
    - execute() 调用 WeatherWorkflowService.execute_workflow()，映射为 WorkflowExecutionResult
    - 额外暴露 list_workflows / describe / diagnostics
    """

    def supports(self, payload: WorkflowSubmitRequest) -> bool:
        if not settings.weather_workflow_enabled:
            return False
        weather_request = self._normalize_weather_request(payload.weather_request)
        if not weather_request:
            return False
        return bool(weather_request.get("workflow"))

    # m20 修复：统一 status 字符串转换，避免 .value / str() / model_dump() 三种方式混用
    @staticmethod
    def _status_str(status) -> str:
        """统一将 status 转换为字符串值。

        对于 Enum 成员返回 .value，对于普通字符串直接返回，其他类型走 str()。
        避免 Python 3.11+ 中 str(StrEnum.member) 返回 "EnumClass.member" 的问题。
        """
        if hasattr(status, "value"):
            return status.value
        return str(status)

    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
    ) -> WorkflowExecutionResult:
        weather_request = self._normalize_weather_request(payload.weather_request)
        return self._execute_workflow(
            run_id=run_id,
            payload=payload,
            requested_at=requested_at,
            event_factory=event_factory,
            weather_request=weather_request,
        )

    # ------------------------------------------------------------------ workflow 执行

    def _execute_workflow(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory,
        weather_request: dict[str, Any],
    ) -> WorkflowExecutionResult:
        service = self._get_service()
        workflow = weather_request.get("workflow")
        context = weather_request.get("context") or self._build_default_context(payload, run_id)

        # 从 weather_request 中提取优先级，默认为 VIEWPORT
        priority_str = weather_request.get("priority", "viewport")
        try:
            priority = WorkflowPriority[priority_str.upper()]
        except KeyError:
            priority = WorkflowPriority.VIEWPORT

        # 获取图层 ID
        layer_id = payload.layer_id or weather_request.get("layer_id") or f"weather-{run_id[-8:]}"

        # 将 viewport_bbox 注入到 workflow.inputs，使节点可通过 resolve_bbox() 获取正确的渲染范围
        viewport_bbox_dict = None
        if payload.map_context and payload.map_context.viewport_bbox:
            viewport_bbox_dict = payload.map_context.viewport_bbox.model_dump(mode="json")
            if isinstance(workflow, dict):
                workflow["inputs"] = {**workflow.get("inputs", {}), "viewport_bbox": viewport_bbox_dict}
            elif hasattr(workflow, "inputs") and isinstance(workflow.inputs, dict):
                workflow.inputs["viewport_bbox"] = viewport_bbox_dict

        # 瓦片 workflow 并发执行，不需要 lifecycle manager 的“每图层唯一”互斥替换
        is_tile_workflow = self._is_tile_workflow(weather_request)

        # 注册工作流到生命周期管理器（自动替换旧工作流）
        workflow_id = weather_request.get("workflow_id") or f"wf-{layer_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        def cancel_callback():
            """取消回调：当新工作流替换旧工作流时调用"""
            logger.info("[WeatherBridgeService] Cancel callback triggered for workflow %s", workflow_id)

        if not is_tile_workflow:
            workflow_lifecycle_manager.submit_workflow(
                layer_id=layer_id,
                workflow_id=workflow_id,
                priority=priority,
                bbox=viewport_bbox_dict,
                metadata={
                    "run_id": run_id,
                    "command_type": payload.command_type.value,
                },
                cancel_callback=cancel_callback,
            )

            # 更新状态为运行中
            workflow_lifecycle_manager.update_workflow_state(layer_id, WorkflowState.RUNNING, run_id=run_id)

        # 执行工作流
        exec_context = ExecutionContext.model_validate(context) if isinstance(context, dict) else context
        run_result = service.execute_workflow(workflow, exec_context)

        # P0 修复：检查 run_result.status，失败时抛错让 hub 正确标记 failed
        # 修复前：即使所有节点失败（status=failed），bridge 仍构造成功结果返回
        # 修复后：status=failed 时抛 RuntimeError，hub 会捕获并标记 workflow 为 failed
        # 注意：必须使用 _status_str() 而非 str()，因为 RunStatus(str, Enum) 在
        # Python 3.11+ 下 str() 返回 "RunStatus.failed" 而非 "failed"
        status_str = self._status_str(run_result.status).lower()
        if status_str == "failed":
            if not is_tile_workflow:
                # 更新工作流状态为失败
                workflow_lifecycle_manager.update_workflow_state(layer_id, WorkflowState.FAILED)
            error_detail = "; ".join(run_result.errors[:5]) if run_result.errors else "unknown failure"
            raise RuntimeError(
                f"天气工作流执行失败 (status=failed): {error_detail}"
            )

        if not is_tile_workflow:
            # 更新工作流状态为完成
            workflow_lifecycle_manager.update_workflow_state(layer_id, WorkflowState.COMPLETED)

        result_refs = self._build_result_refs(
            run_id=run_id,
            payload=payload,
            requested_at=requested_at,
            run_result=run_result,
        )
        entry_name = weather_request.get("workflow_id") or run_result.workflow_id or "weather_workflow"
        result_dto = {
            "workflow_entry_name": entry_name,
            "run_id": run_id,
            "engine_run_id": run_result.run_id,
            "job_status": self._status_str(run_result.status),
            "node_count": len(run_result.node_results),
            "outputs": run_result.outputs,
            "warnings": list(run_result.warnings),
            "errors": list(run_result.errors),
        }
        events = [
            event_factory(
                channel="log",
                message=f"天气工作流 {entry_name} 已完成执行，status={run_result.status}。",
                progress=74,
                payload={
                    "run_id": run_result.run_id,
                    "workflow_id": run_result.workflow_id,
                    "status": self._status_str(run_result.status),
                    "node_count": len(run_result.node_results),
                },
            ),
            event_factory(
                channel="data",
                message="天气结果已映射为 workflow 结果引用。",
                progress=95,
                payload={
                    "result_count": len(result_refs),
                    "entry_name": entry_name,
                },
            ),
        ]
        diagnostics = [
            "weather_bridge_service 已接入 workflow-runs 主链。",
            f"weather_workflow_enabled={settings.weather_workflow_enabled}",
            f"engine_run_id={run_result.run_id}",
            f"engine_workflow_id={run_result.workflow_id}",
            f"engine_status={run_result.status}",
            f"engine_node_count={len(run_result.node_results)}",
        ]
        if run_result.warnings:
            diagnostics.append(f"engine_warnings={len(run_result.warnings)}")
        if run_result.errors:
            diagnostics.append(f"engine_errors={len(run_result.errors)}")

        message = (
            f"天气工作流 {entry_name} 执行完成，"
            f"status={run_result.status}，已生成 {len(result_refs)} 个结果引用。"
        )
        if run_result.errors:
            diagnostics.extend([f"engine_error={err}" for err in run_result.errors[:5]])

        return WorkflowExecutionResult(
            message=message,
            result_refs=result_refs,
            result_dto=result_dto,
            diagnostics=diagnostics,
            events=events,
        )

    # ------------------------------------------------------------------ 元数据接口

    def list_workflows_response(self):
        service = self._get_service()
        report = service.diagnose()
        node_registry = report.get("node_registry", {})
        supported_types = []
        if isinstance(node_registry, dict):
            supported_types = node_registry.get("supported_node_types", []) or []
        workflows = [
            {
                "name": node_type,
                "node_type": node_type,
                "category": "weather" if node_type.startswith("weather_") else "sample",
            }
            for node_type in supported_types
        ]
        return {
            "status_code": 200,
            "body": {
                "workflows": workflows,
                "workflow_count": len(workflows),
                "source": "weatherengine",
            },
        }

    def describe_workflow_response(self, workflow_name: str):
        service = self._get_service()
        report = service.diagnose()
        node_registry = report.get("node_registry", {})
        supported_types = []
        if isinstance(node_registry, dict):
            supported_types = node_registry.get("supported_node_types", []) or []
        if workflow_name not in supported_types:
            return {
                "status_code": 404,
                "body": {
                    "error_type": "not_found",
                    "error_code": "weather_workflow_not_found",
                    "user_message": f"天气节点类型不存在: {workflow_name}",
                    "developer_message": f"workflow_name not in supported_node_types: {workflow_name}",
                },
            }
        return {
            "status_code": 200,
            "body": {
                "name": workflow_name,
                "node_type": workflow_name,
                "category": "weather" if workflow_name.startswith("weather_") else "sample",
                "source": "weatherengine",
            },
        }

    def get_diagnostics_response(self):
        service = self._get_service()
        report = service.diagnose()
        return {
            "status_code": 200,
            "body": report,
        }

    def get_workflow_panel_schema_response(self, workflow_name: str):
        """返回天气工作流的 panel schema（与 ComfyUI 风格编辑器兼容）。"""
        service = self._get_service()
        spec = service.registry.get_node_spec(workflow_name)
        if spec is None:
            return {
                "status_code": 404,
                "body": {
                    "error_type": "not_found",
                    "error_code": "weather_node_spec_not_found",
                    "user_message": f"天气节点类型不存在: {workflow_name}",
                },
            }
        return {
            "status_code": 200,
            "body": {
                "name": workflow_name,
                "node_type": workflow_name,
                "source": "weatherengine",
                "input_ports": [{"name": p.name, "required": p.required} for p in spec.input_ports],
                "output_ports": [{"name": p.name} for p in spec.output_ports],
                "params": spec.params,
            },
        }

    def get_workflow_ui_schema_response(self, workflow_name: str):
        """返回天气工作流的 UI schema（供前端编辑器使用）。"""
        return {
            "status_code": 200,
            "body": {
                "name": workflow_name,
                "node_type": workflow_name,
                "source": "weatherengine",
                "ui_schema": {"category": "weather"},
            },
        }

    # ------------------------------------------------------------------ 内部工具

    def _get_service(self):
        if not settings.weather_workflow_enabled:
            raise RuntimeError("Weather workflow bridge is disabled by BACKEND_WEATHER_WORKFLOW_ENABLED=false.")
        try:
            return _get_weather_workflow_service()
        except Exception as exc:
            logger.exception("Failed to initialize WeatherWorkflowService")
            raise RuntimeError(f"Failed to initialize WeatherWorkflowService: {exc}") from exc

    def _build_default_context(self, payload: WorkflowSubmitRequest, run_id: str) -> dict[str, Any]:
        weather_request = self._normalize_weather_request(payload.weather_request)
        # 优先取 weather_request.workflow_id；瓦片 workflow 还会把 id 放在 workflow.workflow_id
        workflow_id = (
            weather_request.get("workflow_id")
            or (weather_request.get("workflow") or {}).get("workflow_id")
            or payload.layer_id
            or run_id
        )
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
            "workflow_id": workflow_id,
            "metadata": metadata,
        }
        return context

    def _build_result_refs(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        run_result,
    ) -> list[WorkflowResultReference]:
        result_refs: list[WorkflowResultReference] = [
            WorkflowResultReference(
                result_id=f"weather-result-{run_id[-8:]}",
                result_kind=ResultKind.json,
                title="天气工作流结果",
                mime_type="application/json",
                inline_data={
                    "workflow": {
                        "run_id": run_id,
                        "engine_run_id": run_result.run_id,
                        "workflow_id": run_result.workflow_id,
                        "command_type": payload.command_type.value,
                        "layer_id": payload.layer_id,
                    },
                    "status": self._status_str(run_result.status),
                    "node_results": [
                        {
                            "node_id": nr.node_id,
                            "status": self._status_str(nr.status),
                            "outputs": nr.outputs,
                            "warnings": list(nr.warnings),
                        }
                        for nr in run_result.node_results
                    ],
                    "outputs": run_result.outputs,
                    "warnings": list(run_result.warnings),
                    "errors": list(run_result.errors),
                },
                updated_at=requested_at,
            )
        ]

        # Tile workflow 支持：若节点输出包含 GeoJSON FeatureCollection，追加一个可直接使用的 json result_ref
        tile_geojson, tile_meta = self._extract_tile_geojson(run_result)
        if tile_geojson is not None:
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"weather-tile-geojson-{run_id[-8:]}",
                    result_kind=ResultKind.json,
                    title="天气瓦片 GeoJSON",
                    mime_type="application/geo+json",
                    inline_data={
                        "geojson": tile_geojson,
                        "tile_meta": tile_meta,
                    },
                    updated_at=requested_at,
                )
            )

        # M15 修复：将 RunResult.artifacts 映射为 file 类型的 WorkflowResultReference
        # 与 gee_bridge_service._build_result_refs 的 artifact 映射逻辑对齐
        for index, artifact in enumerate(run_result.artifacts or []):
            artifact_dict = artifact if isinstance(artifact, dict) else artifact.model_dump(mode="python")
            storage_uri = str(artifact_dict.get("storage_uri") or artifact_dict.get("uri") or "")
            if not storage_uri:
                continue
            result_refs.append(
                WorkflowResultReference(
                    result_id=f"weather-artifact-{run_id[-8:]}-{index}",
                    result_kind=ResultKind.file,
                    title=f"天气产物 {artifact_dict.get('artifact_type', index)}",
                    mime_type=str(artifact_dict.get("content_type") or "application/octet-stream"),
                    resource_url=storage_uri,
                    resource_key=str(artifact_dict.get("artifact_id") or storage_uri),
                    resource_size_bytes=artifact_dict.get("size"),
                    updated_at=requested_at,
                )
            )
        return result_refs

    def _extract_tile_geojson(self, run_result) -> tuple[Any, Any]:
        """从 workflow 输出中提取 tile GeoJSON 及其元数据（供前端 tile manager 使用）。"""
        for key, value in (run_result.outputs or {}).items():
            if not isinstance(value, dict):
                continue
            if value.get("type") == "FeatureCollection" and isinstance(value.get("features"), list):
                tile_meta = value.get("_tile_meta")
                if tile_meta is not None and isinstance(tile_meta, dict):
                    logger.info(
                        "[WeatherBridgeService] extracted tile geojson from outputs key=%s "
                        "layer=%s z=%s x=%s y=%s hour=%s resolution=%s features=%s",
                        key,
                        tile_meta.get("layer_id"),
                        tile_meta.get("z"),
                        tile_meta.get("x"),
                        tile_meta.get("y"),
                        tile_meta.get("hour"),
                        tile_meta.get("resolution"),
                        len(value.get("features", [])),
                    )
                    return value, tile_meta
        return None, None

    @staticmethod
    def _is_tile_workflow(weather_request: dict[str, Any]) -> bool:
        """判断是否为瓦片 workflow：包含 weather_tile_render 节点。"""
        workflow = weather_request.get("workflow") or {}
        nodes = workflow.get("nodes") or []
        return any(
            (node.get("node_type") if isinstance(node, dict) else getattr(node, "node_type", None))
            == "weather_tile_render"
            for node in nodes
        )

    def _normalize_weather_request(self, value: WeatherWorkflowRequest | dict[str, Any] | Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, WeatherWorkflowRequest):
            return value.model_dump(mode="json", exclude_none=True)
        if isinstance(value, dict):
            return dict(value)
        return {}


weather_bridge_service = WeatherBridgeService()
