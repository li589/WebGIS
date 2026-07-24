from __future__ import annotations

from contracts.job import JobRequest
from contracts.request_templates import (
    build_workflow_request_template,
    get_module_request_template,
)
from workflow.template_inference import infer_workflow_request_template


class JobRequestValidationError(ValueError):
    """Raised when a JobRequest is structurally decoded but semantically invalid."""


def validate_job_request(request: JobRequest) -> JobRequest:
    if request.workflow_definition is not None and request.module_name is not None:
        raise JobRequestValidationError(
            "module_name cannot be combined with workflow_definition; explicit workflows must define their own nodes"
        )

    uses_workflow_entry = (
        request.workflow_definition is not None
        or request.workflow_name is not None
        or request.module_name is not None
    )

    if uses_workflow_entry:
        if request.pipeline_name != "workflow":
            raise JobRequestValidationError(
                "pipeline_name must be 'workflow' when workflow_definition, workflow_name, or module_name is used"
            )
        if request.workflow_definition is not None:
            _validate_explicit_workflow_template(request)
        if request.module_name is not None:
            _validate_module_name(request.module_name)
            _validate_module_request_template(request)
        elif request.workflow_definition is None and request.workflow_name is not None:
            _validate_workflow_name(request.workflow_name)
            _validate_workflow_request_template(request)
        return request

    if request.pipeline_name == "workflow":
        raise JobRequestValidationError(
            "pipeline_name='workflow' is only a placeholder and requires workflow_definition, workflow_name, or module_name"
        )

    _validate_pipeline_name(request.pipeline_name)
    return request


def _validate_module_name(name: str) -> None:
    from modules.registry import get_module

    try:
        get_module(name)
    except KeyError as exc:
        raise JobRequestValidationError(f"Unknown module_name: {name}") from exc


def _validate_workflow_name(name: str) -> None:
    from workflow.presets import has_named_workflow

    if not has_named_workflow(name):
        raise JobRequestValidationError(f"Unknown workflow_name: {name}")


def _validate_pipeline_name(name: str) -> None:
    from runner.registry import get_pipeline

    try:
        get_pipeline(name)
    except KeyError as exc:
        raise JobRequestValidationError(f"Unknown pipeline_name: {name}") from exc


def _validate_module_request_template(request: JobRequest) -> None:
    if request.module_name is None:
        return
    template = get_module_request_template(request.module_name)
    if template is None:
        return
    _validate_template(template, request)


def _validate_workflow_request_template(request: JobRequest) -> None:
    if request.workflow_name is None:
        return
    template = build_workflow_request_template(request.workflow_name, request)
    if template is None:
        return
    _validate_template(template, request)


def _validate_template(template, request: JobRequest) -> None:
    missing_datasource_keys = [
        key
        for key in template.required_datasource_keys
        if key not in request.datasource_selection
    ]
    if missing_datasource_keys:
        missing_datasource_keys = [
            key
            for key in missing_datasource_keys
            if not _has_satisfying_data_access_request(template, request, key)
        ]
    if missing_datasource_keys:
        raise JobRequestValidationError(
            f"{template.entry_kind} '{template.entry_name}' requires datasource_selection keys: "
            + ", ".join(missing_datasource_keys)
        )

    missing_algorithm_keys = [
        key
        for key in template.required_algorithm_keys
        if key not in request.algorithm_params
    ]
    if missing_algorithm_keys:
        raise JobRequestValidationError(
            f"{template.entry_kind} '{template.entry_name}' requires algorithm_params keys: "
            + ", ".join(missing_algorithm_keys)
        )

    for key, allowed_values in template.allowed_algorithm_values.items():
        if key not in request.algorithm_params:
            continue
        value = request.algorithm_params[key]
        if _matches_allowed_value(value, allowed_values):
            continue
        allowed_text = ", ".join(str(item) for item in allowed_values)
        raise JobRequestValidationError(
            f"{template.entry_kind} '{template.entry_name}' rejects algorithm_params.{key}={value!r}; "
            f"allowed values: {allowed_text}"
        )

    if (
        template.allowed_task_types
        and request.task_type not in template.allowed_task_types
    ):
        allowed_text = ", ".join(template.allowed_task_types)
        raise JobRequestValidationError(
            f"{template.entry_kind} '{template.entry_name}' rejects task_type={request.task_type!r}; "
            f"allowed values: {allowed_text}"
        )


def _matches_allowed_value(value: object, allowed_values: tuple[object, ...]) -> bool:
    if value in allowed_values:
        return True
    if isinstance(value, str) and all(isinstance(item, str) for item in allowed_values):
        return value.lower() in {str(item).lower() for item in allowed_values}
    return False


def _has_satisfying_data_access_request(
    template, request: JobRequest, required_key: str
) -> bool:
    raw_requests = request.datasource_selection.get("_data_access_requests")
    if not isinstance(raw_requests, dict):
        return False
    for dataset_name in _get_accepted_dataset_names(template, required_key):
        dataset_request = raw_requests.get(dataset_name)
        if not isinstance(dataset_request, dict):
            continue
        selector = dataset_request.get("selector", {})
        if isinstance(selector, dict) and selector.get("uris"):
            return True
        if dataset_request.get("uris") or dataset_request.get("uri"):
            return True
    return False


def _get_accepted_dataset_names(template, required_key: str) -> tuple[str, ...]:
    accepted_by_required_key = getattr(
        template, "accepted_data_access_by_required_key", {}
    )
    if isinstance(accepted_by_required_key, dict):
        dataset_names = accepted_by_required_key.get(required_key)
        if isinstance(dataset_names, tuple):
            return dataset_names
    accepted_datasets = tuple(getattr(template, "accepted_data_access_datasets", ()))
    if (
        len(getattr(template, "required_datasource_keys", ())) == 1
        and accepted_datasets
    ):
        return accepted_datasets
    return (required_key,)


def _validate_explicit_workflow_template(request: JobRequest) -> None:
    template = infer_workflow_request_template(request.workflow_definition)
    missing_datasource_keys = [
        key
        for key in template.required_datasource_keys
        if key not in request.datasource_selection
    ]
    if missing_datasource_keys:
        missing_datasource_keys = [
            key
            for key in missing_datasource_keys
            if not _has_satisfying_data_access_request(template, request, key)
        ]
    if missing_datasource_keys:
        raise JobRequestValidationError(
            f"workflow_definition '{template.workflow_id}' requires datasource_selection keys: "
            + ", ".join(missing_datasource_keys)
        )
