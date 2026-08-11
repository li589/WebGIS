# 功能全景核查报告：8 大领域

- 核查日期：2026-08-11
- 基线：dev @ 5ec7180 + 审查修复（H1/H2/H3/M2/M4 已合入工作区）
- 核查方式：领域映射 → 靶向测试 → 关键实现深查

---

## 核查总览

| # | 领域 | 状态 | 依据 |
|---|---|---|---|
| 1 | 任务提交 | 🟢 绿 | 靶向测试 + submission_service 深查 |
| 2 | 调度 | 🟢 绿 | 靶向测试 + timer/Celery Beat 深查 |
| 3 | 配置设置工作流 | 🟢 绿 | 靶向测试 + config 热更新深查 |
| 4 | 流水线功能 | 🟢 绿 | 靶向测试 + run_job 深查 |
| 5 | 数据加载和缓存 | 🟢 绿 | 靶向测试 + data_access/reuse_cache 深查 |
| 6 | 图层显示 | 🟢 绿 | 前端 55 文件/309 测试全绿 |
| 7 | 实时动态显示已处理部分 | 🟢 绿 | workflow-poller 机制深查 + 兜底闭环确认 |
| 8 | 时间轴对齐显示 | 🟢 绿（1 项建议） | 对齐算法深查；缺专项单测 |

**测试实证：后端领域靶向 201 passed；前端显示域 55 文件 / 309 tests passed；全量后端 758 passed。**

---

## 各领域详情

### 1. 任务提交 ✅
- **提交链路**：workflow_router → `submission_service.submit_workflow` → 原子容量预留（`save_run_under_capacity`，BEGIN IMMEDIATE 关 TOCTOU）→ accepted 持久化 → Celery 派发（8s 超时保护）。
- **提交期校验**：requested_outputs 上限、template 静态校验（缺失 datasource/algorithm key → 422 结构化 issue）。
- **审查修复已含**：H1 派发超时不再误标 failed → queued（`dispatch_ack_uncertain`）；H2b 重投追踪。
- **测试**：test_workflow_routes / test_business_regression 等 ✅

### 2. 调度 ✅
- **workflow_timer_service**：cron（自研解析，Asia/Shanghai 墙钟）/ interval（≥60s）/ event 三种触发器；CLAIMED 乐观哨兵防 Beat+API 双触发；claim TTL 600s（M2 已修）；stale claim 回收。
- **Celery Beat**：timer tick（每分钟）、天气小时刷新、Open-Meteo 同步（每 6h）、runs/cache 清理（每日 03:00/03:30 UTC）、看门狗（每 15min）。
- **测试**：test_workflow_timer_service / test_celery_tasks ✅

### 3. 配置设置工作流 ✅
- config_routes（读/写鉴权、RBAC viewer/operator/admin）+ config_service + `effective_config.hydrate` 热应用 + `restart_backend_service` 进程组重启。
- 动态配置（限流/并发/容量上限）热生效；环境型配置写 .env 后调度重启，前端有提示。
- **测试**：test_config_contracts / test_config_security / test_config_write_offload / test_concurrency_config ✅

### 4. 流水线功能 ✅
- `runner.run_job`：请求归一 → workflow 解析（named/single-module/canvas）→ 图编译校验 → 数据准备 → WorkflowRunner 执行（拓扑分层 + 节点并行）→ manifest 输出；legacy pipeline 兼容路径。
- 编程异常向上传播、运行异常降级 JobResult(failed)（含 call_chain 诊断）。
- **测试**：test_workflow_graph_compiler / test_workflow_dry_validate / test_workflow_request_resolver / test_workflow_bridge_resolution / test_workflow_repository ✅

### 5. 数据加载和缓存 ✅
- data_access 协调器（v1/v2 双协议、materialization、conversion trace、cache_hits）；`_prepared_inputs` 注入工作流。
- **workflow reuse_cache**：omega_sf 块级复用（`resolve_reuse_output_dir`），失败重试注入 reuse 参数，避免重复反演已完成的块。
- data_cache_service：静态缓存 TTL 可配（默认不限）+ 过期清理。
- **测试**：test_data_cache_service / test_node_cache_cleanup / test_open_portal_data_access / test_layer_remote_uris ✅

### 6. 图层显示 ✅
- 前端：catalog/active-layers/run-layers 状态模型 + MapCanvas 渲染 + overlay-image-module + symbology + layer-stack-sync。
- 后端：unified/overlay/weather 瓦片服务。
- **测试**：前端 map/layer-sidebar/info-panel 55 文件 309 tests 全绿；后端瓦片测试 ✅

### 7. 实时动态显示"已处理部分" ✅
- **workflow-poller.ts**（前端核心）：
  - `pollWorkflowRun` 增量拉取事件（`afterEventId` 游标，limit 24）；
  - 自适应轮询：事件活跃 → 快速间隔，空闲 → 慢间隔；
  - `block_commit` / `block_refresh` / `artifact` 阶段 → `applyWorkflowEventsToJobLayer` 渐进更新图层（omega_sf 块反演逐块上图）；
  - 视口刷新陈旧守卫、网络抖动不误判失败、终态权威快照同步。
- **兜底闭环**：H1 修复后停在 queued 的 run，`cleanup_stale_workflow_runs`（non_terminal_queue_statuses 含 queued + 无存活 task_id）会清理；running 卡死由看门狗兜底。
- **测试**：workflow-overlay-render-hint / weather-overlay 等 ✅

### 8. 时间轴对齐显示 ✅（1 项建议）
- **weather-timeline.ts**：0.25h 量化（`quantizeClockHour`）→ 精确匹配（同日期+钟点）→ 最近回退（`findNearestForecastHour`）→ 最新有效时次（`findLatestValidCoverageInstant`）；`isDateHourWithinCoverage` 覆盖判定（valid_times 优先）。
- **layer-timeline.ts**：粒度段生成（`generateTimelineSegments`）、刻度抽稀（`computeVisibleTickIndices`）。
- TimelineScrubber（步进/拖动/粒度切换）驱动 currentDate/currentHour → 图层时次对齐。
- ⚠️ **建议 A1**：weather-timeline / layer-timeline 工具函数**无专项单测**（前端 309 tests 未覆盖对齐回退、覆盖边界、0.25h 量化、跨日/跨月边界）。建议补充。

---

## 建议（按优先级）

| # | 优先级 | 建议 |
|---|---|---|
| A1 | 中 | 为 weather-timeline/layer-timeline 补专项单测（精确→最近→最新回退、覆盖边界、跨日/跨月、0.25h 量化） |
| A2 | 低 | 实时显示基于轮询（无 SSE/WebSocket）——单机构部署够用；多客户端并发时轮询放大负载，可观察是否需要推送 |
| A3 | 低 | config 热更新中 env 型配置需重启进程组生效——已有提示机制，可考虑前端明确标注"需重启"的字段 |
| A4 | 低 | workflow-poller 事件 limit=24 固定值——大块反演事件密集时可观察是否需要按事件类型分流 |

---

## 结论

8 大领域全部核查通过（测试实证 + 实现深查）。代码审查修复（H1/H2/H3/M2/M4）已全部通过回归（758 passed），且 H1 的 queued 兜底与既有 cleanup/watchdog 形成完整闭环。唯一实质性缺口是时间轴工具函数的专项单测（A1），建议后续补充。
