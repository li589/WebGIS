# 天气图层系统工程级改进计划

> **更新于 2026-07-11**：根据代码实际状态核查后重写。原计划中大量项目已在前序迭代中完成（Redis 缓存、请求去重、bbox 限制、动态分辨率、数据预取、失败分类与重试、stale cache 降级）。本版本聚焦尚未完成且有实际收益的改进项。

## 现状核查

### 已完成项（无需重复）

| 原计划项 | 状态 | 实现位置 |
|---------|------|---------|
| 1.1 限制 bbox 大小 | ✅ 已完成 | 前端 `stores/layers/index.ts` WEATHER_REQUEST_BUCKETS（z0-z5 分级，最大 360×170 → 最小 15×10）；后端 `_utils.py:compute_dynamic_resolution`（5 档分辨率梯度） |
| 1.2 Redis 缓存 | ✅ 已完成 | `redis_client.py` + `weatherengine/client.py`（cache_get_json/cache_set_json，commit f9ca734） |
| 1.3 请求去重 | ✅ 已完成 | `weatherengine/client.py` SETNX 跨 worker 去重锁（`weather:lock:point:*` / `weather:lock:grid:*`） |
| 3.1 数据预取 | ✅ 已完成 | 前端 BFS 环形扩散预取（WEATHER_PREFETCH_CONCURRENCY=2，WEATHER_PREFETCH_MAX_QUEUE=30，expandWeatherTilePrefetch） |
| 2.1 失败分类与重试 | ✅ 部分完成 | FailureClassifier + RetryPolicy（指数退避+抖动，P1-4）；stale cache 429 降级（weatherengine/client.py）；**断路器未实现** |

### 当前实际问题（来自运行时观测）

1. **风场数据稀疏/不连续**：地图平移后风场粒子出现断裂，边缘不衔接。根因：`buildMergedGeojsonForCatalog` 的去重 key 包含 `height:value`，相邻瓦片在边界处的特征点位置不完全重合，导致合并后出现缝隙
2. **`/layers` 端点响应过慢**：首次调用需 ~72s。根因：`dataset_config` 导入 + 8 并发 readiness 检查全部触发 provider 路径解析
3. **Open-Meteo API 429 限流**：并发 workflow 导致 API 限流，虽有 stale cache 降级但响应仍慢

---

## 改进方案

### 阶段 A：风场连续性修复（高优先级）

#### A.1 修复瓦片合并去重逻辑

**问题**：`buildMergedGeojsonForCatalog`（index.ts:1020）的去重 key 为 `lng:lat:height:value`，相邻瓦片在边界处的网格点位置因分辨率步长不同（snap 后）不完全对齐，导致合并后出现空隙

**方案**：
- 去重 key 仅用坐标（`lng:lat`），去掉 `height:value`（同坐标不同高度是正常的多层叠加，不应去重）
- 对边界点做容差匹配（±0.01°），避免 snap 步长导致的微小偏移被当作不同点

**修改文件**：
- `Code/frontend/src/stores/layers/index.ts` — `buildMergedGeojsonForCatalog`

#### A.2 瓦片边界对齐

**问题**：不同 zoom bucket 的瓦片分辨率不同（z2=120×80 vs z3=60×40），平移跨 bucket 时网格点不衔接

**方案**：
- 平移时若 zoom bucket 未变化，仅增量加载新进入视口的瓦片，不重置已有缓存
- 跨 bucket 切换时做一次完整重载（已有 `evictDistantWeatherTiles` 逻辑，确认其在 bucket 切换时正确清旧）

**修改文件**：
- `Code/frontend/src/stores/layers/index.ts` — 瓦片加载/驱逐逻辑

---

### 阶段 B：`/layers` 性能修复（高优先级）

#### B.1 dataset_config 导入优化

**问题**：`/layers` 首次调用 ~72s。`workflow_request_resolver._load_provider_dataset_helpers` 在 ThreadPoolExecutor 内导入 `dataset_config`（5s 超时），但 `list_layers` 路由又对每个图层并行调用 `describe_layer_run_readiness`（8 并发），每个都触发 `_resolve_provider_dataset_path`（lru_cache），首次串行等待

**方案**：
- 在应用启动时（FastAPI lifespan）预热 `_load_provider_dataset_helpers` 缓存，避免首次请求时阻塞
- `/layers` 路由的 readiness 检查改为惰性：首次只返回 `run_readiness="unknown"`，后台异步填充

**修改文件**：
- `Code/backend/app/main.py` — lifespan 预热
- `Code/backend/app/api/routes.py` — `list_layers` 改为惰性 readiness
- `Code/backend/app/services/workflow_request_resolver.py` — 添加 `warm_provider_helpers()` 函数

---

### 阶段 C：断路器与限流保护（中优先级）

#### C.1 Open-Meteo 断路器

**问题**：API 持续 429 时仍反复重试，浪费请求配额且增加延迟

**方案**：
- 在 `OpenMeteoClient` 中增加进程内断路器（CLOSED → OPEN → HALF_OPEN）
- 连续 5 次 429/超时后打开断路器，60s 内直接返回 stale cache，不发请求
- 半开状态放行 1 个探测请求，成功则关闭断路器

**修改文件**：
- `Code/backend/app/weatherengine/client.py` — 增加 `CircuitBreaker` 内部类
- `Code/backend/app/weatherengine/constants.py` — 断路器参数常量

#### C.2 workflow 并发限流优化

**问题**：429 容量限制时（active_runs=4），前端仍持续提交预取请求

**方案**：
- 前端收到 429 后暂停预取队列，等待退避时间后再恢复（已有 `429 退避时间戳` 逻辑，确认覆盖预取队列）

**修改文件**：
- `Code/frontend/src/stores/layers/index.ts` — 确认 429 退避覆盖预取 drain

---

### 阶段 D：多数据源故障转移（低优先级）

#### D.1 天气数据源备用切换

**问题**：单点依赖 Open-Meteo API

**现状**：`ApiConfigManager` 已注册 OPEN_METEO / TIANDITU / BAIDU / GAODE / GEE，但 weatherengine 仅使用 Open-Meteo

**方案**：
- 在 `OpenMeteoClient` 之外封装 `MultiSourceWeatherClient`，按优先级尝试
- 断路器打开时自动切换到备用源（如有配置）
- 无备用源配置时回退到 stale cache（已有逻辑）

**修改文件**：
- `Code/backend/app/weatherengine/client.py` — 封装多源客户端
- `Code/backend/app/services/api_config.py` — 天气数据源优先级配置

---

### 阶段 E：性能监控增强（低优先级）

#### E.1 请求耗时指标

**现状**：`/runtime/status` 已有 redis_cache stats、cache_stats、celery stats（P1-5），但缺少 API 请求耗时统计

**方案**：
- 在 FastAPI 中间件中记录每个端点的 P50/P95 耗时
- 写入 Redis hash（`metrics:{endpoint}:{date}`），TTL 24h
- 新增 `/runtime/metrics` 端点查询

**修改文件**：
- `Code/backend/app/main.py` — 性能中间件
- `Code/backend/app/api/routes.py` — `/runtime/metrics` 端点
- `Code/backend/app/core/redis_client.py` — metrics 读写辅助

---

## 实施优先级

| 优先级 | 任务 | 预期收益 | 状态 |
|--------|------|---------|------|
| P0 | A.1 瓦片合并去重修复 | 解决风场断裂可见问题 | ✅ 完成 2026-07-11 |
| P0 | B.1 /layers 预热 + 惰性 readiness | 首次响应 72s → 7s | ✅ 完成 2026-07-11 |
| P1 | A.2 瓦片边界对齐 | 跨 bucket 平移时无缝衔接 | 待开始 |
| P1 | C.1 Open-Meteo 断路器 | 429 风暴时快速降级，减少无效请求 | 待开始 |
| P2 | C.2 预取 429 退避确认 | 防止容量耗尽时持续冲击 | 待开始 |
| P3 | D.1 多数据源故障转移 | Open-Meteo 宕机时仍可用 | 待开始 |
| P3 | E.1 性能监控增强 | 可观测性，辅助后续调优 | 待开始 |

---

## 验证指标

| 指标 | 目标 | 验证方式 |
|------|------|---------|
| 风场连续性 | 平移后无可见断裂 | 前端目视 + 网格点密度对比 |
| `/layers` 首次响应 | <2s | E2E 脚本计时 |
| Open-Meteo 429 降级延迟 | <1s（断路器打开后直接 stale） | 单元测试 + 日志 |
| 缓存命中率 | >80% | `/runtime/status` redis_cache stats |
