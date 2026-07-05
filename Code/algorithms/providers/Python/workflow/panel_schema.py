from __future__ import annotations

from dataclasses import dataclass, field

from contracts.request_templates import get_module_request_template
from modules.registry import get_module
from workflow.serialization import coerce_workflow_definition
from workflow.template_inference import _infer_workflow_request_template
from workflow.validation import validate_workflow_definition


@dataclass(frozen=True, slots=True)
class WorkflowPanelField:
    key: str
    section: str
    required: bool
    value_kind: str
    description: str | None = None
    consumers: tuple[str, ...] = ()
    entry_names: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    format_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowInputPanelSchema:
    workflow_id: str
    workflow_name: str | None
    datasource_fields: tuple[WorkflowPanelField, ...] = ()
    algorithm_param_fields: tuple[WorkflowPanelField, ...] = ()
    request_fields: tuple[WorkflowPanelField, ...] = ()
    notes: tuple[str, ...] = ()


def build_workflow_input_panel_schema(value: object) -> WorkflowInputPanelSchema:
    definition = coerce_workflow_definition(value)
    validate_workflow_definition(definition)
    template = _infer_workflow_request_template(definition)

    datasource_fields: dict[str, _MutableField] = {}
    algorithm_fields: dict[str, _MutableField] = {}
    request_fields: dict[str, _MutableField] = {}

    node_map = {node.node_id: node for node in definition.nodes if node.enabled}
    edge_targets: dict[str, set[str]] = {}
    for edge in definition.edges:
        edge_targets.setdefault(edge.to_node, set()).add(edge.to_port)

    for key in template.required_datasource_keys:
        field = datasource_fields.setdefault(key, _MutableField(key=key, section="datasource_selection"))
        field.required = True
        field.value_kind = "external_input"
        field.description = field.description or "Required by input:* binding in workflow_definition."

    for key, input_spec in definition.inputs.items():
        field = datasource_fields.setdefault(key, _MutableField(key=key, section="datasource_selection"))
        field.value_kind = "external_input"
        field.source_types.add(input_spec.source_type)
        field.format_hints.add(input_spec.format)
        if key not in template.required_datasource_keys:
            field.description = field.description or "Declared workflow input that is not strictly required by current bindings."

    for node_requirement in template.nodes:
        node = node_map[node_requirement.node_id]
        direct_bound_ports = set(node.input_bindings) | edge_targets.get(node.node_id, set())
        entry_name = node_requirement.entry_name
        module_template = None
        module_mode_required_inputs: dict[str, tuple[str, ...]] = {}
        if node.node_type == "module" and entry_name:
            module_template = get_module_request_template(entry_name)
            module_mode_required_inputs = dict(get_module(entry_name).get_spec().mode_required_inputs)

        for input_key in node_requirement.required_input_keys:
            field = datasource_fields.setdefault(input_key, _MutableField(key=input_key, section="datasource_selection"))
            field.required = True
            field.value_kind = "external_input"
            field.consumers.add(node_requirement.node_id)
            if entry_name:
                field.entry_names.add(entry_name)

        for request_key in node_requirement.referenced_request_keys:
            field = request_fields.setdefault(request_key, _MutableField(key=request_key, section="request"))
            field.required = True
            field.value_kind = _request_value_kind(request_key)
            field.consumers.add(node_requirement.node_id)
            if entry_name:
                field.entry_names.add(entry_name)
            field.description = field.description or _request_description(request_key)

        if module_template is None:
            continue

        if "request:datasource_selection" in node.input_bindings.values():
            for key in module_template.required_datasource_keys:
                if key in direct_bound_ports and key != "datasource_selection":
                    continue
                field = datasource_fields.setdefault(key, _MutableField(key=key, section="datasource_selection"))
                field.required = True
                field.value_kind = "path_or_uri"
                field.consumers.add(node_requirement.node_id)
                field.entry_names.add(module_template.entry_name)
                field.description = field.description or f"Template-derived datasource key for module '{module_template.entry_name}'."
            for key in module_template.optional_datasource_keys:
                if key in direct_bound_ports and key != "datasource_selection":
                    continue
                field = datasource_fields.setdefault(key, _MutableField(key=key, section="datasource_selection"))
                field.required = field.required or False
                field.value_kind = field.value_kind or "path_or_uri"
                field.consumers.add(node_requirement.node_id)
                field.entry_names.add(module_template.entry_name)
                field.description = field.description or f"Optional datasource key for module '{module_template.entry_name}'."

        if "request:algorithm_params" in node.input_bindings.values():
            for key in module_template.required_algorithm_keys:
                field = algorithm_fields.setdefault(key, _MutableField(key=key, section="algorithm_params"))
                field.required = True
                field.value_kind = "scalar"
                field.consumers.add(node_requirement.node_id)
                field.entry_names.add(module_template.entry_name)
                field.description = field.description or f"Required algorithm param for module '{module_template.entry_name}'."
            for key, values in module_template.allowed_algorithm_values.items():
                field = algorithm_fields.setdefault(key, _MutableField(key=key, section="algorithm_params"))
                field.value_kind = "enum"
                field.allowed_values.update(str(item) for item in values)
                field.consumers.add(node_requirement.node_id)
                field.entry_names.add(module_template.entry_name)
                field.description = field.description or f"Enum-like algorithm param for module '{module_template.entry_name}'."
            for key in module_template.optional_algorithm_keys:
                field = algorithm_fields.setdefault(key, _MutableField(key=key, section="algorithm_params"))
                field.value_kind = field.value_kind or "scalar"
                field.consumers.add(node_requirement.node_id)
                field.entry_names.add(module_template.entry_name)
                field.description = field.description or f"Optional algorithm param for module '{module_template.entry_name}'."
            for mode, required_inputs in module_mode_required_inputs.items():
                mode_field = algorithm_fields.setdefault("mode", _MutableField(key="mode", section="algorithm_params"))
                mode_field.value_kind = "enum"
                mode_field.allowed_values.add(mode)
                mode_field.consumers.add(node_requirement.node_id)
                mode_field.entry_names.add(module_template.entry_name)
                mode_field.description = mode_field.description or "Workflow mode selector that activates mode-specific input requirements."
                for required_input in required_inputs:
                    if required_input in direct_bound_ports and required_input != "algorithm_params":
                        continue
                    field = datasource_fields.setdefault(required_input, _MutableField(key=required_input, section="datasource_selection"))
                    field.required = True
                    field.value_kind = field.value_kind or "path_or_uri"
                    field.consumers.add(node_requirement.node_id)
                    field.entry_names.add(module_template.entry_name)
                    field.description = field.description or f"Mode-specific datasource key for module '{module_template.entry_name}' in mode '{mode}'."

    return WorkflowInputPanelSchema(
        workflow_id=template.workflow_id,
        workflow_name=template.workflow_name,
        datasource_fields=_freeze_fields(datasource_fields),
        algorithm_param_fields=_freeze_fields(algorithm_fields),
        request_fields=_freeze_fields(request_fields),
        notes=template.notes,
    )


@dataclass(slots=True)
class _MutableField:
    key: str
    section: str
    required: bool = False
    value_kind: str = ""
    description: str | None = None
    consumers: set[str] = field(default_factory=set)
    entry_names: set[str] = field(default_factory=set)
    allowed_values: set[str] = field(default_factory=set)
    source_types: set[str] = field(default_factory=set)
    format_hints: set[str] = field(default_factory=set)


def _freeze_fields(fields: dict[str, _MutableField]) -> tuple[WorkflowPanelField, ...]:
    return tuple(
        WorkflowPanelField(
            key=item.key,
            section=item.section,
            required=item.required,
            value_kind=item.value_kind or "scalar",
            description=item.description,
            consumers=tuple(sorted(item.consumers)),
            entry_names=tuple(sorted(item.entry_names)),
            allowed_values=tuple(sorted(item.allowed_values)),
            source_types=tuple(sorted(item.source_types)),
            format_hints=tuple(sorted(item.format_hints)),
        )
        for item in sorted(fields.values(), key=lambda field: (field.section, field.key))
    )


def _request_value_kind(request_key: str) -> str:
    if request_key in {"algorithm_params", "datasource_selection", "output_spec_extra", "tags"}:
        return "object"
    if request_key in {"time_range", "region"}:
        return "structured_object"
    return "object"


def _request_description(request_key: str) -> str:
    descriptions = {
        "algorithm_params": "Whole algorithm_params object is consumed by one or more nodes.",
        "datasource_selection": "Whole datasource_selection object is consumed by one or more nodes.",
        "output_spec_extra": "Whole output_spec.extra object is consumed by one or more nodes.",
        "time_range": "Workflow reads request.time_range directly.",
        "region": "Workflow reads request.region directly.",
        "tags": "Workflow reads request.tags directly.",
    }
    return descriptions.get(request_key, "Workflow reads this request field directly.")
