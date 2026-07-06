"""ModuleSpec → RequestTemplateSpec 自动推导器。

把 modules 的 input_ports / mode_required_inputs / default_params 自动推导为
RequestTemplateSpec，消除 contracts/request_templates.py 中 MODULE_REQUEST_TEMPLATES
的手工填写。

推导规则：
- required_datasource_keys = input_ports 中 kind=scalar 且 required=True 的 name
- optional_datasource_keys = input_ports 中 kind=scalar 且 required=False 的 name
- required_algorithm_keys = default_params 中无默认值的 key（或 mode_required_inputs 展开的 keys）
- optional_algorithm_keys = default_params 中有默认值的 key
- allowed_task_types = (module_name, "workflow")
- accepted_data_access_datasets / allowed_algorithm_values / notes 由 template_overrides 提供
"""
from __future__ import annotations

from typing import Any

from contracts.job import JobRequest
from contracts.request_templates import RequestTemplateSpec
from modules.registry import get_module, get_template_overrides, list_modules


def derive_template_from_module(module_name: str) -> RequestTemplateSpec | None:
    """从 ModuleSpec 自动推导 RequestTemplateSpec。

    Args:
        module_name: module 名称（或别名）

    Returns:
        RequestTemplateSpec，若 module 未注册返回 None
    """
    try:
        module = get_module(module_name)
    except KeyError:
        return None

    spec = module.get_spec()
    overrides = get_template_overrides(spec.name)

    # 推导 required/optional datasource keys
    required_datasource_keys: list[str] = []
    optional_datasource_keys: list[str] = []
    for port in spec.input_ports:
        if port.kind == "scalar":
            if port.required:
                required_datasource_keys.append(port.name)
            else:
                optional_datasource_keys.append(port.name)

    # 推导 required/optional algorithm keys
    # mode_required_inputs 展开后的是 required，default_params 中的是 optional
    required_algorithm_keys: set[str] = set()
    for mode_inputs in spec.mode_required_inputs.values():
        for key in mode_inputs:
            required_algorithm_keys.add(key)

    optional_algorithm_keys: list[str] = []
    for key in spec.default_params:
        if key not in required_algorithm_keys:
            optional_algorithm_keys.append(key)

    # allowed_task_types：module_name + "workflow"，可被 overrides 覆盖
    default_allowed_task_types = (spec.name, "workflow")

    return RequestTemplateSpec(
        entry_kind="module",
        entry_name=spec.name,
        required_datasource_keys=tuple(required_datasource_keys),
        accepted_data_access_datasets=tuple(overrides.get("accepted_data_access_datasets", ())),
        accepted_data_access_by_required_key=dict(overrides.get("accepted_data_access_by_required_key", {})),
        optional_datasource_keys=tuple(optional_datasource_keys),
        required_algorithm_keys=tuple(sorted(required_algorithm_keys)),
        optional_algorithm_keys=tuple(optional_algorithm_keys),
        allowed_task_types=tuple(overrides.get("allowed_task_types", default_allowed_task_types)),
        allowed_algorithm_values=dict(overrides.get("allowed_algorithm_values", {})),
        notes=overrides.get("notes"),
    )


def get_module_request_template(name: str) -> RequestTemplateSpec | None:
    """获取 module 的 RequestTemplateSpec。

    优先从 MODULE_REQUEST_TEMPLATES 手工表查找（向后兼容），
    未命中则用 derive_template_from_module 自动推导。
    """
    # 优先查手工表（保持向后兼容）
    from contracts.request_templates import MODULE_REQUEST_TEMPLATES

    manual_template = MODULE_REQUEST_TEMPLATES.get(name)
    if manual_template is not None:
        return manual_template

    # 自动推导
    return derive_template_from_module(name)


def list_module_templates() -> dict[str, RequestTemplateSpec]:
    """列出所有 module 的 RequestTemplateSpec（手工 + 自动推导）。"""
    result: dict[str, RequestTemplateSpec] = {}
    # 先加载手工表
    from contracts.request_templates import MODULE_REQUEST_TEMPLATES

    for name, template in MODULE_REQUEST_TEMPLATES.items():
        result[name] = template

    # 再补充自动推导的（跳过已存在的）
    for module_name in list_modules():
        if module_name not in result:
            derived = derive_template_from_module(module_name)
            if derived is not None:
                result[module_name] = derived

    return result


def validate_request_against_template(
    request: JobRequest,
    template: RequestTemplateSpec,
) -> tuple[bool, list[str]]:
    """基于 RequestTemplateSpec 校验 JobRequest。

    Returns:
        (is_valid, errors)
    """
    errors: list[str] = []

    # 1. 校验 allowed_task_types
    if template.allowed_task_types and request.task_type not in template.allowed_task_types:
        errors.append(
            f"task_type '{request.task_type}' not allowed for entry '{template.entry_name}'. "
            f"Allowed: {list(template.allowed_task_types)}"
        )

    # 2. 校验 required_datasource_keys
    datasource_selection = request.datasource_selection or {}
    for key in template.required_datasource_keys:
        if key not in datasource_selection and datasource_selection.get(key) is None:
            errors.append(f"Missing required datasource key: '{key}'")

    # 3. 校验 required_algorithm_keys
    algorithm_params = request.algorithm_params or {}
    for key in template.required_algorithm_keys:
        if key not in algorithm_params and algorithm_params.get(key) is None:
            # mode_required_inputs 中的 key 由 mode 控制，检查 mode 是否存在
            if key in ("input_mat", "input_dir"):
                # 这些由 datasource_selection 提供，不算 algorithm_params 缺失
                continue
            errors.append(f"Missing required algorithm param: '{key}'")

    # 4. 校验 allowed_algorithm_values
    for key, allowed_values in template.allowed_algorithm_values.items():
        if key in algorithm_params:
            value = algorithm_params[key]
            if value not in allowed_values:
                errors.append(
                    f"algorithm param '{key}' value '{value}' not allowed. "
                    f"Allowed: {list(allowed_values)}"
                )

    # 5. 校验 accepted_data_access_datasets
    if template.accepted_data_access_datasets:
        data_access_requests = request.datasource_selection.get("_data_access_requests", {})
        if isinstance(data_access_requests, dict):
            for dataset_name in data_access_requests:
                if dataset_name not in template.accepted_data_access_datasets:
                    errors.append(
                        f"dataset '{dataset_name}' not in accepted_data_access_datasets. "
                        f"Accepted: {list(template.accepted_data_access_datasets)}"
                    )

    return (len(errors) == 0, errors)
