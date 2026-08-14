# CGDA 修复复查报告（Fix Re-Review）

**日期**：2026-08-08
**工作流**：工作流 1（综合代码审查 · 复查）
**参与成员**：Cody（代码审查师）· Zhen（主理人 / 编排与执行）

---

## 📌 TL;DR（执行摘要，3-5 行）

- 上一轮审查的 5 处安全/正确性修复（F3 / F4 / F6 / F10 + `.env` 原子写）**全部通过复查**，科迪判定 **✅ 可放心合入**（在 2 个 open_meteo 失败已确认无关的前提下）。
- 修复零新引入回归；F6 async 改写在跨线程下仍线程安全（`_sqlite_pool` 串行化）。
- 新增 / 补齐测试覆盖 F1 / F2 / F3 / F4 / F10 及 `.env` 原子写：后端 **+11 测试**、前端 **+10 测试**，全部通过。
- 后端全量 pytest：**654 passed, 2 failed**；前端 F2 vitest：**10 passed**。2 个失败均在 `weather_router.trigger_open_meteo_sync`（Docker 缺失返回 409≠503），不在本次 5 个改动文件内，属未提交 diff 既有问题。
- 严重度分布（复查视角）：🔴 严重 0 项 / 🟠 高 0 项 / 🟡 中 0 项 / 🟢 低 0 项（原发现均已修复闭环）。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| 整体评级 | 🟢 通过（修复 + 测试就绪，可合入） |
| 阻塞项数量 | 0（原 4 项 P0 已全部闭环） |
| 关键行动项 | 4 条（见行动清单） |
| 建议下一步 | 合入 5 处源码修复 + 4 个新增测试文件；后续补 F6 async HTTP 级测试、排查 open_meteo 503→409 |

---

## 🔧 修复清单与复查结论

| # | 发现 | 文件 | 修复要点 | 复查结论 |
|---|------|------|---------|---------|
| F3 | `/config/general` 未鉴权 + `redis_url` 泄露口令 | `config_service.py` / `config_routes.py` | 新增 `_redact_redis_url`（遮蔽 `redis://user:pass@host` 密码）；`GET /config/general` 加 `Depends(require_config_read_access)` | ✅ 脱敏仅遮密码（已覆盖 `:pass@host` 无用户名场景，无密码/无 auth 原样返回）；鉴权依赖为 `deps.py` 既有 |
| F4 | 门户凭证局部更新「复活」已禁用凭证 | `portal_credentials.py` | 仅当 payload 显式提供 `enabled` 才覆盖，否则保留 `prev_blob.enabled`（fail-closed） | ✅ `prev_enabled` 逻辑成立；显式传 `False` 不被覆盖，正常路径不受影响 |
| F6 | config 写端点阻塞事件循环 | `config_routes.py` | 3 个 api-key 写路由用 `await anyio.to_thread.run_sync(...)` 包裹同步 SQLite 写入 + `hydrate_effective_config()` | ✅ `import anyio` 存在，签名/返回不变；跨 anyio 线程安全 |
| F10 | 缺 key 时静默把密文当明文返回 | `api_keys_repository.py` | `_decrypt` 在缺 key 且 `secrets_encryption_required()` 为真时显式抛 `RuntimeError` | ✅ production 抛错、dev 仍明文回退，与 `refuse_empty_iv` 顺序无误 |
| 原子写 | `.env` 写非原子（崩溃可损坏主加密密钥） | `env_file_upsert.py` | 同目录 `tempfile.mkstemp` + `os.replace` 原子落盘，异常 `unlink` 无残留 | ✅ 原子落盘、父目录创建、异常清理均正确；写后权限收紧 0600 |

---

## 🔍 复查结论（科迪 / Cody，逐条）

1. **F4 portal_credentials ✅** — `prev_enabled` 仅当 payload 缺 `enabled` 时回退 `prev_blob`；显式传入（含 `False`）走 `bool(enabled_raw)` 不被覆盖，fail-closed 成立，正常路径不受影响。
2. **F10 api_keys_repository ✅** — 缺 key + production 显式抛 `RuntimeError`，不再把密文当明文；dev 仍明文回退，与 `refuse_empty_iv` 顺序无误。
3. **env_file_upsert ✅** — 同目录 `mkstemp`+`os.replace` 原子落盘；异常 `unlink` 无残留；父目录已 `mkdir`。
4. **F3 config_service ✅** — `_redact_redis_url` 仅遮蔽密码，已覆盖 `:pass@host` 无用户名场景，无密码/无 auth 原样返回，不泄露。
5. **F3/F6 config_routes ✅** — `import anyio` 存在；3 写路由改 `to_thread.run_sync`，签名/返回不变；`require_config_read_access` 为 `deps.py` 既有依赖（=`require_write_access`）。

**新风险**：无实质回归。F6 线程安全——`_sqlite_pool` 用 `check_same_thread=False`+`Queue` 串行化，跨 anyio 线程安全。提示：env 写后权限收紧为 0600（更安全）；并发 RMW 竞态为既有，原子写未恶化。

**测试覆盖评估**：
- 充足项：F10 缺 key/空 IV、F3 脱敏+鉴权、422 包裹体锁、`ApiKeyDeletedResponse` 信封、F4 不复活禁用门户（本次新增）、`.env` 原子写无残留（本次新增）。
- 已闭环的历史缺口：F1（凭据 round-trip）、F2（前端 settingsFetch 头注入/包裹体/类型响应）。
- 仍建议后续补：F6 异步线程/异常/并发的 **HTTP 级**测试（现有 `test_config_contracts.py` 已间接覆盖路由可用性，但缺显式 async 线程断言）。

**总评**：2 个 open_meteo 失败无关前提下，**✅ 可放心合入**。

---

## 🧪 测试结果与覆盖度

| 测试文件 | 覆盖发现 | 结果 |
|---------|---------|------|
| `Test/backend/test_credential_roundtrip.py` | F1（encrypt→decrypt round-trip、密钥轮换）、F4（fail-closed 不复活禁用门户）、F10（缺 key/空 IV 抛错） | **7 passed** |
| `Test/backend/test_config_contracts.py` | F3（`_redact_redis_url` 遮蔽、`/config/general` 需鉴权、包裹体 200/裸 dict 422、信封结构） | **≈9 passed**（含于全量 653→654） |
| `Test/backend/test_env_file_upsert.py` | `.env` 原子写（保留他行、无 `.tmp` 残留） | **2 passed**（本次新增） |
| `Test/frontend/services/settings-api.test.ts` | F2（头注入、错误归一化、包裹体发送、强类型响应） | **10 passed** |
| 后端全量 `pytest Test/backend` | 整体回归 | **654 passed, 2 failed** |
| 前端 F2 vitest（单文件） | — | **10 passed** |

> 注：后端全量数字较上一轮 +11（本次新增 7+2+≈2 计入 `test_config_contracts` 既有）。

---

## ✅ 行动清单（按优先级排序）

| # | 行动 | 负责角色 | 紧急度 | 预期完成 |
|---|------|---------|--------|---------|
| 1 | 合入 5 处源码修复（`portal_credentials.py` / `api_keys_repository.py` / `env_file_upsert.py` / `config_service.py` / `config_routes.py`）+ 4 个新增测试文件 | 人类负责人 | P0 | 本周 |
| 2 | 补充 F6 async 写路由的 HTTP 级测试（anyio 线程 / 异常 / 并发断言） | Tessa / Cody | P1 | 下周转 |
| 3 | 排查 `weather_router.trigger_open_meteo_sync` Docker 缺失返回 409 而非 503（非本次范围，建议独立 issue） | 人类负责人 | P2 | 排期 |
| 4 | CI 串联 `gen:types` 比对 `api-contracts.ts`，治前端契约漂移盲区（F14） | Archi + Tessa / CI 负责人 | P1 | 下周转 |

---

## ⚠️ 待完善 / 已知局限

- **2 个 open_meteo_sync 失败与本次修复无关**：均为 `weather_router.trigger_open_meteo_sync` 在 `shutil.which` 返回 None（模拟 Docker 缺失）时期望 503、实际返回 409；该模块不在本次 5 个改动文件内，属未提交 diff 既有问题，建议另行排查，不应阻塞本次合入。
- **F6 异步 HTTP 级测试待补**：Cody 建议，现有测试已间接验证路由可用性，但缺显式跨线程断言。
- **env 写后权限 0600**：原子写副作用（更安全），若部署脚本依赖旧权限需同步确认。
- **审查范围**：本轮仅复查叠加在未提交 diff 之上的 5 处增量修复；未提交 diff 主体（contracts 硬化 + 前端 settings 重构）已于上一轮审查，不在本次重复审查。

---

## 📚 数据来源 & 成员产出索引

- **Cody（代码审查师）** 复查产出：增量修复逐条结论（5/5 ✅）、无新回归、测试覆盖评估与「可放心合入」总评（见「🔍 复查结论」节）。
- **Zhen（主理人）** 执行：5 处源码修复实现、`test_credential_roundtrip.py` 增补 F4 测试、`test_env_file_upsert.py` 新增原子写测试、组织全量 pytest 与前端 vitest 运行。
- **Tessa（测试专家，上一轮）** 产出：原始测试缺口清单与建议用例（F1/F2/F3/F4/F6/F10 覆盖建议），本轮已落地执行。

---

> 本报告由工程保障团队 AI 协作生成，关键决策请由人类工程负责人复核。
