# CGDA 安全升级与角色权限重构方案

> 基于 2026-08-13 代码审计结果更新。审计覆盖后端鉴权模块（auth_router/auth_bootstrap/user_repository/deps）、安全配置与加密（config_routes/effective_config/gee_credentials_repository/main.py）、工作流并发控制（submission_service/lifecycle_service/follow_up_dispatch_service）、前端契约（openapi.json/前端组件/测试文件）四大领域。
>
> **2026-08-13 更新**：Phase A/B/C/D 全部实施完成。后端测试 28 passed（auth + resource_permissions），前端测试 636 passed，lint 0 errors，build success，OpenAPI 契约校验通过。

## 一、当前状态总览

### 1.1 已完成（无需额外工作）

以下项目已在代码审计中确认实现，标记为完成：

| 计划项 | 涉及文件 | 确认状态 |
|--------|---------|---------|
| P0: 安全响应头中间件（X-Frame-Options/X-Content-Type-Options/HSTS/CSP） | `app/main.py` L63-92 | ✅ 已实现，生产环境启用完整 CSP+HSTS |
| P1-a: 加密密钥版本标记（v1: 前缀 + 旧格式兼容） | `app/services/gee_credentials_repository.py` | ✅ 已实现，AES-GCM-256 + 随机 12-byte IV |
| P1-b: Dev Bypass 启动断言 | `app/services/effective_config.py` L53-67 | ✅ 已实现，非 development 禁止 api_keys_enabled=false |
| P2-a: CORS 收紧（显式 origins/methods/headers） | `app/main.py` L50-73 | ✅ 已实现，空 origins fail-fast |
| P2-b: 开发默认凭据非 loopback 拒绝 | `app/services/auth_bootstrap.py` L29-42 | ✅ 已实现 |
| 角色重命名（后端）: VALID_ROLES/WRITE_ROLES 更新 | `user_repository.py`/`credential_resolver.py`/`deps.py` | ✅ 已实现，admin/standard/demo 三角色 |
| 配置管理端点 admin-only 收紧 | `app/api/config_routes.py` | ✅ 全部写端点使用 `require_config_management_access` |
| 上传下载 demo 管控 | `app/api/deps.py`/`credential_resolver.py` | ✅ `can_data_transfer()` 含 demo 开关 |
| 工作流创建权限区分 | `app/api/deps.py`/`credential_resolver.py` | ✅ `require_workflow_create_access` 已实现 |
| 数据库迁移脚本 | `Code/backend/scripts/migrate_roles_v2.py` | ✅ 脚本已存在，支持 dry-run + 备份 |

### 1.2 已实施改动（2026-08-13 完成）

| 领域 | 实施项 | 涉及文件 | 验证状态 |
|------|--------|---------|---------|
| Phase A: 契约同步 | openapi.json 角色枚举更新 + 前端旧角色清理 | `openapi.json`/`UserAccountSettings.vue`/`SettingsPanel.vue`/`auth-store.test.ts` | ✅ 前端 636 tests passed |
| Phase B: 资源访问控制 | 权限表 + PermissionRepository + 管理 API + 访问检查中间件 + 前端 UI | `permission_repository.py`/`user_repository.py`/`auth_router.py`/`deps.py`/`layer_router.py`/`workflow_definition_router.py`/`UserAccountSettings.vue`/`auth-api.ts` | ✅ 后端 19 tests passed + 22 regression tests passed |
| Phase C: 工作流并发控制 | 按角色并发上限 + 排队唤醒机制 + 运行时配置 | `submission_service.py`/`queue_dispatch_service.py`/`lifecycle_service.py` | ✅ 后端 80 tests passed |
| Phase D: 前端适配 | 排队状态 UI + demo 禁用提示 + 角色显示文案 | `WorkflowRunList.vue`/`DataSourceSettings.vue`/`SettingsPanel.vue` | ✅ 前端 636 tests + lint 0 errors + build success |
| OpenAPI 契约 | 重新生成 openapi.json（175 paths, 202 schemas） | `openapi.json`/`api-contracts.ts` | ✅ check:openapi 通过 |

---

## 二、角色权限模型（当前状态，无需修改）

### 2.1 角色定义（已生效）

| 角色 | 后端字面量 | 定位 |
|------|-----------|------|
| admin | `"admin"` | 管理员，几乎所有操作无限制 |
| standard | `"standard"` | 标准用户，可查看全部内容，可创建图层/工作流，工作流并发受限 |
| demo | `"demo"` | 演示账户，可查看全部内容，可运行工作流+创建图层，不能创建工作流，上传下载受管控 |

### 2.2 权限矩阵（已生效，代码审计确认）

| 权限维度 | admin | standard | demo |
|----------|-------|----------|------|
| 查看所有图层/数据 | ✓ | ✓ | ✓ |
| 查看系统配置（脱敏） | ✓ | ✓ | ✗ |
| 创建新图层 | ✓ | ✓ | ✓ |
| 创建新工作流定义 | ✓ | ✓ | ✗ |
| 运行工作流 | ✓ 不限并发 | ✓ 限并发 | ✓ 限并发 |
| 修改高危配置（API Key/GEE/加密/远程存储/天气/Provider） | ✓ | ✗ | ✗ |
| 修改常规配置（无专门类别，统一归入配置管理） | ✓ | ✗ | ✗ |
| 上传/下载数据 | ✓ 不限 | ✓ 不限 | △ 受 `demo_data_transfer_enabled` 开关控制 |
| 用户管理 | ✓ | ✗ | ✗ |

### 2.3 鉴权规则源（代码已确认）

| 规则 | 定义位置 | 效果 |
|------|---------|------|
| `_WRITE_ROLES` | `credential_resolver.py` L19 | `{"admin", "standard"}` — demo 不可写 |
| `_CONFIG_MANAGEMENT_ROLES` | `credential_resolver.py` L20 | `{"admin"}` — 仅 admin 可管理配置 |
| `_WORKFLOW_CREATE_ROLES` | `credential_resolver.py` L21 | `{"admin", "standard"}` — demo 不可创建 |
| `can_data_transfer()` | `credential_resolver.py` L99 | demo 受 `settings.demo_data_transfer_enabled` 控制 |
| `require_write_access` | `deps.py` L68 | 综合：session/API Token/service key/dev_bypass |
| dev_bypass 条件 | `credential_resolver.py` L149 | 仅 development + loopback 或显式 `BACKEND_DEV_AUTH_BYPASS` |

---

## 三、安全基础设施（当前状态，无需修改）

### 3.1 安全响应头（已生效）

在 `app/main.py` 的 `security_headers_middleware` 中，所有请求响应均设置以下头：

| 响应头 | 值 | 防护目标 |
|--------|---|---------|
| `X-Content-Type-Options` | `nosniff` | MIME 类型嗅探 |
| `X-Frame-Options` | `DENY` | 点击劫持 |
| `Referrer-Policy` | `strict-same-origin` | 跨源 Referer 泄露 |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` | 浏览器 API 滥用 |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains`（仅生产） | HTTPS 降级 |
| `Content-Security-Policy` | 限制 script/src/style-src/img-src（仅生产） | XSS/注入 |

### 3.2 CORS 配置（已生效）

- 空 origins 列表时 fail-fast（拒绝 `*` 通配符）
- 默认 origins：localhost 5173-5176/4173
- 显式 methods/headers 白名单，不开放通配符
- `allow_credentials=True` 配合显式 origins，安全

### 3.3 加密体系（已生效）

- 算法：AES-GCM-256，使用 `cryptography.hazmat.primitives.ciphers.aead.AESGCM`
- 密文格式：`v1:{ciphertext_b64}` + 独立 `iv_b64` 列
- 旧格式兼容：无前缀视为 v0，仅 development 环境允许
- 生产环境缺 key 或缺 cryptography 包：fail-fast 拒绝启动
- 开发环境无 key：记录 error 日志，明文模式运行

### 3.4 限流体系（已生效）

| 限流面 | 阈值 | 实现 |
|--------|------|------|
| 写接口（/config/*/import/*/workflow-runs/* 等） | 120 次/分钟/IP | Redis 集中计数，降级进程内滑动窗口 |
| 登录（/auth/login） | 10 次/分钟/IP | 同上 |
| 天气瓦片（/weather/tiles/**） | 240 次/分钟/IP | 同上 |
| 生效范围 | 仅 production | development/test 旁路 |

### 3.5 启动安全关卡（已生效）

| 断言 | 触发位置 | 行为 |
|------|---------|------|
| `assert_encryption_policy()` | Application lifespan | 生产环境缺 key 拒启 |
| `assert_data_root_policy()` | Application lifespan | 生产环境缺数据根拒启 |
| `assert_dev_bypass_policy()` | Application lifespan | 生产环境误启 api_keys_enabled=false 拒启 |
| `_check_dev_credentials_safety()` | `bootstrap_auth()` | 开发环境绑定非 loopback 拒用默认凭据 |

---

## 四、待实施改动

### Phase A：前端契约同步与旧角色清理（约 0.5 天）

**目标**：将 openapi.json 和前端组件中的旧角色名 `operator`/`viewer` 更新为 `standard`/`demo`，与后端保持同步。

#### A-1：更新 openapi.json 角色枚举（0.5h）

**现状**：`openapi.json` 中 `CreateUserRequest` 和 `UserPublic` 的 `role` 字段枚举为 `["admin", "operator", "viewer"]`，默认值为 `"operator"`。

**方案**：重新生成 openapi.json 以反映后端最新角色定义。

```
cd Code/backend && ../../Env/Python312/python.exe scripts/export_openapi.py
```

生成后运行校验：
```
cd Code/frontend && npm run check:openapi && npm run gen:types
```

**影响文件**：
- `Code/frontend/openapi.json` — 自动生成，角色枚举自动同步
- `Code/frontend/src/types/api-contracts.ts` — 由 `gen:types` 自动生成

#### A-2：前端组件旧角色引用清理（1h）

**现状**：`UserAccountSettings.vue` 和 `SettingsPanel.vue` 中共 11 处使用 `operator`/`viewer` 作为角色值。

**改动清单**：

| 文件 | 行 | 当前值 | 改为 |
|------|----|--------|------|
| `SettingsPanel.vue` | 124 | `operator: '操作员'` | `standard: '标准用户'` |
| `SettingsPanel.vue` | 125 | `viewer: '只读'` | `demo: '演示'` |
| `UserAccountSettings.vue` | 22 | `const newRole = ref<UserRole>('operator')` | `const newRole = ref<UserRole>('standard')` |
| `UserAccountSettings.vue` | 32 | `operator: '操作员'` | `standard: '标准用户'` |
| `UserAccountSettings.vue` | 33 | `viewer: '只读'` | `demo: '演示'` |
| `UserAccountSettings.vue` | 75 | `newRole.value = 'operator'` | `newRole.value = 'standard'` |
| `UserAccountSettings.vue` | 209 | `{ label: '操作员', value: 'operator' }` | `{ label: '标准用户', value: 'standard' }` |
| `UserAccountSettings.vue` | 210 | `{ label: '只读', value: 'viewer' }` | `{ label: '演示', value: 'demo' }` |
| `UserAccountSettings.vue` | 235 | `{ label: '操作员', value: 'operator' }` | `{ label: '标准用户', value: 'standard' }` |
| `UserAccountSettings.vue` | 236 | `{ label: '只读', value: 'viewer' }` | `{ label: '演示', value: 'demo' }` |

#### A-3：前端测试旧角色清理（0.2h）

| 文件 | 行 | 当前值 | 改为 |
|------|----|--------|------|
| `Test/frontend/stores/auth-store.test.ts` | 11 | `roles: ['admin', 'operator', 'viewer']` | `roles: ['admin', 'standard', 'demo']` |

#### A-4：执行数据库迁移（0.3h，部署时执行）

```
cd Code/backend
../../Env/Python312/python.exe scripts/migrate_roles_v2.py --dry-run  # 预览
../../Env/Python312/python.exe scripts/migrate_roles_v2.py            # 实际执行
```

迁移完成后执行 `FLUSHDB` 清空 Redis（吊销全部 session/token），强制所有用户重新登录。

**迁移窗口**：选择无活跃工作流时段。

---

### Phase B：资源访问控制基础版（约 2 天）

**目标**：支持管理员对 standard/demo 用户按资源（图层/工作流定义/数据源路径）进行访问控制，支持黑名单/白名单两种模式。

#### B-1：数据库层 — 新增权限表与字段（0.5天）

**新增表** `user_resource_permissions`：

```sql
CREATE TABLE IF NOT EXISTS user_resource_permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resource_type TEXT NOT NULL,   -- 'layer' | 'workflow' | 'data_source'
    resource_id TEXT NOT NULL,     -- 图层 ID / 工作流定义 ID / 数据源路径
    permission TEXT NOT NULL,      -- 'allow' | 'deny'
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, resource_type, resource_id)
);
```

**新增字段** `users.permission_mode`：

```sql
ALTER TABLE users ADD COLUMN permission_mode TEXT NOT NULL DEFAULT 'open';
-- open: 默认开放（黑名单模式）
-- whitelist: 白名单模式（仅 allow 记录可访问）
```

**影响文件**：
- `app/services/user_repository.py` — `_init_schema` 中添加表创建和字段迁移
- 新增 `app/services/permission_repository.py` — 权限表 CRUD

#### B-2：后端服务层 — PermissionRepository（0.5天）

**新增文件** `permission_repository.py`：

```python
class PermissionRepository:
    def get_user_permissions(self, user_id: int) -> list[UserResourcePermission]:
        """获取用户全部资源权限记录。"""

    def set_user_permissions(self, user_id: int, permissions: list[PermissionInput]) -> None:
        """批量设置用户资源权限（事务内删除旧记录 + 插入新记录）。"""

    def delete_permission(self, permission_id: int) -> bool:
        """删除单条权限记录。"""

    def check_resource_access(self, user_id: int, resource_type: str, resource_id: str) -> bool:
        """检查用户是否有权访问指定资源。
        - admin 角色始终返回 True
        - permission_mode=open：无 deny 记录则允许
        - permission_mode=whitelist：有 allow 记录才允许
        """
```

**缓存策略**：检查结果按 `(user_id, resource_type)` 维度做进程内 LRU 缓存，TTL 30s。批量列表接口一次性查询全量权限而非逐条检查。

**影响文件**：
- 新增 `app/services/permission_repository.py`
- `app/services/workflow/service_container.py` — 注册 PermissionRepository

#### B-3：管理 API（0.5天）

**新增端点**：

| 端点 | 方法 | 鉴权 | 功能 |
|------|------|------|------|
| `/auth/users/{id}/permissions` | GET | `require_admin` | 列出用户资源权限 |
| `/auth/users/{id}/permissions` | PUT | `require_admin` | 批量设置权限 |
| `/auth/users/{id}/permissions/{permission_id}` | DELETE | `require_admin` | 删除单条权限 |
| `/auth/users/{id}/permission-mode` | PATCH | `require_admin` | 切换用户权限模式（open/whitelist） |

**影响文件**：
- `app/api/routers/auth_router.py` — 新增权限管理端点
- `Code/frontend/openapi.json` — 重新生成

#### B-4：访问检查中间件（0.5天）

**新增依赖函数** `require_resource_access(resource_type: str, resource_id: str)`：

```python
async def require_resource_access(
    request: Request,
    resource_type: str,
    resource_id: str,
    credential: CredentialContext = Depends(require_session),
) -> None:
    if credential.role == "admin":
        return
    if not await permission_repo.check_resource_access(
        credential.user_id, resource_type, resource_id
    ):
        raise HTTPException(status_code=403, detail="Resource access denied")
```

**接入点**：

| 路由 | 资源类型 | 接入方式 |
|------|---------|---------|
| `GET /layers/{layer_id}` | `layer` | 路由参数中提取 layer_id |
| `GET /workflow-definitions/{def_id}` | `workflow` | 路由参数中提取 def_id |
| `POST /workflow-runs` | `workflow` | 请求体中提取引用的 workflow_definition_id |
| 数据导入/远程浏览 | `data_source` | 请求参数中提取路径 |

**影响文件**：
- `app/api/deps.py` — 新增 `require_resource_access`
- `app/api/routers/layer_router.py` — 增加权限检查
- `app/api/routers/workflow_definition_router.py` — 增加权限检查
- `app/api/routers/workflow_router.py` — `submit_workflow` 增加权限检查
- 其他数据源相关路由

#### B-5：前端适配（额外，归属 Phase D 统一处理）

- 用户管理界面增加「资源权限」标签页
- 支持按资源类型筛选、批量勾选
- 被屏蔽的资源在前端列表中隐藏或标记为「无权限」

---

### Phase C：工作流并发控制 — 按角色区分（约 1 天）

**目标**：将当前全局容量池（business=8, weather_tile=16）改为按用户角色区分，支持管理员为每个用户单独配置并发上限。

#### C-1：数据库层 — 用户并发字段（0.2天）

**字段已在 `users` 表中预留**（`max_concurrent_workflows INTEGER DEFAULT NULL`），检查确认后只需确保 `_init_schema` 中已包含该字段。

**影响文件**：
- `app/services/user_repository.py` — 确认 `_init_schema` 包含 `max_concurrent_workflows` 字段
- 若无则补充迁移

#### C-2：后端提交逻辑（0.5天）

**修改 `submission_service.py` 的 `submit_workflow`**：

1. 在 `save_run_under_capacity` 之前，增加按用户角色和用户独立配置的并发检查
2. 超限时写入 `queued` 状态而非抛出 ValueError（429）

```python
# 角色默认并发上限
_role_concurrency_defaults = {
    "admin": None,       # 无限制（受全局 max_active_runs 约束）
    "standard": 3,       # 默认 3
    "demo": 1,           # 默认 1
}

def _user_concurrency_limit(self, user_id: int, role: str) -> int:
    """获取用户工作流并发上限（用户配置 > 角色默认 > 全局 max_active_runs）。"""
    # 1. 检查用户独立的 max_concurrent_workflows
    # 2. 回退到角色默认值
    # 3. 回退到全局 max_active_runs
```

**影响文件**：
- `app/services/workflow/submission_service.py` — 修改 `submit_workflow`，增加 `_user_concurrency_limit`
- `app/services/workflow_repository.py` — `save_run_under_capacity` 增加按用户计数参数

#### C-3：排队唤醒机制（0.3天）

**新增排队工作流 FIFO 唤醒调度器**：

```python
class QueueDispatchService:
    def dispatch_queued_workflows(self, user_id: int | None = None) -> int:
        """检查是否有排队工作流可以唤醒。
        - user_id 为 None 时检查所有排队工作流
        - user_id 指定时仅检查该用户
        - 按 (queued_at, run_id) 排序，FIFO 公平性
        - 每唤醒一个即检查容量是否已满
        """
```

**触发点**：
1. 工作流完成时（`lifecycle_service.finalize_workflow_success`）
2. 工作流失败/取消时（`lifecycle_service.finalize_workflow_failure` / `cancel_workflow_run`）
3. 定时 Beat 任务（周期性清理 + 唤醒）

**影响文件**：
- 新增 `app/services/workflow/queue_dispatch_service.py`
- `app/services/workflow/lifecycle_service.py` — 成功/失败/取消时触发唤醒
- `app/services/workflow/service_container.py` — 注册 QueueDispatchService
- `app/tasks/workflow_tasks.py` — 新增 Beat 定时唤醒任务

#### C-4：运行时配置（0.2天）

**新增运行时配置项**：

```
backend.max_concurrent_workflows_standard   # standard 角色默认并发上限（默认 3）
backend.max_concurrent_workflows_demo       # demo 角色默认并发上限（默认 1）
```

管理员可通过配置 API 运行时调整，立即生效。用户级别的 `max_concurrent_workflows` 优先于角色默认值。

**影响文件**：
- `app/services/effective_config.py` — 添加默认值注册
- `app/services/workflow/submission_service.py` — 读取运行时配置

---

### Phase D：前端适配（约 0.5 天）

**目标**：适配角色重命名、资源权限管理、工作流排队状态展示。

#### D-1：角色显示文案更新（已纳入 Phase A-2）

#### D-2：用户管理界面角色下拉框（已纳入 Phase A-2）

#### D-3：工作流排队状态 UI（0.3天）

**现状**：工作流提交超限时返回 429 错误，前端显示错误提示。

**改为**：standard/demo 用户超限时返回 `queued` 状态（非 429），前端：

1. 工作流列表显示 `queued` 状态标签（带排队图标）
2. 显示排队位置提示（如 "排队中（第 2 位）"）
3. 可选：排队超时提醒（如超过 30 分钟仍为 queued 状态）

**影响文件**：
- `Code/frontend/src/components/workflow/WorkflowRunList.vue` — 新增 queued 状态展示
- `Code/frontend/src/services/workflow-api.ts` — 处理 queued 状态响应
- `Code/frontend/src/types/api-contracts.ts` — 确认 queued 状态类型定义

#### D-4：demo 用户上传下载禁用提示（0.2天）

**现状**：demo 用户调用上传/下载接口时返回 403，前端无特殊提示。

**改为**：demo 用户的数据管理界面显示禁用提示横幅，上传/下载按钮置灰并显示 tooltip。

**影响文件**：
- `Code/frontend/src/components/settings/DataSourceSettings.vue` — 根据角色显示提示
- `Code/frontend/src/data-manager/ui/` — 上传/下载按钮根据角色禁用

---

## 五、实施路径

### 推荐执行顺序

```
Phase A → Phase D → Phase C → Phase B
```

**理由**：
1. **Phase A 优先**：修复契约不同步问题，消除前端旧角色残留，是后续所有改动的基础。
2. **Phase D 次之**：前端适配可独立完成，不依赖后端新功能，且体量小、收效快。
3. **Phase C 第三**：工作流并发控制改动范围明确，新增 `queue_dispatch_service` 但影响面集中。
4. **Phase B 最后**：资源访问控制涉及面最广（新增表、服务、API、中间件、前端标签页），需要最长的设计和测试时间。

### 依赖关系

| Phase | 依赖前置 | 阻塞后续 |
|-------|---------|---------|
| Phase A | 无 | Phase D（角色名同步） |
| Phase D | Phase A | 无 |
| Phase C | 无 | 无 |
| Phase B | 无 | 无 |

### 验证清单

#### Phase A 验证

```
# 后端角色枚举一致
grep -n "operator" Code/backend/app/ --include="*.py" | grep -v "gee/core" | grep -v "scripts/"
# 预期：无输出（仅 GEE 比较运算符，不含用户角色）

# 前端角色枚举一致
grep -n "operator\|viewer" Code/frontend/src/ --include="*.vue" --include="*.ts"
# 预期：无输出

# OpenAPI 契约校验
cd Code/frontend && npm run check:openapi

# 前端类型生成
cd Code/frontend && npm run gen:types

# 前端测试
cd Code/frontend && npm run test

# 数据库迁移（dry-run 确认无旧角色）
cd Code/backend && ../../Env/Python312/python.exe scripts/migrate_roles_v2.py --dry-run
# 预期：无需迁移（未找到旧角色记录），退出码 2
```

#### Phase B 验证

```
# 后端测试
Env/Python312/python.exe -m pytest Test/backend/test_auth.py -q
# 新增权限测试
Env/Python312/python.exe -m pytest Test/backend/test_resource_permissions.py -q

# 启动后端后检查权限 API
curl -X GET http://127.0.0.1:8000/auth/users/1/permissions -H "Authorization: Bearer admin-token"
```

#### Phase C 验证

```
# 后端测试
Env/Python312/python.exe -m pytest Test/backend/test_workflow_routes.py -q

# 启动后端后测试并发限制
# 1. 创建 standard 用户
# 2. 提交 4 个工作流（默认上限 3，第 4 个应 queued）
# 3. 等待其中一个完成，确认排队工作流自动唤醒
```

#### Phase D 验证

```
cd Code/frontend && npm run test && npm run lint && npm run build
```

---

## 六、风险与注意事项

### 6.1 角色重命名迁移

- 迁移脚本 `migrate_roles_v2.py` 已包含备份逻辑（`users.db.bak`）
- 迁移完成后执行 `FLUSHDB` 清空 Redis，全部 session/token 失效，所有用户需重新登录
- 迁移窗口需选择无活跃工作流时段
- 迁移脚本退出码：0=成功、1=数据库未找到、2=已迁移过

### 6.2 配置端点权限收紧影响

- 原 operator 可修改的配置项（天气模型、Provider 优先级）已变为 admin-only
- standard 用户前端需隐藏这些设置入口，避免 403 体验问题
- 当前前端 `SettingsPanel.vue` 中已有角色判断逻辑，需确认其使用的角色名已更新

### 6.3 工作流排队公平性

- 排队键设计为 `(queued_at, run_id)` 排序，保证 FIFO 公平性
- 多用户排队时需避免某用户的工作流长期饥饿
- 建议添加「管理员可手动调整排队顺序」的能力（可选，非 Phase C 范围）

### 6.4 资源访问控制性能

- 每次图层/工作流访问需查询权限表，建议：
  - 权限检查结果按 `(user_id, resource_type)` 维度做进程内 LRU 缓存，TTL 30s
  - 批量列表接口一次性查询全量权限而非逐条检查
  - admin 角色跳过全部权限检查

### 6.5 前端契约同步

- `openapi.json` 需在 Phase A 重新生成，角色枚举自动与后端同步
- 运行 `npm run gen:types` 更新前端类型定义
- 运行 `npm run check:openapi` 确认无漂移

### 6.6 测试覆盖

- Phase A：角色枚举更新后检查所有测试用例，确保无 `operator`/`viewer` 残留
- Phase B：新增 `test_resource_permissions.py` 覆盖权限表 CRUD 与访问检查逻辑
- Phase C：新增工作流并发测试，覆盖超限排队、FIFO 唤醒、配置变更
- Phase D：前端测试覆盖排队状态 UI、demo 禁用提示

### 6.7 当前未纳入范围的安全项

- **密钥轮换完整流程**：依赖 P1-a 版本标记，但未实现轮换 API。未来按需演进。
- **并发会话数限制**：实验室场景人少，多设备登录正常，不实现。
- **会话空闲超时**：科研场景长时间运行任务，不实现。
- **密码复杂度/历史检查**：实验室用户少，弱密码风险可控，不实现。
- **账户级限流**：内网部署，IP 限流已足够，不实现。