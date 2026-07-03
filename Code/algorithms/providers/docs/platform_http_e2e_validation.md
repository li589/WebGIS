# 平台 HTTP 模式端到端联调验收

## 目的

本文档用于完成“真实平台接口模式”的非 UI 联调验收，目标是验证以下链路已经闭环：

```text
HTTP 受理进程 -> PlatformJobQueue -> 平台任务接口 -> 独立 worker -> 状态回写 -> 结果查询
```

这里的“真实任务样本”指：

1. 使用仓库内真实模块与真实 `JobRequest` 结构
2. 使用 `queue-backend=platform`
3. 通过 `PlatformHttpClient` 走真实平台 HTTP/JSON 接口约定

## 当前代码入口

与本验收直接相关的实现如下：

1. `Python/service/platform_http_client.py`
2. `Python/service/platform_service_factory.py`
3. `Python/service/http_server.py`
4. `Python/service/worker_process.py`
5. `Python/tests/test_platform_http_integration.py`

## 环境变量

平台 HTTP 模式当前通过以下环境变量驱动：

| 变量 | 说明 | 必填 |
| --- | --- | --- |
| `MAT2PY_PLATFORM_BASE_URL` | 平台基础地址，例如 `http://platform.example.com` | 是 |
| `MAT2PY_PLATFORM_TOKEN` | 平台访问令牌，会作为 `Authorization: Bearer ...` 发送 | 否 |
| `MAT2PY_PLATFORM_TIMEOUT` | HTTP 请求超时，默认 `30` 秒 | 否 |

如平台接口路径与默认约定不同，可继续覆盖以下变量：

1. `MAT2PY_PLATFORM_PUBLISH_SUBMISSION_PATH`
2. `MAT2PY_PLATFORM_CLAIM_SUBMISSION_PATH`
3. `MAT2PY_PLATFORM_ACK_SUBMISSION_PATH`
4. `MAT2PY_PLATFORM_RUN_CONTEXT_PATH`
5. `MAT2PY_PLATFORM_UPDATE_STATUS_PATH`
6. `MAT2PY_PLATFORM_COMPLETE_JOB_PATH`
7. `MAT2PY_PLATFORM_DISCOVER_ASSETS_PATH`
8. `MAT2PY_PLATFORM_RESOLVE_BUNDLE_PATH`
9. `MAT2PY_PLATFORM_ACQUIRE_BUNDLE_PATH`
10. `MAT2PY_PLATFORM_MATERIALIZE_BUNDLE_PATH`
11. `MAT2PY_PLATFORM_EMIT_LOG_EVENT_PATH`
12. `MAT2PY_PLATFORM_PERSIST_RASTER_PATH`
13. `MAT2PY_PLATFORM_PERSIST_TABLE_PATH`
14. `MAT2PY_PLATFORM_PERSIST_MANIFEST_PATH`

## 默认平台接口约定

默认路径如下：

| 能力 | 默认路径 |
| --- | --- |
| 提交队列项 | `/api/v1/platform/submissions` |
| 认领队列项 | `/api/v1/platform/submissions/claim` |
| 确认队列项 | `/api/v1/platform/submissions/ack` |
| 构建运行上下文 | `/api/v1/platform/run-context` |
| 上报任务状态 | `/api/v1/platform/job-status` |
| 上报完成结果 | `/api/v1/platform/job-completions` |
| 发现资产 | `/api/v1/platform/data-assets/discover` |
| 解析 bundle | `/api/v1/platform/data-bundles/resolve` |
| 获取 bundle | `/api/v1/platform/data-bundles/acquire` |
| 物化 bundle | `/api/v1/platform/data-bundles/materialize` |
| 发送日志事件 | `/api/v1/platform/log-events` |
| 持久化栅格产品 | `/api/v1/platform/products/raster` |
| 持久化表产品 | `/api/v1/platform/products/table` |
| 持久化 manifest | `/api/v1/platform/manifests` |

## 启动方式

### 1. 启动 HTTP 受理进程

```bash
cd d:\Workspace\mat2py\Python
python -m service.http_server ^
  --host 127.0.0.1 ^
  --port 8000 ^
  --workspace D:\workspace\mat2py-platform ^
  --queue-backend platform ^
  --no-worker
```

说明：

1. `queue-backend=platform` 会切到 `PlatformHttpClient + PlatformJobQueue`
2. `--no-worker` 表示该进程只负责受理与查询

### 2. 启动独立 worker

```bash
cd d:\Workspace\mat2py\Python
python -m service.worker_process ^
  --workspace D:\workspace\mat2py-platform ^
  --queue-backend platform ^
  --persistent-state
```

说明：

1. `worker_process` 会复用同一套平台 HTTP 客户端
2. `persistent-state` 会把异步状态持久化到本地 `service_state/submissions`

## 推荐联调样本

### 样本 1：`ndvi_daily`

适用原因：

1. 输入结构最简单
2. 已完成统一数据访问迁移
3. 更适合作为平台 HTTP 首个冒烟样本

建议请求体：

```json
{
  "job_id": "platform-ndvi-001",
  "pipeline_name": "workflow",
  "module_name": "ndvi_daily",
  "task_type": "ndvi_daily",
  "time_range": {
    "start": "2025-01-01T00:00:00Z",
    "end": "2025-01-02T00:00:00Z"
  },
  "region": {
    "kind": "global",
    "value": {}
  },
  "datasource_selection": {
    "_data_access_requests": [
      {
        "dataset_name": "NDVI_16DAY_RASTER",
        "variables": ["ndvi"],
        "time_range": {
          "start": "2025-01-01T00:00:00Z",
          "end": "2025-01-02T00:00:00Z"
        }
      }
    ]
  },
  "algorithm_params": {},
  "output_spec": {
    "include_manifest": true
  }
}
```

### 样本 2：`station_daily`

适用原因：

1. 同时覆盖目录型和附属文件型 prepared-input
2. 能验证 `conversion_trace` 的资源级摘要是否完整

### 样本 3：`omega_block` 或 `retrieval_workflow` 的 `mode=omega`

适用原因：

1. 覆盖多输入 MAT 链路
2. 能验证高价值模块在平台模式下的真实可执行性

## 验收步骤

### 步骤 1：受理成功

调用：

```bash
curl -X POST http://127.0.0.1:8000/jobs/async ^
  -H "Content-Type: application/json" ^
  -d "@payload.json"
```

期望：

1. 返回 `202`
2. 返回 `submission_id`
3. 返回 `status=queued`

### 步骤 2：平台队列收到作业

平台侧应确认：

1. 已收到 `publish_submission`
2. 队列负载包含 `submission_id`
3. 负载中 `request` 为完整 `JobRequest` JSON

### 步骤 3：worker 成功认领

平台侧应确认：

1. worker 已调用 `claim_submission`
2. 作业从待处理状态转为执行中

### 步骤 4：运行状态上报

平台侧应确认：

1. 收到 `update_job_status`
2. 至少出现 `planning` 或 `running` 等状态

### 步骤 5：完成回写

平台侧应确认：

1. 收到 `complete_job`
2. 收到 `ack_submission`
3. manifest 已通过 `persist_manifest` 落库或登记

### 步骤 6：状态查询闭环

查询：

```bash
curl http://127.0.0.1:8000/jobs/{submission_id}
```

期望：

1. `state=completed`
2. `job_result.status=success`
3. `result_dto` 存在
4. `result_dto.artifacts.manifest_uri` 存在
5. 如果本次任务走了统一数据访问链路，`result_dto.conversion_trace` 与 `result_dto.conversion_trace_panel` 存在

## 通过标准

满足以下条件即可判定“平台 HTTP 模式端到端联调通过”：

1. 至少 1 个真实模块样本在 `queue-backend=platform` 下成功执行
2. 平台接口收到了 `publish -> claim -> status -> complete -> ack` 完整链路
3. `GET /jobs/{submission_id}` 能返回稳定 `result_dto`
4. `manifest`、`products`、`conversion_trace` 在服务层可查询

## 当前自动化覆盖

仓库内已有自动化测试：

1. `Python/tests/test_platform_http_integration.py`

它当前覆盖：

1. `PlatformHttpClient` 的队列、状态、数据源、日志、产物接口编解码
2. `build_platform_http_job_service()` 的异步端到端链路
3. `build_http_job_service(queue_backend="platform")` 的平台模式装配

这组测试可视为真实平台联调前的本地回归护栏。
