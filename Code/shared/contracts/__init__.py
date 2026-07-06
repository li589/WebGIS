"""Shared API contracts.

契约分层说明（协议统一后的权威关系）：

1. 用户请求层（本包，shared/contracts）：
   - AlgorithmWorkflowRequest / GeeWorkflowRequest / WeatherWorkflowRequest
   - 面向 HTTP API，使用 Pydantic BaseModel，字段可选、松散 dict
   - 是前端 / 外部系统与后端交互的单一事实源

2. 内部执行层（algorithms/providers/Python/contracts）：
   - JobRequest / JobResult / OutputSpec / TimeRange / RegionSpec
   - 面向 Python provider 内部运行时，使用 dataclass(slots=True)，字段必填、结构化
   - 是 Python 算法包内部的权威契约

3. 桥接层（backend/app/services/python_provider_bridge_service.py）：
   - 负责用户请求层 → 内部执行层的转换
   - _build_job_request_payload: AlgorithmWorkflowRequest dict → JobRequest dict
   - 转换规则：
     * 直传：module_name / workflow_name / workflow_definition / workflow_entry_name /
             datasource_selection / algorithm_params / output_spec / resource_hint /
             cache_policy / resume_policy / tags / task_type / region / time_range
     * 新增（运行时派生）：job_id(=run_id) / pipeline_name(="workflow") / priority(映射)
     * 增强：tags 注入 workflow_run_id/workflow_command_type/workflow_layer_id
     * 兜底：task_type/region/time_range 用外层 WorkflowSubmitRequest 补全
   - 校验：_validate_algorithm_request_shape 负责 time_range/region 内部结构校验

字段对应关系详见 shared/contracts/api_contracts.py 中 AlgorithmWorkflowRequest 注释。
"""
