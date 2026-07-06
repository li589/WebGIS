from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.services.workflow_execution import WorkflowExecutionResult
from shared.contracts.api_contracts import FailureCategory, WorkflowSubmitRequest


class BridgeExecutionError(Exception):
    """Bridge 执行失败统一异常。

    携带失败分类（FailureCategory）+ 原始 cause，供 hub 层判断是否重试。
    bridge 层只做分类，不做循环重试（避免阻塞 worker）。
    """

    def __init__(
        self,
        *,
        category: FailureCategory,
        message: str,
        cause: Exception | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.cause = cause
        self.details = details or {}
        self.retryable = category.retryable

    def __str__(self) -> str:
        cause_repr = f" (cause: {self.cause!r})" if self.cause else ""
        return f"[{self.category.value}] {super().__str__()}{cause_repr}"


@runtime_checkable
class BridgeProtocol(Protocol):
    """Bridge Service 统一协议。

    M6 修复：4 个 bridge（gee / weather / python_provider / provider_workflow）
    共享此 Protocol，避免"口头约定"造成的不一致。

    实现要求：
    - supports() 必须先检查 enabled flag，禁用时返回 False
    - execute() 必须自己处理异常，不应向上抛出（避免拖垮主链）
      瞬态失败应抛 BridgeExecutionError(category=transient_*)，hub 会自动重试
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
        """执行工作流，返回 WorkflowExecutionResult。

        异常处理约定：
        - 瞬态失败（网络/上游 5xx/超时/限流）：抛 BridgeExecutionError(category=transient_*)
        - 终态失败（参数错误/协议错误/业务逻辑错误）：抛 BridgeExecutionError(category=terminal_*)
        - 内部可恢复的降级：写入 diagnostics，不抛异常
        """
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
