# 配置管理器实施计划

## 摘要

在工具栏"截图"与"日志"之间添加"设置"按钮，实现专业级配置管理器（右侧抽屉+左侧分类标签）。包含五大分类：常规设置、API管理、GEE账户管理、数据源、关于。重点功能为"API管理"（天地图/百度/Open-Meteo/后端认证）和"GEE账户管理"（多账户 Service Account 登录）。同步完善后端配置管理 API。

## 当前状态分析

### 前端
- **ModeToolbar.vue**（L149-169）：截图按钮和日志按钮紧邻，中间无设置入口
- **DashboardView.vue**（L44-46）：使用 `ref(false)` 管理面板开关（screenshotOpen/workflowStatusOpen/logOpen）
- **LogPanel.vue**：右侧抽屉模式参考（`.log-panel-overlay` fixed inset 0 + `.log-panel` 右侧 24rem）
- **ui store**：无配置管理状态
- **services/runtime-api.ts**：使用 fetch + 相对路径（dev 走 Vite proxy）

### 后端
- **config.py**：frozen dataclass `Settings`，全部从环境变量读取，无运行时修改能力
- **gee_credentials_repository.py**：已有 SQLite 持久化 GEE 账户（AES-GCM 加密），支持 upsert/list/delete/enable/test
- **gee_config_routes.py**：仅有 GET 端点（配置/限制/状态/环境），无账户管理 POST/PUT/DELETE
- **accounts/pool.py**：InMemoryAccountPool 支持 add_account/remove_account/snapshot/health_report
- **accounts/credentials.py**：GeeCredentialsLoader 支持 load/test 凭证
- **main.py**（L135-147）：通过 `app.include_router()` 注册路由

## 实施变更

### 第一部分：后端配置管理 API

#### 1. 新建 `Code/backend/app/services/api_keys_repository.py`
**用途**：API Key 的 SQLite 持久化层，支持运行时修改

**表结构**：
```sql
CREATE TABLE IF NOT EXISTS api_keys (
    key_name TEXT PRIMARY KEY,        -- 'tianditu' / 'baidu' / 'backend_auth'
    key_value TEXT NOT NULL,          -- 加密存储
    key_iv TEXT NOT NULL,             -- AES-GCM IV
    display_name TEXT NOT NULL,       -- 显示名称
    description TEXT,                 -- 描述
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_tested_at TEXT,
    last_test_status TEXT
);
```

**方法**：
- `upsert_key(key_name, key_value, display_name, description)` → 新增/更新
- `get_key(key_name)` → 获取解密后的 key（内部使用）
- `list_keys()` → 列出所有 key（脱敏，仅显示前4位+后4位）
- `delete_key(key_name)` → 删除
- `set_enabled(key_name, enabled)` → 启用/禁用
- `update_test_status(key_name, status)` → 更新测试状态

**加密**：复用 GEE credentials 的 AES-GCM 加密逻辑，密钥从 `settings.gee_credentials_encryption_key` 读取（共用加密密钥）

#### 2. 新建 `Code/backend/app/api/config_routes.py`
**用途**：配置管理 API 路由，前缀 `/config`

**端点列表**：

**常规设置**：
- `GET /config/general` — 获取常规配置（环境、版本、存储路径等，脱敏）
- `PUT /config/general` — 更新可写的常规配置

**API Key 管理**：
- `GET /config/api-keys` — 列出所有 API Key（脱敏：`tianditu_****1234`）
- `PUT /config/api-keys/{key_name}` — 新增/更新 API Key
- `DELETE /config/api-keys/{key_name}` — 删除 API Key
- `POST /config/api-keys/{key_name}/test` — 测试 API Key（针对天地图/百度发送测试请求）
- `PUT /config/api-keys/{key_name}/toggle` — 启用/禁用

**GEE 账户管理**：
- `GET /config/gee/accounts` — 列出所有 GEE 账户（脱敏，复用 `GeeCredentialsRepository.list_accounts()`）
- `POST /config/gee/accounts` — 新增 GEE 账户（上传 service_account JSON + account_id）
- `DELETE /config/gee/accounts/{account_id}` — 删除 GEE 账户
- `POST /config/gee/accounts/{account_id}/test` — 测试 GEE 账户（调用 `GeeCredentialsLoader.test_credentials()`）
- `PUT /config/gee/accounts/{account_id}/toggle` — 启用/禁用账户
- `POST /config/gee/accounts/reload` — 重载账户池（从 SQLite 重新加载到 InMemoryAccountPool）

**GEE 运行时配置**：
- `GET /config/gee/runtime` — 获取 GEE 运行时配置（并发限制、存储等）
- `PUT /config/gee/runtime` — 更新 GEE 运行时配置

**天气 API 配置**：
- `GET /config/weather` — 获取天气 API 配置（模型、缓存TTL、限流参数）
- `PUT /config/weather` — 更新天气 API 配置

**关于**：
- `GET /config/about` — 获取项目信息（版本、技术栈、模块列表、架构描述）

**请求/响应模型**（Pydantic）：
```python
class ApiKeyItem(BaseModel):
    key_name: str
    display_name: str
    description: str | None
    masked_value: str        # 脱敏值
    enabled: bool
    last_tested_at: str | None
    last_test_status: str | None

class ApiKeyUpdateRequest(BaseModel):
    key_value: str           # 明文 key（HTTPS 传输）
    display_name: str | None = None
    description: str | None = None
    enabled: bool = True

class GeeAccountItem(BaseModel):
    account_id: str
    display_name: str | None
    project_id: str | None
    account_type: str
    enabled: bool
    last_tested_at: str | None
    last_test_status: str | None

class GeeAccountCreateRequest(BaseModel):
    account_id: str
    service_account_json: dict    # service_account JSON 对象
    display_name: str | None = None

class GeeRuntimeConfig(BaseModel):
    max_parallel_exports: int
    max_parallel_uploads: int
    max_parallel_downloads: int
    account_cooldown_seconds: int

class WeatherConfig(BaseModel):
    default_model: str
    cache_ttl_seconds: int
    daily_api_limit: int
    soft_warning_threshold: int

class AboutInfo(BaseModel):
    project_name: str
    version: str
    description: str
    tech_stack: list[str]
    modules: list[dict]
    architecture_summary: str
```

#### 3. 更新 `Code/backend/app/main.py`
- 导入 `from app.api.config_routes import router as config_router`
- 在 L147 后添加 `app.include_router(config_router)`

#### 4. 新建 `Code/backend/app/services/config_service.py`
**用途**：配置管理业务逻辑层，协调 repository 和运行时状态

**职责**：
- 初始化 `ApiKeysRepository`（复用 GEE 的 SQLite 路径和加密密钥）
- 初始化 `GeeCredentialsRepository`（已存在，直接注入）
- 提供 `get_effective_api_key(key_name)` 方法：优先从 SQLite 读取，回退到 `settings` 环境变量
- 提供 `reload_gee_account_pool()` 方法：从 SQLite 重载账户到运行时 AccountPool
- 更新底图代理服务，使其调用 `get_effective_api_key()` 而非直接读 `settings`

#### 5. 更新底图代理服务
- 修改 `tile_routes.py` 或相关底图代理代码，使其通过 `config_service.get_effective_api_key('tianditu')` / `get_effective_api_key('baidu')` 获取 key
- 保持向后兼容：DB 无 key 时回退到 `settings.tianditu_api_key`

### 第二部分：前端配置管理器 UI

#### 6. 新建 `Code/frontend/src/stores/settings.ts`
**用途**：配置管理 Pinia store

**状态**：
```typescript
const apiKeys = ref<ApiKeyItem[]>([])
const geeAccounts = ref<GeeAccountItem[]>([])
const geeRuntimeConfig = ref<GeeRuntimeConfig | null>(null)
const weatherConfig = ref<WeatherConfig | null>(null)
const generalConfig = ref<GeneralConfig | null>(null)
const aboutInfo = ref<AboutInfo | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
```

**方法**：
- `loadAll()` — 并行加载所有配置
- `loadApiKeys()` / `updateApiKey(name, value)` / `deleteApiKey(name)` / `testApiKey(name)` / `toggleApiKey(name)`
- `loadGeeAccounts()` / `addGeeAccount(account_id, sa_json)` / `deleteGeeAccount(account_id)` / `testGeeAccount(account_id)` / `toggleGeeAccount(account_id)` / `reloadGeePool()`
- `loadGeeRuntimeConfig()` / `updateGeeRuntimeConfig(config)`
- `loadWeatherConfig()` / `updateWeatherConfig(config)`
- `loadAboutInfo()`

#### 7. 新建 `Code/frontend/src/services/settings-api.ts`
**用途**：配置管理 API 调用封装

**函数**：每个后端端点对应一个函数，使用 `resolveApiUrl()` + `fetch()`，与 `runtime-api.ts` 风格一致。

#### 8. 新建 `Code/frontend/src/components/settings/SettingsPanel.vue`
**用途**：主设置面板（右侧抽屉 + 左侧分类标签）

**布局结构**：
```
.settings-overlay (fixed inset 0, background: rgba(4,10,18,0.4))
└── .settings-panel (width: 38rem, max-width: 92vw, height: 100vh, right side)
    ├── .settings-header (标题 + 关闭按钮)
    ├── .settings-body (flex row)
    │   ├── .settings-nav (左侧导航, width: 9rem)
    │   │   ├── 常规设置
    │   │   ├── API管理
    │   │   ├── GEE账户管理
    │   │   ├── 数据源
    │   │   └── 关于
    │   └── .settings-content (右侧内容, flex: 1, overflow-y: auto)
    │       └── <component :is="activeTabComponent" />
    └── .settings-footer (保存/重置按钮，可选)
```

**样式**：复用 LogPanel 的暗色主题配色（rgba(8,17,31,0.98) 背景、#5ad5ff 强调色等）

**Props/Emits**：`emit('close')`

#### 9. 新建 `Code/frontend/src/components/settings/GeneralSettings.vue`
**用途**：常规设置标签页

**内容**：
- 环境信息（只读）：BACKEND_ENV、BACKEND_HOST、BACKEND_PORT
- 存储路径（只读）：data_root、output_root、cache_dir
- 工作流配置：max_active_runs（可编辑）、max_requested_outputs（可编辑）
- 日志级别（可编辑）：DEBUG/INFO/WARNING/ERROR

#### 10. 新建 `Code/frontend/src/components/settings/ApiKeySettings.vue`
**用途**：API 管理标签页（重点功能）

**布局**：按服务分组卡片
- **天地图**：API Key 输入框（脱敏显示）+ 测试按钮 + 启用/禁用开关
- **百度地图**：API Key 输入框 + 测试按钮 + 启用/禁用开关
- **Open-Meteo**：天气模型选择（best_match/gfs_seamless/era5等）+ 缓存TTL + 每日限额 + 软警告阈值
- **后端认证**：API Key 输入框 + 启用/禁用 + 密钥轮换

**交互**：
- 编辑模式：点击编辑按钮，输入框变为可编辑，显示保存/取消
- 测试：点击测试按钮，显示 loading → 成功/失败状态
- 脱敏显示：`tianditu_****1234` 格式，编辑时清空显示完整值

#### 11. 新建 `Code/frontend/src/components/settings/GeeAccountSettings.vue`
**用途**：GEE 账户管理标签页（重点功能）

**布局**：
- 顶部操作栏：添加账户按钮 + 重载账户池按钮
- 账户列表：每个账户一张卡片
  - 卡片内容：account_id、display_name（client_email）、project_id、状态徽章（启用/冷却/禁用）、测试状态
  - 卡片操作：测试、启用/禁用开关、删除（二次确认）

**添加账户流程**：
1. 点击"添加账户"→ 弹出表单
2. 输入 account_id（自定义标识）
3. 粘贴 service_account JSON 内容（textarea + JSON 校验）
4. 或上传 .json 文件（file input）
5. 可选输入 display_name
6. 提交 → 后端验证 JSON 格式 → 存储 → 刷新列表

**测试账户**：
- 点击测试 → 后端调用 `GeeCredentialsLoader.test_credentials()` → 显示结果
- 测试成功：绿色徽章 "有效"
- 测试失败：红色徽章 + 错误信息

#### 12. 新建 `Code/frontend/src/components/settings/DataSourceSettings.vue`
**用途**：数据源配置标签页

**内容**：
- 本地数据根目录（BACKEND_DATA_ROOT，只读显示）
- 产物输出根目录（BACKEND_OUTPUT_ROOT，只读显示）
- 存储后端类型（local/minio，只读显示）
- MinIO 配置（如果使用 minio）：endpoint、bucket、secure（只读显示）
- 远程 FileBrowser 服务器配置（只读显示）：win11 / nas 服务器地址和状态

#### 13. 新建 `Code/frontend/src/components/settings/AboutSettings.vue`
**用途**：关于标签页，包含项目架构思维导图

**内容**：
- 项目名称、版本、描述
- 技术栈标签云（Vue 3、FastAPI、Pinia、MapLibre、Celery、Redis、SQLite、MinIO、GEE、Open-Meteo）
- **架构思维导图**：使用 SVG 或 CSS 绘制树状结构图
  ```
                    综合地理态势分析系统
                         /        |        \
                   前端层       后端层      数据层
                  /  |  \      /  |  \    /  |  \
             UI组件 Store Service API 引擎  本地 远程 演示
  ```
  - 使用 CSS flexbox/grid 实现层级缩进 + 连接线
  - 每个节点可点击高亮（纯前端交互）
  - 不使用第三方思维导图库，纯 SVG/CSS 实现

#### 14. 更新 `Code/frontend/src/components/ModeToolbar.vue`
**变更**：
- 添加 `openSettings` 到 emits（L52-57）
- 在截图按钮（L149-157）和日志按钮（L160-169）之间添加设置按钮：
```vue
<!-- 设置 -->
<button
  class="tool-btn"
  type="button"
  title="系统设置"
  @click="emit('openSettings')"
>
  <span class="btn-icon" aria-hidden="true">⚙</span>
  <span class="btn-label">设置</span>
</button>
```

#### 15. 更新 `Code/frontend/src/views/DashboardView.vue`
**变更**：
- 导入 `SettingsPanel`（defineAsyncComponent）
- 添加 `const settingsOpen = ref(false)`（L46 附近）
- 添加 `handleOpenSettings` / `handleCloseSettings` 函数
- 在 ModeToolbar 事件绑定中添加 `@open-settings="handleOpenSettings"`（L262-271）
- 在模板末尾（LogPanel 之后）添加：
```vue
<SettingsPanel
  v-if="settingsOpen"
  @close="handleCloseSettings"
/>
```

## 假设与决策

1. **加密密钥共用**：API Key 加密复用 GEE 的 `gee_credentials_encryption_key`，避免引入新密钥。无密钥时明文存储（开发模式）。
2. **SQLite 路径**：API Keys 表与 GEE 账户表使用同一个 SQLite 文件（`gee_credentials.sqlite3`），或新建独立文件 `api_keys.sqlite3`。决定使用独立文件 `api_keys.sqlite3` 避免耦合。
3. **运行时生效**：API Key 更新后立即生效（通过 `config_service.get_effective_api_key()` 动态读取），无需重启后端。
4. **GEE 账户池重载**：添加/删除/启用/禁用 GEE 账户后，需手动点击"重载账户池"或自动触发 `reload_gee_account_pool()` 使运行时 AccountPool 同步。
5. **安全考虑**：API Key 列表接口返回脱敏值；编辑时通过 HTTPS 传输明文；前端不缓存明文 key。
6. **架构图**：纯 SVG/CSS 实现，不引入第三方思维导图库（如 mermaid），避免增加依赖。
7. **响应式**：设置面板在小屏幕下左侧导航变为顶部水平标签（`@media max-width: 600px`）。

## 验证步骤

1. **后端 API 验证**：
   - 启动后端后，curl 测试每个 `/config/*` 端点
   - `GET /config/api-keys` 返回脱敏列表
   - `PUT /config/api-keys/tianditu` 更新后 `GET` 确认生效
   - `POST /config/gee/accounts` 上传测试 JSON，`GET /config/gee/accounts` 确认
   - `DELETE /config/gee/accounts/{id}` 删除后确认
   - `POST /config/gee/accounts/{id}/test` 测试连通性

2. **前端 UI 验证**：
   - 工具栏"设置"按钮位于"截图"和"日志"之间
   - 点击设置 → 右侧抽屉滑出，左侧5个分类标签
   - API管理：编辑天地图 key → 保存 → 测试 → 显示结果
   - GEE账户管理：添加账户（粘贴 JSON）→ 列表显示 → 测试 → 删除
   - 关于：架构思维导图正确渲染
   - 关闭按钮 / 点击遮罩 → 抽屉关闭

3. **TypeScript 编译**：`npx vue-tsc --noEmit` 零错误

4. **集成验证**：
   - 更新天地图 key 后，切换到天地图底图，确认新 key 生效
   - 添加 GEE 账户后，提交 GEE 工作流，确认账户池使用新账户
