# Python 计算包详细设计文档

## 1. 文档定位

本文档是 [blueprint_report.md](file:///d:/Workspace/mat2py/docs/blueprint_report.md) 的下一层设计文档。

蓝图报告回答的是：

1. 为什么要重构。
2. 数据源是什么。
3. 为什么要做成 WebGIS 可调用后端。
4. 为什么要从单脚本转成产品矩阵。

而本文档回答的是：

1. Python 计算包到底怎么组织。
2. 对外接口长什么样。
3. 内部模块怎么拆。
4. 数据契约怎么定义。
5. 不同模块如何在运行时协作。
6. A/B/C/D 四类 MATLAB 代码如何迁移成 Python pipeline。

本文档不设计完整调度系统，不设计前端，不设计集群资源管理器。  
本文档只设计一件事：

**一套可被作业调度系统调用的、高性能、多参数、统一接口的 Python 遥感计算包。**

如果需要进一步把当前 pipeline 扩展为“节点化工作流 / 图执行模型 / 多格式统一输入层”，请继续参考：

- [workflow_extension_design.md](file:///d:/Workspace/mat2py/docs/workflow_extension_design.md)

## 2. 设计目标

### 2.1 核心目标

这一计算包需要满足以下目标：

1. 能把现有 MATLAB 处理流程统一迁移到 Python。
2. 能被外部调度系统稳定调用。
3. 能统一接入不同数据源。
4. 能统一输出结构化产品。
5. 能记录结构化日志。
6. 能支持多参数任务、多变量输出、多时间尺度产品。

### 2.2 非目标

以下内容不在当前设计范围内：

1. 完整的前端 API 网关。
2. 集群调度器本体。
3. 容器编排系统。
4. 用户权限系统。
5. 分布式数据库设计。

### 2.3 成功标准

成功标准不是“某一个 MATLAB 脚本能被 Python 复刻运行”，而是：

1. 任意任务都能通过统一入口启动。
2. 任意任务都能通过统一数据接口取数。
3. 任意任务都能通过统一日志接口汇报状态。
4. 任意任务都能通过统一产品接口交付产物。
5. A/B/C/D 各模块都能在同一框架下落地。

## 3. 设计原则

### 3.1 平台无关

外部平台可能变化，调度系统也可能变化。  
因此计算包不能绑定某一种调度器或某一种 Web 框架。

### 3.2 接口先行

先定义：

1. 任务请求对象。
2. 数据请求对象。
3. 产品清单对象。
4. 日志事件对象。

再写内部逻辑。

### 3.3 算法与 I/O 分离

算法核心尽量不感知：

1. 数据来自本地还是远程。
2. 文件在缓存层还是持久层。
3. 日志发往终端还是平台。

### 3.4 结果优先而不是文件优先

内部模块返回的首先应该是“领域对象”或“产品对象”，然后再由产品输出层决定写成什么格式。

### 3.5 兼容现有科研流程

前期允许保留 `.mat` 兼容输出，但不允许把 `.mat` 继续当作唯一长期接口。

## 4. 系统边界

### 4.1 外部系统视角

完整平台大致是：

1. 前端提交请求。
2. 平台后端组装作业。
3. 调度器安排资源。
4. Python 计算包执行。
5. 平台获取日志和产物。

因此本计算包在架构中的位置是：

```text
前端 -> 平台后端 -> 调度系统 -> Python 计算包 -> 产品存储/日志回传
```

### 4.2 本计算包负责的边界

本计算包内部负责：

1. 任务入口。
2. 数据接入。
3. 数据标准化。
4. 算法执行。
5. 产品写出。
6. 日志回报。

### 4.3 本计算包对外暴露的边界

强制对外接口：

1. 调度适配接口。
2. 数据源适配接口。
3. 日志适配接口。

推荐补充接口：

4. 产品输出接口。

## 5. 总体架构

## 5.1 分层结构

从设计目标上看，系统仍然可以抽象为以下能力层，但当前实现已经按“先落可运行主链，再逐步补外围层”的策略推进。

### 目标能力层

```text
interfaces      对外协议层
contracts       请求/响应/产品/事件契约层
runner          统一任务入口层
pipelines       业务流程编排层
ingest          原始数据接入与 bundle 装配层
algorithms      科学计算核心层
publish         产品交付层
storage         缓存/路径/中间结果组织层
```

### 当前已落地的主干层

```text
interfaces      已落地
contracts       已落地
runner          已落地
pipelines       已落地
ingest          已落地
algorithms      已落地
utils           已落地
publish/storage/standardize   仍以规划位为主，尚未作为独立目录完全展开
```

### 5.2 各层职责

#### `interfaces`

定义对外协议，不写算法实现。

#### `contracts`

定义所有标准对象：

1. `JobRequest`
2. `JobResult`
3. `DataRequest`
4. `DataBundle`
5. `ProductManifest`
6. `LogEvent`

#### `runner`

统一任务入口和运行时上下文创建。

#### `pipelines`

把一条业务链组织起来，例如：

1. NDVI 日产品生产。
2. SMAP 日产品生产。
3. FY 日产品生产。
4. 站点验证产品生产。
5. 反演产品生产。

#### `ingest`

读取原始文件并提取变量和元信息。

#### `algorithms`

只做科学计算。

#### `publish`

把内部产品写成外部产品，并生成 manifest。

#### `storage`

负责缓存路径、中间文件、命名策略、分块存储策略。

## 6. 目录结构设计

当前代码已经统一直接落在 `d:\Workspace\mat2py\Python` 根目录下，不再使用早期方案中的 `Python/mat2py/` 二级包结构。

### 当前实际结构

```text
mat2py/
  docs/
    blueprint_report.md
    detailed_design.md
    field_mapping_contract.md
  Python/
    interfaces/
      scheduler.py
      datasource.py
      logger.py
      product_sink.py
    contracts/
      job.py
      data.py
      product.py
      event.py
      runtime.py
    runner/
      dispatch.py
      runtime.py
      registry.py
    ingest/
      mat_bundle.py
      ndvi.py
      smap.py
      fy.py
      station.py
      daily_bundle.py
      timeseries_bundle.py
    algorithms/
      ndvi.py
      physics.py
      inversion.py
      block_inversion.py
      omega.py
      fy.py
      station.py
    pipelines/
      ndvi_products.py
      smap_products.py
      fy_products.py
      station_products.py
      inversion_products.py
      daily_bundle_products.py
      timeseries_bundle_products.py
      block_inversion_products.py
      omega_block_products.py
      retrieval_workflow_products.py
    utils/
      fy_executor.py
      local_adapters.py
    README.md
    pyproject.toml
    requirements.txt
```

### 当前已经注册的 pipeline

以 `runner/registry.py` 为准，当前已可直接调度的兼容 pipeline 包括：

- `smap_daily_pipeline`
- `ndvi_daily_pipeline`
- `fy_daily_pipeline`
- `station_daily_pipeline`
- `inversion_daily_pipeline`
- `daily_bundle_pipeline`
- `timeseries_bundle_pipeline`
- `block_inversion_pipeline`
- `omega_block_pipeline`
- `retrieval_workflow_pipeline`

这些名称当前都应视为兼容入口，而不是未来主执行面。默认请求应优先使用 `module_name` 或 `workflow_name`。更细的分类与迁移建议见 `pipeline_registry_audit.md`。

后续新增代码都应继续直接放在 `Python/` 根目录下的对应分层目录中，不再回退到 `Python/mat2py/` 的旧结构。

## 7. 核心运行时模型

### 7.1 运行时总体对象

统一运行时建议包含六类核心对象：

1. `JobRequest`
2. `RuntimeContext`
3. `PipelineContext`
4. `DataBundle`
5. `ProductManifest`
6. `JobResult`

### 7.2 运行时执行顺序

统一执行顺序如下：

```text
run_job(request)
  -> 校验 request
  -> 创建 RuntimeContext
  -> 创建 LoggerAdapter 上下文
  -> 选择 pipeline
  -> pipeline 请求数据
  -> datasource 返回 DataBundle
  -> pipeline 调用 standardize / algorithms
  -> publish 写产品
  -> 生成 ProductManifest
  -> 返回 JobResult
```

### 7.3 运行上下文

运行上下文必须统一封装，而不是各 pipeline 自己拼装。

建议对象 `RuntimeContext` 至少包含：

- `job_id`
- `run_id`
- `workspace`
- `tmp_dir`
- `cache_dir`
- `resource_hint`
- `datasource_adapter`
- `logger_adapter`
- `product_sink`
- `clock`
- `env`

## 8. 契约设计

这一节定义整个系统最重要的对象契约。

## 8.1 `JobRequest`

### 8.1.1 作用

描述一次外部请求希望执行什么任务。

### 8.1.2 必需字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | `str` | 外部作业 ID |
| `pipeline_name` | `str` | 兼容字段；兼容 pipeline 模式下表示目标 pipeline 名称，`module/workflow` 模式下通常传占位值 `workflow` |
| `task_type` | `str` | 任务类型，如 `ndvi_daily`、`smap_daily`、`inversion_run` |
| `time_range` | `TimeRange` | 时间范围 |
| `region` | `RegionSpec` | 空间范围 |
| `datasource_selection` | `dict` | 数据源选择配置 |
| `algorithm_params` | `dict` | 计算参数 |
| `output_spec` | `OutputSpec` | 输出要求 |

### 8.1.3 可选字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `resource_hint` | `ResourceHint` | 资源提示，不是强制资源分配 |
| `cache_policy` | `CachePolicy` | 缓存策略 |
| `resume_policy` | `ResumePolicy` | 断点续跑策略 |
| `priority` | `int` | 优先级提示 |
| `tags` | `dict[str, str]` | 附加标签 |
| `module_name` | `str \| None` | 原生模块入口；非空时由 `run_job()` 自动包装为单节点 workflow |
| `workflow_name` | `str \| None` | 预定义 workflow preset 名称，例如 `retrieval_workflow` |
| `workflow_definition` | `Any \| None` | 显式工作流定义；当前实现要求为 `WorkflowDefinition` 实例 |

### 8.1.4 Python 原型

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

补充说明：

1. 当前默认入口应优先使用 `module_name` 或 `workflow_name`。
2. `workflow_definition` 当前支持 `WorkflowDefinition` 实例、JSON-compatible `dict` 和 JSON 字符串；调用侧若从 JSON 入参进入，推荐先通过 `workflow.serialization` 做统一反序列化与结构校验。
3. `pipeline_name` 仍保留在契约里，主要是为了兼容旧 pipeline 和保持 `JobRequest` 结构稳定。

## 8.2 `JobResult`

### 8.2.1 作用

作为统一任务执行返回对象。

### 8.2.2 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | `str` | 原始作业 ID |
| `run_id` | `str` | 实际运行 ID |
| `status` | `str` | 当前实现主要返回 `success` / `failed`，保留向 `partial_success` 扩展的设计位 |
| `started_at` | `datetime` | 开始时间 |
| `finished_at` | `datetime` | 结束时间 |
| `manifest_uri` | `str` | 产品清单位置 |
| `log_uri` | `str \| None` | 日志位置 |
| `metrics` | `dict` | 执行指标 |
| `error_summary` | `str \| None` | 错误摘要 |

## 8.3 `DataRequest`

### 8.3.1 作用

描述一次取数请求。

### 8.3.2 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `dataset_name` | `str` | 数据集名称 |
| `variables` | `list[str]` | 所需变量 |
| `time_range` | `TimeRange` | 时间范围 |
| `spatial_filter` | `RegionSpec \| None` | 空间过滤 |
| `depth_filter` | `dict[str, Any] \| None` | 深度过滤或其他层次过滤条件 |
| `acquire_mode` | `str` | `lazy` / `partial` / `full` |
| `cache_policy` | `CachePolicy \| None` | 缓存策略 |
| `target_grid` | `dict[str, Any] \| None` | 目标网格要求 |

## 8.4 `DataBundle`

### 8.4.1 作用

表示一次取数后得到的数据集合，不要求一开始就完全物化。

### 8.4.2 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `bundle_id` | `str` | 数据包 ID |
| `dataset_name` | `str` | 数据集名称 |
| `variables` | `list[str]` | 实际变量 |
| `time_range` | `TimeRange` | 时间覆盖 |
| `storage_mode` | `str` | `lazy` / `partial` / `full` |
| `local_paths` | `list[str]` | 本地实体文件路径 |
| `remote_refs` | `list[str]` | 远程引用 |
| `metadata` | `dict` | 元数据 |
| `is_materialized` | `bool` | 是否已物化 |

## 8.5 `ProductManifest`

### 8.5.1 作用

统一描述一次任务产生的所有产品。

### 8.5.2 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | `str` | 作业 ID |
| `run_id` | `str` | 运行 ID |
| `products` | `list[ProductRef]` | 全部产品 |
| `main_layers` | `list[str]` | 主要图层 |
| `qc_layers` | `list[str]` | 质量图层 |
| `tables` | `list[str]` | 表格产品 |
| `metadata_uri` | `str \| None` | 元数据文件位置 |
| `created_at` | `datetime` | 生成时间 |
| `extra` | `dict` | 扩展元数据 |

补充说明：

`main_layers/qc_layers/tables` 用于描述结果发现层；
像 `fy_daily_plan_json`、`fy_daily_command_plan`、`*_mat` 这类兼容或编排产物，仍通过 `products[].type` 与 `extra` 暴露，不要求强行映射进图层/表格语义。

## 8.6 `LogEvent`

### 8.6.1 作用

统一描述日志事件，供平台或日志系统消费。

### 8.6.2 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | `str` | 作业 ID |
| `run_id` | `str` | 运行 ID |
| `stage` | `str` | 所在阶段 |
| `event_type` | `str` | 事件类型 |
| `timestamp` | `datetime` | 时间戳 |
| `message` | `str` | 文本信息 |
| `progress` | `float \| None` | 进度百分比 |
| `extra` | `dict` | 扩展字段 |

## 9. 枚举与子契约设计

## 9.1 `TaskType`

建议至少保留：

- `ndvi_standardize`
- `ndvi_daily_product`
- `smap_daily_product`
- `fy_daily_product`
- `station_standardize`
- `station_validation`
- `inversion_run`
- `omega_avg_build`

## 9.2 `AcquireMode`

- `lazy`
- `partial`
- `full`

## 9.3 `ProductType`

- `raster`
- `table`
- `manifest`
- `auxiliary`
- `mat_dataset`
- `plan_json`
- `command_plan`

说明：

当前 Python 兼容层除了最终发布导向的 `raster/table/manifest` 外，还会显式产出 `.mat` 兼容数据集与计划类产物。
这些类型主要服务于 MATLAB 迁移过渡期、算法联调和命令执行编排；后续面向 WebGIS 的正式发布层仍应继续收敛到栅格、表和元数据三类标准产品。

## 9.4 `StageName`

- `validate_request`
- `discover_data`
- `acquire_data`
- `standardize_data`
- `run_algorithm`
- `publish_products`
- `finalize`

## 10. 对外接口详细设计

## 10.1 `SchedulerAdapter`

### 10.1.1 设计意图

这里不是实现调度系统，而是让调度系统可以向计算包传递运行上下文。

### 10.1.2 主要职责

1. 提供调度上下文。
2. 接收阶段状态更新。
3. 接收最终执行结果。

### 10.1.3 协议原型

```python
class SchedulerAdapter(Protocol):
    def get_run_context(self, request: JobRequest) -> dict[str, Any]:
        ...

    def update_status(self, job_id: str, run_id: str, status: str, detail: dict[str, Any] | None = None) -> None:
        ...

    def complete(self, result: JobResult) -> None:
        ...
```

### 10.1.4 说明

`SchedulerAdapter` 不负责分配 CPU，也不负责排队。  
它只是让你的计算包和外部调度器之间有一个稳定的适配层。

## 10.2 `DataSourceAdapter`

### 10.2.1 设计意图

统一隐藏数据来自：

1. 本地磁盘
2. 缓存层
3. 远程存储
4. 在线 API

之间的差异。

### 10.2.2 能力分层

建议定义四级能力：

1. `discover`
2. `resolve`
3. `acquire`
4. `materialize`

### 10.2.3 协议原型

```python
class DataSourceAdapter(Protocol):
    def discover(self, request: DataRequest) -> list[Any]:
        ...

    def resolve(self, request: DataRequest) -> DataBundle:
        ...

    def acquire(self, bundle: DataBundle) -> DataBundle:
        ...

    def materialize(self, bundle: DataBundle) -> DataBundle:
        ...
```

### 10.2.4 不同模式说明

#### `lazy`

只返回可访问引用，不立即下载全部内容。

#### `partial`

只下载变量、时间窗、空间窗的局部数据。

#### `full`

下载或复制完整数据副本。

## 10.3 `LoggerAdapter`

### 10.3.1 设计意图

使日志从“面向终端输出”变成“面向平台事件”。

### 10.3.2 协议原型

```python
class LoggerAdapter(Protocol):
    def bind_context(self, job_id: str, run_id: str) -> None:
        ...

    def emit_stage_start(self, stage: str, message: str) -> None:
        ...

    def emit_progress(self, stage: str, progress: float, message: str) -> None:
        ...

    def emit_warning(self, stage: str, message: str, extra: dict[str, Any] | None = None) -> None:
        ...

    def emit_error(self, stage: str, message: str, extra: dict[str, Any] | None = None) -> None:
        ...

    def emit_artifact(self, stage: str, artifact_uri: str, artifact_type: str) -> None:
        ...

    def emit_stage_end(self, stage: str, message: str) -> None:
        ...
```

### 10.3.3 日志事件类型

建议统一以下事件：

- `job_started`
- `stage_started`
- `progress`
- `warning`
- `error`
- `artifact_emitted`
- `stage_finished`
- `job_finished`

## 10.4 `ProductSink`

### 10.4.1 设计意图

统一产品交付行为，防止输出散乱。

### 10.4.2 协议原型

```python
class ProductSink(Protocol):
    def write_raster(self, product: RasterProduct) -> ProductRef:
        ...

    def write_table(self, product: TableProduct) -> ProductRef:
        ...

    def write_manifest(self, manifest: ProductManifest) -> str:
        ...
```

### 10.4.3 输出职责

1. 统一命名。
2. 统一路径。
3. 统一格式。
4. 统一 manifest。

## 11. 领域模型设计

## 11.1 时间模型

### `TimeRange`

```python
@dataclass(slots=True)
class TimeRange:
    start: datetime
    end: datetime
    step: str | None = None
```

### 说明

`step` 可以表示：

- `1D`
- `8D`
- `1M`
- `DOY`

## 11.2 空间模型

### `RegionSpec`

```python
@dataclass(slots=True)
class RegionSpec:
    kind: str
    value: dict[str, Any]
```

支持形式：

1. 全局
2. bbox
3. shp/geojson
4. 行政区编码
5. 网格编号集合

### 当前实现说明

当前 `DataSourceAdapter` 接口和 `BasePipeline.datasource_adapter` 已经预留在统一入口中，但现阶段多数 pipeline 仍直接消费 `JobRequest.datasource_selection` 中的本地路径与参数配置。  
也就是说，数据源抽象的协议边界已经稳定，而且入口层已接入 `plan -> adapter` 的预取与物化过程；但“所有 pipeline 都通过 adapter 完整接管 discover/resolve/acquire/materialize”仍属于下一阶段工作。

## 11.3 网格模型

### `GridSpec`

```python
@dataclass(slots=True)
class GridSpec:
    crs: str
    width: int
    height: int
    transform: tuple[float, ...]
    resolution: float | tuple[float, float]
```

## 11.4 深度模型

### `DepthSpec`

```python
@dataclass(slots=True)
class DepthSpec:
    top_cm: float
    bottom_cm: float
```

## 12. 产品模型设计

## 12.1 `RasterProduct`

### 字段

当前代码中的 `RasterProduct` 实现字段为：

- `name`
- `uri`
- `variable`
- `metadata`

## 12.2 `TableProduct`

### 字段

当前代码中的 `TableProduct` 实现字段为：

- `name`
- `uri`
- `table_type`
- `metadata`

## 12.3 `ProductRef`

### 作用

统一在 manifest 中引用具体产品。

### 字段

- `name`
- `type`
- `uri`
- `variable`
- `tags`

## 13. runner 层详细设计

## 13.1 统一入口函数

建议唯一主入口如下：

```python
def run_job(
    request: JobRequest,
    scheduler_adapter: SchedulerAdapter,
    datasource_adapter: DataSourceAdapter,
    logger_adapter: LoggerAdapter,
    product_sink: ProductSink | None = None,
) -> JobResult:
    ...
```

当前实现中，如果未显式传入 `product_sink`，`run_job()` 会自动回退到本地 `LocalProductSink` 写出 manifest。

## 13.2 `dispatch.py`

### 职责

1. 复制并规范化 `JobRequest`
2. 在 `workflow_definition / workflow_name / module_name / pipeline_name` 之间选择执行路径
3. 创建运行上下文
4. 驱动 workflow 或兼容 pipeline 执行

## 13.3 `registry.py`

### 职责

维护 `pipeline_name -> Pipeline` 的注册表。

### 原型

```python
PIPELINE_REGISTRY: dict[str, type[BasePipeline]]
```

## 13.4 `runtime.py`

### 职责

构建：

1. `RuntimeContext`
2. 临时目录
3. 缓存目录
4. 运行 ID

## 14. pipeline 层详细设计

## 14.1 基类设计

建议定义基类 `BasePipeline`：

```python
class BasePipeline(ABC):
    name: str

    @abstractmethod
    def plan(self, request: JobRequest, ctx: RuntimeContext) -> PipelinePlan:
        ...

    @abstractmethod
    def execute(self, request: JobRequest, ctx: RuntimeContext) -> ProductManifest:
        ...
```

## 14.2 为什么需要 `plan()`

`plan()` 用来显式声明：

1. 需要哪些数据集。
2. 需要哪些变量。
3. 是否需要缓存。
4. 是否可以并行。
5. 输出哪些产品。

这样后续如果平台想做任务预估、资源预判、或干跑演练，也更方便。

## 14.3 `PipelinePlan`

### 字段

- `required_datasets`
- `required_variables`
- `estimated_outputs`
- `parallelizable`
- `chunk_strategy`
- `cache_requirement`

## 15. ingest 层详细设计

## 15.1 总体职责

`ingest` 层只负责：

1. 打开文件。
2. 提取变量。
3. 读取元数据。
4. 建立原始对象。

它不负责：

1. 投影统一。
2. 时间轴统一。
3. 结果标准输出。

## 15.2 模块划分

### `ingest.ndvi`

负责：

1. 读取 `VNP13C1`
2. 读取 `MYD13C1`
3. 提取 `NDVI/QA/角度/辅助层`

### `ingest.smap`

负责：

1. 读取 `SPL3SMP_E`
2. 提取 `TBh/TBv/Ts/VWC/IA/SM/VOD`

### `ingest.fy3`

负责：

1. 读取 FY 轨道 HDF
2. 提取亮温、角度、经纬度
3. 组织升轨降轨元信息

### `ingest.station`

负责：

1. 读取 ISMN
2. 读取中国站点 txt/csv
3. 解析时间、深度、站点元数据

## 16. standardize 层详细设计

## 16.1 作用

`standardize` 是整个迁移的关键层。  
它负责把当前 MATLAB 中隐式完成的标准化工作，变成显式、可复用的处理模块。

## 16.2 子模块职责

### `standardize.raster`

负责：

1. 重投影
2. 重采样
3. NoData 处理
4. 窗口裁剪
5. 网格对齐

### `standardize.timeseries`

负责：

1. 时间对齐
2. 时间补全
3. 重采样
4. 聚合

### `standardize.ndvi`

负责：

1. QA 过滤
2. 缩放因子处理
3. 日尺度插值前准备

### `standardize.tb`

负责：

1. FY 条带到日产品组织
2. 通道命名统一
3. 日尺度标准网格写出

### `standardize.station`

负责：

1. 原始站点记录清洗
2. 日均或过境时刻聚合
3. 站点-网格映射

## 17. algorithms 层详细设计

## 17.1 设计原则

算法层必须尽量做到：

1. 输入明确。
2. 输出明确。
3. 与文件系统无关。
4. 可单元测试。
5. 可局部高性能优化。

## 17.2 `algorithms.ndvi`

建议包含：

- `qa_mask_ndvi()`
- `interpolate_to_daily()`
- `build_ndvi_climatology()`
- `compute_ndvi_anomaly()`

## 17.3 `algorithms.physics`

建议包含：

- `compute_tau()`
- `compute_vwc()`
- `compute_fresnel()`
- `compute_mironov_dielectric()`

## 17.4 `algorithms.inversion`

建议包含：

- `retrieve_dynamic_h()`
- `run_ddca()`
- `retrieve_sm_vod()`
- `build_omega_daily()`
- `build_omega_doy_avg()`

## 17.5 `algorithms.metrics`

建议包含：

- `rmse()`
- `bias()`
- `ubrmse()`
- `correlation()`
- `dtw_distance()`

## 18. publish 层详细设计

## 18.1 输出目标

面向 WebGIS，推荐输出四类文件：

1. 栅格图层
2. 表格产品
3. 质量控制产品
4. manifest 与元数据

## 18.2 命名规范

统一命名建议：

```text
{product_family}__{variable}__{source}__{time_key}__{region_key}__v{version}.{ext}
```

例如：

```text
inversion__sm__fy3d__20250701__china__v1.tif
validation__station_match__ismn__20150101_20211231__global__v1.parquet
```

## 18.3 manifest 内容

建议 `manifest.json` 至少包含：

1. 作业信息
2. 运行时间
3. 输入来源
4. 输出产品列表
5. 质量控制产品
6. 参数快照

## 19. storage 层详细设计

## 19.1 路径策略

建议采用统一路径策略：

```text
workspace/
  cache/
    {dataset}/
  intermediate/
    {run_id}/
  products/
    {product_family}/
      {year}/
  manifests/
    {run_id}.json
  logs/
    {run_id}.jsonl
```

## 19.2 缓存策略

### 建议的缓存级别

1. `none`
2. `metadata_only`
3. `partial`
4. `full`

### 缓存键建议

缓存键应至少包含：

- `dataset_name`
- `variables`
- `time_range`
- `spatial_filter`
- `target_grid`

## 20. A/B/C/D 到 pipeline 的映射设计

## 20.1 A 模块映射

### 现有功能

1. VIIRS/MODIS NDVI 原始数据提取
2. 重投影与升尺度
3. 日尺度插值
4. 与气候态对比

### 当前推荐入口

- `module_name=ndvi_daily`
- `ndvi_products` 作为当前实现文件名

说明：

当前代码已落地的是原生模块 `ndvi_daily`，旧 `ndvi_daily_pipeline` 仅保留兼容意义。  
`ndvi_climatology_pipeline` 和 `ndvi_anomaly_pipeline` 仍属于后续扩展位，而不是当前默认入口。

### 输入

- `VNP13C1`
- `MYD13C1`

### 输出

- `ndvi_daily`
- `ndvi_climatology`
- `ndvi_anomaly`
- `ndvi_valid_count`

## 20.2 B 模块映射

### 现有功能

1. SMAP 日产品变量提取
2. FY 条带组织成日产品

### 当前推荐入口

- `module_name=smap_daily`
- `module_name=fy_daily`

说明：

当前代码已落地的是原生模块 `smap_daily` 与 `fy_daily`。  
其中 `fy_daily` 当前支持两种契约模式：

1. `plan_only`：输出 job plan 与 command plan
2. `data_products`：在命令执行完成且最终多波段 TIF 存在时，进一步登记 `fy_daily_tif`，并解包生成 `TBv/TBh/IA` 的 `fy_daily_mat`

`tb_comparison_pipeline` 仍是设计位，尚未进入注册表。

### 输出

- `tbv_daily`
- `tbh_daily`
- `ts_daily`
- `ia_daily`
- `smap_sm_daily`
- `smap_vod_daily`

## 20.3 C 模块映射

### 现有功能

1. ISMN 原始记录解析
2. 中国站点数据整理
3. 点到网格映射

### 当前推荐入口

- `module_name=station_daily`

说明：

当前代码已落地的是原生模块 `station_daily`。  
当前它除了站点级 `daily/am6` 聚合外，还能按需写出 `site/grid/network` 验证 MAT，用于承接 MATLAB `C2/C4` 中的站点到 SMAP 网格、以及网络层聚合逻辑。  
后续若验证链继续扩展，可以再拆成独立验证模块或 workflow。

### 输出

- `station_daily_mat`
- `station_am6_mat`
- `station_site_validation_mat`
- `station_grid_validation_mat`
- `station_net_validation_mat`

## 20.4 D 模块映射

### 现有功能

1. 消费日产品
2. 执行块级反演
3. 输出 SM/VOD/OMEGA/QC
4. 多年平均 omega 构建

### 当前推荐入口

- `module_name=inversion_daily`
- `module_name=daily_bundle`
- `module_name=timeseries_bundle`
- `module_name=block_inversion`
- `module_name=omega_block`
- `workflow_name=retrieval_workflow`

说明：

当前 D 模块已经从“单一 inversion pipeline”演化为一组可组合模块与工作流：

1. `daily_bundle` 负责逐日装配
2. `timeseries_bundle` 负责时序矩阵装配
3. `block_inversion` 负责 `dh/ddca`
4. `omega_block` 负责 OMEGA block 求解
5. `retrieval_workflow`
   - 负责 `timeseries bundle -> inversion/omega` 的整链编排

`omega_avg_pipeline` 与更完整的回代产线仍属于后续阶段。

### 输出

- `daily_bundle_mat`
- `timeseries_bundle_mat`
- `dh_block_mat`
- `sm_vod_block_mat`
- `omega_block_mat`
- `dh_daily_mat`
- `sm_daily_mat`
- `vod_daily_mat`
- `omega_daily_mat`

说明：

这里既包含中间 bundle / block 级兼容产物，也包含按日拆分的反演结果。
真正面向 WebGIS 发布层的 `sm_daily/vod_daily/omega_daily/qc_daily` 仍应作为下一阶段发布适配的目标接口，而不是和当前 `.mat` 兼容产物混为一层。

## 21. 任务执行时序设计

## 21.1 典型时序：SMAP 日产品

```text
调度器 -> run_job()
run_job -> 校验 JobRequest
run_job -> logger.emit_stage_start(validate_request)
run_job -> 自动包装 module_name=smap_daily
smap_daily module -> datasource.resolve(DataRequest)
datasource -> 返回 DataBundle
smap_daily module -> ingest.smap
smap_daily module -> standardize.tb
smap_daily module -> publish.write_raster()
smap_daily module -> publish.write_manifest()
run_job -> 返回 JobResult
```

## 21.2 典型时序：反演任务

```text
调度器 -> run_job()
run_job -> pipeline.plan()
run_job -> DataSourceAdapter.discover/resolve/acquire/materialize
run_job -> workflow preset: retrieval_workflow
retrieval_workflow -> timeseries_bundle
retrieval_workflow -> 根据 mode 选择 block_inversion 或 omega_block
omega_block/block_inversion -> 算法层块级计算
module -> 产出 SM/VOD/OMEGA/QC 及诊断 MAT
module -> 记录产物与日志
run_job -> 返回 JobResult
```

## 22. 错误模型设计

## 22.1 错误分类

建议统一错误类型：

1. `RequestValidationError`
2. `DataDiscoveryError`
3. `DataAcquireError`
4. `StandardizationError`
5. `AlgorithmExecutionError`
6. `ProductPublishError`

## 22.2 错误处理原则

1. 错误必须带阶段信息。
2. 错误必须带简明摘要。
3. 错误必须能被日志接口结构化发出。
4. 能部分成功的任务允许 `partial_success`。

## 23. 性能设计

## 23.1 性能分层

### I/O 优化

1. 按窗口读取栅格
2. 按变量读取 HDF5
3. 按时间段读取时序

### 计算优化

1. `numpy` 向量化
2. `numba` JIT
3. 分块计算
4. 可控并行

### 缓存优化

1. 缓存静态场
2. 缓存气候态
3. 缓存标准化日产品

## 23.2 并行模型

建议内部只做“受控并行”，不自行做复杂分布式调度。

推荐两级并行：

1. pipeline 内块级并行
2. 数值计算核局部并行

而更高层的集群分配交给外部调度系统。

## 23.3 资源提示模型

`ResourceHint` 建议字段：

- `cpu_cores`
- `memory_gb`
- `gpu_count`
- `tmp_disk_gb`
- `preferred_chunk_size`

说明：

这是建议值，不是硬调度。

## 24. 配置设计

## 24.1 配置层次

建议分四级：

1. 数据集配置
2. 运行时配置
3. 产品配置
4. 算法参数配置

## 24.2 配置文件形式

建议使用 `yaml`。

示例：

```yaml
job_id: job-20250701-001
workflow_name: retrieval_workflow
task_type: inversion_run
time_range:
  start: 2025-01-01
  end: 2025-12-31
region:
  kind: bbox
  value:
    xmin: 73
    ymin: 18
    xmax: 135
    ymax: 54
datasource_selection:
  tb_source: FY3D
  ndvi_source: VNP13C1
  sm_source: SMAP
algorithm_params:
  mode: omega
  temp_scheme: DUAL
  block_days: 8
  use_gldas_template: true
  save_match_info: true
  exp_mode: Exp2
  lambda_list: 1,10,100,1000
  tbv_aliases: TBv,tbv
  smap_sm_aliases: sm_dca,SM,sm
  gldas_tc_aliases: Ts_gldas,TC
  tbv_mat_aliases: TBv_mat
  smref_mat_aliases: SMref_mat
output_spec:
  raster_format: COG
  table_format: parquet
  include_qc: true
  include_manifest: true
```

## 24.3 字段映射与 Shape 契约

当前代码已经正式支持“字段别名配置 + 默认字段回退”。

字段配置入口包括：

1. `build_daily_bundle_config()`：控制原始日 MAT、静态场、GLDAS/template 字段名
2. `build_omega_field_config()`：控制 `timeseries bundle` 与外部 MAT 的字段名
3. `build_block_field_config()`：控制 `block_inversion` 输入字段名

同时，当前算法链已经统一 shape 契约：

1. 时序输入使用 `(nt, npix)`
2. 静态输入使用 `(npix,)`
3. 标量、1D 与 `(1, npix)` 会自动广播到目标 shape

详细字段名和 shape 约定请以 [field_mapping_contract.md](file:///d:/Workspace/mat2py/docs/field_mapping_contract.md) 为准。

## 25. 测试设计

## 25.1 测试层次

建议四层测试：

1. 契约测试
2. 算法单元测试
3. pipeline 集成测试
4. 小样本回归测试

## 25.2 契约测试

验证：

1. `JobRequest` 序列化
2. `DataBundle` 状态转换
3. `ProductManifest` 输出结构

## 25.3 算法测试

验证：

1. NDVI 插值
2. Tau 计算
3. 反演函数输出范围

## 25.4 回归测试

使用小范围样本：

1. 对比 MATLAB 输出
2. 验证数值误差容忍范围

## 26. 迁移实施顺序

## 26.1 第一阶段：骨架与契约

先完成：

1. `contracts/`
2. `interfaces/`
3. `runner/`
4. `README.md / pyproject.toml / requirements.txt`

## 26.2 第二阶段：标准化产品

优先完成：

1. `module_name=smap_daily`
2. `module_name=ndvi_daily`
3. `module_name=fy_daily`

原因：

这些模块输入输出清晰，且能为后续反演铺路。

## 26.3 第三阶段：站点产品

完成：

1. `module_name=station_daily`
2. 站点验证相关算法与表产品

## 26.4 第四阶段：反演核心

完成：

1. `algorithms.physics`
2. `algorithms.inversion`
3. `module_name=daily_bundle`
4. `module_name=timeseries_bundle`
5. `module_name=block_inversion`
6. `module_name=omega_block`
7. `workflow_name=retrieval_workflow`

## 26.5 第五阶段：完善产品层

完成：

1. `manifest`
2. `qc`
3. 区域统计表
4. 时间序列产品

## 27. 最小可行版本定义

建议第一个可交付版本只包含：

1. 统一 `run_job()` 入口
2. `DataSourceAdapter` 基础版
3. `LoggerAdapter` 基础版
4. `ProductSink` 本地文件版
5. `module_name=smap_daily`
6. `module_name=ndvi_daily`

只要这六项落地，就已经建立了整个系统的骨架。

## 28. 后续扩展位

为后续扩展保留以下位置：

1. 新数据源扩展
2. 新产品扩展
3. 新日志后端扩展
4. 新存储后端扩展
5. 新区域裁剪方式扩展
6. 新并行策略扩展

## 29. 最终结论

这套详细设计的核心不是“给现有脚本套一层壳”，而是：

1. 用统一契约把任务、数据、日志、产品都标准化。
2. 用统一 runner 把所有任务入口统一化。
3. 用 pipeline 把 A/B/C/D 四类业务组织起来。
4. 用算法层保证高性能计算核心独立。
5. 用产品层保证结果可被 WebGIS 稳定消费。

如果后续严格按照本文档来搭骨架，那么你的 Python 化工作会具备三个非常重要的特征：

1. 不是一次性翻译，而是可持续维护的工程迁移。
2. 不是只适合科研手工运行，而是适合被调度系统长期调用。
3. 不是只输出单个结果文件，而是天然支持多图层、多时间序列、多参数产品。
