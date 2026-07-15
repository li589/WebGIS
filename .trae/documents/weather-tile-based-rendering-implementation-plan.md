# 天气图层标准瓦片渲染改造计划（更新版）

> **Current Status (as of 2026-07-11 session continuation)**
> - ✅ Stage 1: Backend standard tile service `tile_service.py` + `weather_tile_routes.py` + `main.py` registration.
> - ✅ Stage 2.1: `weather-tile-api.ts` (coordinate tools + tile fetch) created and stable.
> - ✅ Stage 2.2: `weather-tile-utils.ts` (multi-tile GeoJSON merge + dedup + bounds) created.
> - ✅ Stage 2.3: `weather-tile-manager.ts` (cache, scheduling, global 4 slots, per-layer priority queue, generation) created.
> - ✅ Stage 2.4: `weather-render.ts` default render hints + `buildDefaultWeatherRenderHint`.
> - ✅ Stage 2.5: `stores/layers/types.ts` extended with `renderHint?: WeatherLayerRenderHint`.
> - ⬜ Stage 3: Wire `stores/layers/index.ts`, `MapCanvas.vue`, `LayerSidebar.vue`, `InfoPanel.vue`.
> - ⬜ Stage 4: Validation (pytest, vue-tsc, browser tests).
>
> The user has previously approved this plan: backend standard tile service + global-slot + per-layer priority queue concurrency model. This update reflects the actual code state and the remaining wiring work.

## 1. 背景与目标

当前天气图层（风场粒子流/等值线/风羽/温度填充等）在前 1 秒显示正常，随后出现：
- 粒子流变成密集小短线或突然稀疏；
- 缩放后只剩少量流线；
- 第一次加载正常，后续数据被后续工作流结果覆盖后视觉异常。

根因是前端仍使用“基于 bbox 的虚拟瓦片 + 工作流异步拉取”模式：
- 不同缩放级别/移动位置提交的 bbox 大小、分辨率不一致；
- 多瓦片合并时去重、补洞、坐标系转换存在误差；
- 外扩预取与移动时的请求互相覆盖，导致数据拼接错误。

目标：改为**后端标准 Web Mercator 瓦片服务**（`/weather/tiles/{layer_id}/{z}/{x}/{y}`），前端按瓦片调度，实现：
1. 同一缩放级别下所有瓦片分辨率一致，拼接无错位；
2. 视口内瓦片立即渲染，BFS 外扩预取；
3. 全局并发槽位（默认 4）+ 图层内优先级队列，避免 429；
4. 移动/缩放时取消旧请求、丢弃过期结果，避免冲突。

## 2. 现状分析

### 2.1 后端（已完成）

| 文件 | 状态 | 说明 |
|------|------|------|
| `Code/backend/app/weatherengine/tile_service.py` | ✅ 已创建 | 实现 `tile_bbox`、`zoom_to_resolution`、内存 LRU + Redis 缓存、`asyncio.Semaphore` 并发控制、按图层类型生成 GeoJSON、注入 `_tile_meta`。 |
| `Code/backend/app/api/weather_tile_routes.py` | ✅ 已创建 | 提供 `GET /weather/tiles/{layer_id}/{z}/{x}/{y}`，已在 `main.py` 注册。 |
| `Code/backend/tests/test_weather_tile_service.py` | ✅ 已创建 | 覆盖坐标转换、缓存键、并发控制、缓存命中。 |

### 2.2 前端（部分完成）

| 文件 | 状态 | 说明 |
|------|------|------|
| `Code/frontend/src/services/weather-tile-api.ts` | ✅ 已创建 | `lngLatToTile`、`tileToLngLatBounds`、`tilesInBounds`、`tilesInViewport`、`fetchWeatherTile`、`buildTileKey`。 |
| `Code/frontend/src/services/weather-tile-utils.ts` | ✅ 已创建 | `mergeWeatherTiles`（量化经纬度 + `height` 去重）、`computeTilesBounds`、`buildMergeStats`、`formatMergeStats`。 |
| `Code/frontend/src/stores/weather-tile-manager.ts` | ✅ 已创建 | Pinia store；全局 `MAX_CONCURRENT_TILE_FETCH = 4`；图层内 priority 0（viewport）/1（prefetch）；`generation` 丢弃过期结果；`AbortController` 取消；BFS 外扩邻居。 |
| `Code/frontend/src/components/map/weather-render.ts` | ✅ 已扩展 | `WEATHER_RENDER_HINTS` 常量 + `buildDefaultWeatherRenderHint`，为所有天气图层提供默认 `paint_mode`、`palette`、`primary_metric`、`legend_ticks`。 |
| `Code/frontend/src/stores/layers/types.ts` | ✅ 已扩展 | `ActiveLayerDisplay` 新增 `renderHint?: WeatherLayerRenderHint`。 |
| `Code/frontend/src/stores/layers/index.ts` | ⬜ **待改造** | 仍保留大量旧虚拟瓦片/工作流逻辑（`weatherTileCache`、`buildWeatherTileSpec`、`enqueueWeatherTilePrefetch`、`runWorkflowForCatalog` 天气分支等），需移除并接入 `weatherTileManager`。 |
| `Code/frontend/src/components/MapCanvas.vue` | ⬜ **待改造** | `resolveAllWeatherOverlayStates` 仍从 `jobLayer.layerAssets` 取 GeoJSON；需改为从 tile manager 获取合并数据，并监听 manager 的 `dataVersion`。 |
| `Code/frontend/src/components/LayerSidebar.vue` | ⬜ **待改造** | 添加天气图层后仍调用 `runWorkflowForCatalog` 自动拉取，需改为依赖 tile manager。 |
| `Code/frontend/src/components/InfoPanel.vue` | ⬜ **待改造** | `hasWeatherLayerAsset` 仅判断 `geojsonUrl`，且 `weatherRenderHint` 未优先使用 `displayLayer.renderHint`；需支持 tile manager 数据状态。 |
| `Code/frontend/src/components/map/wind-particle-canvas.ts` | 已稳定 | 支持多源 BFS 补洞、网格校验和，可直接消费合并后的 GeoJSON。 |
| `Code/frontend/src/components/map/wind-barb-layer.ts` | 已稳定 | 使用数据真实 bounds 计算布局，LOD 绘制。 |

## 3. 关键设计决策（已确认）

1. **瓦片坐标系**：统一使用 Web Mercator `z/x/y`，与后端 `tile_service.py` 保持一致。
2. **数据源**：天气图层渲染不再走 `/workflow-runs` 的 `analysis` 命令，直接请求 `/weather/tiles/{layer_id}/{z}/{x}/{y}`；点天气查询仍保持现有 `/weather/point` 工作流不变。
3. **并发模型**：**全局 4 槽位 + 图层内优先级队列**。
   - 视口可见瓦片：`priority = 0`；
   - BFS 外扩瓦片：`priority = 1`；
   - 同优先级按 FIFO；槽位释放时从所有图层队列中按优先级拉取。
4. **移动冲突解决**：每个图层维护 `generation` 计数器。`setViewport` 时 `generation++`，丢弃所有 `generation` 不匹配的结果；同时取消不在新视口内的瓦片 `AbortController`。
5. **结果拼接**：`weather-tile-utils.ts` 按“量化经纬度 + `height`”去重；保留各瓦片原始坐标，依靠 MapLibre `renderWorldCopies` 处理世界副本。
6. **渲染触发**：`MapCanvas` 监听 `currentHour` / 地图视口 / 图层可见性变化，调用 `weatherTileManager.setViewport(...)`；manager 数据版本变化后通过 `dataVersion` ref 触发 `syncWeatherOverlay`。

## 4. 实施步骤

### Stage 3：接入与清理

#### 3.1 改造 `Code/frontend/src/stores/layers/index.ts`

**移除旧虚拟瓦片逻辑**
- 删除状态：
  - `weatherTileCache`
  - `weatherCatalogPrimaryTileKey`
  - `weatherRunTileSpecs`
  - `weatherPrefetchQueue`
  - `weatherPrefetchActiveKeys`
  - `weatherPrefetchBackoffUntil`
- 删除常量/类型/函数：
  - `WEATHER_REQUEST_WORLD_LAT_LIMIT`、`WEATHER_REQUEST_VIEWPORT_EXPANSION`、`WEATHER_REQUEST_TILE_STEP_RATIO`
  - `WEATHER_PREFETCH_CONCURRENCY`、`WEATHER_PREFETCH_MAX_QUEUE`、`WEATHER_TILE_CACHE_MAX_PER_BUCKET`
  - `WEATHER_REQUEST_BUCKETS`、`WeatherTileSpec`、`WeatherTileCacheEntry`
  - `buildWeatherTileSpec`、`buildNeighborWeatherTileSpecs`、`resolvePrimaryWeatherTileSpec`、`buildDefaultViewportBBox`
  - `getWeatherRequestBucket`、`snapRequestCenter`、`getBoundingBoxSpans`、`roundBboxCoordinate`、`areBoundingBoxesEqual`
  - `getWeatherTileCacheKey`、`getWeatherTileCacheEntry`、`setWeatherTileCacheEntry`、`evictDistantWeatherTiles`
  - `extractGeojsonDataFromJobLayer`、`buildMergedGeojsonForCatalog`、`applyMergedWeatherTileData`、`patchCatalogJobLayerGeojson`、`cacheWeatherTileJobLayer`
  - `enqueueWeatherTilePrefetch`、`expandWeatherTilePrefetch`、`drainWeatherPrefetchQueue`、`trimWeatherPrefetchQueueForCatalog`、`pollHiddenWeatherTileRun`
- 改造 `runWorkflowForCatalog`：天气图层（`isWeatherEngineLayer`）不再提交 analysis workflow；仅非天气图层或用户手动“运行工作流”时走原逻辑。
- 清理 `interruptWorkflowForCatalog`、`refreshActiveWeatherWorkflows`、`handleViewportChange` 中仅用于天气刷新的分支。
- 删除 `lastWorkflowSubmitTime`、`lastWorkflowBBox` 中仅用于天气刷新的部分（如保留非天气图层使用则保留）。

**接入 `weatherTileManager`**
- 引入：
  ```ts
  import { useWeatherTileManager } from '../../services/weather-tile-manager'
  ```
- 在 store 内实例化：
  ```ts
  const weatherTileManager = useWeatherTileManager()
  ```
- 修改 `addLayer`：对天气图层调用 `weatherTileManager.setLayerActive(catalogId, true)`。
- 修改 `removeLayer`：对天气图层调用 `weatherTileManager.clearLayer(catalogId)`。
- 修改 `toggleLayerVisibility`：对天气图层调用 `weatherTileManager.setLayerActive(catalogId, layer.visible)`。
- 修改 `setMapViewport`：
  - 更新 `currentMapCenter/BBox/Zoom` 后，对每个可见天气图层调用：
    ```ts
    weatherTileManager.setViewport(
      layer.catalogId,
      center,
      currentMapZoom.value,
      currentHour.value,
      'best_match',
      currentMapBBox.value,
    )
    ```
- 修改 `setCurrentHour`：小时变化时，对所有可见天气图层重新触发 `setViewport`。

**扩展 `ActiveLayerDisplay` 的 `renderHint`**
- 在 `activeLayersDisplay` computed 中，为天气图层填充 `renderHint`：
  ```ts
  renderHint: layer.isAdminBoundary
    ? undefined
    : (buildDefaultWeatherRenderHint(layer.catalogId) ?? layer.jobLayer?.mapLayerPayload?.renderHint),
  ```

#### 3.2 改造 `Code/frontend/src/components/MapCanvas.vue`

**引入 tile manager**
- ```ts
  import { useWeatherTileManager } from '../stores/weather-tile-manager'
  import { buildDefaultWeatherRenderHint } from './map/weather-render'
  ```
- ```ts
  const weatherTileManager = useWeatherTileManager()
  ```

**修改 `resolveAllWeatherOverlayStates`**
- 对每个可见图层：
  - 如果是天气图层（`isWeatherEngineCatalogId(layer.catalogId)`）：
    ```ts
    const geojsonData = weatherTileManager.getMergedGeojsonForViewport(layer.catalogId)
    const renderHint = layer.renderHint ?? buildDefaultWeatherRenderHint(layer.catalogId)
    if (!renderHint) continue
    states.push({
      catalogId: layer.catalogId,
      geojsonUrl: null,
      geojsonData,
      cogPreviewUrl: null,
      cogBbox: null,
      renderHint,
      opacity: layer.opacity,
    })
    ```
  - 非天气图层保持原 `jobLayer.layerAssets` 逻辑。

**修改 `syncWindParticleFlow`**
- 当 `geojsonData` 为内联数据时，判断内容是否变化（比较 feature 数量 + 采样 checksum），避免同一份数据反复触发 `updateGeoJSON` 导致粒子重置。
- 保持现有 `enableBarbLayer = paint_mode === 'barb'` 逻辑。

**扩展 watcher**
- 在现有 watcher 数组中追加 `weatherTileManager.dataVersion`，使瓦片加载完成后触发 `scheduleSyncWeatherOverlay()`：
  ```ts
  watch(
    () => [
      JSON.stringify(...),
      layersStore.particleFlowCatalogId,
      props.currentHour,
      weatherTileManager.dataVersion,
    ],
    () => scheduleSyncWeatherOverlay(),
  )
  ```

**清理**
- `onBeforeUnmount` 中清理 tile manager 中相关图层状态（遍历 `activeLayers` 中的天气图层调用 `weatherTileManager.clearLayer`）。

#### 3.3 改造 `Code/frontend/src/components/LayerSidebar.vue`

**修改 `addCatalogItem`**
- 对天气图层不再调用 `runWorkflowForCatalog`：
  ```ts
  function addCatalogItem(catalogId: string, isAdminBoundary = false) {
    layersStore.addLayer(catalogId, isAdminBoundary)
    if (!isAdminBoundary && layersStore.isWeatherEngineLayer(catalogId)) {
      // 不再自动跑 workflow；MapCanvas 会在地图就绪后通过 setViewport 拉取瓦片
      return
    }
  }
  ```
- 移除或调整 library 卡片中的工作流状态徽标逻辑：天气图层不显示 running/queued/succeeded 等 job 徽标，改为显示 tile manager 状态或仅“已添加”。

#### 3.4 改造 `Code/frontend/src/components/InfoPanel.vue`

**修改 `weatherRenderHint`**
- 优先使用 `displayLayer.renderHint`：
  ```ts
  const weatherRenderHint = computed(
    () => displayLayer.value?.renderHint
      ?? jobLayer.value?.mapLayerPayload?.renderHint
      ?? props.pointWeather?.render_hint
      ?? null,
  )
  ```

**修改 `hasWeatherLayerAsset`**
- 同时判断 tile manager 中该图层已有缓存瓦片：
  ```ts
  import { useWeatherTileManager } from '../stores/weather-tile-manager'
  const weatherTileManager = useWeatherTileManager()
  const hasWeatherLayerAsset = computed(() => {
    if (!isRealtimeWeatherLayerId(displayLayer.value.catalogId)) return false
    const stats = weatherTileManager.getStats(displayLayer.value.catalogId)
    return stats.cached > 0 || stats.pending > 0
  })
  ```

**调整粒子流按钮可用性**
- `particleFlowButtonDisabled` 应基于 `hasWeatherLayerAsset` 的新定义，不再依赖 `geojsonUrl`。

### Stage 4：验证

- [ ] 后端：`pytest Code/backend/tests/test_weather_tile_service.py -v` 通过。
- [ ] 启动后端，手动访问 `/weather/tiles/wind-field/3/2/1?hour=12` 返回 GeoJSON。
- [ ] 前端：`vue-tsc --noEmit` 无类型错误。
- [ ] 浏览器验证：
  - 添加风场图层后 1 秒内粒子流正常，持续 10 秒无变短线/消失；
  - 缩放后粒子数量根据 zoom 调整，无突然稀疏；
  - 平移地图时新视口瓦片加载，旧数据平滑过渡，无覆盖闪烁；
  - 同时添加多个天气图层（风场 + 温度 + 降水），全局最多 4 个并发请求，无 429；
  - Network 面板可见 `/weather/tiles/...` 请求，且同一瓦片在 hour 不变时不重复请求。

## 5. 数据流示例

```
用户添加 wind-field 图层
  │
  ▼
LayerSidebar 只 addLayer，不再 submit workflow
  │
  ▼
MapCanvas watcher 发现可见天气图层 + 地图就绪
  │
  ▼
setMapViewport → layersStore.setMapViewport(...)
  │
  ▼
weatherTileManager.setViewport('wind-field', center, zoom, hour, model, bbox)
  │
  ├─ 计算视口 z/x/y（如 z=5, x=25..27, y=12..14）
  ├─ generation++，取消不在集合内的 pending 请求
  └─ 将缺失瓦片以 priority=0 入队，调用 drainQueue()
       │
       ▼
  全局 4 槽位拉取 /weather/tiles/wind-field/{z}/{x}/{y}?hour=12
       │
       ▼
  瓦片返回 → 存入缓存 → dataVersion++ → 触发 MapCanvas sync
       │
       ▼
  syncWeatherOverlay → resolveAllWeatherOverlayStates
       │
       ▼
  weatherTileManager.getMergedGeojsonForViewport('wind-field')
       │
       ▼
  weather-tile-utils.mergeWeatherTiles 合并可见瓦片、去重
       │
       ▼
  syncWindParticleFlow 用合并 GeoJSON 创建/更新 WindParticleCanvas
```

## 6. 验证步骤（可执行清单）

1. **后端单元测试**
   ```powershell
   cd Code/backend
   pytest tests/test_weather_tile_service.py -v
   ```
2. **后端冒烟测试**
   ```powershell
   curl "http://localhost:8000/weather/tiles/wind-field/3/2/1?hour=12"
   ```
3. **前端类型检查**
   ```powershell
   cd Code/frontend
   npx vue-tsc --noEmit
   ```
4. **前端运行时观察**
   - 打开浏览器 DevTools Network，过滤 `weather/tiles`；
   - 添加 `wind-field`，确认请求 URL 为 `/weather/tiles/wind-field/{z}/{x}/{y}`；
   - 连续缩放/平移，观察并发请求数 ≤ 4；
   - 观察 Console `[WeatherTileManager]` 日志，确认 generation 不匹配的结果被丢弃。

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 后端 `fetch_grid_forecast` 在瓦片边缘生成重复点，合并去重后仍可能缺失 | 视觉拼接缝 | 统一 `zoom_to_resolution` 表，保证相邻瓦片格网对齐；去重键使用 0.001° 量化。 |
| 快速缩放导致大量瓦片请求积压 | 卡顿/429 | generation 机制丢弃过期结果；`AbortController` 取消不需要的请求；全局 4 槽位限制并发。 |
| 用户跨日界线拖动（renderWorldCopies） | 粒子流/风羽位置偏移 | 瓦片坐标归一化到主世界，feature 坐标不越界；canvas 渲染复用已有的 world-wrap 处理。 |
| 旧工作流逻辑残留导致重复拉取 | 资源浪费 | 在 `stores/layers/index.ts` 中彻底删除旧虚拟瓦片状态与方法。 |
| 非天气图层渲染被误改 | 回归 | `resolveAllWeatherOverlayStates` 中保留非天气图层的原分支，仅天气图层走 tile manager。 |
