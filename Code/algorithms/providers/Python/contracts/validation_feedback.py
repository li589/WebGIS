from __future__ import annotations

import re
from dataclasses import dataclass, field

from contracts.job import JobRequest
from contracts.serialization import JobRequestDecodeError
from contracts.validation import JobRequestValidationError
from workflow.serialization import WorkflowDefinitionDecodeError
from workflow.ui_metadata import build_workflow_input_panel_ui_schema
from workflow.validation import WorkflowDefinitionValidationError


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    field_path: str | None = None
    field_key: str | None = None
    section: str | None = None
    label: str | None = None
    control_type: str | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationFeedback:
    error_type: str
    summary: str
    issues: tuple[ValidationIssue, ...]


def build_validation_feedback(
    error: Exception,
    *,
    request: JobRequest | None = None,
    workflow_definition: object | None = None,
) -> ValidationFeedback:
    panel_catalog = _build_panel_catalog(
        workflow_definition=workflow_definition or (request.workflow_definition if request is not None else None)
    )

    if isinstance(error, JobRequestDecodeError):
        issues = _build_decode_issues(error, default_section="request", panel_catalog=panel_catalog)
        return ValidationFeedback("job_request_decode", str(error), issues)
    if isinstance(error, WorkflowDefinitionDecodeError):
        issues = _build_decode_issues(error, default_section="workflow_definition", panel_catalog=panel_catalog)
        return ValidationFeedback("workflow_definition_decode", str(error), issues)
    if isinstance(error, JobRequestValidationError):
        issues = _build_job_request_validation_issues(error, panel_catalog=panel_catalog)
        return ValidationFeedback("job_request_validation", str(error), issues)
    if isinstance(error, WorkflowDefinitionValidationError):
        issues = _build_workflow_validation_issues(error, panel_catalog=panel_catalog)
        return ValidationFeedback("workflow_definition_validation", str(error), issues)
    return ValidationFeedback(
        "unknown_validation_error",
        str(error),
        (ValidationIssue(code="unknown_validation_error", message=str(error)),),
    )


def _build_decode_issues(
    error: Exception,
    *,
    default_section: str,
    panel_catalog: dict[str, dict[str, str]],
) -> tuple[ValidationIssue, ...]:
    message = str(error)
    code = "decode_error"
    field_path = None
    if message.startswith("Missing required field: "):
        code = "missing_required_field"
        field_path = message.split(": ", 1)[1]
    elif message.startswith("Unknown field(s) not allowed: "):
        location_text = message.split(": ", 1)[1]
        if " -> " in location_text:
            base_path, keys_text = location_text.split(" -> ", 1)
            issues = []
            for key in _split_csv(keys_text):
                issues.append(
                    _make_issue(
                        "unknown_field",
                        message,
                        field_path=f"{base_path}.{key}",
                        default_section=default_section,
                        panel_catalog=panel_catalog,
                    )
                )
            return tuple(issues)
    elif message.startswith("Field must be an ISO datetime string: "):
        code = "invalid_iso_datetime"
        field_path = message.split(": ", 1)[1]
    elif message.startswith("Fields must both include timezone info or both omit it: "):
        paths_text = message.split(": ", 1)[1]
        return tuple(
            _make_issue(
                "inconsistent_timezone",
                message,
                field_path=path,
                default_section=default_section,
                panel_catalog=panel_catalog,
            )
            for path in _split_csv(paths_text)
        )
    elif message.startswith("Field must satisfy start <= end: "):
        code = "invalid_range"
        field_path = message.split(": ", 1)[1]
    elif ": " in message and ("job_request." in message or "workflow_definition." in message):
        field_path = message.rsplit(": ", 1)[1]
        code = _decode_error_code_from_message(message)

    return (_make_issue(code, message, field_path=field_path, default_section=default_section, panel_catalog=panel_catalog),)


def _build_job_request_validation_issues(
    error: JobRequestValidationError,
    *,
    panel_catalog: dict[str, dict[str, str]],
) -> tuple[ValidationIssue, ...]:
    message = str(error)

    if message.startswith("module_name cannot be combined with workflow_definition"):
        return (
            _make_issue(
                "selector_conflict",
                message,
                field_path="job_request.module_name",
                default_section="request",
                panel_catalog=panel_catalog,
            ),
            _make_issue(
                "selector_conflict",
                message,
                field_path="job_request.workflow_definition",
                default_section="request",
                panel_catalog=panel_catalog,
            ),
        )

    if message.startswith("pipeline_name must be 'workflow'"):
        return (
            _make_issue(
                "invalid_pipeline_placeholder",
                message,
                field_path="job_request.pipeline_name",
                default_section="request",
                panel_catalog=panel_catalog,
            ),
        )

    if message.startswith("pipeline_name='workflow' is only a placeholder"):
        return (
            _make_issue(
                "missing_workflow_selector",
                message,
                field_path="job_request.pipeline_name",
                default_section="request",
                panel_catalog=panel_catalog,
            ),
        )

    for prefix, field_path in (
        ("Unknown module_name: ", "job_request.module_name"),
        ("Unknown workflow_name: ", "job_request.workflow_name"),
        ("Unknown pipeline_name: ", "job_request.pipeline_name"),
    ):
        if message.startswith(prefix):
            return (
                _make_issue(
                    "unknown_selector",
                    message,
                    field_path=field_path,
                    default_section="request",
                    panel_catalog=panel_catalog,
                ),
            )

    match = re.match(r"^(module|workflow|workflow_definition) '([^']+)' requires datasource_selection keys: (.+)$", message)
    if match:
        entry_kind, entry_name, keys_text = match.groups()
        issues = []
        for key in _split_csv(keys_text):
            issues.append(
                _make_issue(
                    "missing_datasource_key",
                    message,
                    field_path=f"job_request.datasource_selection.{key}",
                    default_section="datasource_selection",
                    panel_catalog=panel_catalog,
                    details={"entry_kind": entry_kind, "entry_name": entry_name},
                )
            )
        return tuple(issues)

    match = re.match(r"^(module|workflow) '([^']+)' requires algorithm_params keys: (.+)$", message)
    if match:
        entry_kind, entry_name, keys_text = match.groups()
        issues = []
        for key in _split_csv(keys_text):
            issues.append(
                _make_issue(
                    "missing_algorithm_key",
                    message,
                    field_path=f"job_request.algorithm_params.{key}",
                    default_section="algorithm_params",
                    panel_catalog=panel_catalog,
                    details={"entry_kind": entry_kind, "entry_name": entry_name},
                )
            )
        return tuple(issues)

    match = re.match(
        r"^(module|workflow) '([^']+)' rejects algorithm_params\.([A-Za-z0-9_]+)=.+; allowed values: (.+)$",
        message,
    )
    if match:
        entry_kind, entry_name, key, allowed_values = match.groups()
        return (
            _make_issue(
                "invalid_algorithm_value",
                message,
                field_path=f"job_request.algorithm_params.{key}",
                default_section="algorithm_params",
                panel_catalog=panel_catalog,
                details={
                    "entry_kind": entry_kind,
                    "entry_name": entry_name,
                    "allowed_values": tuple(_split_csv(allowed_values)),
                },
            ),
        )

    match = re.match(r"^(module|workflow) '([^']+)' rejects task_type=.+; allowed values: (.+)$", message)
    if match:
        entry_kind, entry_name, allowed_values = match.groups()
        return (
            _make_issue(
                "invalid_task_type",
                message,
                field_path="job_request.task_type",
                default_section="request",
                panel_catalog=panel_catalog,
                details={
                    "entry_kind": entry_kind,
                    "entry_name": entry_name,
                    "allowed_values": tuple(_split_csv(allowed_values)),
                },
            ),
        )

    return (_make_issue("job_request_validation_error", message, default_section="request", panel_catalog=panel_catalog),)


def _build_workflow_validation_issues(
    error: WorkflowDefinitionValidationError,
    *,
    panel_catalog: dict[str, dict[str, str]],
) -> tuple[ValidationIssue, ...]:
    message = str(error)

    root_mappings = (
        ("workflow_definition must contain at least one enabled node", "empty_workflow", "workflow_definition.nodes"),
        ("workflow_definition.outputs must not be empty", "missing_outputs", "workflow_definition.outputs"),
        ("Workflow contains a cycle", "workflow_cycle", "workflow_definition.edges"),
    )
    for prefix, code, field_path in root_mappings:
        if message.startswith(prefix):
            return (_make_issue(code, message, field_path=field_path, default_section="workflow_definition", panel_catalog=panel_catalog),)

    match = re.match(r"^Duplicate enabled node_id detected in workflow definition: (.+)$", message)
    if match:
        return (
            _make_issue(
                "duplicate_node_id",
                message,
                field_path="workflow_definition.nodes",
                default_section="workflow_definition",
                panel_catalog=panel_catalog,
                details={"node_id": match.group(1)},
            ),
        )

    match = re.match(r"^Duplicate workflow output name detected: (workflow_definition\.outputs\[\d+\]\.name)=.+$", message)
    if match:
        return (
            _make_issue(
                "duplicate_output_name",
                message,
                field_path=match.group(1),
                default_section="workflow_definition",
                panel_catalog=panel_catalog,
            ),
        )

    match = re.match(r"^(workflow_definition\.nodes\[[^\]]+\]) module node requires params\.module_name$", message)
    if match:
        return (
            _make_issue(
                "missing_module_name",
                message,
                field_path=f"{match.group(1)}.params.module_name",
                default_section="workflow_definition",
                panel_catalog=panel_catalog,
            ),
        )

    match = re.match(r"^(workflow_definition\.nodes\[[^\]]+\]) bridge\.pipeline node requires params\.pipeline_name$", message)
    if match:
        return (
            _make_issue(
                "missing_pipeline_name",
                message,
                field_path=f"{match.group(1)}.params.pipeline_name",
                default_section="workflow_definition",
                panel_catalog=panel_catalog,
            ),
        )

    match = re.match(r"^(workflow_definition\.[^ ]+) references unsupported request binding: request:(.+)$", message)
    if match:
        return (
            _make_issue(
                "unsupported_request_binding",
                message,
                field_path=match.group(1),
                default_section="workflow_definition",
                panel_catalog=panel_catalog,
                details={"request_binding": match.group(2)},
            ),
        )

    match = re.match(r"^(workflow_definition\.[^ ]+) (?:references|uses).+$", message)
    if match:
        return (
            _make_issue(
                "invalid_workflow_reference",
                message,
                field_path=match.group(1),
                default_section="workflow_definition",
                panel_catalog=panel_catalog,
            ),
        )

    match = re.match(r"^Workflow required input port not bound: ([^.]+)\.(.+)$", message)
    if match:
        node_id, port_name = match.groups()
        return (
            _make_issue(
                "missing_node_input_binding",
                message,
                field_path=f"workflow_definition.nodes[{node_id}].input_bindings.{port_name}",
                default_section="workflow_definition",
                panel_catalog=panel_catalog,
            ),
        )

    match = re.match(r"^Workflow input port received multiple bindings: ([^.]+)\.(.+)$", message)
    if match:
        node_id, port_name = match.groups()
        return (
            _make_issue(
                "duplicate_node_input_binding",
                message,
                field_path=f"workflow_definition.nodes[{node_id}].input_bindings.{port_name}",
                default_section="workflow_definition",
                panel_catalog=panel_catalog,
            ),
        )

    return (_make_issue("workflow_validation_error", message, default_section="workflow_definition", panel_catalog=panel_catalog),)


def _make_issue(
    code: str,
    message: str,
    *,
    field_path: str | None = None,
    default_section: str,
    panel_catalog: dict[str, dict[str, str]],
    details: dict[str, object] | None = None,
) -> ValidationIssue:
    section = _infer_section(field_path, default_section=default_section)
    field_key = _infer_field_key(field_path)
    label = None
    control_type = None
    if field_key and field_key in panel_catalog:
        label = panel_catalog[field_key].get("label")
        control_type = panel_catalog[field_key].get("control_type")
        section = panel_catalog[field_key].get("section", section) or section
    return ValidationIssue(
        code=code,
        message=message,
        field_path=field_path,
        field_key=field_key,
        section=section,
        label=label,
        control_type=control_type,
        details={} if details is None else details,
    )


def _build_panel_catalog(*, workflow_definition: object | None) -> dict[str, dict[str, str]]:
    if workflow_definition is None:
        return {}
    try:
        ui_schema = build_workflow_input_panel_ui_schema(workflow_definition)
    except Exception:
        return {}
    catalog: dict[str, dict[str, str]] = {}
    for section in ui_schema.sections:
        for field in section.fields:
            catalog[field.key] = {
                "section": section.key,
                "label": field.label,
                "control_type": field.control_type,
            }
    return catalog


def _infer_section(field_path: str | None, *, default_section: str) -> str | None:
    if field_path is None:
        return default_section
    if ".datasource_selection." in field_path or field_path.startswith("workflow_definition.inputs."):
        return "datasource_selection"
    if ".algorithm_params." in field_path:
        return "algorithm_params"
    if any(token in field_path for token in (".time_range", ".region", ".tags", ".output_spec", ".task_type", ".pipeline_name", ".module_name", ".workflow_name")):
        return "request"
    return default_section


def _infer_field_key(field_path: str | None) -> str | None:
    if field_path is None:
        return None
    if field_path.endswith(".workflow_definition"):
        return "workflow_definition"
    if "." not in field_path:
        return field_path
    tail = field_path.rsplit(".", 1)[1]
    return tail if tail else None


def _decode_error_code_from_message(message: str) -> str:
    prefixes = {
        "Field must be a non-empty string": "invalid_string",
        "Field must be an object": "invalid_object",
        "Field must be an object or null": "invalid_nullable_object",
        "Field must be an integer or null": "invalid_integer",
        "Field must be a boolean": "invalid_boolean",
        "Field must be a number or null": "invalid_number",
        "Field must be a string or null": "invalid_nullable_string",
        "Field must be an array": "invalid_list",
        "Mapping value must be a string": "invalid_string_mapping",
        "Array item must be a string": "invalid_string_list",
    }
    for prefix, code in prefixes.items():
        if message.startswith(prefix):
            return code
    return "decode_error"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
