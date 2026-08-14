# CGDA 全量审查报告（2026-08-09）

**日期**：2026-08-09  
**分支 / HEAD**：`dev` @ `a6e3137`（审查启动基线 `d5ad133`，期间新增 `a6e3137` style 提交）  
**方法**：CI 对齐自动化质量门 + 五维人工审查 + 运行态健康检查  
**约束**：仅出报告，未改代码  

**上次审计参照**：

- [deliverables/gstack/pre-launch-check-cgda-2026-08-04.md](../../deliverables/gstack/pre-launch-check-cgda-2026-08-04.md) — 五维 P0 已清零
- [deliverables/code-review-2026-08-05.md](../../deliverables/code-review-2026-08-05.md) — 增量静态审查

---

## 1. TL;DR

| 项 | 结论 |
|----|------|
| **整体评估** | **🟡 条件通过（开发/内网联调可用；公网暴露前须修 P0）** |
| **自动化质量门** | pre-commit ✅；pytest 688+328 ✅；vitest 537 ✅；build ✅；check:openapi/catalog ✅；gen:types 无漂移 ✅ |
| **新 P0** | **1** — `POST /weather/sync/trigger` 无鉴权 |
| **新 P1** | **6** — 开发 bypass XFF 伪造、限流覆盖缺口、runtime 侦察面、SSRF 残余等 |
| **新 P2** | **8+** — god-store 债、settings 内联 body、eslint 警告、算法 format 范围缺口等 |
| **与 2026-08-04 对比** | 配置/凭据审查项已收口（`75136d6`/`5fc2b9d`）；无 P0 回归；出现 1 个**新**未鉴权写端点 |

**最重要行动**：为 `POST /weather/sync/trigger` 加 `require_write_access`（及限流），再评估是否将 `/runtime/status` 等管理读端点纳入读鉴权。

---

## 2. 自动化基线表

| 步骤 | 命令 / 工具 | 结果 | 备注 |
|------|-------------|------|------|
| Pre-commit | `pre-commit run --all-files` | **PASS** | ruff / ruff-format / mypy / eslint / prettier 全绿 |
| 后端测试 | `pytest Test/backend/ -q` | **688 passed** | 50.34s；12 warnings |
| 后端覆盖率 | `--cov=Code/backend/app --cov-fail-under=50` | **未跑** | 本地 Env 未装 `pytest-cov`；CI 仍会跑 |
| 算法测试 | `pytest Test/algorithms/ -q` | **328 passed** | 22.11s |
| 前端测试 | `npm run test` | **537 passed**（107 files） | 5.10s |
| 前端 lint | `npm run lint` | **0 errors / 36 warnings** | no-console×15、no-explicit-any×21 |
| 前端构建 | `npm run build` | **PASS** | vue-tsc + vite；litegraph eval 警告（第三方） |
| OpenAPI | `npm run check:openapi` | **PASS** | paths + operation fingerprints 一致 |
| Catalog | `npm run check:catalog` | **PASS** | FE=38 BE=38 |
| gen:types | `npm run gen:types` + `git diff` | **无漂移** | api-contracts.ts 与 openapi.json 同步 |
| Ruff check | `ruff check Code/backend/app Code/algorithms/providers/Python` | **PASS** | All checks passed |
| Ruff format | `ruff format --check`（同上路径） | **16 files would reformat** | 均在 `data_access/`、`ingest/`、`modules/`；**不在** pre-commit 钩子范围（见 §5.5） |
| pip-audit | `pip-audit -r requirements.txt` | **工具失败** | Windows GBK 解码 requirements.txt 中文注释失败 |
| npm audit | `npm audit --audit-level=high` | **工具失败** | registry.npmmirror.com 不支持 audit API |

日志：`.ai/progress/review-phase1-*.log`

---

## 3. 增量变更审查（`4373110..HEAD`）

| 提交 | 范围 | 审查结论 |
|------|------|----------|
| `75136d6` | 配置/凭据审查收口、api-key 500 修复、gen-types CI 门、契约同步 | ✅ 正向；`test_config_contracts` / `test_credential_roundtrip` 等补齐；无回归 |
| `5fc2b9d` | `GET /runtime/config` 读鉴权；F5/F11 契约与 offload 测试 | ✅ 闭合 F15；与 PATCH 对齐 |
| `b06097a` | 工作流 UI：wf-scroll、只读排列、顶栏源字、测量文案 | ✅ 纯 UI；build 通过 |
| `d5ad133` | `@datapool/guangdong.geojson` → npm 1.0.1 | ✅ CI/跨机安装友好；vitest/build 绿 |
| `a6e3137` | 脚本尾随空白 pre-commit 修复 | ✅ 无功能影响 |

**增量无新 P0 引入**；全仓扫描发现的历史端点 `POST /weather/sync/trigger` 仍为开放写面（见 §4.1）。

---

## 4. 五维发现清单

### 4.1 安全与鉴权

| ID | 级 | 位置 | 问题 | 建议 |
|----|-----|------|------|------|
| **S-P0-1** | 🔴 P0 | `weather_router.py` L230–233 | `POST /weather/sync/trigger` **无** `require_write_access`；可触发 Open-Meteo Docker/Celery 同步，高 IO/全局锁 | 加 `Depends(require_write_access)`；纳入写限流前缀 |
| **S-P1-1** | 🟠 P1 | `deps.py` L50–54 + `rate_limit.py` L69–75 | 开发 bypass 用 `client_ip()`，在 `BACKEND_TRUST_PROXY=true` 时可被 `X-Forwarded-For: 127.0.0.1` 伪造 | bypass 判定改用 `request.client.host` |
| **S-P1-2** | 🟠 P1 | `deps.py` L24–30 | `BACKEND_DEV_AUTH_BYPASS` 对 LAN 全开放读写（设计如此，运维风险高） | 交付清单强制关闭；文档已述，保持审计 |
| **S-P1-3** | 🟠 P1 | `ssrf.py` L219–231 | 检测到 HTTP(S) 代理时 IP 钉扎降级，DNS 重绑定残余面 reopen | 代理场景 fail-closed 或代理感知钉扎 |
| **S-P1-4** | 🟠 P1 | `ssrf.py` + `weatherengine/client.py` 等 | 仅 `source_fetcher` 用 `safe_urlopen`；`allow_private=True` 默认 | 用户可控 URL 统一走 hardened 出站 |
| **S-P1-5** | 🟠 P1 | `rate_limit.py` L51–52 | 写限流仅 `/config`、`/import`、`/workflow-runs`；缺 `/cleanup`、`/runtime`、`/workflow-timers`、`/weather/sync` | 扩展 `_WRITE_LIMITED_PREFIXES` |
| **S-P1-6** | 🟠 P1 | `runtime_router.py` L51–115、L188+ | `GET /runtime/status|metrics|api-config|tiles/cache/stats` 无鉴权 | 管理读端点加 `require_config_read_access` 或网络 ACL |
| **S-P1-7** | 🟠 P1 | `effective_config.py` | 单主密钥加密全部凭据（架构性 blast radius） | 长期 HKDF 分域；短期文档化 |
| **S-P2-1** | 🟡 P2 | `workflow_timer_router.py` | ~~`POST /workflow-timers/cron-preview` 无鉴权~~ **已闭环（2026-08-14）**：列表 / 详情 / cron-preview 均加 `require_write_access` | 保持写鉴权；前端定时器面板须已登录 |
| **S-P2-2** | 🟡 P2 | `config_routes.py` L5 vs L116 | 模块 doc 写 `/general` 公开，实现已加读鉴权 | 更新 docstring |

**已验证无回归（2026-08 审查修复）**：

- `require_config_read_access` 敏感 GET 全覆盖；`config_routes` 无 `dict[str, Any]` 裸 body
- `GET /runtime/config` 已加读鉴权（`5fc2b9d`）
- 64-hex 加密 key、空 IV 生产拒绝（`effective_config.py`）
- dev bypass 仅 loopback 或显式 `BACKEND_DEV_AUTH_BYPASS`（非 trust_proxy 伪造场景下正确）

### 4.2 契约与 API

| ID | 级 | 结论 |
|----|-----|------|
| **C-P1-1** | — | check:openapi + gen:types 双门均绿；178 schemas |
| **C-P2-1** | 🟡 P2 | `settings-api.ts` 7+ 处 toggle/update 仍内联 `{ enabled }` 等，未用 `ApiKeyToggleRequest` 等 gen 类型 | 用 `satisfies` 或显式 request 类型 |

### 4.3 后端工作流 / 异步 / 数据面

| ID | 级 | 结论 |
|----|-----|------|
| **W-P2-1** | 🟡 P2 | 节点缓存 API（`cleanup_router`）有鉴权但无限流；与 S-P1-5 联动 | 扩展限流 |
| **W-P2-2** | — | `test_node_cache_cleanup.py` 存在；688 后端测试全绿 |
| **W-P2-3** | — | Docker Redis/MinIO 仍绑 `127.0.0.1`（`docker-compose.yml` L26/L48）— 无回归 |

### 4.4 前端架构与 UI 债

| ID | 级 | 位置 | 问题 |
|----|-----|------|------|
| **F-P1-1** | 🟠 P1 | `stores/layers/index.ts`（~2676 LOC） | God-store：~97 成员 API、`activeLayersDisplay` ~290 LOC、与 weather-tile 双向耦合 |
| **F-P1-2** | 🟠 P1 | `stores/weather-tile-manager.ts`（~1863 LOC） | 模块级可变单例、跨 store 硬依赖、workflow UI 类型混入 |
| **F-P2-1** | 🟡 P2 | eslint | 36 warnings（wind 栈 console×11、map any×21） |
| **F-P2-2** | 🟡 P2 | `settings-api.ts` | 见 C-P2-1 |

**近期 UI（`b06097a`）**：wf-scroll、只读排列、测量文案 — 无安全问题。

### 4.5 算法 / 基础设施 / 文档

| ID | 级 | 结论 |
|----|-----|------|
| **A-P2-1** | 🟡 P2 | pre-commit ruff 仅覆盖 `Code/algorithms/providers/Python/algorithms/`；`data_access/`、`ingest/`、`modules/` 共 16 文件 format 漂移 | 扩展钩子 files 或单独 format job |
| **A-P2-2** | — | 算法 pytest 328 绿 |
| **D-P2-1** | 🟡 P2 | `AGENTS.md` 与实现基本一致；`/config/general` 公开描述需与 `75136d6` 读鉴权对齐 |

---

## 5. 已知开放项（继承，非本次新报 P0）

| 项 | 来源 | 状态 |
|----|------|------|
| SSRF DNS 重绑定 TOCTOU | 2026-08-05 R1 | 部分缓解（钉扎+重定向复验）；代理路径仍弱 |
| God-store 续拆 | 用户决策延后 | `layers/index.ts`、`weather-tile-manager.ts` |
| Redis requirepass | 2026-08-04 降级 | 绑回环；全链路 REDIS_URL 改造待定 |
| 跨进程配置吊销传播 | P0-8 降级 | 写路径 rehydrate；无 pubsub |

---

## 6. 运行态健康（Phase 3）

**时间**：2026-08-09 05:02 UTC+8  

| 组件 | 状态 |
|------|------|
| Redis / MinIO / Open-Meteo | running |
| FastAPI `:8000` | 就绪 |
| Frontend Vite `:5175` | 就绪 |
| Workers ×7 + Beat | 运行中 |
| Gateway Nginx | 默认联调入口（`launch.py start` / `restart`）；本地 HMR 用 `start --vite` |

| 探测 | 结果 |
|------|------|
| `GET /health` | `{"status":"ok","environment":"development"}` |
| `GET http://localhost:5175/` | **200** |

---

## 7. 分批修复建议

> **每批修复完成后必须：**  
> 1. 跑相关 pytest / vitest（见 [AGENTS.md](../../AGENTS.md)「改 X 则跑 Y」）  
> 2. `cd Code/frontend && npm run test && npm run lint && npm run build`  
> 3. `Env\Python312\python.exe launch.py stop` → `launch.py start` → `launch.py status` + `GET /health`

### B1 — P0 紧急（安全写面）

- 为 `POST /weather/sync/trigger` 加 `require_write_access`
- 将 `/weather/sync` 纳入写限流前缀
- **验证**：`pytest Test/backend/test_config_security.py Test/backend/test_rate_limit_coverage.py -q` + 手动无 key → 401

### B2 — P1 鉴权与侦察面

- 开发 bypass 改用 `request.client.host` 判 loopback
- `GET /runtime/status|metrics|api-config|tiles/cache/stats` 加 `require_config_read_access`
- 扩展写限流至 `/cleanup`、`/runtime`、`/workflow-timers`
- **验证**：`pytest Test/backend/test_config_security.py -q`；settings 页仍能读 runtime（带 key）

### B3 — P1 SSRF 加固

- 审计所有 `urlopen`/`httpx` 出站；用户 URL 统一 `safe_urlopen`
- 代理存在时 fail-closed 或钉扎经代理
- **验证**：`pytest Test/backend/test_ssrf.py Test/backend/test_fetch_gateway.py -q`

### B4 — P2 工程债（可并行）

- `settings-api.ts` 内联 body → gen request types
- 扩展 pre-commit ruff 至 `Code/algorithms/providers/Python/**`
- God-store：先抽 `activeLayersDisplay` + weather-tile queue 模块
- Wind 栈 `console.log` → `debugLog` / 删除
- **验证**：`npm run test` + `pre-commit run --all-files`

---

## 8. 审查局限

- 未跑 E2E 浏览器 / 地图交互手测
- 未验证算法数学正确性（FY/SMAP 等）
- 本地 pip-audit / npm audit 因环境与镜像源未得出 CVE 列表（CI security-scan job 为准）
- 本地未跑 `--cov`（pytest-cov 未装）；覆盖率以 CI 为准
- 未做依赖 CVE 深度人工研判

---

## 9. 发现汇总计数

| 严重度 | 新增（本次） | 说明 |
|--------|-------------|------|
| P0 | 1 | S-P0-1 |
| P1 | 6 | S-P1-1～7（7 项含架构债）+ F-P1-1～2 |
| P2 | 8+ | 契约/前端 eslint/算法 format/文档等 |
| 信息 | 若干 | litegraph eval、npm 镜像 audit 不可用 |

**Go / No-Go 建议**：

- **内网 / loopback 开发**：🟢 可继续迭代（测试全绿）
- **面向不可信网络部署**：🔴 No-Go，须先完成 **B1**（最低限度）
