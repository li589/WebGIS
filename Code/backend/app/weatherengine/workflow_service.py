from __future__ import annotations

import logging
from typing import Any

from app.workflow_engine.executor import WorkflowExecutor
from app.workflow_engine.models import ExecutionContext, RunResult, WorkflowDefinition
from app.workflow_engine.registry import NodeRegistry
from app.weatherengine.nodes import (
    ForecastFetchNode,
    PointParseNode,
    WindFieldRenderNode,
    TemperatureGridRenderNode,
    PrecipitationGridRenderNode,
    HumidityGridRenderNode,
    PressureGridRenderNode,
    VisibilityGridRenderNode,
    SummaryGenerateNode,
)

logger = logging.getLogger(__name__)


class WeatherWorkflowService:
    """天气工作流应用服务 — 管理节点注册表与工作流执行编排。

    M12 修复：明确与 WeatherEngineService 的职责边界。
    - 本类负责：节点注册、workflow 编排（DAG 拓扑执行）、结果汇总。
    - 不负责：API 调用、forecast 解析、GeoJSON/COG 渲染原语（这些由 WeatherEngineService 提供）。
    - 节点通过 ExecutionContext 获取上游数据，调用 WeatherEngineService 的公开方法完成渲染。
    - 对外由 WeatherBridgeService 桥接到 workflow-runs 主链。
    """

    def __init__(self) -> None:
        self._registry = NodeRegistry()
        self._executor = WorkflowExecutor(self._registry)
        self._register_default_nodes()

    def _register_default_nodes(self) -> None:
        default_nodes = (
            ForecastFetchNode,
            PointParseNode,
            WindFieldRenderNode,
            TemperatureGridRenderNode,
            PrecipitationGridRenderNode,
            HumidityGridRenderNode,
            PressureGridRenderNode,
            VisibilityGridRenderNode,
            SummaryGenerateNode,
        )
        for node_cls in default_nodes:
            if not self._registry.has(node_cls.node_type):
                self._registry.register(node_cls)

    @property
    def registry(self) -> NodeRegistry:
        return self._registry

    def normalize_workflow_definition(self, workflow) -> WorkflowDefinition:
        if isinstance(workflow, WorkflowDefinition):
            return workflow
        if isinstance(workflow, dict):
            return WorkflowDefinition.model_validate(workflow)
        raise TypeError(f"Unsupported workflow type: {type(workflow)}")

    def validate_workflow(self, workflow) -> WorkflowDefinition:
        workflow = self.normalize_workflow_definition(workflow)
        self._executor.topological_sort(workflow.nodes, workflow.edges)
        return workflow

    def execute_workflow(self, workflow, context=None) -> RunResult:
        workflow = self.normalize_workflow_definition(workflow)
        if context is None:
            context = ExecutionContext(workflow_id=workflow.workflow_id)
        elif isinstance(context, dict):
            context = ExecutionContext.model_validate(context)
        return self._executor.execute(workflow, context)

    def diagnose(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "node_registry": {
                "status": "ok",
                "supported_node_types": self._registry.supported_node_types(),
            },
        }
