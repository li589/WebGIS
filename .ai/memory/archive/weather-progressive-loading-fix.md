# 天气图层渐进式加载与平移中断修复计划

## Summary

将天气图层改造为 windy.com 式的渐进式瓦片加载系统：
1. 提交间隔从 5s 降为 2s
2. 视口优先加载 → 自动向外围扩展（BFS 环形扩散）
3. 平移时中断旧位置的外扩，保留已获取数据，从新位置继续同层级加载
4. 每个 zoom 桶允许多个并行瓦片拉取（并发数 3）
5. Canvas 渐进更新：新瓦片到达时不重置所有粒子，仅扩展网格

## Current State Analysis

### 现有瓦片缓存与合并系统（已具备基础）

- [index.ts:977-1002](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L977-L1002) `buildMergedGeojsonForCatalog` — 已支持合并同一 catalogId + zoomBucketKey 下的所有已成功瓦片，按坐标去重
- [index.ts:1004-1028](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L1004-L1028) `patchCatalogJobLayerGeojson` + `applyMergedWeatherTileData` — 将合并后的 GeoJSON 写入 jobLayer 的 `geojsonData`，触发响应式更新
- [index.ts:964-970](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L964-L970) `weatherTileCache` — Map 缓存，key = `catalogId:zoomBucketKey:snappedLng:snappedLat`，存储每个瓦片的 GeoJSON 数据
- [MapCanvas.vue:421](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/MapCanvas.vue#L421) `resolveAllWeatherOverlayStates` — 优先使用 `geojsonData`（内联合并数据），回退到 `geojsonUrl`

### 现有预取系统（需扩展）

- [index.ts:1149-1170](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L1149-L1170) `enqueueWeatherTilePrefetch` — 仅预取 1-2 个邻居瓦片
- [index.ts:294-298](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L294-L298) `getWeatherPrefetchNeighborLimit` — z0/z1 桶 1 个邻居，其他 2 个
- [index.ts:1086-1139](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L1086-L1139) `drainWeatherPrefetchQueue` — 并发数 `WEATHER_PREFETCH_CONCURRENCY = 1`，串行处理
- [index.ts:1069-1084](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L1069-L1084) `pollHiddenWeatherTileRun` — 静默轮询预取瓦片，完成后调用 `applyMergedWeatherTileData`

### 现有并发控制（需改造）

- [index.ts:1369-1371](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L1369-L1371) `runWorkflowForCatalog` — `activeWorkflowCatalogIds.has(catalogId)` 阻止同一 catalog 的新提交
- [index.ts:1611](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L1611) `refreshActiveWeatherWorkflows` — 同样跳过活跃工作流的图层
- [index.ts:1480-1491](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L1480-L1491) `cancelWorkflowRunForJob` — 已存在，调用后端 cancel API + 停止轮询 + 从 `activeWorkflowCatalogIds` 移除

### Canvas 渐进更新（需新增）

- [wind-particle-canvas.ts:618-629](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-particle-canvas.ts#L618-L629) `updateGeoJSON` — 完全重建网格 + `initParticles()` 重置所有粒子
- 每次新瓦片完成 → `applyMergedWeatherTileData` → 响应式触发 → `updateGeoJSON` → 粒子全部重置 → 视觉闪烁

### 后端能力（无需修改）

- [workflow_manager.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/weatherengine/workflow_manager.py) `WorkflowLifecycleManager` — 已支持优先级调度（VIEWPORT > SURROUNDING > BACKGROUND）和自动取消
- [grid_fetch.py](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/backend/app/weatherengine/nodes/grid_fetch.py) `GridFetchNode` — 已支持 bbox 参数化获取，`compute_dynamic_resolution` 根据 bbox 自动调整分辨率
- 后端 `/workflow-runs/{run_id}/cancel` API — 已存在，前端 `cancelWorkflowRun` 已封装

## Proposed Changes

### 变更 1: 提交间隔 5s → 2s

**文件**: `Code/frontend/src/stores/layers/index.ts`

```typescript
const WORKFLOW_REFRESH_MIN_INTERVAL_MS = 2000  // 最小重新提交间隔（2 秒）
```

**原因**: 用户要求 2s。后端已有 Open-Meteo API 429 指数退避重试（5 次，最小 5s 间隔），2s 前端间隔不会压垮后端。

---

### 变更 2: 预取并发数 1 → 3，预取策略改为 BFS 环形扩散

**文件**: `Code/frontend/src/stores/layers/index.ts`

**修改 2a — 并发数**:
```typescript
const WEATHER_PREFETCH_CONCURRENCY = 3  // 并行瓦片拉取数
```

**修改 2b — BFS 环形扩散**: 重写 `enqueueWeatherTilePrefetch` 和 `getWeatherPrefetchNeighborLimit`。

当前逻辑：仅预取 1-2 个直接邻居。
新逻辑：BFS 扩散 — 主瓦片完成后，将其 8 个邻居加入队列；每个邻居完成后，再将其未加载的邻居加入队列，直到覆盖整个 zoom 桶范围或达到队列上限。

```typescript
/** 预取队列最大长度（防止无限扩展） */
const WEATHER_PREFETCH_MAX_QUEUE_SIZE = 30

/** 每个瓦片完成后的扩散回调：将未加载的邻居加入队列 */
function expandWeatherTilePrefetch(catalogId: string, completedSpec: WeatherTileSpec) {
  if (completedSpec.tileKey.endsWith(':world')) return  // 全球瓦片不扩散
  const neighbors = buildNeighborWeatherTileSpecs(completedSpec)
  for (const spec of neighbors) {
    const existing = getWeatherTileCacheEntry(catalogId, spec)
    if (existing && (existing.status === 'queued' || existing.status === 'running' || existing.status === 'succeeded')) continue
    if (weatherPrefetchQueue.length >= WEATHER_PREFETCH_MAX_QUEUE_SIZE) break
    enqueueWeatherTilePrefetchSingle(catalogId, spec)
  }
}
```

**修改 2c — 预取完成后触发扩散**: 在 `pollHiddenWeatherTileRun` 中，瓦片成功后调用 `expandWeatherTilePrefetch`：

```typescript
// pollHiddenWeatherTileRun 中，succeeded 分支：
if (jobLayer.status === 'succeeded') {
  applyMergedWeatherTileData(catalogId, spec.zoomBucketKey)
  expandWeatherTilePrefetch(catalogId, spec)  // 新增：BFS 扩散
}
```

同理在 `syncWorkflowRunSnapshot` 中 primary 瓦片成功后也调用 `expandWeatherTilePrefetch`。

**修改 2d — 拆分 `enqueueWeatherTilePrefetch`**: 将当前函数拆为：
- `enqueueWeatherTilePrefetch(catalogId, primarySpec)` — 入口，仅用于 primary 瓦片首次扩散（保留兼容）
- `enqueueWeatherTilePrefetchSingle(catalogId, spec)` — 单个瓦片入队（去重检查 + 加入队列 + 触发 drain）

---

### 变更 3: 平移中断 + 数据保留 + 新位置重启

**文件**: `Code/frontend/src/stores/layers/index.ts`

**核心逻辑**: 在 `refreshActiveWeatherWorkflows` 中，当检测到同 zoom 桶但位置变化时：

1. **取消当前 primary 工作流**（如果在运行）：调用 `cancelWorkflowRunForJob`
2. **保留 `weatherTileCache` 中的所有已获取瓦片**（不做任何清理）
3. **清空预取队列**中该 catalog 的旧位置瓦片（`trimWeatherPrefetchQueueForCatalog`）
4. **提交新位置的 primary 工作流**
5. 新工作流完成后，`applyMergedWeatherTileData` 会自动合并旧+新瓦片数据

```typescript
async function refreshActiveWeatherWorkflows() {
  const activeWeatherLayers = activeLayers.value.filter(
    (layer) => supportsViewportDrivenRefresh(layer.catalogId) && layer.jobLayer,
  )
  const now = Date.now()
  const currentBBox = currentMapBBox.value
  for (const layer of activeWeatherLayers) {
    const primaryTileSpec = resolvePrimaryWeatherTileSpec(
      layer.catalogId, currentMapCenter.value, currentBBox, currentMapZoom.value,
    )
    const requestBBox = primaryTileSpec?.bbox ?? currentBBox
    const lastRequestBBox = lastWorkflowBBox.get(layer.catalogId)

    // snapped bbox 完全相同 → 跳过（位置没变）
    if (requestBBox && areBoundingBoxesEqual(lastRequestBBox, requestBBox)) continue

    // 正在提交 → 跳过
    if (submittingCatalogIds.has(layer.catalogId)) continue

    // 检查是否需要取消当前工作流（平移/缩放导致位置变化）
    const isActive = activeWorkflowCatalogIds.has(layer.catalogId)
    if (isActive) {
      // 同 zoom 桶但位置变了 → 中断当前工作流，保留数据，从新位置重启
      const lastTileKey = weatherCatalogPrimaryTileKey.get(layer.catalogId)
      const sameBucket = lastTileKey && primaryTileSpec && lastTileKey.startsWith(primaryTileSpec.zoomBucketKey)
      if (sameBucket) {
        // 平移：取消当前工作流 + 清空预取队列 + 保留缓存
        const activeJobId = jobLayers.value.find((item) =>
          activeLayers.value.some((l) => l.catalogId === layer.catalogId && l.jobLayer?.jobId === item.jobId)
        )?.jobId
        if (activeJobId) {
          await cancelWorkflowRunForJob(activeJobId, layer.catalogId)
        }
        trimWeatherPrefetchQueueForCatalog(layer.catalogId)
        // 不检查最小间隔，立即从新位置提交
      } else {
        // 缩放跨越桶边界 → 取消旧桶工作流 + 清空预取队列 + 保留缓存
        const activeJobId = jobLayers.value.find((item) =>
          activeLayers.value.some((l) => l.catalogId === layer.catalogId && l.jobLayer?.jobId === item.jobId)
        )?.jobId
        if (activeJobId) {
          await cancelWorkflowRunForJob(activeJobId, layer.catalogId)
        }
        trimWeatherPrefetchQueueForCatalog(layer.catalogId)
      }
    } else {
      // 无活跃工作流 → 检查最小间隔
      if (layer.jobLayer?.status === 'succeeded') {
        const lastSubmit = lastWorkflowSubmitTime.get(layer.catalogId) ?? 0
        const elapsed = now - lastSubmit
        if (elapsed < WORKFLOW_REFRESH_MIN_INTERVAL_MS) {
          if (!requestBBox || !isSignificantViewportChange(layer.catalogId, requestBBox)) continue
        }
      }
    }

    // 检查瓦片缓存命中
    if (primaryTileSpec) {
      const cachedPrimaryTile = getWeatherTileCacheEntry(layer.catalogId, primaryTileSpec)
      if (cachedPrimaryTile?.status === 'succeeded') {
        weatherCatalogPrimaryTileKey.set(layer.catalogId, primaryTileSpec.tileKey)
        lastWorkflowSubmitTime.set(layer.catalogId, Date.now())
        lastWorkflowBBox.set(layer.catalogId, primaryTileSpec.bbox)
        applyMergedWeatherTileData(layer.catalogId, primaryTileSpec.zoomBucketKey)
        expandWeatherTilePrefetch(layer.catalogId, primaryTileSpec)
        continue
      }
    }

    if (canRunCatalog(layer.catalogId)) {
      try {
        await runWorkflowForCatalog(layer.catalogId, { skipIfRequestBBoxUnchanged: true })
      } catch (error) {
        console.warn(`[LayersStore] Failed to refresh weather workflow for ${layer.catalogId}:`, error)
      }
    }
  }
}
```

**修改 3b — `runWorkflowForCatalog` 移除 `activeWorkflowCatalogIds` 阻塞**:

当前 L1370-1371：
```typescript
if (submittingCatalogIds.has(catalogId)) return
if (activeWorkflowCatalogIds.has(catalogId)) return  // ← 移除这行
```

改为：仅检查 `submittingCatalogIds`（防止重复提交同一请求），不再阻塞已有活跃工作流（由 `refreshActiveWeatherWorkflows` 负责取消旧工作流）。

**原因**: 用户要求"每个 zoom 一个工作流" + "多个并行拉取"。`activeWorkflowCatalogIds` 的阻塞语义与渐进式加载冲突。

---

### 变更 4: Canvas 渐进更新 — 不重置所有粒子

**文件**: `Code/frontend/src/components/map/wind-particle-canvas.ts`

**问题**: 当前 `updateGeoJSON` 调用 `initParticles()` 重置所有粒子到随机位置，每次新瓦片完成都会导致视觉闪烁。

**修改**: `updateGeoJSON` 改为渐进式更新：

```typescript
updateGeoJSON(geojson: WindGeoJSON): void {
  const featureCount = geojson?.features?.length ?? 0
  const newGrid = buildWindGridFromGeoJSON(geojson)
  if (!newGrid) {
    console.warn('[WindParticleCanvas] Failed to create grid from GeoJSON')
    return
  }

  const oldGrid = this.grid
  this.grid = newGrid
  this.updateCanvasBounds()

  if (!oldGrid) {
    // 首次加载：正常初始化粒子
    this.initParticles()
    return
  }

  // 渐进更新：检查新旧网格是否有重叠区域
  const overlapWest = Math.max(oldGrid.west, newGrid.west)
  const overlapEast = Math.min(oldGrid.east, newGrid.east)
  const overlapSouth = Math.max(oldGrid.south, newGrid.south)
  const overlapNorth = Math.min(oldGrid.north, newGrid.north)
  const hasOverlap = overlapWest < overlapEast && overlapSouth < overlapNorth

  if (hasOverlap) {
    // 保留重叠区域内的粒子，重置区域外的粒子到新网格范围内
    const targetCount = this.resolveParticleCountForZoom(this.map.getZoom())
    const retainedParticles = this.particles.filter(p =>
      p.lon >= newGrid.west && p.lon <= newGrid.east &&
      p.lat >= newGrid.south && p.lat <= newGrid.north
    )
    // 保留的粒子截断轨迹（坐标可能偏移）
    for (const p of retainedParticles) {
      p.trail = p.trail.length >= 2 ? p.trail.slice(-2) : p.trail
    }
    // 补充新粒子到目标数量
    this.particles = retainedParticles
    while (this.particles.length < targetCount) {
      this.particles.push(this.createRandomParticle())
    }
    // 如果粒子过多，截断
    if (this.particles.length > targetCount * 1.2) {
      this.particles = this.particles.slice(0, targetCount)
    }
  } else {
    // 无重叠（完全不同的区域）：全量重置
    this.initParticles()
  }
}

/** 创建单个随机粒子（从 initParticles 中提取） */
private createRandomParticle(): Particle {
  if (!this.grid) throw new Error('Grid not initialized')
  const { south, north, west, east } = this.grid
  const { offsetX, offsetY } = this.layout
  const dpr = this.pixelRatio
  const lat = south + Math.random() * (north - south)
  const lon = west + Math.random() * (east - west)
  const screen = this.map.project([lon + this.lonWrapOffset, lat])
  const x = (screen.x - offsetX) * dpr
  const y = (screen.y - offsetY) * dpr
  return {
    lat, lon,
    trail: [x, y],
    age: Math.floor(Math.random() * this.options.maxAge),
    maxAge: this.options.maxAge + Math.floor(Math.random() * MAX_AGE_RANDOM_RANGE),
  }
}
```

**同步修改**: `initParticles` 改为调用 `createRandomParticle`：

```typescript
private initParticles(): void {
  if (!this.grid) return
  this.particles = []
  for (let i = 0; i < this.options.particleCount; i++) {
    this.particles.push(this.createRandomParticle())
  }
  // ... console.log ...
}
```

**同样修改 `wind-barb-layer.ts` 和 `wind-contour-layer.ts` 的 `updateGeoJSON`**: 这两个层的 `updateGeoJSON` 已经是全量替换（`loadData` + `updateLayout` + `draw`），不需要渐进更新，因为它们不是动画态的。只需确保 `draw` 在新数据加载后正确重绘即可。无需修改。

---

### 变更 5: 瓦片缓存淘汰策略

**文件**: `Code/frontend/src/stores/layers/index.ts`

**问题**: BFS 扩散会持续加载瓦片，缓存无限增长。需要淘汰远离当前视口的旧瓦片。

**修改**: 在 `expandWeatherTilePrefetch` 中，当缓存超过阈值时，淘汰离当前视口最远的瓦片：

```typescript
/** 每个 catalogId + zoomBucketKey 的最大缓存瓦片数 */
const WEATHER_TILE_CACHE_MAX_PER_BUCKET = 50

function evictDistantWeatherTiles(catalogId: string, zoomBucketKey: string, currentCenter: { lng: number; lat: number }) {
  const entries: Array<{ key: string; entry: WeatherTileCacheEntry; distance: number }> = []
  for (const [key, entry] of weatherTileCache) {
    if (entry.catalogId !== catalogId || entry.spec.zoomBucketKey !== zoomBucketKey) continue
    if (entry.status === 'queued' || entry.status === 'running') continue  // 不淘汰进行中的
    const dx = entry.spec.center.lng - currentCenter.lng
    const dy = entry.spec.center.lat - currentCenter.lat
    entries.push({ key, entry, distance: dx * dx + dy * dy })
  }
  if (entries.length <= WEATHER_TILE_CACHE_MAX_PER_BUCKET) return
  // 按距离降序排列，淘汰最远的
  entries.sort((a, b) => b.distance - a.distance)
  const toEvict = entries.length - WEATHER_TILE_CACHE_MAX_PER_BUCKET
  for (let i = 0; i < toEvict; i++) {
    weatherTileCache.delete(entries[i].key)
  }
}
```

在 `expandWeatherTilePrefetch` 开头调用：
```typescript
evictDistantWeatherTiles(catalogId, completedSpec.zoomBucketKey, completedSpec.center)
```

---

### 变更 6: `syncWorkflowRunSnapshot` 中 primary 瓦片成功后触发 BFS 扩散

**文件**: `Code/frontend/src/stores/layers/index.ts`

当前 L1250-1252：
```typescript
if (tileRunSpec.primary) {
  enqueueWeatherTilePrefetch(catalogId, tileRunSpec.spec)
}
```

改为：
```typescript
if (tileRunSpec.primary) {
  expandWeatherTilePrefetch(catalogId, tileRunSpec.spec)
}
```

同样在 `runWorkflowForCatalog` L1415 的缓存命中分支：
```typescript
enqueueWeatherTilePrefetch(catalogId, primaryTileSpec)
```
改为：
```typescript
expandWeatherTilePrefetch(catalogId, primaryTileSpec)
```

---

## Assumptions & Decisions

1. **纯前端修改，不改后端** — 后端 `GridFetchNode` 已支持 bbox 参数化获取，`WorkflowLifecycleManager` 已支持取消，`/workflow-runs/{run_id}/cancel` API 已存在。前端通过提交多个独立工作流实现并行拉取。
2. **`activeWorkflowCatalogIds` 语义改变** — 不再阻塞新提交，仅用于跟踪活跃工作流以便取消。由 `refreshActiveWeatherWorkflows` 负责决定何时取消旧工作流。
3. **BFS 扩散上限 30 个队列** — 防止无限扩展。每个瓦片完成后触发下一环扩散，自然形成 BFS。
4. **缓存上限 50 瓦片/桶** — 超过时淘汰离视口最远的已成功瓦片。进行中的瓦片不淘汰。
5. **Canvas 渐进更新保留重叠区域粒子** — 仅重置区域外的粒子，避免视觉闪烁。完全不同区域时全量重置。
6. **风羽和等值线层不改 `updateGeoJSON`** — 它们不是动画态的，全量替换 + 重绘即可，无闪烁问题。
7. **旋转/俯视兼容** — `map.project()` 和 `computeCanvasLayout` 已正确处理 pitch/bearing，`lonWrapOffset` 不影响投影本身。
8. **z0（全球）瓦片不扩散** — 全球瓦片 `tileKey` 以 `:world` 结尾，`expandWeatherTilePrefetch` 直接返回。

## Verification Steps

1. **TypeScript 编译**: `cd Code/frontend && npx vue-tsc --noEmit`
2. **2s 间隔测试**: 缩放后观察控制台 `[LayersStore] runWorkflowForCatalog` 日志，确认约 2s 后提交
3. **BFS 扩散测试**: 添加风场图层后，观察控制台日志确认瓦片从视口中心向外环形加载（邻居 → 邻居的邻居）
4. **平移中断测试**: 平移地图（不缩放），确认：
   - 旧工作流被取消（日志出现 `Cancelled` ）
   - 已有粒子流不消失（缓存数据保留）
   - 新位置工作流在 2s 内提交
   - 新瓦片完成后粒子流扩展到新区域
5. **缩放切换桶测试**: 从 z3 缩放到 z5，确认旧桶工作流取消，新桶工作流启动
6. **渐进更新测试**: 新瓦片完成时观察粒子流，确认不全部闪烁重置（仅边缘扩展）
7. **并发测试**: 观察网络面板，确认同时有 3 个 `/workflow-runs` POST 请求
8. **缓存淘汰测试**: 持续平移使缓存超过 50，确认旧瓦片被淘汰（控制台日志）
