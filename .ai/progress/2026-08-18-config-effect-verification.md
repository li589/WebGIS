# 后端框架级配置「写入→生效」验证矩阵（2026-08-18）

> 对应计划：`.trae/documents/2026-08-18-未闭合项收口与后端配置真实性验证计划.md` 阶段 2。
> 方法：三路 Explore 全量枚举 + 关键定性逐条人工抽查复核（每条落到文件:行）。
> 三态定义：**accepted**（API 200）/ **persisted**（落盘 .env / SQLite / json）/ **applied**（服务行为实际变化）。
> 「假设置」判定：accepted+persisted 但永不 applied = **惰性键**；前端可编辑但 PATCH 必 400 = **越权键**。

## 0. 结论速览

| 类别 | 数量 | 说明 |
|---|---|---|
| runtime PATCH 白名单 15 键 | 真实热生效 **5** / 惰性 **10** | 惰性含 P-A `log_level`；白名单注释自称「仅允许已接线字段」与事实不符（runtime_status_service.py:61） |
| 前端可编辑但必 400（P-B） | **4** | hydrate 支持 DB 覆盖（effective_config.py:279-314）但白名单+校验器均缺 |
| deployment 受管键 | **25**（非计划所称 24）全部有真实消费方 | 均重启生效；docker 组 4 键仅 compose 消费（设计如此） |
| SQLite 热载域（api-keys/GEE/天气/remote-storage/门户/数据集） | 全部真实生效 | 唯一例外：gaode/bing key 无瓦片消费（P-D 预留）；worker 进程侧 provider/model 冻结（P-C） |
| 退役端点恒 410 / 内置 provider 删除回退 / GET general 只读 | 设计行为 | 记录即可（P-E/P-F） |

---

## 1. R1：runtime PATCH 19 键矩阵（核心发现）

**链路**：FE `GeneralSettings.vue:303-331`（saveParam，19 键全 PATCH `scope='backend'`，`:322` 成功提示「已更新（N 项生效）」）→ `PATCH /runtime/config`（`api/routers/runtime_router.py:24-38`）→ `apply_runtime_config`（`services/workflow/runtime_status_service.py:391-409`：白名单校验 `:426-430` 拒绝→`ValueError`→400；写 SQLite `workflow_state.sqlite3` 表 `runtime_config` `:396`；写后 hydrate `:398-400`）→ 快照 `effective_config.py:hydrate_effective_config()`（overrides → RuntimeSnapshot，`:215-316`）。

| # | 键 | 白名单:行 | 真实消费方（文件:行） | 三态 | 结论 |
|---|---|---|---|---|---|
| 1 | task_executor | :66 | `get_task_executor()`←`workflow/transition_builder.py:96,138`（executor 派发决策） | A/P/AP | ✅ 热生效 |
| 2 | max_active_runs | :67 | `submission_service.py:592`→`persistence_service.py:201-216`（每次 submit 直读 DB） | A/P/AP | ✅ 热生效 |
| 3 | max_active_weather_tile_runs | :68 | `submission_service.py:597` 同上 | A/P/AP | ✅ 热生效 |
| 4 | max_requested_outputs | :69 | `submission_service.py:630,636` 同上 | A/P/AP | ✅ 热生效 |
| 5 | weather_cache_ttl_seconds | :70 | `get_weather_cache_ttl_seconds()`←`weatherengine/tile_service.py:530,767`、`fetch_gateway.py:186,256`、`api/weather_tile_routes.py:106` | A/P/AP | ✅ 热生效 |
| 6 | weather_refresh_forecast_hours | :71 | 消费方全读冻结 settings：`fetch_gateway.py:184`、`weather_value_utils.py:231`、`weatherengine/service.py:619`、`nodes/forecast_fetch.py:51`；快照字段零消费 | A/P/✗ | ⚠️ **惰性**（保存提示生效，实际永不变） |
| 7 | log_level（P-A） | :72 | **全仓零消费**；唯一 setLevel 在 `core/logging.py:46` 启动时读 `settings.log_level` 一次 | A/P/✗ | ⚠️ **惰性**；FE 描述「立即生效」（GeneralSettings.vue:234）为虚假承诺 |
| 8 | cache_default_ttl_seconds | :73 | getter `effective_config.py:428` 零调用；实际 `download_orchestrator.py:237-238`、`download_progress_tracker.py:649` 读 settings | A/P/✗ | ⚠️ **惰性** |
| 9 | provider_max_hotspots | :74 | getter `:432` 零调用；`provider_result_builder.py:59` 读 settings | A/P/✗ | ⚠️ **惰性** |
| 10 | provider_max_series_points | :75 | getter `:436` 零调用；`provider_result_builder.py:60`、`workflow/provider_workflow_service.py:132,356` 读 settings | A/P/✗ | ⚠️ **惰性** |
| 11 | provider_table_chunk_size | :76 | `provider_result_builder.py:214,223` 读 settings | A/P/✗ | ⚠️ **惰性** |
| 12 | provider_series_chunk_size | :77 | `provider_result_builder.py:262,271`、`python_provider_result_builder.py:442` 读 settings | A/P/✗ | ⚠️ **惰性** |
| 13 | result_inline_max_bytes | :78 | `workflow/provider_workflow_service.py:134`、`result_storage.py:145` 读 settings | A/P/✗ | ⚠️ **惰性** |
| 14 | celery_task_soft_time_limit | :79 | getter `:440` 零调用；`core/celery_app.py:59` worker 启动固化读 settings；**DB 覆盖不回写 .env，重启也不生效** | A/P/✗ | ⚠️ **惰性**（连重启都无效） |
| 15 | celery_task_time_limit | :80 | 同上 `celery_app.py:60` | A/P/✗ | ⚠️ **惰性**（同上） |
| 16 | workflow_node_parallelism（P-B） | ✗ 不在 | 消费方已就绪：`python_provider_bridge_service.py:329,338`→`get_workflow_node_parallelism()` 注入算法 env `CGDA_WORKFLOW_NODE_PARALLELISM` | A/✗ | ❌ **PATCH 必 400**（白名单 `:65-81` 拒绝；validators `:87-105` 亦缺） |
| 17 | algorithm_max_parallel_workers（P-B） | ✗ 不在 | 已就绪：`python_provider_bridge_service.py:328,332`→`CGDA_MAX_PARALLEL_WORKERS` | A/✗ | ❌ **PATCH 必 400** |
| 18 | task_memory_budget_mb（P-B） | ✗ 不在 | **全仓零消费**（backend+algorithms 均 `rg` 证实；getter `:462` 零调用） | A/✗ | ❌ **PATCH 必 400**；且即使扩白名单仍无消费方 |
| 19 | task_cpu_budget_cores（P-B） | ✗ 不在 | 同上（getter `:467` 零调用） | A/✗ | ❌ 同上 |

> hydrate 对 16-19 四键的 DB 覆盖支持在 `effective_config.py:279-314`（max(1,…) / max(0,…) 兜底）——「写入机制就绪、入口被白名单挡住」是 P-B 的准确画像。

## 2. R2：config_routes 写端点矩阵（按域）

### 2.1 API Keys（admin；`api_keys.sqlite3` 表 api_keys + history，AES-GCM `api_keys_repository.py:101-108`）
| 端点 | 行 | 持久化 | 消费方 | 生效 | 结论 |
|---|---|---|---|---|---|
| PUT/DELETE /config/api-keys/{key}、/toggle、history restore/清删、POST test | :178/:202/:226/:251/:264/:278/:215 | SQLite（test 无持久化） | `backend_auth`→`effective_config.py:353-371`←`api/deps.py:111-113`（写鉴权）；**瓦片仅 tianditu(:455 tk)/baidu(:458 ak)** `tile_proxy_service.py:425-458`；gaode/bing 无注入（:447-449） | 写后 hydrate（`config_api_keys.py:186-188/235-237/277-279`）即时 | ✅ 真实；gaode/bing=**预留**（`api_config.py:390-397 _HOT_PATH_WIRED`、`config_api_keys.py:54-61` 自认）→ P-D 标注 |
### 2.2 GEE 账户（admin+管理开关；`gee_credentials.sqlite3`）
| POST/DELETE/toggle/reload/test | :301/:343/:370/:386/:359 | SQLite | 变更后 `_reload_gee_facade`（`config_gee_accounts.py:116-125`）→ `gee_bridge_service.py:25-58` 清 lru_cache 重建账号池 | 即时 | ✅ 真实 |
### 2.3 天气（admin；`weather_engine.sqlite3` / `weather_providers.sqlite3`）
| PUT /config/weather/model | :426 | SQLite 键 default_model | `_effective_model_cache`（`weather_engine_settings.py:27`）写时失效（:36-38,72）→ `get_effective_weather_default_model` :41-55 | FastAPI 进程即时；**worker 侧缓存跨进程无法失效** | ✅（FastAPI）/ ⚠️ worker 冻结（P-C） |
| PUT providers/{id}、/toggle、/priority | :468/:511/:533 | SQLite | `registry.set_enabled/set_priority`、`provider.apply_config`（`config_weather_providers.py:280-286`）进程内即时 | 同上 | ✅（FastAPI）/ ⚠️ worker 冻结（P-C） |
| DELETE providers/{id} | :557 | 删 DB 行 | 内置项回退代码默认（`config_weather_providers.py:355`） | — | ✅ 设计行为（P-E） |
| POST providers/{id}/test | :500 | 无 | 连通测试 | — | ✅ |
> P-C 证据：`apply_persisted_provider_overrides`（`config_weather_providers.py:379-481`）调用方仅 `main.py:113-115`（lifespan）与同文件 :120（惰性注册）；`core/celery_app.py:127-141` worker_ready 仅 `register_default_providers()`，无 DB 覆盖应用、无 hydrate、全仓无 worker_process_init → worker 的 provider 启停/优先级/model 与 API 进程脱钩，需 worker 重启。
### 2.4 远程存储凭证（admin；`remote_storage_credentials.sqlite3`）
| PUT/DELETE/toggle/failover/history*、POST test/browse/search | :601/:631/:643/:725/:749/:761/:775/:657/:673/:698 | SQLite（test/browse/search 无持久化） | `remote_auth_resolver.py:52,122`←`source_fetcher.py:576-580`、`workflow_request_resolver.py:1196-1198` | 每次解析直读 DB | ✅ 真实热载 |
### 2.5 数据源 / 门户 / 数据集（admin；`research_data_settings.sqlite3`）
| PUT /config/data-source/paths | :798 | **写 backend .env**（`config_service.py:390-445`→`env_file_upsert.py:46`；DATA_ROOT/OUTPUT_ROOT/STATIC_CACHE_ROOT/CACHE_DIR/DOWNLOAD_SOURCE_ROOT 五键） | 见 R3 对应行 | **须 restart backend** | ✅（FE 入口已收敛 `/deployment`，PathConfigSection 只读） |
| PUT /config/deployment + POST preview | :843/:831 | **deployment.config.json 原子写**（`deployment_config.py:675,590`）+ `.bak.1-3` 轮换（:549-561）+ backend/.env 镜像（:686-690）+ data-sync/.env 双写（:691-692）；任一步失败整体回滚（:694-700） | 见 R3 | **须 restart**（docker 组 restart-full） | ✅ 25 键全链健康 |
| POST /config/service/restart | :885 | 无配置持久化；子进程调度 `launch.py restart backend`（`service_restart.py:61-101`） | — | 运维动作 | ✅ |
| PUT open-data-presets / portal-credentials / portals / remote-layer-uris / datasets CRUD / remote-sources CRUD / rescan | :928/:951/:968/:991/:1008/:1026/:1068/:1096/:1106/:1119/:1148/:1165 | SQLite KV/表 | 门户凭据逐次解密直读 DB（`portal_credentials.py:159-193`←`config_service.py:652-659`←算法 `data_access_nodes.py` lazy 解析）；数据集/远程源逐查询直读 | 即时 | ✅ 热载 |
| POST data-cache/evict、cache/invalidate-templates | :914/:1191 | 无（删缓存文件 / 清内存 lru_cache） | — | 运维动作 | ✅ |

## 3. R3：deployment 受管 25 键（`deployment_config.py:_SPECS L69-281`，五组 data3/runtime7/caches6/imports2/docker7）

全部 **accepted+persisted+applied(重启)**，无「仅存储回显」键。逐键消费方（节选关键，全表见勘察底稿）：

| 组 | 键 → 消费点（文件:行） | 生效 |
|---|---|---|
| data | BACKEND_DATA_ROOT→`dataset_registry_service.py:396,485`、`workflow_request_resolver.py:1154-1243`、`analysis_run_service.py:62,224`；OUTPUT_ROOT→`data_io/services/paths.py:38-42`、`object_store.py:305`；PROJECTBACKUP_ROOT→算法 `dataset_config.py:97`（env 直读） | restart-backend |
| runtime | RUNTIME_ROOT→`config.py:32-45`（模块级派生，早于 Settings）；WORKFLOW_STATE_DIR→`workflow_repository.py:84` 等 4 库；LOG_DIR/LOG_LEVEL→`core/logging.py:41,46,52`；RESULT_ARTIFACT_DIR→`object_store.py:305`；PYTHON_PROVIDER_WORKSPACE→`python_provider_bridge_service.py:220,448`；SPATIALITE_DB_PATH→`spatial_repository.py:40,262` | restart-backend |
| caches | CACHE_DIR→`cache_service.py:49`、`weatherengine/client.py:240` 等 5 处；STATIC_CACHE_ROOT→`data_cache_service.py:15`+算法 `data_access_nodes.py:22`（双端 env）；STATIC_CACHE_TTL→`data_cache_service.py:29`+算法 `cache_store.py:19`；DOWNLOAD_SOURCE_ROOT→`source_fetcher.py:466`；CACHE_DEFAULT_TTL→`download_orchestrator.py:237` 等（重启路径；进程内另有 runtime PATCH 通道，见 R1#8）；TILE_PROXY_CACHE_TTL→`tile_proxy_service.py:255` | restart-backend |
| imports | MAX_IMPORTS_TOTAL/SOFT_RESERVE→`data_io/services/paths.py:61-69`（模块导入期 env） | restart-backend |
| docker | MINIO_ROOT_USER/PASSWORD→仅 `docker-compose.yml:54-80`；OPEN_METEO_HOST_PORT→compose :101；OPEN_METEO_DATA_VOLUME→两份 compose（backend :111 / data-sync :56），backend 进程仅当文本转述（`open_meteo_sync_tasks.py:176-192`、`launch/subprocess_utils.py:78-94`）；SYNC_DOMAINS/VARIABLES→`weather_sync_service.py` 多处+compose 实参；OPEN_METEO_LOCAL_URL→`provider_registry.py:279`、`ssrf.py:80`、`redis_client.py:262` | **restart-full**（设计如此） |

**非受管键抽查**（仅 .env/Settings，不经配置中心）：CORS→`main.py:169-179`；worker 并发/池→`celery_app.py:54,68-69`；写/登录/瓦片限流→`rate_limit.py:167-198`+`main.py:226-272`（env 直读）；demo/stubs 开关→`source_fetcher.py:650`、`workflow_definition_router.py:51`。均真实消费。⚠️ 唯一异常：`login_rate_limit_per_minute` Settings 字段（config.py:684）定义后无人读（实际消费 `rate_limit.py:185-189` 直读 env）——仅冗余定义，无功能影响，记录不改。

## 4. R4：其他路由持久化写端点（B 组）

| 端点 | 行 | 持久化 | 消费 | 结论 |
|---|---|---|---|---|
| PUT/DELETE /workspace | `workspace_router.py:76,111` | users.sqlite3 user_workspaces | 前端图层工作区跨设备同步 | ✅ |
| POST/PUT/DELETE /workflow-definitions(+duplicate) | `workflow_definition_router.py:304-369` | JSON 文件 `{data_root}\workflow_definitions\user\` | 定义列表/编译直读 | ✅（system 拒改删） |
| POST/PUT/DELETE /workflow-timers | `workflow_timer_router.py:91-204` | workflow_state.sqlite3 workflow_timers | Beat tick 直读 | ✅ |
| POST /frontend/commands、/runtime/api-config/{provider} | `runtime_router.py:94-111,152-169` | 无 | — | ✅ 恒 410 设计行为（P-E，docstring 已声明） |
| POST /runtime/tiles/cache/clear | `runtime_router.py:244-249` | 无（清进程内瓦片缓存） | — | ✅ 运维动作 |

**已核查不含配置持久化的路由**：weather（sync trigger 业务触发）、workflow/analysis/zonal/GEE（运行提交）、cleanup（维护）、import/data_io（数据面）、auth（账号数据）、tile 三路由（只读）、gee_config（4 GET）。

## 5. GET /config/general（P-F 核查）

46 字段全部只读回显自 Settings（`config_service.py:129-177`；redis 口令脱敏 :169）——无写路径、无假承诺。✅ 设计如此。

## 6. 假设置最终清单与处置建议

| 级别 | 项 | 处置建议 |
|---|---|---|
| ❌ 修改即报错（4） | P-B 四键 | 扩白名单+validators（runtime_status_service.py:65-105）；16/17 两键消费方已就绪即真生效；18/19（task_memory/cpu_budget）扩后仍无消费方→按 P-D 模式标注「预留」或 UI 隐藏 |
| ⚠️ 只改文字无功能（10） | R1#6-15（含 P-A log_level） | 7 键（#6,#8-13）消费方读 settings→**改读既有 snapshot getter**（getter 已在 effective_config.py:428-441，机械替换 ~12 处调用点+补 3 个 getter）；#7 log_level 按 P-A 在 hydrate 接 root logger；#14/15 celery 时限在 P-C worker 钩子内 `app.conf.update`（新 worker 世代生效，文档注明） |
| ⚠️ 跨进程不生效 | P-C worker 侧 provider/model 冻结 | worker_process_init 钩子：apply_persisted_provider_overrides + hydrate（计划已批准） |
| ℹ️ 预留（2） | P-D gaode/bing key | UI 徽标+文档标注，不接消费（ADR 既定） |
| ℹ️ 设计行为 | 410 端点/内置 provider 删除回退/GET general 只读/login_rate_limit 冗余字段 | 矩阵记录，不改 |

## 7. 修复落地与回归测试（2026-08-18 阶段 3 + 3.14）

### 7.1 修复清单（全部已实施）

| 项 | 修复内容 | 文件 |
|---|---|---|
| P-B 越权键 ×4 | 白名单 + int validators 扩容（workflow_node_parallelism 1-16 / algorithm_max_parallel_workers 0-64 / task_memory_budget_mb 0-65536 / task_cpu_budget_cores 0-64） | `runtime_status_service.py:65-115` |
| P-A log_level | hydrate 时 `_apply_runtime_log_level` 应用到根 logger；test/testing 环境跳过；非法值仅告警 | `effective_config.py:319,489-501` |
| 惰性键 ×7 消费方接通（#6,#8-13） | 12 处调用点改读 snapshot getter + 补 3 个 getter（get_weather_refresh_forecast_hours / get_cache_default_ttl_seconds / get_provider_table_chunk_size 等） | `fetch_gateway.py:187`、`weather_value_utils.py:233`、`weatherengine/service.py:623`、`nodes/forecast_fetch.py:53`、`download_orchestrator.py:237`、`download_progress_tracker.py:650`、`provider_result_builder.py:65-66,220,269`、`provider_workflow_service.py:138-139,362`、`result_storage.py:146`、`python_provider_result_builder.py:442` |
| P-C worker 钩子 | `worker_ready` + `worker_process_init` 双信号 → `_bootstrap_worker_runtime`（provider 覆盖 + hydrate + celery 时限 conf.update；失败仅告警不阻断） | `celery_app.py:128-184` |
| P-D 预留标注 | gaode/bing key「预留」徽标；task_memory/cpu_budget 描述改「值仅保存展示，暂未接入调度准入」 | `ApiKeySettings.vue`、`GeneralSettings.vue` |

#16/#17（parallelism 键）扩白名单后即真热生效（消费方 python_provider_bridge_service 已就绪）；#18/#19（budget 键）扩白名单后为诚实「预留」态（UI 已标注，不再假承诺）。

### 7.2 回归测试（Test/backend/test_runtime_config_effect.py，新增 12 项全过）

- **P-B**：4 键 PATCH accepted+persisted；hydrate→getter 投影闭环；越界/幽灵键/bool 仍拒（400 路径）。
- **P-A**：test 环境 no-op；dev 环境 setLevel 生效（WARNING/ERROR）；非法值忽略；hydrate 链路闭环。
- **P-C**：双信号注册断言；prefork 钩子真实应用 celery 时限到 conf（111/222 实测）；依赖故障仅告警不抛。
- 邻域回归：test_config_contracts + test_concurrency_config + test_celery_tasks + test_interaction_hub（57 过）；weather 域 27 过；download/result_storage 域 27 过。

## 8. 定向实机冒烟证据（2026-08-18 10:15-10:30，development + loopback）

> 环境：FastAPI :8000 + Gateway :5175（development）；服务密钥角色 `operator`（.env `BACKEND_API_KEY_ROLE=operator`）。
> 冒烟前 `launch.py restart backend`（10:17:08-46）完成，加载阶段 3 新代码；该重启同时实战验证了 236c357 世代清扫（单世代、无残留告警）。

| # | 项 | 结果 | 证据 |
|---|---|---|---|
| S1a | PATCH log_level=DEBUG + cache_default_ttl_seconds=180 | ✅ | `200 accepted=true applied=2`；GET 回显 `log_level=DEBUG, cache_ttl=180`；恢复 INFO/1800 ✓ |
| S1b | P-B 四键 PATCH（重启前 400 旧白名单 → 重启后） | ✅ | 重启前：`400 Unsupported runtime config key: backend.workflow_node_parallelism`（证明运行态确为旧代码）；重启后：`200 applied=4`，回显 4/2/4096/2 |
| S1c | P-A root logger 级别热切换（按 logger 分组，排除 uvicorn.access 独立 handler） | ✅ | log_level=ERROR 期间 6 请求 `app.*` INFO 行 **0 新增**（仅 hydrate 的 ERROR secrets 告警 +1）；切 DEBUG 后 `INFO:app.main` 恢复 **+7**；已恢复 INFO |
| S3 | api-key toggle 热载 | ✅（RBAC 证据） | `PUT /config/api-keys/gaode/toggle` → **403**（operator 非.admin）→ 权限闸门真实生效；toggle 行为由单测 `test_config_contracts.py::test_api_key_toggle_flips_status`（HTTP 200 路径）覆盖；gaode 原态 enabled=false 未被改动 |
| S4 | P-C worker 钩子真实运行 | ✅（7/7 worker） | 10:17:35-36 全部 7 个 worker 日志出现 `Weather providers registered in Celery worker` + **`Effective config hydrated: keys=['backend_auth'] executor=celery weather_ttl=3600`**（后者为 P-C 新增行为，旧代码 worker 侧无此日志）；providers 只读可见（open-meteo-local/online enabled，openweather/weatherapi disabled） |
| S5 | 数据源页只读 | ✅ | `GET /config/data-source` 200 只读回显（data_root/output_root/static_cache_root）；FE 断言 `data-source-settings.test.ts:198 PathConfigSection（只读）` + `:233 input disabled`；写入入口收敛 `/deployment`（deployment-config-view.test.ts 正向输入断言） |

**遗留（用户决策项）**：S2 deployment preview/apply 全链与 S3/S4 的 admin 写操作（provider toggle 等）被 RBAC 拦（operator 服务密钥）；apply 涉及写 `deployment.config.json`+`.env` 镜像（计划决策 #5 要求用户确认）。选项：临时提权 service key（role=admin→restart→冒烟→恢复）完成完整链，或以 `test_deployment_config.py` 单测覆盖为准（原子 apply/`.bak.1-3` 轮换/回滚均已断言）。浏览器抽查 PathConfigSection 无登录凭据，同列用户手动项（组件测试已断言）。

## 9. 验证证据索引

- 人工复核：runtime_status_service.py:55-105、effective_config.py:215-345、celery_app.py:90-141、GeneralSettings.vue:230-337、provider_result_builder.py:59-60/214/262、tile_service.py:530/767、fetch_gateway.py:184-186/256、transition_builder.py:96/138、submission_service.py:592-636、setLevel 全仓唯一 core/logging.py:46、budget 键全仓 rg 零消费。
- 三路 Explore 底稿：写端点全集（config_routes 38 端点 + runtime_router 4 + R4）、deployment 25 键逐键消费链、热载链（api-keys/weather/GEE/remote/portal/hydrate 调用方 7 处）。
- 关键行号冲突修正：runtime_status_service 实际路径在 `services/workflow/` 下（计划原文写 `services/`，已按事实记录）。

## 10. 阶段5 收口（2026-08-18，全量回归 + 提交）

| 项 | 结果 | 证据 |
|---|---|---|
| 后端全量回归 | ✅ | `pytest Test/backend`：**1992 passed, 2 skipped**（含新增 12 项） |
| 前端全量回归 | ✅ | vitest：141 文件 **1001 passed**；eslint 0 错；`npm run build` 5.53s 成功（仅 2 条已知非阻断提示：overlay-symbology 双导入、vite 插件耗时占比） |
| pre-commit 全量 | ✅ | ruff / ruff-format / mypy / eslint / prettier / 私钥与大文件检查全过（首轮 ruff 自动修复 2 处格式，复跑全绿；TRAE shell 需补 `PATH+=C:\Windows\System32` + `COMSPEC`，否则 xargs 找不到 cmd.exe 报 NoneType） |
| 提交 | ✅ | **5b99206** `fix(config): runtime 调优键真实生效与 PATCH 白名单对齐`（18 文件 +460/-38；git add -A 全量暂存单提交，遵循 2026-08-16 事故硬约定）；分支 dev 领先 origin/dev 3 提交，**未推送**（待用户指示） |

**工作区终态**：clean；本次任务三提交：fd1c11f（info-panel 收口）/ 236c357（launcher 世代清扫）/ 5b99206（config 真实生效）。
