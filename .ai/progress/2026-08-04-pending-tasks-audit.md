# 待完善任务核查快照（2026-08-04）

> **近期排期 SSOT**：本文件 + [工程收口仪表盘](../docs/reference/工程收口仪表盘.md)。  
> 历史快照（`项目任务清单.md` 正文、`.ai/memory/archive/*`）勿再单独排期。  
> 本轮仅文档收口，未改业务代码。

## 1. 已完成（A）

| 项 | 证据 | 备注 |
|----|------|------|
| 工程收口 Phase 0–1 | 仪表盘勾选 | 安全、legacy/demo 脱钩、OpenAPI drift |
| 天气几何与商业化视觉 | `.ai/docs/reference/天气渲染进度同步-2026-07-21.md` | 格网半开归属、风粒子、标量 LUT |
| Redis / Celery / MinIO / Open-Meteo 运行栈 | `launch.py` + `Code/backend/docker-compose.yml` | 旧任务清单「Redis 未完成」已过时 |
| Nginx 可选剖面 | `Code/infra/gateway/` + `launch.py start gateway` | 非默认 `start`；与 Vite 互斥 |
| FY/SMAP 算法链路与 Matlab 对照 + UI 闭环 | `fy-smap-progress-tracker.md` + `2026-08-04-fy-smap-ui-closed-loop.md` | `run-d1f167fbaec4`；导出点击偶发拦截 |
| 工作流调度 P0（cancel / reuse） | `workflow_scheduling_audit_report.md`（2026-08-04） | C-01～C-04、R-01 已实施 |
| `Test/` 测试集中化 | `2026-08-04-test-reorganization.md` | 路径与配置迁移完成（见该报告） |
| 后端 `Test/backend` 全绿 | `2026-08-04-backend-32-fixes.md` | **489 passed, 0 failed**（关 safe-delete shim + unrar + 测试对齐）；算法 306 / 前端 439 无退化 |
| Open-Meteo **Phase D** | coverage/sync API/FE model 单测 + 活栈 overview/coverage/trigger 烟测 | UI 风场/停容器可选 |
| Open-Meteo **Phase C** | last_sync + trigger `domains` + 503 sync_unavailable + 设置页 Sync 域只读/本次覆盖 | 已完成 |
| Open-Meteo **Phase B** | `stores/weather-engine.ts` + tile-manager / Dashboard | 改模型后 coverage+瓦片刷新；C/D 仍开 |
| Open-Meteo **Phase A** | `本地Open-Meteo完善计划-2026-07-21.md` | 后端 default_model / sync overview 真源 |

## 2. 部分完成（B）— 勿标完成

| 项 | 进度 | 缺口 |
|----|------|------|
| Layers god store 拆分 | 2026-08-10：已切出 `catalog-runtime` / `active-layers` / `run-layers` / `workspace-hydrate` / `weather-reconcile`；`index.ts` 仍为组合入口 | 「完全多 store」未勾 |
| ~~FY/SMAP UI~~ | **已闭环** | 见 `2026-08-04-fy-smap-ui-closed-loop.md`；条带更大样本 / 导出命中为残留 |
| 真实数据 e2e / NAS 绿测 | 产品化路径已落地（远程存储 + e2e 文档 B 节） | 实机 NAS/数据环境绿测仍缺 |
| 工作流审计 P1 | P0 已修 | ~~V-01/V-02/P-01 已实施~~；残留 P-02 时间轴 seek 可选后续 |

## 3. 未开始（C）— 平台 backlog（非本期）

- PostGIS（工作流状态现状 SQLite）
- Cesium **主链**（`cesium` / `vue-cesium` 依赖已引入，非默认主界面）
- deck.gl
- TiTiler / Martin
- 全站应用容器化、SSE

## 4. 过时文档对照

| 文档 | 问题 | 处理 |
|------|------|------|
| `项目任务清单.md` §3「Redis / Nginx 未完成」等 | 与现状矛盾 | 顶部已指向仪表盘 + 本 audit |
| `fy-smap-fix-execution-plan.md`「阶段 2a 进行中」 | 算法侧已完成，UI 仍开 | 已同步勾选状态 |
| 仪表盘 / 部分正文 `Doc/` 路径 | 已迁入 `.ai/docs/` | 仪表盘指针已改 |

## 5. 已闭环：原「后端 32 失败」非功能债

> 曾记为环境性失败；**2026-08-04 已修到 0**，见 [`2026-08-04-backend-32-fixes.md`](2026-08-04-backend-32-fixes.md)。  
> 本地复跑须关 WorkBuddy safe-delete shim（约定见 `AGENTS.md`）：  
> `CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend ...`  
> 可选后续：confirm 端点 Mercator 往返精度；catalog id 变更是否需业务回滚（报告 §遗留关注）。

## 6. 下一步计划方案

| 优先级 | 主题 | 动作 | 验收 |
|--------|------|------|------|
| ~~P0~~ | FY/SMAP UI 闭环 | **已完成** `run-d1f167fbaec4` + materialize | 可选：更大样本条带目视；修导出面板点击层级 |
| ~~P0~~ | Open-Meteo Phase B | **已完成** `weather-engine.defaultModel` 贯通 | 单测通过；手工看网络面板 `model=` |
| P1 | 真实数据 e2e | 有 NAS 时按 `Code/docs/真实数据e2e门槛.md` B 节绿测；无环境则仪表盘保持「待数据环境」 | 一条非 lab-output 全绿 |
| P1 | ~~工作流 P1~~ | **V-01/V-02/P-01 已实施**（dry-validate 提交、updatedAt+eventId 进度选取、progressive 失败 UI）；残留 P-02 时间轴 seek | 审计报告 P1 勾选；P-02 可选后续 |
| P2 | Layers 继续拆分 | ~~catalog/active/run/hydrate/weather-reconcile 已切出~~；`index.ts` 仍为组合入口 | 见 `2026-08-10-layers-slices.md` |
| ~~P2~~ | ~~R2 断路器调参~~ | **已完成**（threshold 1→3 + 指数退避；2026-08-12 确认代码已修复） | `redis_client.py` / `test_redis_circuit_breaker.py` |
| ~~P2~~ | ~~D-1 Task* 死契约~~ | **已清除**（旧模型已不在 `api_contracts.py` / `openapi.json`；2026-08-12 确认） | 无 Task* 残留 |
| ~~P2~~ | ~~D-2 OpenAPI security~~ | **已完成**（`main.py` 补充 SessionAuth + BearerAuth；2026-08-12） | `check:openapi` 通过 |
| ~~P2~~ | ~~N-3 hPa 单位语义~~ | **已完成**（9 个 hPa 字段添加 Field description；2026-08-12） | openapi.json 含 description |
| ~~P2~~ | ~~N-4 时间戳类型化~~ | **已完成**（新增 `OpenMeteoSyncStatusResponse` + `response_model`；`str()`→`strftime()`；2026-08-12） | openapi.json finished_at = date-time |
| ~~P2~~ | ~~L2 Ghost uvicorn~~ | **已完成**（`launch/commands.py` 补充 `spawn_main` + `uvicorn` pattern；2026-08-12） | stop 后 :8000 无残留 |
| P3 | 平台 backlog | PostGIS / Cesium 主链 / TiTiler·Martin — 不排进当前 sprint | 保持「非本期」 |

## 7. 相关链接

- [工程收口仪表盘](../docs/reference/工程收口仪表盘.md)
- [fy-smap-progress-tracker](fy-smap-progress-tracker.md)
- [ui-verification-steps](ui-verification-steps.md)
- [2026-08-04-test-reorganization](2026-08-04-test-reorganization.md)
- [2026-08-04-backend-32-fixes](2026-08-04-backend-32-fixes.md)
- [workflow_scheduling_audit_report](../docs/reference/workflow_scheduling_audit_report.md)
- [本地Open-Meteo完善计划](../docs/reference/本地Open-Meteo完善计划-2026-07-21.md)
- [修订方案（暂缓代码）](../plans/2026-08-04-next-sprint-revised.md)
