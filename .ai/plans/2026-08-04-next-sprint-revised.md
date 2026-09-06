# 修订后的下一步方案（2026-08-04）

> 触发：用户新增 `.ai/progress/2026-08-04-backend-32-fixes.md`（后端 32 失败 → 0），并要求重启栈、保证 `.ai` 可读。  
> **文档同步（§2 文档三项）**：2026-08-04 已按选项 A 执行（audit / 仪表盘勾选 / test-reorg 指针）。  
> **代码向 P0/P1**：仍待你确认后再动手。
## 0. 已当场完成（非本方案待办）

| 项 | 结果 |
|----|------|
| 全栈重启 | `launch.py stop` → `start`；status：Docker Redis/MinIO/Open-Meteo ✓，FastAPI :8000 ✓，Vite :5175 ✓，7 worker + beat ✓（gateway 未启，符合默认） |
| `.ai` 可读性 | 新增根 `.cursorignore`（`!.ai/` / `!.ai/**`）；`.gitignore` 注释；`.ai/README.md` 增加「IDE / AI 工具可读性」；`.vscode/settings.json` 注明勿排除 `.ai`，pytest 路径改到 `Test/backend` |

建议你在 Cursor：**Settings → Indexing → Refresh**，确认 `.ai/progress` 可被检索。

## 1. 相对原「待完善核查」方案的变更

### 原方案仍成立的部分（未完成 / 部分）

- Layers god store 完全拆分 — 仍开
- Open-Meteo Phase B（tile-manager ↔ `default_model`）— 仍开（P0）
- FY/SMAP UI 人工闭环 + 更大样本条带 — 仍开（P0）
- 真实数据 e2e / NAS 绿测 — 仍开（P1，需数据环境）
- 工作流审计 P1（V-01/V-02/P-01/P-02）— 仍开（P1）
- 平台 backlog（PostGIS / Cesium 主链 / TiTiler·Martin / SSE）— 非本期

### 因你本次改动而过时的表述

| 旧结论 | 新事实 | 待同步文档（确认后执行） |
|--------|--------|--------------------------|
| 后端 32 个环境性 pytest 失败 = 非功能债 | **489 passed / 0 failed**（关 safe-delete shim）；报告见 `progress/2026-08-04-backend-32-fixes.md` | `2026-08-04-pending-tasks-audit.md` §5；仪表盘「2026-07-21 之后里程碑」勾选；`test-reorganization.md` §6 脚注 |
| audit「Test 迁移后后端未全绿」 | 测试代码已对齐 catalog；shim/unrar 约定已写入 `AGENTS.md` / `project-conventions.md` | 同上 |
| 前端 vitest 432 | 报告称 **439 passed / 89 文件** | progress 索引可选更新 |

### 遗留关注（来自 backend-32-fixes，可选后续）

1. `test_confirm_with_offset` Mercator 往返 ~0.013°：若要亚百米精度，应重设计 confirm bounds（非再放宽容差）。
2. D 组 catalog 断言（smap-soil→smap-sm-ts 等）：若业务上属误删图层 id，应恢复 catalog，而非只改测试。

## 2. 确认后建议执行顺序

### 文档同步（小，优先）— **已完成 2026-08-04**

1. ~~更新 `2026-08-04-pending-tasks-audit.md`~~ ✅
2. ~~更新 `工程收口仪表盘.md`~~ ✅
3. ~~在 `2026-08-04-test-reorganization.md` 顶部加闭环指针~~ ✅

### 代码向 P0（仍按原优先级）

1. FY/SMAP UI：`ui-verification-steps.md` + 更大样本条带上图。
2. Open-Meteo Phase B：`weather-tile-manager` / Dashboard coverage 读 settings `default_model`。

### P1 / P2

- NAS e2e、工作流 P1、Layers 继续拆分 — 不变。

## 3. 明确暂不执行

- 不开始 Open-Meteo / FY UI / 工作流 P1 代码改动。
- 不自动改 audit/仪表盘（等你确认本修订方案后）。
- 不提交 git。

## 4. 请确认

回复例如：

- **A)** 先做文档同步（§2 文档三项），P0 代码另开  
- **B)** 文档 + 立刻做 Open-Meteo Phase B  
- **C)** 文档 + 立刻做 FY/SMAP UI 验证指导/协助  
- **D)** 方案再改（说明要改哪）
