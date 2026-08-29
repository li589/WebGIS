# 代码审查报告 — Agent 子系统与任务属主隔离（2026-08-29）

**审查范围**：`fd3ca8e` / `bd83c90` / `24414ad` 三个提交引入的新代码（Agent 多配置档、编排器、工具运行时、主题仓库、导入任务属主隔离）及工作区未提交改动。
**审查类型**：代码审查（审计阶段只读，未修改任何业务代码）
**编程语言**：Python 3.12（FastAPI 0.116.1）+ TypeScript / Vue 3.5.38
**审查代码量**：后端约 3600 行新增 + 前端约 2457 行新增
**问题总数**：14 个（**致命 1** / 严重 3 / 警告 7 / Karpathy 建议 3）

---

## 一、致命问题（必须修复，功能中断）

### C-1：导入任务属主 ContextVar 跨 FastAPI 依赖边界丢失 → 非管理员用户的异步导入任务完全不可用

**位置**
- 写入侧：`Code/backend/app/api/deps.py:225`（`require_data_transfer_access`，**同步** `def`）→ 第 233-236 行调用 `set_import_job_owner()`
- 兜底读取：`Code/backend/app/data_io/services/jobs.py:21`（ContextVar 定义）、`:41`（`_job_owner_ctx.get()`）
- 7 个入队调用点**均不传** `owner_user_id`：`Code/backend/app/data_io/api/router.py` 的 511 / 521 / 528 / 566 / 823 / 946 / 1001 行

**原代码**
```python
# app/api/deps.py:225  —— 同步依赖
def require_data_transfer_access(request: Request, x_api_key: str | None = Security(_api_key_header)) -> None:
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and can_data_transfer(ctx):
        try:
            from app.data_io.services.jobs import set_import_job_owner
            set_import_job_owner(int(ctx.user_id) if ctx.user_id is not None else None)
        except Exception:
            logger.debug("set_import_job_owner failed", exc_info=True)
        return

# app/data_io/api/router.py:511  —— 异步端点，不传属主
job = enqueue_job("vector", {...}, force_async=True)

# app/data_io/services/jobs.py:41  —— 只能靠 ContextVar 兜底
owner = owner_user_id if owner_user_id is not None else _job_owner_ctx.get()
```

**问题描述**
`set_import_job_owner()` 只是 `_job_owner_ctx.set(uid)`。但 **`require_data_transfer_access` 是同步 `def`**，FastAPI 会在线程池中执行同步依赖（`run_in_threadpool` → anyio 以 `copy_context()` 运行），在副本上下文中 `ContextVar.set()` **不会回传**到事件循环。而所有导入端点都是 `async def`，读到的一律是默认值 `None`。

**复现证据 A —— 机制层（FastAPI 0.116.1 最小三例对照）**

| 依赖 → 端点 | 端点读到的值 |
|---|---|
| sync dep → **async** endpoint（即本仓库真实形状） | `UNSET` ❌ |
| sync dep → sync endpoint | `UNSET` ❌ |
| **async** dep → async endpoint | `SET_IN_ASYNC_DEP` ✅ |

**复现证据 B —— 真实 app 端到端（已于 2026-08-29 全栈验证，见第八节）**

以 `standard` 用户会话登录真实 `create_app()`，走真实 `POST /import/vector`（`async_mode=true`）：

```
[POST /import/vector]                 status=200  job-b655608ff95646d1  (status=running)
[落库 owner_user_id]                  None        <-- 期望 2（stduser）
[GET /import/jobs/{id} as stduser]    status=403  {"detail":"无权访问该导入任务"}
[GET /import/jobs      as stduser]    items=[]    <-- 自己的任务不出现在列表
[对照组 GET /import/jobs/{id} as admin] status=200  <-- 管理员可见，证明任务本身健康
```

**前端消费链路**（`Code/frontend/src/data-manager/core/api.ts:470`）
`fetchImportJob()` 对非 2xx 直接 `throw new Error(parseErrorDetail(403, ...))`，该异常穿透 `waitForImportJob` 的轮询循环。
→ **用户实际观感：提交导入后立刻弹出「无权访问该导入任务」，而非转圈超时**（10 分钟超时逻辑根本走不到）。

**影响链**
1. `create_job` 写入 `owner_user_id: null`
2. `list_jobs`（`jobs.py:105-108`）fail-closed 过滤无主任务 → **用户在任务列表里看不到自己刚提交的任务**
3. `_deny_job_if_not_owner`（`router.py:420`，第 424 行 `if owner is None` 直接 403）→ **状态轮询、取消、下载结果全部 403「无权访问该导入任务」**

即：非管理员提交的异步导入任务会真实执行，但提交者**全程无法查看进度或取回结果**。
**管理员不受影响**（`include_all=True` / admin 直通），这是它在联调和测试中容易漏掉的原因。

**为何测试没兜住**：`Test/` 下 `owner_user_id` 仅出现在 `test_workflow_timer_ownership.py`（工作流域，非导入任务域）；`/import/jobs/{id}` 的测试集中在 `test_exception_narrowing.py`，只覆盖 404/500 路径，未覆盖属主隔离。

**修复建议**（不要依赖 ContextVar，改为显式传参）
```python
# app/api/deps.py —— 改为返回凭据的异步依赖
async def get_data_transfer_cred(
    request: Request,
    x_api_key: str | None = Security(_api_key_header),
) -> CredentialContext:
    ctx = resolve_credential(request, x_api_key)
    if ctx is not None and can_data_transfer(ctx):
        return ctx
    if ctx is not None and ctx.role == "demo":
        raise ApiError(...)
    raise ApiError(AUTH_ERROR, status_code=403, detail="...")

# app/data_io/api/router.py —— 端点显式取属主并下传
async def import_batch(
    body: ImportBatchBody,
    cred: CredentialContext = Depends(get_data_transfer_cred),
) -> dict[str, Any]:
    owner = int(cred.user_id) if cred.user_id is not None else None
    job = enqueue_job("vector", {...}, force_async=True, owner_user_id=owner)
```

**回归测试（修复前必然失败，可作留仓用例）**
以 `standard` 用户身份 `POST /import/batch`，断言返回的 `job_id` 能被**同一用户** `GET /import/jobs/{job_id}` 取到 200（当前返回 403）。

### ✅ C-1 修复记录（2026-08-29 已修复并转绿）

**根因只修一处**：属主不再走隐式上下文，改由端点显式下传。

| 文件 | 改动 |
|---|---|
| `Code/backend/app/api/deps.py:225` | 移除 `require_data_transfer_access` 内无效的 `set_import_job_owner()` 调用与静默 `except Exception`；docstring 记录该陷阱，防止后人改回隐式方案 |
| `Code/backend/app/data_io/services/jobs.py` | 删除 `_job_owner_ctx` ContextVar 与 `set_import_job_owner()`；`create_job` 的 `owner_user_id` 改为**只取显式入参**，docstring 声明契约与 `None` 的 fail-closed 语义 |
| `Code/backend/app/data_io/api/router.py` | 新增 `_owner_user_id(cred)` 助手；5 个端点（`/import/batch`、`/import/vector`、`/import/raster/commit`、`/import/document/{id}/commit`、`/export/batch`）加 `cred` 参数，**7 个 `enqueue_job` 调用点全部传 `owner_user_id`** |

**红灯证据**（修复前）
```
> assert owner is not None, "owner_user_id 未落库 —— ContextVar 兜底失效（C-1 回归）"
E AssertionError: owner_user_id 未落库 —— ContextVar 兜底失效（C-1 回归）
E assert None is not None
```

**绿灯证据**（修复后）
```
Test/backend/test_import_job_ownership.py ...   3 passed in 15.79s
```
留仓回归锁：`Test/backend/test_import_job_ownership.py` —— 覆盖「提交者本人可见」「另一 standard 用户不可见」「admin 可旁路」三条，并显式断言属主落库。

**回归基线**：data_io/jobs 相关 27 个测试文件 + agent/theme，共 **258 passed / 1 skipped**；与剔除新文件后的基线（255 passed / 1 skipped）对比，新增 3 条用例全绿、**无新增失败**。
> 该组合中 `test_agent_chat.py` 有 4 条失败，经对照验证为**既有顺序污染**（单独跑 12 passed），非本次引入，详见第八节。

---

## 二、严重问题（建议修复）

### M-1：`/agent/models/refresh` 无限流，且任意登录用户可驱动服务端用全局配置档凭据外呼

**位置**：`Code/backend/app/api/routers/agent_router.py:363-389`；限流仅覆盖 chat（`app/api/rate_limit.py:301` 的 `_agent_chat_limiter`，挂载见 `app/main.py:265`）

**问题**：该端点只做 `_require_agent_access`（登录即可，**demo 角色同样可调用**），随后按客户端传入的 `profile_id` / `scope` 取配置档原文并触发外呼：
```python
raw = config_service.get_profile_raw(pid, scope=scope, user_id=uid)
result = refresh_models_for_profile(raw)   # 用该档 API Key 发起外网请求
```
**影响**：
- 非管理员可用**全局配置档的 API Key** 发起外网请求（额度消耗 / 请求放大面）；单次最多外呼 2 次（ollama tags + models）
- 404 与 200 的响应差异可枚举全局配置档 id（信息泄漏）
- 无任何限流，可循环调用

**修复建议**：纳入 `should_rate_limit_*` 系列（或复用 agent_chat 限流器）；`scope == "global"` 时要求 `role == "admin"`。

---

### M-2：会话文件无数量上限、无 TTL，客户端可控 session_id → 无界文件增长

**位置**：`Code/backend/app/services/agent/session_store.py:28-34`、`:61-88`

**问题**：`session_id` 由客户端提供（`agent_router.py:46`，已用 `_SAFE_SESSION` 正则收敛到 `[A-Za-z0-9_-]{1,128}`，路径穿越风险已封堵 ✅），但每个 session_id 落一个永久 json 文件，**无 TTL、无数量上限、无清理任务**。
**影响**：循环提交不同 session_id 即可持续创建文件（低成本磁盘/inode 膨胀型 DoS）。单文件约 96 KB 上限（12 轮 × 2 × 4000 字符）。
**修复建议**：写入时更新 mtime；按「每用户会话数上限（如 50）+ 未更新时间 TTL（如 7 天）」清理，可在 Beat 任务或访问时惰性清理。

---

### M-3：编排器宽异常兜底把一切内部错误包装成 502「模型调用失败」

**位置**：`Code/backend/app/services/agent/orchestrator.py:570-574`
```python
except Exception as exc:
    logger.exception("Agent LLM call failed profile=%s", profile_id)
    raise LlmClientError(f"模型调用失败：{exc}") from exc
```
**影响**：
- `execute_server_tool`（含 ACL 查询）、JSON 解析、配置读取等任何异常都被包装成 LLM 故障，返回 502；真实缺陷被掩盖，与正在推进的 Phase 3「异常边界收窄」方向相反
- `str(exc)` 可能携带内部路径/结构进入客户端响应
**修复建议**：只转换已知边界（`LlmClientError` / `OSError` / `TimeoutError` / `json.JSONDecodeError`）；其余记录日志并返回通用 500 文案，不外抛 `str(exc)`。

---

## 三、警告（建议）

| # | 问题 | 位置 | 说明与建议 |
|---|---|---|---|
| W-1 | **`list_jobs` 文档字符串与实现相反** | `jobs.py:86-94` vs `:105-108` | docstring 称「legacy 无主任务**会返回**」，代码实际 `continue` 跳过（fail-closed）。**代码是对的、文档是错的**——照文档"修正"就会变成 fail-open 越权。请改 docstring 并加注释锁定该语义 |
| W-2 | **base_url 的 SSRF 校验可在配置层绕过** | `config_service.py:200-209`、`:480-487` | 先发 `protocol=demo` 写入任意 URL（demo 分支直接 return 不校验），再改回 `openai` 即可绕过配置层校验。执行层 `safe_urlopen` 仍兜底（非 production 允许私网），故未升级为严重；属纵深防御缺失。建议改为「只要最终协议非 demo 就重校验 base_url」 |
| W-3 | **工具 JSON 每请求重复读盘解析** | `orchestrator.py:40-105` | `load_system_prompt` + `_all_tools_*` 每轮 chat 触发 3-5 次 `read_text` + `json.loads`（含 follow-up 的二次调用）。同项目 `presets.py` 已有 mtime 热载缓存，此处不一致。建议照 `presets.py` 模式加缓存 |
| W-4 | **UI intent 的 `catalog_id` 未做可访问性校验** | `Code/frontend/src/components/agent/agent-ui-intent.ts:41-64` | `set_layer_visibility` 在图层未激活时直接 `workspace.addLayer(catalogId)`（`active-layers.ts:119` 无权限校验）。后端 ACL 仍守住实际数据，故非数据泄漏；但与 W-5 的注入面叠加时应收敛。建议在应用前比对可访问图层集合 |
| W-5 | **`client_context`（客户端任意 JSON）直注 system prompt** | `orchestrator.py:108-137` | 可诱导模型输出非预期内容。已缓解项：前端无 `v-html`（已全仓 grep 确认）、intent 名称白名单、intent 参数已收敛。建议限制体积与键白名单 |
| W-6 | **错误码语义污染** | `agent_router.py:180-185`、`:378-382`、`:409-419` | 422 / 404 / 502 一律复用 `AUTH_ERROR` 码。监控按 code 聚合会误判为鉴权故障。建议按语义拆分为独立错误码 |
| W-7 | **SVG logo 存储型 XSS 残余面** | `theme_repository.py:36`、`:450-475`；`auth_router.py:802`、`:824` | 白名单含 `.svg`，下载端点**公开免鉴权**且以 `image/svg+xml` 直出。**已由三重因素缓解**：`X-Content-Type-Options: nosniff`（内容嗅探不可行）+ 生产 CSP `script-src 'self'`（阻断内联脚本）+ 前端以 `<img src>` 引用（img 上下文不执行脚本）。**残余风险集中在开发/测试环境（无 CSP）**。建议：logo 路由单独下发 `Content-Security-Policy: sandbox` 或 `Content-Disposition: attachment`，或对 SVG 做消毒 |

---

## 四、Karpathy 维度建议

- **K-1 死代码**：`orchestrator.py:193` 的 `_server_calls` 把 `run_workflow` 计入服务端调用，但工具清单（`server_tools_runtime.py:10` `_ALLOWED_TOOLS`）里根本没有它 → `execute_server_tool:21-25` 的 `run_workflow` 分支**不可达**。建议删除该分支与 `_server_calls` 中的特判。
- **K-2 死赋值**：`config_service.py:650` `raw = get_effective_profile_raw(...)` 之后从未使用（ruff F841 已报）。
- **K-3 常量语义不自洽**：`session_store.py` 中 `_MAX_TURNS = 12`，`append_turn` 按 `-(_MAX_TURNS*2)` 存 12 轮，但 `load_history` 按 `[-_MAX_TURNS:]` 只取 6 轮 → 存 12 用 6，且 `orchestrator.py:322` 的 `len(history)//2` 展示轮数也随之偏差。建议统一为「N 轮 = 2N 条」。

---

## 五、验证证据

| 证据类型 | 命令 | 结果 |
|---|---|---|
| 静态检查 | `Env/Python312/python.exe -m ruff check Code/backend/app/services/agent/ Code/backend/app/api/routers/agent_router.py Code/backend/app/services/theme_repository.py Code/backend/app/data_io/services/jobs.py` | **4 errors**：`config_service.py:650` F841、`orchestrator.py:294` F841、`session_store.py:10` F401、`theme_repository.py:11` F401 |
| 后端测试 | `REDIS_URL=... ENVIRONMENT=test python -m pytest Test/backend/test_agent_chat.py Test/backend/test_themes.py -q` | **17 passed**（93s） |
| 前端测试 | `npm run test -- --run`（agent-ui-intent / agent-api / useAgentCompanionPosition / theme） | **24 passed / 4 files** |
| M-1 端到端（真实 app） | standard 用户 `POST /agent/models/refresh {"profile_id":"demo","scope":"global"}` | **200** `{"models":["demo-rules"]}` → 非管理员可驱动全局档；伪 id → **404**（枚举预言确认）；连续 40 次调用状态码集合 `[200]`，**无 429**（无限流确认） |
| C-1 端到端（真实 app） | standard 用户 → `POST /import/vector` → `GET /import/jobs/{id}` / `GET /import/jobs`，admin 作对照 | **缺陷复现**：落库 `owner_user_id=None`、本人 403、本人列表为空、管理员 200 且可见 |
| 根因复现（机制层） | FastAPI 0.116.1 最小三例对照 | sync 依赖两种情形均 `UNSET`，仅 async 依赖可读到 → **证实 C-1 根因** |
| 门禁核查 | `.pre-commit-config.yaml:15-22` | ruff 钩子 `files` 正则**覆盖** `Code/backend/app/services/agent/` 且带 `--exit-non-zero-on-fix` → 4 处报错说明该提交**未经过 pre-commit 门禁** |

> 说明：pytest 首次运行因 `.pytest_tmp` 清理触发 `PermissionError [WinError 5]`（已知的沙箱删除保护问题，非本次审查代码缺陷）；换用全新 `--basetemp` 后正常通过。

---

## 八、全栈验证记录（2026-08-29 补记）

审查结论最初基于源码阅读与最小复现。经用户要求做全栈验证后，在**真实 `create_app()` 实例**上以 `standard` 用户会话复跑了两条主链路（临时验证脚本已运行并清理，未入库）。

### 验证方法
复用 `Test/backend/test_agent_chat.py` 的鉴权夹具模式（`BACKEND_USER_AUTH_ENABLED=true` + 真实 `UserRepository` + `bootstrap_auth()` + 真实 `standard` 用户会话），对真实端点发请求。仅桩掉 `resolve_upload_path` 以跳过文件上传管道，其余全为真实代码路径。

### C-1 结果：缺陷确认

| 观测点 | 结果 | 判定 |
|---|---|---|
| `POST /import/vector`（standard，`async_mode=true`） | `200`，返回 `job-b655608ff95646d1`，`status=running` | 任务已真实创建并执行 |
| 落库 `owner_user_id` | **`None`**（期望 `2`，即 stduser） | ❌ 属主丢失 |
| `GET /import/jobs/{id}`（提交者本人） | **`403`** `{"detail":"无权访问该导入任务"}` | ❌ 无法轮询 |
| `GET /import/jobs`（提交者本人） | **`items=[]`** | ❌ 列表中不可见 |
| 对照组：同一 job，admin | **`200`**，且出现在 admin 列表 | ✅ 任务本身健康，仅非管理员被阻断 |

**结论**：C-1 从「推断」升级为**实测确认的致命缺陷**——非管理员提交的异步导入任务会真实执行，但提交者全程无法查看进度或取回结果。

**附加观测**：admin 列表同时出现了上一次验证运行遗留的 `job-3dc966cc2d0b47b0`，说明**无主任务记录会跨运行持续累积**，且只有管理员能看到——这与 M-2（无 TTL/无清理）叠加后会持续膨胀。

### M-1 结果：缺陷确认

| 观测点 | 结果 | 判定 |
|---|---|---|
| standard 用户刷新**全局**档 `demo` | `200` `{"models":["demo-rules"],"manual":false}` | ❌ 非管理员可驱动全局配置档 |
| 刷新不存在的 id | `404` | ❌ 存在枚举预言（可探测全局档 id） |
| 连续 40 次调用 | 状态码集合 `[200]`，**无 429** | ❌ 该路径无限流 |

### 前端链路结论

`fetchImportJob()`（`data-manager/core/api.ts:470`）对非 2xx 立即 `throw`，异常穿透 `waitForImportJob` 的轮询循环。
→ **用户观感是「提交后立刻报『无权访问该导入任务』」**，不是转圈等待；其 10 分钟超时分支在此场景下不可达。

### 验证后的问题状态

| 编号 | 验证前 | 验证后 |
|---|---|---|
| C-1 | 源码推断 + 机制层复现 | **端到端确认**（含 admin 对照组）→ **已修复并转绿** |
| M-1 | 代码路径推断 | **端到端确认**（可驱动 + 可枚举 + 无 429） |
| M-2 | 代码路径推断 | 间接佐证（跨运行遗留无主任务累积） |
| 其余 | 静态审查 | 静态审查（未逐条端到端） |

### 附带发现：既有测试顺序污染（非本次引入，建议单独立项）

跑回归基线时发现，将 `test_agent_chat.py` 与 data_io 相关测试文件放在同一进程内运行时，有 4 条 agent 用例失败：

```
FAILED test_agent_chat.py::test_agent_chat_open_layer_with_api_key
FAILED test_agent_chat.py::test_agent_chat_list_layers_from_context
FAILED test_agent_chat.py::test_agent_chat_opacity_intent
FAILED test_agent_chat.py::test_agent_chat_session_memory
```

**已排除本次改动的责任**：
* 单独运行 `test_agent_chat.py` → **12 passed**
* 同组合但剔除本次新增的 `test_import_job_ownership.py` → **仍然 4 failed**（255 passed / 1 skipped）

→ 属既有的跨文件状态污染（agent 夹具会改写全局 `settings` / 用户库 / API key，与 `deployment.config.json` 强制覆写 `BACKEND_DATA_ROOT` 的机制叠加后会互相干扰）。C-1 修复未加重该问题，但它会让 CI 全量跑持续报红，建议单独立项排查。

### 附带发现：openapi.json 存在上一提交遗留的 1 行漂移

`24414ad` 为 `GET /auth/themes` 增加了 docstring「List all product themes (admin session required).」但未重新导出 schema，导致 `Code/frontend/openapi.json` 缺这一行 `description`。
`check:openapi` 只校验关键路径指纹，**当前不报红**；本次改动对 OpenAPI 零影响（已导出新 schema 全文比对确认）。建议顺手重导一次以保持产物与代码一致。

---

## 六、审查总结

- **整体评分**：**72 / 100**
- **主要风险**：新增的导入任务属主隔离**在运行时完全失效**（C-1），非管理员的异步导入功能事实上不可用；Agent 子系统的外呼端点存在限流与权限边界缺口（M-1）。
- **优先修复 Top 3**：**C-1**（功能中断）→ **M-1**（限流/越权外呼）→ **W-1**（文档与实现相反，随时可能被"修"成越权）。

**正向评价（这些做对了，值得保持）**
1. **属主隔离的失败方向正确**：`list_jobs` fail-closed、`_deny_job_if_not_owner` 对 `owner is None` 直接拒绝——安全语义设计是对的，坏在传参机制。
2. **ACL 过滤失败时 fail-closed**：`server_tools_runtime.py:100-102` 异常时返回空集而非全量。
3. **LLM 外呼已走 SSRF 防护**：`openai_compat` 全量使用 `safe_urlopen` + 60s 超时，未裸用 urllib。
4. **session_id 与用户键均已正则收敛**，路径穿越风险已封堵；`resolve_logo_path` 有 `relative_to` 穿越防护。
5. **原子写入**：配置与会话文件统一 `tmp + replace`。
6. **工具调用有明确白名单**：`_ALLOWED_INTENTS` / `_ALLOWED_TOOLS`，且主动禁用 `run_workflow`。
7. **chat 端点已限流**（30/分钟/IP）并与写接口限流键分离。
8. **presets 的 mtime 热载缓存**实现干净，可作为 W-3 的修复样板。

**已知限制与未验证项**
1. ~~C-1 未做端到端验证~~ → **已于 2026-08-29 全栈验证闭环**（真实 app + standard 会话 + 真实端点，详见第八节），该项不再是不确定项。验证时仅桩掉了 `resolve_upload_path`（上传管道非本次审查对象），依赖、端点、`create_job`、`list_jobs`、`_deny_job_if_not_owner` 均为真实代码。
2. M-1 的**外呼放大未做定量压测**：已确认「非管理员可驱动 + 无 429 + 存在 404 枚举预言」三项事实，但用真实外网配置档压测额度消耗的影响未量化，标注为「可复现、影响未量化」。
3. W-7 的 SVG 风险在生产环境被 CSP 阻断，**未对目标部署（Nginx Gateway :5175）实际响应头做抓包验证**；若网关剥离了 CSP 头，该项应升级为严重。
4. 未审查 `AgentCompanion.vue`（680 行）与 `AgentSettings.vue`（729 行）的完整交互逻辑，仅覆盖后端契约与其消费方 `agent-ui-intent.ts`。
5. 工作区 5 个未提交改动经核对**均为 CSS/文案微调**，无逻辑风险，可安全提交。
