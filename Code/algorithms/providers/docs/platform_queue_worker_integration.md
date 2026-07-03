# 平台队列与 Worker 集成说明

## 1. 文档定位

本文档说明 Python 计算包如何通过平台队列、worker 和平台侧回调能力接入更完整的后端系统。

本文档关注的是：

- 任务如何进入队列
- worker 如何消费任务
- 状态如何回写
- 日志如何上报
- 产物如何持久化

## 2. 当前状态

当前仓库已经具备以下相关能力：

- HTTP 接收层
- 本地 file queue
- worker process
- 平台 adapter 骨架
- mock 平台 client
- 结果与 manifest 封装

这意味着 Python 计算包已经不只是单机脚本入口，而是具备分进程、可桥接平台的运行方式。

## 3. 队列与 worker 的角色

### 3.1 队列

队列负责：

1. 接收提交请求
2. 记录待处理任务
3. 为 worker 提供可消费作业
4. 支持 claim / ack / status 更新语义

### 3.2 Worker

worker 负责：

1. 从队列取任务
2. 构建或接收运行时上下文
3. 调用 `run_job()` 或 `JobService`
4. 回写运行状态与结果

## 4. 当前可用实现

当前代码目录里已经具备：

- `service/job_queue.py`
- `service/async_jobs.py`
- `service/worker.py`
- `service/worker_process.py`
- `service/platform_job_queue.py`
- `service/platform_client_mock.py`
- `service/platform_adapters.py`
- `service/platform_service_factory.py`

## 5. 平台接入方式

### 5.1 回调式骨架

如果平台已经有现成的回调方法，可以先用：

- `CallbackSchedulerAdapter`
- `TrackingSchedulerAdapter`
- `CallbackDataSourceAdapter`
- `CallbackLoggerAdapter`
- `CallbackProductSink`

### 5.2 平台客户端式接入

如果平台已经有较稳定的 `platform_client`，可以使用真实 adapter：

- `PlatformSchedulerAdapter`
- `PlatformDataSourceAdapter`
- `PlatformLoggerAdapter`
- `PlatformProductSink`

### 5.3 mock 平台联调

如果平台尚未完全打通，可以先用：

- `PlatformClientMock`
- `build_platform_job_service(...)`
- `build_platform_mock_service(...)`

## 6. 推荐执行链路

推荐的生产化链路是：

```text
HTTP / platform submit
  -> queue backend
  -> worker claim
  -> JobService / run_job
  -> manifest / result / log
  -> status ack / complete
```

## 7. 本地开发模式

当前仓库也支持本地 file queue + persistent state 的联动方式，适合先做分进程联调，再替换成平台真实队列。

## 8. 需要关注的边界

### 8.1 幂等性

worker 侧应避免重复执行同一提交。

### 8.2 状态回写

应保证 queued、running、completed、failed 等状态能稳定回写。

### 8.3 产物持久化

worker 不应只返回内存对象，还应确保 manifest、log 和产品引用可被后续查询。

### 8.4 错误收口

任务失败时，应返回结构化错误，而不是仅抛出裸异常。

## 9. 与后端的关系

后端不应该把 worker 逻辑写死在 API 层，而应该通过 service 和 queue 的抽象来组织任务执行。

## 10. 结论

队列与 worker 集成的目标，是让 Python 计算包同时支持：

1. 本地联调
2. 分进程执行
3. 平台队列执行
4. 产物与状态可查询
5. 与 WebGIS 后端协同运行
