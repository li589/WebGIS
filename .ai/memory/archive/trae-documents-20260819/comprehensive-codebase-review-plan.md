# CGDA 全面代码审查规划

> 审查框架：Staff Engineer Mode → `architecture-decisions`（主）+ `code-readability-for-agents`（辅）
> 审查范围：CGDA 全仓库（后端 / 前端 / 算法 / 基础设施 / 共享契约 / 测试 / 工具 / 文档 / CI）
> 审查目标：不放过一个地方，覆盖架构边界、安全、代码质量、API 契约、测试覆盖、性能、可观测性、数据可靠性、基础设施、文档生命周期 10 大维度
> 输出：先展示本规划供审阅 → 执行后输出详细审查报告

---

## 一、代码库全景统计

| 区域 | 文件数 | 代码行数 | 测试文件数 | 测试行数 |
|------|--------|---------|-----------|---------|
| 后端 `Code/backend/app/` | 265 .py | 69,181 | 110 | 18,046 |
| 前端 `Code/frontend/src/` | 348 (.ts/.vue/.css) | 106,072 | 123 | 10,671 |
| 算法 `Code/algorithms/` | 193 .py | 45,031 | 64 | — |
| 共享 `Code/shared/` | 15 .py | 1,849 | — | — |
| 启动器 `launch/` | 11 .py | 2,287 | — | — |
| 基础设施 `Code/infra/` | 13 | — | — | — |
| 工具 `Tools/` | ~50 | — | — | — |
| 文档 `Docs/` | ~166 | — | — | — |
| AI 工作区 `.ai/` | 105+72 | — | — | — |
| **合计** | **~700+ 源文件** | **~225K 行** | **310** | **~29K 行** |

### 超大文件清单（>800 行，审查重点）

| 行数 | 文件 | 区域 | 问题类型 |
|------|------|------|---------|
| 12,946 | `types/api-contracts.ts` | 前端 | 自动生成（排除） |
| 3,398 | `services/node_template_registry.py` | 后端 | God Class |
| 3,324 | `algorithms/omega_sf.py` | 算法 | 核心算法（审查复杂度） |
| 2,878 | `algorithms/omega.py` | 算法 | 核心算法 |
| 2,457 | `gee/core/tests/.../test_workflow_service.py` | 后端测试 | 测试规模 |
| 1,948 | `stores/weather-tile-manager.ts` | 前端 | God Store |
| 1,924 | `components/workflow/WorkflowCanvas.vue` | 前端 | God Component |
| 1,877 | `gee/core/tests/.../test_workflow_*.py` | 后端测试 | 测试规模 |
| 1,819 | `components/info-panel/InfoPanel.styles.css` | 前端 | 样式膨胀 |
| 1,598 | `components/workflow/WorkflowEditorPanel.vue` | 前端 | God Component |
| 1,571 | `components/workflow/WorkflowStatusPanel.vue` | 前端 | God Component |
| 1,516 | `gee/core/tests/.../test_export_workflow.py` | 后端测试 | 测试规模 |
| 1,443 | `weatherengine/weather_render_service.py` | 后端 | God Service |
| 1,282 | `components/workflow/WorkflowTimerPanel.vue` | 前端 | God Component |
| 1,262 | `components/layer-sidebar/LayerSidebar.styles.css` | 前端 | 样式膨胀 |
| 1,194 | `components/map/wind-particle-webgl-renderer.ts` | 前端 | WebGL 复杂度 |
| 1,185 | `data-manager/ui/AttributeTable.vue` | 前端 | God Component |
| 1,156 | `components/map/wind-particle-canvas.ts` | 前端 | WebGL 复杂度 |
| 1,139 | `gee/core/src/.../workflow/*.py` | 后端 | God Service |
| 1,116 | `stores/layers/workflow-runner.ts` | 前端 | God Store |
| 1,098 | `services/python_provider_result_builder.py` | 后端 | God Service |
| 1,099 | `components/workflow/WorkflowInspector.vue` | 前端 | God Component |
| 1,075 | `services/workflow_request_resolver.py` | 后端 | God Service |
| 1,053 | `components/settings/WeatherProviderSettings.vue` | 前端 | God Component |
| 1,015 | `stores/layers/run-layers.ts` | 前端 | God Store |
| 1,010 | `components/map/overlay-image-module.ts` | 前端 | God Module |
| 1,007 | `services/api-config.ts` | 前端 | God Service |
| 997 | `stores/layers/catalog.ts` | 前端 | God Store |
| 995 | `ingest/fy_preprocess.py` | 算法 | 预处理复杂度 |
| 973 | `data-manager/core/api.ts` | 前端 | God Service |
| 945 | `weatherengine/client.py` | 后端 | God Client |
| 942 | `components/workflow/PipelineLauncher.vue` | 前端 | God Component |
| 928 | `services/workflow_timer_service.py` | 后端 | God Service |
| 919 | `services/overlay_registry.py` | 后端 | God Registry |
| 914 | `ingest/daily_bundle.py` | 算法 | 预处理复杂度 |
| 895 | `components/settings/GpuPerfTestDialog.vue` | 前端 | God Component |
| 880 | `data-manager/ui/DataExportPanel.vue` | 前端 | God Component |
| 829 | `components/workflow/WorkflowList.vue` | 前端 | God Component |
| 823 | `data_io/api/router.py` | 后端 | God Router |
| 819 | `components/settings/OpenMeteoSyncSettings.vue` | 前端 | God Component |
| 817 | `components/workflow/WorkflowNodePalette.vue` | 前端 | God Component |
| 814 | `data_io/services/dbf_encoding.py` | 后端 | 编码处理 |
| 813 | `services/workflow_repository.py` | 后端 | God Repository |

---

## 二、审查维度与 SEM 专项映射

| 审查维度 | SEM 专项 | 审查重点 | 在仓库中的对应区域 |
|---------|---------|---------|-----------------|
| **A. 架构边界** | `architecture-decisions` | 模块边界、依赖方向、服务拆分、上下文映射 | 全仓库 |
| **B. 代码可读性** | `code-readability-for-agents` | 文件/函数大小、命名碰撞、规范实现唯一性、Agent 搜索可达性 | 全仓库 |
| **C. 安全与威胁** | `secure-sdlc-and-threat-modeling` + `identity-and-secrets` + `input-validation-and-injection-defense` | 鉴权、加密、SSRF、注入、凭据管理、RBAC | 后端 auth/config/credential 路径 |
| **D. API 契约** | `api-design-and-compatibility` + `data-contracts` | OpenAPI 漂移、前后端契约、路由一致性 | `Code/shared/contracts/`、`openapi.json`、nginx/vite |
| **E. 测试质量** | `testing-and-quality-gates` | 覆盖率、测试可靠性、测试数据、CI 门禁 | `Test/`、`.github/workflows/ci.yml` |
| **F. 配置安全** | `configuration-and-automation-safety` | .env 管理、配置漂移、写操作安全性 | 后端 config 路径、`.env*` 文件 |
| **G. 性能与容量** | `performance-and-capacity` | 热路径、内存、并发、瓦片渲染 | 后端 weatherengine/tile_service、前端 WebGL |
| **H. 数据库操作** | `database-operations` | SQLite WAL、连接池、CAS 锁、SpatiaLite | 后端 `_sqlite_pool.py`、`workflow_repository.py` |
| **I. 缓存与派生数据** | `caching-and-derived-data` | Redis 缓存、天气缓存、瓦片缓存、失效策略 | 后端 `cache_service.py`、`weatherengine/` |
| **J. 依赖弹性** | `dependency-resilience` | 重试、熔断、限流、超时、降级 | 后端 `circuit_breaker.py`、`rate_limit.py`、Open-Meteo |
| **K. 容器与基础设施** | `container-runtime-and-orchestration` + `configuration-and-automation-safety` | Docker compose、nginx、启动器 | `Code/infra/`、`launch/`、`docker-compose.yml` |
| **L. 依赖与代码卫生** | `dependency-and-code-hygiene` | 死代码、静态分析积压、依赖更新、TODO | 全仓库 |
| **M. 可观测性** | `observability-and-alerting` | 日志、错误处理、健康检查、状态监控 | 后端 `main.py`、`runtime_status_service.py`；前端 `_http.ts`、`LogPanel` |
| **N. 数据管道可靠性** | `data-pipeline-reliability` | 数据同步、Open-Meteo 管道、数据接入 | 后端 `data_io/`、`Code/infra/data-sync/` |
| **O. 文档生命周期** | `documentation-lifecycle` | AGENTS.md 准确性、文档新鲜度、.ai/rules 一致性 | `Docs/`、`AGENTS.md`、`.ai/` |

---

## 三、逐维度审查要点

### 维度 A：架构边界（`architecture-decisions`）

**审查目标**：验证模块边界清晰、依赖方向正确、无循环依赖、无跨层泄漏。

**A1. 后端服务边界**
- 审查 `app/services/`（106 文件 / 29K 行）是否职责清晰
- 检查 `app/services/workflow/` 子目录与顶层 workflow_* 服务是否有重复职责
- 检查 `app/data_io/services/` 与 `app/services/import_service/` 是否有代码重复（AGENTS.md 已提及此问题）
- 检查 `app/weatherengine/` 与 `app/services/weather_*` 的边界划分
- 检查 `app/gee/` 子项目的独立性（独立 pyproject.toml、独立 tests）与主项目集成方式
- 检查 `app/services/node_template_registry.py`（3,398 行）是否应拆分

**A2. 前端模块边界**
- 审查 `components/map/`（48 文件）风场 WebGL 渲染链的模块化程度
- 检查 `stores/layers/`（27 文件）store 间依赖关系与循环引用风险
- 检查 `data-manager/` 与 `stores/` 的职责重叠
- 检查 `services/` 与 `stores/` 的分层是否清晰（service 不应直接修改 store 状态）

**A3. 算法包边界**
- 审查 `Code/algorithms/providers/Python/` 的子目录划分（algorithms/modules/data_access/ingest/service/workflow/contracts/pipelines）
- 检查 `algorithms/` 与后端 `app/services/python_provider_bridge_service.py` 的集成边界
- 检查 `Code/shared/contracts/` 是否被算法包正确引用

**A4. 依赖方向验证**
- 后端：`api/routers/` → `services/` → `core/`（不应反向）
- 前端：`views/` → `components/` → `stores/` → `services/`（不应反向）
- 算法：`algorithms/` → `shared/contracts/`（不应依赖后端/前端）
- 检查是否有 `services/` 直接导入 `api/` 的反向依赖
- 检查是否有 `stores/` 直接导入 `components/` 的反向依赖

**A5. 上下文映射（Bounded Context Map）**
- 产出系统上下文映射表：工作流引擎 / 天气引擎 / GEE 引擎 / 算法引擎 / 数据 I/O / 配置管理 / 鉴权 / 图层管理 / 前端 UI
- 标注每个上下文的职责、模型语言、上游/下游、关系模式（conformist / anti-corruption layer / shared kernel）

---

### 维度 B：代码可读性与 Agent 可搜索性（`code-readability-for-agents`）

**审查目标**：验证 Agent 能在一次工具调用中定位规范实现，无命名碰撞、无 God File。

**B1. God File 审查**
- 后端 >800 行的 ~32 个文件：逐个评估是否应拆分、按什么职责拆分
- 前端 >800 行的 ~25 个 .vue/.ts 文件：逐个评估组件拆分可行性
- 算法 >800 行的 ~5 个文件：评估是否为算法本质复杂度还是可拆分
- 特别关注：`node_template_registry.py`（3,398 行）、`omega_sf.py`（3,324 行）、`weather-tile-manager.ts`（1,948 行）

**B2. 命名碰撞检查**
- 全仓库搜索常见动词命名碰撞：`process`、`handle`、`update`、`run`、`apply`、`save`、`validate`、`resolve`、`build`、`create`
- 检查后端 `services/` 中是否有多个文件定义同名函数/类
- 检查前端 `stores/` 与 `services/` 中是否有同名导出
- 检查算法包 `modules/` 中的节点类名是否唯一

**B3. 规范实现唯一性**
- 对每个核心行为验证是否存在唯一实现：
  - "鉴权在哪里发生" → 应唯一定位到 `deps.py` / `auth_router.py`
  - "限流在哪里应用" → 应唯一定位到 `rate_limit.py`
  - "工作流如何编译" → 应唯一定位到 `workflow_graph_compiler.py`
  - "天气瓦片如何渲染" → 应唯一定位到 `tile_service.py`
  - "图层如何持久化" → 应唯一定位到 `workspace-persist.ts`
  - "配色方案如何切换" → 应唯一定位到 `useLayerSymbology.ts`
- 标记存在多个候选实现的行为

**B4. 测试可发现性**
- 验证后端测试命名约定（`test_<module>.py`）与源文件的映射关系
- 验证前端测试在 `Test/frontend/` 中保持 `src/` 目录结构的约定
- 标记无法通过函数名+约定找到测试的函数

**B5. 文档共存检查**
- 检查每个后端 `app/` 子目录是否有 `__init__.py` docstring 声明职责
- 检查前端 `src/` 子目录是否有 README 或 barrel export 声明职责
- 检查算法包各子目录的 `__init__.py` 是否声明公共接口

---

### 维度 C：安全与威胁模型（`secure-sdlc-and-threat-modeling` + `identity-and-secrets` + `input-validation-and-injection-defense`）

**审查目标**：验证鉴权、加密、输入验证、凭据管理无安全漏洞。

**C1. 鉴权与 RBAC**
- 审查 `auth_router.py`（429 行）：登录、账户管理、Token 发放/吊销逻辑
- 审查 `deps.py`（254 行）：鉴权依赖注入，Cookie/Token/API Key 三路验证
- 审查 `session_service.py`、`user_repository.py`、`permission_repository.py`：三角色模型（admin/standard/demo）实现
- 验证角色变更时是否吊销全部会话与 Token
- 验证 production 模式下 demo 开关是否强制关闭
- 检查 `/config/*` 写操作是否仅 admin 可写
- 检查 `/config/about` 是否仍公开（设计如此）

**C2. 加密与密钥管理**
- 审查 `core/config.py`（547 行）：`BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY` 64 hex 校验
- 审查 `gee_credentials_repository.py`、`api_keys_repository.py`、`remote_storage_credentials_repository.py`：加密存储实现
- 验证共享主密钥用于 GEE SA / API keys / 天气 provider / 远程存储 / 门户凭据的一致性
- 验证非 development 缺 key 拒启
- 验证空 IV 明文行在生产拒绝解密
- 检查密钥轮换路径是否存在

**C3. 输入验证与注入防御**
- 审查 `core/ssrf.py`：私网出站阻断（SSRF 防护）
- 审查 `import_router.py`（315 行）：栅格/矢量导入的路径安全、文件类型校验
- 审查 `remote_browser_router.py`（203 行）：远程文件浏览的路径穿越防御
- 审查 `data_io/api/router.py`（823 行）：文件操作的路径安全
- 检查所有接受用户输入路径的端点是否做了路径规范化与边界检查
- 检查文件上传是否限制大小、类型、扩展名
- 检查 SQL 拼接（SpatiaLite 空间查询）是否使用参数化

**C4. 凭据管理**
- 审查 `.env.example` 与 `.env` 的敏感信息隔离
- 检查是否有硬编码密钥/密码/Token（全仓库 grep）
- 审查 `env_file_upsert.py`：.env 写操作的安全性
- 检查 `credential_resolver.py`：凭据解析的降级路径
- 验证 Remote FileBrowser 请求是否带 `User-Agent` header（Cloudflare 403 问题）

**C5. 前端安全**
- 审查 `safe-redirect.ts`：开放重定向防御
- 审查 `session-expired.ts`：401 自动跳转登录的逻辑
- 审查 `backend-auth.ts` / `http-credentials.ts`：凭据存储与传输
- 检查是否有 `innerHTML` / `v-html` 导致的 XSS 风险
- 检查 LocalStorage / SessionStorage 中是否存储敏感信息

---

### 维度 D：API 契约与兼容性（`api-design-and-compatibility` + `data-contracts`）

**审查目标**：验证前后端 API 契约一致、OpenAPI 无漂移、路由配置对齐。

**D1. OpenAPI 契约漂移**
- 审查 `Code/frontend/openapi.json` 与后端实际路由的一致性
- 审查 `Code/shared/contracts/api_contracts.py`（684 行）与 OpenAPI 定义的一致性
- 检查 `npm run check:openapi` 是否覆盖所有端点
- 检查 `npm run gen:types` 生成的 `api-contracts.ts`（12,946 行）是否与 openapi.json 同步

**D2. 路由配置对齐**
- 完整比对 `vite.config.ts` proxy 键与 `nginx.conf` 两个 location 正则的并集
- 标记任何仅在一侧配置的路由
- 验证 `/analysis` 路由已在两侧配置（近期修复）
- 验证 `/auth`、`/overlay-tiles`、`/health` 等关键路由的一致性

**D3. API 版本与向后兼容**
- 检查 `workflow-runs` 主链与旧 `/tasks` 兼容桥接的实现
- 验证旧 `/tasks` 是否仅做兼容、不新增依赖
- 检查 API 响应字段是否有未声明的 breaking change
- 审查 `analysis_router.py`（88 行）新端点的 API 设计

**D4. 数据契约**
- 审查 `Code/shared/contracts/config_contracts.py`（435 行）配置契约
- 审查 `Code/algorithms/providers/Python/contracts/` 契约定义
- 检查 `WorkflowResultReference` 的 US-ASCII 约束是否在所有创建点遵守
- 检查 `MODULE_REQUEST_TEMPLATES` 与自动推导模板的优先级

---

### 维度 E：测试质量与 CI 门禁（`testing-and-quality-gates`）

**审查目标**：验证测试覆盖充分、测试可靠、CI 门禁有效。

**E1. 后端测试覆盖（110 文件 / 18K 行）**
- 对照"改 X 则跑 Y"映射表，验证每个关键模块是否有对应测试
- 检查以下核心模块的测试覆盖：
  - 工作流：编译 / 运行 / 定时器 / CAS 锁 / 取消 / 缓存复用
  - 天气：瓦片服务 / 点查 / 引擎 / 桥接 / 多源 / 限流 / 熔断
  - 安全：配置 / 鉴权 / 加密 / SSRF / 凭据
  - 数据：导入 / CRS / 栅格时序 / 可恢复上传
  - GEE：桥接服务
- 标记无测试覆盖的关键模块

**E2. 前端测试覆盖（123 文件 / 10.7K 行）**
- 检查 `components/map/` 风场 WebGL 渲染链的测试覆盖
- 检查 `stores/layers/` 27 个 store 模块的测试覆盖
- 检查 `services/` HTTP 调用层的测试覆盖
- 标记无测试覆盖的关键组件/store

**E3. 算法测试覆盖（64 文件）**
- 检查 `omega_sf.py`（3,324 行）核心算法的测试覆盖
- 检查 `omega.py`（2,878 行）正演模型的测试覆盖
- 检查数据接入格式适配器（TIFF/HDF/MAT/NetCDF/CSV/SHP）的测试覆盖
- 检查并行化（ProcessPoolExecutor）的测试覆盖

**E4. CI 门禁审查**
- 审查 `.github/workflows/ci.yml`（302 行）的 8 个 Job
- 验证 pre-commit → pytest → vitest → build → check:openapi → check:catalog 的依赖链
- 验证覆盖率阈值（后端 50%）是否合理
- 检查 `security-scan`（pip-audit + npm audit）是否非阻塞（continue-on-error）是否合理
- 检查 CI 环境与本地环境的一致性（Ubuntu vs Windows 差异）

**E5. 测试可靠性**
- 检查是否有 flaky 测试（依赖时序、网络、外部服务）
- 检查是否有 skip/xfail 标记的测试及其原因
- 检查 WorkBuddy 沙盒 shim 对测试的影响（`CODEBUDDY_SESSION_ID` 环境变量）
- 检查 `test_archive_safe.py` 对 `UnRAR.exe` 的依赖

---

### 维度 F：配置安全（`configuration-and-automation-safety`）

**审查目标**：验证配置管理安全、无配置漂移、写操作有保护。

**F1. .env 管理**
- 审查 `Code/backend/.env.example`（172 行）：配置项完整性
- 审查 `env_file_upsert.py`：.env 写操作的安全性（原子写入、权限）
- 检查 `BACKEND_DATA_ROOT` / `BACKEND_OUTPUT_ROOT` 空根拒启逻辑
- 检查 `BACKEND_PROJECTBACKUP_ROOT` 覆盖逻辑
- 检查 production 环境下演示开关强制关闭

**F2. 配置写操作**
- 审查 `config_routes.py`（677 行）：配置管理端点
- 审查 `config_service.py`（487 行）：配置服务
- 验证 `PUT /config/data-source/paths` 写 .env 后须重启后端进程组
- 检查配置变更是否触发 `restart backend`

**F3. 凭据配置**
- 审查 `config_api_keys.py`、`config_weather_providers.py`、`config_remote_storage.py`、`config_gee_accounts.py`
- 验证所有凭据配置端点仅 admin 可写
- 检查凭据加密存储的一致性

---

### 维度 G：性能与容量（`performance-and-capacity`）

**审查目标**：验证热路径性能、内存使用、并发控制无瓶颈。

**G1. 后端热路径**
- 审查天气瓦片渲染热路径：`GET /weather/tiles/...`（`WeatherTileService`）
- 验证天气瓦片不占 workflow 池（独立 `weather_tile` 池）
- 检查 `BACKEND_MAX_ACTIVE_RUNS=8` 与 `BACKEND_MAX_ACTIVE_WEATHER_TILE_RUNS=16` 的合理性
- 检查 Open-Meteo API 限流（8000 daily limit, 6400 soft warning）
- 检查文件流式传输（1MB 本地 / 5MB MinIO multipart）

**G2. 前端性能**
- 审查 WebGL 风场渲染链性能（`wind-particle-canvas.ts` 1,156 行 + `wind-particle-webgl-renderer.ts` 1,194 行）
- 检查瓦片请求并发控制（`MAX_CONCURRENT_TILE_FETCH=4`）
- 检查 `weather-tile-manager.ts` 视口防抖（350ms debounce）
- 检查 `MapLibre renderWorldCopies=true` 跨 ±180° 处理
- 检查大列表渲染（`AttributeTable.vue` 1,185 行）是否有虚拟滚动

**G3. 并发控制**
- 审查 Celery worker 并发管理（Windows solo / Linux prefork）
- 检查 `CGDA_MAX_PARALLEL_WORKERS` 配置
- 检查算法包 `ProcessPoolExecutor` 并行化（spawn context、自动 worker 数调整）
- 检查并行 chunk 超时保护（`CGDA_PARALLEL_TIMEOUT_PER_CHUNK`）

---

### 维度 H：数据库操作（`database-operations`）

**审查目标**：验证 SQLite/SpatiaLite 操作安全、无并发问题。

**H1. SQLite 连接池**
- 审查 `_sqlite_pool.py`（135 行）：WAL 模式、synchronous=NORMAL、busy_timeout、check_same_thread=False
- 验证连接池配置是否满足线程安全

**H2. CAS 锁**
- 审查工作流运行状态更新：`UPDATE ... WHERE run_id=? AND status=?`
- 验证终态冲突立即抛出 `ConcurrentModificationError`
- 验证非终态冲突重试 3 次
- 检查 CAS 操作的测试覆盖

**H3. SpatiaLite**
- 审查 `spatialite_loader.py`（245 行）：扩展加载与降级
- 检查空间查询是否使用参数化
- 验证 `BACKEND_SPATIALITE_ENABLED` 降级逻辑

---

### 维度 I：缓存与派生数据（`caching-and-derived-data`）

**审查目标**：验证缓存策略合理、失效正确、无脏数据。

**I1. Redis 缓存**
- 审查 `cache_service.py`（194 行）：缓存统计（hits/misses/upserts/evictions/hit rate）
- 审查 `circuit_breaker.py`（254 行）：熔断器（5 连续失败 → OPEN, 60s 超时, HALF_OPEN 探测）
- 检查 Redis key 命名约定（`weather:*`）
- 检查 `launch.py flush` 清缓存的范围与影响

**I2. 天气缓存**
- 审查天气文件缓存：`.data/cache/weather/` 与 `weatherengine/` 目录
- 验证 Open-Meteo API 429 错误时 stale cache fallback
- 检查缓存失效策略（TTL / 手动 / 事件驱动）
- 验证修改 `WeatherLayerSpec` 字段后清缓存的完整性

**I3. 瓦片缓存**
- 审查 `tile_proxy_service.py`（432 行）：瓦片代理缓存
- 检查瓦片缓存键的计算（layer_id / z / x / y / palette / style）
- 检查缓存淘汰策略

---

### 维度 J：依赖弹性（`dependency-resilience`）

**审查目标**：验证重试、熔断、限流、超时、降级策略完善。

**J1. Open-Meteo API 弹性**
- 审查 HTTP 请求级限流：`_RateLimitedResponse` wrapper
- 验证 429 错误时 slot 释放
- 审查 Redis 计数器（8000 daily limit, 6400 soft warning）
- 验证限额达限时 block + stale cache fallback
- 审查熔断器配置（5 连续失败 → OPEN, 60s, HALF_OPEN）

**J2. 工作流容量管理**
- 审查 429 容量错误处理（active_runs=4 时触发）
- 验证 prefetch concurrency 降低
- 验证 3 秒退避 + 队列重插入

**J3. 重试策略**
- 审查可重试失败的指数退避（max_attempts=3, initial_backoff=2s）
- 检查 `failure_classifier.py`（132 行）：失败分类逻辑
- 验证网络/API 失败降级 vs 编程 bug 传播

**J4. 远程数据源弹性**
- 审查 `Code/shared/remote_sources/transports/`：SFTP/SMB/GCS/FTP 传输错误处理
- 审查 `source_fetcher.py`（465 行）：流式传输错误处理
- 检查 Remote FileBrowser 连接超时与重试

---

### 维度 K：容器与基础设施（`container-runtime-and-orchestration` + `configuration-and-automation-safety`）

**审查目标**：验证 Docker 配置、nginx 配置、启动器安全可靠。

**K1. Docker Compose**
- 审查 `Code/backend/docker-compose.yml`：Redis / MinIO / Open-Meteo 容器配置
- 审查 `Code/infra/data-sync/docker-compose.yml`：数据同步隔离（`-p data-sync`）
- 验证 named volume `backend_open-meteo-data` 共享但 project 名不同
- 检查容器资源限制（memory / CPU）
- 检查容器健康检查配置

**K2. Nginx 配置**
- 审查 `Code/infra/gateway/nginx.conf`：反代规则、白名单正则
- 验证 `client_max_body_size 200m` 与后端上传限制一致
- 验证超时 600s 与 Celery task_time_limit 一致
- 验证 `50x.html` 错误页配置
- 完整比对 nginx 白名单与 vite proxy 路径

**K3. 启动器**
- 审查 `launch/commands.py`（893 行）：start/stop/status/restart/flush/sync 命令
- 审查 `launch/process_manager.py`（269 行）：进程生命周期管理
- 验证 `restart backend` 只重启 FastAPI + Worker + Beat（不动 Docker/Vite）
- 检查 Windows 管理员身份要求的实现
- 检查 `flush` 命令的影响范围与安全提示

---

### 维度 L：依赖与代码卫生（`dependency-and-code-hygiene`）

**审查目标**：验证无死代码、依赖不过时、静态分析无积压。

**L1. 死代码检查**
- 后端：检查 `forceStyle` 字段残留（近期修复后是否半死代码）
- 前端：检查 `cesium` / `vue-cesium` 3D 地球实验性功能的使用程度
- 检查 `Tools/` 下的 `_tmp_*` 临时脚本是否应清理
- 检查 `Tools/` 下的遗留启动脚本（`start_backend.py` 等）是否已被 `launch.py` 取代

**L2. 依赖版本**
- 审查 `requirements.txt`：30 个运行时依赖的版本锁定
- 审查 `package.json`：16 个核心依赖 + 18 个开发依赖
- 检查是否有已知漏洞的依赖版本
- 检查 `earthengine-api`、`rasterio`、`scipy` 等关键依赖的版本兼容性

**L3. TODO/FIXME 审查**
- 后端仅 2 条 TODO（`overlay_registry.py`、`source_fetcher.py`）：评估优先级
- 前端 0 条 TODO/FIXME/HACK
- 检查 `.ai/plans/` 与 `.ai/progress/` 中的待办事项是否仍有意义

**L4. 代码重复**
- 检查 `data_io/services/` 与 `services/import_service/` 的代码重复（AGENTS.md 已提及）
- 检查天气 provider 代码是否有重复模式可抽取
- 检查前端 `components/map/` 风场/标量场 WebGL 渲染链的代码重复

---

### 维度 M：可观测性（`observability-and-alerting`）

**审查目标**：验证日志、错误处理、健康检查、状态监控完善。

**M1. 后端可观测性**
- 审查 `app/main.py`（313 行）：全局异常处理
- 审查 `runtime_status_service.py`：运行时状态服务
- 审查 `app/core/logging.py`：日志配置
- 检查错误处理是否使用特定异常类型而非 broad `except Exception`
- 验证网络/API 失败降级 vs 编程 bug 传播的策略

**M2. 前端可观测性**
- 审查 `_http.ts`：HTTP 错误处理
- 审查 `session-expired.ts`：401 自动跳转
- 审查 `LogPanel.vue`：客户端日志（错误筛选 / JSON 导出 / badge）
- 审查 `ServiceConnectivityBanner.vue`：健康检查轮询
- 审查 `SystemStatusSettings.vue`：系统状态面板

**M3. 错误页面与降级**
- 审查 `NotFoundView.vue`：404 处理
- 审查 `AppErrorBoundary.vue`：前端错误边界
- 审查 `50x.html`：Gateway 5xx 错误页
- 验证 API 401（非 `/auth/*` bootstrap）→ 自动跳转登录

---

### 维度 N：数据管道可靠性（`data-pipeline-reliability`）

**审查目标**：验证数据同步、接入管道可靠、可重放。

**N1. Open-Meteo 数据同步**
- 审查 `Code/infra/data-sync/`：同步脚本与 compose 隔离
- 审查 `launch.py sync`：数据面一次性同步命令
- 验证同步幂等性（可重复运行）
- 检查同步失败的回滚与重试

**N2. 数据接入管道**
- 审查 `Code/algorithms/providers/Python/ingest/`：各数据源预处理
- 审查 `Code/algorithms/providers/Python/data_access/`：通用读取器
- 检查 `universal_reader.py`（661 行）多格式支持（TIFF/HDF/MAT/NetCDF/CSV/SHP）
- 验证数据接入的可重放性

**N3. 远程数据源**
- 审查 `Tools/remote_data_scanner.py`：远程数据扫描
- 审查 `Code/shared/remote_sources/`：多协议传输（FTP/SFTP/SMB/GCS）
- 验证远程数据只读约束
- 检查扫描 checkpoint 机制（每 200 目录保存）

---

### 维度 O：文档生命周期（`documentation-lifecycle`）

**审查目标**：验证文档准确、新鲜、与代码一致。

**O1. AGENTS.md 准确性**
- 验证"目录路由"表与实际目录结构一致
- 验证"命令指针"表与 `launch.py` 实际命令一致
- 验证"改 X 则跑 Y"映射表与实际测试命令一致
- 验证"高风险区"描述与实际代码一致
- 验证"前端错误与可观测性"描述与实际实现一致

**O2. .ai/rules 一致性**
- 审查 `.ai/rules/project-conventions.md`：运行时/launch/改X则跑Y/高风险区/命名/提交
- 审查 `.ai/rules/git-commit-message.md`：Conventional Commits 规范
- 验证规则文件与 AGENTS.md 指针的一致性

**O3. 文档新鲜度**
- 检查 `Docs/06-代码审查/` 历史审查报告的时效性
- 检查 `Docs/99-历史归档/` 代码事实同步快照是否标注"仅历史参考"
- 检查 `Docs/05-专题研究/` 中硬编码审计报告的覆盖范围
- 检查各 README.md 的准确性

---

## 四、审查执行顺序

### 阶段 1：基线验证（所有后续审查的前提）
1. 运行 `cd Code/frontend && npm run test && npm run lint && npm run build`
2. 运行 `CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= Env/Python312/python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="Test/.pytest-be"`
3. 运行 `Env/Python312/python.exe -m pytest Test/algorithms -q`
4. 运行 `pre-commit run --all-files`
5. 运行 `cd Code/frontend && npm run check:openapi && npm run check:catalog`
6. 记录基线状态（通过/失败/跳过数）

### 阶段 2：架构与可读性（维度 A + B）
7. 产出后端模块依赖图（grep import 关系）
8. 产出前端模块依赖图
9. 执行 God File 清单逐个评估
10. 执行命名碰撞检查
11. 执行规范实现唯一性检查（one-tool-call test）
12. 产出上下文映射表

### 阶段 3：安全深审（维度 C + F）
13. 鉴权与 RBAC 全链路审查
14. 加密与密钥管理审查
15. 输入验证与注入防御审查
16. 凭据管理审查
17. 前端安全审查
18. 配置安全审查

### 阶段 4：API 与契约（维度 D）
19. OpenAPI 契约漂移检查
20. 路由配置对齐检查（vite vs nginx）
21. 数据契约审查

### 阶段 5：测试与 CI（维度 E）
22. 后端测试覆盖缺口分析
23. 前端测试覆盖缺口分析
24. 算法测试覆盖缺口分析
25. CI 门禁有效性审查

### 阶段 6：数据与基础设施（维度 H + I + J + K + N）
26. SQLite/SpatiaLite 操作审查
27. 缓存策略审查
28. 依赖弹性审查
29. 容器与基础设施审查
30. 数据管道可靠性审查

### 阶段 7：性能与可观测性（维度 G + M）
31. 热路径性能审查
32. 并发控制审查
33. 可观测性审查

### 阶段 8：代码卫生与文档（维度 L + O）
34. 死代码检查
35. 依赖版本审查
36. 代码重复检查
37. 文档准确性验证

### 阶段 9：汇总与报告
38. 按维度汇总发现项
39. 产出风险优先级矩阵
40. 填充审查报告模板
41. 产出最终审查报告

---

## 五、审查输出格式

审查执行后，按以下结构产出详细审查报告：

```
# CGDA 全面代码审查报告

## 0. 审查元数据
- 审查范围：全仓库（~700+ 源文件 / ~225K 行 / 310 测试文件）
- 审查框架：SEM architecture-decisions（主）+ code-readability-for-agents（辅）
- 验证命令基线：前端 test/lint/build + 后端 pytest + pre-commit + check:openapi/check:catalog
- 基线状态：[通过/失败详情]

## 1. 架构边界审查（维度 A）
### 1.1 后端服务边界
### 1.2 前端模块边界
### 1.3 算法包边界
### 1.4 依赖方向验证
### 1.5 上下文映射表

## 2. 代码可读性审查（维度 B）
### 2.1 God File 清单与拆分建议
### 2.2 命名碰撞报告
### 2.3 规范实现唯一性报告
### 2.4 测试可发现性报告
### 2.5 文档共存检查
### 2.6 可读性记分卡

## 3. 安全与威胁模型审查（维度 C）
### 3.1 鉴权与 RBAC
### 3.2 加密与密钥管理
### 3.3 输入验证与注入防御
### 3.4 凭据管理
### 3.5 前端安全

## 4. API 契约审查（维度 D）
### 4.1 OpenAPI 契约漂移
### 4.2 路由配置对齐
### 4.3 数据契约

## 5. 测试质量审查（维度 E）
### 5.1 后端测试覆盖缺口
### 5.2 前端测试覆盖缺口
### 5.3 算法测试覆盖缺口
### 5.4 CI 门禁有效性
### 5.5 测试可靠性

## 6. 配置安全审查（维度 F）
## 7. 性能与容量审查（维度 G）
## 8. 数据库操作审查（维度 H）
## 9. 缓存与派生数据审查（维度 I）
## 10. 依赖弹性审查（维度 J）
## 11. 容器与基础设施审查（维度 K）
## 12. 依赖与代码卫生审查（维度 L）
## 13. 可观测性审查（维度 M）
## 14. 数据管道可靠性审查（维度 N）
## 15. 文档生命周期审查（维度 O）

## 16. 风险优先级矩阵
| 风险编号 | 维度 | 严重度 | 发现项 | 影响范围 | 建议动作 |
| --- | --- | --- | --- | --- | --- |

## 17. 改进建议汇总（按优先级排序）
## 18. 审查局限性说明
```

---

## 六、风险优先级预评估

基于代码库调研，以下为预判的高风险区域（审查时需重点关注）：

| 预判风险 | 维度 | 预估严重度 | 依据 |
|---------|------|-----------|------|
| `node_template_registry.py`（3,398 行）God Class | A+B | 高 | 单文件承载过多职责 |
| `data_io/services/` 与 `services/import_service/` 代码重复 | A+L | 高 | AGENTS.md 已提及 |
| `omega_sf.py`（3,324 行）+ `omega.py`（2,878 行）算法复杂度 | B+G | 中 | 核心算法本质复杂度 |
| 配色方案 `forceStyle` 残留半死代码 | L+C | 中 | 近期修复后遗留 |
| 前端 God Component（WorkflowCanvas 1,924 行等） | A+B | 中 | 5+ 个 >1,000 行的 .vue 文件 |
| SQLite CAS 锁在并发场景下的可靠性 | H | 中 | 单机 SQLite 并发限制 |
| Open-Meteo 限流 + 熔断 + stale cache 降级链 | I+J | 中 | 多层降级逻辑的边界情况 |
| Windows solo / Linux prefork worker 池差异 | K+G | 中 | 跨平台行为不一致 |
| CI (Ubuntu) 与本地 (Windows) 环境差异 | E+K | 中 | 路径/编码/依赖差异 |
| `api-contracts.ts`（12,946 行）生成与同步 | D | 低 | 自动生成但需验证同步 |
| `Tools/` 目录临时脚本积压 | L | 低 | ~50 个脚本，部分 `_tmp_*` |
| 文档与代码漂移 | O | 低 | AGENTS.md 虽活跃但需验证 |

---

## 七、假设与约束

1. **审查不修改代码**：本审查为只读分析，所有发现项记录在报告中，不直接修复
2. **基线验证可能失败**：部分测试受 WorkBuddy 沙盒 shim 影响，需用 `CODEBUDDY_SESSION_ID=` 前缀禁用
3. **`test_archive_safe.py` 依赖 UnRAR.exe**：本地可能未下载，该测试可能跳过
4. **GEE 凭据不可用**：GEE 功能可能处于 degraded mode，相关测试可能跳过
5. **远程数据源只读**：无法验证远程写入操作
6. **审查深度权衡**：~225K 行代码无法逐行审查，采用"重点深审 + 模式扫描 + 抽样验证"策略
7. **自动生成代码排除**：`api-contracts.ts`（12,946 行）为 OpenAPI 自动生成，排除逐行审查

---

## 八、审查质量保障

- **可追溯**：每个发现项标注具体文件路径与行号范围
- **可验证**：每个建议提供可执行的验证命令
- **有优先级**：所有发现项按严重度（Blocker / High / Medium / Low / Info）分级
- **有上下文**：引用 AGENTS.md、project_memory.md 中的已知约束与教训
- **不遗漏**：15 个维度 × 每维度 3-5 个审查点 = ~60+ 个审查检查点覆盖全仓库
