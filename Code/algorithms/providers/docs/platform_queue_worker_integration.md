# 平台队列与 Worker 集成说明

## 目的

本文档说明当前仓库如何支持以下目标链路：

```text
提交任务 -> 平台队列 -> worker 执行 -> 查询状态
```

它关注的是服务化与调度化边界，不涉及 OMEGA 算法本身。

## 当前对应代码

当前这条链路主要由以下文件组成：

1. `Python/service/job_api.py`
2. `Python/service/http_server.py`
3. `Python/service/job_queue.py`
4. `Python/service/worker.py`
5. `Python/service/platform_adapters.py`
6. `Python/service/platform_templates.py`
7. `Python/service/async_jobs.py`

其中：

1. `job_queue.py` 现在提供可替换的 `JobQueueBackend` 边界，默认实现为 `InMemoryJobQueue`
2. `async_jobs.py` 现在提供可替换的 `AsyncJobStore` 边界，默认实现为 `AsyncJobRegistry`
3. 本地还补了一份文件持久化状态存储：`FileAsyncJobRegistry`
4. 本地还补了一份文件队列实现：`FileJobQueue`
5. 队列侧也补了平台接入模板：`PlatformJobQueueTemplate` / `PlatformJobQueue`
6. 独立 worker 进程入口位于：`Python/service/worker_process.py`

## 当前工作流

### 1. 提交任务

HTTP 入口：

1. `POST /jobs`
2. `POST /jobs/async`
3. `POST /jobs/validate`

其中：

1. `POST /jobs` 为同步执行
2. `POST /jobs/async` 为异步入队
3. `POST /jobs/validate` 只做校验，不执行任务

### 2. 入队

当前最小异步模型会把请求提交到：

1. `InMemoryJobQueue`

提交成功后返回：

1. `submission_id`
2. `job_id`
3. `status_url`

### 3. worker 执行

当前 worker 入口位于：

1. `JobQueueWorker`

它的职责是：

1. 从队列中取出异步作业
2. 更新异步状态为 `running`
3. 调用 `run_job()`
4. 回写最终 `JobResult`
5. 把最终响应写回 registry

### 4. 查询状态

查询入口：

1. `GET /jobs/{submission_id}`

当前会返回：

1. `state`
2. `scheduler_status`
3. `status_detail`
4. `run_id`
5. `job_result`
6. `final_response_status`
7. `final_response_body`

## 状态含义

当前异步状态最少包括：

1. `accepted`
2. `queued`
3. `running`
4. `completed`
5. `failed`

推荐平台映射方式：

1. `accepted`：服务已受理，但还未真正入队完成
2. `queued`：已进入队列，等待 worker 消费
3. `running`：worker 已开始执行
4. `completed`：任务执行成功
5. `failed`：任务执行失败或最终响应失败

## 平台 adapter 两种接法

### 方案 A：回调骨架

适合平台已有现成函数回调时，直接使用：

1. `CallbackSchedulerAdapter`
2. `TrackingSchedulerAdapter`
3. `CallbackDataSourceAdapter`
4. `CallbackLoggerAdapter`
5. `CallbackProductSink`

特点：

1. 接入成本最低
2. 适合先做联调
3. 适合把平台已有函数快速挂上来

### 方案 B：类模板

适合平台要写正式 adapter 类时，直接继承：

1. `PlatformSchedulerAdapterTemplate`
2. `PlatformDataSourceAdapterTemplate`
3. `PlatformLoggerAdapterTemplate`
4. `PlatformProductSinkTemplate`

特点：

1. 更适合长期维护
2. 更适合接正式平台 SDK 或网关客户端
3. 更接近“真实 adapter 实现”

### 方案 C：首版真实 adapter

当前仓库已经补上第一版可直接实例化的真实 adapter 实现：

1. `PlatformSchedulerAdapter`
2. `PlatformDataSourceAdapter`
3. `PlatformLoggerAdapter`
4. `PlatformProductSink`

这些类支持两种接法：

1. 直接传 `platform_client`
2. 单独传具体函数回调

默认约定的 `platform_client` 方法名如下：

1. `build_run_context(request)`
2. `update_job_status(job_id, run_id, status, detail)`
3. `complete_job(result)`
4. `discover_assets(request)`
5. `resolve_bundle(request)`
6. `acquire_bundle(bundle)`
7. `materialize_bundle(bundle)`
8. `emit_log_event(event)`
9. `persist_raster(product)`
10. `persist_table(product)`
11. `persist_manifest(manifest)`

这意味着平台如果已有统一 client 对象，可以先按这些方法名快速对接；如果方法名不同，也可以直接走显式函数注入。

### 方案 D：平台 mock 闭环

当前仓库还提供了一个可直接运行的 mock 平台闭环：

1. `PlatformClientMock`
2. `build_platform_job_service(...)`
3. `build_platform_mock_service(...)`

适用场景：

1. 本地联调整条服务链
2. 演示 `提交 -> 队列 -> worker -> 查询状态`
3. 在没有真实平台 SDK 前先验证接入边界

其中：

1. `PlatformClientMock` 负责记录状态、日志、产物、manifest，以及 `publish_submission / claim_submission / ack_submission`
2. `build_platform_job_service(...)` 用真实 adapter 组装 `JobService + JobQueueWorker`
3. `build_platform_mock_service(...)` 进一步把 mock client 一并创建出来
4. `build_platform_mock_service(...)` 当前默认会启用 `use_platform_queue=True`

这意味着当前 mock 平台默认已经不是“内存队列伪装平台”，而是会真实经过：

1. `PlatformJobQueue`
2. `platform_client.publish_submission(...)`
3. `platform_client.claim_submission(...)`
4. `platform_client.ack_submission(...)`

## 推荐的真实平台落地方式

建议平台按以下顺序接入：

### 第一步：服务与协议收口

1. 先使用 `POST /jobs/async`
2. 统一请求体为 `JobRequest`
3. 用 `GET /jobs/{submission_id}` 做状态查询

### 第二步：替换本地队列

当前默认是：

1. `InMemoryJobQueue`

平台接入时建议替换为：

1. Redis / MQ / 平台自有任务队列
2. 或平台自己的任务表 + 拉取器

如果还处在单机联调阶段，现在也可以先过渡到：

1. `FileJobQueue`
2. `PlatformJobQueueTemplate`
3. `CallbackJobQueueBackend`
4. `PlatformJobQueue`

### 第三步：替换本地 adapter

当前默认是：

1. `LocalSchedulerAdapter`
2. `LocalDataSourceAdapter`
3. `ConsoleLoggerAdapter`
4. `LocalProductSink`

平台接入时建议替换为：

1. 平台真实 scheduler adapter
2. 平台真实 datasource adapter
3. 平台真实 logger adapter
4. 平台真实 product sink

如果还在联调阶段，也可以先这样过渡：

1. 保留 `InMemoryJobQueue`
2. 使用 `PlatformClientMock`
3. 使用 `build_platform_mock_service(...)`

如果当前还不准备切换到真实持久化队列，但希望查询状态能跨进程重启保留，仓库内也可以先过渡到：

1. `build_local_persistent_job_service(...)`
2. 或给 `build_platform_job_service(...)` 显式注入 `FileAsyncJobRegistry`

如果希望连队列也先支持分进程拆分，本地推荐组合现在变成：

1. `FileJobQueue`
2. `FileAsyncJobRegistry`
3. `service.http_server --queue-backend file --persistent-state --no-worker`
4. `service.worker_process --queue-backend file --persistent-state`

### 第四步：独立部署 worker

当前本地最小服务会自动启动一个内存 worker，适合联调。

平台化后建议：

1. HTTP service 只负责受理和查询
2. worker 进程独立部署
3. worker 从平台队列消费任务
4. worker 执行后回写统一状态中心

## 当前边界

当前已经具备：

1. 同步执行模型
2. 最小异步入队模型
3. worker 消费执行模型
4. 状态查询模型
5. 可替换的 queue / async store 边界
6. 文件持久化状态存储
7. 文件队列实现，可支持单机分进程联调
8. 独立 worker 进程入口
9. 平台 adapter 回调骨架
10. 平台 adapter 类模板
11. 平台真实 adapter 首版实现

当前仍未具备：

1. 持久化队列
2. 分布式共享 job store
3. 生产级认证鉴权
4. 多 worker 协调与幂等治理
5. SLA、重试和死信策略

## 推荐下一步

如果目标是尽快接入 WebGIS 后端调度器，当前最合理的下一步是：

1. 先选定平台队列承载方式
2. 先把平台现有 client 映射到 `PlatformSchedulerAdapter`
3. 再把产物落盘/登记链映射到 `PlatformProductSink`
4. 最后把 worker 独立为平台进程

这样可以在不改算法主链的前提下，把当前仓库平滑升级为真正的平台执行节点。
