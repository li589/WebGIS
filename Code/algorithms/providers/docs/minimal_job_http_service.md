# 最小 HTTP 作业服务

## 1. 文档目的

本文档说明仓库内的最小 HTTP 作业服务如何运行、暴露哪些接口，以及它和生产级 WebGIS 后端服务之间的边界。

对应代码入口主要包括：

1. `Python/service/job_api.py`
2. `Python/service/http_server.py`

## 2. 当前定位

这层服务的目标是：

1. 把 `JobRequest` 解码、校验、执行和标准响应收敛成统一 HTTP 入口
2. 让 WebGIS 后端或调度器先能直接联调本仓库
3. 为后续接入正式网关、认证和调度治理提供稳定边界

它不是：

1. 完整的生产网关
2. 完整的异步任务队列系统
3. 多租户鉴权服务

## 3. 当前能力

当前服务已经覆盖：

- 请求入口统一
- schema 暴露
- validate / submit 分离
- 标准错误响应收口
- 最小异步提交与查询模型
- 模块与 workflow 的能力发现接口
- workflow 的 panel schema / UI schema 接口
- 文件队列 + 文件状态存储的本地分进程运行方式
- 平台 adapter 骨架

## 4. 运行方式

当前可直接通过 `service.http_server` 启动 HTTP 服务，也可以再单独启动 `service.worker_process` 作为 worker。

服务支持：

- 本地内嵌 worker
- 关闭内嵌 worker 后独立 worker 进程
- file queue 模式
- 平台队列模式

## 5. 当前接口

### `GET /health`

健康检查接口。

### `GET /schemas/job-request`

返回 `JobRequest` 的 JSON Schema。

### `GET /schemas/workflow-definition`

返回 `WorkflowDefinition` 的 JSON Schema。

### `GET /api/v1/modules`

返回当前可直接调用的原生模块列表。

### `GET /api/v1/modules/{module_name}`

返回单个模块的结构化说明。

### `GET /api/v1/workflows`

返回当前命名 workflow 列表。

### `GET /api/v1/workflows/{workflow_name}`

返回单个 workflow 的完整结构化说明。

### `GET /api/v1/workflows/{workflow_name}/panel-schema`

返回 workflow 输入面板 schema。

### `GET /api/v1/workflows/{workflow_name}/ui-schema`

返回 workflow UI schema。

### `POST /jobs/validate`

只做请求反序列化和业务校验，不执行实际任务。

### `POST /jobs`

同步执行完整任务。

### `POST /jobs/async`

异步受理任务，返回 `submission_id`。

### `GET /jobs/{submission_id}`

查询异步作业状态和最终结果。

## 6. 请求流

```text
HTTP Request
  -> raw JSON text
  -> coerce_job_request(...)
  -> validate_job_request(...)
  -> run_job(...)
  -> JobResult / ApiErrorResponse
```

## 7. 默认适配器

最小 HTTP 服务默认使用本地适配器：

- `LocalSchedulerAdapter`
- `LocalDataSourceAdapter`
- `ConsoleLoggerAdapter`
- `LocalProductSink`

## 8. 平台适配

仓库同时提供了：

- 平台 adapter 骨架
- mock 平台集成闭环
- 真实平台 HTTP 模式接入方式

## 9. 推荐联调方式

如果要联调 OMEGA 或其它工作流，建议：

1. `pipeline_name = "workflow"`
2. `workflow_name = "retrieval_workflow"`
3. `algorithm_params.mode = "omega"`

## 10. 当前边界

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
2. 生产级异步队列和回调治理
3. 多 worker 协调和幂等治理
4. 平台级限流和配额
5. 网关超时治理
6. 真实调度器与数据源适配

## 11. 结论

最小 HTTP 作业服务的意义在于把 Python 计算包先用一个稳定、可测试、可联调的 HTTP 入口收口起来，后续再逐步替换成真正的平台级后端能力。
