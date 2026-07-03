# Workflow HTTP/JSON 适配规范

## 1. 文档定位

本文档描述 `workflow_definition` 如何通过 HTTP/JSON 进入 Python 计算包，并在运行时被统一适配为可执行 workflow。

本文档主要面向：

1. 平台后端
2. API 网关
3. 调度系统
4. 前端动态表单生成器

它关注的是**显式 workflow 定义**的 JSON 适配、校验、模板推导和执行路径。

## 2. 适配入口

当前 workflow 适配相关能力主要来自：

```python
from workflow.serialization import coerce_workflow_definition
from workflow.template_inference import infer_workflow_request_template
from workflow.panel_schema import build_workflow_input_panel_schema
from workflow.ui_metadata import build_workflow_input_panel_ui_schema
from workflow.validation import validate_workflow_definition
```

## 3. 输入形态

当前 `workflow_definition` 支持三种 HTTP/JSON 输入形态：

1. JSON object
2. JSON string
3. `null`

推荐平台传入 JSON object；如果上游先做了存储或透传，也可以先存成 JSON string，再由 Python 侧统一解析。

## 4. 标准链路

推荐链路如下：

```text
HTTP body
  -> workflow_definition
  -> coerce_workflow_definition(...)
  -> validate_workflow_definition(...)
  -> infer_workflow_request_template(...)
  -> build_workflow_input_panel_schema(...)
  -> build_workflow_input_panel_ui_schema(...)
  -> run_job(...)
```

## 5. workflow 定义目标

workflow 定义的目标是让平台能够显式描述：

- 节点如何连接
- 节点使用哪些输入
- 哪些输入来自 request
- 哪些输入来自 datasource_selection
- 节点输出如何作为后续节点输入
- 最终结果如何映射为 manifest 或产品

## 6. 推荐结构

当前 workflow 定义应至少表达以下内容：

- workflow 标识
- workflow 名称
- 节点列表
- 节点类型
- 输入绑定
- 输出定义
- workflow 级元数据

## 7. 节点与绑定语义

当前约定中，节点输入绑定支持三类来源：

1. `request:*`
2. `input:*`
3. `node:*`

这意味着：

- `request:*` 表示来自外层请求字段
- `input:*` 表示来自 workflow 外部输入
- `node:*` 表示来自上游节点输出

## 8. 输入模板推导

显式 workflow 的一个核心能力是自动推导最小输入模板。

当前可以通过：

```python
template = infer_workflow_request_template(workflow_definition_payload)
```

推导出：

1. 实际需要哪些 `datasource_selection` 键
2. 哪些 `request:*` 键会被消费
3. 各节点的外部输入依赖

该能力适合用于：

- 前端动态表单
- 后端运行前校验
- 平台任务编辑器

## 9. UI schema 生成

如果平台希望直接渲染动态任务表单，可以使用：

```python
panel_schema = build_workflow_input_panel_schema(workflow_definition_payload)
ui_schema = build_workflow_input_panel_ui_schema(workflow_definition_payload)
```

当前输出分为三部分：

1. `datasource_fields`
2. `algorithm_param_fields`
3. `request_fields`

其中 `ui_schema` 会在此基础上增加：

- 字段标题
- 标签
- 控件类型
- placeholder
- 示例值
- 中文说明

## 10. 校验策略

workflow 校验重点检查：

1. workflow 标识是否完整
2. 节点类型是否合法
3. 输入绑定语法是否合法
4. 节点是否存在重复定义
5. 图中是否存在环路
6. `request:*`、`input:*`、`node:*` 的引用是否指向有效来源
7. 输出节点是否可解析

## 11. 与 JobRequest 的关系

`workflow_definition` 不是替代 `JobRequest`，而是 `JobRequest` 的一个可选字段。

也就是说：

- 任务仍然通过 `JobRequest` 进入平台
- 只是其中可以携带显式 workflow 定义
- `run_job()` 会根据优先级选择执行路径

## 12. 常见错误

常见错误包括：

1. workflow JSON 不是合法对象
2. workflow 缺少必要字段
3. 节点类型未注册
4. 输入绑定写错
5. workflow 中存在循环依赖
6. 输出端口无法解析
7. workflow 校验通过但与外层 `JobRequest` 的入口语义不一致

## 13. 错误处理建议

平台侧建议：

1. JSON 解析错误归类为 `400`
2. workflow 结构或业务校验错误归类为 `422`
3. 这两类错误都应在任务入队前拦截

## 14. 推荐使用场景

显式 workflow 适合以下情况：

1. 平台需要动态生成任务图
2. 一个任务要串多个 module
3. 需要可视化显示输入绑定
4. 需要高级表单和模板推导
5. 需要在同一请求中定义多个执行阶段

## 15. 结论

workflow HTTP/JSON 适配的核心不是“把 JSON 变成对象”，而是让平台可以用统一协议把图、输入、输出和校验全部串起来。这样前端、后端和算法包就可以在同一套 workflow 语义下协作。
