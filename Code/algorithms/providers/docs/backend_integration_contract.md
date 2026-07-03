# Python 后端对接规范

## 1. 文档目的

本文档面向后端平台、调度系统和调用方，说明当前 `Code/algorithms/providers/Python/` 计算包的标准接入方式。

目标有三项：

1. 明确 `run_job()` 的真实调用契约。
2. 统一 `JobRequest` 的推荐构造方式。
3. 区分原生入口、工作流入口与兼容入口，避免继续把旧 pipeline 当默认主入口。

## 2. 统一入口

当前统一任务入口为：

```python
from runner.dispatch import run_job
```

函数签名：

```python
def run_job(
    request: JobRequest,
    scheduler_adapter: SchedulerAdapter,
    datasource_adapter: DataSourceAdapter,
    logger_adapter: LoggerAdapter,
    product_sink: ProductSink | None = None,
    workspace: str | Path | None = None,
) -> JobResult:
    ...
```

调用方只需要负责：

1. 构造 `JobRequest`
2. 提供调度、数据源、日志适配器
3. 可选提供产品输出适配器

如果调用方更希望以服务边界而不是函数边界接入，当前还可以使用：

```python
from service.job_api import JobService, build_local_job_service
```

其中：

1. `JobService.validate_job(payload)` 只做请求解码和业务校验
2. `JobService.submit_job(payload)` 统一执行 `coerce_job_request -> validate_job_request -> run_job`
3. `JobService.submit_job_async(payload)` 返回异步 `submission_id`
4. `JobService.get_job_status(submission_id)` 查询异步作业状态
5. `build_local_job_service()` 使用本地 adapter 构造最小可运行服务
6. `JobService.list_modules_response()` 返回模块 catalog
7. `JobService.describe_module_response(module_name)` 返回模块详情
8. `JobService.list_workflows_response()` 返回 workflow catalog
9. `JobService.describe_workflow_response(workflow_name)` 返回 workflow 详情
10. `JobService.get_workflow_panel_schema_response(workflow_name)` 返回 workflow panel schema
11. `JobService.get_workflow_ui_schema_response(workflow_name)` 返回 workflow UI schema

## 2.1 WebGIS-facing 结果 DTO

`submit_job()` 与 `get_job_status()` 当前除了保留原始 `job_result` 外，还会额外返回：

1. `result_dto`

`result_dto` 的目标是给 WebGIS 一个稳定的结果视图，避免前端或网关层自己解析 `manifest_uri` 的多种形态。

推荐把它当作：

1. 任务详情页主视图
2. 产品清单主视图
3. 图层预览入口主视图

而把原始 `job_result` 当作底层执行记录保留。

## 3. 执行模式

`run_job()` 当前支持四种模式，优先级从高到低如下：

1. `workflow_definition`
2. `workflow_name`
3. `module_name`
4. `pipeline_name`

说明：

1. 只要 `workflow_definition` 非空，就直接执行显式工作流。
2. 否则如果 `workflow_name` 非空，就构建预定义 workflow preset。
3. 否则如果 `module_name` 非空，就自动包装成单节点 workflow。
4. 只有前三者都为空时，才回退到兼容 `pipeline_name` 路径。

推荐顺序：

1. 默认优先 `module_name`
2. 多节点编排优先 `workflow_name`
3. 需要完全自定义图时使用 `workflow_definition`
4. `pipeline_name` 仅用于旧接口兼容

## 4. JobRequest 契约

当前 `JobRequest` 字段如下：

```python
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
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| `job_id` | 是 | 平台侧任务唯一 ID |
| `pipeline_name` | 是 | 兼容字段；兼容 pipeline 模式下填写真实注册名，workflow 化模式下通常填占位值 |
| `task_type` | 是 | 业务类型标签，供调度与日志使用 |
| `time_range` | 是 | 时间范围 |
| `region` | 是 | 空间范围 |
| `datasource_selection` | 是 | 数据源选择、外部输入与路径配置 |
| `algorithm_params` | 是 | 算法参数、字段别名、模式开关 |
| `output_spec` | 是 | 输出格式与额外输出配置 |
| `resource_hint` | 否 | 资源提示 |
| `cache_policy` | 否 | 缓存策略 |
| `resume_policy` | 否 | 续跑策略 |
| `priority` | 否 | 优先级 |
| `tags` | 否 | 附加标签 |
| `module_name` | 否 | 单模块入口 |
| `workflow_name` | 否 | 预定义 workflow 名称 |
| `workflow_definition` | 否 | 显式工作流定义 |

## 5. 推荐约定

### 5.1 `pipeline_name` 约定

当前 `pipeline_name` 仍是必填字段，但语义已经分化：

1. 兼容 pipeline 模式：必须填写真实注册名，例如 `smap_daily_pipeline`
2. `module_name / workflow_name / workflow_definition` 模式：通常填写占位值 `workflow`

注意：

1. `pipeline_name: workflow` 不是注册表里的真实 pipeline 名称。
2. 它只是当前 `JobRequest` 契约还未去掉该字段时的兼容占位写法。

### 5.2 `workflow_definition` 约定

当前 `run_job()` 已支持三种输入形态：

1. `WorkflowDefinition` 实例
2. JSON-compatible `dict`
3. JSON 字符串

运行时会先经过统一适配入口：

```python
from workflow.serialization import coerce_workflow_definition
from workflow.template_inference import infer_workflow_request_template
```

### 5.3 `datasource_selection` 演进约定

当前 `datasource_selection` 仍然承担以下职责：

1. 兼容旧模块的路径输入
2. 承载外部数据源选择键
3. 承载运行前准备好的 `_prepared_bundles`

但后续演进方向已经明确：

1. 模块不再优先依赖裸路径
2. 数据准备会逐步标准化为统一输入对象
3. 本地文件、缓存、HTTP、MinIO 与对象存储来源会在底层统一归一化
4. 各类格式读取与转换逻辑会下沉到统一数据访问底座

## 6. 标准请求示例

### 6.1 单模块模式

```yaml
job_id: smap-job-001
pipeline_name: workflow
task_type: smap_daily
time_range:
  start: 2025-01-01
  end: 2025-01-02
region:
  kind: global
  value: {}
datasource_selection: {}
algorithm_params: {}
output_spec:
  raster_format: COG
  table_format: parquet
  include_qc: true
  include_manifest: true
  extra: {}
module_name: smap_daily
workflow_name: null
workflow_definition: null
```

### 6.2 预定义工作流模式

```yaml
job_id: retrieval-job-001
pipeline_name: workflow
task_type: retrieval
time_range:
  start: 2025-01-01
  end: 2025-01-31
region:
  kind: bbox
  value:
    xmin: 73
    ymin: 18
    xmax: 135
    ymax: 54
datasource_selection: {}
algorithm_params:
  mode: omega
output_spec:
  raster_format: COG
  table_format: parquet
  include_qc: true
  include_manifest: true
  extra: {}
module_name: null
workflow_name: retrieval_workflow
workflow_definition: null
```

### 6.3 显式工作流模式

显式工作流建议通过 `workflow.serialization` 与 `workflow.template_inference` 生成和校验，再交给 `run_job()`。

## 7. 当前内置入口

### 7.1 原生模块

当前已落地的原生模块包括：

1. `daily_bundle`
2. `timeseries_bundle`
3. `ndvi_daily`
4. `smap_daily`
5. `station_daily`
6. `fy_daily`
7. `inversion_daily`
8. `block_inversion`
9. `omega_block`

### 7.2 预定义工作流

当前已落地的 workflow preset：

1. `retrieval_workflow`

### 7.3 兼容 pipeline

当前兼容 pipeline 仍保留在 `runner/registry.py` 中，例如：

1. `smap_daily_pipeline`
2. `ndvi_daily_pipeline`
3. `fy_daily_pipeline`
4. `station_daily_pipeline`
5. `inversion_daily_pipeline`
6. `daily_bundle_pipeline`
7. `timeseries_bundle_pipeline`
8. `block_inversion_pipeline`
9. `omega_block_pipeline`
10. `retrieval_workflow_pipeline`

说明：

1. `retrieval_workflow_pipeline` 当前只是兼容 shim
2. 调用方应优先改用 `workflow_name: retrieval_workflow`

## 8. 请求模板与日志规范

### 8.1 模块与工作流模板

当前运行前校验会检查入口对应的关键输入模板。

### 8.2 日志规范

当前日志接口仍然是 `LoggerAdapter`，但推荐平台按结构化事件消费。

建议至少统一以下字段：

1. `timestamp`
2. `job_id`
3. `run_id`
4. `event_type`
5. `stage`
6. `message`
7. `progress`
8. `extra`

## 9. JobResult 契约

当前 `run_job()` 返回 `JobResult`：

```python
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
```

状态约定：

1. 成功时 `status="success"`
2. 失败时 `status="failed"`
3. 失败摘要写入 `error_summary`

## 10. 对接建议

推荐平台侧按以下顺序接入：

1. 新业务优先走 `module_name`
2. 标准反演链优先走 `workflow_name=retrieval_workflow`
3. 旧任务保留 `pipeline_name` 兼容调用，但逐步迁移
4. 如果走显式工作流，优先使用 `workflow.serialization` 和 `workflow.template_inference`
5. 把 `algorithm_params` 作为字段别名和算法开关的主要扩展入口

## 11. 相关文档

进一步说明可参考：

1. `README.md`
2. `detailed_design.md`
3. `workflow_extension_design.md`
4. `pipeline_registry_audit.md`
5. `workflow_http_json_adapter.md`
6. `unified_data_access_design.md`
7. `unified_data_access_task_plan.md`
