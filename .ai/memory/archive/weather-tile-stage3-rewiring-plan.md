# 天气图层标准瓦片渲染 Stage 3 接入计划

## 1. 摘要（Summary）

当前天气图层显示异常（首次加载正常、缩放后线条稀疏/忽然变化）的根因是：**新旧两条数据路径并存**。旧路径通过 `stores/layers/index.ts` 的虚拟瓦片 + `/workflow-runs` 拉取并合并 GeoJSON；新路径通过 `weatherTileManager` 请求后端 `/weather/tiles/{z}/{x}/{y}`。由于 Stage 3 接入未完成，MapCanvas 仍从 `jobLayer.layerAssets` 取数据，导致工作流结果与瓦片结果互相覆盖。

本计划目标：**彻底关闭天气图层的 workflow 自动拉取，全面切换到后端标准瓦片服务 + 前端 `weatherTileManager` 调度**，解决缩放/移动时的数据冲突、并发与拼接问题。

## 2. 现状分析（Current State Analysis）

### 2.1 已完成（无需改动）

| 文件 | 状态 | 说明 |
|------|------|------|
| `Code/backend/app/weatherengine/tile_service.py` | 已稳定 | Web Mercator z/x/y → bbox、分辨率表、LRU+Redis 缓存、4 槽位并发。 |
| `Code/backend/app/api/weather_tile_routes.py` | 已稳定 | `GET /weather/tiles/{layer_id}/{z}/{x}/{y}` 已注册。 |
| `Code/frontend/src/services/weather-tile-api.ts` | 已稳定 | `lngLatToTile`、`tilesInBounds`、`fetchWeatherTile`。 |
| `Code/frontend/src/services/weather-tile-utils.ts` | 已稳定 | `mergeWeatherTiles` 按量化经纬度 + height 去重。 |
| `Code/frontend/src/stores/weather-tile-manager.ts` | 已稳定 | 全局 4 槽位、图层内 priority 0/1、generation 丢弃、BFS 外扩。 |
| `Code/frontend/src/components/map/weather-render.ts` | 已稳定 | `WEATHER_RENDER_HINTS` + `buildDefaultWeatherRenderHint`。 |
| `Code/frontend/src/stores/layers/types.ts` | 已稳定 | `ActiveLayerDisplay.renderHint?: WeatherLayerRenderHint`。 |

### 2.2 未完成/待改造

| 文件 | 问题 |
|------|------|
| `Code/frontend/src/stores/layers/index.ts` | 仍保留旧虚拟瓦片状态与逻辑：`weatherTileCache`、`weatherPrefetchQueue`、`buildWeatherTileSpec`、`runWorkflowForCatalog` 天气分支、`refreshActiveWeatherWorkflows`、`handleViewportChange` 天气刷新等。天气图层仍通过 workflow 拉取。 |
| `Code/frontend/src/components/MapCanvas.vue` | `resolveAllWeatherOverlayStates` 仍从 `layer.jobLayer?.mapLayerPayload?.layerAssets` 取 GeoJSON，未接入 `weatherTileManager`。 |
| `Code/frontend/src/components/LayerSidebar.vue` | `addCatalogItem` 对天气图层仍调用 `runWorkflowForCatalog`。 |
| `Code/frontend/src/components/InfoPanel.vue` | `hasWeatherLayerAsset` 仅判断 `geojsonUrl`；`weatherRenderHint` 未优先使用 `displayLayer.renderHint`；粒子流按钮可用性基于旧 asset 定义。 |

### 2.3 根因定位

- **数据冲突**：旧 workflow 路径提交的 bbox 随缩放变化，不同分辨率的数据被合并到同一 `jobLayer.mapLayerPayload.layerAssets.geojsonData`，覆盖新瓦片数据。
- **并发问题**：旧路径使用 `WEATHER_PREFETCH_CONCURRENCY=2` 的 workflow 预取，容易触发 429；新路径已有 4 槽位 HTTP 并发。
- **坐标系不一致**：旧虚拟瓦片使用自定义 bucket + bbox，新路径使用标准 Web Mercator，混用导致拼接误差。

## 3. 关键设计决策（Decisions）

1. **天气图层不再走 `/workflow-runs` 的 `analysis` 命令**：添加、视口变化、小时变化全部通过 `/weather/tiles/...` 拉取。
2. **点天气查询 `/weather/point` 保持现有 workflow 不变**（用户明确仅改造图层渲染）。
3. **并发模型沿用已确认的“全局 4 槽位 + 图层内优先级队列”**。
4. **移动/缩放冲突通过 `generation` + `AbortController` 解决**：已在 `weatherTileManager` 实现，只需确保 MapCanvas 正确监听 `dataVersion`。
5. **结果拼接沿用 `weather-tile-utils.ts` 的去重逻辑**。
6. **多个天气图层可共存**：不再限制“一个天气图层的自动渲染工作流”，但粒子流图层仍独占（`particleFlowCatalogId`）。

## 4. 实施步骤（Proposed Changes）

### 4.1 改造 `Code/frontend/src/stores/layers/index.ts`

**A. 删除旧虚拟瓦片状态与方法**

删除以下状态：
- `weatherTileCache`
- `weatherCatalogPrimaryTileKey`
- `weatherRunTileSpecs`
- `weatherPrefetchQueue`
- `weatherPrefetchActiveKeys`
- `weatherPrefetchBackoffUntil`
- `viewportDebounceTimer`（天气刷新专用部分，若 `setMapViewport` 不再触发 weather workflow 则可简化）
- `lastWorkflowSubmitTime`、`lastWorkflowBBox` 中仅用于天气刷新的部分（保留非天气图层使用时再决定）

删除以下常量/类型/函数：
- `WEATHER_REQUEST_WORLD_LAT_LIMIT`、`WEATHER_REQUEST_VIEWPORT_EXPANSION`、`WEATHER_REQUEST_TILE_STEP_RATIO`
- `WEATHER_PREFETCH_CONCURRENCY`、`WEATHER_PREFETCH_MAX_QUEUE`、`WEATHER_TILE_CACHE_MAX_PER_BUCKET`
- `WEATHER_REQUEST_BUCKETS`、`WeatherTileSpec`、`WeatherTileCacheEntry`
- `buildWeatherTileSpec`、`buildNeighborWeatherTileSpecs`、`resolvePrimaryWeatherTileSpec`、`buildDefaultViewportBBox`
- `getWeatherRequestBucket`、`snapRequestCenter`、`getBoundingBoxSpans`、`roundBboxCoordinate`、`areBoundingBoxesEqual`
- `getWeatherTileCacheKey`、`getWeatherTileCacheEntry`、`setWeatherTileCacheEntry`、`evictDistantWeatherTiles`
- `extractGeojsonDataFromJobLayer`、`buildMergedGeojsonForCatalog`、`applyMergedWeatherTileData`、`patchCatalogJobLayerGeojson`、`cacheWeatherTileJobLayer`
- `enqueueWeatherTilePrefetch`、`expandWeatherTilePrefetch`、`drainWeatherPrefetchQueue`、`trimWeatherPrefetchQueueForCatalog`、`pollHiddenWeatherTileRun`

删除/简化 `runWorkflowForCatalog` 中的天气分支：天气图层不再提交 analysis workflow。非天气图层或用户手动“运行工作流”时保留原逻辑。

清理 `interruptWorkflowForCatalog`、`refreshActiveWeatherWorkflows`、`handleViewportChange` 中仅用于天气刷新的分支。`setMapViewport` 不再触发天气 workflow 刷新。

**B. 接入 `weatherTileManager`**

- 引入：
  ```ts
  import { useWeatherTileManager } from '../../services/weather-tile-manager'
  import { buildDefaultWeatherRenderHint } from '../../components/map/weather-render'
  ```
- store 内实例化：
  ```ts
  const weatherTileManager = useWeatherTileManager()
  ```
- `addLayer`：对天气图层调用 `weatherTileManager.setLayerActive(catalogId, true)`。
- `removeLayer`：对天气图层调用 `weatherTileManager.clearLayer(catalogId)`。
- `toggleLayerVisibility`：对天气图层调用 `weatherTileManager.setLayerActive(catalogId, layer.visible)`。
- `setMapViewport`：更新 `currentMapCenter/BBox/Zoom` 后，对每个可见天气图层调用：
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
- `setCurrentHour`：小时变化时，对所有可见天气图层重新触发 `setViewport`。

**C. 扩展 `ActiveLayerDisplay` 的 `renderHint`**

在 `activeLayersDisplay` computed 中，为天气图层填充 `renderHint`：
```ts
renderHint: layer.isAdminBoundary
  ? undefined
  : (buildDefaultWeatherRenderHint(layer.catalogId) ?? layer.jobLayer?.mapLayerPayload?.renderHint),
```

**D. 保留非天气图层的 workflow 能力**

- `runWorkflowForCatalog` 对非天气图层保持原有逻辑。
- `isWeatherEngineLayer`、`supportsMapLayerResult`、`supportsViewportDrivenRefresh` 保留，但仅用于判断，不自动触发天气 workflow。

### 4.2 改造 `Code/frontend/src/components/MapCanvas.vue`

**A. 引入依赖**

```ts
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import { buildDefaultWeatherRenderHint } from './map/weather-render'
```

```ts
const weatherTileManager = useWeatherTileManager()
```

**B. 修改 `resolveAllWeatherOverlayStates`**

对每个可见图层：
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

**C. 修改 `syncWindParticleFlow`**

- 当 `geojsonData` 为内联数据时，判断内容是否变化（比较 feature 数量 + 采样 checksum），避免同一份数据反复触发 `updateGeoJSON` 导致粒子重置。
- 保持现有 `enableBarbLayer = paint_mode === 'barb'` 逻辑。

**D. 扩展 watcher**

在现有 watcher 数组中追加 `weatherTileManager.dataVersion`，使瓦片加载完成后触发 `scheduleSyncWeatherOverlay()`：
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

**E. 清理**

`onBeforeUnmount` 中遍历 `activeLayers` 中的天气图层调用 `weatherTileManager.clearLayer`。

### 4.3 改造 `Code/frontend/src/components/LayerSidebar.vue`

**A. 修改 `addCatalogItem`**

天气图层不再调用 `runWorkflowForCatalog`：
```ts
function addCatalogItem(catalogId: string, isAdminBoundary = false) {
  layersStore.addLayer(catalogId, isAdminBoundary)
  if (!isAdminBoundary && layersStore.isWeatherEngineLayer(catalogId)) {
    // 不再自动跑 workflow；MapCanvas 会在地图就绪后通过 setViewport 拉取瓦片
    return
  }
}
```

**B. 调整 library 卡片状态徽标**

天气图层不显示 running/queued/succeeded 等 job 徽标，改为显示“已添加 ✓”。非天气图层保留原徽标逻辑。

### 4.4 改造 `Code/frontend/src/components/InfoPanel.vue`

**A. 修改 `weatherRenderHint`**

优先使用 `displayLayer.renderHint`：
```ts
const weatherRenderHint = computed(
  () => displayLayer.value?.renderHint
    ?? jobLayer.value?.mapLayerPayload?.renderHint
    ?? props.pointWeather?.render_hint
    ?? null,
)
```

**B. 修改 `hasWeatherLayerAsset`**

同时判断 tile manager 中该图层已有缓存瓦片：
```ts
import { useWeatherTileManager } from '../stores/weather-tile-manager'
const weatherTileManager = useWeatherTileManager()
const hasWeatherLayerAsset = computed(() => {
  if (!isRealtimeWeatherLayerId(displayLayer.value.catalogId)) return false
  const stats = weatherTileManager.getStats(displayLayer.value.catalogId)
  return stats.cached > 0 || stats.pending > 0
})
```

**C. 调整粒子流按钮可用性**

`particleFlowButtonDisabled` 基于新的 `hasWeatherLayerAsset`，不再依赖 `geojsonUrl`。

### 4.5 后端验证（无需改动，仅验证）

- 确认 `tile_service.py` 的 `zoom_to_resolution` 表与前端 `tilesInBounds` 计算的瓦片对齐。
- 确认 `weather_tile_routes.py` 返回 `application/geo+json` 并注入 `_tile_meta`。

## 5. 假设与依赖（Assumptions & Dependencies）

- `weatherTileManager` 的 `setViewport` 在视口变化时会被调用（依赖 `MapCanvas` 的 `syncMapViewportToStore`）。
- 后端 `/weather/tiles/...` 在开发环境下通过 Vite proxy 可达。
- 粒子流独占逻辑保持不变：同一时间只启用一个风场图层的粒子流。
- 非天气图层（如 `lab-output`）的 workflow 逻辑不受本次改造影响。

## 6. 验证步骤（Verification）

### 6.1 后端单元测试

```powershell
cd Code/backend
pytest tests/test_weather_tile_service.py -v
```

### 6.2 后端冒烟测试

```powershell
curl "http://localhost:8000/weather/tiles/wind-field/3/2/1?hour=12"
```

### 6.3 前端类型检查

```powershell
cd Code/frontend
npx vue-tsc --noEmit
```

### 6.4 浏览器运行时验证

- 添加 `wind-field` 图层后 1 秒内粒子流正常，持续 10 秒无变短线/消失。
- 缩放后粒子数量根据 zoom 调整，无突然稀疏。
- 平移地图时新视口瓦片加载，旧数据平滑过渡，无覆盖闪烁。
- 同时添加多个天气图层（风场 + 温度 + 降水），Network 面板中 `/weather/tiles/...` 并发请求数 ≤ 4。
- Network 面板中同一瓦片在 hour 不变时不重复请求。
- Console 中 `[WeatherTileManager]` 日志显示 generation 不匹配的结果被丢弃。
- 添加天气图层后不再产生 `/workflow-runs` 的 `analysis` 请求。

## 7. 风险与缓解（Risks & Mitigations）

| 风险 | 影响 | 缓解 |
|------|------|------|
| 旧 workflow 逻辑残留导致重复拉取 | 资源浪费、数据覆盖 | 彻底删除 `stores/layers/index.ts` 中的旧虚拟瓦片状态与方法。 |
| 非天气图层渲染被误改 | 回归 | `resolveAllWeatherOverlayStates` 中保留非天气图层的原分支。 |
| 快速缩放导致大量瓦片请求积压 | 卡顿/429 | generation 机制 + AbortController + 全局 4 槽位。 |
| 粒子流在数据未就绪时启用 | 按钮可点击但无数据 | `hasWeatherLayerAsset` 改用 tile manager stats 判断。 |
| 多个天气图层的粒子流冲突 | 视觉异常 | 保留 `particleFlowCatalogId` 独占逻辑。 |
