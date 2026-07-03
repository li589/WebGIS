# Workflow Extension Design

## 1. 文档定位

本文档描述当前 Python 计算包中 workflow 能力的扩展方向，用于解释从“兼容 pipeline”逐步过渡到“模块化 workflow”之后，系统应如何继续演进。

本文档关注三件事：

1. 现有 workflow 体系已经支持什么。
2. 未来 workflow 体系应该往哪里扩展。
3. workflow、module、pipeline 三者之间的边界如何保持清晰。

## 2. 当前状态

当前系统已经具备以下能力：

- `module_name` 入口可自动包装成单节点 workflow
- `workflow_name` 可选择预定义 workflow preset
- `workflow_definition` 可接收显式图定义
- `pipelines` 目录仍作为兼容层存在
- workflow 校验、序列化和模板推断能力已经具备

也就是说，workflow 已经不是概念，而是当前 Python 计算包中的正式执行形态之一。

## 3. 设计目标

### 3.1 核心目标

未来 workflow 扩展的核心目标是：

1. 让更复杂的算法链可以通过显式图来表达。
2. 让输入模板可以自动推导。
3. 让平台可以根据 workflow 自动生成动态表单。
4. 让多模块、多阶段、多输出任务仍然保持统一契约。

### 3.2 非目标

本文档不负责：

1. 平台级调度器设计。
2. 资源分配器设计。
3. 前端页面渲染实现。
4. 数据库与对象存储底座设计。

## 4. 当前 workflow 结构

当前 workflow 设计可分为四层：

```text
workflow.definition   workflow 数据结构
workflow.validation   workflow 校验
workflow.serialization workflow 序列化与反序列化
workflow.executor     workflow 执行
```

配套能力还包括：

- `workflow.template_inference`
- `workflow.panel_schema`
- `workflow.ui_metadata`
- `workflow.bridge`

## 5. 当前支持的工作流形态

### 5.1 单模块 workflow

当任务只需要一个原生模块完成时，`run_job()` 会自动把 `module_name` 包装成单节点 workflow。

### 5.2 预定义 workflow preset

当前典型 preset 是 `retrieval_workflow`，用于把时序装配与反演模块串联起来。

### 5.3 显式 workflow 定义

当平台需要完全自定义节点、边和输入绑定时，可以直接提供 `WorkflowDefinition`。

## 6. 扩展目标

### 6.1 更复杂的图表达

未来 workflow 应支持：

- 多输入节点
- 多输出节点
- 中间产物复用
- 条件分支
- 可选节点
- 图级元数据

### 6.2 更强的输入推断

未来应该让 workflow 自动推断：

- 哪些输入来自 `datasource_selection`
- 哪些输入来自 `algorithm_params`
- 哪些输入来自 `request` 级别字段
- 哪些输入是节点内部可默认值

### 6.3 更好的 UI 适配

workflow 应继续服务于：

- 动态表单生成
- 节点级输入分区
- 参数说明
- 默认值展示
- 字段级校验反馈

## 7. 设计原则

### 7.1 workflow 只描述“如何连接”

workflow 不负责算法本体实现，也不直接承载数据读取逻辑。

### 7.2 module 承载实际执行

真正的计算应落在 `modules` 中。

### 7.3 pipeline 只保留兼容语义

pipeline 不应继续成为主执行面，只保留历史入口和迁移桥接。

## 8. 推荐演进方向

### 8.1 由 preset 走向图模板

当前 `workflow_name` 代表一类预定义 preset。后续可以进一步扩展为：

- 业务模板
- 数据模板
- 算法模板
- UI 模板

### 8.2 由静态图走向半动态图

先从固定节点集合开始，再逐步允许节点参数和输入绑定动态化。

### 8.3 由工作流描述走向执行审计

未来 workflow 不仅要能跑，还要能审计：

- 节点执行顺序
- 输入来源
- 输出来源
- 失败节点
- 重试历史

## 9. 与其他模块的关系

### 9.1 与 `runner`

`runner` 负责统一入口和上下文创建，workflow 只是执行策略的一部分。

### 9.2 与 `contracts`

workflow 必须遵循 `JobRequest`、`JobResult`、`DataBundle` 等契约。

### 9.3 与 `service`

service 层负责把 workflow 暴露给平台 HTTP、队列和 worker。

### 9.4 与 `backend`

后端只负责调用 workflow，不应该在服务层中重复实现图执行逻辑。

## 10. 推荐的落地方向

接下来如果继续扩展 workflow，建议优先做以下几件事：

1. 把更多标准链路沉淀成 preset。
2. 继续增强 template inference。
3. 提高 panel schema 与 UI metadata 的一致性。
4. 让 workflow validation 提供更好的字段级错误反馈。
5. 逐步减少 pipeline 兼容入口的重要性。

## 11. 结论

workflow 是当前 Python 计算包从“脚本驱动”过渡到“工程驱动”的关键层。未来它的核心价值不是替代 module，而是把多个 module 以稳定、可审计、可扩展的方式组织起来。
