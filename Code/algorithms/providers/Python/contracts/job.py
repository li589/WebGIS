from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .product import OutputSpec
from .runtime import CachePolicy, RegionSpec, ResourceHint, TimeRange


@dataclass(slots=True)
class JobRequest:
    job_id: str
    pipeline_name: str
    task_type: str
    time_range: TimeRange
    region: RegionSpec
    datasource_selection: dict[str, Any]
    algorithm_params: dict[str, Any]
    output_spec: OutputSpec
    resource_hint: ResourceHint | None = None
    cache_policy: CachePolicy | None = None
    resume_policy: dict[str, Any] | None = None
    priority: int | None = None
    tags: dict[str, str] = field(default_factory=dict)
    module_name: str | None = None
    workflow_name: str | None = None
    workflow_definition: Any | None = None
    # 透明透传字段：由调用方设置的工作流入口名，结果侧原样回写
    # 修复前：该字段在 AlgorithmWorkflowRequest 中存在但经 bridge 转换时被丢弃，导致信息损失
    workflow_entry_name: str | None = None

    def __post_init__(self) -> None:
        # 结构校验：job_id / pipeline_name 必填非空。
        # 这是构造期可判定的硬约束，不涉及 entry 字段语义。
        # entry 字段（module_name / workflow_name / workflow_definition）的互斥与
        # 必填校验由 validate_job_request() 在 dispatch 前执行，因为合法的
        # "先构造后赋值"模式（测试与 bridge 转换层均使用）要求 entry 字段可在
        # 构造后设置，不应在 __post_init__ 中强制。
        if not self.job_id or not self.pipeline_name:
            raise ValueError("job_id and pipeline_name must be non-empty")


@dataclass(slots=True)
class JobResult:
    job_id: str
    run_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    manifest_uri: str | None = None
    log_uri: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error_summary: str | None = None
