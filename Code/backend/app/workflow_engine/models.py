from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from app.workflow_engine.enums import PortKind, RunStatus
from app.workflow_engine.schema import CURRENT_SCHEMA_VERSION


class PortSpec(BaseModel):
    """节点端口规格定义。"""

    name: str
    kind: PortKind = PortKind.value
    required: bool = True
    description: str | None = None


class EdgeSpec(BaseModel):
    """节点间连线规格定义，描述从源节点端口到目标节点端口的连接。"""

    source_node_id: str
    source_port: str
    target_node_id: str
    target_port: str


class NodeSpec(BaseModel):
    """节点规格定义。"""

    node_id: str
    node_type: str
    version: str = "1.0.0"
    params: dict[str, Any] = Field(default_factory=dict)
    input_ports: list[PortSpec] = Field(default_factory=list)
    output_ports: list[PortSpec] = Field(default_factory=list)
    retry_limit: int = 0
    batch_enabled: bool = False
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    deprecated: bool = False
    replacement_node_type: str | None = None
    parameter_aliases: dict[str, str] = Field(default_factory=dict)


class RuntimePolicy(BaseModel):
    """运行时策略，控制工作流执行行为。"""

    continue_on_error: bool = False
    max_retries_per_node: int = 0


class StoragePolicy(BaseModel):
    """存储策略，描述产物存储后端与基础路径。"""

    backend: str | None = None
    base_path: str | None = None


class WorkflowDefinition(BaseModel):
    """工作流定义，包含节点、边及运行/存储策略。"""

    workflow_id: str
    schema_version: str = CURRENT_SCHEMA_VERSION
    version: str = "1.0.0"
    inputs: dict[str, Any] = Field(default_factory=dict)
    nodes: list[NodeSpec]
    edges: list[EdgeSpec] = Field(default_factory=list)
    runtime_policy: RuntimePolicy = Field(default_factory=RuntimePolicy)
    storage_policy: StoragePolicy = Field(default_factory=StoragePolicy)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_node_ids_unique(self) -> WorkflowDefinition:
        seen: set[str] = set()
        for node in self.nodes:
            if node.node_id in seen:
                raise ValueError(f"Duplicate node_id: {node.node_id}")
            seen.add(node.node_id)
        return self


class ExecutionContext(BaseModel):
    """单次工作流执行的上下文信息。"""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str = ""
    account_id: str | None = None
    storage_backend: str | None = None
    temp_dir: str = "./tmp"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(BaseModel):
    """产物记录，描述节点执行产生的可持久化产物。"""

    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_run_id: str = ""
    node_id: str = ""
    artifact_type: str = ""
    storage_uri: str = ""
    content_type: str | None = None
    size: int | None = None
    checksum: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeExecutionResult(BaseModel):
    """单节点执行结果。"""

    node_id: str
    status: RunStatus = RunStatus.completed
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    """整条工作流的执行结果。"""

    run_id: str
    workflow_id: str
    status: RunStatus = RunStatus.completed
    node_results: list[NodeExecutionResult] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
