"""Workflow graph, execution engine, presets, and HTTP/JSON adapters.

WebGIS 平台接入方可通过 coerce_workflow_definition() 将平台侧 JSON 工作流定义
反序列化为 WorkflowDefinition，再交给 run_job(workflow_definition=...) 执行。
"""

from workflow.schemas import ArtifactRef
from workflow.executor import WorkflowResult, WorkflowRunner
from workflow.graph import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNodeSpec,
    WorkflowOutputSpec,
)
from workflow.presets import (
    build_named_workflow,
    has_named_workflow,
    list_named_workflows,
)
from workflow.serialization import (
    coerce_workflow_definition,
    get_workflow_definition_json_schema,
    workflow_definition_from_mapping,
)
from workflow.validation import (
    validate_workflow_definition,
)

__all__ = [
    "ArtifactRef",
    "build_named_workflow",
    "coerce_workflow_definition",
    "get_workflow_definition_json_schema",
    "has_named_workflow",
    "list_named_workflows",
    "validate_workflow_definition",
    "workflow_definition_from_mapping",
    "WorkflowDefinition",
    "WorkflowEdge",
    "WorkflowNodeSpec",
    "WorkflowOutputSpec",
    "WorkflowResult",
    "WorkflowRunner",
]
