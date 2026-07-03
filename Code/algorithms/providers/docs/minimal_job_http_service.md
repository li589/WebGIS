# 最小 HTTP 作业服务

## 目的

本文档说明仓库内新增的最小 HTTP 作业服务如何运行、暴露哪些接口，以及它和生产级 WebGIS 后端服务之间的边界。

对应代码入口：

1. `Python/service/job_api.py`
2. `Python/service/http_server.py`

如果你要继续对接平台队列和独立 worker，请同时参考：

1. [平台队列与 Worker 集成说明](file:///d:/Workspace/mat2py/docs/platform_queue_worker_integration.md)

## 当前定位

这层服务的目标是：

1. 把 `JobRequest` 解码、校验、执行、标准响应收敛成统一 HTTP 入口
2. 让 WebGIS 后端或调度器先能直接联调本仓库
3. 为后续接入正式网关、认证和调度治理提供稳定边界

它不是：

1. 完整的生产网关
2. 完整的异步任务队列系统
3. 多租户鉴权服务

## 运行命令

在项目 Python 目录下，可直接运行：

```bash
d:\Workspace\mat2py\venv\Scripts\python.exe -m service.http_server --host 127.0.0.1 --port 8000
```

如果希望指定 workspace：

```bash
d:\Workspace\mat2py\venv\Scripts\python.exe -m service.http_server --host 127.0.0.1 --port 8000 --workspace D:\workspace\mat2py-api
```

如果希望把状态和队列都落到 workspace，并关闭服务内嵌 worker，改成：

```bash
d:\Workspace\mat2py\venv\Scripts\python.exe -m service.http_server --host 127.0.0.1 --port 8000 --workspace D:\workspace\mat2py-api --queue-backend file --persistent-state --no-worker
```

然后再单独启动 worker 进程：

```bash
d:\Workspace\mat2py\venv\Scripts\python.exe -m service.worker_process --workspace D:\workspace\mat2py-api --queue-backend file --persistent-state
```

## 当前接口

### `GET /health`

用途：

1. 健康检查
2. 验证服务是否启动

示例响应：

```json
{
  "status": "ok",
  "service": "mat2py-job-api",
  "workspace": "D:/workspace/mat2py-api"
}
```

### `GET /schemas/job-request`

用途：

1. 返回 `JobRequest` 的 JSON Schema
2. 供平台或前端动态校验请求字段

### `GET /schemas/workflow-definition`

用途：

1. 返回 `WorkflowDefinition` 的 JSON Schema
2. 供工作流编排或高级接入方做静态校验

### `GET /api/v1/modules`

用途：

1. 返回当前可直接调用的原生模块列表
2. 暴露每个模块的端口、默认参数和请求模板
3. 供 WebGIS 动态生成“模块执行”入口

### `GET /api/v1/modules/{module_name}`

用途：

1. 返回单个模块的结构化说明
2. 查看输入端口、输出端口和 `request_template`

### `GET /api/v1/workflows`

用途：

1. 返回当前命名 workflow 列表
2. 暴露工作流描述、节点数量和请求模板
3. 供 WebGIS 动态生成“工作流执行”入口

### `GET /api/v1/workflows/{workflow_name}`

用途：

1. 返回单个 workflow 的完整结构化说明
2. 包含 `definition`、`request_template`、`panel_schema`、`ui_schema`

### `GET /api/v1/workflows/{workflow_name}/panel-schema`

用途：

1. 返回 workflow 输入面板 schema
2. 供 WebGIS 后端或前端动态生成表单字段

### `GET /api/v1/workflows/{workflow_name}/ui-schema`

用途：

1. 返回 workflow UI schema
2. 供 WebGIS 前端直接生成控件类型、分组和占位提示

### `POST /jobs/validate`

用途：

1. 只做请求反序列化和业务校验
2. 不执行实际任务
3. 适合前端预校验、平台预检查、联调排错

成功响应示例：

```json
{
  "valid": true,
  "normalized_request": {
    "job_id": "omega-job-001",
    "pipeline_name": "workflow"
  }
}
```

### `POST /jobs`

用途：

1. 接收完整请求体
2. 执行 `coerce_job_request -> validate_job_request -> run_job`
3. 返回标准成功结果或标准错误对象

当前它是同步执行模型：

1. HTTP 请求期间直接执行任务
2. 成功时返回 `job_result` 与 `result_dto`
3. 失败时返回 `500` 和结构化错误体

`result_dto` 是面向 WebGIS 的稳定结果视图，目的在于把：

1. `JobResult`
2. `manifest_uri`
3. `ProductManifest.products / main_layers / qc_layers / tables / extra`

整形成可直接供任务详情页、产品面板和预览入口消费的字段。

典型字段包括：

1. `artifacts.manifest_uri`
2. `artifacts.metadata_uri`
3. `manifest_loaded`
4. `manifest_summary`
5. `products`
6. `main_layers`
7. `qc_layers`
8. `tables`
9. `extra`

说明：

1. 当 `manifest_uri` 指向本地可读取 JSON 文件时，服务会自动展开 manifest 内容
2. 当 `manifest_uri` 是 `MinIO/S3/HTTP/memory://` 这类当前服务端不直接读取的远端 URI 时，仍会返回稳定字段，但 `manifest_loaded=false`
3. 这非常适合 `FastAPI + Celery + Redis + MinIO` 架构下由 WebGIS 自己决定是否进一步访问对象存储

### `POST /jobs/async`

用途：

1. 异步受理任务
2. 立即返回 `submission_id`
3. 后续通过查询接口查看状态

当前返回示例：

```json
{
  "accepted": true,
  "submission_id": "2f5c3f6c6d6442628ec2fdbf49b57f20",
  "job_id": "omega-job-001",
  "status": "queued",
  "status_url": "/jobs/2f5c3f6c6d6442628ec2fdbf49b57f20"
}
```

### `GET /jobs/{submission_id}`

用途：

1. 查询异步作业状态
2. 查看当前 `run_id`
3. 查看最终 `job_result` 与最终 HTTP 响应

当前会返回：

1. `state`
2. `scheduler_status`
3. `status_detail`
4. `run_id`
5. `job_result`
6. `result_dto`
7. `final_response_status`
8. `final_response_body`

## 当前请求流

```text
HTTP Request
  -> raw JSON text
  -> coerce_job_request(...)
  -> validate_job_request(...)
  -> run_job(...)
  -> JobResult / ApiErrorResponse
```

## 当前默认适配器

最小 HTTP 服务默认使用本地适配器：

1. `LocalSchedulerAdapter`
2. `LocalDataSourceAdapter`
3. `ConsoleLoggerAdapter`
4. `LocalProductSink`

这意味着：

1. 它适合本地联调、仓库内演示、后端接口收口
2. 它不等于平台真实的 scheduler / datasource / artifact sink

## 平台 adapter 骨架

当前仓库还新增了面向平台接入的函数式 adapter 骨架，位于：

1. `Python/service/platform_adapters.py`

当前可直接复用的骨架包括：

1. `CallbackSchedulerAdapter`
2. `TrackingSchedulerAdapter`
3. `CallbackDataSourceAdapter`
4. `CallbackLoggerAdapter`
5. `CallbackProductSink`

它们的目的不是替代平台实现，而是让平台侧可以先把既有回调、状态上报、日志采集和产物写出能力直接挂接到当前仓库的统一接口上。

## 平台 mock 示例

当前仓库还提供了一个可直接运行的 mock 平台集成闭环，适合在没有真实平台 SDK 前先验证接入方式：

1. `PlatformClientMock`
2. `build_platform_job_service(...)`
3. `build_platform_mock_service(...)`

推荐阅读：

1. [平台队列与 Worker 集成说明](file:///d:/Workspace/mat2py/docs/platform_queue_worker_integration.md)

## 与 OMEGA 的推荐组合

当前推荐用以下方式联调 OMEGA：

1. `pipeline_name = "workflow"`
2. `workflow_name = "retrieval_workflow"`
3. `algorithm_params.mode = "omega"`

相关请求样例见：

1. [OMEGA WebGIS 最小请求样例](file:///d:/Workspace/mat2py/docs/omega_webgis_minimal_request_examples.md)

## 当前边界

当前这层服务已经解决：

1. 请求入口统一
2. schema 暴露
3. validate / submit 分离
4. 标准错误响应收口
5. 最小异步提交与查询模型
6. 模块与 workflow 的能力发现接口
7. workflow 的 panel schema / UI schema 接口
8. 文件队列 + 文件状态存储的本地分进程运行方式
9. 平台 adapter 骨架

当前仍未解决：

1. 鉴权与认证
2. 生产级异步队列与回调治理
3. 多 worker 协调和幂等治理
4. 平台级限流和配额
5. 网关超时治理
6. 真实调度器与数据源适配

## 推荐下一步

如果要把这层最小服务继续推进成可上线后端，建议按以下顺序做：

1. 把本地 adapter 替换成平台真实 adapter
2. 把当前最小异步模型升级为平台真实任务队列
3. 接入认证、鉴权和限流
4. 接入平台日志、告警和产物持久化
5. 再做灰度和 SLA 观察
