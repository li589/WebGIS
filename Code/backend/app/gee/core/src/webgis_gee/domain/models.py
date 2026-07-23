from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from webgis_gee.domain.enums import AccountState, PortKind, RunStatus
from webgis_gee.workflow.schema import CURRENT_SCHEMA_VERSION


class PortSpec(BaseModel):
    name: str
    kind: PortKind = PortKind.VALUE
    required: bool = True
    description: str | None = None


class EdgeSpec(BaseModel):
    source_node_id: str
    source_port: str
    target_node_id: str
    target_port: str


class NodeSpec(BaseModel):
    node_id: str
    node_type: str
    version: str = "1.0.0"
    params: dict[str, Any] = Field(default_factory=dict)
    input_ports: list[PortSpec] = Field(default_factory=list)
    output_ports: list[PortSpec] = Field(default_factory=list)
    retry_limit: int = Field(default=0, ge=0)
    batch_enabled: bool = False
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    deprecated: bool = False
    replacement_node_type: str | None = None
    parameter_aliases: dict[str, str] = Field(default_factory=dict)


class RuntimePolicy(BaseModel):
    continue_on_error: bool = False
    max_retries_per_node: int = Field(default=0, ge=0)


class StoragePolicy(BaseModel):
    backend: str | None = None
    base_path: str | None = None


class WorkflowDefinition(BaseModel):
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
    def ensure_node_ids_unique(self) -> "WorkflowDefinition":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("workflow contains duplicated node_id values")
        return self


class AccountLease(BaseModel):
    account_id: str
    state: AccountState = AccountState.AVAILABLE
    leased_at: datetime | None = None
    cooldown_until: datetime | None = None
    last_error: str | None = None
    success_count: int = 0
    failure_count: int = 0
    # 与账号关联的 ee.Credentials 对象（运行时对象，不参与 JSON 序列化）
    credentials: Any | None = None
    # GCP project_id（用于 ee.Initialize(project=...)）
    project_id: str | None = None
    # 账号类型：service_account / oauth
    account_type: str = "service_account"
    # 友好显示名（脱敏后的 email 或自定义名称）
    display_name: str | None = None

    def mark_leased(self) -> None:
        self.state = AccountState.LEASED
        self.leased_at = datetime.now(timezone.utc)
        self.cooldown_until = None

    def mark_available(self) -> None:
        self.state = AccountState.AVAILABLE
        self.leased_at = None
        self.cooldown_until = None
        self.last_error = None

    def mark_cooldown(self, seconds: int, reason: str) -> None:
        self.state = AccountState.COOLDOWN
        self.leased_at = None
        self.last_error = reason
        self.failure_count += 1
        self.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)

    def mark_success(self) -> None:
        self.success_count += 1
        self.state = AccountState.AVAILABLE
        self.leased_at = None
        self.cooldown_until = None
        self.last_error = None

    def is_available(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.state == AccountState.AVAILABLE:
            return True
        if (
            self.state == AccountState.COOLDOWN
            and self.cooldown_until
            and self.cooldown_until <= now
        ):
            self.mark_available()
            return True
        return False

    @property
    def health_score(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total


class ArtifactRecord(BaseModel):
    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_run_id: str
    node_id: str
    artifact_type: str
    storage_uri: str
    content_type: str | None = None
    size: int | None = None
    checksum: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionContext(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    workflow_id: str
    account_id: str | None = None
    storage_backend: str | None = None
    temp_dir: str = "./tmp"
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeExecutionResult(BaseModel):
    node_id: str
    status: RunStatus = RunStatus.COMPLETED
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    run_id: str
    workflow_id: str
    status: RunStatus
    node_results: list[NodeExecutionResult] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class DiagnosticsReport(BaseModel):
    status: str
    checks: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
