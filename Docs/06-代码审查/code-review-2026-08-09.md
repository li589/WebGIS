# CGDA 代码审查摘要（2026-08-09）

**分支**：`dev` @ `a6e3137`  
**详版**：[`.ai/progress/code-review-fullstack-2026-08-09.md`](../.ai/progress/code-review-fullstack-2026-08-09.md)（本地，不上传 GitHub）

---

## TL;DR

**🟡 条件通过** — 自动化质量门全绿（pre-commit、688+328 pytest、537 vitest、build、check:openapi/catalog），运行态健康。发现 **1 个新 P0**：`POST /weather/sync/trigger` 无鉴权即可触发 Open-Meteo 同步。公网暴露前须修；内网联调可继续。

| 维度 | 结论 |
|------|------|
| 自动化 / CI 对齐 | ✅ 全绿 |
| 增量（`4373110..HEAD`） | ✅ 配置/凭据、`/runtime/config` 鉴权、UI 小修无回归 |
| 安全 | 🔴 1 P0 + 6 P1 |
| 契约 | ✅ OpenAPI + gen:types 同步 |
| 前端债 | 🟠 god-store 仍大（~2.7k + ~1.9k LOC） |
| 运行态 | ✅ FastAPI/前端/Worker 就绪 |

---

## 自动化基线（摘要）

| 项 | 结果 |
|----|------|
| pre-commit | PASS |
| pytest backend | 688 passed |
| pytest algorithms | 328 passed |
| vitest | 537 passed |
| eslint | 0 errors / 36 warnings |
| build | PASS |
| check:openapi / catalog | PASS |

---

## 优先行动项（Top 5）

1. **P0** — `POST /weather/sync/trigger` 加 `require_write_access` + 写限流（[`weather_router.py` L230](../Code/backend/app/api/routers/weather_router.py)）
2. **P1** — 开发 bypass 用 `request.client.host` 判 loopback，避免 `X-Forwarded-For` 伪造（[`deps.py` L50](../Code/backend/app/api/deps.py)）
3. **P1** — 将 `/runtime/status`、`/runtime/metrics`、`/runtime/api-config` 等管理读端点纳入读鉴权
4. **P1** — 写限流扩展至 `/cleanup`、`/runtime`、`/workflow-timers`
5. **P2** — god-store 续拆（`layers/index.ts`、`weather-tile-manager.ts`）与 settings-api 内联 body 改 gen 类型

---

## 发现汇总

| 级 | 数量 | 代表项 |
|----|------|--------|
| P0 | 1 | 未鉴权天气同步触发 |
| P1 | 6+ | runtime 侦察面、限流缺口、SSRF 残余、god-store |
| P2 | 8+ | eslint 36 warnings、算法 ruff 范围缺口、文档漂移 |

**继承开放项**：SSRF DNS 重绑定（部分缓解）、单加密主密钥 blast radius、god-store 拆分延后。

---

## 分批修复与强制验收

每批修复后必须：

1. 跑相关 pytest / vitest（见 `AGENTS.md`「改 X 则跑 Y」）
2. `cd Code/frontend && npm run test && npm run lint && npm run build`
3. `Env\Python312\python.exe launch.py stop` → `launch.py start` → `launch.py status` + `/health`

| 批次 | 范围 |
|------|------|
| **B1** | P0 天气同步鉴权 + 限流 |
| **B2** | P1 鉴权/侦察面/限流扩展 |
| **B3** | P1 SSRF 出站统一 |
| **B4** | P2 前端债 + pre-commit 算法范围 |

---

## Go / No-Go

- **内网开发**：🟢 继续迭代
- **不可信网络部署**：🔴 先完成 B1
