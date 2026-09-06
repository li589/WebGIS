# CGDA 架构审查清单（Phase 1）

> 审查人：架构师高见远（software-architect）
> 日期：2026-08-07
> 范围：G1 后端核心（api/services/core/weatherengine）+ G3 前端 store 架构（stores/ + components/map/）
> 性质：只读架构审查，未修改任何代码

## 1. 架构总评
后端分层总体健康：api→services→core 单向依赖、无 service import router；workflow 服务用 DI 容器（service_container.py）、多引擎用 bridge 链+队列查表（workflow_tasks.py）扩展性良好；SSRF 防护（DNS 重绑定钉死 IP）、Celery visibility_timeout/acks_late 等已见成熟处理。主要风险集中在前端：layers god store（4464 行）未拆分、store→component 依赖倒置；后端并发面：Open-Meteo sync 无全局互斥、多处进程内内存态在 FastAPI 多 worker 下状态分裂。**健康度：⚠️（可运行，但并发一致性 + 前端可维护性为 P1 隐患）**

## 2. 分层与边界问题
| ID | 位置 | 问题 | 严重度 | 建议 |
|----|------|------|--------|------|
| L1 | `Code/backend/app/api/routers/weather_router.py:180` | trigger_open_meteo_sync 在 router 内做 docker compose 探测、Celery 降级、线程派发（~90 行业务编排） | P2 | 抽取 weather_sync_service，router 只留 HTTP 壳 |
| L2 | `Code/backend/app/api/routers/workflow_router.py:218` | materialize_workflow_map_layers 含 ~180 行磁盘扫描 + raster timeseries upsert 业务 | P2 | 下沉到 services（python_provider_result_builder 域） |
| L3 | `Code/backend/app/weatherengine/service.py`（2436 行）/ `services/config_service.py`（1635 行） | 两个 god 模块：前者 fetch/parse/全部 build_*_geojson/COG 混杂；后者 API keys+GEE+天气 provider+数据源+portal+远端存储 6 域 | P2 | 按域拆分：渲染原语构建器、配置域仓储 |
| L4 | `Code/backend/app/services/effective_config.py:106` | 访问 config_service 私有函数 `_sync_api_config_manager_key` 做投影 | P3 | 提公共接口，消除跨模块私有调用 |

## 3. 依赖方向问题
| ID | 位置 | 问题 | 严重度 | 建议 |
|----|------|------|--------|------|
| D1 | `Code/frontend/src/stores/weather-tile-manager.ts:18`、`stores/layers/index.ts:25`、`stores/overlay-symbology.ts:7` | store 反向 import components/map（map-viewport-sync、weather-render、layer-symbology）——状态层依赖表现层 | P2 | normalizeLngBounds/renderHint 等下沉 `src/utils`，强制 store 只依赖 services/utils |
| D2 | `Code/frontend/src/stores/layers/index.ts`（头 79 行） | god store 聚合 6 个其他 store + 11 个 layers/ 子模块，hub-and-spoke 高扇入 | P2 | 见 §4 拆分 |
| D3 | `Code/backend/app/services/` | 176 处服务间交叉 import；`_load_runtime_overrides`→workflow_repository 延迟导入规避环 | P3 | 抽共享契约层（shared.contracts 已部分承担），减少运行时 import |

## 4. Layers god store 拆分方案（现状 → 建议边界）
**现状**：`stores/layers/index.ts` 4464 行、~80 个导出成员；catalog.ts/result-adapter/workspace-persist/weather-viewport 等 11 个辅助模块已拆出但仍全部被单一 store 吸入；同时承担图层增删/顺序/透明度、run group 管理、工作流提交/轮询/恢复、点天气查询、视口同步、workspace 持久化。
**建议拆为 3 个 store**（不做，仅边界方案）：
- `useLayerWorkspaceStore`：activeLayers、runLayerGroups、顺序/透明度/显示名、workspace-persist、sidebarView、selectedInstance —— 纯图层状态；
- `useWorkflowRunStore`：jobLayers、run group 生命周期、事件轮询（EVENT_POLL_* 常量）、submit/cancel/retry、tracked-runs 恢复、pointWeather —— 工作流与数据获取；
- `useLayerViewportStore`：currentHour、map viewport、weather-viewport slices、flushWeatherTileViewports、windDisplayMode。
约束：weather-tile-manager 保持独立传输层，layers 系列只依赖它不反向合并；任何新 store 不得 import components/。

## 5. 并发/运行架构问题
| ID | 位置 | 问题 | 严重度 | 建议 |
|----|------|------|--------|------|
| C1 | `tasks/open_meteo_sync_tasks.py:110` + `api/routers/weather_router.py:180` + `launch/cli.py:209` | sync 三入口（Beat/UI/launch）均直接 `docker compose run` 写同一 named volume，**无全局互斥**；redis_client.acquire_dedup_lock 已存在但 sync 路径未用 | P1 | sync 入口统一加 Redis SET NX 锁（key=sync:{domains}），持锁失败直接跳过/返回 409；本地线程路径加进程内 threading 锁 |
| C2 | `api/routers/weather_router.py:25,21` | `_LOCAL_SYNC_JOBS`、`_COVERAGE_CACHE` 仅进程内存：FastAPI 多 worker 下 status/coverage 请求落到其他进程 → 404/重复探针打上游 | P1 | sync job 状态落 Redis（TTL）或 DB；coverage 探针结果落 Redis |
| C3 | `core/celery_app.py:53` | `worker_pool="solo"`：单 worker 内无并行，concurrency 设置对 solo 无效；卡死任务仅 watchdog 标记状态、不释放 worker（注释已承认） | P2 | 生产 Linux 切 prefork+concurrency 按队列分配；solo 保留为 Windows 开发兜底 |
| C4 | `services/workflow_repository.py` + `api_keys_repository.py` + `gee_credentials_repository.py` | 4 个独立 SQLite 库被 FastAPI+Celery 多进程写；WAL+busy_timeout(30s) 缓解但状态机转移（submit/cancel/retry）无 CAS 版本号，竞态可致状态回滚 | P2 | run 状态更新加 `WHERE status=<期望前态>` 乐观锁，冲突重读 |

## 6. 性能架构问题
| ID | 位置 | 问题 | 严重度 | 建议 |
|----|------|------|--------|------|
| R1 | `services/source_fetcher.py:239,325` | 本地/远端文件 `read_bytes()` 全量进内存再 `put_bytes`，默认上限 512MB、可配 8GB → 内存峰值/OOM | P2 | 流式拷贝（shutil.copyfileobj/分块上传）到 object_store |
| ~~R2~~ | ~~`core/redis_client.py:30`~~ | ~~断路器 threshold=1：单次瞬时 Redis 错误即全局关缓存 30s，瓦片热路径退化为重算风暴~~ | ~~P2~~ | **✅ 已修复（2026-08-12）**：threshold 1→3 + 指数退避 30→60→120s；集中式断路器默认 5；Open-Meteo 断路器 10。见 `2026-08-12-p2-quick-wins.md` |
| R3 | `weatherengine/tile_service.py:47` | 内存 LRU(256) × 每进程（FastAPI+7 worker 各自副本）内存放大；Redis 为真正共享层。SCAN 已正确使用（KEYS 未出现，验证通过） | P3 | 接受现状，明确 Redis 为权威缓存、进程 LRU 仅热点 |

## 7. 扩展性问题
| ID | 位置 | 问题 | 严重度 | 建议 |
|----|------|------|--------|------|
| X1 | `layer_catalog.py` / `weatherengine/constants.py` / `frontend/src/stores/layers/catalog.ts` | 新增一个算法节点/数据源需动 5+ 模块，且图层引擎绑定存在三处真源（后端 layer_catalog engine、WEATHER_LAYER_SPECS、前端 LAYER_LIBRARY） | P2 | 统一为单一图层注册表（后端下发 schema，前端消费），消灭手工同步 |
| X2 | `weatherengine/fetch_gateway.py:229` | 商业源"稀疏网格不可用于瓦片"是隐式规则，写死在网关 | P2 | 提升为 provider 能力声明（如 `grid_density=dense|sparse`） |
| X3 | `services/api_config.py` vs `services/effective_config.py` | ApiConfigManager 与 effective_config 双读路径并存（前者仅只读投影，注释已声明） | P3 | 收敛为单入口，删除第二套消费面 |

## 8. 已知遗留项复核结论
1. **Layers god store 未完全拆分**：确认未拆分（4464 行/~80 导出）；辅助模块已拆但仍是单一 store。→ 按 §4 方案执行，属 P2 可维护性，不阻塞发布。
2. **sync 无全局互斥锁**：确认存在且**升级为 P1**——三入口可并行 `docker compose run` 写同一 volume（文件级竞争/损坏），而现成 acquire_dedup_lock 未接线。建议本 Phase 修复。
3. **`_LOCAL_SYNC_JOBS` 仅内存**：确认存在；**新增风险**：`_COVERAGE_CACHE`（weather_router.py:21）同性质，FastAPI 多 worker 下 coverage 探针每进程重复打 Open-Meteo 上游。建议与 C2 一并落 Redis。
4. **时间轴 coverage 探针时区偏差**：确认存在——探针硬编码 `timezone=Asia/Shanghai`（weather_router.py:49），而 forecast client 用 `timezone=auto`（client.py:458,779）按点自动推导；非中国区域/DST 切换时 times 索引与瓦片 hour 错位。建议时区收敛为单一可配置常量（如 `weather_timezone`），探针与取数共用。
