# CGDA 全面代码审查计划（2026-08-15）

> 触发：`/plan 熟悉项目内容，并起草全面代码审查计划`。
> 执行模式（用户已确认）：**审查出报告（只读）**——产出分级问题清单与审查报告，**不含修复**。
> 聚焦范围（用户已确认，全选）：**安全专项、后端核心与并发、前端状态与可维护性、基础设施与治理**。
> 本计划为**只读编排层规划**；执行期不修改任何源码/配置，仅产出审查结论与可追踪问题清单。

---

## 0. 背景与目标

项目 CGDA 已进入工程化落地阶段（`workflow-runs` 主链、天气瓦片、Celery/Redis/MinIO 可运行）。当前基准：后端 277 py / ~75k 行，前端 378 ts/vue，算法 15 命名空间，129 后端测试 + 130 前端测试 + 66 算法测试。

本仓库已有较长审查历史（`Docs/06-代码审查` 22 份 + `.ai/plans/2026-08-07-code-review-plan.md` 编排框架），近期（08-14/08-15）已闭环大量**安全加固**与**数据源/工作流主链路**问题。因此本次**不重审已闭环/已留痕项**，而是：

- **目标 A**：对已知**遗留风险**逐条复核真实性、给出当前状态与处置建议（见 §5 遗留清单）。
- **目标 B**：在四个聚焦域内做**盲区扫描**，识别此前报告未覆盖的新问题。
- **目标 C**：产出**分级（P0/P1/P2/P3）问题清单**（含 文件:行 / 严重度 / 复现路径 / 处置建议）+ 综合审查报告（HTML，落 `Docs/08-HTML报告`）。

**明确不做**：不实施修复、不重构、不改配置、不提交；仅列出问题与建议。

---

## 1. 术语与验收标准

严重度分级（沿用仓库惯例）：
- **P0 阻断**：安全漏洞可被利用 / 生产数据损坏 / 主链路不可用 / 凭据泄露。
- **P1 高**：功能错误、并发正确性缺陷、可复现的性能/安全降级、鉴权边界缺口。
- **P2 中**：可维护性/死代码/重复实现/命名/测试缺口，无立即可利用风险。
- **P3 低**：风格、文档陈旧、冗余文件、建议性优化。

**验收标准**：
1. 四个聚焦域每域均有明确结论（✅ 无新问题 / ⚠️ 有 P2+ 问题 / ❌ 有 P0-P1 问题）与证据。
2. 遗留清单（§5）逐条给出「已闭环 / 仍未处理+风险等级 / 建议处置」。
3. 问题清单 ≥ 每条含 `文件:行`、严重度、复现/触发路径、处置建议；P0/P1 必须给出建议。
4. 综合审查报告落盘，含分级统计与「本次新增 vs 既有遗留」区分。
5. 全程只读，无任何源码/配置改动。

---

## 2. 审查前基线（只读验证，用于判断既有失败与本次发现隔离）

> 目的：记录当前测试/质量门基线，避免把「既有漂移失败」误报为本次新发现。仅运行只读命令（测试、lint、build、契约检查），不修改代码。

| 检查 | 命令（仓库根，Windows） | 注 |
|------|------|-----|
| 后端测试 | `CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="Test/.pytest-be"` | 需 `ENVIRONMENT=test` + `REDIS_URL`；WorkBuddy 需先禁用 safe-delete shim |
| 算法测试 | `Env/Python312/python.exe -m pytest Test/algorithms -q` | — |
| 前端单元 | `cd Code/frontend && npm run test` | — |
| 前端 lint / build | `cd Code/frontend && npm run lint && npm run build` | 记录警告数 |
| 契约漂移 | `cd Code/frontend && npm run check:openapi` | drift 应为零 |
| 图层目录 | `cd Code/frontend && npm run check:catalog` | 应为零 |
| 全仓质量门 | `pre-commit run --all-files` | 记录失败项 |

> 已知既有失败（08-15 报告已定性与归属，非本次引入）：`test_weather_coverage.py`/`test_weather_engine_settings_phase_a.py`（router 接口漂移，引用已移除的 `get_redis_client`）、`test_frontend_call_simulation.py`（匿名 401 语义漂移）、`test_import_raster_crs.py`（异常处理器漂移）、`test_dataset_registry.py`（本地注册库共享状态）。审查报道与修复建议时，这些计入「既有遗留」，不重复归因。

---

## 3. 审查范围与分工（四聚焦域 → 六维度）

每个聚焦域内按六维度检查：**安全 / 正确性 / 性能 / 可维护性 / 契约一致性 / 测试覆盖**。按域分组，避免重复遍历。

### 域 A：安全专项（P0 优先）
已知遗留复核（§5）+ 盲区扫描，重点文件：
- **凭据与加密**：`app/services/credential_resolver.py`、`api_keys_repository.py`、`gee_credentials_repository.py`、`weather_providers_repository.py`、`portal_credentials.py`、`app/core/config.py`（`BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY`）。复核：P2-4 双 AESGCM 实现、明文回退路径（`secrets_encryption_required`）、单一主密钥轮换策略、密钥是否硬编码。
- **鉴权与 RBAC**：`app/api/deps.py`、`auth_router.py`、`session_service.py`、`user_repository.py`。复核：三角色边界、`demo` 只读约束、写鉴权一致性、会话/TTL 吊销逻辑。
- **SSRF / 路径**：`app/core/ssrf.py`、`remote_browser_router.py`、`config_service`（URI 存储校验）。复核：P2-3 新旧 remote browser 权限模型不一致、私网放行 `allow_private=True` 的调用方是否收紧、DNS 重绑定与重定向逐跳校验。
- **前端安全**：`src/services/_http.ts`、`backend-auth.ts`（写密钥 localStorage）、`vite.config.ts`/`nginx.conf`（CSP 缺失）、`session-expired.ts`。复核：`X-Api-Key` 落 localStorage 的 XSS 面、`vue/no-v-html` 关闭范围、Cookie `HttpOnly/SameSite`、nginx 反代白名单与 `/config` 端点暴露面。
- **nginx / 网关**：`Code/infra/gateway/nginx.conf`。复核：正则白名单与后端路由耦合（新增 API 易漏配）、`real_ip`/`X-Forwarded-*` 处理、无 rate limit。

### 域 B：后端核心与并发
- **SQLite 并发写**：`app/services/_sqlite_pool.py`（单写者 + WAL + busy_timeout 30s + max_size 8）、`workflow_state.sqlite3`、`spatial_repository.py`。复核：多 Worker 并发写是否触发 `database is locked`、连接池与 worker_concurrency 匹配、事务边界。
- **Celery 配置**：`app/core/celery_app.py`。复核：Windows `solo` 池退化（无并行）、`acks_late` + `broker_visibility_timeout=8100` vs `task_time_limit=7500`、优先级队列、任务可重入性。
- **工作流引擎**：`app/services/workflow/`（`submission_service`、`lifecycle_service`、`queue_dispatch_service` CAS、`retry_dispatcher`、`cancel_paths`、`reuse_cache`）、`workflow_graph_compiler.py`、`workflow_timer_service.py`（cron 解析 / Date×DOW AND / 乐观 claim / 僵死哨兵 5min）。复核：取消/重试竞态、reuse 缓存一致性、定时器双触发防护。
- **限流与断路器**：`app/api/rate_limit.py`、`app/core/redis_client.py`。复核：仅 production 生效的旁路、Redis 挂时进程内降级（多进程阈值失效）、分布式计数一致性。
- **天气瓦片并发**：`app/weatherengine/tile_service.py`（asyncio+threading 双 Semaphore 并发槽位 6）、缓存 TTL/命中。复核：并发放行、缓存穿透、provider 限流保护。

### 域 C：前端状态与可维护性
- **Layers store**：`stores/layers/`（30 文件域拆分 + `bindings.ts` 可变共享对象）、`active-layers.ts`（deps 接口 30+ 方法）、`workspace-persist.ts`（80 层上限 / localStorage 元数据）。复核：跨域解耦、quota、刷新风暴、`runGroupLocked` 占位一致。
- **weather-tile 调度**：`stores/weather-tile-manager.ts`（55KB：并发槽位 6 / AIMD / 优先级队列 / generation / LRU merge / TTL/SWR）、`weather-tile-types.ts` 可调常数。复核：数值合理性、缓存失效、内存上界。
- **HTTP 层重复**：`services/_http.ts` vs `data-manager/core/api.ts`（独立实现）、`data-io.ts` re-export。复核：行为差异、错误处理一致性。
- **死依赖与体积**：`cesium`/`vue-cesium` 已声明 0 引用、`api-contracts.ts` 450KB、`MapCanvas.vue` 35KB。复核：依赖清理、bundle 拆分、chunk 体积门。
- **测试覆盖门槛过低**：前端 lines 22% / statements 21% / branches 16% / functions 19%。复核：关键路径（鉴权、地图、天气调度）无覆盖风险点。

### 域 D：基础设施与治理
- **CI**：`.github/workflows/ci.yml`（8 job）。复核：`setup-node@v4`/`setup-python@v5` 未 pin sha 的供应链风险、4 个 job 重复 `pip install`/起 redis 的复用、coverage 门偏低（后端 52%）、`check-openapi` 重复安装。
- **依赖治理**：`requirements.txt`（pin 混用 `==` vs `>=`、`python-multipart` 未 pin）、`requirements-dev.txt`（全宽松）、前端 npm 依赖。复核：可复现性、锁文件。
- **mypy 配置失效**：`mypy.ini` exclude 用旧 `app/tests/` 路径，测试已迁根 `Test/`。复核：exclude 是否仍生效、是否误检根 Test。
- **vendor 二进制治理**：`Code/backend/vendor/unrar/` 二进制 gitignore、CI 依赖 `apt install unrar`。复核：干净 clone 后 `test_archive_safe.py` 缺二进制 fail 的交付影响。
- **配置文件治理**：`deployment.config.json` 加载链、`data-sync/.env` 双写。复核：fail-closed 完整、凭据不入 json。
- **仓库卫生**：根目录 `nul` 文件（疑似误提交）、`launch/__pycache__` 3.10+3.12 双版本、`providers/Python/.pytest_cache` 提交在树、`.ai/*.tmp-*` 敏感临时文件、`.data/` 大日志堆积（fastapi.log.old 114MB）、`09-结题材料` 多版本 docx 冗余、`06-代码审查` 混入 HTML。

---

## 4. 执行流程（只读）

```
Phase 0  基线采集（§2）：记录测试/lint/build/契约/质量门基线数字，标注既有失败归属
Phase 1  域 A 安全专项：遗留复核 + 盲区扫描 → 安全问题清单
Phase 2  域 B 后端核心与并发 → 并发/性能/正确性问题清单
Phase 3  域 C 前端状态与可维护性 → 可维护性/状态问题清单
Phase 4  域 D 基础设施与治理 → CI/依赖/仓库卫生问题清单
Phase 5  交叉复核：遗留清单（§5）逐条定状态；合并四清单 → 去重 → P0/P1/P2/P3 分级
Phase 6  报告：HTML 综合审查报告落 Docs/08-HTML报告 + 问题清单（可追踪）
```

> 每域审查用独立 Explore/读取子代理并行推进（≤3 并发），主会话汇总。Phase 0 只读命令先行，作为问题隔离依据。

---

## 5. 已知遗留清单（复核项，优先确认当前状态）

| # | 遗留项 | 来源 | 复核要点 | 预期处置 |
|----|--------|------|---------|---------|
| L-1 | Layers god store 未完全拆分（`stores/layers/index.ts` 聚合边界） | 08-07 计划 | 拆分后跨域耦合（`bindings.ts` 可变对象）是否可接受 | 状态 + 建议 |
| L-2 | confirm 端点 Mercator 往返 ~0.013° 偏差 | 08-07 计划 | 是否需要重设计 bounds | 状态 + 建议 |
| L-3 | 时间轴 coverage 时区偏差（Asia/Shanghai vs 浏览器） | 08-07 计划 | 探针时区一致性 | 状态 + 建议 |
| L-4 | sync 无全局互斥锁（Beat+UI+`launch.py sync` 并行写 volume） | 08-07 计划 | 并发写 Open-Meteo volume 风控 | 状态 + 建议 |
| L-5 | `_LOCAL_SYNC_JOBS` 仅内存、多进程不共享 | 08-07 计划 | FastAPI 多 worker 一致性 | 状态 + 建议 |
| L-6 | `_store_path_manifest` ×4 重复实现 | 08-15 审计 | 四处签名差异、收敛建议 | 状态 + 建议 |
| L-7 | P2-3 新旧 remote browser 权限模型不一致 | 08-15 审计 | 统一到 profile 驱动 + read 权限模型 | 状态 + 建议 |
| L-8 | P2-4 两套 AESGCM 加密实现 | 08-15 审计 | 统一到单一加密工具模块 | 状态 + 建议 |
| L-9 | P2-8 `/config/remote-storage/{id}/browse` 与 `/search` demo 可浏览目录结构 | 08-15 审计 | 机构交付前 security 复核 | 状态 + 建议 |
| L-10 | 后端测试既有漂移失败（weather_coverage / frontend_call_simulation / import_raster_crs / dataset_registry） | 08-15 审计 | 各自归属与修复建议（不真正修复） | 状态 + 建议 |
| L-11 | `Test/` 下 pytest basetemp junction 锁死（`.pytest-be*`） | 08-15 审计 | 清理建议 | 状态 + 建议 |
| L-12 | CI actions 未 pin sha、requirements pin 漂移、coverage 门偏低 | 本次探索 | 供应链与可复现性 | 状态 + 建议 |
| L-13 | 前端 `X-Api-Key` 落 localStorage + CSP 缺失 + `vue/no-v-html` 关闭 | 本次探索 | XSS 面 | 状态 + 建议 |
| L-14 | SQLite 单写者并发写 + Windows solo 池退化 | 本次探索 | 并发瓶颈与部署平台 | 状态 + 建议 |
| L-15 | 仓库卫生（`nul` 文件、`.pytest_cache` 提交、`.data` 大日志、敏感 tmp、结题材料冗余） | 本次探索 | 治理清理清单 | 状态 + 建议 |

---

## 6. 输出物（仅落盘，不改源码）

1. **本计划**：`.trae/documents/2026-08-15-comprehensive-code-review.md`
2. **问题清单**：`Docs/06-代码审查/问题清单-2026-08-15.md`（含 `文件:行` / 严重度 / 复现路径 / 处置建议 / 是否为既有遗留）
3. **综合审查报告**：`Docs/08-HTML报告/comprehensive-code-review-2026-08-15.html`（四域结论 + 分级统计 + 遗留状态矩阵 + 修复路线建议，供后续排期）

---

## 7. 假设与决策

- **只读**：全程不修改源码/配置/依赖，不提交；仅产出报告与清单。
- **不修复**：P0/P1 仅给处置建议，修复工作由后续独立排期（用户可基于报告发起新任务）。
- **不重审**：已闭环历史项（安全加固、FY 数据链路、archive_safe 扩展等）不重复遍历，仅在涉及新发现时交叉引用。
- **隔离既有失败**：Phase 0 基线先行，凡基线已失败的项计入遗留（L-10），不重复归因。
- **报告格式**：HTML（用户偏好紧凑、对齐、减少白边；沿用 `<html-report>` 技能规范）。
- **规模假设**：后端 277 文件使用基于风险的抽样精读 + 静态扫描（rg 定位模式）+ 关键文件精读，而非逐文件全读；聚焦域内文件优先。

---

## 8. 下一步（计划批准后，进入只读执行）

1. **Phase 0**：跑 §2 基线命令，记录数字与既有失败归属。
2. **Phase 1–4**：并行 Explore 子代理（≤3 并发）按域 A→B→C→D 扫描，主会话精读关键文件（`_sqlite_pool.py`、`celery_app.py`、`credential_resolver.py`、`ssrf.py`、`rate_limit.py`、`_http.ts`、`workspace-persist.ts`、`nginx.conf`、`ci.yml`、`requirements.txt`）。
3. **Phase 5**：合并清单、分级、遗留定状态。
4. **Phase 6**：写问题清单 + HTML 报告，NotifyUser 呈交。