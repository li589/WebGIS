# CGDA Phase 2 收口报告（测试缺口补齐 + 回归修复 + 全量复查）— 最终版

**日期**：2026-08-08（含 08-09 凌晨收尾）
**工作流**：工作流 1（综合代码审查）+ 工作流 4（测试策略 / 部署前检查）
**参与成员**：Cody（代码审查师）、Tessa（测试专家）；主理人甄宇航（编排 / 汇编）

---

## 📌 TL;DR（执行摘要）

- 整体结论：Phase 2 全部闭环——测试缺口补齐（F6/F7/F8/F12/F13/F6-async）+ 捕获并修复 2 个源码回归（F20，均为 500）+ 补 F5/F11 测试 + 落地 F15 鉴权闸门 + F14 CI 闸门。全量后端 **688 passed / 0 failed**，两批提交均过全部 pre-commit 钩子（`75136d6`、`5fc2b9d`）。
- 严重度分布：🔴严重 2 项（F20 源码回归，**已修复**）/ 🟠高 0 / 🟡中 0 / 🟢低 0（本次 Phase 2 新增）
- 阻塞 / 非阻塞：**无阻塞项**。原 19 项发现全部闭环或确认，F15 已按安全默认方案实施。
- 测试矩阵：后端相关测试 39 passed（contracts 27 + breaking-contracts 8 + write-offload 4），全量 688 passed；前端 F13 vitest 5 passed。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟢 通过（测试全绿 + 缺陷修复 + 鉴权闸门落地） |
| 阻塞项数量 | 0 |
| 关键行动项 | 3 条（push 两批提交并关注 CI / open_meteo 可选加固 / 后续契约改动跑 gen:types） |
| 建议下一步 | push `75136d6`、`5fc2b9d` 到 dev，观察 CI 全绿后合入主干 |

---

## 一、Phase 2 范围与目标

承接前序 rereview（5 处后端源码修复 + 原子写 + 新测试，结论「safe to merge」），本轮目标：

1. 补齐剩余可自动闭环的测试缺口：F6 / F7 / F8 / F12 / F13 / F6-async；
2. 复查 open_meteo_sync 503→409 历史失败；
3. 将 F14（openapi.json → api-contracts.ts 同步）接入 CI 闸门；
4. F15 人工决策 → 已拍板执行（安全默认：读鉴权同门）；
5. 残留 F5 / F11 → 本轮补测试闭环。

---

## 二、测试缺口补齐（Tessa 交付，仅新增 / 扩展测试）

| 发现 | 文件 | 内容 | 结果 |
|------|------|------|------|
| F6 | `Test/backend/test_config_contracts.py` | PUT /portal-credentials/earthdata（含 clear_secrets）→200；`extra="ignore"` 仅透传声明字段；POST /data-cache/evict 包裹体→200 | ✅ |
| F7 | 同上 | gee / weather / remote-storage 的 deleted / toggle / priority 共 7 个 `*Response` 信封断言 + portal 整图，覆盖全部 9 类 | ✅ |
| F8 | 同上 | GET /runtime/config HTTP 级验证 scope→key→value 合并快照（带 X-API-Key） | ✅ |
| F12 | 同上 | dev 局域网旁路正向路径（development + BACKEND_DEV_AUTH_BYPASS + 非 loopback）→ 写端点 200 | ✅ |
| F6-async | 同上 | 3 个 api-key 写路由 HTTP 测试（PUT create → toggle → delete）——初始被源码 bug 阻塞，xfail 跟踪，**修复后转正** | ✅（修复后） |
| F13 | `Test/frontend/components/settings/weather-provider-settings.test.ts` | 5 用例覆盖 config_schema / field.options / daily_quota=0 / typeMeta 缺失分支不崩溃 | ✅ 5 passed |
| **F5** | `Test/backend/test_config_breaking_contracts.py` | 8 用例锁定 `PUT /config/data-source/open-data-presets` 与 `/remote-layer-uris` 契约：包裹体 200 + 契约反序列化、extra=ignore 丢弃未声明字段、空 body 422、裸 dict 422（破坏性锁定） | ✅ 8 passed |
| **F11** | `Test/backend/test_config_write_offload.py` | 4 用例：api-key 写路由经 `anyio.to_thread.run_sync` 的 spy 断言（update/toggle/delete）+ 事件循环级非阻塞（asyncio + ASGITransport 并发，轻量 GET <1s 响应，连跑 3 次稳定） | ✅ 4 passed |

---

## 三、新发现源码缺陷（F20，P1，已修复）

> 关键价值：本轮「测试缺口补齐」直接捕获了前一轮源码修复引入的 2 个回归——这正是补齐测试的意义所在。两处均位于当时未提交 diff（`git status` 显示 `M`），非测试陈旧、非环境偶发。已随第一批提交 `75136d6` 落地。

### Bug 1 — `update_api_key` 端点 500（F6-async 根因）
- 位置：`Code/backend/app/api/config_routes.py:148-157`
- 根因：`anyio.to_thread.run_sync(func, *args)` 仅接受位置参数，原函数直接传 `key_name=` 等关键字参数 → `TypeError` → 500，`PUT /config/api-keys` 整体不可用。
- 修复：`lambda:` 包裹调用（不依赖形参顺序）。

### Bug 2 — `toggle_api_key` 端点 500（Bug 1 修复后才暴露）
- 位置：`Code/backend/app/services/config_service.py:281-284`
- 根因：toggle 返回值缺 `display_name`，不满足 `ApiKeyItem` 必填 → `ResponseValidationError` → 500（独立 bug，被 Bug 1 掩盖）。
- 修复：改为 `return _annotate_key_entry(info, source="db")` 并补 `display_name`。

### 处置
移除 3 个 `@pytest.mark.xfail`，目标测试全绿；`test_config_contracts.py` 26 → 27 passed（+F15 负路径）。

---

## 四、F15 — /runtime/config 鉴权闸门（已实施，随第二批 `5fc2b9d` 落地）

- 改动：`Code/backend/app/api/routers/runtime_router.py:5,42` — GET /runtime/config 加 `dependencies=[Depends(require_config_read_access)]`（读鉴权同门，与同文件 PATCH 的 `require_write_access` 对齐）。
- 影响面（已核实，无破坏）：前端 `settings-api.ts` 的 `settingsFetch` 统一 `withWriteAuthHeaders(..., true)` 带 X-API-Key；dev loopback 旁路 / prod 带 key；service 层直调用例不经 HTTP 不受影响；`test_celery_e2e.py` 为手动脚本走 loopback。
- 测试：新增负路径 `test_runtime_config_requires_read_auth_without_key`（无 key → 401）；F8 正向用例带 key 仍 200。
- 连锁：重新导出 `openapi.json`（159 paths，含 /runtime/config security 声明）+ `npm run gen:types` 对齐 —— F14 闸门首次实际拦截并修复漂移（含 `/config/general` 一处 75136d6 残留漂移）。

---

## 五、open_meteo_sync 503→409 复查结论

Cody 确认：**非代码缺陷**。`weather_router.trigger_open_meteo_sync` 本就返回 503（`weather_router.py:290-306`）；2 个目标测试文件 9/9 通过；前序 409 来自 Redis sync-lock 残留（`is_open_meteo_sync_locked()` 为 True，line 276），属环境偶发抖动。

→ 无需改源码。可选加固（未做，待用户按需）：在两测试中 mock / clear `is_open_meteo_sync_locked` 消除跨运行抖动。

---

## 六、F14 — openapi.json → api-contracts.ts CI 同步闸门

`.github/workflows/ci.yml` 新增 `gen-types` job（needs: check-openapi）：`npm run gen:types` + `git diff --exit-code src/types/api-contracts.ts`，不一致即 CI 失败。**本轮已实战验证**：F15 改动触发漂移告警 → 重新导出 + gen:types → 清零。当前分支与 live app 完全一致，不会误红。

---

## 七、整体回归验证（最终）

| 范围 | 命令 | 结果 |
|------|------|------|
| 相关测试三文件 | `pytest test_config_contracts.py test_config_breaking_contracts.py test_config_write_offload.py` | 39 passed |
| **全量后端** | `pytest Test/backend`（全新 basetemp） | **688 passed, 2 subtests passed, 0 failed**（65.55s） |

较上轮基线（675 passed / 0 failed）：+13（F15 负路径 1 + F5 8 + F11 4），无新回归。

> ⚠️ 环境注意：复用同一 basetemp 目录（如 `Test/.pytest-be`）多次运行后可能被 Windows 文件锁占用，pytest 会话清理时报 `WinError 5` → 大面积 ERROR（122 errors）。**换全新 basetemp 目录即恢复**（本次用 `Test/.pytest-final`）。非代码问题。

---

## 八、原始 19 项发现（F1–F19）+ 新增 F20 状态总览（最终）

### 全部闭环 / 确认 ✅
- **F1** credential round-trip 测试、**F2** settings-api.ts 前端测试（10 vitest）、**F3** /config/general 鉴权 + redis_url 脱敏、**F4** portal 局部更新 fail-closed、**F5** 破坏性契约测试（本轮 8 用例）、**F6** PortalCredentialUpsert/DataCacheEvict HTTP 覆盖、**F7** 9 类 delete/toggle 信封断言、**F8** /runtime/config 快照测试、**F9** env 原子写、**F10** evict 子串匹配、**F11** 事件循环 offload 专测（本轮 4 用例）、**F12** dev 局域网旁路正向路径、**F13** WeatherProviderSettings.vue 组件测试、**F14** openapi→api-contracts CI 闸门、**F15** /runtime/config 鉴权闸门（本轮实施）、**F16** dev bypass fail-closed、**F17** 进程内限流器、**F18** _decrypt 缺密钥回明文、**F19** portal upsert 改进 —— 均 ✅
- **F20**（新增）api-key 写路由 2 个 500 源码回归 —— ✅ 修复

### 无残留阻塞项。F16/F17/F18/F19 为前序确认项。

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | push `75136d6`、`5fc2b9d` 到 dev，观察 CI（pre-commit / pytest / vitest / check-openapi / gen-types）全绿 | 人类工程负责人 / 主理人 | P0 | push 后 |
| 2 | 可选加固：open_meteo_sync 两测试 mock / clear `is_open_meteo_sync_locked` 消除跨运行抖动 | Cody | P2 | 按需 |
| 3 | 后续任何后端契约 / security 改动后：跑 `export_openapi.py` + `npm run gen:types`（F14 闸门约束） | 全体 | P1 | 每次改动时 |
| 4 | Windows 跑 pytest 用**全新 basetemp 目录**（避免复用被锁目录触发 WinError 5） | 全体 | P1 | 每次验证时 |

---

## ⚠️ 待完善 / 已知局限

- open_meteo_sync 可选加固未做（环境偶发 409，非代码问题；需要时再改）。
- 前端全量 `npm run test` 未在本轮全量重跑（仅 F13 5 用例 + 既有 F2 10 用例）；后端 688 已全绿。
- 两批提交尚未 push；CI 验证待 push 后确认。
- `deliverables/` 已加入 .gitignore（本地交付物不入库）；如需入库可自行调整。

---

## 📚 数据来源 & 成员产出索引

- Cody（代码审查师）原始产出：open_meteo 复查结论（非 bug）、F20 两 bug 定位 + 修复 + git 归因、F15 鉴权闸门实施 + 影响面分析。
- Tessa（测试专家）原始产出：`test_config_contracts.py`（F6/F7/F8/F12/F6-async）、`weather-provider-settings.test.ts`（F13）、`test_config_breaking_contracts.py`（F5）、`test_config_write_offload.py`（F11）。
- 主理人汇编：本报告、全量回归验证（688 passed）、F14 闸门落地与实战修复、两批提交（`75136d6` / `5fc2b9d`）、.gitignore 补充（`.pytest_tmp_*` / `deliverables/` / `nul`）。

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
