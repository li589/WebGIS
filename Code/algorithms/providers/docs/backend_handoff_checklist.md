# 后端交接清单

## 1. 交接目标

本清单用于把当前仓库中的 `Python/` 计算包交接给后端同事，准备放置到：

```text
Code\algorithms\providers
```

当前建议的交付定位是：

1. 可作为“后端联调版”接入
2. 适合开始平台接口联调、任务链路验证、DAL 输入契约验证
3. 不建议直接标记为“最终封版”

## 2. 建议放置方式

建议后端在代码库中按如下方式放置：

```text
Code/
  algorithms/
    providers/
      Python/
```

说明：

1. 默认以整个 `Python/` 目录作为 provider 计算包
2. 不建议拆散内部子目录结构，因为当前导入路径依赖 `contracts`、`runner`、`service`、`workflow`、`modules`、`pipelines` 等并列包结构
3. 启动、测试和文档中的相对路径说明，也默认基于 `Python/` 根目录

## 3. 当前可交付能力

当前版本已经具备以下能力，可进入后端联调：

1. 同步任务入口：`run_job()`
2. 服务化入口：`JobService`
3. 异步任务提交、排队、执行、状态查询
4. 平台 HTTP 队列模式：`PlatformHttpClient + PlatformJobQueue`
5. 预定义 workflow、显式 `workflow_definition`、单模块 workflow 三种执行模式
6. `describe_workflow`、`panel_schema`、`ui_schema` 元数据接口
7. `_data_access_requests` 统一数据访问输入
8. `_prepared_inputs` prepared 输入透传与消费
9. prepared-input 多资源按 metadata 精确选择

## 4. 本轮已修复的关键问题

以下问题已经不是当前交接阻塞项：

1. 异步 worker 在执行异常时的确认语义错误
   - 已避免任务在异常时被静默 ack / 删除
2. `retrieval_workflow` 的 preview/schema 固定偏向 `dh`
   - 已补齐 `dh / ddca / omega` 多模式预览
3. 显式 `workflow_definition` 未兼容 `_data_access_requests`
   - 已支持 inline workflow 使用 DAL 风格输入
4. `_prepared_inputs` 多资源消费只取首个路径
   - 已支持按资源 `metadata` 中的 `role / target_key / source_key / consumer_key` 优先匹配

## 5. 后端必须了解的边界

当前仍需明确以下边界，避免联调误判：

1. 当前版本适合“联调接入”，不是“全量稳定回归后的最终上线包”
2. 普通 pipeline 在 `run_job()` 中会优先按 `required_datasets` 自己走 prepare 流程
3. 普通 pipeline 不会自动把外部手工注入的 `_prepared_inputs` 当作“跳过 prepare”的直接输入
4. `retrieval_workflow` 的元数据接口现在是“多模式合并展示”
5. 因此某些 mode-specific 字段会被展示为“可见但非所有模式都必填”

如果后端后续希望支持：

1. 直接向普通 pipeline 注入 `_prepared_inputs`
2. 并跳过 prepare 阶段

则需要单独作为后续能力开发，不属于本次交接范围。

## 6. 推荐后端联调顺序

建议按下面顺序推进：

1. 校验 `Python/` provider 在目标仓库内的导入路径是否正常
2. 校验平台 HTTP 配置与鉴权
3. 校验异步任务提交、状态推进、完成回写
4. 校验 workflow catalog / describe / panel / ui-schema
5. 校验 `_data_access_requests` 契约
6. 校验 prepared-input 多资源场景
7. 跑 1 到 2 个真实任务样本做端到端联调

## 7. 建议优先联调的接口

### 7.1 任务执行链路

1. `submit_job`
2. `submit_job_async`
3. `get_job_status`

### 7.2 workflow 元数据链路

1. `GET /api/v1/workflows`
2. `GET /api/v1/workflows/{workflow_name}`
3. `GET /api/v1/workflows/{workflow_name}/panel-schema`
4. `GET /api/v1/workflows/{workflow_name}/ui-schema`

### 7.3 平台 HTTP 队列链路

1. `publish_submission`
2. `claim_submission`
3. `ack_submission`
4. `update_job_status`
5. `complete_job`

## 8. 建议优先联调的任务样本

### 样本 1：`ndvi_daily`

原因：

1. 输入最简单
2. 适合首个冒烟
3. 已进入统一数据访问链路

### 样本 2：`station_daily`

原因：

1. 目录与附属文件输入更完整
2. 更容易验证 prepared-input 与 conversion trace

### 样本 3：`retrieval_workflow`，`mode=omega`

原因：

1. 能覆盖多输入 MAT
2. 能覆盖 workflow 多模式元数据
3. 是高价值链路

## 9. 建议验收点

后端联调时至少确认以下几点：

1. 异步任务状态能从 `accepted/queued/running` 正常推进到 `completed/failed`
2. 执行异常时不会发生任务静默丢失
3. `retrieval_workflow` 的 `omega_fixed_mat`、`exp0_calib_mat` 能在 workflow 元数据接口中看到
4. 显式 `workflow_definition` 使用 `_data_access_requests` 时不会被静态校验误拒
5. prepared-input 多资源场景中，`daily_mat_sources` 不会错误复用同一个目录到多个目标键
6. `result_dto` 能稳定返回 `manifest`、`products` 以及相关结构化字段

## 10. 推荐后端查看的文档

交接时建议后端至少同时阅读以下文档：

1. [backend_integration_contract.md](file:///d:/Workspace/mat2py/docs/backend_integration_contract.md)
2. [platform_http_e2e_validation.md](file:///d:/Workspace/mat2py/docs/platform_http_e2e_validation.md)
3. [unified_data_access_migration_batches.md](file:///d:/Workspace/mat2py/docs/unified_data_access_migration_batches.md)
4. [platform_queue_worker_integration.md](file:///d:/Workspace/mat2py/docs/platform_queue_worker_integration.md)
5. [minimal_job_http_service.md](file:///d:/Workspace/mat2py/docs/minimal_job_http_service.md)

## 11. 推荐后端先跑的回归

如果后端在目标仓库落包后希望先做冒烟，建议至少跑以下测试：

```bash
cd Code\algorithms\providers\Python
python -m unittest tests.test_job_queue_worker
python -m unittest tests.test_job_request_validation
python -m unittest tests.test_job_service
python -m unittest tests.test_data_access_consumers
python -m unittest tests.test_native_modules.NativeModuleTests.test_timeseries_bundle_pipeline_execute_uses_matching_multi_resource_prepared_inputs
```

## 12. 交接结论

结论如下：

1. 当前版本可以交接给后端开始联调
2. 当前版本不建议直接定义为最终发布版
3. 若后端联调中不新增协议变更，后续工作重点应转向扩大回归与收口边界能力
