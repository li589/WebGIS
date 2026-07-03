# 模块化工作流扩展设计

## 1. 文档定位

本文档是对当前 `Python` 计算包的一次扩展设计。

它不替代现有的：

- [blueprint_report.md](file:///d:/Workspace/mat2py/docs/blueprint_report.md)
- [detailed_design.md](file:///d:/Workspace/mat2py/docs/detailed_design.md)
- [field_mapping_contract.md](file:///d:/Workspace/mat2py/docs/field_mapping_contract.md)

而是在这些文档之上，专门回答一个新问题：

**如何把当前“统一 pipeline 执行器”扩展成一个支持丰富输入参数、广泛数据格式、节点化组合和中间产物复用的模块化工作流处理器。**

这里所说的“像 ComfyUI 一样”，重点不在可视化界面，而在于：

1. 节点是一等公民。
2. 节点之间通过端口连接。
3. 每个节点都有明确的输入、输出和参数 schema。
4. 中间结果可以被复用、缓存、回放和替换。
5. 同一个科学流程既可以作为整条 workflow 执行，也可以拆成多个可组合子节点。

## 2. 现状判断

当前架构的强项是：

1. 已经有统一入口 `run_job()`。
2. 已经有统一请求对象 `JobRequest`。
3. 已经有 pipeline 注册表。
4. 已经有 `plan -> prepare -> execute -> write_manifest` 的主执行链。
5. 已经有较成熟的字段别名映射、shape 适配和 MAT 兼容层。

当前架构的短板是：

1. pipeline 粒度偏粗，执行模型仍是线性的“单 pipeline”。
2. 参数主要靠 `datasource_selection` 和 `algorithm_params` 两个自由字典透传。
3. 节点之间没有端口契约，也没有图结构。
4. 预取结果 `_prepared_bundles` 只是注入到请求对象中，不是正式的中间产物系统。
5. `parallelizable`、`chunk_strategy` 还只是描述信息，没有升级成真正的节点调度语义。
6. 格式支持仍偏“按模块定制解析”，没有统一的格式适配器层。

因此，下一阶段不应该推翻现有 `pipeline` 模式，而应该做一件更稳妥的事：

**把现有 `pipeline` 收缩为兼容层，并把系统最终收敛为“`module + workflow`”两层抽象。**

## 3. 设计目标

### 3.1 核心目标

工作流扩展需要满足以下目标：

1. 支持单数据集、时间范围、参数表、静态辅助场、上游中间结果等多种输入形态。
2. 支持 `MAT/HDF5/TIF/NetCDF/CSV/Parquet/JSON` 等常见科研与平台数据格式。
3. 支持节点级参数 schema、默认值、类型检查和输入校验。
4. 支持工作流图定义，而不是只靠一个 `pipeline_name`。
5. 支持节点级缓存、失败恢复、节点重跑和中间结果替换。
6. 支持把现有 pipeline 作为“复合节点”平滑接入，而不是重写全部代码。

### 3.2 非目标

以下内容不在本阶段设计范围内：

1. 可视化拖拽前端界面。
2. 完整的分布式图执行引擎。
3. 多租户权限和用户协作系统。
4. 跨集群资源编排。
5. 所有旧 pipeline 一次性完全节点化。

### 3.3 成功标准

成功标准不是“把概念图画出来”，而是：

1. 可以定义一个结构化 workflow，并在运行前组装为 `WorkflowDefinition`。
2. 可以把一个 workflow 编译成节点执行计划。
3. 节点输入输出有明确 schema。
4. 现有 pipeline 至少可以以复合节点形式挂入 workflow。
5. 节点输出可以以 artifact 的形式被下游节点消费。

## 4. 总体架构

建议把执行架构拆成三层：

### 4.1 最终抽象

最终系统只保留两层核心抽象：

- `Module`
- `Workflow`

其中单模块执行等价于只有一个节点的 workflow；复杂任务则由多个 module 节点组成。
统一入口可以接受完整 `workflow_definition`，也可以接受 `module_name` 作为单节点 workflow 的简写。
当前实现里，`workflow_definition` 已支持 `WorkflowDefinition` 实例、JSON-compatible `dict` 和 JSON 字符串三种输入形态；运行前会统一适配为 `WorkflowDefinition`。

### 4.2 兼容层

兼容层保留当前实现：

- `run_job()`
- `BasePipeline`
- `PipelinePlan`
- `ProductManifest`
- `datasource_selection`
- `algorithm_params`

这一层保证现有调用方和既有脚本不被破坏。

这一层不是最终目标本身，而是迁移阶段的兼容外壳。

### 4.3 工作流层

工作流层新增以下对象：

- `WorkflowDefinition`
- `WorkflowNodeSpec`
- `PortSpec`
- `ArtifactRef`
- `WorkflowPlan`
- `NodeExecutionContext`
- `WorkflowRunner`

这一层负责：

1. 工作流定义解析。
2. 节点拓扑排序。
3. 节点间输入输出绑定。
4. 节点级缓存和状态记录。
5. 复合节点与旧 pipeline 的兼容桥接。

除普通 `input:*` 绑定外，工作流还应允许绑定请求级上下文，例如 `datasource_selection`、`algorithm_params` 和 `output_spec.extra`，从而让“单模块 workflow”不需要额外样板节点也能直接消费统一入口传入的配置。

### 4.4 模块层

模块层是最终的科学执行单元，负责：

1. 暴露输入端口、输出端口和默认参数。
2. 接收 workflow 节点调度。
3. 产出可复用 artifact 或最终产品。
4. 兼容“细粒度功能模块”和“整数据集处理模块”两种粒度。

迁移期允许通过 `PipelineBackedModule` 包装旧 pipeline，但长期目标是让 `pipelines/` 逐步退化并移除。

### 4.5 适配层

适配层把“文件/目录/表/中间结果”统一抽象成可消费数据源：

- `InputSource`
- `FormatReader`
- `Selector`
- `FieldMapper`
- `ArtifactStore`

这一层负责：

1. 支持多格式输入。
2. 支持时间范围和变量选择。
3. 支持字段映射和 schema 归一化。
4. 支持节点输出被注册为中间 artifact。

## 5. 核心对象设计

### 5.1 `WorkflowDefinition`

用于描述整个工作流。

建议字段：

```python
@dataclass(slots=True)
class WorkflowDefinition:
    workflow_id: str
    version: str
    name: str
    description: str | None
    inputs: dict[str, "InputBinding"]
    nodes: list["WorkflowNodeSpec"]
    edges: list["WorkflowEdge"]
    outputs: list["WorkflowOutputSpec"]
    defaults: dict[str, object]
    metadata: dict[str, object]
```

职责：

1. 描述节点集合。
2. 描述边和输出节点。
3. 描述工作流级默认参数。
4. 作为序列化和持久化单位。

### 5.2 `WorkflowNodeSpec`

用于描述单个节点的静态定义。

```python
@dataclass(slots=True)
class WorkflowNodeSpec:
    node_id: str
    node_type: str
    version: str
    label: str | None
    input_bindings: dict[str, "PortBinding"]
    params: dict[str, object]
    cache_policy: dict[str, object] | None = None
    retry_policy: dict[str, object] | None = None
    enabled: bool = True
```

职责：

1. 指定节点类型。
2. 定义输入端口如何绑定。
3. 定义节点私有参数。
4. 支持节点级缓存和重试策略。

### 5.3 `PortSpec`

端口是工作流可组合性的关键。

```python
@dataclass(slots=True)
class PortSpec:
    name: str
    kind: str
    data_class: str
    required: bool = True
    multi_input: bool = False
    description: str | None = None
    shape_hint: str | None = None
    format_hint: list[str] | None = None
```

建议 `kind` 至少支持：

- `artifact`
- `scalar`
- `table`
- `raster`
- `timeseries`
- `config`

建议 `data_class` 至少支持：

- `mat_dataset`
- `raster_series`
- `table_frame`
- `static_bundle`
- `timeseries_bundle`
- `retrieval_block`
- `manifest`

### 5.4 `ArtifactRef`

用于统一描述节点输出和可复用中间结果。

```python
@dataclass(slots=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    format: str
    uri: str | None
    producer_node_id: str
    schema_name: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
```

它与当前 `ProductRef` 的区别是：

1. `ProductRef` 面向最终产品交付。
2. `ArtifactRef` 面向工作流内部复用和节点间传递。

### 5.5 `NodeExecutor`

每种节点类型都应由一个执行器负责。

```python
class NodeExecutor(Protocol):
    def get_input_ports(self) -> list[PortSpec]: ...
    def get_output_ports(self) -> list[PortSpec]: ...
    def get_param_schema(self) -> type[BaseModel]: ...
    def execute(self, inputs: dict[str, object], params: BaseModel, ctx: NodeExecutionContext) -> dict[str, ArtifactRef | object]: ...
```

这样可以把：

- 输入校验
- 参数校验
- 执行逻辑
- 输出注册

统一收口到节点级接口。

### 5.6 `WorkflowRunner`

`WorkflowRunner` 是图执行器的核心。

建议职责：

1. 校验 workflow 定义。
2. 做节点拓扑排序。
3. 为每个节点构建 `NodeExecutionContext`。
4. 解析输入 binding。
5. 调用对应 `NodeExecutor`。
6. 把输出写入 `ArtifactStore`。
7. 汇总成最终 `ProductManifest` 或 `WorkflowResult`。

## 6. 输入 schema 设计

### 6.1 当前问题

现在的输入主要靠：

- `datasource_selection`
- `algorithm_params`

这两类自由字典。

优点是灵活。
缺点是：

1. 参数缺少集中校验。
2. 键名不统一。
3. 不利于节点复用。
4. 不利于工作流可视化配置。

### 6.2 建议的 `InputSourceSpec`

建议引入统一输入描述：

```python
@dataclass(slots=True)
class InputSourceSpec:
    source_type: str
    format: str
    path: str | None = None
    pattern: str | None = None
    field_map: dict[str, list[str]] = field(default_factory=dict)
    selector: dict[str, object] = field(default_factory=dict)
    options: dict[str, object] = field(default_factory=dict)
```

建议 `source_type` 至少支持：

- `local_file`
- `local_dir`
- `glob`
- `mat_dataset`
- `raster_series`
- `table`
- `static_bundle`
- `upstream_artifact`

建议 `format` 至少支持：

- `mat`
- `hdf5`
- `tif`
- `netcdf`
- `csv`
- `parquet`
- `json`
- `zarr`

### 6.3 选择器 `selector`

`selector` 用于表达“不是整份文件都读进来”。

建议支持：

```python
{
    "time_range": {"start": "2020-01-01", "end": "2020-12-31"},
    "variables": ["TBv", "TBh", "Ts"],
    "bands": [1, 2, 3],
    "date_pattern": "YYYYMMDD",
    "pixel_subset": {"type": "lin_pix", "path": "subset.csv"},
    "region": {"kind": "bbox", "value": {...}}
}
```

### 6.4 字段映射扩展

当前已有较成熟的字段别名机制，应当保留并外扩。

下一阶段建议把字段映射从“MAT 变量别名”扩展为四层：

1. 文件发现映射  
   例如：文件名日期模式、文件分层规则、升降轨命名规则。
2. 容器读取映射  
   例如：HDF5 group 路径、NetCDF 变量名、CSV 列名。
3. 领域字段映射  
   例如：`TBv/TBh/Ts/NDVI/SM_ref/LC`。
4. shape 契约映射  
   例如：`(row, col, time)`、`(time, pixel)`、`(pixel,)` 的归一化。

## 7. 节点类型分层

建议工作流节点至少分成五类。

### 7.1 Source Nodes

负责接入原始数据。

示例：

- `source.dataset`
- `source.time_range`
- `source.parameter_table`
- `source.static_bundle`
- `source.manifest`

### 7.2 Normalize Nodes

负责把输入转成标准结构。

示例：

- `normalize.field_map`
- `normalize.date_filter`
- `normalize.shape_cast`
- `normalize.match_timeseries`
- `normalize.pixel_subset`

### 7.3 Science Nodes

负责具体科学计算。

示例：

- `science.smap_daily`
- `science.ndvi_daily`
- `science.fy_daily`
- `science.station_validate`
- `science.daily_bundle`
- `science.timeseries_bundle`
- `science.block_inversion`
- `science.omega`

### 7.4 Control Nodes

负责图内控制逻辑。

示例：

- `control.switch`
- `control.merge`
- `control.foreach`
- `control.param_scan`
- `control.subworkflow`

### 7.5 Sink Nodes

负责最终写出或注册结果。

示例：

- `sink.write_mat`
- `sink.write_cog`
- `sink.write_parquet`
- `sink.publish_manifest`
- `sink.register_product`

## 8. 与现有 pipeline 的兼容策略

### 8.1 原则

现有 pipeline 不废弃，而是转成两种角色：

1. 保持原状，继续作为 `run_job()` 的直接执行单元。
2. 作为 workflow 中的“复合节点”被包装调用。

### 8.2 复合节点桥接

建议新增一个桥接执行器，例如：

```python
class PipelineBridgeNodeExecutor(NodeExecutor):
    pipeline_name: str
```

它的职责是：

1. 把节点输入映射回 `JobRequest.datasource_selection`
2. 把节点参数映射回 `JobRequest.algorithm_params`
3. 调用现有 pipeline 的 `plan/execute`
4. 把 `ProductManifest` 和中间输出包装成 `ArtifactRef`

这样可以先快速把这些 pipeline 节点化：

- `smap_daily_pipeline`
- `ndvi_daily_pipeline`
- `fy_daily_pipeline`
- `daily_bundle_pipeline`
- `timeseries_bundle_pipeline`
- `retrieval_workflow_pipeline`（兼容名，可桥接到 `retrieval_workflow` preset）

### 8.3 `run_job()` 双模式

建议把 `run_job()` 未来扩成双模式入口：

1. `pipeline mode`
2. `workflow mode`

示意：

```python
if request.workflow_definition is not None:
    return run_workflow_job(...)
return run_pipeline_job(...)
```

这样可以保留旧调用方完全不变。

## 9. 中间产物系统

### 9.1 当前问题

当前中间结果主要有两类：

1. 各 pipeline 自己落到本地目录的 MAT/TIF 文件。
2. `run_job()` 注入的 `_prepared_bundles`。

这两者都不够正式，也不利于节点图复用。

### 9.2 建议的 `ArtifactStore`

建议新增中间产物仓库接口：

```python
class ArtifactStore(Protocol):
    def put(self, artifact: ArtifactRef, payload: object | None = None) -> ArtifactRef: ...
    def get(self, artifact_id: str) -> ArtifactRef: ...
    def load(self, artifact_id: str) -> object: ...
    def exists(self, fingerprint: str) -> bool: ...
```

建议第一阶段先支持：

1. 文件路径型 artifact
2. MAT/TIF/CSV/JSON/Parquet 的轻量装载
3. 基于 fingerprint 的节点缓存命中

### 9.3 cache key

节点缓存键建议由以下内容组成：

1. `node_type`
2. `node_version`
3. 输入 artifact 指纹
4. 参数 schema 的归一化结果
5. 关键环境信息

## 10. 节点级状态与日志

当前日志与状态更多是 job/pipeline 级。

工作流层需要新增节点级观测：

1. `pending`
2. `ready`
3. `running`
4. `cached`
5. `success`
6. `failed`
7. `skipped`

建议新增 `NodeEvent`：

```python
@dataclass(slots=True)
class NodeEvent:
    workflow_id: str
    run_id: str
    node_id: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    message: str | None
    extra: dict[str, object]
```

这会直接改善：

1. 调试能力
2. 前端可视化能力
3. 失败恢复能力
4. 节点重跑能力

## 11. 第一版目录草案

建议在 `Python/` 下新增：

```text
workflow/
  __init__.py
  graph.py
  schemas.py
  registry.py
  executor.py
  artifact_store.py
  bridge.py
  nodes/
    __init__.py
    source_nodes.py
    normalize_nodes.py
    science_nodes.py
    control_nodes.py
    sink_nodes.py
```

职责建议如下：

- `graph.py`
  - `WorkflowDefinition`
  - `WorkflowNodeSpec`
  - `WorkflowEdge`
  - `WorkflowOutputSpec`
- `schemas.py`
  - `InputSourceSpec`
  - `PortSpec`
  - `ArtifactRef`
  - 参数 schema 基类
- `registry.py`
  - `NodeExecutor` 注册表
- `executor.py`
  - `WorkflowRunner`
  - `WorkflowPlan`
- `artifact_store.py`
  - 中间结果仓库
- `bridge.py`
  - 现有 pipeline 与 workflow 节点的桥接

## 12. 示例 workflow

下面给出一个 OMEGA 检索工作流示意：

```json
{
  "workflow_id": "omega_retrieval_v1",
  "version": "1.0",
  "nodes": [
    {
      "node_id": "daily_bundle",
      "node_type": "module",
      "input_bindings": {
        "datasource_selection": "request:datasource_selection",
        "algorithm_params": "request:algorithm_params",
        "output_spec_extra": "request:output_spec_extra"
      },
      "params": {
        "module_name": "daily_bundle",
        "temp_scheme": "DUAL",
        "tb_source": "FY"
      }
    },
    {
      "node_id": "ts_bundle",
      "node_type": "module",
      "params": {
        "module_name": "timeseries_bundle"
      }
    },
    {
      "node_id": "omega",
      "node_type": "module",
      "input_bindings": {
        "algorithm_params": "request:algorithm_params",
        "output_spec_extra": "request:output_spec_extra"
      },
      "params": {
        "module_name": "omega_block",
        "exp_mode": "Exp2"
      }
    }
  ],
  "edges": [
    {
      "from_node": "daily_bundle",
      "from_port": "output_path",
      "to_node": "ts_bundle",
      "to_port": "input_path"
    },
    {
      "from_node": "ts_bundle",
      "from_port": "output_path",
      "to_node": "omega",
      "to_port": "input_mat"
    }
  ],
  "outputs": [
    {
      "name": "final_manifest",
      "source": "node:omega.manifest"
    }
  ]
}
```

当前实现约束补充：

1. 当前默认支持的节点类型是 `module`，兼容桥接节点类型是 `bridge.pipeline`。
2. `input_bindings` 当前采用 `dict[str, str]`，值使用 `request:*`、`input:*`、`node:*` 三类绑定语法。
3. 端口级连线使用 `edges`，不要再给同一输入端口重复写一份等价 `input_bindings`，否则会触发执行期冲突校验。

## 13. 实施顺序

### 13.1 Phase 1：定义对象，不改算法

先完成：

1. `WorkflowDefinition`
2. `WorkflowNodeSpec`
3. `PortSpec`
4. `ArtifactRef`
5. `WorkflowRunner` 空壳
6. `PipelineBridgeNodeExecutor`

这一阶段不改现有科学代码，只是把工作流层对象立起来。

### 13.2 Phase 2：节点桥接

优先把这些旧入口桥接到模块/工作流体系：

1. `module_name=smap_daily`
2. `module_name=ndvi_daily`
3. `module_name=daily_bundle`
4. `module_name=timeseries_bundle`
5. `workflow_name=retrieval_workflow`

### 13.3 Phase 3：输入 schema 与格式适配器

新增：

1. `InputSourceSpec`
2. `FormatReaderRegistry`
3. `FormatWriterRegistry`
4. `SelectorAdapter`

这一阶段开始摆脱“每个 pipeline 自己读路径”的模式。

### 13.4 Phase 4：节点缓存与状态机

新增：

1. `ArtifactStore`
2. 节点缓存键
3. `NodeEvent`
4. 节点失败重试与恢复

### 13.5 Phase 5：前端联动

在后端语义稳定后，再考虑：

1. workflow JSON 编辑器
2. 可视化节点界面
3. 节点市场或模板库

## 14. 与当前项目的关系

这份设计和当前项目已有约束是一致的：

1. 保留 `Python/` 扁平结构，不引入第二层包根。
2. 保留现有 `run_job()` 统一入口，不破坏已完成的回归测试。
3. 复用现有字段别名映射体系，而不是重写字段契约。
4. 把现有 A/B/C/D pipeline 视作可桥接的科学节点资产。
5. 允许当前 `.mat` 兼容层继续存在，同时把未来的发布层抽象留给 workflow sink。

## 15. 下一步建议

建议下一步按以下顺序推进：

1. 在 `docs/` 中确认本设计文档。
2. 在 `Python/workflow/` 下落第一版数据结构骨架，不接入真实科学逻辑。
3. 先做 `PipelineBridgeNodeExecutor`，把现有 pipeline 作为复合节点跑通。
4. 补一组针对 workflow graph 的最小测试：
   - workflow schema 校验
   - 节点拓扑排序
   - 节点桥接执行
   - artifact 注册与读取

如果要继续执行，实现层的最小切入点不是重写 OMEGA，而是先搭：

1. `workflow/graph.py`
2. `workflow/schemas.py`
3. `workflow/registry.py`
4. `workflow/bridge.py`
5. `workflow/executor.py`
