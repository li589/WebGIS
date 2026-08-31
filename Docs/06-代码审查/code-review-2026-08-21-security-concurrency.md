# 后端安全与并发审查（2026-08-21）

- 范围：`Code/backend/app`（273 个非测试 Python 文件；`gee/core` 子树已抽查关键模块）
- 方式：只读静态审查。按「安全泄漏 / SSRF / 路径穿越 / 命令注入 / 弱加密 / 吞异常」与「模块级可变全局 / 锁使用 / asyncio 混用 / Celery 共享状态 / 原子写 / SQLite 并发」两个专项逐模式 grep + 逐点读上下文验证。
- 结论统计：**P0 × 2（同根因，涉及 4 个入口），P1 × 4，P2 × 8**。

---

## P0（需立即修复）

### [S-1] upload_id / layer_id 无分隔符校验 → 任意目录递归删除（Windows 部署下可利用）

- 文件：
  - `Code/backend/app/data_io/services/upload.py:244-247`（`discard_upload`）
  - `Code/backend/app/api/routers/import_router.py:307-323`（`delete_imported_raster`）
  - 入口：`Code/backend/app/data_io/api/router.py` 的 `/import/upload/{upload_id}/discard` 类端点与 `DELETE /import/raster/{layer_id}`
- 证据（凭据值用 *** 替代，此处无凭据，仅路径）：

  ```python
  # upload.py:244
  def discard_upload(upload_id: str) -> None:
      dest = STAGING_DIR / upload_id          # upload_id 未做任何格式校验
      if dest.exists():
          shutil.rmtree(dest, ignore_errors=True)   # 只要目录存在就递归删除

  # import_router.py:310
  async def delete_imported_raster(layer_id: str) -> dict[str, Any]:
      if not layer_id.startswith("imported-"):       # 仅前缀检查
          raise HTTPException(status_code=400, ...)
      spec = unregister_overlay(layer_id)
      dest_dir = _IMPORTS_DIR / layer_id             # 未拒绝 ..、\、/
      ...
      shutil.rmtree(dest_dir, ignore_errors=True)
  ```

- 触发路径：
  - URL 路径参数（`{upload_id}`、`{layer_id}`）：`/` 无法注入（Starlette `[^/]+`），但 `%5C`（`\`）解码后可进入参数——Windows 下 `\` 是 `pathlib`/`os` 的路径分隔符，`imported-..\..\..\目标` 即可穿越出 `imports/` 根。
  - POST body（如 `UploadCompleteBody.upload_id`、`RasterInspectBody.upload_id`）无任何编码障碍，`\` 与 `..` 可直接提交。
- 影响：具备 `require_data_transfer_access` 权限的调用方可让后端**递归删除服务器上任意已存在目录**（`ignore_errors=True` 失败也静默）。本项目开发与部署环境为 Windows（`win32`），可利用性高。Linux 部署下 URL 参数不可注入 `/`、`\` 非分隔符，仅 body 传入不构成穿越——但不应依赖该平台差异。
- 对照证据（作者已知此风险，但只修了一处）：`Code/backend/app/data_io/api/router.py:701-716` 的 `delete_imported_layer` 做了完整校验：

  ```python
  safe = Path(layer_id).name
  if safe != layer_id or ".." in layer_id or "/" in layer_id or "\\" in layer_id:
      raise HTTPException(status_code=400, detail="非法 layer_id")
  ```

- 修复建议：
  1. 在 `upload.py` / `import_router.py` 复刻 `delete_imported_layer` 的校验（`Path(x).name == x` 且不含 `..` / `/` / `\`），或更进一步对 `upload_id` 加白名单 `^up-[a-f0-9]{16}$`、`layer_id` 加 `^imported-[a-z0-9-]+$`。
  2. 深层防御：在 `STAGING_DIR / upload_id`、`IMPORTS_DIR / layer_id` 拼接后统一 `resolve()` + `is_relative_to(root)` 判界（参考 `source_fetcher.py:468-483` 的写法）。

### [S-2] 同根因的「越界写」入口：rename / CRS confirm / 断点续传可向 imports 根外写文件

- 文件：
  - `Code/backend/app/data_io/services/paths.py:144-191`（`update_imported_layer_display_name`，入口 `PATCH /import/layers/{layer_id}/display-name`）
  - `Code/backend/app/data_io/services/raster_register.py:253-333`（`confirm_imported_raster_crs`，入口 `POST /import/raster/confirm`，layer_id 来自 JSON body）
  - `Code/backend/app/data_io/services/upload.py:59-76`（`init_upload(resume_upload_id=...)`，来自 JSON body）
- 证据：

  ```python
  # paths.py:149-155 —— 仅前缀检查，未拒绝 .. 与分隔符
  lid = str(layer_id or "").strip()
  if not lid.startswith("imported-"):
      raise ValueError("仅支持导入图层重命名")
  dest = IMPORTS_DIR / lid          # Windows 下 \ 穿越

  # raster_register.py:261-264
  if not layer_id.startswith("imported-"):
      raise ValueError("仅允许确认 imported-* 图层")
  dest_dir = IMPORTS_DIR / layer_id

  # upload.py:59-61 —— resume_upload_id 直接拼接（后续会在该目录创建 meta.lock、写 meta.json）
  resume_dest = STAGING_DIR / resume_upload_id
  ```

- 影响：写原语受固定文件名限制（`meta.json` / `bounds.json` / `preview.png` / `meta.lock` / `blob.part`），但 `confirm_imported_raster_crs` 的 body 参数在 Windows 下无任何编码障碍，可覆盖 imports 根之外任意目录中的同名文件（内容部分用户可控），造成数据损坏；`init_upload(resume_upload_id)` 可在任意目录创建锁文件并续写 `blob.part`。评级 P0 的原因：与 S-1 同根因、同一批攻击面，且满足「外部输入可触发 + 数据损坏」。
- 修复建议：与 S-1 相同——统一在「用户输入 → 路径拼接」的收敛点（建议在 `data_io/services/paths.py` 增加一个 `safe_import_dir(layer_id: str) -> Path` 帮助函数）做白名单 + resolve 判界，全部 8 处 `startswith("imported-")` 调用点（见下方 P2 读穿越条目）一次性收编。

---

## P1（特定条件下功能 bug / 数据损坏 / 资源泄漏）

### [C-1] weather 工作流取消回调从未真正执行，且存在 TypeError 中断提交的路径

- 文件：`Code/backend/app/weatherengine/workflow_manager.py:230-258`，配合 `Code/backend/app/services/weather_bridge_service.py:136-154`
- 证据：

  ```python
  # workflow_manager.py:242-249
  if workflow.cancel_callback:
      try:
          loop = asyncio.get_event_loop()          # 线程上下文（Celery worker / threadpool）无 loop → RuntimeError
          if loop.is_running():
              asyncio.create_task(workflow.cancel_callback())   # 回调是同步函数 → 返回 None → TypeError
          else:
              loop.run_until_complete(workflow.cancel_callback())
      except Exception as e:
          if isinstance(e, (AttributeError, NameError, TypeError, ImportError, SyntaxError)):
              raise                                # TypeError 属于编程 bug，会向上抛出
          logger.warning(f"... Cancel callback failed: {e}")   # RuntimeError 被静默吞掉
  ```

  `weather_bridge_service.py:136` 传入的 `cancel_callback` 是**同步**函数（仅打日志），而 `ManagedWorkflow.cancel_callback` 的类型标注是 `Callable[[], Awaitable[None]]`。
- 影响：
  1. 实际调用路径（Celery worker / FastAPI 同步线程池）中 `get_event_loop()` 抛 `RuntimeError` → 被吞成 warning → 取消回调静默跳过，「新工作流自动替换取消旧工作流」的核心语义失效（旧任务实际仍在跑，仅状态被改写）。
  2. 若该代码在事件循环线程内被同步调用（如未来从 async 路由直接调用），`create_task(None)` 抛 `TypeError` → 按设计向上传播 → **中断 submit_workflow**，新工作流提交失败。
- 修复建议：回调契约二选一：要么把 `cancel_callback` 改为同步 `Callable[[], None]` 并直接调用（当前唯一调用方就是同步的）；要么由 bridge 提供真正的 `async def` 回调，并在同步上下文用 `asyncio.run`（仅限无 running loop 时）或派发到事件循环线程执行。同时把「无事件循环」显式记 warning 而非依赖 `get_event_loop()` 的隐式异常。

### [C-2] meta.json / bounds.json 非原子写（`_save_meta` 修复模式的遗漏同类）

- 文件（均已核实为直接 `write_text`，无 tmp + `os.replace`）：
  - `Code/backend/app/data_io/services/raster_register.py:181-186`（`register_geotiff_as_imported` 写 bounds.json/meta.json）
  - `Code/backend/app/data_io/services/raster_register.py:322-333`（`confirm_imported_raster_crs` 写 preview.png/bounds.json）
  - `Code/backend/app/data_io/services/raster_timeseries.py:335-399`（时序 upsert 写 bounds.json/meta.json）
  - `Code/backend/app/data_io/services/vector.py:330`（矢量导入写 meta.json）
  - `Code/backend/app/data_io/services/paths.py:170, 187`（显示名更新写 meta.json/bounds.json）
- 对照（已正确实现的同类）：`data_io/services/_meta_io.py:40-49`（tmp + `os.replace` + 跨进程文件锁）、`weatherengine/client.py:63-80, 605-620`（`unique_cache_tmp_path` + `replace_with_retry`）、`services/feedback_store.py:78`。
- 影响：导入提交、CRS 确认、时序追加、显示名修改均发生在 Celery worker / 线程池，与 API 进程的读端（`overlay_registry._try_load_imported_overlay:646-662`、`zonal_stats_service._find_imported_raster_path:392-402`）并发。读到半写 JSON → `JSONDecodeError` → 图层被当作「不存在」（lazy-load 返回 None）或 500；`raster_timeseries` 并发 upsert 同一图层时相互覆盖丢字段（`time_list` 丢失 → 时序图层退化为 static）。
- 修复建议：将上述 5 处统一改为 `_meta_io.save_meta` 风格（同目录 tmp + `os.replace`）；对「读-改-写」的 meta（timeseries upsert、display_name 更新）再套 `_io_meta_lock`。

### [S-3] `confirm_imported_raster_crs` 读越界文件（S-2 的读侧放大）

- 文件：`Code/backend/app/data_io/services/raster_register.py:279-281`
- 证据：`src_path = dest_dir / source_filename`，其中 `source_filename` 来自越界目录中 `bounds.json` 的 `meta.source_filename`（攻击者若先经 S-2 写入了构造的 bounds.json，可指定 `../../任意.tif`——`source_filename` 本身也未做 `Path(...).name` 归一）。
- 影响：与 S-2 组合可将任意本地 TIF 重投影后写到越界目录（preview.png）；单独看是受限的任意文件读取（需经 rasterio 解析）。
- 修复建议：随 S-2 一并修复；`source_filename` 取值处加 `Path(str(name)).name`（`zonal_stats_service.py:398` 已是正确写法，可对齐）。

### [C-3] SQLiteConnectionPool `close_all` 与借出连接归还之间存在 put 阻塞竞态

- 文件：`Code/backend/app/services/_sqlite_pool.py:127-152`
- 证据：

  ```python
  def _release(self, conn):
      self._pool.put(conn)          # Queue(maxsize=8)；池满时无限阻塞

  def close_all(self, *, quiet=False):
      while not self._pool.empty(): ...   # 只关池内空闲连接
      with self._lock:
          self._created = 0               # 借出中的连接未计入
  ```

- 影响：`close_all`（测试清理 / `__del__`）执行时若有连接仍被借出，`_created` 归零后新请求会再创建至 8 个连接；被借出的旧连接归还时 `put` 可能使队列超过 maxsize → **归还线程永久阻塞**（FastAPI 线程池线程泄漏）。触发条件苛刻（关闭与并发使用交叠，主要在测试与热重载场景），故列 P1 而非 P0。
- 修复建议：`_release` 改为 `self._pool.put(conn, timeout=...)` 或 `put_nowait` + 异常时关闭连接；`close_all` 记录借出数或置「关闭中」标志拒绝后续 `_acquire`。

---

## P2（记录不修 / 低危）

1. **读侧路径穿越（S-2 根因的读面）**：`services/overlay_registry.py:634-641`、`services/zonal_stats_service.py:381-388` 同样以 `startswith("imported-")` 后直接拼接读 `bounds.json`/`meta.json`。读原语受限（需目标目录有特定文件结构），信息泄漏面小；随 S-2 的统一收敛点一并修复即可。
2. **WorkflowLifecycleManager 双锁不等价**：`weatherengine/workflow_manager.py:69-76`——同步路径用 `threading.RLock`、异步路径用 `asyncio.Lock`，两把锁保护同一份 `_active_workflows`，互不互斥。当前所有实际调用方（`weather_bridge_service.py`）只走同步版，风险为潜在；若未来混用会破坏「每图层唯一工作流」不变量。建议异步版内部改走 `self._lock`（run_in_executor）或干脆移除 async 版本。
3. **`_get_local_slot_lock` 双重检查锁定缺失**：`core/redis_client.py:299-305` 无锁 check-then-create，两线程可各自创建 Lock 互不互斥。仅 Redis 不可用的降级路径触发，后果是本地限流短暂超限。建议模块导入时直接实例化。
4. **Redis 熔断计数器无锁读改写**：`core/redis_client.py:45-70` 的 `_consecutive_failures += 1` 等多线程竞态，最多导致熔断阈值统计偏差，语义自愈。
5. **权限缓存跨 worker 不失效**：`services/permission_repository.py:62-91` 的 `_access_cache` 仅进程内失效，多 worker 下权限撤销最长 30s（TTL）内在其他 worker 仍生效。属已知缓存权衡，建议文档化或迁 Redis。
6. **`_token_cache` 无锁复合操作**：`services/remote_access/filebrowser_client.py:87-95` 并发时可能重复 login（token 均有效，无害）。
7. **`_LOCAL_SYNC_JOBS` 无锁复合清理**：`services/weather_sync_service.py:49-65` 多个降级线程并发时 stale 清理可能交错，最坏多留/少清几条，Redis 层有 TTL 兜底。
8. **`COVERAGE_CACHE` 等模块级 dict 无锁读写**：`services/weather_coverage_cache.py:19`、`api/routers/weather_router.py:65-69`、`services/workflow/runtime_status_service.py:45`、`services/python_provider_bridge_service.py:96-116`——CPython GIL 保证单操作原子，最坏读到旧值或重复计算，均自愈。无需修复，记录以防未来引入多步 check-then-act。

---

## 审查覆盖说明

### 已跑的 grep 模式（path 限定 `Code/backend/app`）

| 维度 | pattern | hit 情况 |
|---|---|---|
| 凭据入日志 | `logger.*(password\|secret\|token\|api_key\|credential)` | 3 处，均只记 key 名/异常摘要，无明文值 |
| f-string 敏感值 | `f["']...\{*(password\|secret\|token...)\}` | `portal_catalog.py:740-744` 等均为构造 Authorization 头（内存中），未入日志/响应 |
| SSRF | `urlopen(\|requests.(get\|post...)(`、`httpx.(AsyncClient\|Client)(` | 直连 `urlopen` 共 3 处，均有 `is_trusted_open_meteo_local_url`（固定常量 URL）守卫；其余 13 处全部走 `safe_urlopen` |
| 路径穿越 | `os.path.join\|Path\(` + `resolve()\|startswith` 组合、`shutil.rmtree\|unlink(` | 命中 S-1/S-2/P2-1；其余删除入口（cleanup_router、data_io router 的 delete_imported_layer、export）判界正确 |
| 命令注入 | `shell=True\|os.system\|subprocess.*` | 8 处 subprocess 全部 list 参数无 shell；`docker compose run` 的 domains 经 `is_supported_weather_model` 白名单（weather_sync_service.py:130-139） |
| 弱加密 | `verify=False` | 0 处 |
| 吞异常 | `except Exception:/s*/n/s*pass` | 10 处，逐一读上下文：均有注释理由（best-effort 降级 / 队列空 / 覆盖由其他检查兜底），无掩盖安全错误者 |
| 模块级可变全局 | `^_[A-Z_]+ *= *(\{\|\[\|set\(|dict\()`、`_cache.*=\s*\{` 等 | 40+ 处，逐个分类：常量表（排除）/ TTL 缓存（P2-8）/ 需锁复合操作（P1/P2 上述） |
| 锁使用 | `threading.(Lock\|RLock\|Semaphore\|Event)(` | 30 处，全部 `with` 用法（异常安全）；`tile_service` semaphore 获取后有 finally 释放（501-527） |
| asyncio 混用 | `asyncio.run\|run_in_executor\|run_until_complete\|get_event_loop` | 4 处，命中 C-1；`tile_service.py:449-462` 的 `run_in_executor` 用法正确 |
| 原子写 | `os.replace\|replace_with_retry`、`write_text(json.dumps` | 命中 C-2 的 5 处遗漏；已正确实现的 6 处作为对照 |
| SQLite 并发 | `_sqlite_pool.py` 全文精读 | WAL + busy_timeout + Queue 独占，命中 C-3 的关闭竞态 |

### 排除的误报（避免重复排查）

1. `config_api_keys.test_api_key` 把 key 拼进 tianditu/baidu 探测 URL——目标是官方固定域名、key 即该服务自身的 key，消息与日志均不含 key 值；出站前有 `validate_outbound_url(allow_private=False)`。
2. `auth_router` 的 `dev_prefill` / `dev_write_api_key` 返回默认管理员口令——有三重守卫（development 环境 + `dev_auth_prefill` 开关 + loopback IP），设计如此。
3. `session_service` 把会话 token 明文作为 Redis key / SQLite 行——标准服务端 session 模式，token 为 `secrets.token_urlsafe(32)` 随机值，非用户口令。
4. API Key / GEE 凭据 / 远程存储凭据的存储链路（`secret_cipher.py` AES-GCM-256 随机 IV + 生产 fail-closed；`api_keys_repository.py` 全链路 `_mask_value` 脱敏，API 响应仅返回 `masked_value`）——实现规范，无泄漏。
5. Open-Meteo 同步的三入口互斥（`open_meteo_sync_tasks.py:34-133`）：按单域 all-or-nothing 加锁 + Redis Lua compare-and-delete + TTL 兜底 + 进程内降级锁——实现完善。
6. `passwords.py` PBKDF2-SHA256 200k 迭代 + `secrets.compare_digest` 恒时比较——规范。
7. `rate_limit.py`：登录 10/min、写接口 120/min、瓦片 240/min、反馈上传 5/min，Redis ZSET 集中计数 + 内存降级，默认不信任 `X-Forwarded-For`——规范。
8. CORS：强制显式 origins（空值直接启动失败），无 `*` + credentials 组合。
9. `paths.py` 的配额回收（`reclaim_import_space`）只删临时区、永不删 `imported-*` 永久层；`cleanup_router` 的 node-cache 清理有「必须 products 直接子目录」白名单。
10. `service_restart.py` 的 `subprocess.Popen`：组件名有 `_ALLOWED` 白名单，路径为仓库内固定 `launch.py`，无用户可控参数。
11. 已知背景（任务说明中给出的）：frozen Settings 动态读、lru_cache 跨测试污染、多 worker 限流/会话走 Redis、development loopback 旁路、`.env` 中 API key 存在本身——均按设计排除。

### 值得肯定的高质量实现（供后续审计基线）

- `core/ssrf.py`：IP 钉死防 DNS 重绑定、重定向逐跳校验、跨主机跳转剥离 Authorization/Cookie、代理 fail-closed——超出常见工程水准。
- `source_fetcher.py:464-500`：本地文件源的 root 约束 + `resolve()` 判界 + production fail-closed。
- `data_io/api/router.py:701-716`：`delete_imported_layer` 的 layer_id 校验是本报告 S-1/S-2 的正确范本。
