from __future__ import annotations

from dataclasses import dataclass, field

from contracts.job import JobRequest
from contracts.serialization import JobRequestDecodeError
from contracts.validation import JobRequestValidationError
from contracts.validation_feedback import ValidationIssue, build_validation_feedback
from workflow.serialization import WorkflowDefinitionDecodeError
from workflow.validation import WorkflowDefinitionValidationError


@dataclass(frozen=True, slots=True)
class ApiSuggestedFix:
    code: str
    message: str
    field_path: str | None = None


@dataclass(frozen=True, slots=True)
class ApiErrorResponse:
    error_type: str
    error_code: str
    http_status: int
    retryable: bool
    user_message: str
    developer_message: str
    issues: tuple[ValidationIssue, ...] = ()
    suggested_fixes: tuple[ApiSuggestedFix, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


def build_api_error_response(
    error: Exception,
    *,
    request: JobRequest | None = None,
    workflow_definition: object | None = None,
) -> ApiErrorResponse:
    if isinstance(
        error,
        (
            JobRequestDecodeError,
            WorkflowDefinitionDecodeError,
            JobRequestValidationError,
            WorkflowDefinitionValidationError,
        ),
    ):
        feedback = build_validation_feedback(
            error,
            request=request,
            workflow_definition=workflow_definition,
        )
        http_status, error_code, retryable, user_message = _classify_validation_feedback(feedback.error_type)
        return ApiErrorResponse(
            error_type=feedback.error_type,
            error_code=error_code,
            http_status=http_status,
            retryable=retryable,
            user_message=user_message,
            developer_message=feedback.summary,
            issues=feedback.issues,
            suggested_fixes=_build_suggested_fixes(feedback.issues),
            metadata={"issue_count": len(feedback.issues)},
        )

    return ApiErrorResponse(
        error_type="internal_server_error",
        error_code="internal_server_error",
        http_status=500,
        retryable=True,
        user_message="服务器处理请求时发生未预期错误。",
        developer_message=str(error),
        metadata={"issue_count": 0},
    )


def _classify_validation_feedback(error_type: str) -> tuple[int, str, bool, str]:
    if error_type == "job_request_decode":
        return 400, "job_request_decode_failed", False, "请求体格式不正确，无法解析为 JobRequest。"
    if error_type == "workflow_definition_decode":
        return 400, "workflow_definition_decode_failed", False, "workflow_definition 格式不正确，无法完成反序列化。"
    if error_type == "job_request_validation":
        return 422, "job_request_validation_failed", False, "请求参数未通过业务校验，请检查表单字段。"
    if error_type == "workflow_definition_validation":
        return 422, "workflow_definition_validation_failed", False, "workflow_definition 未通过静态校验，请检查节点和连线配置。"
    return 400, "validation_failed", False, "请求未通过校验。"


def _build_suggested_fixes(issues: tuple[ValidationIssue, ...]) -> tuple[ApiSuggestedFix, ...]:
    fixes: list[ApiSuggestedFix] = []
    for issue in issues:
        fix = _build_suggested_fix(issue)
        if fix is not None:
            fixes.append(fix)
    return tuple(fixes)


def _build_suggested_fix(issue: ValidationIssue) -> ApiSuggestedFix | None:
    if issue.code == "missing_required_field":
        return ApiSuggestedFix(
            code="provide_required_field",
            message=f"补充必填字段 `{issue.field_path}`。",
            field_path=issue.field_path,
        )
    if issue.code == "missing_datasource_key":
        return ApiSuggestedFix(
            code="provide_datasource_key",
            message=f"在 `datasource_selection` 中补充 `{issue.field_key}`。",
            field_path=issue.field_path,
        )
    if issue.code == "missing_algorithm_key":
        return ApiSuggestedFix(
            code="provide_algorithm_key",
            message=f"在 `algorithm_params` 中补充 `{issue.field_key}`。",
            field_path=issue.field_path,
        )
    if issue.code == "invalid_algorithm_value":
        allowed_values = issue.details.get("allowed_values")
        suffix = ""
        if isinstance(allowed_values, tuple):
            suffix = "，可选值：" + ", ".join(str(item) for item in allowed_values)
        return ApiSuggestedFix(
            code="use_allowed_algorithm_value",
            message=f"修正 `{issue.field_key}` 的取值{suffix}。",
            field_path=issue.field_path,
        )
    if issue.code == "invalid_task_type":
        allowed_values = issue.details.get("allowed_values")
        suffix = ""
        if isinstance(allowed_values, tuple):
            suffix = "，建议使用：" + ", ".join(str(item) for item in allowed_values)
        return ApiSuggestedFix(
            code="align_task_type",
            message=f"调整 `task_type` 与入口类型保持一致{suffix}。",
            field_path=issue.field_path,
        )
    if issue.code == "invalid_iso_datetime":
        return ApiSuggestedFix(
            code="use_iso_datetime",
            message=f"把 `{issue.field_path}` 改为 ISO 时间字符串，例如 `2025-01-01T00:00:00Z`。",
            field_path=issue.field_path,
        )
    if issue.code == "inconsistent_timezone":
        return ApiSuggestedFix(
            code="use_consistent_timezone",
            message=f"统一 `{issue.field_path}` 的时区口径，建议都使用 ISO UTC 时间。",
            field_path=issue.field_path,
        )
    if issue.code == "invalid_range":
        return ApiSuggestedFix(
            code="fix_time_range_order",
            message="确保 `time_range.start <= time_range.end`。",
            field_path=issue.field_path,
        )
    if issue.code == "unknown_field":
        return ApiSuggestedFix(
            code="remove_unknown_field",
            message=f"移除未注册字段 `{issue.field_path}`，或改为契约允许的字段名。",
            field_path=issue.field_path,
        )
    if issue.code == "unknown_selector":
        return ApiSuggestedFix(
            code="use_registered_selector",
            message=f"改用已注册的入口名称，检查 `{issue.field_path}`。",
            field_path=issue.field_path,
        )
    if issue.code == "selector_conflict":
        return ApiSuggestedFix(
            code="remove_conflicting_selector",
            message="移除互斥的入口选择字段，只保留一种执行入口。",
            field_path=issue.field_path,
        )
    if issue.code == "unsupported_request_binding":
        return ApiSuggestedFix(
            code="use_supported_request_binding",
            message="把 request 绑定改为受支持的键，例如 `request:algorithm_params` 或 `request:time_range`。",
            field_path=issue.field_path,
        )
    if issue.code in {"missing_node_input_binding", "duplicate_node_input_binding"}:
        return ApiSuggestedFix(
            code="fix_node_binding",
            message="检查该节点输入端口的绑定配置，确保必填端口已绑定且没有重复来源。",
            field_path=issue.field_path,
        )
    if issue.code in {"workflow_cycle", "duplicate_node_id", "duplicate_output_name"}:
        return ApiSuggestedFix(
            code="fix_workflow_topology",
            message="调整 workflow 图定义，消除环路、重复节点 ID 或重复输出名。",
            field_path=issue.field_path,
        )
    return None
