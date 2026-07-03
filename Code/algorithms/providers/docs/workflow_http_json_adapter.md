# HTTP/JSON 到 WorkflowDefinition 的适配规范

## 1. 文档定位

本文档补充 [backend_integration_contract.md](file:///d:/Workspace/mat2py/docs/backend_integration_contract.md) 中关于显式工作流的对接说明，专门描述：

1. 平台如何通过 HTTP/JSON 传入 `workflow_definition`
2. Python 侧如何把 JSON payload 反序列化成 `WorkflowDefinition`
3. 校验失败时应该返回什么样的错误语义

## 2. 适配目标

平台侧常见输入链路如下：

```text
HTTP Request
  -> JSON body
  -> Python dict
  -> coerce_workflow_definition(...)
  -> WorkflowDefinition
  -> run_job(...)
```

这里的关键点是：

1. `run_job()` 最终执行的是 `WorkflowDefinition`
2. HTTP 层传入的通常是 JSON object，而不是 Python dataclass
3. 因此需要一个稳定、可复用的反序列化适配层

## 3. Python 侧标准入口

当前标准适配入口位于：

- [serialization.py](file:///d:/Workspace/mat2py/Python/workflow/serialization.py)

核心函数：

```python
from workflow.serialization import (
    coerce_workflow_definition,
    get_workflow_definition_json_schema,
)
```

含义如下：

1. `coerce_workflow_definition(payload)`：把 `WorkflowDefinition` / `dict` / JSON string 统一转成 `WorkflowDefinition`
2. `get_workflow_definition_json_schema()`：返回当前 HTTP/JSON payload 的 JSON schema 描述

## 4. 支持的输入形态

### 4.1 Python 运行时对象

```python
workflow_definition = WorkflowDefinition(...)
```

适用场景：

1. 平台内部已经有 Python 组装层
2. 不经过 HTTP/JSON

### 4.2 JSON object 映射

```python
workflow_definition = {
    "workflow_id": "wf-demo",
    "nodes": [...],
    "outputs": [...],
}
```

适用场景：

1. Web 框架已把 HTTP body 解码为 `dict`
2. 平台希望直接把 JSON payload 传给 `run_job()`

### 4.3 JSON 字符串

```python
workflow_definition = "{\"workflow_id\": \"wf-demo\", \"nodes\": [...], \"outputs\": [...]}"
```

适用场景：

1. CLI 或消息队列场景
2. 平台上游暂时只能传字符串

## 5. JSON 顶层结构

当前支持的 JSON 顶层字段如下：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `workflow_id` | 是 | `string` | 工作流唯一标识 |
| `version` | 否 | `string` | 版本号，默认 `1.0` |
| `name` | 否 | `string \| null` | 展示名称 |
| `description` | 否 | `string \| null` | 工作流说明 |
| `inputs` | 否 | `object` | 工作流输入源声明 |
| `nodes` | 是 | `array` | 节点列表 |
| `edges` | 否 | `array` | 边列表 |
| `outputs` | 是 | `array` | 工作流输出列表 |
| `defaults` | 否 | `object` | 工作流级默认参数 |
| `metadata` | 否 | `object` | 扩展元数据 |

## 6. 子对象结构

### 6.1 `nodes[]`

每个节点当前支持：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `node_id` | 是 | `string` | 节点 ID |
| `node_type` | 是 | `string` | 当前常用 `module`，兼容桥接使用 `bridge.pipeline` |
| `version` | 否 | `string` | 节点版本，默认 `1.0` |
| `label` | 否 | `string \| null` | 展示标签 |
| `input_bindings` | 否 | `object<string, string>` | 输入绑定映射 |
| `params` | 否 | `object` | 节点参数 |
| `cache_policy` | 否 | `object \| null` | 缓存策略 |
| `retry_policy` | 否 | `object \| null` | 重试策略 |
| `enabled` | 否 | `boolean` | 是否启用，默认 `true` |

### 6.2 `edges[]`

每条边当前支持：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `from_node` | 是 | `string` | 来源节点 ID |
| `from_port` | 是 | `string` | 来源端口 |
| `to_node` | 是 | `string` | 目标节点 ID |
| `to_port` | 是 | `string` | 目标端口 |

### 6.3 `outputs[]`

每个输出当前支持：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `name` | 是 | `string` | 输出名称 |
| `source` | 是 | `string` | 绑定来源 |

### 6.4 `inputs`

每个 `inputs.<name>` 当前支持：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `source_type` | 是 | `string` | 输入源类型 |
| `format` | 是 | `string` | 输入格式 |
| `path` | 否 | `string \| null` | 路径 |
| `pattern` | 否 | `string \| null` | 发现模式 |
| `field_map` | 否 | `object<string, string[]>` | 字段别名映射 |
| `selector` | 否 | `object` | 选择器 |
| `options` | 否 | `object` | 其他选项 |

## 7. 绑定语法

`input_bindings` 和 `outputs[].source` 当前只支持三类字符串绑定：

1. `request:*`
2. `input:*`
3. `node:*`

典型示例：

```json
{
  "datasource_selection": "request:datasource_selection",
  "algorithm_params": "request:algorithm_params",
  "input_mat": "node:timeseries_bundle.output_path",
  "omega_fixed_mat": "input:omega_fixed_mat"
}
```

说明：

1. `request:*` 绑定到 `JobRequest` 的请求级对象
2. `input:*` 绑定到 `request.datasource_selection` 中的外部输入
3. `node:*` 绑定到上游节点输出

## 8. 当前执行约束

平台组装 JSON 时需要遵守以下约束：

1. 同一输入端口不要既通过 `input_bindings` 绑定，又通过 `edges` 再绑定一次
2. `input_bindings` 的值必须是字符串，不能再嵌套 `{"source": ...}` 结构
3. 输出侧建议显式暴露 `final_manifest`
4. `node_type` 当前默认使用 `module`
5. 兼容旧 pipeline 节点时才使用 `bridge.pipeline`

## 9. 推荐的 HTTP body 示例

```json
{
  "job_id": "wf-http-001",
  "pipeline_name": "workflow",
  "task_type": "workflow",
  "time_range": {
    "start": "2025-01-01T00:00:00",
    "end": "2025-01-16T00:00:00"
  },
  "region": {
    "kind": "global",
    "value": {}
  },
  "datasource_selection": {
    "source_value": "demo-http"
  },
  "algorithm_params": {},
  "output_spec": {
    "raster_format": "COG",
    "table_format": "parquet",
    "include_qc": true,
    "include_manifest": true,
    "extra": {}
  },
  "workflow_definition": {
    "workflow_id": "wf-http-demo",
    "nodes": [
      {
        "node_id": "module_node",
        "node_type": "module",
        "input_bindings": {
          "input_value": "input:source_value"
        },
        "params": {
          "module_name": "ndvi_daily"
        }
      }
    ],
    "outputs": [
      {
        "name": "final_manifest",
        "source": "node:module_node.manifest"
      }
    ]
  }
}
```

## 10. 平台侧推荐流程

如果平台直接接收的是完整 HTTP body，推荐优先参考 [job_request_http_json_adapter.md](file:///d:/Workspace/mat2py/docs/job_request_http_json_adapter.md)，先把整个 payload 统一适配成 `JobRequest`。

仅就 `workflow_definition` 子对象而言，推荐平台侧按以下顺序处理：

1. 收到 HTTP JSON body
2. 先校验业务级字段，如 `job_id`、`time_range`、`region`
3. 对 `workflow_definition` 使用 `get_workflow_definition_json_schema()` 做前置结构校验
4. 调用 `coerce_workflow_definition()` 转为 `WorkflowDefinition`
5. 把结果写回 `JobRequest.workflow_definition`
6. 调用 `run_job()`

示例：

```python
from contracts.serialization import coerce_job_request
from runner.dispatch import run_job

payload = http_request.json()
request = coerce_job_request(payload)
result = run_job(request, scheduler_adapter, datasource_adapter, logger_adapter)
```

## 11. 错误语义

适配层失败时，当前会抛出：

- `WorkflowDefinitionDecodeError`
- `WorkflowDefinitionValidationError`
- `TypeError`

常见错误包括：

1. 缺少必填字段，如 `workflow_id`
2. 字段类型错误，如 `nodes` 不是数组
3. 绑定结构错误，如 `input_bindings` 的值不是字符串
4. JSON 字符串不能成功解码
5. 使用了未注册的 `node_type`
6. `edges` 或 `outputs` 指向未知节点端口
7. 使用了未支持的 `request:*` 绑定键
8. 工作流图存在环路

错误信息会尽量带上路径，例如：

```text
Mapping value must be a string binding: workflow_definition.nodes[0].input_bindings.input_mat
```

平台侧建议：

1. 将这类错误归类为请求参数错误
2. 直接返回 4xx，而不是进入调度执行

补充说明：

1. 当前 Python 侧会在 `coerce_workflow_definition()` 之后、真正执行之前，再做一轮静态预校验。
2. 这意味着部分过去只能在执行期暴露的图定义错误，现在会在调度前被提前拦截。

## 12. JSON schema 获取

当前 Python 侧可直接获取 schema：

```python
from workflow.serialization import get_workflow_definition_json_schema

schema = get_workflow_definition_json_schema()
```

这个 schema 适合：

1. 平台启动时缓存
2. HTTP 层做请求预校验
3. 前端或工作流编辑器联动生成表单

## 13. 相关文件

代码与文档入口如下：

1. [serialization.py](file:///d:/Workspace/mat2py/Python/workflow/serialization.py)
2. [dispatch.py](file:///d:/Workspace/mat2py/Python/runner/dispatch.py)
3. [backend_integration_contract.md](file:///d:/Workspace/mat2py/docs/backend_integration_contract.md)
