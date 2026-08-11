# S1/S2/S3 + Nit 实施报告

> 实施人：CodeReviewExpert（火眼眼）｜日期：2026-08-09
> 对应审查报告：`deliverables/code-review-2026-08-09-arch-flow.md`（S1~S3 + N1~N4）

## 验证结果

| 测试套件 | 结果 |
|----------|------|
| 后端 test_auth.py（回归） | **9 passed** |
| 后端 test_error_codes.py（新） | **6 passed** |
| 后端 test_rate_limit_redis.py（新） | **6 passed** |
| 后端 test_rate_limit_client_ip.py + coverage | **8 passed** |
| 前端 auth-router + session-expired | **12 passed**（含 4 个新一致性断言） |
| OpenAPI 漂移检查 | **OK**（无漂移） |
| 前端 gen:types | **成功** |

---

## S1：错误码体系整体落地

**目标**：对齐架构交付包《系统设计》BD-03 错误码表——`C403001`（鉴权/授权失败语义域）+ `C429001`（限流，带 `Retry-After`）。

### 后端
- **新增** `app/api/error_codes.py`：`ErrorCodeSpec` 数据类 + `ApiError(HTTPException)` 异常基类（携带 `error_code` 属性）。HTTP 状态码保持标准语义（401/403/429），与业务码解耦。
- **改造** `app/api/deps.py`：`require_session` / `require_admin` / `require_write_access` 的鉴权失败点全部改用 `ApiError(AUTH_ERROR, status_code=...)`，响应体统一输出 `error_code: "C403001"`。
- **改造** `app/api/routers/auth_router.py`：登录失败、会话过期、跨用户越权、admin-required 等场景统一挂 C403001。
- **改造** `app/main.py` 全局异常处理器：识别 `ApiError.error_code` 并透传到响应体 `{"detail", "error_code", "request_id"}`。
- **设计决策**：503（API key 未配置）与功能开关（GEE 账号管理关闭）**不挂** C403001——前者是运维配置问题（非鉴权失败），后者是功能可用性（非授权拒绝），保持语义域纯净。

### 限流响应（C429001）
- **新增** `rate_limit.py::rate_limited_response()`：统一构造 429 响应 `{"detail", "error_code": "C429001", "request_id"}` + `Retry-After` header。
- **改造** `main.py` 限流中间件：三类限流（login/write/tile）全部走统一响应构造器。

### 前端
- **改造** `http-errors.ts`：`ApiRequestError` 新增 `errorCode` + `retryAfterSec` 字段；新增 `extractErrorCode()`。
- **改造** `_http.ts`：从响应体提取 `error_code`、从响应头提取 `Retry-After`，透传到 `ApiRequestError`。
- **不自动重试写请求**：429 不做自动重试（POST/PUT/DELETE/PATCH 有副作用，重试存在重复提交风险）；workflow-runner 的 429 重试是业务池容量语义，保留不动。

### 测试
- 新增 `test_error_codes.py`（6 用例）：未鉴权写→C403001、viewer 写→C403001、登录失败→C403001、admin-required→C403001、限流→C429001+Retry-After、422 校验错误不挂码。

---

## S2：多进程模式 + 限流 Redis 集中化

### S2a：启用多进程
- **配置** `config.py` 新增 `fastapi_workers`（默认 2，`BACKEND_FASTAPI_WORKERS`）。
- **改造** `start_fastapi.py`：`uvicorn.run(workers=settings.fastapi_workers)` + `multiprocessing.freeze_support()`（Windows spawn 必需）+ reload 与 workers 互斥（多 worker 下强制关 reload）。
- **幂等保护** `auth_bootstrap.py::bootstrap_auth`：多 worker 并发创建 admin 时 `sqlite3.IntegrityError`（唯一约束冲突）不再抛错，重查确认后告警降级（属正常竞争）。
- **幂等保护** `_bootstrap_dev_api_key`：`upsert_key` 已是 `ON CONFLICT` 幂等，多 worker 并发安全。

### S2b：限流 Redis 集中化
- **重写** `rate_limit.py`：
  - `SlidingWindowRateLimiter`（进程内，降级路径，返回 `RateLimitResult{allowed, retry_after_seconds}`）
  - `RedisSlidingWindowRateLimiter`（Redis ZSET 滑动窗口，多进程共享阈值）
  - `RateLimiter`（统一入口：Redis 优先 → 不可用降级进程内 + 告警限频）
- **Redis ZSET 实现**：member=`{时间戳}:{随机后缀}`（唯一），score=时间戳；每次判定 `ZREMRANGEBYSCORE` 清理 + `ZCARD` 计数（pipeline 原子），超阈用 `ZRANGE 0 0` 取最早记录计算 `Retry-After`。
- **降级语义**：Redis 熔断/不可用时回退进程内计数——单进程语义不变，多进程为尽力而为（更宽松而非失效），30s 限频告警避免刷屏。
- **登录限流**：原全环境生效（含 test），现统一为 **production-only**（与写/瓦片限流一致），消除测试环境计数竞争。
- **测试**：新增 `test_rate_limit_redis.py`（6 用例）覆盖 ZSET 放行/超阈+Retry-After/expire TTL/降级路径/滑动窗口过期驱逐。

---

## S3：safeRedirect 白名单动态化

- **新增** `app/route-paths.ts`：路由定义单一真源（`SPA_ROUTES` / `EXTRA_ROUTES` / `SPA_PATHS` 派生）。
- **改造** `router.ts`：从 `route-paths.ts` 导入构建路由表，不再硬编码。
- **改造** `safe-redirect.ts`：白名单 `SPA_PATHS` 由 `route-paths.ts` 动态导入，新增 SPA 路由无需手改 safe-redirect。
- **新增测试** 4 个一致性断言（`auth-router.test.ts`）：
  - 每个 `SPA_ROUTES` 条目都在白名单内
  - `SPA_PATHS` 只含 router 实际注册的路径
  - router 由同一份定义构建（无漂移）
  - login/not-found 排除在白名单外
- **jsdom 环境**：测试文件加 `@vitest-environment jsdom`（router 初始化需要 window）。

---

## Nit 修复

| # | 修复 | 文件 |
|---|------|------|
| N1 | `create_token` 直接返回 `created_at`，消除 auth_router 二次查询（小 N+1） | `user_token_repository.py` + `auth_router.py` |
| N2 | `update_user` 字段名白名单显式检查（`_UPDATABLE_COLUMNS`，非 assert 避免 `-O` 失效） | `user_repository.py` |
| N3 | rate_limit 注释错位修正（`_login_limiter` / `_tile_limiter` 注释归位） | `rate_limit.py`（重写时已修正） |
| N4 | `auth_bootstrap` 空串 `BACKEND_API_KEY=` 显式告警（防静默回退 dev 默认 key） | `auth_bootstrap.py` |

---

## 改动文件清单

**后端（10 文件）**：
- `app/api/error_codes.py`（新）
- `app/api/deps.py`、`app/api/routers/auth_router.py`、`app/main.py`
- `app/api/rate_limit.py`（重写）
- `app/core/config.py`、`start_fastapi.py`
- `app/services/auth_bootstrap.py`、`app/services/user_repository.py`、`app/services/user_token_repository.py`

**前端（5 文件）**：
- `app/route-paths.ts`（新）、`app/router.ts`、`app/safe-redirect.ts`
- `services/http-errors.ts`、`services/_http.ts`

**测试（3 文件）**：
- `Test/backend/test_error_codes.py`（新）、`Test/backend/test_rate_limit_redis.py`（新）
- `Test/frontend/auth-router.test.ts`（增强）

**契约**：`Code/frontend/openapi.json` + `Code/frontend/src/types/api-contracts.ts`（重导出）

---

## 后续观察项

1. **多进程实测**：本地默认 2 worker，首次 `launch.py start fastapi` 后确认日志无 bootstrap 竞争异常；Redis 限流 ZSET key 形如 `cgda:ratelimit:{write|login|tile}:{ip}`。
2. **Redis 降级告警**：Redis 故障时日志会出现 `Rate limiter [xxx] degraded to in-process counting`（30s 限频）。
3. **架构文档对齐**：S1 落地后，G6 交付包中 C403001/C429001 从「目标态」变为「已实施」，可更新文档状态。
