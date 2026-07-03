# Python 计算包详细设计文档

## 1. 文档定位

本文档描述 `Code/algorithms/providers/Python/` 的当前工程化设计，用于说明这个 Python 计算包如何作为平台统一算法执行层接入后端工作流。

它回答的是：

1. Python 计算包如何组织。
2. 对外接口长什么样。
3. 内部模块如何拆分。
4. 数据契约如何定义。
5. 不同模块如何在运行时协作。
6. 现有 MATLAB 迁移代码如何在同一框架下落地。

本文档不设计完整调度系统，也不设计前端页面。它只设计一件事：

**一套可被平台调用的、模块化、可扩展、契约统一的 Python 遥感计算包。**

## 2. 设计目标

### 2.1 核心目标

这一计算包需要满足以下目标：

1. 能承接现有科学计算流程并持续迁移。
2. 能被后端工作流稳定调用。
3. 能统一接入不同数据源和数据格式。
4. 能统一输出结构化产品与 manifest。
5. 能记录结构化日志与状态事件。
6. 能支持多参数任务、多变量输出、多时间尺度产品。

### 2.2 非目标

以下内容不在本文档设计范围内：

1. 前端 API 网关。
2. 平台级调度器本体。
3. 容器编排系统。
4. 用户权限系统。
5. 分布式数据库设计。

### 2.3 成功标准

成功标准不是“某一个脚本能运行”，而是：

1. 任意任务都能通过统一入口启动。
2. 任意任务都能通过统一数据接口取数。
3. 任意任务都能通过统一日志接口汇报状态。
4. 任意任务都能通过统一产品接口交付产物。
5. 原生模块、兼容 pipeline 与 workflow preset 能在同一框架下协作。

## 3. 设计原则

### 3.1 平台无关

Python 计算包不能绑定某一种后端或某一种调度器实现。

### 3.2 接口先行

先定义任务请求对象、数据请求对象、产品对象和日志对象，再写内部逻辑。

### 3.3 算法与 I/O 分离

算法核心尽量不感知：

1. 数据来自本地还是远程。
2. 文件在缓存层还是持久层。
3. 日志发往终端还是平台。

### 3.4 结果优先而不是文件优先

内部模块返回的首先应该是领域对象或产品对象，然后再由产品输出层决定写成什么格式。

### 3.5 兼容迁移流程

前期允许保留 `.mat`、plan、command plan 等兼容产物，但长期目标是统一到标准产品与 manifest。

## 4. 系统边界

### 4.1 外部系统视角

完整平台大致是：

1. 前端提交请求。
2. 平台后端组装工作流。
3. 调度系统安排资源。
4. Python 计算包执行。
5. 平台获取日志和产物。

因此本计算包在架构中的位置是：

```text
前端 -> 平台后端 -> 调度/队列 -> Python 计算包 -> 产品存储/日志回传
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

### 5.1 分层结构

当前实现可以抽象为以下能力层：

```text
interfaces      对外协议层
contracts       请求/响应/产品/事件契约层
runner          统一任务入口层
workflow        工作流定义、执行与序列化层
service         HTTP / 队列 / 平台适配层
data_access     数据源发现、解析、物化与格式适配层
ingest          原始数据接入与 bundle 装配层
algorithms      科学计算核心层
modules         原生算法模块层
publish         产品交付层
storage         缓存/路径/中间结果组织层
pipelines       兼容层
utils           辅助工具层
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

#### `workflow`

承载 workflow 定义、校验、序列化、执行和模板推断。

#### `service`

承载 HTTP、worker、平台适配器、队列与结果封装。

#### `data_access`

负责数据源发现、解析、物化、缓存和格式适配。

#### `ingest`

读取原始文件并提取变量和元信息。

#### `modules`

承载原生算法模块，是当前迁移的主落点。

#### `algorithms`

只做科学计算核心。

#### `publish`

把内部产品写成外部产品，并生成 manifest。

#### `storage`

负责缓存路径、中间文件、命名策略和分块策略。

#### `pipelines`

保留旧 pipeline 的兼容入口，不作为长期主执行面。

## 6. 当前代码结构

当前代码已经统一落在 `Code/algorithms/providers/Python/` 下，不再沿用更早期的二级包结构。

### 当前实际结构

```text
Python/
├─ contracts/
├─ interfaces/
├─ runner/
├─ workflow/
├─ service/
├─ data_access/
├─ modules/
├─ ingest/
├─ algorithms/
├─ pipelines/
├─ publish/
├─ storage/
├─ utils/
├─ tests/
├─ pyproject.toml
├─ requirements.txt
└─ README.md
```

### 当前可调度入口的理解

当前项目中应该把以下入口都视为有效但分层不同的入口：

- `module_name`：当前主推荐入口，表示原生模块
- `workflow_name`：预定义 workflow preset 名称
- `workflow_definition`：显式工作流定义
- `pipeline_name`：兼容入口，仅用于历史 pipeline 兼容

其中，`module_name` 和 `workflow_name` 是当前更推荐的主入口；`pipeline_name` 主要用于历史兼容。

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
  -> 选择 workflow / module / pipeline
  -> 数据准备
  -> datasource 返回 DataBundle
  -> 执行 standardize / algorithms
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

### 8.1 `JobRequest`

#### 作用

描述一次外部请求希望执行什么任务。

#### 必需字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | `str` | 外部作业 ID |
| `pipeline_name` | `str` | 兼容字段；历史 pipeline 入口 |
| `task_type` | `str` | 任务类型 |
| `time_range` | `TimeRange` | 时间范围 |
| `region` | `RegionSpec` | 空间范围 |
| `datasource_selection` | `dict` | 数据源选择配置 |
| `algorithm_params` | `dict` | 计算参数 |
| `output_spec` | `OutputSpec` | 输出要求 |

#### 可选字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `resource_hint` | `ResourceHint` | 资源提示 |
| `cache_policy` | `CachePolicy` | 缓存策略 |
| `resume_policy` | `ResumePolicy` | 断点续跑策略 |
| `priority` | `int` | 优先级提示 |
| `tags` | `dict[str, str]` | 附加标签 |
| `module_name` | `str \| None` | 原生模块入口 |
| `workflow_name` | `str \| None` | 预定义 workflow 名称 |
| `workflow_definition` | `Any \| None` | 显式工作流定义 |

#### Python 原型

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

### 8.2 `JobResult`

#### 作用

作为统一任务执行返回对象。

#### 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | `str` | 原始作业 ID |
| `run_id` | `str` | 实际运行 ID |
| `status` | `str` | `success` / `failed` / `partial_success` |
| `started_at` | `datetime` | 开始时间 |
| `finished_at` | `datetime` | 结束时间 |
| `manifest_uri` | `str` | 产品清单位置 |
| `log_uri` | `str \| None` | 日志位置 |
| `metrics` | `dict` | 执行指标 |
| `error_summary` | `str \| None` | 错误摘要 |

### 8.3 `DataRequest`

描述一次取数请求，包含数据集名、变量、时间范围、空间过滤和缓存策略等字段。

### 8.4 `DataBundle`

表示一次取数后得到的数据集合，不要求一开始就完全物化。

### 8.5 `ProductManifest`

统一描述一次任务产生的所有产品，包含主产品、QC 产品、表格产品与扩展元数据。

### 8.6 `LogEvent`

统一描述日志事件，供平台或日志系统消费。

## 9. 对外接口设计

### 9.1 `SchedulerAdapter`

用于让调度系统向计算包传递运行上下文，并接收状态更新和最终结果。

### 9.2 `DataSourceAdapter`

统一隐藏数据来自本地磁盘、缓存层、远程存储或在线 API 的差异。

当前能力分层建议为：

1. `discover`
2. `resolve`
3. `acquire`
4. `materialize`

### 9.3 `LoggerAdapter`

使日志从“面向终端输出”变成“面向平台事件”。

### 9.4 `ProductSink`

统一产品交付行为，防止输出散乱。

## 10. 领域模型

### 10.1 时间模型

`TimeRange` 表示时间范围。

### 10.2 空间模型

`RegionSpec` 表示全局、bbox、shp/geojson、行政区编码或网格编号集合等空间范围。

### 10.3 网格模型

`GridSpec` 用于描述网格 CRS、宽高、仿射参数和分辨率。

### 10.4 深度模型

`DepthSpec` 用于站点或剖面层次描述。

## 11. 产品模型

### 11.1 `RasterProduct`

字段包括 `name`、`uri`、`variable`、`metadata`。

### 11.2 `TableProduct`

字段包括 `name`、`uri`、`table_type`、`metadata`。

### 11.3 `ProductRef`

用于在 manifest 中统一引用具体产品。

## 12. runner 与 workflow 层

### 12.1 `run_job()`

统一主入口应支持：

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

### 12.2 `dispatch.py`

负责规范化 `JobRequest`，并在 `workflow_definition / workflow_name / module_name / pipeline_name` 之间选择执行路径。

### 12.3 `registry.py`

维护兼容 pipeline 注册表。

### 12.4 `runtime.py`

负责构建运行 ID、临时目录、缓存目录与运行上下文。

### 12.5 `workflow`

负责 workflow schema、校验、序列化、执行与模板推断。

## 13. 数据接入层

### 13.1 `data_access`

`data_access` 负责数据源发现、解析、物化、缓存与格式适配。

### 13.2 `ingest`

`ingest` 负责具体源文件读取和原始变量装配。

### 13.3 `modules`

`modules` 是当前迁移阶段的原生模块承载层。

### 13.4 `pipelines`

`pipelines` 保留兼容入口，不作为长期主执行面。

## 14. 标准处理层

### 14.1 `standardize`

当前代码库已经具备标准化处理的实际能力，但该概念仍主要体现在具体模块与工作流中。建议后续如果继续显式拆分，可再把 raster / timeseries / station 的标准化能力继续独立化。

## 15. 算法层

### 15.1 设计原则

算法层必须尽量做到输入明确、输出明确、与文件系统无关、可单元测试、可局部高性能优化。

### 15.2 `algorithms.ndvi`

建议包含 QA 掩膜、日尺度插值、气候态构建与异常计算。

### 15.3 `algorithms.physics`

建议包含 `tau`、`vwc`、`fresnel` 与介电模型计算。

### 15.4 `algorithms.inversion`

建议包含动态高度、DDCA、SM/VOD 反演与 OMEGA 相关计算。

## 16. 产品输出层

### 16.1 输出目标

面向 WebGIS，推荐输出四类文件：

1. 栅格图层
2. 表格产品
3. 质量控制产品
4. manifest 与元数据

### 16.2 命名规范

建议统一采用：

```text
{product_family}__{variable}__{source}__{time_key}__{region_key}__v{version}.{ext}
```

### 16.3 manifest 内容

建议 `manifest.json` 至少包含：

1. 作业信息
2. 运行时间
3. 输入来源
4. 输出产品列表
5. 质量控制产品
6. 参数快照

## 17. 存储层

### 17.1 路径策略

建议采用统一路径策略：

```text
workspace/
  cache/
  intermediate/
  products/
  manifests/
  logs/
```

### 17.2 缓存策略

建议缓存级别：`none`、`metadata_only`、`partial`、`full`。

## 18. 业务映射

### 18.1 A 模块

NDVI 相关模块，推荐以 `module_name=ndvi_daily` 为主入口。

### 18.2 B 模块

SMAP / FY 相关模块，推荐以 `module_name=smap_daily`、`module_name=fy_daily` 为主入口。

### 18.3 C 模块

站点相关模块，推荐以 `module_name=station_daily` 为主入口。

### 18.4 D 模块

反演与组合 workflow，推荐以 `module_name=daily_bundle`、`module_name=timeseries_bundle`、`module_name=block_inversion`、`module_name=omega_block` 以及 `workflow_name=retrieval_workflow` 为主入口。

## 19. 任务执行时序

### 19.1 SMAP 日产品

```text
调度器 -> run_job()
run_job -> 校验 JobRequest
run_job -> 自动包装 module_name=smap_daily
smap_daily -> datasource.resolve(DataRequest)
datasource -> 返回 DataBundle
smap_daily -> ingest.smap
smap_daily -> 写出产品与 manifest
run_job -> 返回 JobResult
```

### 19.2 反演任务

```text
调度器 -> run_job()
run_job -> pipeline.plan()
run_job -> 数据准备
run_job -> workflow preset: retrieval_workflow
retrieval_workflow -> timeseries_bundle
retrieval_workflow -> block_inversion / omega_block
module -> 产出结果与诊断产物
run_job -> 返回 JobResult
```

## 20. 错误模型

统一错误类型建议包括：

1. `RequestValidationError`
2. `DataDiscoveryError`
3. `DataAcquireError`
4. `StandardizationError`
5. `AlgorithmExecutionError`
6. `ProductPublishError`

错误必须带阶段信息、简明摘要，并能被日志接口结构化发出。允许部分成功任务返回 `partial_success`。

## 21. 性能设计

### 21.1 I/O 优化

按窗口读取栅格、按变量读取 HDF5、按时间段读取时序。

### 21.2 计算优化

使用 `numpy` 向量化、`numba` JIT、分块计算和受控并行。

### 21.3 缓存优化

缓存静态场、缓存气候态、缓存标准化日产品。

## 22. 配置设计

建议使用 `yaml` 配置任务、区域、数据源和算法参数。

字段映射和 shape 契约应以 `field_mapping_contract.md` 为准，避免在多个文档里重复定义。

## 23. 测试设计

建议覆盖：

1. 契约测试
2. 算法单元测试
3. workflow / pipeline 集成测试
4. 小样本回归测试

## 24. 迁移实施顺序

建议优先顺序：

1. 稳定 `contracts` 与 `interfaces`
2. 收敛 `runner` 与 `workflow`
3. 继续补齐 `data_access` 与 `publish`
4. 完善原生 `modules`
5. 逐步收敛 `pipelines`

## 25. 最小可行版本定义

建议第一个稳定版本至少包含：

1. 统一 `run_job()` 入口
2. `DataSourceAdapter` 基础版
3. `LoggerAdapter` 基础版
4. `ProductSink` 本地文件版
5. `module_name=smap_daily`
6. `module_name=ndvi_daily`

## 26. 结论

这套设计的核心不是“给现有脚本套一层壳”，而是：

1. 用统一契约把任务、数据、日志和产品标准化。
2. 用统一 runner 把入口统一化。
3. 用 workflow 和 modules 把业务组织起来。
4. 用算法层保证高性能计算核心独立。
5. 用产品层保证结果可被 WebGIS 稳定消费。

如果后续严格按照本文档继续演进，那么这套 Python 计算包会具备三个重要特征：

1. 可持续维护的工程迁移。
2. 可被调度系统长期调用。
3. 天然支持多图层、多时间序列、多参数产品。
