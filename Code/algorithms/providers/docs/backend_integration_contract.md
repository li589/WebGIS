# Python 后端对接规范

## 1. 文档目的

本文档面向后端平台、调度系统和调用方，说明当前 `Python/` 计算包的标准接入方式。

目标只有三个：

1. 明确 `run_job()` 的真实调用契约。
2. 统一 `JobRequest` 的推荐构造方式。
3. 区分原生入口与兼容入口，避免继续把旧 pipeline 当默认主入口。

补充说明：

当前仓库已经提供最小 HTTP 服务入口，可作为本规范的直接落地实现之一，相关说明见 [minimal_job_http_service.md](file:///d:/Workspace/mat2py/docs/minimal_job_http_service.md)。
若要继续接入平台队列与独立 worker，请参考 [platform_queue_worker_integration.md](file:///d:/Workspace/mat2py/docs/platform_queue_worker_integration.md)。
若要按本轮非 UI 交付方式继续推进真实平台 HTTP 接口、迁移批次和联调验收，请同时参考：

1. [unified_data_access_migration_batches.md](file:///d:/Workspace/mat2py/docs/unified_data_access_migration_batches.md)
2. [platform_http_e2e_validation.md](file:///d:/Workspace/mat2py/docs/platform_http_e2e_validation.md)

补充说明：

当前仓库已经明确进入“统一数据访问与格式适配”规划阶段。若后续需要让模块统一支持缓存数据、在线数据、MinIO 对象与本地多格式对象，请同时参考：

1. [unified_data_access_design.md](file:///d:/Workspace/mat2py/docs/unified_data_access_design.md)
2. [unified_data_access_task_plan.md](file:///d:/Workspace/mat2py/docs/unified_data_access_task_plan.md)

## 2. 统一入口

当前唯一统一任务入口为：

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

其中 `submit_job()` 与 `get_job_status()` 当前除了保留原始 `job_result` 外，还会额外返回：

1. `result_dto`

`result_dto` 的目标是给 WebGIS 一个稳定的结果视图，避免前端或网关层自己解析 `manifest_uri` 的多种形态。

推荐把它当作：

1. 任务详情页主视图
2. 产品清单主视图
3. 图层预览入口主视图

而把原始 `job_result` 当作底层执行记录保留。

如果调用方希望直接把平台现有回调接到当前接口上，当前还可以复用：

```python
from service.platform_adapters import (
    CallbackSchedulerAdapter,
    TrackingSchedulerAdapter,
    CallbackDataSourceAdapter,
    CallbackLoggerAdapter,
    CallbackProductSink,
)
```

这组骨架的作用是把平台现有的状态上报、日志收集、数据解析和产物持久化能力快速映射到当前仓库的 adapter 协议，而不需要先重写整套接口实现。

如果调用方已经有比较稳定的 `platform_client` 对象，当前还可以直接使用首版真实 adapter：

```python
from service import (
    PlatformSchedulerAdapter,
    PlatformDataSourceAdapter,
    PlatformLoggerAdapter,
    PlatformProductSink,
)
```

这些类默认优先约定 `platform_client` 上的方法名，例如：

1. `build_run_context`
2. `update_job_status`
3. `complete_job`
4. `resolve_bundle`
5. `emit_log_event`
6. `persist_manifest`

如果平台现有方法名不一致，也可以显式传入对应的函数回调，不需要修改算法或 `run_job()` 主链。

如果调用方希望直接通过 HTTP/JSON 接入平台，而不是在同一进程内构造 `platform_client`，当前仓库已经补充：

```python
from service import PlatformHttpClient, build_platform_http_job_service
```

其中：

1. `PlatformHttpClient` 负责把 `publish_submission / claim_submission / ack_submission` 以及 scheduler、datasource、logger、product sink 约定统一映射到平台 HTTP 接口
2. `build_platform_http_job_service(...)` 会使用环境变量构造真实平台 HTTP 模式的 `JobService + Worker`
3. `service.http_server --queue-backend platform` 与 `service.worker_process --queue-backend platform` 已可直接进入该模式

如果调用方更偏向 HTTP/JSON 接口而不是直接调用 `JobService`，当前还可以直接复用：

1. `GET /api/v1/modules`
2. `GET /api/v1/modules/{module_name}`
3. `GET /api/v1/workflows`
4. `GET /api/v1/workflows/{workflow_name}`
5. `GET /api/v1/workflows/{workflow_name}/panel-schema`
6. `GET /api/v1/workflows/{workflow_name}/ui-schema`

这组接口的目的不是提交作业，而是给 WebGIS 提供“模块/工作流发现、表单生成、结构化说明”能力。

## 2.1 WebGIS-facing 结果 DTO

`result_dto` 当前包含以下稳定字段：

1. `job_id`
2. `run_id`
3. `status`
4. `started_at`
5. `finished_at`
6. `duration_ms`
7. `error_summary`
8. `artifacts.manifest_uri`
9. `artifacts.log_uri`
10. `artifacts.metadata_uri`
11. `artifacts.manifest`
12. `artifacts.log`
13. `artifacts.metadata`
14. `manifest_loaded`
15. `manifest_summary`
16. `products`
17. `main_layers`
18. `qc_layers`
19. `tables`
20. `metrics`
21. `extra`

字段语义：

1. `manifest_loaded=true` 表示服务端已经成功读取本地 manifest JSON，并完成产品整形
2. `manifest_loaded=false` 表示服务端只拿到了 `manifest_uri`，但未直接展开内容
3. `products[*].is_previewable=true` 表示该产品更适合被 WebGIS 直接挂到预览或下载入口
4. `products[*].storage_backend` 是稳定存储后端标识，当前会归一化为 `minio`、`s3`、`http`、`https`、`file` 或其他 URI scheme
5. `products[*].bucket` 与 `products[*].object_key` 为对象存储友好字段；对 `minio://bucket/key` 与 `s3://bucket/key` 会自动拆分
6. `products[*].preview_url` 与 `products[*].download_url` 优先读取 manifest 显式字段；若产品本身是 HTTP 地址则默认回填为原始 `uri`
7. `products[*].uri` 继续保留为兼容字段，但推荐 WebGIS/FastAPI 优先消费结构化存储字段，而不是自行解析 URI
8. `artifacts.manifest / artifacts.log / artifacts.metadata` 与 `products[*]` 使用同一套结构化存储视图，包含 `uri`、`storage_backend`、`bucket`、`object_key`、`preview_url`、`download_url`
9. `artifacts.*_uri` 继续保留为兼容字段；新接入方建议优先消费 `artifacts.manifest`、`artifacts.log`、`artifacts.metadata`

对 `FastAPI + Celery + Redis + MinIO` 架构的推荐理解是：

1. Celery 任务执行后只需要稳定产出 `JobResult.manifest_uri`
2. 如果 `manifest_uri` 是本地可读路径，服务可直接展开
3. 如果 `manifest_uri` 是 `s3://`、`minio://`、HTTP URL 或其他远端对象存储地址，服务先返回稳定 DTO 框架
4. WebGIS/FastAPI 应优先按 `products[*].storage_backend + bucket + object_key` 构造 MinIO/S3 下载代理、签名 URL 或对象访问入口
5. 如果 `preview_url` 或 `download_url` 已由 manifest 明确给出，则 WebGIS 可直接消费，不必再解析原始 `uri`
6. 本地开发或单机联调场景下，`file` 类型产品会自动补齐 `file://` 形式的 `preview_url/download_url`
7. 同样地，任务详情页里的 manifest、metadata、log 入口也应优先使用 `artifacts.manifest/log/metadata` 的结构化字段，而不是单独解析 `*_uri`

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

补充说明：

1. 当 `workflow_definition` 已显式给出时，`workflow_name` 可以继续作为任务显示名保留，不再作为 preset 选择器使用。
2. 当 `module_name` 已给出时，`workflow_name` 可以作为自动包装单节点 workflow 的名称覆盖值。
3. 真正冲突的组合是 `workflow_definition` 与 `module_name` 同时出现。

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
| `pipeline_name` | 是 | 兼容字段；兼容 pipeline 模式下填写真实注册名，workflow 化模式下通常填 `workflow` |
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

该入口会把平台侧 payload 规范化为 `WorkflowDefinition`，并在结构不合法时抛出明确路径的错误信息。

如果调用方想先拿到“自定义 workflow 的最小输入模板”，可以直接调用 `infer_workflow_request_template(...)`。
它会基于显式图定义推导：

1. 实际需要的 `datasource_selection` 输入键
2. 实际消费到的 `request:*` 键
3. 各节点级别的外部输入依赖

如果调用方想直接生成平台输入面板，可进一步使用：

```python
from workflow.panel_schema import build_workflow_input_panel_schema
from workflow.ui_metadata import build_workflow_input_panel_ui_schema
```

当前会返回三类字段分区：

1. `datasource_fields`
2. `algorithm_param_fields`
3. `request_fields`

每个字段项会附带：

1. 是否必填
2. 值类型提示
3. 被哪些节点消费
4. 来自哪些 module entry
5. 允许值枚举
6. 输入源类型与格式提示

如果调用方希望把这份 schema 直接给前端渲染，可继续使用 `build_workflow_input_panel_ui_schema(...)`。

当前会在原始 panel schema 之上补充：

1. section 级标题与说明
2. 字段中文标签
3. 控件类型建议
4. placeholder
5. 推荐示例值

这意味着平台可以直接基于 Python 输出结果渲染首版动态表单，而不需要自己再维护一套字段展示映射。

### 5.3 `datasource_selection` 演进约定

当前 `datasource_selection` 仍然承担以下职责：

1. 兼容旧模块的路径输入
2. 承载外部数据源选择键
3. 承载运行前准备好的 `_prepared_bundles`

但后续演进方向已经明确：

1. 模块不再优先依赖裸路径
2. `dispatch.py` 将逐步把数据准备结果标准化为可消费的统一输入对象
3. 本地文件、缓存、HTTP、MinIO 与对象存储来源会在底层统一归一化
4. 各类格式读取与转换逻辑会下沉到统一数据访问底座，而不是继续散落在模块内部

也就是说：

1. `datasource_selection` 在短期内仍是兼容层
2. 真正的新能力将以下层的统一数据访问契约为准
3. 具体设计与任务拆解见 [unified_data_access_design.md](file:///d:/Workspace/mat2py/docs/unified_data_access_design.md) 与 [unified_data_access_task_plan.md](file:///d:/Workspace/mat2py/docs/unified_data_access_task_plan.md)

进一步地，如果调用方希望把校验异常直接映射成字段级错误反馈，可使用：

```python
from contracts.validation_feedback import build_validation_feedback
```

当前会统一处理：

1. `JobRequestDecodeError`
2. `WorkflowDefinitionDecodeError`
3. `JobRequestValidationError`
4. `WorkflowDefinitionValidationError`

返回结构中每个 issue 至少包含：

1. `code`
2. `field_path`
3. `section`
4. `label`
5. `control_type`
6. `details`

这意味着平台不只可以“知道请求错了”，还可以直接把错误定位到：

1. `datasource_selection`
2. `algorithm_params`
3. `request`
4. `workflow_definition`

并与前面生成的 UI metadata 形成闭环。

如果调用方希望直接返回标准 HTTP 错误响应，可继续使用：

```python
from contracts.api_errors import build_api_error_response
```

当前返回体至少包含：

1. `error_type`
2. `error_code`
3. `http_status`
4. `retryable`
5. `user_message`
6. `developer_message`
7. `issues`
8. `suggested_fixes`

默认映射规则如下：

1. decode 失败 -> `400`
2. validation 失败 -> `422`
3. 未分类异常 -> `500`

这意味着后端 HTTP 层已经可以直接把 Python 侧的校验异常、字段级 issue 和修复建议打包成稳定响应，而不需要再手写一层错误翻译逻辑。

如果调用来自 HTTP/JSON，推荐流程为：

1. 平台先按本文档和 JSON schema 组装 payload
2. 如有需要，先调用 `get_workflow_definition_json_schema()` 做前置校验
3. 再通过 `coerce_job_request()` 一次性转成完整 `JobRequest`
4. 最后调用 `run_job()`

当前 `JobRequest` 的 HTTP/JSON 反序列化入口为：

```python
from contracts.serialization import coerce_job_request, get_job_request_json_schema
from contracts.validation import validate_job_request
```

它会统一完成：

1. `time_range.start/end` 的 ISO 时间解析
2. `region` 的对象结构校验
3. `output_spec` 的默认值填充
4. `resource_hint / cache_policy` 的 JSON 到 dataclass 适配
5. `workflow_definition` 的级联反序列化
6. `validate_job_request()` 的请求级业务校验

## 6. 标准请求示例

### 6.1 单模块模式

适用场景：

1. 单个原生模块即可完成任务
2. 不需要显式图编排

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

适用场景：

1. 走项目内置的标准编排
2. 当前典型例子是 `retrieval_workflow`

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

适用场景：

1. 由平台或上层服务动态生成图
2. 需要自定义节点连接关系

```python
from workflow.graph import WorkflowDefinition, WorkflowNodeSpec, WorkflowOutputSpec

workflow_definition = WorkflowDefinition(
    workflow_id="custom-single-module",
    name="custom-single-module",
    description="Example workflow",
    nodes=[
        WorkflowNodeSpec(
            node_id="module_node",
            node_type="module",
            input_bindings={
                "datasource_selection": "request:datasource_selection",
                "algorithm_params": "request:algorithm_params",
                "output_spec_extra": "request:output_spec_extra",
            },
            params={"module_name": "ndvi_daily"},
        )
    ],
    outputs=[WorkflowOutputSpec(name="final_manifest", source="node:module_node.manifest")],
)
```

对应请求：

```yaml
job_id: custom-job-001
pipeline_name: workflow
task_type: ndvi_daily
time_range:
  start: 2025-01-01
  end: 2025-01-16
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
module_name: null
workflow_name: null
workflow_definition: WorkflowDefinition(...)
```

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

它会根据 `algorithm_params.mode` 串联：

1. `timeseries_bundle -> block_inversion`
2. 或 `timeseries_bundle -> omega_block`

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

当前运行前校验已经不只检查字段组合，还会校验入口对应的关键输入模板。

关键规则如下：

1. `module_name=smap_daily`、`ndvi_daily`、`station_daily`、`fy_daily` 时，`datasource_selection.input_dir` 是必需项
2. `module_name=inversion_daily`、`block_inversion`、`omega_block` 时，`datasource_selection.input_mat` 是必需项
3. `module_name=block_inversion` 时，`algorithm_params.mode` 若提供，必须是 `dh` 或 `ddca`
4. `module_name=omega_block` 时，`algorithm_params.exp_mode` 若提供，支持 `Exp0`、`Exp1A`、`Exp1B`、`Exp2`
5. `workflow_name=retrieval_workflow` 时，`algorithm_params.mode` 支持 `dh`、`ddca`、`omega`
6. 当 `workflow_name=retrieval_workflow` 且 `mode=omega` 时，必须提供 `omega_fixed_mat` 与 `exp0_calib_mat`
7. `task_type` 会和 `module_name / workflow_name` 做一致性校验；不匹配时在执行前直接拒绝
8. 对显式 `workflow_definition`，系统现在会根据图中的 `input:*` 绑定自动推导最小输入模板，并在缺 key 时运行前直接拒绝

### 8.2 循环调用防护

当前系统已增加两层防护：

1. workflow 图内部环路继续由 workflow 静态校验拦截
2. nested `bridge.pipeline` / compat module 禁止再次调用 compat shim pipeline
3. 运行时会记录 `call_chain`，重复进入同一 workflow/pipeline 会被直接拒绝

这意味着：

1. `workflow -> bridge.pipeline -> retrieval_workflow_pipeline` 这类危险回流路径现在会被提前阻断
2. 模块之间不应通过 compat/shim 形成递归嵌套调用

### 8.3 日志规范

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

当前实现已开始统一以下阶段名：

1. `dispatch.workflow`
2. `dispatch.pipeline`
3. `workflow.node.<node_id>`
4. `workflow.dispatch`

并且新增了：

1. 节点级 `start/end/error`
2. 最终 manifest 的 `job_manifest` artifact 日志
3. 本地 `ConsoleLoggerAdapter` 的 JSON 行输出

## 9. workflow 图定义约束

当前实现的关键约束如下：

1. 默认节点类型使用 `node_type: "module"`
2. 兼容桥接节点类型使用 `node_type: "bridge.pipeline"`
3. `input_bindings` 当前是 `dict[str, str]`
4. 绑定语法只支持 `request:*`、`input:*`、`node:*`
5. 工作流输出建议明确暴露 `final_manifest`
6. `run_job()` 在真正执行前会先做一轮 workflow 静态校验

额外注意：

1. 同一输入端口不要同时通过 `input_bindings` 和 `edges` 重复绑定
2. 否则会触发 workflow 输入冲突校验
3. 未注册的 `node_type`、未知端口、非法 `request:*` 绑定和图环路也会在运行前被提前拒绝

## 10. JobResult 契约

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

## 11. 对接建议

推荐平台侧按以下顺序接入：

1. 新业务优先走 `module_name`
2. 标准反演链优先走 `workflow_name=retrieval_workflow`
3. 旧任务保留 `pipeline_name` 兼容调用，但逐步迁移
4. 如果走显式工作流，优先复用 `workflow.serialization` 提供的适配入口与 JSON schema
5. 把 `algorithm_params` 作为字段别名和算法开关的主要扩展入口

## 12. 相关文档

进一步说明可参考：

1. [README.md](file:///d:/Workspace/mat2py/Python/README.md)
2. [detailed_design.md](file:///d:/Workspace/mat2py/docs/detailed_design.md)
3. [workflow_extension_design.md](file:///d:/Workspace/mat2py/docs/workflow_extension_design.md)
4. [pipeline_registry_audit.md](file:///d:/Workspace/mat2py/docs/pipeline_registry_audit.md)
5. [workflow_http_json_adapter.md](file:///d:/Workspace/mat2py/docs/workflow_http_json_adapter.md)
6. [unified_data_access_design.md](file:///d:/Workspace/mat2py/docs/unified_data_access_design.md)
7. [unified_data_access_task_plan.md](file:///d:/Workspace/mat2py/docs/unified_data_access_task_plan.md)
