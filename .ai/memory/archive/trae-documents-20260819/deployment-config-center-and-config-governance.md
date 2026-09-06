# 数据源配置中心与配置文件治理 — 实施计划

> 插件：trae-remote-official:staff-engineer-mode（specialist：configuration-and-automation-safety）
> 原则：任何配置变更必须满足 **校验 → 预览(diff) → 确认 → 原子应用 → 可恢复**，fail-closed。

---

## 一、目标与范围

1. **消除部署阻塞型硬编码**：`I:\Geograph_DataSet` 及派生路径在部署机（win/linux、任意盘符/挂载点）上必须全量可配置，且默认值不再指向本机 I: 盘。
2. **新建「部署与数据源配置中心」独立页面**（新路由，仅 admin），集中管理：数据根/导入导出、运行时目录（节点/瓦片/处理/下载缓存）、产出结果/报告/分析图表、日志、Docker 相关；保存为**专属配置文件 `deployment.config.json`**，重启后自动载入。
3. **配置文件全景治理**：逐文件明确 多余/敏感层级（admin / 普通用户 / 底层）/ 类别（引导配置 vs 数据配置），并重定义 修改-加载-保存-重载 生命周期。

**不做**（范围边界）：
- 不改凭据类面板（API Key / GEE 账号 / 远程存储凭据 / 天气 Provider 已有专门管理界面，且均为 DB 热载配置）；
- 不自动改写 docker-compose.yml 本体（端口/volume 绑定等只读展示，仅维护 compose 已支持 env 注入的键）；
- 不迁移 `Tools/` 主线外脚本（仅出具审计报告，见附录 B）；
- 不动历史快照文档中的路径示例。

---

## 二、现状事实（Phase 1 探索结论）

### 2.1 硬编码审计结论（运行时代码中真实的 I: 盘残留）

| # | 位置 | 问题 | 严重度 |
|---|------|------|--------|
| H1 | `Code/backend/app/core/config.py:22` | `_RUNTIME_ROOT` 默认 `I:\Geograph_DataSet\_runtime`，派生 workflow_state/logs/artifacts/cache/python_provider/gee 共 7 个目录默认值。部署机改 `BACKEND_DATA_ROOT` 后 `_runtime` 仍指向 I: 盘 | **P0（部署阻塞）** |
| H2 | `Code/algorithms/providers/Python/ingest/gldas_download.py:46` | `DEFAULT_OUTPUT_DIR = Path(r"I:\Geograph_DataSet\...")`，**无 env 回退** | P0 |
| H3 | `Code/algorithms/providers/Python/ingest/nsidc_download.py:64-68` | 兜底回退 I:（注释已注明仅独立运行兜底，工作流节点显式传参） | 保留，文档标注 |
| H4 | `Code/backend/scripts/migrate_roles_v2.py:67` | `_runtime` 默认回退 I: | P1 |
| H5 | `Test/backend/conftest.py:29-33`、`Test/algorithms/conftest.py:22` | 未设 env 且 I: 盘存在时直接注入实验室真实路径 | P1（加显式开关） |
| H6 | `Code/backend/.env:16-17` | 本地实际值（部署机需整体重配，本计划的直接对象） | 由配置中心接管 |
| H7 | `Code/backend/.env.example:96-116` | 示例值为 I:（示例性质，需加"部署必改"注释） | P1 |
| H8 | `Code/backend/source_uri_map.example.json` | 26 个 `file:///I:/Geograph_DataSet/...` 图层 URI 模板 | P1（配置中心提供生成器） |
| H9 | `Code/frontend/src/components/settings/data-source/PathConfigSection.vue:149` | placeholder 文案 `例如 I:\Geograph_DataSet` | P1（改中性示例） |
| H10 | `Code/backend/app/core/redis_client.py:254-257` | 用字符串 `"127.0.0.1:8080" in url` 判定"本地 Open-Meteo"，改端口即失效 | P1（真 bug） |
| H11 | `Code/frontend/vite.config.ts:64` | `allowedHosts: ['geoflow.cgdas.dpdns.org']` 硬编码域名 | P2 |
| H12 | `launch/constants.py:47`、`launch/gateway_manager.py:22`、`launch/commands.py` | 端口 5175/8000 常量分散（有 DEFAULT_* 常量已集中，未接 env） | P2 |
| H13 | `Code/backend/app/data_io/services/archive_safe.py:459-460` | 7z.exe 探测候选 `C:\Program Files\7-Zip\...`（vendor/PATH 之后，合理探测序） | 保留 |
| H14 | `Code/backend/docker-compose.yml:26,48-49` | redis `127.0.0.1:6379:6379`、minio 端口绑定写死；`OPEN_METEO_HOST_PORT` 已支持 `${...}` 注入 | 只读展示（见 2.4） |
| H15 | `Code/infra/data-sync/docker-compose.yml:34-35` 与 `.env.example:4,7` | domains/variables 默认值双处重复维护 | P2 |

其余命中（README、Docs/、`Test/debug|standalone`、`Tools/` 全部脚本）均为文档/一次性脚本，不属运行链，见附录 B。

### 2.2 配置加载链（现状）

```
启动(launch.py) → backend 进程 import app.core.config:
  ① load_dotenv(Code/backend/.env)            ← 现有唯一文件真源
  ② Settings() 冻结实例化（各 BACKEND_* env → 字段默认值）
main.py lifespan:
  ③ hydrate_effective_config()  ← DB 覆盖(api_keys/runtime_config 投影，热载)
  ④ assert_data_root_policy()   ← production/test 空 DATA_ROOT 拒启
```
- **写 .env 的唯一入口**：`PUT /config/data-source/paths`（`config_service.update_data_source_paths` L390-469 → `env_file_upsert.upsert_env_keys` 原子写）。
- **重启**：`service_restart.schedule_backend_restart` 始终整组（fastapi+worker+beat）执行 `launch.py restart backend`。
- docker-compose（`Code/backend/docker-compose.yml`）自动读取**同目录 `.env`**；data-sync 栈读取 `Code/infra/data-sync/.env`（两份独立）。

### 2.3 鉴权与前端现状

- 后端 RBAC：`require_config_management_access`（仅 admin，deps.py L177-195）已覆盖全部 /config 写端点；`GET /auth/me` 返回 role（admin/standard/demo）；前端 `auth.isAdmin`（stores/auth.ts L28）。
- 前端**无路由级 admin 守卫**（router.ts L33-47 仅登录守卫）；admin 显隐仅有 `v-if="auth.isAdmin"` 面板模式（UserAccountSettings.vue:312）。
- 路由单一真源：`route-paths.ts` SPA_ROUTES（现仅 `/`）→ router.ts L20-24 全部映射 DashboardView；新增页面需登记 SPA_ROUTES **并**改 router.ts component 映射；`safe-redirect.ts` 白名单自动同步。
- 危险确认现用原生 `window.confirm`；表单样式复用 `settings-form.css`。

### 2.4 Docker 相关可配置面

| 键 | 作用 | 消费方 | 可经配置中心写 |
|---|---|---|---|
| `MINIO_ROOT_USER/PASSWORD` | MinIO 凭据 | backend/.env → compose 注入 | ✅（GET 脱敏，写空=不改） |
| `OPEN_METEO_HOST_PORT` | open-meteo 宿主端口 | backend/.env → compose `${...}` | ✅ |
| `OPEN_METEO_DATA_VOLUME` | 共享 named volume 名 | **两份 .env**（backend + data-sync） | ✅ 双写 |
| `OPEN_METEO_SYNC_DOMAINS/VARIABLES` | 同步范围 | data-sync/.env | ✅ 双写 data-sync/.env |
| redis/minio 端口绑定、gateway 5175 | compose/nginx 写死 | — | ❌ 只读展示 |

---

## 三、方案设计

### 3.1 部署配置真源：`Code/backend/deployment.config.json`

**加载顺序（config.py 修改点）**：
```
① load_dotenv(.env)                        # 不变
② 若存在 BACKEND_DEPLOYMENT_CONFIG（默认 Code/backend/deployment.config.json）：
   解析 + schema 校验 → 逐键 os.environ 覆盖（优先于 .env）→ 失败则拒启（fail-closed，报文件路径+.bak 位置）
③ Settings() 实例化                         # 不变，天然读到覆盖值
```
Celery worker/beat 同样 import config.py，覆盖自动生效；launch.py 不消费这些键，无需改动。

**Schema（v1，JSON，分组）**：
```jsonc
{
  "schema_version": 1,
  "data":    { "data_root": "", "output_root": "", "project_backup_root": "" },
  "runtime": { "runtime_root": "", "workflow_state_dir": "", "log_dir": "",
               "log_level": "INFO", "result_artifact_dir": "",
               "python_provider_workspace": "", "spatialite_db_path": "" },
  "caches":  { "cache_dir": "", "static_cache_root": "", "static_cache_ttl_seconds": 0,
               "download_source_root": "", "cache_default_ttl_seconds": 0,
               "tile_proxy_cache_ttl_seconds": 0 },
  "imports": { "max_imports_total_bytes": 0, "imports_soft_reserve_bytes": 0 },
  "docker":  { "minio_root_user": "", "minio_root_password": "",
               "open_meteo_host_port": 0, "open_meteo_data_volume": "",
               "open_meteo_sync_domains": "", "open_meteo_sync_variables": "",
               "open_meteo_local_url": "" },
  "notes": ""
}
```
- 空字符串/null = "未设置，不覆盖"（沿用现有 update_data_source_paths 语义）。
- 组→env 键映射表固定于 schema 模块（如 `data.data_root → BACKEND_DATA_ROOT`）；`docker.open_meteo_*` 键额外写入 `Code/infra/data-sync/.env`（仅 OPEN_METEO_DATA_VOLUME/SYNC_DOMAINS/SYNC_VARIABLES 三键）。
- **每键带元数据**（pydantic-style 声明，供 API 与前端共享）：env 键名、是否必须绝对路径、是否必须已存在（data_root/output_root=是；cache 类=允许自动创建）、生效方式（restart-backend / restart-full[docker] / none）、说明文案。

### 3.2 `_RUNTIME_ROOT` 派生修复（H1）

```python
# config.py L20-30 重写：
_data_root_env = os.getenv("BACKEND_DATA_ROOT", "").strip()
_RUNTIME_ROOT = Path(os.getenv("BACKEND_RUNTIME_ROOT", "").strip() or
                     (_data_root_env and str(Path(_data_root_env) / "_runtime"))
                     or str(BACKEND_ROOT / ".data" / "_runtime"))
```
- 显式 `BACKEND_RUNTIME_ROOT` > `<DATA_ROOT>/_runtime` > 仓库 `.data/_runtime`（dev 兜底）。I: 默认彻底移除。
- `.env.example` 对应示例与注释同步更新。

### 3.3 后端 API（新增，挂 `config_routes.py`）

| 端点 | 鉴权 | 行为 |
|---|---|---|
| `GET /config/deployment` | `require_config_read_access` | 返回：每键 {当前运行值, .env 值, deployment.json 值, 来源, 生效方式} + `pending_restart` + 文件存在性/备份列表。minio_password 恒脱敏 `••••` |
| `POST /config/deployment/preview` | `require_config_management_access` | 入参=期望配置（同 schema）。**纯只读**：跑全部校验（绝对路径/存在性/端口范围/字节数下限/schema），返回 `{errors[], warnings[], diff:[{key, env_key, old, new, source, restart_level}]}`。校验失败即整体 fail，不给部分应用 |
| `PUT /config/deployment` | `require_config_management_access` | 入参=期望配置。服务端**重新全量校验**（不信任前端预览结果，validation gate integrity）；通过后按序原子应用（见 3.4）；返回 applied diff + pending_restart |
| `POST /config/deployment/apply-restart` | mgmt | 复用现有 `POST /config/service/restart` 语义（本端点可省，前端直接调现有 restart；保留在设计中作为语义别名，实现时**砍掉**，避免重复端点） |
| `GET /config/deployment/export?redact=1` | mgmt | 导出脱敏 deployment.config.json（供部署机拷贝），`Content-Disposition: attachment` |

实现要点：
- 校验复用并扩展现有 `update_data_source_paths` 的路径校验（绝对+存在，config_service.py L354-387 抽出为 `_validate_path_field` 复用）。
- restart_level 计算：docker 组键变更 → `restart-full`（提示 `launch.py restart`，管理员本机执行）；其余 → `restart-backend`（可走 UI 重启，受 `BACKEND_UI_RESTART_ENABLED` 约束）。
- 新端点自动被 `Test/backend/test_config_security.py` 的路由扫描断言覆盖（必须挂依赖，L31-76）。

### 3.4 保存的原子应用序列（recovery path 内建）

```
1. 备份现 deployment.config.json → deployment.config.json.bak（保留最近 3 份轮换 .bak.1/.2/.3）
2. upsert_env_keys() 写 Code/backend/.env（全部映射键；敏感值非空才写）
3. 若含 docker.open_meteo_* → upsert 到 Code/infra/data-sync/.env（复用 env_file_upsert，path 参数已支持）
4. 原子写 deployment.config.json（临时文件 + os.replace，同 upsert_env_keys 模式）
5. 任一步失败：恢复 .bak、回滚已写 .env 键（用第 1 步前读到的旧值反向 upsert），返回明确错误 —— 拒绝半应用状态
6. 成功 → 返回 diff + pending_restart=true；前端引导"立即重启"或"稍后手动重启"
```
- 启动侧 fail-closed：deployment.config.json 存在但解析/schema 失败 → 拒启，错误信息含 `.bak` 恢复指引（`assert_data_root_policy` 同款 RuntimeError 风格，新增 `assert_deployment_config_policy`）。

### 3.5 前端：新路由页面「部署与数据源配置中心」

**路由**：
- `route-paths.ts`：`SPA_ROUTES` 增加 `{ path: '/deployment', name: 'deployment-config' }`（safeRedirect 白名单自动同步）。
- `router.ts`：该路由显式 component 映射 `DeploymentConfigView.vue`（lazy import），`meta: { requiresAdmin: true }`；beforeEach 增加：`if (to.meta.requiresAdmin && auth.bootstrapped && !auth.isAdmin) return '/'`（UX 层，后端 API 已兜底）。
- `Test/frontend/auth-router.test.ts` 扩展：requiresAdmin 路由对非 admin 重定向、admin 放行。

**页面 `src/views/DeploymentConfigView.vue`**：
- 顶部状态条：当前 `data_root` 生效值、`pending_restart` 徽章（复用 PathConfigSection 模式）、`.env`/`deployment.json`/运行值三方不一致提示。
- 分组卡片（Tabs 或纵向卡片，复用 `settings-form.css`）：数据根 / 运行时与日志 / 缓存 / 导入导出 / Docker。每字段：label + 说明（后端元数据下发）+ 输入框；密码类 password input，placeholder "留空保持不变"。
- 三步操作流（页面内状态机 `editing → previewing → applying`）：
  1. 编辑 → 「预览变更」→ `POST preview`；
  2. 展示 diff 表（键、旧→新、来源、生效方式）+ errors/warnings；有 error 阻断，warning（如"目录不存在将自动创建"）可继续；
  3. 「确认并保存」（danger 确认，`window.confirm` 与现有一致）→ `PUT` → 成功后按 restart_level 提示：restart-backend → 复用现有 `restartBackendService` + `waitForBackendHealthy`（GET /health 轮询，120s，PathConfigSection.vue L107-108 同款）；restart-full → 明确文案"需在服务器执行 launch.py restart"。
- 入口：`SettingsPanel.vue` 顶部（admin 可见）「部署配置中心」按钮跳 `/deployment`；`ModeToolbar` 不加（保持工具栏简洁）。
- 非直接消费组件（PathConfigSection/LocalDataSourcePanel）保留不动，仅在 DataSourceSettings 顶部加提示卡引导至新页面（避免双入口数据不一致，旧入口后续版本再下线——本计划不动）。

**服务层**：`src/services/settings-api.ts` 增加 `getDeploymentConfig` / `previewDeploymentConfig` / `updateDeploymentConfig` / `exportDeploymentConfig`（沿用 `settingsFetch` 15s 超时 + withWriteAuthHeaders）。类型入 `src/types/api-contracts.ts`（`check:openapi` 会对齐，需同步后端 openapi 导出）。

### 3.6 配置文件治理（全景矩阵与生命周期）

**A. 文件清单与判定**（写入新文档 `Docs/03-规范协议/配置文件治理说明.md`，附表）：

| 文件 | 判定 | 层级 | 读 | 写 | 处置 |
|---|---|---|---|---|---|
| `Code/backend/deployment.config.json`（新） | **部署/数据配置真源** | admin | API(read) | API(mgmt) only | 本计划新增 |
| `Code/backend/.env` | 底层引导配置（含密钥） | admin | 文件系统（API 脱敏） | 仅经配置中心 / 手动 | 由配置中心镜像维护 |
| `Code/backend/.env.example` | 模板 | 公开(仓库) | — | 开发者 | P1：更新示例+部署必改注释 |
| `Code/infra/data-sync/.env(.example)` | 数据面底层 | admin | 文件系统 | 配置中心（限 3 键）双写 | 保留 |
| `deployment.config.json.bak.*` | 备份 | admin | 文件系统 | 系统自动 | 轮换 3 份 |
| `source_uri_map.example.json` | 图层 URI 机构模板 | 公开(仓库) | — | 开发者 | P1 生成器消费 |
| DB（api_keys/gee/weather/remote_storage/runtime_config） | 运行时热载配置 | admin(写)/standard(读) | API | API | 已有面板，不动 |
| `catalog_seeds/`、`workflow_seeds/` | 数据目录种子 | 公开(仓库) | — | 开发者 | 不动 |
| 前端 `settings-local`（localStorage） | 用户偏好 | 用户本人 | 本地 | 本地 | 不动 |
| **多余项**：`AGENTS.md`「Open-Meteo 双源」行引用的 `.env.open-meteo.example` | 文档漂移（实际为 `Code/infra/data-sync/.env.example`） | — | — | — | P1 修正 AGENTS.md |

**B. 生命周期矩阵**（同文档 + API 元数据下发）：

| 变更对象 | 修改入口 | 校验 | 保存 | 生效/重载 |
|---|---|---|---|---|
| 路径/存储/配额（deployment.json 组） | 配置中心 | preview 全量校验 | 原子写+备份+.env 镜像 | `launch.py restart backend`（docker 组需全量 restart） |
| 凭据/Provider（DB） | 既有设置面板 | 既有 | DB | `invalidate_effective_config` 热载，无需重启 |
| 前端偏好 | 界面设置 | — | localStorage | 即时 |
| `.env` 手改（运维应急） | 文件系统 | 启动断言 | — | 重启后生效；与 deployment.json 冲突时**后者优先**（启动日志打印覆盖键清单） |

**C. 漂移防护**：`GET /config/deployment` 的三方对比（运行值 vs .env vs json）即 drift 检测；`pending_restart` 语义沿用 `get_data_source_config`（config_service.py L301-311）并扩展到全部键。

### 3.7 P1 修复项（随 Batch 4 落地）

- H2：`gldas_download.py` 改 `os.getenv("BACKEND_DATA_ROOT")` 注入 + 缺省 raise（对齐 `dataset_config._get_data_root` fail-fast 模式；走 algorithms pre-commit ruff+mypy）。
- H4：`migrate_roles_v2.py` 回退改为仓库 `.data/_runtime`。
- H5：两处 conftest 增加 `CGDA_TEST_DATA_ROOT` 显式覆盖开关，未设时保持现有"I: 存在才用"行为（向后兼容，CI 无 I: 盘不受影响）。
- H7：`.env.example` 示例值改 `<部署数据根>` 占位风格 + 顶部"部署机必改清单"注释块。
- H9：placeholder 改 `例如 D:\geo_data 或 /data/geo_data`。
- H10：`redis_client.py` 判定改为从 `settings.open_meteo_local_url` 解析 host:port 比对（换端口不再失效），补单测。
- H8：配置中心「生成 URI 映射」按钮（P1 末位，可单独提交）：实现前先确认 `BACKEND_DOWNLOAD_SOURCE_URI_MAP` 的解析格式（config.py L524-527，内联 JSON 还是文件路径），按实际格式从 data_root + example 模板批量替换生成。
- H11/H12/H15：P2 记录在治理文档"后续项"，不在本计划实施。

---

## 四、实施批次与验证

### Batch 1 — 后端真源与硬编码修复（P0）
改：`app/core/config.py`（加载链+派生）、`app/services/deployment_config.py`（新：schema/校验/加载/原子应用）、`app/services/effective_config.py`（新增 assert_deployment_config_policy，main.py lifespan 挂接）、`.env.example`。
验证：`Env/Python312/python.exe -m pytest Test/backend/test_data_root_policy.py Test/backend/test_deployment_config.py -q`（新测试：派生优先级、json>.env 覆盖、坏文件拒启、原子写+回滚、备份轮换）。

### Batch 2 — 配置中心 API
改：`app/api/config_routes.py`（4 端点）、`app/services/config_service.py`（抽 `_validate_path_field` 复用）、openapi 导出。
验证：`Env/Python312/python.exe -m pytest Test/backend/test_config_security.py Test/backend/test_deployment_config.py Test/backend/test_data_source_paths.py -q`；`cd Code/frontend && npm run check:openapi`。

### Batch 3 — 前端页面与路由守卫
改：`src/app/route-paths.ts`、`src/app/router.ts`、`src/views/DeploymentConfigView.vue`（新）、`src/components/settings/SettingsPanel.vue`（入口）、`src/services/settings-api.ts`、`src/types/api-contracts.ts`、`PathConfigSection.vue` placeholder。
验证：`cd Code/frontend && npm run test -- deployment-config auth-router data-source-settings && npm run lint && npm run build`。

### Batch 4 — 治理与 P1 修复
改：`Docs/03-规范协议/配置文件治理说明.md`（新，含 §3.6 矩阵+附录 B 审计清单）、`AGENTS.md` 漂移修正、`gldas_download.py`、`migrate_roles_v2.py`、`Test/*/conftest.py`、`redis_client.py`。
验证：后端 `pytest Test/backend/test_config_security.py -q` + 新增 redis 判定单测；算法 `pre-commit run --files Code/algorithms/providers/Python/ingest/gldas_download.py`；后端全量回归按 AGENTS.md WorkBuddy 前缀约定执行。

### 端到端验收（手动，一次）
1. dev 起服 → admin 登录 → 访问 `/deployment`（standard/demo 账号访问应被重定向回 `/`）；
2. 修改 `data_root` 为新目录 → 预览 diff → 确认 → UI 重启 → 验证 `GET /config/deployment` 三方一致、`GET /layers` 的 `run_readiness` 按新根变化；
3. 写坏 deployment.config.json → 重启应拒启且错误指引 .bak；恢复 .bak 后正常；
4. 改 `open_meteo_host_port` → 确认两份 .env 均更新、提示需全量 restart。

---

## 五、风险与回滚

| 风险 | 缓解 |
|---|---|
| deployment.json 损坏导致拒启 | fail-closed + .bak 轮换 3 份 + 错误信息含恢复命令；runbook 写入治理文档 |
| 双写（json/.env×2）中途失败半应用 | 3.4 步骤 5 反向回滚已写键；应用前置备份；测试覆盖"第二步失败"分支 |
| 与既有 `PUT /config/data-source/paths` 双入口冲突 | 配置中心为 admin 新主入口；旧端点保留（测试依赖），页面层加引导；不删旧端点（后续版本再议） |
| `_RUNTIME_ROOT` 派生变更影响本机现网 dev | 本机 `.env` 已显式含 DATA_ROOT=I:\…，派生结果与现状一致（`I:\Geograph_DataSet\_runtime`），行为无变化；仅删除"未配置时的 I: 默认" |
| 前端新页面暴露敏感值 | 路径非敏感全量展示；minio_password 全链路脱敏（GET/preview/export） |
| schema_version 演进 | v1 起步；loader 拒绝未知 version（fail-closed），升级走新 version + 迁移函数 |

## 六、假设与决策记录

1. 专属配置文件采用 **JSON**（与仓库 JSON 生态/catalog seeds 一致，pydantic 风格校验），位置 `Code/backend/deployment.config.json`，可经 `BACKEND_DEPLOYMENT_CONFIG` env 改址（自举场景）。
2. `.env` 保留为兼容镜像（docker-compose 仅认 .env），deployment.json 为优先真源——两者都由同一 PUT 原子维护，不产生双头编辑。
3. 前端路由级 admin 守卫只做 UX（后端 `require_config_management_access` 是安全边界），符合现有分层。
4. 「应用即重启」不自动执行：保存返回 pending_restart，由管理员显式点击重启（受 `BACKEND_UI_RESTART_ENABLED` 约束）——避免保存即中断在线会话。
5. docker compose 本体不改写：端口绑定类仅只读展示 + 治理文档说明；可 env 注入键全量纳入配置中心。
