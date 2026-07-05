from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.services.workflow_execution import WorkflowExecutionResult
from shared.contracts.api_contracts import WorkflowSubmitRequest


@runtime_checkable
class BridgeProtocol(Protocol):
    """Bridge Service 统一协议。

    M6 修复：4 个 bridge（gee / weather / python_provider / provider_workflow）
    共享此 Protocol，避免"口头约定"造成的不一致。

    实现要求：
    - supports() 必须先检查 enabled flag，禁用时返回 False
    - execute() 必须自己处理异常，不应向上抛出（避免拖垮主链）
    - 元数据接口（list/describe/diagnostics）必须返回 dict[str, Any]
      包含 status_code 与 body 两个键
    """

    def supports(self, payload: WorkflowSubmitRequest) -> bool:
        """判断是否接管该 payload。禁用或字段缺失时返回 False。"""
        ...

    def execute(
        self,
        *,
        run_id: str,
        payload: WorkflowSubmitRequest,
        requested_at: datetime,
        event_factory: Any,
    ) -> WorkflowExecutionResult:
        """执行工作流，返回 WorkflowExecutionResult。异常应被捕获并写入 result_dto。"""
        ...

    def list_workflows_response(self) -> dict[str, Any]:
        """返回支持的 workflow 列表。结构: {"status_code": int, "body": {...}}"""
        ...

    def describe_workflow_response(self, workflow_name: str) -> dict[str, Any]:
        """返回单个 workflow 详情。结构: {"status_code": int, "body": {...}}"""
        ...

    def get_diagnostics_response(self) -> dict[str, Any]:
        """返回诊断信息。结构: {"status_code": int, "body": {...}}"""
        ...
