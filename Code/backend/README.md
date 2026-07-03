# Backend

这是项目当前的后端骨架，基于 `FastAPI`，并已具备 `workflow-runs` 的同步/异步编排入口。

## 当前能力

- `GET /health`
- `POST /workflow-runs`
- `GET /workflow-runs/{run_id}`
- `GET /workflow-runs/{run_id}/events`
- `GET /artifacts/{artifact_id}`
- `GET /algorithm/workflows`
- `GET /algorithm/workflows/{workflow_name}`
- `GET /algorithm/workflows/{workflow_name}/panel-schema`
- `GET /algorithm/workflows/{workflow_name}/ui-schema`
- 支持 `sync / celery` 两种工作流执行模式
- 支持结构化日志、结果大对象落盘与旧 `/tasks` 桥接

## 目录

```text
backend/
├─ app/
│  ├─ api/
│  ├─ core/
│  ├─ services/
│  ├─ tasks/
│  └─ main.py
└─ requirements.txt
```

## 本地启动

优先使用项目内的 `Env` 脚本：

```powershell
.\Env\Python312\install-backend-deps.ps1
.\Env\backend\dev.ps1
```

默认访问地址：

```text
http://127.0.0.1:8000
```

健康检查：

```text
http://127.0.0.1:8000/health
```

## 工作流执行模式

默认使用同步模式：

```powershell
$env:BACKEND_WORKFLOW_EXECUTOR="sync"
```

如需切换到 Celery + Redis：

```powershell
$env:BACKEND_WORKFLOW_EXECUTOR="celery"
$env:BACKEND_REDIS_URL="redis://127.0.0.1:6379/0"
$env:BACKEND_CELERY_BROKER_URL=$env:BACKEND_REDIS_URL
$env:BACKEND_CELERY_RESULT_BACKEND=$env:BACKEND_REDIS_URL
```

如需切到 MinIO 对象存储：

```powershell
$env:BACKEND_OBJECT_STORE_BACKEND="minio"
$env:BACKEND_MINIO_ENDPOINT="127.0.0.1:9000"
$env:BACKEND_MINIO_ACCESS_KEY="minioadmin"
$env:BACKEND_MINIO_SECRET_KEY="minioadmin"
$env:BACKEND_MINIO_BUCKET="workflow-artifacts"
$env:BACKEND_MINIO_SECURE="false"
```

可选安全项：

```powershell
$env:BACKEND_API_KEY="replace-with-your-own-secret"
```

如设置了 `BACKEND_API_KEY`，所有写接口都需要在请求头中附带 `x-api-key`。

性能与容量控制：

```powershell
$env:BACKEND_MAX_ACTIVE_RUNS="4"
$env:BACKEND_MAX_REQUESTED_OUTPUTS="6"
$env:BACKEND_PROVIDER_MAX_HOTSPOTS="200"
$env:BACKEND_PROVIDER_MAX_SERIES_POINTS="240"
$env:BACKEND_PROVIDER_TABLE_CHUNK_SIZE="100"
$env:BACKEND_PROVIDER_SERIES_CHUNK_SIZE="120"
$env:BACKEND_RESULT_INLINE_MAX_BYTES="131072"
```

- 超过 `BACKEND_MAX_ACTIVE_RUNS` 时，新工作流会被拒绝
- provider 热点和序列结果会按上限自动截断，避免单次运行占满内存
- 超过 `BACKEND_RESULT_INLINE_MAX_BYTES` 的结果不会继续走 `inline_data`，而会落到 artifact 存储并返回 `resource_url`
- 当热点表或长序列超过 chunk 阈值时，会自动切为 manifest + chunk 引用结构，避免一次性拼装超大结果

队列与调度标签：

```powershell
$env:BACKEND_WORKFLOW_QUEUE_REALTIME="realtime"
$env:BACKEND_WORKFLOW_QUEUE_ALGORITHM_REALTIME="realtime"
$env:BACKEND_WORKFLOW_QUEUE_ALGORITHM_STANDARD="standard"
$env:BACKEND_WORKFLOW_QUEUE_ALGORITHM_HEAVY="heavy"
$env:BACKEND_WORKFLOW_QUEUE_ALGORITHM_BATCH="batch"
$env:BACKEND_WORKFLOW_QUEUE_DOWNLOAD_REALTIME="download-realtime"
$env:BACKEND_WORKFLOW_QUEUE_DOWNLOAD_STANDARD="download-standard"
$env:BACKEND_WORKFLOW_QUEUE_ANALYSIS_STANDARD="standard"
$env:BACKEND_WORKFLOW_QUEUE_ANALYSIS_HEAVY="heavy"
$env:BACKEND_WORKFLOW_QUEUE_ANALYSIS_BATCH="batch"
```

- `WorkflowSubmitRequest` 现已支持 `priority`、`resource_profile`、`realtime_preferred`、`queue_tag`
- `WorkflowSubmitRequest` 现已支持 `algorithm_request`
- Celery 模式下会先区分两大通道，再按这些标签自动选择队列和优先级
- 当前双通道策略：
  - `algorithm_request -> algorithm`
  - `layer_preview / refresh_data / sync_demo -> download`
  - `analysis / export / custom -> analysis`
- 旧 `/tasks` 已映射为默认调度策略：
  - `layer_preview -> high + light + realtime`
  - `analysis -> normal + standard`
  - `export -> low + batch`

启动 API：

```powershell
.\Env\backend\dev.ps1
```

如需以 Celery 模式启动 API：

```powershell
.\Env\backend\dev-celery.ps1
```

启动 worker：

```powershell
.\Env\backend\worker.ps1
```

按通道拆分启动 worker：

```powershell
.\Env\backend\worker-download.ps1
.\Env\backend\worker-analysis.ps1
```

- `worker-download.ps1` 默认监听 `download-realtime,download-standard`
- `worker-analysis.ps1` 默认监听 `realtime,standard,heavy,batch`
- `worker.ps1` 现在支持：
  - `-QueueNames`
  - `-Concurrency`
  - `-WorkerName`
- worker 默认优先走“快速启动”：
  - 先激活现有虚拟环境
  - 探测 `fastapi / celery / redis / minio` 是否已可导入
  - 只有缺少依赖时才自动执行 `install-backend-deps.ps1`
- 如需强制在每次 worker 启动前重新安装依赖，可设置：
  - `BACKEND_WORKER_INSTALL_DEPS=true`
- 可通过 `Env\backend\dev.env.ps1` 覆盖：
  - `BACKEND_WORKER_ANALYSIS_QUEUES`
  - `BACKEND_WORKER_ANALYSIS_CONCURRENCY`
  - `BACKEND_WORKER_ANALYSIS_NAME`
  - `BACKEND_WORKER_DOWNLOAD_QUEUES`
  - `BACKEND_WORKER_DOWNLOAD_CONCURRENCY`
  - `BACKEND_WORKER_DOWNLOAD_NAME`
  - `BACKEND_WORKER_INSTALL_DEPS`

如本机已安装 Redis，或已将 `redis-server.exe` 放在 `Env\Redis\` 下，可直接启动：

```powershell
.\Env\backend\redis.ps1
```

检查 MinIO 连通性：

```powershell
.\Env\backend\minio-check.ps1
```

## 第一条真实 provider 工作流

当前已将 `lab-output` 图层接入 `algorithms/providers`：

- `lab-output` 走真实 provider 分发
- 非 provider 工作流已拆分为：
  - `analysis_workflow_service`
  - `download_workflow_service`
- provider 输出已统一映射为 `json / table / chart / text` 结果引用

如需把你自己的核心算法接入当前工作流，可直接指定动态入口：

```powershell
$env:LAB_OUTPUT_ALGORITHM_ENTRYPOINT="algorithms.providers.lab_output_example_impl:run_lab_output_algorithm"
```

当前版本出于安全考虑，不再接受请求侧传入 Python 模块入口；动态算法挂接仅允许通过服务端环境变量配置。

外部算法函数当前约定：

- 输入：`ProviderExecutionPayload`
- 输出：`dict`
- 推荐返回字段：`title`、`summary`、`metric_label`、`metric_unit`、`metric_value`、`hotspots`、`series`、`diagnostics`、`metadata`

## Python 算法桥接

- 当前已新增 `python_provider_bridge_service`
- 目标是把 `Code/algorithms/providers/Python` 作为完整算法任务子系统接入现有 `workflow-runs -> Celery worker` 主链
- 当前桥接策略：
  - FastAPI 仍作为统一平台入口
  - Celery + Redis 仍作为唯一正式任务调度器
  - worker 内部直接调用 `Python/service/job_api.py` 提供的 `JobService`
- 当前 `WorkflowSubmitRequest.algorithm_request` 会被映射为 Python 侧 `JobRequest` 负载
- 当前已接通的只读元数据接口：
  - `GET /algorithm/workflows`
  - `GET /algorithm/workflows/{workflow_name}`
  - `GET /algorithm/workflows/{workflow_name}/panel-schema`
  - `GET /algorithm/workflows/{workflow_name}/ui-schema`
- 当前运行结果映射策略：
  - `job_result + result_dto` 会回填到 `json` 结果引用
  - `manifest / metadata / log` 会优先映射为 `file` 结果引用
  - 仍由现有 artifact / spill / chunk 体系统一处理
- 当前桥接优先面向：
  - `module_name`
  - `workflow_name`
  - `workflow_definition`
- 后续应继续补齐：
  - `JobRequest` 专用共享协议
  - 真实样本任务联调
  - `result_dto.products` 到 WebGIS 预览层的进一步映射

## 状态存储

- `workflow-runs`、事件流和运行时配置当前默认写入 `Code/backend/.data/workflow_state`
- 底层存储已切换为 SQLite，而不是逐文件 JSON
- 旧 `/tasks` 接口状态也已切换到同一 SQLite 底座
- 旧 `/tasks` 已不再维护独立执行链，而是内部桥接到 `workflow-runs`
- 可通过 `BACKEND_WORKFLOW_STATE_DIR` 覆盖默认目录

## 日志与结果文件

- 结构化日志默认写入 `Code/backend/.data/logs/backend.log`
- 结果大对象默认写入 `Code/backend/.data/artifacts`
- 可通过以下环境变量覆盖：

```powershell
$env:BACKEND_LOG_DIR="custom-log-dir"
$env:BACKEND_RESULT_ARTIFACT_DIR="custom-artifact-dir"
$env:BACKEND_OBJECT_STORE_BACKEND="local"
```

- 日志字段默认包含：`request_id`、`run_id`、`task_id`
- 旧 `/tasks` 桥接到 `workflow-runs` 后，`task_id` 和 `run_id` 会同时出现在状态与日志诊断中
- 当前对象存储抽象已接入，但默认后端仍是 `local`
- 如切换到 `minio`，`GET /artifacts/{artifact_id}` 会返回对象下载跳转而不是本地文件响应
- 结果引用现支持：
  - 小结果：`inline_data`
  - 大结果：`resource_url + resource_backend + resource_key + resource_size_bytes`
  - 超长表/序列：`inline manifest + chunk resource_url`

## 下载与缓存骨架

- 下载主链已拆为：
  - `download_workflow_service`
  - `download_service`
  - `cache_service`
  - `download_tasks`
- 当前 `download_service` 已从纯计划骨架升级为“可执行下载骨架”：
  - 生成下载 ticket
  - 输出 `job_state` 下载状态机骨架
  - 输出 `source_fetch` 源抓取状态汇总
  - 生成下载 manifest artifact
  - 输出可直接访问的 `file` 结果引用
  - 在缓存命中时复用同一 manifest artifact
- 当前 `cache_service` 负责生成缓存键、记录缓存元数据、TTL 与 artifact 指针
- 默认缓存目录：

```powershell
$env:BACKEND_CACHE_DIR="Code/backend/.data/cache"
$env:BACKEND_CACHE_DEFAULT_TTL_SECONDS="1800"
```

- 这层现在还是最小骨架，但后续可平滑替换为真实下载器、缓存索引和对象存储清单服务
- 当前 `refresh_data / layer_preview / sync_demo` 返回中，除 JSON 摘要外，还会附带一个真实 `file` 类型结果引用，指向下载执行清单
- 当前 JSON 摘要中已包含：
  - `execution.job_state`
  - `execution.follow_up_policy`
  - `source_fetch`
  - 每个 `source_ref` 的 `fetch_status / fetch_stage / source_uri / estimated_bytes`
- 当 `job_state.next_action=dispatch_source_fetch` 时，系统现在会在 workflow 落库后继续触发下载 follow-up task：
  - `sync` 模式下直接本地执行并回写 run / event / manifest
  - `celery` 模式下派发到下载队列，再由 worker 回写 run / event / manifest
- 当前 follow-up task 已升级为“可重试抓取骨架”：
  - 会记录 `fetch_attempts / max_attempts / last_error / completed_at`
  - 会把 source 级状态推进到 `ready / retry_pending / failed`
  - 当前已验证 `partial_success` 与最大尝试次数命中后的 `failed` 状态
  - 当本次抓取未完全成功时，cache 状态会转为 `degraded`

## Provider 流式写出

- 当前 provider 结果写出已经支持按 `Iterable` 流式分 chunk 落盘，而不是每段都切片复制整块结果
- 这一步适合大热点表、长时间序列、下载清单、批量分析结果
- 当前 `lab-output` provider 已可通过以下参数模拟大结果压测：

```json
{
  "parameters": {
    "hotspot_count": 120,
    "series_step_hours": 1
  }
}
```
