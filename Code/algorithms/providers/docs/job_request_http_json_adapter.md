# HTTP/JSON 到 JobRequest 的适配规范

## 1. 文档定位

本文档补充 [backend_integration_contract.md](file:///d:/Workspace/mat2py/docs/backend_integration_contract.md) 与 [workflow_http_json_adapter.md](file:///d:/Workspace/mat2py/docs/workflow_http_json_adapter.md)，专门描述完整 HTTP body 如何在 Python 侧被统一适配为 `JobRequest`。

目标有四个：

1. 让平台直接传完整 JSON body，而不是手工拼 Python dataclass
2. 统一 `time_range`、`region`、`output_spec`、`resource_hint`、`cache_policy` 的适配口径
3. 把 `workflow_definition` 级联接入完整请求反序列化链
4. 明确参数错误应在 HTTP 层以 4xx 直接返回

## 2. 标准入口

当前标准适配入口位于：

- [serialization.py](file:///d:/Workspace/mat2py/Python/contracts/serialization.py)

核心函数：

```python
from contracts.serialization import (
    coerce_job_request,
    get_job_request_json_schema,
)

from contracts.validation import validate_job_request
```

含义如下：

1. `coerce_job_request(payload)`：把 `JobRequest` / `dict` / JSON string 统一转成 `JobRequest`
2. `get_job_request_json_schema()`：返回当前 HTTP body 的 JSON schema 描述
3. `validate_job_request(request)`：执行请求级业务校验，检查入口组合和占位字段语义

## 3. 输入链路

平台侧推荐链路如下：

```text
HTTP Request
  -> JSON body
  -> Python dict
  -> coerce_job_request(...)
  -> JobRequest
  -> run_job(...)
```

如果请求里带 `workflow_definition`，内部还会继续走：

```text
workflow_definition payload
  -> coerce_workflow_definition(...)
  -> WorkflowDefinition
```

## 4. 顶层字段

当前 `JobRequest` HTTP/JSON payload 支持以下字段：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `job_id` | 是 | `string` | 平台任务唯一 ID |
| `pipeline_name` | 是 | `string` | 兼容字段；workflow 化模式下通常填 `workflow` |
| `task_type` | 是 | `string` | 业务类型 |
| `time_range` | 是 | `object` | 时间范围对象 |
| `region` | 是 | `object` | 空间范围对象 |
| `datasource_selection` | 是 | `object` | 数据源选择和外部输入 |
| `algorithm_params` | 是 | `object` | 算法参数 |
| `output_spec` | 否 | `object` | 输出配置；缺失时会自动填默认值 |
| `resource_hint` | 否 | `object \| null` | 资源提示 |
| `cache_policy` | 否 | `object \| null` | 缓存策略 |
| `resume_policy` | 否 | `object \| null` | 续跑策略 |
| `priority` | 否 | `integer \| null` | 优先级 |
| `tags` | 否 | `object<string, string>` | 附加标签 |
| `module_name` | 否 | `string \| null` | 单模块入口 |
| `workflow_name` | 否 | `string \| null` | 预定义工作流 |
| `workflow_definition` | 否 | `object \| string \| null` | 显式工作流定义 |

## 5. 关键子对象

### 5.1 `time_range`

当前结构：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `start` | 是 | `string` | ISO 时间字符串 |
| `end` | 是 | `string` | ISO 时间字符串 |
| `step` | 否 | `string \| null` | 时间步长描述 |

规则：

1. Python 侧使用 `datetime.fromisoformat(...)` 解析
2. 结尾为 `Z` 的字符串会先转换为 `+00:00`
3. 必须满足 `start <= end`

接受示例：

```json
{
  "start": "2025-01-01T00:00:00Z",
  "end": "2025-01-16T00:00:00Z",
  "step": "P1D"
}
```

### 5.2 `region`

当前结构：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `kind` | 是 | `string` | 范围类型，如 `global`、`bbox` |
| `value` | 是 | `object` | 范围参数对象 |

规则：

1. `kind` 必须是非空字符串
2. `value` 必须是对象，不能是字符串、数组或数字

### 5.3 `output_spec`

当前结构：

| 字段 | 必填 | 类型 | 默认值 |
|---|---|---|---|
| `raster_format` | 否 | `string` | `COG` |
| `table_format` | 否 | `string` | `parquet` |
| `include_qc` | 否 | `boolean` | `true` |
| `include_manifest` | 否 | `boolean` | `true` |
| `extra` | 否 | `object` | `{}` |

说明：

1. 整个 `output_spec` 可以省略
2. 若省略，Python 侧会自动填成默认 `OutputSpec()`
3. 若只传部分字段，其余字段继续按默认值补齐

### 5.4 `resource_hint`

当前结构：

| 字段 | 必填 | 类型 |
|---|---|---|
| `cpu_cores` | 否 | `integer \| null` |
| `memory_gb` | 否 | `number \| null` |
| `gpu_count` | 否 | `integer \| null` |
| `tmp_disk_gb` | 否 | `number \| null` |
| `preferred_chunk_size` | 否 | `integer \| null` |

说明：

1. 传入对象后，会被反序列化为 `ResourceHint`
2. 数值字段中，浮点和整数都会统一成 Python 数值类型

### 5.5 `cache_policy`

当前结构：

| 字段 | 必填 | 类型 | 默认值 |
|---|---|---|---|
| `mode` | 否 | `string` | `metadata_only` |
| `enabled` | 否 | `boolean` | `true` |

说明：

1. 传入对象后，会被反序列化为 `CachePolicy`
2. 若对象存在但字段缺失，会按 dataclass 默认值补齐

## 6. `workflow_definition` 串联规则

若 HTTP body 中包含 `workflow_definition`，当前支持三种输入形态：

1. JSON object
2. JSON string
3. `null`

Python 侧会级联调用：

```python
from workflow.serialization import coerce_workflow_definition
from workflow.template_inference import infer_workflow_request_template
```

因此这部分会继续继承已有能力：

1. `WorkflowDefinition` 结构反序列化
2. workflow 静态预校验
3. 明确到字段路径的错误提示
4. 对显式 workflow 反推出最小 `datasource_selection` 输入模板

## 7. 推荐 HTTP body 示例

```json
{
  "job_id": "job-http-003",
  "pipeline_name": "workflow",
  "task_type": "retrieval",
  "time_range": {
    "start": "2025-01-01T00:00:00Z",
    "end": "2025-01-31T00:00:00Z"
  },
  "region": {
    "kind": "bbox",
    "value": {
      "xmin": 73,
      "ymin": 18,
      "xmax": 135,
      "ymax": 54
    }
  },
  "datasource_selection": {},
  "algorithm_params": {
    "mode": "omega"
  },
  "output_spec": {
    "include_manifest": true,
    "extra": {
      "publish": false
    }
  },
  "resource_hint": {
    "cpu_cores": 8,
    "memory_gb": 32
  },
  "cache_policy": {
    "mode": "full",
    "enabled": false
  },
  "workflow_name": "retrieval_workflow"
}
```

## 8. 平台侧推荐代码

```python
from contracts.serialization import coerce_job_request
from runner.dispatch import run_job

payload = http_request.json()
request = coerce_job_request(payload)
validate_job_request(request)
result = run_job(request, scheduler_adapter, datasource_adapter, logger_adapter)
```

## 9. 错误语义

当前建议把错误分为两层：

1. 解码/结构层错误
2. 业务/语义层错误

适配层失败时，当前主要会抛出：

- `JobRequestDecodeError`
- `JobRequestValidationError`
- `WorkflowDefinitionDecodeError`
- `WorkflowDefinitionValidationError`
- `TypeError`

常见错误包括：

1. 缺少必填字段，如 `job_id`
2. 时间字符串不是合法 ISO 格式
3. `time_range.start > time_range.end`
4. `region.value` 不是对象
5. `output_spec.include_qc` 不是布尔值
6. `resource_hint` 或 `cache_policy` 的字段类型不合法
7. `pipeline_name='workflow'` 但没有提供 `workflow_definition / workflow_name / module_name`
8. `workflow_definition` 与 `module_name` 同时出现
9. `module_name / workflow_name / pipeline_name` 指向不存在的入口
10. `workflow_definition` 结构不合法

平台侧建议：

1. `JobRequestDecodeError`、`WorkflowDefinitionDecodeError`、`TypeError` 归类为 `400 Bad Request`
2. `JobRequestValidationError`、`WorkflowDefinitionValidationError` 归类为 `422 Unprocessable Entity`
3. 这两类错误都不要进入任务调度或执行阶段

## 10. 请求级业务校验规则

当前 `validate_job_request()` 主要检查以下规则：

1. `module_name` 不能与 `workflow_definition` 同时出现
2. 只要使用 `workflow_definition / workflow_name / module_name` 任一 workflow 化入口，`pipeline_name` 就必须是占位值 `workflow`
3. 若 `pipeline_name='workflow'`，则必须至少提供 `workflow_definition / workflow_name / module_name` 之一
4. `module_name` 存在时，必须是已注册原生模块
5. 当 `workflow_definition` 和 `module_name` 都不存在、仅使用 `workflow_name` 时，`workflow_name` 必须是已注册 preset
6. 若回退走 compat pipeline 路径，`pipeline_name` 必须是已注册旧 pipeline

补充说明：

1. `workflow_name` 不是永远都表示 preset 选择器。
2. 当 `workflow_definition` 已存在时，`workflow_name` 可以作为外层任务名或显示名保留。
3. 当 `module_name` 已存在时，`workflow_name` 也可以作为自动包装单节点 workflow 的名称覆盖值。

## 11. 模块与工作流请求模板

当前 `validate_job_request()` 已经前移了一层业务模板校验，不再只检查字段组合，还会检查入口对应的关键输入是否齐全。

### 11.1 `module_name` 关键模板

| `module_name` | 必需 `datasource_selection` | 关键 `algorithm_params` / 说明 | 推荐 `task_type` |
|---|---|---|---|
| `smap_daily` | `input_dir` | 无强制参数 | `smap_daily` / `workflow` |
| `ndvi_daily` | `input_dir` | 可选 `emit_quality_products`、`sg_window_length` 等 | `ndvi_daily` / `workflow` |
| `station_daily` | `input_dir` | 可选 `source_type` 与验证参数 | `station_daily` / `workflow` |
| `fy_daily` | `input_dir` | `orbit_mode` 若提供，必须是 `MWRID` / `MWRIA` / `Both` | `fy_daily` / `workflow` |
| `inversion_daily` | `input_mat` | `mode` 若提供，必须是 `dh` / `ddca` | `inversion_daily` / `workflow` |
| `block_inversion` | `input_mat` | `mode` 若提供，必须是 `dh` / `ddca` | `block_inversion` / `retrieval` / `workflow` |
| `omega_block` | `input_mat` | `exp_mode` 若提供，支持 `Exp0` / `Exp1A` / `Exp1B` / `Exp2` | `omega_block` / `retrieval` / `workflow` |

### 11.2 `workflow_name` 关键模板

当前唯一内置 preset 是 `retrieval_workflow`。

规则如下：

1. `task_type` 推荐使用 `retrieval`，也兼容 `workflow`
2. `algorithm_params.mode` 若给出，支持 `dh` / `ddca` / `omega`
3. 当 `mode=omega` 时，`datasource_selection` 必须提供 `omega_fixed_mat` 与 `exp0_calib_mat`
4. 当 `mode=dh` 或 `mode=ddca` 时，上述两个输入不是必需项

### 11.3 `task_type` 一致性

当前 `task_type` 已不再只是任意标签。

对 `module_name` 与 `workflow_name` 入口，系统会检查它是否与所选入口模板一致；若明显不匹配，会在执行前直接返回 `422`。

注意：

1. 对显式 `workflow_definition`，当前还不做强绑定的 `task_type` 模板约束
2. 对 compat `pipeline_name`，当前主要仍做注册性校验，业务模板约束较弱

### 11.4 显式 `workflow_definition` 模板推导

现在平台可以直接对自定义 workflow 调用：

```python
from workflow.template_inference import infer_workflow_request_template
from workflow.panel_schema import build_workflow_input_panel_schema

template = infer_workflow_request_template(workflow_definition_payload)
panel_schema = build_workflow_input_panel_schema(workflow_definition_payload)
```

当前会推导出：

1. 整张图实际引用的 `input:*`，并收敛成最小 `required_datasource_keys`
2. 实际消费到的 `request:*` 键，例如 `algorithm_params`、`time_range`、`tags`
3. 每个节点级别使用到的显式外部输入

同时，`validate_job_request()` 现在会对显式 `workflow_definition` 复用这套推导结果；如果 `input:*` 所需的 key 没有出现在 `datasource_selection` 中，会在执行前直接返回 `422`。

如果平台需要直接生成输入面板，推荐继续使用：

```python
from workflow.panel_schema import build_workflow_input_panel_schema
from workflow.ui_metadata import build_workflow_input_panel_ui_schema
```

当前返回结果会把字段分成三组：

1. `datasource_fields`
2. `algorithm_param_fields`
3. `request_fields`

每个字段项至少包含：

1. `key`
2. `required`
3. `value_kind`
4. `consumers`
5. `entry_names`
6. `allowed_values`
7. `source_types`
8. `format_hints`

如果平台希望直接拿到更偏前端渲染的字段信息，可继续调用：

```python
from workflow.ui_metadata import build_workflow_input_panel_ui_schema
```

该入口会在 panel schema 之上补一层 UI metadata，当前包括：

1. section 级 `title`
2. 字段级 `label`
3. 字段级 `control_type`
4. 字段级 `placeholder`
5. 字段级 `example_value`
6. 中文化描述文本

当前控件类型示例：

1. `directory_picker`
2. `file_picker`
3. `path_input`
4. `select`
5. `switch`
6. `number_input`
7. `text_input`
8. `datetime_input`
9. `datetime_range`
10. `region_editor`
11. `json_editor`

### 11.5 validation feedback schema

当前 Python 侧还提供统一的字段级错误反馈构造器：

```python
from contracts.validation_feedback import build_validation_feedback
```

适用场景：

1. HTTP 层需要把异常转换成结构化错误响应
2. 前端需要把错误直接定位到表单字段
3. 平台希望把后端校验错误映射成统一的错误码体系

当前支持的异常来源：

1. `JobRequestDecodeError`
2. `WorkflowDefinitionDecodeError`
3. `JobRequestValidationError`
4. `WorkflowDefinitionValidationError`

当前返回结构包括：

1. `error_type`
2. `summary`
3. `issues[]`

每个 `issue` 至少包含：

1. `code`
2. `message`
3. `field_path`
4. `field_key`
5. `section`
6. `label`
7. `control_type`
8. `details`

示例：

```python
from contracts.serialization import coerce_job_request
from contracts.validation import validate_job_request
from contracts.validation_feedback import build_validation_feedback

try:
    request = coerce_job_request(payload)
    validate_job_request(request)
except Exception as exc:
    feedback = build_validation_feedback(exc, request=request)
```

典型映射效果：

1. 缺少 `datasource_selection.input_dir` 时，`issue.section='datasource_selection'`
2. 非法 `algorithm_params.mode` 时，`issue.field_path='job_request.algorithm_params.mode'`
3. workflow 中非法 `request:*` 绑定时，`issue.field_path` 会指向具体 `workflow_definition.nodes[...]`
4. 如果 workflow 已能生成 UI metadata，`issue.label` 与 `issue.control_type` 会自动补齐

### 11.6 标准 API error response

如果 HTTP 层希望直接返回稳定的错误响应体，可继续使用：

```python
from contracts.api_errors import build_api_error_response
```

当前会把以下错误统一包装成标准响应：

1. `JobRequestDecodeError`
2. `WorkflowDefinitionDecodeError`
3. `JobRequestValidationError`
4. `WorkflowDefinitionValidationError`
5. 其他未分类异常

当前返回结构包括：

1. `error_type`
2. `error_code`
3. `http_status`
4. `retryable`
5. `user_message`
6. `developer_message`
7. `issues`
8. `suggested_fixes`
9. `metadata`

当前默认 HTTP 语义：

1. `JobRequestDecodeError` -> `400`
2. `WorkflowDefinitionDecodeError` -> `400`
3. `JobRequestValidationError` -> `422`
4. `WorkflowDefinitionValidationError` -> `422`
5. 未分类异常 -> `500`

示例：

```python
from contracts.serialization import coerce_job_request
from contracts.validation import validate_job_request
from contracts.api_errors import build_api_error_response

try:
    request = coerce_job_request(payload)
    validate_job_request(request)
except Exception as exc:
    response = build_api_error_response(exc, request=request)
    return {
        "status": response.http_status,
        "body": {
            "error_type": response.error_type,
            "error_code": response.error_code,
            "retryable": response.retryable,
            "user_message": response.user_message,
            "developer_message": response.developer_message,
            "issues": [issue.__dict__ for issue in response.issues],
            "suggested_fixes": [fix.__dict__ for fix in response.suggested_fixes],
            "metadata": response.metadata,
        },
    }
```

典型行为：

1. 缺少字段时，`suggested_fixes` 会提示补齐对应 key
2. 非法枚举值时，`suggested_fixes` 会附允许值建议
3. selector 冲突时，`suggested_fixes` 会提示只保留一种入口
4. 未分类运行时异常会回 `500`，并标记 `retryable=true`

## 12. 日志输出约定

当前日志接口仍沿用 `LoggerAdapter`，但推荐平台把每条事件当成结构化日志消费。

建议最少包含这些字段：

| 字段 | 说明 |
|---|---|
| `timestamp` | ISO UTC 时间 |
| `job_id` | 作业 ID |
| `run_id` | 运行 ID |
| `event_type` | 如 `stage_start` / `progress` / `artifact` / `error` |
| `stage` | 统一阶段名 |
| `message` | 可读消息 |
| `progress` | 仅进度事件使用，范围 `0~1` |
| `extra` | 扩展字段 |

当前实现中的阶段名已经开始收口为：

1. `dispatch.workflow`
2. `dispatch.pipeline`
3. `workflow.node.<node_id>`
4. `workflow.dispatch`

补充说明：

1. `WorkflowRunner` 现在会自动输出节点级 `start/end/error`
2. 本地 `ConsoleLoggerAdapter` 已改为 JSON 行输出
3. 最终 manifest 写盘后会额外输出 `job_manifest` artifact 日志

## 13. JSON schema 获取

当前 Python 侧可直接获取 schema：

```python
from contracts.serialization import get_job_request_json_schema

schema = get_job_request_json_schema()
```

适用场景：

1. HTTP 层请求预校验
2. 平台启动时缓存 schema
3. 前端表单或任务编辑器联动生成字段约束
