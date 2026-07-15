# 天气图层标准瓦片渲染改造计划（可执行版）

## 1. 摘要

当前天气图层仍走“前端按视口 bbox 提交 workflow → 后端 `WeatherEngineService.execute` 拉取 Open-Meteo 网格 → 前端合并 GeoJSON → Canvas 2D 渲染”的链路。
缩放/平移时频繁触发新 workflow，且旧逻辑存在：

- 单图层只能有一个活跃 workflow（`weatherRunTileSpecs` 只记录一个 `primary`）。
- 预取瓦片成功后直接 `patchCatalogJobLayerGeojson`，新数据与旧数据在合并时按坐标去重，浮点精度与瓦片边界处理不统一。
- 风羽层在 particle_flow 模式下曾被无条件创建（已条件化，但数据变更仍可能误触发）。

用户反馈“第一次加载正常，缩放/移动后忽然变稀疏/出现小短线”，根因是**数据按非标准瓦片重新组装、工作流串行化、外扩预取与视口移动冲突**。

本计划按用户已确认的决策落地：

- **实现路径**：后端标准瓦片服务（z/x/y GeoJSON 瓦片）。
- **并发模型**：全局并发槽位（默认 4）+ 图层内优先级队列，取消“每天气图层仅一个活跃工作流”限制。

最终形态：前端按标准 Web Mercator 瓦片请求天气数据，后端 `/weather/tiles/{layer_id}/{z}/{x}/{y}` 直接返回 GeoJSON；视口内瓦片优先加载，外围瓦片低优先级 BFS 预取；已缓存瓦片直接复用，移动时取消 outdated 请求。

## 2. 现状分析（基于当前代码）

### 2.1 后端

| 文件 | 当前状态 | 与本次改造的关系 |
|------|----------|------------------|
| `Code/backend/app/weatherengine/tile_service.py` | 已创建，含 `tile_bbox`、`zoom_to_resolution`、`WeatherTileService.get_tile`、内存 LRU + Redis 缓存、全局 `asyncio.Semaphore(4)` | 可直接复用，无需大改 |
| `Code/backend/app/weatherengine/service.py` | 已实现 `build_wind_geojson_from_grid`、`build_temperature_geojson_from_grid`、`build_precipitation_geojson_from_grid`、`build_humidity_geojson_from_grid`、`build_pressure_geojson_from_grid`、`build_visibility_geojson_from_grid` | `tile_service.py` 将直接调用这些构建器 |
| `Code/backend/app/weatherengine/client.py` | `fetch_grid_forecast` 已支持 bbox + resolution，内置断路器、429/stale cache、跨 worker 去锁 | `tile_service.py` 生成瓦片时调用 |
| `Code/backend/app/main.py` | 已 include `tile_router`（底图代理），未注册天气瓦片路由 | 需要新增并注册 `/weather/tiles` 路由 |
| `Code/backend/app/api/routes.py` | 已有 `/weather/point` 与 `/weather/workflows/*` | 天气瓦片路由独立到新文件，不改动此处 |

### 2.2 前端

| 文件 | 当前状态 | 与本次改造的关系 |
|------|----------|------------------|
| `Code/frontend/src/stores/layers/index.ts` | 维护 `weatherTileCache`、`weatherPrefetchQueue`、`weatherPrefetchActiveKeys`；`runWorkflowForCatalog` 对天气图层提交 bbox workflow；`buildMergedGeojsonForCatalog` 按坐标去重合并 | 需要移除旧虚拟瓦片 workflow 逻辑，接入瓦片管理器 |
| `Code/frontend/src/components/MapCanvas.vue` | `resolveAllWeatherOverlayStates` 从 `jobLayer.mapLayerPayload.layerAssets` 取 `geojsonUrl/geojsonData`；`syncWindParticleFlow` fetch GeoJSON 后渲染 | 需要从瓦片管理器取合并 GeoJSON，保留旧数据 fallback |
| `Code/frontend/src/components/map/wind-particle-canvas.ts` | 从 GeoJSON 构建 WindGrid，含 BFS 最近邻填洞、校验和、粒子保留 | 复用，输入改为多瓦片合并 GeoJSON |
| `Code/frontend/src/components/map/canvas-utils.ts` | `computeCanvasLayout` 处理 world wrap | 复用 |

### 2.3 根因定位

1. **数据组装问题**：旧逻辑按“中心点 + 缩放级别分桶”生成一个非标准 bbox，工作流返回后按 `lng:lat:height` 去重合并。不同请求 bbox 浮点差异导致相邻请求重叠点无法去重，重复点与真实网格错位，粒子流/风羽出现“小短线”。
2. **单 workflow 限制**：`weatherRunTileSpecs` 只保存一个 `primary` run，移动时虽然调用 `interruptWorkflowForCatalog`，但新请求未到达前旧数据已被 patch 覆盖。
3. **外扩与移动冲突**：`expandWeatherTilePrefetch` 在旧位置瓦片成功后继续 BFS，用户移动后 `trimWeatherPrefetchQueueForCatalog` 仅清理队列，已经发出的请求结果仍可能写入 `weatherTileCache` 并参与合并。
4. **坐标系转换**：`buildDefaultViewportBBox`、`snapRequestCenter` 等逻辑在前端独立做 bbox 推导，与后端网格生成不一致。

## 3. 目标与非目标

### 3.1 目标

- 后端新增 `/weather/tiles/{layer_id}/{z}/{x}/{y}`，按标准 Web Mercator z/x/y 返回 GeoJSON。
- 前端以瓦片为最小单位请求、缓存、拼接；视口内瓦片优先，外围瓦片 BFS 预取。
- 取消“每天气图层仅一个活跃工作流”限制，改为全局 4 槽位并发 + 图层内优先级队列。
- 粒子流/风羽/等值线基于“视口内可见瓦片合并后的统一网格”渲染，消除接缝与零值伪影。
- 缩放/平移后只重新请求缺失瓦片，已缓存瓦片直接复用，减少闪烁与卡顿。

### 3.2 非目标

- 不引入 MVT/PNG/COG 瓦片格式；仍返回 GeoJSON FeatureCollection。
- 不改动底图瓦片代理 `/tiles/{provider}/{z}/{x}/{y}`。
- 不替换 Open-Meteo 数据源。
- 不改动非天气类图层的工作流链路。

## 4. 关键设计决策

1. **瓦片格式仍用 GeoJSON**：保持现有 Canvas 2D 渲染器不变，减少前端改动量。
2. **标准 z/x/y Web Mercator 瓦片**：与底图代理一致，前后端缓存键统一。
3. **后端瓦片服务内部做 Web Mercator → EPSG:4326 转换**：Open-Meteo 使用 WGS84，`tile_service.py` 已用 `tile_bbox` 实现。
4. **全局并发 4 槽位**：与 `settings.max_active_runs=4` 和 Open-Meteo 限流经验一致。
5. **视口优先 + BFS 外扩**：用户可见区域最先渲染，外扩仅作缓存预热。
6. **AbortController 取消 outdated 请求**：平移时旧请求立即取消，避免结果错配与资源浪费。
7. **保留旧数据作为 fallback**：新视口数据未就绪时不显示空白。

## 5. 详细实施步骤

### 阶段一：后端天气瓦片服务

#### 5.1 新增 `Code/backend/app/api/weather_tile_routes.py`

实现 `GET /weather/tiles/{layer_id}/{z}/{x}/{y}`：

- Query 参数：
  - `hour: int = 0`（预报小时，限制 0~47）
  - `model: str | None = None`（默认读取 `settings.weather_default_model`）
  - `t: int | None = None`（仅用于客户端缓存 bust，不参与业务）
- 校验：
  - `layer_id ∈ WEATHER_LAYER_SPECS`，否则 400。
  - `z ∈ [0, 12]`，`x`、`y` 在对应 zoom 范围内，否则 400。
- 调用 `weather_tile_service.get_tile(layer_id, z, x, y, hour=hour, model=model)`。
- 响应头：
  - `X-Weather-Tile-Key: {layer_id}:z{z}:x{x}:y{y}:h{hour}`
  - `X-Weather-Tile-Cache: hit | miss`
  - `Cache-Control: public, max-age={settings.weather_cache_ttl_seconds}`
- 返回 `GeoJSON FeatureCollection`。
- 异常处理：
  - `ValueError` → 400
  - 上游 Open-Meteo 断路器打开且无 stale cache → 503
  - 其他内部异常 → 500

#### 5.2 在 `Code/backend/app/main.py` 注册路由

在 `app.include_router(tile_router)` 之后新增：

```python
from app.api.weather_tile_routes import router as weather_tile_router
app.include_router(weather_tile_router)
```

#### 5.3 调整 `Code/backend/app/weatherengine/tile_service.py`（如有必要）

- 确认 `_build_geojson` 已覆盖所有 `WEATHER_LAYER_SPECS` 的 `layer_id`：
  - `wind-field*` → `build_wind_geojson_from_grid`
  - `temperature*` → `build_temperature_geojson_from_grid`
  - `precipitation` → `build_precipitation_geojson_from_grid`
  - `humidity` → `build_humidity_geojson_from_grid`
  - `pressure` → `build_pressure_geojson_from_grid`
  - `visibility` → `build_visibility_geojson_from_grid`
- 若新增图层，按相同模式扩展 `_build_geojson`。
- 当前 `zoom_to_resolution` 映射：z≤1→5°, z≤3→2°, z≤5→1°, z≤7→0.5°, 其他→0.25°，保持不变。

#### 5.4 新增 `Code/backend/tests/test_weather_tile_service.py`

测试用例：

1. `tile_bbox(0, 0, 0)` 接近全球 bbox（`west=-180, east=180, north≈85.05, south≈-85.05`）。
2. `tile_bbox(5, 25, 12)` 计算值与手工公式一致。
3. `tile_key` 格式符合 `weather:tile:{layer_id}:z{z}:x{x}:y{y}:h{hour}:m{model}`。
4. `WeatherTileService.get_tile` 对同一瓦片第二次返回 `hit`（mock Redis/内存缓存）。
5. 无效 `layer_id` 抛 `ValueError`；无效 `z/x/y` 抛 `ValueError`。
6. `hour` 越界时被钳制到 0~47。
7. 并发请求 6 个不同瓦片时，由于 `semaphore=4`，最多同时进入 `_generate_tile` 4 个（通过 mock/计数验证）。

### 阶段二：前端瓦片调度器

#### 5.5 新增 `Code/frontend/src/services/weather-tile-api.ts`

导出：

- `fetchWeatherTile(layerId, z, x, y, options: { hour?, model?, signal? })`
  - 调用 `resolveApiUrl('/weather/tiles/...')`。
  - 使用 `AbortController` / `signal` 支持取消。
  - 返回 `Promise<WindGeoJSON>`。
- `buildTileKey(layerId, z, x, y, hour)`：与后端缓存键一致（用于前端缓存索引）。
- `lngLatToTile(lng, lat, z) -> { x, y }`：标准 Web Mercator 瓦片坐标。
- `tilesInViewport(map, buffer = 1) -> Array<{ z, x, y }>`：
  - 根据地图当前 zoom 取整得到 `z`。
  - 计算视口四个角对应的 tile x/y，扩展 `buffer` 圈。
  - 处理 `renderWorldCopies: true` 下经度越界，返回主世界 tile。
- `tileToLngLatBounds(z, x, y) -> { west, south, east, north }`：与后端 `tile_bbox` 一致，用于调试和优先级排序。

#### 5.6 新增 `Code/frontend/src/stores/weather-tile-manager.ts`

以 Pinia store 形式实现 `useWeatherTileManager`（也可先实现为独立类再挂载到 store）。

核心类型：

```typescript
interface WeatherTileState {
  key: string
  layerId: string
  z: number
  x: number
  y: number
  hour: number
  model: string
  status: 'idle' | 'loading' | 'succeeded' | 'failed'
  geojson: WindGeoJSON | null
  abortController: AbortController | null
  loadedAt: number
  retryCount: number
}
```

常量：

- `MAX_CONCURRENT_TILE_REQUESTS = 4`
- `MAX_RETRIES = 3`
- `INITIAL_RETRY_DELAY_MS = 2000`
- `PREFETCH_BUFFER = 1`（视口外扩 1 圈作为预取）
- `CACHE_MAX_PER_LAYER_ZOOM = 64`

状态：

- `tileCache: Map<string, WeatherTileState>`（key = buildTileKey）
- `runningRequests: Set<string>`
- `pendingQueues: Map<layerId, WeatherTileState[]>`（视口瓦片高优先级队列）
- `prefetchQueues: Map<layerId, WeatherTileState[]>`（外扩预取低优先级队列）

核心方法：

- `setViewport(layerId, center, zoom, hour, model)`：
  1. 计算新视口 tile 集合 `tilesInViewport(map, buffer=0)`。
  2. 对不在新视口内的 `loading` tile，调用 `abortController.abort()` 并从 `runningRequests` 移除。
  3. 清空该图层的 `prefetchQueues`。
  4. 对缺失 tile 按到视口中心距离排序，加入 `pendingQueues[layerId]`。
  5. 触发 `drainQueues()`。
- `drainQueues()`：
  - 优先消费所有图层的 `pendingQueues`（按图层加入顺序/中心距离）。
  - 当 `runningRequests.size < MAX_CONCURRENT_TILE_REQUESTS` 时，从队列取出一个 tile，调用 `loadTile(tile)`。
  - 只有当所有 `pendingQueues` 为空时，才消费 `prefetchQueues`。
- `loadTile(tile)`：
  - 先检查 `tileCache`，命中且未过期直接返回。
  - 创建 `AbortController`，加入 `runningRequests`。
  - 调用 `fetchWeatherTile`。
  - 成功后写入 `tileCache`，状态 `succeeded`，从 `runningRequests` 移除，触发 `onTileLoaded(layerId, tile)`。
  - 失败时若 `retryCount < MAX_RETRIES` 按指数退避重新入队；否则状态 `failed`。
  - 组件卸载/视口变化导致 `AbortController` 已 abort 时，不更新状态。
- `onTileLoaded(layerId, tile)`：
  - 若该图层当前视口所有必需 tile 都已成功，触发 `emit('viewport-ready', layerId)`。
  - 若该 tile 属于当前视口，调度 BFS 外扩：将该 tile 的 8 邻居加入 `prefetchQueues[layerId]`（低优先级）。
- `getMergedGeojsonForViewport(layerId, map, hour, model) -> WindGeoJSON | null`：
  - 获取当前视口 tile 集合。
  - 仅合并 `status === 'succeeded'` 的 tile GeoJSON。
  - 调用 `mergeTileGeojsons(tiles, layerId)`。
  - 若视口 tile 未全部就绪但存在旧合并数据，返回旧数据（fallback）。
- `evictDistantTiles(layerId, center, z)`：
  - 当 `(layerId, z)` 缓存数超过 `CACHE_MAX_PER_LAYER_ZOOM` 时，按到中心距离淘汰最远的 succeeded tile。

#### 5.7 新增 `Code/frontend/src/components/map/weather-tile-utils.ts`

导出：

- `mergeTileGeojsons(tiles: WeatherTileState[], layerId: string): WindGeoJSON | null`
  - 根据 `layerId` 确定主 metric key（如 `wind_speed_10m`、`temperature_2m`）。
  - 坐标去重：量化到 0.001°（约 100m），key = `quantizedLng:quantizedLat:height`。
  - 处理 world wrap：若合并的瓦片跨越日界线，对一侧 tile 的所有点经度统一 `±360` 偏移，使合并后 bbox 连续。
  - 返回标准 `FeatureCollection`。
- `getMetricKeyForLayer(layerId: string): string`
  - `wind-field*` 解析高度后缀。
  - `temperature*` 解析高度后缀。
  - `precipitation/pressure/humidity/visibility` 返回对应字段。

#### 5.8 改造 `Code/frontend/src/stores/layers/index.ts`

变更点：

1. 移除以下旧虚拟瓦片 workflow 相关状态与方法：
   - `weatherTileCache`、`weatherCatalogPrimaryTileKey`、`weatherRunTileSpecs`
   - `weatherPrefetchQueue`、`weatherPrefetchActiveKeys`、`weatherPrefetchBackoffUntil`
   - `WEATHER_REQUEST_BUCKETS`、`buildWeatherTileSpec`、`buildNeighborWeatherTileSpecs`
   - `resolvePrimaryWeatherTileSpec`、`buildDefaultViewportBBox`
   - `enqueueWeatherTilePrefetch`、`expandWeatherTilePrefetch`、`drainWeatherPrefetchQueue`
   - `trimWeatherPrefetchQueueForCatalog`、`pollHiddenWeatherTileRun`
   - `cacheWeatherTileJobLayer`、`extractGeojsonDataFromJobLayer`、`buildMergedGeojsonForCatalog`
   - `applyMergedWeatherTileData`、`patchCatalogJobLayerGeojson`
   - `runWorkflowForCatalog` 中的天气图层 bbox workflow 分支
   - `interruptWorkflowForCatalog` 中的天气相关逻辑
   - `refreshActiveWeatherWorkflows` 中的天气图层刷新逻辑
2. 引入 `useWeatherTileManager`。
3. `setMapViewport(center, bbox, zoom)`：
   - 保留 `currentMapCenter / currentMapBBox / currentMapZoom` 更新。
   - 对每个可见的天气图层调用 `weatherTileManager.setViewport(catalogId, center, zoom, currentHour.value, settings.weather_default_model)`。
4. `currentHour` 变化时：
   - 对所有天气图层调用 `weatherTileManager.invalidateByHour(layerId, hour)`（清空旧 hour 缓存并重新 setViewport）。
5. 保留 `buildRealLayerDisplay`、`extractLayerHotspots` 等渲染适配逻辑，但天气图层的数据状态改为由 `weatherTileManager` 驱动。
6. 在 `activeLayersDisplay` 中，天气图层的 `availabilityState` 可基于 `weatherTileManager.getViewportReadiness(catalogId)` 返回：
   - 视口全部就绪 → `ready`
   - 部分就绪 → `partial`
   - 全部失败或无数据 → `empty`

> **迁移策略**：为降低风险，先在 `layers/index.ts` 中保留旧数据结构（`jobLayer.mapLayerPayload.layerAssets.geojsonData`）作为渲染兼容层，由 `weatherTileManager` 在数据就绪后 patch 到 `jobLayer`。待阶段三验证稳定后再彻底移除 workflow 相关代码。

#### 5.9 改造 `Code/frontend/src/components/MapCanvas.vue`

变更点：

1. 引入 `useWeatherTileManager`。
2. `resolveAllWeatherOverlayStates` 中，对天气图层：
   - 不再依赖 `layer.jobLayer?.mapLayerPayload?.layerAssets?.geojsonUrl/geojsonData`。
   - 调用 `weatherTileManager.getMergedGeojsonForViewport(catalogId, map, props.currentHour, model)` 获取合并 GeoJSON。
   - 将 GeoJSON 放入 `WeatherOverlayState.geojsonData`。
3. `syncWindParticleFlow`：
   - 消费 `state.geojsonData`（来自 manager）。
   - 保持 `enableBarbLayer = overlayState.renderHint.paint_mode === 'barb'`。
   - 保持数据未变化跳过逻辑（基于 URL/data 引用）。
4. `grid_fill` / `heatmap` / `point_symbol` 图层：
   - 直接使用 manager 合并后的 GeoJSON 渲染。
   - 后续可优化为按 tile 独立 source，本次先复用合并 GeoJSON。
5. 地图 `moveend` / `zoomend` 时：
   - `syncMapViewportToStore()` 之后，store 已触发 `weatherTileManager.setViewport`。
   - manager 数据就绪后通过 reactive 状态触发 `MapCanvas` watcher，调用 `scheduleSyncWeatherOverlay()`。

### 阶段三：接入清理与验证

#### 5.10 清理旧代码

- 在 `stores/layers/index.ts` 中删除所有标记为“旧虚拟瓦片 workflow”的状态、常量、方法。
- 删除 `WEATHER_REQUEST_BUCKETS`、`WEATHER_PREFETCH_*` 等常量。
- 保留 `isWeatherEngineCatalogId`、`supportsMapLayerResult`、`supportsParticleFlow` 等必要工具函数。

#### 5.11 类型检查与验证

后端：

```powershell
cd "D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\backend"
python -m pytest tests/test_weather_tile_service.py -v
python -m pytest tests/test_weatherengine_service.py tests/test_weatherengine_client.py -v
```

前端：

```powershell
cd "D:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Code\frontend"
npm run type-check  # 或 vue-tsc --noEmit
```

端到端手动验证：

1. 启动前后端，打开 `http://localhost:5173`。
2. 添加 `wind-field` 图层，DevTools Network 应只看到 `/weather/tiles/wind-field/{z}/{x}/{y}?hour=...` 请求，无 `/workflow-runs` 请求。
3. 初始粒子流显示正常；平移后 1~2 秒内新视口数据加载完成，无“小短线”或稀疏现象。
4. 缩放时先显示旧数据，新 zoom 瓦片就绪后平滑切换。
5. 控制台检查：
   - `[WeatherTileManager]` 视口 tile 集合、加载状态、缓存命中。
   - `[WindParticleCanvas]` 合并后网格 rows/cols、缺失单元数、checksum。
   - 无 `[WindBarbLayer]` 在 `particle_flow` 模式下的绘制日志。
6. 外扩验证：视口稳定 2 秒后，Network 出现低优先级外围 tile 请求；再次平移时这些请求被 cancel。
7. 同时添加风场 + 温度，确认两者各自管理瓦片缓存，互不覆盖。
8. 快速缩放/平移 stress test（10 秒内 5 次），无持续卡顿或控制台报错。

## 6. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Open-Meteo 按瓦片请求导致 QPS 过高 | 429/限流 | 后端 semaphore 限制并发；前端缓存；断路器已存在；预取降级为低优先级。 |
| 瓦片合并后网格过大（高 zoom） | 内存/性能问题 | z 限制到 12；高 zoom 使用较粗 resolution；LRU 淘汰。 |
| 跨日界线瓦片坐标不连续 | 粒子流断裂 | `weather-tile-utils.ts` 统一经度偏移后再合并。 |
| 旧 workflow 路径与新 tile 路径共存导致冲突 | 数据重复或覆盖 | 天气图层完全切到 tile 路径；保留 workflow 路径仅用于显式分析任务。 |
| 前端 store 重构规模大 | 引入回归 | 分阶段：先新增 tile manager 并保留旧逻辑兼容层，验证后再移除旧代码。 |

## 7. 实施顺序建议

按以下顺序执行，每步完成后可独立验证：

1. **后端路由与测试**：新增 `weather_tile_routes.py`、注册到 `main.py`、跑通 `test_weather_tile_service.py`。
2. **前端 API 与瓦片工具**：新增 `weather-tile-api.ts` 和 `weather-tile-utils.ts`，编写简单单元测试验证 `lngLatToTile` / `tilesInViewport`。
3. **前端瓦片管理器**：新增 `weather-tile-manager.ts`，先在 `wind-field` 图层上接入。
4. **前端渲染层接入**：改造 `MapCanvas.vue` 和 `stores/layers/index.ts`，使 `wind-field` 走新路径。
5. **全面切换与清理**：所有天气图层切到瓦片路径，删除旧虚拟瓦片代码，运行前后端类型检查和 stress test。
