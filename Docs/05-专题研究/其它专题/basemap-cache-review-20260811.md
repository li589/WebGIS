# 底图显示与缓存泄漏专项检查报告

- 检查日期：2026-08-11
- **状态更新（2026-08-12）**：下文 P2 `softRequeueCounts` 泄漏已在 `dev` 提交 `2d71f3f` 修复；天地图街道现行为 **vec 底 + cva overlay**，服务端 UA=`CGDA-Backend/1.0`（见 `Docs/07-工程保障/UI优化与底图模块修复-2026-08-12.md`）。本文其余条目仍为当日静态审查快照，**不**自动代表当前代码。
- 范围：前端底图显示链路 + 瓦片/图层缓存
- 方式：仅静态代码审查，**未修改任何代码**（检查当日）
- 关键文件：
  - `Code/frontend/src/components/map/basemap-module.ts`（底图源/层管理、切换、错误熔断）
  - `Code/frontend/src/components/MapCanvas.vue`（地图实例生命周期、onMapLoad 初始化）
  - `Code/frontend/src/components/map/map-canvas-module-bundle.ts`（运行时 tileSourceId watch → 切换）
  - `Code/frontend/src/components/map/map-canvas-teardown-binder.ts`（卸载清理）
  - `Code/frontend/src/stores/weather-tile-manager.ts`（天气瓦片缓存调度）
  - `Code/frontend/src/stores/weather-tile-cache-trim.ts`（瓦片 LRU trim）
  - `Code/frontend/src/services/api-config.ts`（各 provider 瓦片配置）

## 结论速览

| 项 | 判定 | 说明 |
|---|---|---|
| 初始底图显示 | ✅ 正常 | `onMapLoad → switchTileSource` 将图层置为 `visible` |
| 运行时切换底图 | ✅ 正常 | `runtimeModule` watch → `scheduleTileSourceSwitch`（80ms 防抖）→ `switchTileSource` |
| 百度/高德等加密底图 | ✅ 正常 | `needsBackendTransform: true` 由后端统一瓦片代理处理，`tileSize` 均为 256 |
| 地图实例/WebGL 销毁 | ✅ 正常 | `onBeforeUnmount → teardownBinder.dispose() → map.remove()` |
| 天气瓦片缓存上限 | ✅ 有界 | 每图层 `MAX_LAYER_CACHE_TILES=128` + TTL + LRU + 视口 pinned 不驱逐 |
| **软重拉计数模块级泄漏** | 🔴 P2 | `softRequeueCounts` 在 `clearLayer` 时未清理，已删图层残留 key 永久累积 |
| overlay 源/层常驻不移除 | 🟡 P3 | 无 overlay 源或切到 `none` 时仅隐藏，永不 `removeSource/removeLayer` |
| 隐藏图层 tiles 缓存不释放 | 🟡 P3 | `setLayerActive(false)` 清空 pending 但保留 `state.tiles` 直至 `clearLayer` |
| source 复用不更新 tileSize/attribution | 🟡 P3 | 防御性：当前所有 provider 一致，不触发，但换非 256 源会错位 |

---

## 详细问题

### 🔴 P2 · `softRequeueCounts` 模块级 Map 在 `clearLayer` 时泄漏

**位置**：`weather-tile-manager.ts`
- 声明：`const softRequeueCounts = new Map<string, number>()`（行 265，模块级，跨图层/跨会话常驻）
- 写入：`scheduleSoftRequeue()` 第 1455 行 `softRequeueCounts.set(countKey, prev + 1)`，key 形如 `${layerId}:z{x}:x{x}:y{x}:h{x}`
- 删除点（仅 3 处）：`runGapSweep` 单 key 删除（行 564）、`setViewport` 在 zoom/model/provider 变化时按 `layerId:` 前缀删（行 922-924）、`retryLayerTiles` 按 `layerId:` 前缀删（行 1978）
- **`clearLayer()`（行 732-752）只清理了 `mergeCache`（行 748-750），遗漏 `softRequeueCounts`**

**影响**：图层被 `clearLayer` 删除后，其失败瓦片在 `softRequeueCounts` 中的 key（含该 `layerId` 前缀）**永不删除**。这些 key 含具体 z/x/y/h，单个图层可达（失败瓦片数）条；多个图层反复加载/卸载后，模块级 Map 持续累积，且没有任何触发删除的兜底。属**确认的内存泄漏**（量级取决于失败瓦片数，偏小但跨图层持续）。

**建议修复**（报告仅建议，未执行）：
```ts
// clearLayer() 中，合并缓存清理之后追加：
for (const key of Array.from(softRequeueCounts.keys())) {
  if (key.startsWith(`${layerId}:`)) softRequeueCounts.delete(key)
}
```

> 对比：`pendingRetryTimers`（同为模块级 Set）在 `clearLayer` 故意不清，依赖定时器回调触发后从 Set 删除，且回调通过 `generation`/`layerStates` 自检跳过已删图层、不持有图层状态引用，最终会释放——非泄漏。`softRequeueCounts` 则无任何触发清理路径，是真实泄漏点。

---

### 🟡 P3 · overlay 源/层隐藏但从不移除

**位置**：`basemap-module.ts`
- `syncOverlayLayer(cfg, false)`（行 55-60）在目标源无 `overlayUrlTemplate` 时仅 `hideOverlay()`（`setLayoutProperty('visibility','none')`），不 `removeLayer/removeSource`
- `switchTileSource('none')`（行 153-159）同样只隐藏，不移除
- 一旦某源带 overlay 被加载，`TILE_OVERLAY_SOURCE_ID` / `TILE_OVERLAY_LAYER_ID` 永久留在 `map` 内（即便后续切到无 overlay 源或 `none`）

**影响**：单元素常驻（1 个 raster source + 1 个 raster layer），内存影响极小，但属「创建后永不释放」的结构性问题。若后续叠加多种 annotation 源，会逐个累积。

**建议**：在 `hideOverlay` 或显式「无 overlay」分支中，当 `map.getLayer(TILE_OVERLAY_LAYER_ID)` 存在时 `removeLayer` + `removeSource`，而非仅隐藏。

---

### 🟡 P3 · 隐藏天气图层 `state.tiles` 缓存不释放

**位置**：`weather-tile-manager.ts` `setLayerActive(layerId, false)`（行 712-730）
- 隐藏时执行 `state.generation += 1`、取消并清空 `pending`、清 `dataEmptyScope`、`clearGapSweep`，但**刻意保留 `state.tiles`**（注释表明保留以「重新激活即时」）

**影响**：属于设计权衡，但频繁 hide/show 多个天气图层时，隐藏图层的 `state.tiles`（上限 128/层）会持续驻留内存，直到 `clearLayer` 才随 `layerStates.delete` 一起释放。长时间多图层切换场景下内存滞留可观。

**建议**（可选）：`setLayerActive(false)` 时若非立即再激活，可 `state.tiles.clear()`；或按 LRU 给隐藏图层缓存加总上限。当前非紧急。

---

### 🟡 P3 · source 复用路径不更新 `tileSize`/`attribution`/`maxzoom`/`scheme`（防御性）

**位置**：`basemap-module.ts`
- `switchTileSource`（行 150-190）：source 已存在时仅 `existingSource.setTiles([cfg.urlTemplate])`（行 166），只换 URL，不更新 `tileSize`/`attribution`/`maxzoom`/`scheme`
- `ensureTileLayer`（行 97-133）：source 已存在分支只确保 layer 存在，不重设 source 参数
- `retryTileLoad`（行 275-289）、`syncOverlayLayer`（行 62-66）的 overlay 源同理

**当前为何不触发**：`api-config.ts` 中**所有 provider 的 `tileSize` 均为 `256`，`scheme` 均为 `xyz`，`maxzoom` 均为 `18`**（含动态 `endpoint.tileSize`，行 727）。`setTiles` 不动 `tileSize` 在此配置下无副作用。

**风险**：一旦引入非 256 `tileSize`（如 512 矢量瓦片）或不同 `scheme` 的 provider，切换/重试时 raster source 的 `tileSize` 不会跟随更新，将出现**瓦片错位、缩放比例错误、地图整体偏移**等显示 bug。

**建议**：在 source 已存在分支中，除 `setTiles` 外，针对可变参数用 `setPaintProperty`/`map.getSource().tileSize = ...` 或重建 source（`removeSource`+`addSource`）确保参数同步；或在 `TileSourceConfig` 增加「切换时需重建 source」标记。

---

## 已确认正常（无 bug，附证据）

1. **初始底图显示**：`MapCanvas.vue` 行 402-403 `onMapLoad` 调 `switchTileSource(props.tileSourceId)`；该函数（行 112-130 创建图层默认 `visibility:'none'`，行 172-173 立即置 `visible`）→ 首屏底图正常显示。
2. **运行时切换**：`map-canvas-module-bundle.ts` 行 216-218 `onTileSourceChange → scheduleTileSourceSwitch`；`MapCanvas.vue` 行 374 `mapCanvasRuntimeModule.setupWatchers()` 支撑 watch；`scheduleTileSourceSwitch`（行 192-204）含 80ms 防抖 + `switchTileToken` 防止旧切换覆盖新切换。链路完整。
3. **百度/高德加密底图**：`api-config.ts` 百度条目 `needsBackendTransform: true`（行 604/621），`TileSourceConfig` 经 `/unified-tiles/{provider}/{z}/{x}/{y}` 统一后端代理转换，`scheme` 仍按 `xyz` 提供 URL，无标准坐标错位风险。
4. **地图实例/WebGL 销毁**：`MapCanvas.vue` 行 431-433 `onBeforeUnmount → teardownBinder.dispose()`；`teardown-binder.ts` 行 45 `resources.map?.remove()` 销毁 map 实例并释放 WebGL context + 所有事件监听（`lifecycle-binder` 注册的 `map.on('error'/'load')` 随之清理）。无实例泄漏。
5. **天气瓦片缓存有界**：`weather-tile-cache-trim.ts` `MAX_LAYER_CACHE_TILES=128`，`trimWeatherLayerTileCache` 先删远 zoom 瓦片、再 LRU 淘汰非视口 key；视口（pinned）瓦片永不驱逐，避免抖动重拉；`mergeCache` 跨层上限 8。无失控增长。

---

## 检查项清单

- [x] 初始底图是否显示
- [x] 运行时切换底图是否生效（防抖/旧切换覆盖）
- [x] 不同 provider（含百度/高德/Tianditu/Bing）坐标/尺寸一致性
- [x] 地图实例与 WebGL context 卸载销毁
- [x] 底图源/层事件监听解绑
- [x] 天气瓦片缓存上限与 LRU/TTL
- [x] 模块级缓存集合（softRequeueCounts / pendingRetryTimers / mergeCache / layerStates）的清理路径
- [x] overlay 标注源的生命周期
- [x] 错误熔断（handleTileError）阈值与误伤防护

> ~~本报告仅分析问题，未改动任何代码。是否需要按 P2 → P3 顺序进入修复？~~

---

## 修复记录（2026-08-11 17:38）

### ✅ P2 · `softRequeueCounts` 泄漏（已修）

**文件**：`Code/frontend/src/stores/weather-tile-manager.ts`
**改动**：`clearLayer()`（行 748-750 之后）追加 `softRequeueCounts` 按 `layerId:` 前缀清理，与 `mergeCache` 清理逻辑一致。

```diff
+    for (const key of Array.from(softRequeueCounts.keys())) {
+      if (key.startsWith(`${layerId}:`)) softRequeueCounts.delete(key)
+    }
```

### ✅ P3 · overlay 源/层常驻（已修）

**文件**：`Code/frontend/src/components/map/basemap-module.ts`
**改动**：`syncOverlayLayer` 在 `!overlayUrl`（完全无 overlay 配置）时主动 `removeLayer` + `removeSource`，而非仅隐藏。熔断场景（`!visible` 但 overlayUrl 存在）保留原 `hideOverlay` 行为。

### ⏭️ P3 · 隐藏图层 tiles 不释放（不修）

判定为设计权衡：`setLayerActive(false)` 保留 `state.tiles` 确保重新激活时即时显示，属于有意的缓存策略。每图层上限 128 瓦片，且 `clearLayer` 时释放。

### ⏭️ P3 · source 复用不更新 tileSize/attribution（不修）

当前所有 provider 均为 `tileSize=256` / `scheme=xyz` / `maxzoom=18`，不触发错位。未来引入差异化 provider 时建议在 `switchTileSource` 的 source 复用分支中用 `setOptions` 或重建 source。

### 验证结果

- vitest：**74 files / 408 tests passed**（含 basemap-module 4/4 + cache-trim 3/3 + weather-tile batch-sync 3/3 + layers 等全量 map 相关测试）
- ESLint：改动 3 文件 **0 告警**
- 改动文件：3 文件（`weather-tile-manager.ts`、`basemap-module.ts`、`Test/.../basemap-module.test.ts`）
