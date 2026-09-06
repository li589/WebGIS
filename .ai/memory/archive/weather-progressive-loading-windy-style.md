# 天气图层 windy.com 式渐进加载改造计划

## 目标

将天气图层改造为类似 windy.com 的渐进式加载体验：视口优先 → 自动外扩 → 平移中断但保留数据 → 新位置继续渲染。

## 当前状态分析

### 前端 `index.ts` 关键问题

1. **`activeWorkflowCatalogIds`** **阻塞**（L596, L1371, L1611）：工作流运行期间，同一 catalogId 无法提交新工作流。平移时旧工作流阻塞新位置数据获取。
2. **提交间隔 5s**（L655 `WORKFLOW_REFRESH_MIN_INTERVAL_MS`）：用户要求 2s。
3. **预取并发 1**（L152 `WEATHER_PREFETCH_CONCURRENCY`）：仅 1 个并行拉取，外扩速度慢。
4. **预取策略仅 1-2 个邻居**（L1149 `enqueueWeatherTilePrefetch`）：非 BFS 环形扩散，无法像底图瓦片那样持续外扩。
5. **无缓存淘汰**：`weatherTileCache`（L668）无上限，长时间使用会内存膨胀。
6. **min 间隔检查仅对 succeeded 状态生效**（L1615）：running 状态被 `activeWorkflowCatalogIds` 跳过，移除阻塞后需调整。
7. **min 间隔不满足时无重试调度**（L1618-1621）：如果 2s 间隔未满足，直接 `continue` 跳过，更新丢失。

### 粒子 Canvas `wind-particle-canvas.ts` 关键问题

1. **`updateGeoJSON`** **全量重置粒子**（L652-663）：每次合并 GeoJSON 更新都调用 `initParticles()`，所有粒子重新随机分布。新瓦片到达时，已有数据区域粒子被无谓重置，造成视觉闪烁。

### 后端能力（已具备，无需修改）

* `WorkflowLifecycleManager`（`workflow_manager.py`）：支持优先级调度和 `cancel_callback`。

* `GridFetchNode`（`grid_fetch.py`）：支持 `viewport_bbox` / `bbox` 参数化获取，`compute_dynamic_resolution` 自动调整分辨率。

* `cancelWorkflowRun` API（`runtime-api.ts`）：已封装 `POST /workflow-runs/{runId}/cancel`。

## 变更清单

### 变更 1：提交间隔 5s → 2s

**文件**: `Code/frontend/src/stores/layers/index.ts`

**修改**: L655 `WORKFLOW_REFRESH_MIN_INTERVAL_MS` 从 `5000` 改为 `2000`。

**原因**: 用户要求同一图层两次提交最小间隔为 2s。

***

### 变更 2：预取并发 1 → 3 + BFS 环形扩散

**文件**: `Code/frontend/src/stores/layers/index.ts`

**修改内容**:

1. L152 `WEATHER_PREFETCH_CONCURRENCY` 从 `1` 改为 `3`。

2. 删除 L153-154 `WEATHER_PREFETCH_COARSE_NEIGHBOR_LIMIT` 和 `WEATHER_PREFETCH_DEFAULT_NEIGHBOR_LIMIT`（BFS 不需要固定邻居数限制）。

3. 删除 `getWeatherPrefetchNeighborLimit` 函数（L294-298）。

4. 新增常量 `WEATHER_PREFETCH_MAX_QUEUE = 30`（BFS 队列上限，防止无限扩散）。

5. 重写 `enqueueWeatherTilePrefetch`（L1149-1166）为 BFS 扩散入口：

   * 不再限制邻居数量，而是将 8 个邻居全部入队（跳过已缓存/已排队的）。

   * 调用 `void drainWeatherPrefetchQueue()` 启动并行拉取。

6. 新增 `expandWeatherTilePrefetch(catalogId, completedSpec)` 函数：

   * 当一个瓦片成功后调用，生成该瓦片的 8 个邻居 spec。

   * 跳过已 succeeded / queued / running / 已在队列中的瓦片。

   * 如果队列总长 < `WEATHER_PREFETCH_MAX_QUEUE`，将邻居入队。

   * 调用 `void drainWeatherPrefetchQueue()`。

   * 这是 BFS 的核心：每个完成的瓦片触发其邻居入队，形成环形扩散。

**原因**: 像 windy.com / 底图瓦片一样持续向外扩散加载，而非仅预取 1-2 个邻居。

***

### 变更 3：移除 `activeWorkflowCatalogIds` 阻塞 + 平移中断 + 数据保留

**文件**: `Code/frontend/src/stores/layers/index.ts`

**修改内容**:

1. **新增** **`interruptWorkflowForCatalog(catalogId)`** **函数**（放在 `runWorkflowForCatalog` 之前）：

   ```typescript
   function interruptWorkflowForCatalog(catalogId: string) {
     // 查找该 catalogId 的活跃 jobId（非终态）
     const activeJobLayer = jobLayers.value.find((item) =>
       activeLayers.value.some((l) => l.catalogId === catalogId && l.jobLayer?.jobId === item.jobId)
       && !isTerminalStatus(item.status)
     )
     const activeJobId = activeJobLayer?.jobId
       ?? weatherCatalogPrimaryTileKey.get(catalogId) // fallback
     // 从 weatherRunTileSpecs 找到 primary run
     let runJobId: string | null = null
     for (const [jid, spec] of weatherRunTileSpecs.entries()) {
       if (spec.catalogId === catalogId && spec.primary) { runJobId = jid; break }
     }
     const targetJobId = runJobId ?? activeJobId
     if (targetJobId) {
       stopWorkflowPolling(targetJobId)
       activeWorkflowCatalogIds.delete(catalogId)
       weatherRunTileSpecs.delete(targetJobId)
       // fire-and-forget 取消 API 调用，不阻塞新提交
       void cancelWorkflowRun(targetJobId).catch(() => {})
     }
     // 清空预取队列（旧位置的待拉取瓦片不再需要）
     trimWeatherPrefetchQueueForCatalog(catalogId)
     // 注意：不清空 weatherTileCache —— 已成功的数据保留！
   }
   ```

2. **`runWorkflowForCatalog`（L1369-1478）修改**:

   * **删除 L1371** `if (activeWorkflowCatalogIds.has(catalogId)) return`

   * 在缓存命中检查之后、`submitWorkflow` 之前，调用 `interruptWorkflowForCatalog(catalogId)`

   * 保留 `activeWorkflowCatalogIds.add(catalogId)` 在提交成功后

3. **`refreshActiveWeatherWorkflows`（L1592-1633）修改**:

   * **删除 L1611** `if (activeWorkflowCatalogIds.has(layer.catalogId)) continue`

   * **修改 min 间隔检查**（L1615-1621）：移除 `if (layer.jobLayer?.status === 'succeeded')` 条件，改为对所有状态检查 min 间隔。如果间隔未满足且非显著变化，调度一次性重试定时器：

     ```typescript
     const lastSubmit = lastWorkflowSubmitTime.get(layer.catalogId) ?? 0
     const elapsed = now - lastSubmit
     if (elapsed < WORKFLOW_REFRESH_MIN_INTERVAL_MS) {
       if (!requestBBox || !isSignificantViewportChange(layer.catalogId, requestBBox)) {
         // 调度重试：在剩余时间 + 100ms 后重新触发
         const remaining = WORKFLOW_REFRESH_MIN_INTERVAL_MS - elapsed
         if (viewportDebounceTimer.value === null) {
           viewportDebounceTimer.value = window.setTimeout(() => {
             viewportDebounceTimer.value = null
             void refreshActiveWeatherWorkflows()
           }, remaining + 100)
         }
         continue
       }
     }
     ```

4. **`retryWorkflowRunForJob`（L1493-1523）修改**:

   * **删除 L1495** `if (activeWorkflowCatalogIds.has(catalogId)) return`（改为先 interrupt 再 retry，或直接移除阻塞）

**原因**:

* 移除阻塞后，平移时可以立即中断旧工作流、提交新位置工作流。

* `weatherTileCache` 不清空，已成功的瓦片数据保留，合并渲染时复用。

* 重试调度确保 2s 间隔不会导致更新丢失。

***

### 变更 4：Canvas 渐进更新（保留重叠区域粒子）

**文件**: `Code/frontend/src/components/map/wind-particle-canvas.ts`

**修改内容**:

1. **提取** **`createRandomParticle()`** **方法**（从 `initParticles` L441-453 中提取）：

   ```typescript
   private createRandomParticle(): Particle {
     const { south, north, west, east } = this.grid!
     const { offsetX, offsetY } = this.layout
     const dpr = this.pixelRatio
     const lat = south + Math.random() * (north - south)
     const lon = west + Math.random() * (east - west)
     const screen = this.map.project([lon + this.lonWrapOffset, lat])
     const x = (screen.x - offsetX) * dpr
     const y = (screen.y - offsetY) * dpr
     return {
       lat, lon, trail: [x, y],
       age: Math.floor(Math.random() * this.options.maxAge),
       maxAge: this.options.maxAge + Math.floor(Math.random() * MAX_AGE_RANDOM_RANGE),
     }
   }
   ```

2. **`initParticles`（L435-461）改用** **`createRandomParticle`**：

   ```typescript
   private initParticles(): void {
     if (!this.grid) return
     const targetCount = this.resolveParticleCountForZoom(this.map.getZoom())
     this.options.particleCount = targetCount
     this.particles = []
     for (let i = 0; i < targetCount; i++) {
       this.particles.push(this.createRandomParticle())
     }
   }
   ```

3. **新增** **`progressiveUpdateParticles(targetCount)`** **方法**：

   ```typescript
   private progressiveUpdateParticles(targetCount: number): void {
     if (!this.grid) return
     const { south, north, west, east } = this.grid
     // 重置超出新网格范围的粒子
     for (const p of this.particles) {
       if (p.lat < south || p.lat > north || p.lon < west || p.lon > east) {
         this.resetParticle(p)
       }
     }
     // 调整粒子数量
     if (this.particles.length < targetCount) {
       while (this.particles.length < targetCount) {
         this.particles.push(this.createRandomParticle())
       }
     } else if (this.particles.length > targetCount) {
       this.particles.length = targetCount
     }
     this.options.particleCount = targetCount
   }
   ```

4. **`updateGeoJSON`（L652-663）改为渐进更新**：

   ```typescript
   updateGeoJSON(geojson: WindGeoJSON): void {
     const oldGrid = this.grid
     this.grid = buildWindGridFromGeoJSON(geojson)
     if (this.grid) {
       this.updateCanvasBounds()
       const targetCount = this.resolveParticleCountForZoom(this.map.getZoom())
       if (!oldGrid) {
         this.initParticles()
       } else {
         this.progressiveUpdateParticles(targetCount)
       }
     }
   }
   ```

**原因**: 新瓦片到达时，重叠区域粒子保留（不闪烁），仅重置区域外粒子。渐进式更新视觉效果更平滑。

***

### 变更 5：瓦片缓存淘汰策略

**文件**: `Code/frontend/src/stores/layers/index.ts`

**修改内容**:

新增 `evictDistantWeatherTiles(catalogId, currentCenter, currentZoomBucketKey)` 函数：

```typescript
const WEATHER_TILE_CACHE_MAX_PER_BUCKET = 50

function evictDistantWeatherTiles(catalogId: string, currentCenter: { lng: number; lat: number }, currentZoomBucketKey: string) {
  // 1. 淘汰其他 zoom bucket 的瓦片（只保留当前 bucket）
  for (const [key, entry] of weatherTileCache.entries()) {
    if (entry.catalogId === catalogId && entry.spec.zoomBucketKey !== currentZoomBucketKey) {
      weatherTileCache.delete(key)
    }
  }
  // 2. 当前 bucket 超过上限时，按距离淘汰最远的瓦片
  const sameBucketEntries: Array<{ key: string; entry: WeatherTileCacheEntry; dist: number }> = []
  for (const [key, entry] of weatherTileCache.entries()) {
    if (entry.catalogId !== catalogId || entry.spec.zoomBucketKey !== currentZoomBucketKey) continue
    if (entry.status !== 'succeeded') continue  // 只淘汰已完成的，不淘汰进行中的
    const dLng = entry.spec.center.lng - currentCenter.lng
    const dLat = entry.spec.center.lat - currentCenter.lat
    const dist = dLng * dLng + dLat * dLat
    sameBucketEntries.push({ key, entry, dist })
  }
  if (sameBucketEntries.length <= WEATHER_TILE_CACHE_MAX_PER_BUCKET) return
  sameBucketEntries.sort((a, b) => b.dist - a.dist)
  const toEvict = sameBucketEntries.length - WEATHER_TILE_CACHE_MAX_PER_BUCKET
  for (let i = 0; i < toEvict; i++) {
    weatherTileCache.delete(sameBucketEntries[i].key)
  }
}
```

**调用时机**: 在 `syncWorkflowRunSnapshot`（L1248 附近）和 `pollHiddenWeatherTileRun`（L1077 附近）瓦片成功后调用。

**原因**: 防止长时间使用导致 `weatherTileCache` 无限膨胀。优先淘汰其他 zoom bucket 和远距离瓦片。

***

### 变更 6：工作流成功后触发 BFS 扩散

**文件**: `Code/frontend/src/stores/layers/index.ts`

**修改内容**:

1. **`syncWorkflowRunSnapshot`（L1244-1253）修改**：在 `enqueueWeatherTilePrefetch` 调用处替换为 `expandWeatherTilePrefetch`：

   ```typescript
   if (mergedJobLayer.status === 'succeeded') {
     weatherCatalogPrimaryTileKey.set(catalogId, tileRunSpec.spec.tileKey)
     applyMergedWeatherTileData(catalogId, tileRunSpec.spec.zoomBucketKey)
     evictDistantWeatherTiles(catalogId, currentMapCenter.value, tileRunSpec.spec.zoomBucketKey)
     if (tileRunSpec.primary) {
       expandWeatherTilePrefetch(catalogId, tileRunSpec.spec)  // BFS 扩散
     } else {
       expandWeatherTilePrefetch(catalogId, tileRunSpec.spec)  // 邻居完成后继续扩散
     }
   }
   ```

2. **`pollHiddenWeatherTileRun`（L1077-1079）修改**：在 succeeded 分支添加 BFS 扩散和淘汰：

   ```typescript
   if (jobLayer.status === 'succeeded') {
     applyMergedWeatherTileData(catalogId, spec.zoomBucketKey)
     evictDistantWeatherTiles(catalogId, currentMapCenter.value, spec.zoomBucketKey)
     expandWeatherTilePrefetch(catalogId, spec)  // 预取瓦片成功后继续 BFS 扩散
   }
   ```

**原因**: 每个瓦片成功后触发其邻居入队，形成持续的外扩加载，实现 windy.com 式渐进覆盖。

***

## 旋转/俯视兼容性说明

MapLibre 的 `map.project()` 和 `map.getBounds()` 已自动处理 pitch（俯视）和 bearing（旋转）。`computeCanvasLayout` 中的 `lonWrapOffset` 也应用于所有 project 调用。本次改造不引入新的坐标转换逻辑，旋转/俯视兼容性由现有机制保证。高 pitch 下可见区域为梯形，canvas 可能无法完全覆盖——这是现有限制，本次不处理。

## Assumptions & Decisions

1. **`activeWorkflowCatalogIds`** **保留为跟踪集合**：不删除该 Set，只是移除其阻塞语义。仍用于跟踪哪个 catalogId 有活跃工作流，供 `interruptWorkflowForCatalog` 使用。
2. **BFS 队列上限 30**：防止用户长时间停留在高 zoom 时无限扩散。30 个瓦片已足够覆盖可见区域 + 周边缓冲。
3. **缓存淘汰上限 50/桶**：平衡内存和缓存命中率。50 个瓦片约覆盖中等 zoom 下的主要区域。
4. **`interruptWorkflowForCatalog`** **中 cancel API 为 fire-and-forget**：不等待取消完成就提交新工作流，避免延迟。后端会处理取消。
5. **min 间隔重试调度使用** **`viewportDebounceTimer`**：复用现有定时器，避免引入新变量。如果已有定时器在等待，不重复调度。
6. **`setMapViewport`** **中的** **`trimWeatherPrefetchQueueForCatalog`** **保留**：平移时立即停止旧位置预取，减少无效 API 调用。BFS 会从新位置重新扩散。

## Verification Steps

1. **TypeScript 编译验证**: `cd Code/frontend && npx vue-tsc --noEmit`，确保无类型错误。
2. **2s 间隔验证**: 快速连续平移两次，观察控制台 `[LayersStore] runWorkflowForCatalog` 日志，确认同一图层两次提交间隔 ≥ 2s。
3. **BFS 扩散验证**: 在中等 zoom（z3-z4）添加风场图层，观察控制台预取日志，确认瓦片从视口中心向外环形扩散加载，而非仅 1-2 个邻居。
4. **平移中断 + 数据保留验证**:

   * 在 zoom=4 添加风场图层，等待初始数据加载。

   * 平移到相邻区域，观察：旧工作流被取消（cancel API 调用），新工作流提交，但已加载区域的风场仍然显示（缓存命中）。

   * 观察控制台 `applyMergedWeatherTileData` 日志，确认合并的 features 数量随瓦片增加而增长。
5. **Canvas 渐进更新验证**:

   * 添加风场图层，等待粒子流出现。

   * 平移后新瓦片到达，观察粒子流不闪烁（重叠区域粒子保留），仅新区域生成新粒子。
6. **缓存淘汰验证**: 长时间使用后检查 `weatherTileCache.size`（通过控制台），确认不超过 50/桶。
7. **全球缩放验证**: zoom=0 添加风场图层，确认全球数据加载（z0 桶 = world 瓦片）。

