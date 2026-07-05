from __future__ import annotations

from dataclasses import dataclass, field

from workflow.graph import WorkflowDefinition
from workflow.serialization import coerce_workflow_definition
from workflow.validation import validate_workflow_definition


@dataclass(frozen=True, slots=True)
class WorkflowNodeRequirement:
    node_id: str
    node_type: str
    entry_name: str | None = None
    required_input_keys: tuple[str, ...] = ()
    referenced_request_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowRequestTemplate:
    workflow_id: str
    workflow_name: str | None
    required_datasource_keys: tuple[str, ...] = ()
    optional_declared_inputs: tuple[str, ...] = ()
    referenced_request_keys: tuple[str, ...] = ()
    nodes: tuple[WorkflowNodeRequirement, ...] = ()
    notes: tuple[str, ...] = ()


def infer_workflow_request_template(value: object) -> WorkflowRequestTemplate:
    definition = coerce_workflow_definition(value)
    validate_workflow_definition(definition)
    return _infer_workflow_request_template(definition)


def _infer_workflow_request_template(definition: WorkflowDefinition) -> WorkflowRequestTemplate:
    from modules.registry import get_module

    required_inputs: set[str] = set()
    referenced_request_keys: set[str] = set()
    node_requirements: list[WorkflowNodeRequirement] = []

    for node in definition.nodes:
        if not node.enabled:
            continue
        node_input_keys: set[str] = set()
        node_request_keys: set[str] = set()
        for binding in node.input_bindings.values():
            _collect_binding_requirements(
                binding,
                required_inputs=required_inputs,
                referenced_request_keys=referenced_request_keys,
                node_input_keys=node_input_keys,
                node_request_keys=node_request_keys,
            )
        entry_name = _resolve_entry_name(node)
        if node.node_type == "module" and entry_name:
            module_mode_required_inputs = dict(get_module(entry_name).get_spec().mode_required_inputs)
            mode = str(node.params.get("mode", "")).lower()
            for required_input in module_mode_required_inputs.get(mode, ()):
                required_inputs.add(required_input)
                node_input_keys.add(required_input)
        node_requirements.append(
            WorkflowNodeRequirement(
                node_id=node.node_id,
                node_type=node.node_type,
                entry_name=entry_name,
                required_input_keys=tuple(sorted(node_input_keys)),
                referenced_request_keys=tuple(sorted(node_request_keys)),
            )
        )

    declared_inputs = set(definition.inputs)
    optional_declared_inputs = tuple(sorted(declared_inputs - required_inputs))
    notes = []
    if declared_inputs:
        notes.append("Declared workflow.inputs are informational unless referenced by input:* bindings.")
    if not required_inputs:
        notes.append("Workflow does not require any datasource_selection input:* bindings.")

    return WorkflowRequestTemplate(
        workflow_id=definition.workflow_id,
        workflow_name=definition.name,
        required_datasource_keys=tuple(sorted(required_inputs)),
        optional_declared_inputs=optional_declared_inputs,
        referenced_request_keys=tuple(sorted(referenced_request_keys)),
        nodes=tuple(node_requirements),
        notes=tuple(notes),
    )


def _collect_binding_requirements(
    binding: str,
    *,
    required_inputs: set[str],
    referenced_request_keys: set[str],
    node_input_keys: set[str],
    node_request_keys: set[str],
) -> None:
    if binding.startswith("input:"):
        input_name = binding.split(":", 1)[1]
        required_inputs.add(input_name)
        node_input_keys.add(input_name)
        return
    if binding.startswith("request:"):
        request_key = binding.split(":", 1)[1]
        referenced_request_keys.add(request_key)
        node_request_keys.add(request_key)


def _resolve_entry_name(node) -> str | None:
    if node.node_type == "module":
        return str(node.params.get("module_name", "")).strip() or None
    if node.node_type == "bridge.pipeline":
        return str(node.params.get("pipeline_name", "")).strip() or None
    return None
