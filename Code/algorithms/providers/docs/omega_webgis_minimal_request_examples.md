# OMEGA WebGIS 最小请求样例

## 目的

本文档面向 WebGIS 后端和调度接入方，给出当前仓库下 OMEGA 的推荐入口、最小请求样例、成功产物清单，以及常见失败响应示意。

本文档关注的是“平台如何组装请求”，不是算法内部实现细节。

如果你需要直接联调仓库内新增的最小 HTTP 服务，请同时参考：

1. [最小 HTTP 作业服务](file:///d:/Workspace/mat2py/docs/minimal_job_http_service.md)

## 推荐入口

当前推荐优先使用以下入口：

1. `pipeline_name = "workflow"`
2. `workflow_name = "retrieval_workflow"`
3. `algorithm_params.mode = "omega"`

原因是这条链路已经把上游 `timeseries_bundle` 和下游 `omega_block` 串起来，平台不需要自己先离线拼装 `input_mat`。

对应执行链如下：

```text
JobRequest
  -> run_job()
  -> retrieval_workflow
  -> timeseries_bundle
  -> omega_block
  -> final_manifest
```

## 入口差异

### 方案 A：推荐的 workflow 入口

适用场景：

1. 平台已经能提供时序 MAT 源和 ancillary 输入
2. 希望由 workflow 自动先构建 `timeseries_bundle`
3. 希望保持与当前仓库预设入口一致

当前 `retrieval_workflow` 在 `mode=omega` 时，模板层明确要求：

1. `datasource_selection.omega_fixed_mat`
2. `datasource_selection.exp0_calib_mat`

同时，按当前仓库测试和 bundle 构建链路，平台通常还需要准备：

1. `datasource_selection.smap_daily_mat`
2. `datasource_selection.ndvi_daily_mat`
3. `datasource_selection.ancillary_mat`

### 方案 B：直接调用 `omega_block`

适用场景：

1. 平台已经提前产出可直接消费的 `input_mat`
2. 不希望在本次任务中执行 `timeseries_bundle`
3. 希望把 bundle 构建和 OMEGA 检索拆成两个调度步骤

当前 `omega_block` 模块模板最小要求只有：

1. `datasource_selection.input_mat`

但在真实运行中，如果 `input_mat` 本身不包含 OMEGA 需要的固定参数和标定参数，通常仍需额外提供：

1. `datasource_selection.omega_fixed_mat`
2. `datasource_selection.exp0_calib_mat`

## 最小请求样例

### 样例 1：推荐的 workflow 请求

这是当前最推荐给 WebGIS 后端的提交方式。

```json
{
  "job_id": "omega-job-20260703-001",
  "pipeline_name": "workflow",
  "workflow_name": "retrieval_workflow",
  "task_type": "retrieval",
  "time_range": {
    "start": "2025-01-01T00:00:00Z",
    "end": "2025-01-10T00:00:00Z"
  },
  "region": {
    "kind": "global",
    "value": {}
  },
  "datasource_selection": {
    "smap_daily_mat": "D:/data/omega/smap_daily_20250101_20250110.mat",
    "ndvi_daily_mat": "D:/data/omega/ndvi_daily_20250101_20250110.mat",
    "ancillary_mat": "D:/data/omega/ancillary_static.mat",
    "omega_fixed_mat": "D:/data/omega/omega_fixed.mat",
    "exp0_calib_mat": "D:/data/omega/exp0_calib.mat"
  },
  "algorithm_params": {
    "mode": "omega",
    "freq_ghz": 1.4,
    "temp_scheme": "single",
    "exp_mode": "Exp0",
    "write_daily_files": true
  },
  "output_spec": {
    "raster_format": "COG",
    "table_format": "parquet",
    "include_qc": true,
    "include_manifest": true,
    "extra": {
      "output_dir": "D:/workspace/jobs/omega-job-20260703-001/products"
    }
  },
  "resource_hint": {
    "cpu_cores": 8,
    "memory_gb": 32
  }
}
```

字段说明：

1. `pipeline_name` 当前建议固定为占位值 `workflow`
2. `workflow_name` 使用已注册 preset `retrieval_workflow`
3. `algorithm_params.mode` 必须为 `omega`
4. `write_daily_files=true` 时，会额外产出逐日 MAT 文件
5. `resource_hint` 只是调度提示，不改变算法数值语义

### 样例 2：直接调用 `omega_block`

当平台已经有现成 `timeseries_bundle_*.mat` 时，可直接提交模块请求：

```json
{
  "job_id": "omega-block-20260703-001",
  "pipeline_name": "workflow",
  "module_name": "omega_block",
  "task_type": "omega_block",
  "time_range": {
    "start": "2025-01-01T00:00:00Z",
    "end": "2025-01-10T00:00:00Z"
  },
  "region": {
    "kind": "global",
    "value": {}
  },
  "datasource_selection": {
    "input_mat": "D:/workspace/prepared/timeseries_bundle_20250101_20250110.mat",
    "omega_fixed_mat": "D:/data/omega/omega_fixed.mat",
    "exp0_calib_mat": "D:/data/omega/exp0_calib.mat"
  },
  "algorithm_params": {
    "freq_ghz": 1.4,
    "temp_scheme": "single",
    "exp_mode": "Exp0",
    "write_daily_files": true
  },
  "output_spec": {
    "include_manifest": true,
    "extra": {
      "output_dir": "D:/workspace/jobs/omega-block-20260703-001/products"
    }
  }
}
```

说明：

1. 这里不再需要 `workflow_name`
2. `module_name` 和 `workflow_definition` 不能同时出现
3. 若 `input_mat` 已经内含固定参数与标定参数，可视平台数据契约决定是否省略两份额外 MAT

## 当前支持的关键参数

### `algorithm_params`

当前 OMEGA 入口最常用的参数如下：

| 字段 | 必填 | 说明 |
|---|---|---|
| `mode` | workflow 入口必填 | 推荐固定为 `omega` |
| `freq_ghz` | 否 | 频率参数 |
| `temp_scheme` | 否 | 温度方案 |
| `exp_mode` | 否 | 当前允许 `Exp0`、`EXP1A`、`EXP1B`、`EXP2` |
| `write_daily_files` | 否 | 是否额外写出日文件 |

### `datasource_selection`

当前最常见的输入键如下：

| 键名 | workflow 入口 | `omega_block` 入口 | 说明 |
|---|---|---|---|
| `smap_daily_mat` | 常见需要 | 否 | 时序源之一 |
| `ndvi_daily_mat` | 常见需要 | 否 | 时序源之一 |
| `ancillary_mat` | 常见需要 | 否 | 静态辅助输入 |
| `input_mat` | 否 | 必填 | 已构建好的 timeseries bundle |
| `omega_fixed_mat` | `mode=omega` 时必填 | 常建议提供 | OMEGA 固定参数输入 |
| `exp0_calib_mat` | `mode=omega` 时必填 | 常建议提供 | `Exp0` 标定输入 |

## 成功产物

当前 `omega_block` 模块会写出如下产物：

### Product Types

1. `omega_block_mat`
2. `omega_daily_mat`，仅当 `write_daily_files=true`

### Main Layers

1. `OMEGA_mat`
2. `SM_RET_mat`
3. `VOD_RET_mat`
4. `Tau_star_mat`

### QC Layers

1. `qc_flag_mat`
2. `qc_condk_mat`
3. `qc_sratio_mat`

典型 manifest 中还会包含：

1. `extra.module_name = "omega_block"`
2. `extra.output_dir`
3. `extra.freq_ghz`
4. `extra.temp_scheme`
5. `extra.exp_mode`
6. `extra.pixel_chunk_size`

## 成功响应的消费方式

平台最终应以 `ProductManifest` 为准，而不是自行猜测文件名。

推荐消费顺序：

1. 读取 `JobResult.manifest_uri`
2. 加载 manifest
3. 以 `products[].type` 区分 `omega_block_mat` 和 `omega_daily_mat`
4. 以 `main_layers` 和 `qc_layers` 组织后续入库或发布流程

## 常见失败响应

当前 HTTP/JSON 适配链推荐使用 `build_api_error_response(...)` 返回标准错误对象。

### 示例 1：缺少 `omega_fixed_mat`

```json
{
  "error_type": "job_request_validation",
  "error_code": "job_request_validation_failed",
  "http_status": 422,
  "retryable": false,
  "user_message": "请求参数未通过业务校验，请检查表单字段。",
  "developer_message": "workflow_name=retrieval_workflow 在当前参数组合下缺少必需输入。",
  "issues": [
    {
      "code": "missing_datasource_key",
      "field_path": "job_request.datasource_selection.omega_fixed_mat",
      "field_key": "omega_fixed_mat"
    }
  ],
  "suggested_fixes": [
    {
      "code": "provide_datasource_key",
      "message": "在 `datasource_selection` 中补充 `omega_fixed_mat`。",
      "field_path": "job_request.datasource_selection.omega_fixed_mat"
    }
  ],
  "metadata": {
    "issue_count": 1
  }
}
```

### 示例 2：`exp_mode` 不在允许值中

```json
{
  "error_type": "job_request_validation",
  "error_code": "job_request_validation_failed",
  "http_status": 422,
  "retryable": false,
  "user_message": "请求参数未通过业务校验，请检查表单字段。",
  "developer_message": "algorithm_params.exp_mode 的取值不合法。",
  "issues": [
    {
      "code": "invalid_algorithm_value",
      "field_path": "job_request.algorithm_params.exp_mode",
      "field_key": "exp_mode"
    }
  ],
  "suggested_fixes": [
    {
      "code": "use_allowed_algorithm_value",
      "message": "修正 `exp_mode` 的取值，可选值：Exp0, EXP1A, EXP1B, EXP2。",
      "field_path": "job_request.algorithm_params.exp_mode"
    }
  ],
  "metadata": {
    "issue_count": 1
  }
}
```

说明：

1. 上述错误体是按当前契约整理的示意样例
2. 实际 `developer_message` 和 `issues` 细节会随具体校验路径变化
3. 平台侧可直接据 `http_status`、`error_code`、`issues[].field_path` 做前端映射

## 平台接入建议

当前最建议的落地方式如下：

1. 默认走 `workflow_name = retrieval_workflow`
2. 平台统一封装 `datasource_selection` 的路径解析和版本注入
3. 成功时只消费 manifest，不依赖硬编码文件名
4. 失败时统一透传标准 `ApiErrorResponse`
5. 把 `omega_fixed_mat` 和 `exp0_calib_mat` 视为平台级受控输入，而不是前端随意上传字段
