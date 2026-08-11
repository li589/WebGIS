# 工程级代码审查：工作流 / 流水线 / 调度系统

- 审查日期：2026-08-11
- 审查范围：工作流编排（WorkflowRunner / WorkflowExecutor）、流水线派发（runner.dispatch）、调度系统（workflow_timer_service + Celery Beat）、运行态生命周期（submission / lifecycle / persistence）
- 基线：dev @ 5ec7180 / main @ 2e9b8ac
- 审查方式：静态通读核心路径（约 5000 行），重点为正确性、并发/竞态、幂等、失败处理、取消传播、状态一致性

---

## 一、系统架构速览

```
[API 提交] workflow_router → submission_service.submit_workflow
     │  └─ 原子容量预留(save_run_under_capacity, BEGIN IMMEDIATE) → 持久化 accepted/queued
     ├─ Celery 路径: dispatch_workflow_task(apply_async, 8s 超时) → process_workflow_run_task(acks_late)
     │     └─ process_workflow_run (幂等检查) → execute_workflow_task → bridge 链
     │           ├─ python_provider → algorithms WorkflowRunner(拓扑分层 + 节点并行)
     │           ├─ weather → backend WorkflowExecutor(顺序)
     │           ├─ gee → GEE WorkflowExecutor
     │           └─ lifecycle.finalize_* (success/failure/retry/timeout)
     └─ 同步路径: process_workflow_run 直接执行

[调度] Celery Beat(每分钟) → tick_workflow_timers → workflow_timer_service.tick()
     └─ reclaim_stale_claims → claim_due_timers(乐观 CLAIMED 哨兵) → submit_workflow → mark_fired
     另有 event 触发器(emit_event 同步) / 手动触发(trigger_manually)
```

---

## 二、高危问题（建议优先修复）

### H1. 派发超时竞态：`dispatch_workflow_task` 的 8s 超时可能产生"双语义"结果
`Code/backend/app/tasks/workflow_tasks.py:250-265`

```python
pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
fut = pool.submit(lambda: process_workflow_run_task.apply_async(**apply_async_kwargs))
async_result = fut.result(timeout=8)          # broker 慢时抛 TimeoutError
finally:
    pool.shutdown(wait=False, cancel_futures=True)  # 不中断已启动的线程
```

**问题**：`cancel_futures` 不能终止**已在运行**的线程。若 broker 只是"慢"而非"死"，后台线程可能在调用方抛"broker timeout"**之后**才把消息真正投递成功。此时：
- `_dispatch_async_workflow` 的 except 分支把 run 标记为 `failed`（submission_service.py:374-415）；
- 但 broker 实际收到了消息，worker 消费后 `process_workflow_run` 看到终态 failed → 幂等跳过 → **该 run 永远 failed 且算法从未执行**（状态与事实不符）；
- 或调用方（用户/前端）重试 → 生成**新 run_id** → 同一工作流重复提交 → 重复计算。

**影响**：状态机与真实执行脱节；重试路径放大重复计算。属于 at-least-once 与 at-most-once 之间的语义空洞。

**建议**：
1. 超时后 `fut.cancel()` + 短暂等待确认线程未完成投递；若线程仍在跑，无法撤回 → 应把 run 标记为 `queued`（而非 failed），让 worker 的幂等检查自然处理；
2. 或改用 broker 无关的投递确认（如先写 `dispatched=false` 状态，worker 消费后再翻转）；
3. 或在超时分支查询 broker 队列是否已含该 task_id，再决定 failed / queued。

### H2. at-least-once 投递 + 非可恢复执行 → worker 崩溃产生重复执行，且重复结果可覆盖失败终态
`Code/backend/app/services/workflow/submission_service.py:209-224`

```python
if current_run is not None and current_run.status in (succeeded, failed, cancelled):
    return  # 幂等：仅终态跳过
```

**问题**：`process_workflow_run_task` 配置 `acks_late=True` + `reject_on_worker_lost=True`（workflow_tasks.py:201-206），崩溃后任务重投，保证 at-least-once。但幂等检查**只挡终态**：
- worker 在 run 转为 `running` 之后、finalize 之前崩溃（长算法运行中）→ 重投任务看到 `running`（非终态）→ **整个工作流从头重跑** → 重复计算、重复产物、重复副作用；
- 更糟：若第一份执行已 `failed`（普通失败，非 watchdog），而重投的重复执行晚些才完成 → `finalize_workflow_success` 的 `_is_protected_terminal`（lifecycle_service.py:266-281）**只保护 cancelled 与 watchdog-failed**，普通 failed 不保护 → **重复执行的 success 会把合法 failed 覆盖为 succeeded**，状态被污染。

**影响**：长任务崩溃场景下重复执行 + 状态污染，直接违背"run_id 幂等"的注释承诺。

**建议**：
1. 执行前持久化"执行中令牌"（`executor_metadata.worker_task_id` + `started_at`），重投时若检测到**同任务、同 started_at** 的进行中记录则跳过；
2. 或对 `running` 状态的重复投递只做"确认存活"（探活原 worker），不重跑；
3. 或引入检查点/续跑（对 omega_sf 等长反演价值最大）；
4. 至少：`_is_protected_terminal` 应同时保护**所有终态**（failed 一律不被 success 覆盖），消除 M5 的覆盖污染。

### H3. `WorkflowPriority` 优先级在 Redis broker 下是 no-op
`Code/backend/app/tasks/workflow_tasks.py:240-245` + `Code/backend/app/core/celery_app.py:79-83`

```python
# dispatch 传入 priority=1/5/8/9（low/normal/high/critical）
"priority": {low:1, normal:5, high:8, critical:9}[payload.priority],
# 但 broker_transport_options 只有 visibility_timeout / socket_*
```

**问题**：Celery + Redis broker 的 `priority` 仅在配置了 `priority_steps`（且 `task_queue_max_priority`）时生效。当前未配置 → 所有 priority 静默等价，**高/紧急工作流与普通工作流同队列 FIFO**，`realtime_preferred`/`priority` 提升对调度无实际作用。

**影响**：优先级语义形同虚设；极端时 critical 天气瓦片任务被长 batch 任务阻塞。

**建议**：
1. `broker_transport_options` 增加 `"priority_steps": [0, 1, 5, 8, 9]` 与 `task_queue_max_priority: 9`（注意 Redis 队列需全部 worker 一致，且需压测确认）；或
2. 若优先级非硬需求，删除误导性的 priority 映射并注明"当前 broker 不区分优先级"。

---

## 三、中危问题

### M1. `process_workflow_run` 入口 `get_run` 在 try 之外 → 持久化异常会触发无界重投
`Code/backend/app/services/workflow/submission_service.py:210`

```python
def process_workflow_run(self, run_id, payload):
    current_run = self._repository.get_run(run_id)   # ← try 块之外
    if current_run is not None and current_run.status in (...): return
    now = ...
    with log_context(run_id=run_id):
        try:
            ...
        except SoftTimeLimitExceeded: ...
        except Exception: ...
```

**问题**：业务异常被内层 try/except 全部吞掉并 finalize（任务最终成功 ack），这是设计意图（"业务失败不重投"）。但 `get_run` 与幂等检查在 try 之外——若 SQLite 瞬时锁死/IO 异常持续，异常**冒泡出任务体** → 任务失败 → `acks_on_failure_or_timeout=False` → **消息重投 → 反复重试**（每次重试再撞锁）。虽然 `visibility_timeout=8100s` 使重投很慢，但这是无界循环，且每次重投浪费一次幂等读取。

**建议**：把 `get_run` 与幂等检查移入 try；或给任务配置 `max_retries`/`default_retry_delay` 上限；或在任务体最外层包一层"致命异常→记日志→return"。

### M2. 定时器 claim TTL（300s）与提交流程耗时存在双触发窗口
`Code/backend/app/services/workflow_timer_service.py:44,623-660,809-866`

`tick()` 中 claim 后**同步**执行 `_build_submit_payload` + `submission_service.submit_workflow`（模板校验 import、容量预留、8s 超时派发）。若提交耗时 > CLAIM_TTL_SECONDS=300s（broker 慢、模板校验慢、多定时器串行积压），下一次 tick（Beat 每分钟 + 手动 /tick 双入口）会把 `CLAIMED:` 哨兵按超时回收 → **同一定时器再次触发 → 重复提交**。

**概率较低但真实**：Beat 与 `/workflow-timers/tick` 是双触发源，设计上靠乐观 claim 防重，TTL 是兜底——兜底与"提交耗时"之间的空隙即风险窗。

**建议**：claim 时把 TTL 至少设为"预期最大提交耗时 × 2"，或将 submit_workflow 移出 claim 事务窗口（先快速 claim + 快速 mark_fired，再异步提交）；或 claim 哨兵内嵌心跳续约。

### M3. 取消路径：`terminate=True` 后立即置 cancelled，子进程树可能残留
`Code/backend/app/services/workflow/lifecycle_service.py:66-142` + `celery_app.py:227-239`

- Windows solo 池下 `terminate=True` 不保证清理子进程树（代码注释已自认）；
- 算法侧若用 `ProcessPoolExecutor`（节点并行 × 每节点进程），worker 被杀后**孤儿子进程可能继续写产物**；
- `cancel_workflow_run` 写入 cancelled 终态后，算法残存进程之后的写操作不再受状态约束（不再有"结果回写被拒绝"的保护）。

**建议**：取消时对 run 的 tmp 目录写入 cancel 旗标后，额外尝试回收已知子进程（或依赖算法的协作式检查点快速退出）；并在产物落盘侧增加"run 已终态则丢弃/标记"的保护（如已实现则确认覆盖所有产物入口）。

### M4. backend `WorkflowExecutor` 缺失上游输出时静默放行
`Code/backend/app/workflow_engine/executor.py:119-144`

```python
if edge.source_port in source_outputs:
    inputs[edge.target_port] = source_outputs[edge.source_port]
# 上游输出缺失 → 该输入被静默跳过，节点仍继续执行
```

**问题**：天气 DAG 等走 backend `WorkflowExecutor` 的路径，若上游节点失败/无输出，下游节点以**缺输入**继续执行 → 可能产出垃圾或运行时才炸。相比算法侧 WorkflowRunner（`_resolve_binding` 对 `node:` 缺失会抛 KeyError），此处缺失检测较弱。

**建议**：边引用的源端口缺失时显式抛错（或按 `continue_on_error` 策略明确跳过并记录 warning），不要让节点带缺输入运行。

### M5. 并发 finalize 无原子保护（读-改-写 TOCTOU）
`Code/backend/app/services/workflow/lifecycle_service.py:283-400` 等

`_is_protected_terminal`（读）与 `save_run_status`（写）不是同一事务。原 worker、看门狗、acks_late 重投三路并发收口时，任一路都可能读到旧状态后各自写入（SQLite 只保证写串行，不保证"检查与写"原子）。当前 protected 集合覆盖 cancelled + watchdog-failed，但普通 failed 可被迟到的 success 覆盖（见 H2 之 4）。

**建议**：`save_run_status` 对终态写入做条件更新（`WHERE status NOT IN (cancelled, failed, succeeded)` 或 `AND updated_at <= 传入值`），将"保护性终态"从应用层读检查下沉为 SQL 原子条件。

---

## 四、低危 / 设计建议

| # | 位置 | 说明 | 建议 |
|---|---|---|---|
| L1 | workflow_tasks.py:253 | 每次派发新建 `ThreadPoolExecutor` | 复用进程级共享 executor，减少线程抖动 |
| L2 | algorithms/workflow/executor.py:84-123 | 并行层任一节点失败 → 整层中止（无 continue-on-error） | 与 backend executor 的策略对齐或文档化差异 |
| L3 | algorithms/workflow/executor.py | 节点间无取消旗标检查 | 长节点内检查（omega_sf 已实现）；节点之间取消要等当前节点完成——文档化并结合 watchdog 兜底 |
| L4 | workflow_timer_service.py:76-156 | 自研 cron 解析：DOM+DOW 同时受限时按 AND（非 Vixie OR） | 已文档化；建议在创建 API 的校验消息中提示该语义差异 |
| L5 | workflow_timer_service.py:809-866 | `emit_event`/`tick` 内提交失败仅记 `last_error`，无告警/背压 | 接入失败计数告警或 dead-letter 标记 |
| L6 | workflow_timer_service.py:623-660 | claim 循环每定时器一个 `BEGIN IMMEDIATE` 事务 | 定时器数量大（数百）时合并为批量 claim，减少锁竞争 |
| L7 | workflow_tasks.py:176-194 | `_is_valid_queue_tag` 迭代 `dir(settings)` 匹配队列值 | 改为从 settings 显式队列集合派生，避免属性名耦合 |
| L8 | runner/dispatch.py:858-881 | 编程异常（AttributeError 等）向上传播、其余降级 JobResult(failed) | 正确；建议补充 run_job 级 `finally` 兜底 `scheduler_adapter.complete` 的异常保护 |

---

## 五、做得好的方面

- **容量预留原子化**：`save_run_under_capacity` 用 `BEGIN IMMEDIATE` 关闭 TOCTOU（workflow_repository.py:325）。
- **定时器防双触发**：乐观 `CLAIMED:` 哨兵 + `fetch_due_timers` 过滤 + 僵死回收 TTL，Beat 与 API 双入口安全（workflow_timer_service.py）。
- **保护性终态**：cancelled / watchdog-failed 不被后续收口覆盖，看门狗 + 幂等 + 受保护终态构成三层防线（lifecycle_service.py）。
- **长任务超时配置**：visibility_timeout(8100) > time_limit(7500) 防提前重投；per-task 软/硬超时合理（workflow_tasks.py:199-214, celery_app.py:74-83）。
- **可观测性**：节点级进度、stage start/end、转换 trace、task_failure 信号聚合（celery_app.py:103-114）。
- **递归防护**：`push_runtime_call` 深度 8 上限 + 环路检测（runner/call_guard.py）。
- **队列路由表化**：`_CHANNEL_PROFILE_QUEUE_MAP` + queue_tag 白名单（workflow_tasks.py:111-194）。

---

## 六、修复优先级建议

1. **P0**：H1（派发超时双语义）→ 决定超时后状态为 queued 或做投递确认；
2. **P0**：H2（重投重复执行 + 终态覆盖）→ 执行中令牌 + `_is_protected_terminal` 保护所有终态；
3. **P1**：H3（priority no-op）→ 配 priority_steps 或删除映射；
4. **P1**：M1（get_run 移入 try / 重投上限）、M2（claim TTL 与提交耗时协调）；
5. **P2**：M3-M5 + 低危项按迭代窗口消化。
