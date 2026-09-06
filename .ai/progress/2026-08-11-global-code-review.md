# 2026-08-11 全局代码审查 + 编译门 + 全栈重启

## 结论

**可继续联调。** 未发现 Critical 阻断项；编译门通过；全栈已干净重启；抽样冒烟 `gis_buffer_zonal_basic` 成功。

## 审查范围（未提交高风险 diff）

| 区域 | 结论 |
|------|------|
| `workflow_request_resolver` 多模块 exclusivity / `time_range` 合成 | OK：flatten 后 pop `module_name`，definition 仍在时 early-return，不再 re-setdefault |
| `python_provider_request_builder` time_range 修复 | OK |
| `lifecycle_service` 全终态保护 | OK：failed/cancelled/succeeded 均不可被迟到 success 覆盖 |
| `submission_service` dispatch 不确定 → `queued` + `dispatch_ack_uncertain` | OK：依赖 watchdog 回收；**勿默认 flush Redis**（`priority_steps` 兼容） |
| `celery_app` `priority_steps` / `task_queue_max_priority=9` | OK：与 dispatch 映射 1/5/8/9 对齐 |
| `executor` 缺上游输出 → `KeyError` | **Medium**：对必选边正确；若存在可选端口边可能误伤（未证实为当前种子路径阻断） |
| `workflow_timer_service` `CLAIM_TTL_SECONDS=600` | OK |
| `layer_catalog` / `method-*` 种子 | OK：`/layers` = 41，含 4 个 `method-*` |
| FE Dashboard / workflow-runner time_range 注入 | OK；编译期补了节点松散类型断言 |

## Critical / Medium / Low

### Critical
无。

### Medium
1. **Executor 缺上游输出一律抛错** — 可选端口若走同一边解析路径可能误失败。当前 GIS/SF 抽样未触发。后续若有 optional edge，应在解析边时跳过非必选口。
2. **Bugbot / Security Review 子代理不可用** — Cursor Agent usage limit；本次以人工审查代替。额度恢复后可补跑。

### Low
1. FE eslint 仍有既有 `no-explicit-any` warnings（0 errors），与本次改动无关。
2. ~~stop 后 `:8000` 曾残留 ghost uvicorn（父 PID 消失、子进程仍听端口）；需杀 `spawn_main` 子进程后再 start~~ **✅ 已修复（2026-08-12）**：`launch/commands.py` `cmd_stop()` pattern 列表补充 `spawn_main` + `uvicorn`，stop 后无残留。见 `2026-08-12-p2-quick-wins.md`。

## 本轮最小修复

1. `Test/backend/test_workflow_watchdog_finalize.py` — 补 `test_finalize_success_skips_ordinary_failed`（普通 failed 终态保护）。
2. `Code/frontend/src/views/DashboardView.vue` — `canvasNodes` 统一为 `Array<Record<string, unknown>>`，修复 `vue-tsc` 对 `params`/`node_type` 的报错。

## 编译门

| 门 | 结果 |
|----|------|
| pytest（resolver / stub seeds / bridge / watchdog finalize / routes / celery / timer） | **69 passed** |
| `npm run check:catalog` | OK（FE=37 BE=41，BE-only=`method-*`×4） |
| `npm run lint` | 0 errors / 9 warnings（既有） |
| `npm run build` | OK（修 DashboardView TS 后） |

## 重启与冒烟

1. `launch.py stop` → 清 `:8000` 残留子进程 → `BACKEND_PORT=8000`
2. `start docker` → `start backend` → `start frontend`
3. `GET /health` → ok
4. `GET /layers` → **41**，含 `method-smap-omega-doy-dynamic` 等 4 个
5. Frontend `:5175` → 200
6. `Tools/smoke_system_workflows.py --only gis_buffer_zonal_basic --skip-tiles --skip-omega` → **succeeded** `run-8105c8bfb4a2`（~4.1s）

未执行 `launch.py flush`。

## 运维注意

- 解释器仅 `Env\Python312\python.exe`
- 启动前清 `BACKEND_PORT` 继承，固定 **8000**（Vite 代理）
- 勿对 `launch.py start` 管道 `Select-Object -Last`（监控循环会缓冲挂起）
