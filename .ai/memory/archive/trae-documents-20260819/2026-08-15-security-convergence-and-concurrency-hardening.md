# 安全收敛 + 并发专项审查修复计划（2026-08-15）

> 触发：`/plan ①（安全收敛）需要做；研究并行资源抢占、冲突、缓存覆盖等问题和相关bug。Use plugin: brooks-lint`
> 用户决策（已确认）：并发专项采用**审查 + 修复 P0/P1**模式；N-2 采用**彻底迁移下线** legacy 路由。
> 方法论：W-B 审查阶段使用 brooks-lint 插件（`brooks-audit` 架构依赖面 + `brooks-debt` 债务分级）；修复阶段 praxis TDD 惯例（红→绿）。
> 上游输入：`Docs/06-代码审查/问题清单-2026-08-15.md`（N-1/N-2 留痕项）。

---

## 0. 目标

1. **W-A 安全收敛**：N-1 五处内联 AESGCM 收敛到单一加密模块（零数据迁移、零行为变化）；N-2 彻底下线 legacy `/api/remote/*` 路由，前端迁移到 `/config/remote-storage/*` 体系。
2. **W-B 并发专项**：以 brooks-lint 方法论审查 8 个并发面（并行资源抢占/冲突/缓存覆盖），产出分级问题清单；确认的 P0/P1 以 TDD 修复。

---

## 1. 现状分析（Phase 1 探索事实，已核实）

### 1.1 N-1 加密现状（5 处内联 AESGCM）

| # | 文件 | 函数 | 密文格式 | dev 回退 | 异常语义 |
|---|------|------|---------|---------|---------|
| ① | `app/services/api_keys_repository.py` L102-167 | `_encrypt/_decrypt` | 裸 b64 + 独立 `key_iv` 列 | 明文+空 IV | 三分支（无key/ImportError/generic），解密失败 re-raise |
| ② | `app/services/gee_credentials_repository.py` L83-157 | 同上 | **`v1:` 前缀**（唯一带版本） | 明文+空 IV | 与①同构 |
| ③ | `app/services/portal_credentials.py` L28-74 | `_encrypt_blob/_decrypt_blob`（模块级） | KV JSON blob | **b64(明文)+`iv="plain"` 标记** | 无 ImportError 分支；无 key 且 iv≠plain 时 dev 也抛；解密失败由调用方 catch 跳过 |
| ④ | `app/services/remote_storage_credentials_repository.py` L144-190 | `_encrypt/_decrypt` | 裸 b64，双密文字段+history | 明文+空 IV | **generic 裸抛**、解密**无 try/except** |
| ⑤ | `app/services/weather_providers_repository.py` L96-172 | `_encrypt/_decrypt` | 裸 b64 | 明文+空 IV（多一条 warning） | 与①②同构 |

- **无共享模块**：`app/core/` 无任何 cipher/crypto 文件；唯一共享物是策略函数（`effective_config.py` L59-111：`secrets_encryption_required`/`validate_encryption_key_format`/`refuse_empty_iv_outside_development`/`assert_dev_bypass_policy`/`assert_encryption_policy`）。
- 同一把 key（`settings.gee_credentials_encryption_key`），5 个独立 SQLite 库，**无交叉读取**——收敛不需要数据迁移。
- 测试锚点：`Test/backend/test_credential_roundtrip.py`（7 个，断言换 key 抛异常、prod 空 IV 拒绝、portal `iv!="plain"`、`iv="plain"` prod 拒绝）；`Test/backend/test_secrets_encryption.py`（5 个，key 格式与策略）。**密文格式断言不可破坏**。

### 1.2 N-2 权限模型现状

- legacy：`app/api/routers/remote_browser_router.py`，`APIRouter(prefix="/api/remote", dependencies=[Depends(require_write_access)])`（L86-90），3 端点：
  - `GET /servers`（L218）——**无前端调用方**（仅 `types/api-contracts.ts` L3641 声明）
  - `GET /list`（L241）——前端 `RemoteDirBrowser.vue` L62 调用；profile 分支内部已委托 `browser.browse_profile`（L151-173，仅响应改形丢 profile_id/protocol/via）
  - `GET /test`（L313）——前端 `SshSyncForm.vue` L226 调用；profile 分支委托 `config_service.test_remote_storage_profile`
  - legacy 硬编码 `_LEGACY_SERVERS=("hpc","win11","nas")`（L98）+ `_resolve_server`（L101-142）读 settings 直连
- 新体系：`app/api/config_routes.py` `POST /config/remote-storage/{id}/browse|search`（`require_config_read_access`，admin+standard）与 `POST .../test`（`require_config_management_access`，**仅 admin**）；前端 `settings-api.ts` L641-677 已有 `browseRemoteStorage/searchRemoteStorage/failoverRemoteStorage`；`ProfileBrowserDialog.vue` 已用 profile 体系。
- 两套路径校验重复（router `_validate_remote_path` L39-81 vs `browser.normalize_remote_path`，规则等价）。
- 行为变化须知：下线后 standard 用户失去工作流表单内 test 远程连接能力（config test 是 admin-only）——**权限收紧方向，可接受**；前端对 403 需提示。
- 测试：`Test/backend/test_remote_browser_router.py`（5 个，fixture override 鉴权）随路由删除；nginx `/api` 白名单（F8 新增）保留无害。

### 1.3 W-B 并发面现状（8 面事实 + 已观察风险）

| 面 | 事实 | 已观察风险点 |
|----|------|-------------|
| SQLite | `_sqlite_pool.py`：WAL+busy_timeout 30s，max 8，池满 `get()` **无限阻塞**（L99-125）；timer store 独立长连接共库（`workflow_timer_service.py` L387-399） | 跨进程（FastAPI+7 worker）无写串行化；池获取无超时 |
| Celery | solo 池（Windows）；`acks_late` 仅 `process_workflow_run`（7200/7500s）；`visibility_timeout>time_limit` 防双跑；running 重投仅记 warning 不阻止重执行（`submission_service.py` L361-377 自认产物覆盖风险） | 重投副本与原 worker 并写输出目录 |
| Redis | 熔断器 3 连败 30s→120s；`acquire_dedup_lock` Redis 不可用**放行**（L163/171）；API 槽位 `INCR`+`EXPIRE` **非原子**（L329-331）；降级后槽位语义=每进程独立 | 降级期互斥/限流失效；槽位计数泄漏 |
| 天气缓存 | coverage：进程 dict + Redis TTL 300s；瓦片：**双 Semaphore 各 6**（async 与 sync 独立计数，极端 12 并发）+ 进程 LRU 256 + Redis 键含 provider；`@lru_cache` 单例→每 worker 各一套 | 双闸不共享；同步后瓦片缓存不失效（仅 coverage） |
| 文件缓存 | `client.py` L570-587：固定名 `.tmp` + `replace`；dedup 锁失效时两进程写同一 tmp；`launch.py flush` 删缓存目录与在写进程竞态 | Windows 句柄争用（与 basetemp WinError 5 同构） |
| 同步互斥 | 锁键=`sync:{domains}`（domains **字符串原样**）；TTL 7200s；三入口均过 acquire 真闸；CLI domains 读 `data-sync/.env`、后端读 backend `.env` **两份来源**；降级=进程内锁 | domains 组合不同键不同锁但写同一 volume；两份 .env 漂移即互斥失效 |
| 前端缓存 | tile manager 世代机制对"旧结果写回新 state"安全；TTL 固定 1h 未接后端热调；merge cache 键含 generation+coverageSig | localStorage workspace 多标签页 last-writer-wins |
| 定时器 | 乐观 claim `BEGIN IMMEDIATE`+`next_fire_at` 哨兵（L625-662）+ 僵尸回收（L586-623）——cron 路径防护到位 | `mark_fired` 无条件 UPDATE（L680-699）；event 类型无 claim，并发 emit 可重复提交 |

retry 链：`retry_dispatcher.py` L58-103 用 **非 CAS** `save_run_status` 回写 meta，且 L70-76 注入 `reuse_output_dir` 复用原输出目录。

---

## 2. 变更方案

### W-A1：AESGCM 收敛（新建共享模块，零行为变化）

**新建** `Code/backend/app/services/secret_cipher.py`：

```python
# 核心原语（唯一 AESGCM 实现点）
def aesgcm_encrypt(key_hex: str, plaintext: str) -> tuple[str, str]: ...   # -> (ct_b64, iv_b64)
def aesgcm_decrypt(key_hex: str, ciphertext_b64: str, iv_b64: str) -> str: ...
# 统一三分支语义（吸收①②⑤成型逻辑）：
def encrypt_secret(plaintext, *, key, require_encryption: bool) -> tuple[str, str]: ...
def decrypt_secret(ciphertext, iv, *, key, require_encryption: bool) -> str: ...
```

- **各 repo 保留薄壳**：前缀处理（② `v1:`）、存储列映射、③ 的 `iv="plain"` 标记语义**原样保留**——密文格式、dev 回退格式、测试断言全部不变，只把 AESGCM 原语与三分支策略收敛到共享模块。
- ④（generic 裸抛、解密无 try）与③（ImportError 裸抛）切换到统一三分支语义——**唯一行为变化**：④⑤③ 的异常路径更严整（dev 回退明文、非 dev RuntimeError）。修复前先跑现有测试确认无锚定裸抛行为的断言。
- 单测：`Test/backend/test_secret_cipher.py` 新增（原语往返、错误 key、空 IV、三分支矩阵）。
- 切换顺序：⑤ → ① → ④ → ② → ③（风险从低到高），每切换一个跑其对应测试组。

**验收**：`test_credential_roundtrip.py`(7) + `test_secrets_encryption.py`(5) + 新增单测 + 5 个 repo 功能测试组全绿；rg 确认 `from cryptography` 仅出现在 `secret_cipher.py` 一处。

### W-A2：legacy remote browser 彻底下线

**后端**：
1. 删 `app/api/routers/remote_browser_router.py`；移除 `main.py` L23/L368 与 `routers/__init__.py` L24/L39 注册。
2. 重新生成 `Code/frontend/openapi.json`（后端契约脚本）→ `check:openapi` 通过。
3. 删 `Test/backend/test_remote_browser_router.py`（5 个测试随路由消亡）。

**前端**：
1. `RemoteDirBrowser.vue`：`GET /api/remote/list?server=&path=` → 复用 `settings-api.ts` 的 `browseRemoteStorage(profileId, path)`；服务器下拉数据源改为 remote-storage profiles 列表（`RemoteDataSourcesPanel` 同源）。
2. `SshSyncForm.vue` L226：`GET /api/remote/test?server=` → `POST /config/remote-storage/{id}/test`（admin-only；standard 收 403 时显示"仅管理员可测试连接"提示，不阻塞表单提交）。
3. 删 `types/api-contracts.ts` 中 `/api/remote/servers` 声明（L3641）及关联类型。
4. 前端相关测试更新（执行时以 `rg "api/remote" Test/frontend Code/frontend/src` 全量定位调用面）。

**验收**：`npm run test && npm run lint && npm run build` 全绿；`check:openapi` 零漂移（重生成后）；`rg "/api/remote"` 在前后端源码零命中（nginx 白名单条目保留无害，留痕注释）。

### W-B：并发专项审查 + 修复（brooks-lint）

**B1 审查**（先 `brooks-audit` 摸模块依赖面，再 `brooks-debt` 定级）：对 §1.3 的 8 面 + retry 链逐项定级。判据：
- **P0**：可造成生产数据损坏/凭据泄露（如产物目录并发写坏科研数据）。
- **P1**：并发正确性缺陷可复现（互斥失效、缓存脏读、计数泄漏）且修复代价可控。
- **P2/P3**：架构级约束（SQLite 跨进程、solo 池）、降级语义文档化——留痕不修。

**B1 定级结论（2026-08-15 执行完成，8 面全读源）**：

| 面 | 定级 | 结论 |
|----|------|------|
| Redis API 槽位 | **P1（B-R1）** | INCR 后崩溃 → EXPIRE 未执行 → 计数器无 TTL 永久滞留，槽位慢性泄漏直至池耗尽（Open-Meteo 池 6），仅 `launch.py flush` 可救 |
| 天气文件缓存 | **P1（B-R2）** | 固定 `.tmp` 名：Redis 降级时 dedup 锁放行 → 多线程/进程写同一 tmp；实测 Windows 并发 `os.replace` 同目标也报 PermissionError(13)，交错写产生损坏缓存 |
| 同步互斥 | **P1（B-R3）** | 锁键 `sync:{domains}` 原样拼接：`a,b` 与 `b,a` 不同锁 → 同一域集合两次 sync 并发跑同一 Docker volume（缓存覆盖根源之一） |
| retry 链 | P2（B-N2） | 并发双 retry 复用同一 `reuse_output_dir` → 产物缓存块并发写；需目录代次或 CAS 设计，超出最小变更边界 |
| 同步状态注册 | P2（B-N1） | `_LOCAL_SYNC_JOBS` 无锁遍历 + 插入 → 罕见 `RuntimeError: dict changed size`（本地降级路径） |
| 定时器 | P3 | cron/interval 乐观 claim 到位；event 类型无 claim 属语义选择（并发 emit → 多 run 可辩护） |
| SQLite 池 | P3 | WAL+busy_timeout+Queue 设计合格；`_pool.get()` 无界阻塞留痕 |
| 提交容量 | P3 | `save_run_under_capacity` 原子预留已闭环 TOCTOU；同工具排他取消存在小窗口 |

**B2 修复结果（逐项 TDD 红→绿，`Test/backend/test_concurrency_hardening.py` 10/10）**：

| 项 | 修复 | 验证 |
|----|------|------|
| B-R1 | `redis_client.py` 新增 `_ACQUIRE_SLOT_LUA`：单次 eval 完成 INCR + TTL 补挂（`TTL==-1` 时也补挂，自愈孤儿键） | 原子性 + 限额 + 孤儿补挂 3 测试 |
| B-R2 | `client.py` 新增 `unique_cache_tmp_path`（pid+tid+uuid8）与 `replace_with_retry`（PermissionError 指数退避 ×5），两处缓存写点接入 | 唯一性 + 8 线程并发 replace 无异常且终态合法 JSON、无 tmp 残留 |
| B-R3 | `open_meteo_sync_tasks.py::_sync_lock_key` 对 domains 排序+去重+去空白 | 参数化 4 组等价类 + 空/None 回退 default |

范围外发现（随 D 落盘）：`test_weatherengine_service.py` 单文件运行需 `PYTHONPATH=Code/algorithms/providers/Python`（COG 导入链 `publish.__init__ → output_manager → path_utils` 依赖运行时路径注入），全量套件下因其它测试污染 sys.path 而通过——测试隔离缺口，定级 P2 留痕（B-N7）。

---

## 3. 执行顺序与任务分解

1. **A1** 加密收敛（独立先行，风险最低）
2. **A2** legacy 下线（后端删 → 前端迁 → 契约同步）
3. **B1** brooks-lint 并发审查（技能方法论，8 面定级）
4. **B2** 修复确认 P0/P1（逐项红→绿）
5. **R** 全量回归：后端 pytest（basetemp 用 `%TEMP%\cgda-*`，串行）+ 算法 + 前端 vitest 串行（10 文件超时则单独批次补验）+ lint/build/check:openapi/check:catalog
6. **D** 增补落盘：更新 `Docs/06-代码审查/问题清单-2026-08-15.md`（N-1/N-2 置闭环、新增 B 系列条目）+ HTML 报告同步

## 4. 假设与决策

- W-A1 各库密文格式**不迁移**（无交叉读取，格式保留即零风险）；唯一 AESGCM 实现点收敛到 `secret_cipher.py`。
- N-2 下线后 standard 失去表单内 test 能力 = 权限收紧，接受；前端做 403 提示。
- `/api/remote/*` 删除属公开契约变化：openapi.json 重生成 + api-contracts.ts 同步，属计划内动作。
- W-B 分级以审查结论为准，§2 预判清单仅为候选；P2/P3 一律留痕不修（同上次模式）。
- 测试执行遵守仓库硬约定：`Env/Python312`、禁 WorkBuddy shim 前缀、basetemp 指向 `%TEMP%`（避开 `Test/.pytest-be` 锁定）。

## 5. 验证步骤（最终门）

```
后端：CODEBUDDY_SESSION_ID= CLAUDE_SESSION_ID= CODEBUDDY_SAFE_DELETE_SANDBOX= ENVIRONMENT=test
      Env/Python312/python.exe -m pytest Test/backend -p no:cacheprovider --basetemp="$env:TEMP\cgda-be-s1" -q
算法：Env/Python312/python.exe -m pytest Test/algorithms -q --basetemp="$env:TEMP\cgda-alg-s1"
前端：cd Code/frontend && npm run test -- --no-file-parallelism（超时文件单独批次）
      npm run lint && npm run build && npm run check:openapi && npm run check:catalog
```
全部 ≥ 今日基线（后端 1193 passed / 0F / 0E；算法 411；前端全绿）且新契约一致。
