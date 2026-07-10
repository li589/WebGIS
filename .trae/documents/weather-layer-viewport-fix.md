# 天气图层视口同步与坐标偏移修复计划

## Summary

修复天气图层在缩放/平移/全球视图下的 5 个核心问题：
1. 全球缩放（zoom < 3）从不显示天气图层
2. 缩放后加载缓慢（15 秒最小间隔过长）
3. 平移后有时不加载（snap 网格导致 bbox 未变化）
4. 缩放+平移后坐标严重偏移（`renderWorldCopies` 世界副本投影错误）
5. 风场线条抽搐（zoomFactor 过高 + 粒子 canvas 不随平移更新）

## Current State Analysis

### 问题 1: 全球缩放不显示
- [types.ts:38](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/types.ts#L38) `MIN_VISIBLE_ZOOM = 3`
- 粒子流 [wind-particle-canvas.ts:479](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-particle-canvas.ts#L479) `if (zoom < MIN_VISIBLE_ZOOM) { clearRect; return }`
- 风羽 [wind-barb-layer.ts:49](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-barb-layer.ts#L49) `BARB_MIN_VISIBLE_ZOOM = 3`
- 等值线也有同样检查
- 但后端 `WEATHER_REQUEST_BUCKETS[0]` 在 zoom 0-2.5 请求全球数据 (360°×170°)，数据已就绪却不渲染

### 问题 2: 缩放后加载缓慢
- [index.ts:655](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L655) `WORKFLOW_REFRESH_MIN_INTERVAL_MS = 15000`
- [index.ts:660](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L660) `SIGNIFICANT_VIEWPORT_RATIO = 2`（面积变化需 >2 倍才绕过间隔）
- 缩放后 15 秒内不重新提交工作流（除非面积变化 >2 倍）

### 问题 3: 平移后有时不加载
- [index.ts:1608](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/stores/layers/index.ts#L1608) `areBoundingBoxesEqual(lastRequestBBox, requestBBox)` — 如果 snap 后的 bbox 相同则跳过
- `snapRequestCenter` (L209-214) 将中心点对齐到网格步长，小范围平移可能产生相同的 snapped bbox
- 这是**预期行为**（数据范围没变就不重复请求），但用户可能误解为"不加载"

### 问题 4: 坐标严重偏移（核心 Bug）
- [MapCanvas.vue:1389](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/MapCanvas.vue#L1389) `renderWorldCopies: true`
- [canvas-utils.ts:36-39](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/canvas-utils.ts#L36-L39) `map.project([gridWest, gridNorth])` — 投影到**主世界副本**
- 当用户跨越日界线平移时，网格可能在**副本世界**可见，但 `map.project` 返回主世界位置（屏幕外）
- `computeCanvasLayout` 计算出的 canvas 偏移和尺寸对应主世界位置，导致 canvas 定位错误
- 影响范围：粒子流 + 等值线（使用 grid bounds）；风羽使用全局范围 (-180,180) 影响较小但单个 barb 投影也可能错误

### 问题 5: 线条抽搐
- [wind-particle-canvas.ts:485](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-particle-canvas.ts#L485) `zoomFactor = Math.min(Math.pow(2, 6 - zoom), MAX_ZOOM_FACTOR)` `MAX_ZOOM_FACTOR = 8`
- zoom=3 时 zoomFactor=8，粒子速度极快
- [wind-particle-canvas.ts:545](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-particle-canvas.ts#L545) `MAX_TRAIL_LENGTH_PX = 80` — 快速移动频繁触发轨迹重置
- 粒子 canvas 只监听 `movestart`/`moveend`（L357-358），不监听 `move`，平移期间 canvas 被清空不更新
- 对比：风羽和等值线都监听 `MAP_EVENT_MOVE` 并在平移期间持续更新

## Proposed Changes

### 变更 1: 修复 `computeCanvasLayout` 世界副本投影 (问题 4 — 核心)

**文件**: `Code/frontend/src/components/map/canvas-utils.ts`

**原因**: `map.project([lon, lat])` 在 `renderWorldCopies: true` 下只返回主世界副本的屏幕坐标。当用户跨越日界线时，网格在副本世界可见，但投影到主世界（屏幕外），导致 canvas 定位错误。

**修改**: 在 `computeCanvasLayout` 中，使用 `map.getBounds()` 获取可见经度范围，将网格经度 wrap 到可见范围内再投影。

```typescript
export function computeCanvasLayout(
  map: MaplibreMap,
  gridWest: number,
  gridEast: number,
  gridSouth: number,
  gridNorth: number,
  margin = CANVAS_LAYOUT_MARGIN_PX,
): CanvasLayout {
  const container = map.getContainer()
  const vw = container.clientWidth
  const vh = container.clientHeight

  // 修复：处理 renderWorldCopies 模式下的世界副本投影
  // map.project() 只返回主世界副本位置，当用户跨越日界线平移时需要 wrap 经度
  const bounds = map.getBounds()
  const visibleCenterLon = (bounds.getWest() + bounds.getEast()) / 2

  // 将网格经度 wrap 到可见中心附近（±360° 偏移）
  function wrapLon(lon: number): number {
    let wrapped = lon
    while (wrapped < visibleCenterLon - 180) wrapped += 360
    while (wrapped > visibleCenterLon + 180) wrapped -= 360
    return wrapped
  }

  const wWest = wrapLon(gridWest)
  const wEast = wrapLon(gridEast)

  const tl = map.project([wWest, gridNorth])
  const tr = map.project([wEast, gridNorth])
  const bl = map.project([wWest, gridSouth])
  const br = map.project([wEast, gridSouth])

  // ... 后续计算不变 ...
}
```

**注意**: 此修改不影响 WindBarbLayer（它使用 -180,180 全局范围），但会修复 WindParticleCanvas 和 WindContourLayer 的坐标偏移。

### 变更 2: 降低 `MIN_VISIBLE_ZOOM` 并添加低缩放级别降级 (问题 1)

**文件**: `Code/frontend/src/components/map/types.ts`

**修改**: `MIN_VISIBLE_ZOOM` 从 3 改为 0。

```typescript
/** 最小可视 zoom 级别（所有风场图层的统一阈值） */
export const MIN_VISIBLE_ZOOM = 0
```

**文件**: `Code/frontend/src/components/map/wind-barb-layer.ts`

**修改**: `BARB_MIN_VISIBLE_ZOOM` 从 3 改为 0。

**文件**: `Code/frontend/src/components/map/wind-particle-canvas.ts`

**修改**: 在 `draw()` 方法中，不再完全隐藏，而是根据 zoom 级别降级粒子数量和速度：
- zoom < 2: 极少粒子（200），极慢速度
- zoom 2-3: 少量粒子（500），慢速
- zoom >= 3: 正常渲染

在 `resolveParticleCountForZoom` 中添加 zoom 分级：

```typescript
private resolveParticleCountForZoom(zoom: number): number {
  if (!this.grid) return DEFAULT_PARTICLE_OPTIONS.particleCount
  const baseCount = computeParticleCountForGrid(this.grid)
  // 低缩放级别降级粒子数量，避免全球视图下视觉混乱
  if (zoom < 2) return Math.min(baseCount, 200)
  if (zoom < 3) return Math.min(baseCount, 500)
  return baseCount
}
```

### 变更 3: 修复 zoomFactor 防止线条抽搐 (问题 5a)

**文件**: `Code/frontend/src/components/map/wind-particle-canvas.ts`

**修改**: 将 `MAX_ZOOM_FACTOR` 从 8 降为 4，并调整公式使低 zoom 时粒子速度更温和。

```typescript
/** zoomFactor 上限，防止低缩放级别下粒子速度过快导致视觉混乱 */
const MAX_ZOOM_FACTOR = 4
```

L485 公式调整：
```typescript
// 根据缩放级别动态调整速度比例：低 zoom 时粒子经纬度移动量需更大
// 使用更温和的指数（5-zoom 而非 6-zoom），防止低 zoom 时速度过快
const zoomFactor = Math.min(Math.pow(2, 5 - zoom), MAX_ZOOM_FACTOR)
```

### 变更 4: 粒子 canvas 添加 `move` 事件监听 (问题 5b)

**文件**: `Code/frontend/src/components/map/wind-particle-canvas.ts`

**原因**: 当前粒子 canvas 只在 `moveend` 更新位置，平移期间 canvas 被清空不更新。风羽和等值线都在 `move` 期间持续更新。

**修改**: 添加 `MAP_EVENT_MOVE` 监听器，使用 rAF 节流，在平移期间持续更新 canvas 位置和粒子投影。

在 `setupMapEvents` 中添加：
```typescript
import { MAP_EVENT_MOVE, MAP_EVENT_MOVESTART, MAP_EVENT_MOVEEND, MAP_EVENT_RESIZE } from './types'

// 在 setupMapEvents 中添加：
this.moveHandler = () => {
  if (this.rafId !== null) return
  this.rafId = requestAnimationFrame(() => {
    this.rafId = null
    if (this.isMapInteracting) {
      // 平移期间只更新 canvas 位置，不清空不重绘粒子
      this.updateCanvasBounds()
      // 重新投影粒子到新位置（不重置轨迹，只移动起点）
      if (this.grid) {
        const { offsetX, offsetY } = this.layout
        const dpr = this.pixelRatio
        for (const p of this.particles) {
          const screen = this.map.project([p.lon, p.lat])
          const x = (screen.x - offsetX) * dpr
          const y = (screen.y - offsetY) * dpr
          // 平移期间只保留最后一个点，避免轨迹拉伸
          p.trail = [x, y]
        }
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height)
      }
    }
  })
}
// ...
this.map.on(MAP_EVENT_MOVE, this.moveHandler)
```

在 `destroy` 中添加清理：
```typescript
if (this.moveHandler) { this.map.off(MAP_EVENT_MOVE, this.moveHandler); this.moveHandler = null }
```

**注意**: 现有的 `movestart` handler 清空 canvas 的逻辑保留不变。`moveend` handler 的完整重置逻辑也保留不变。`move` handler 只在平移期间持续更新 canvas 位置，使粒子跟随地图移动。

### 变更 5: 缩短工作流刷新最小间隔 (问题 2)

**文件**: `Code/frontend/src/stores/layers/index.ts`

**修改**: `WORKFLOW_REFRESH_MIN_INTERVAL_MS` 从 15000 改为 5000。

```typescript
const WORKFLOW_REFRESH_MIN_INTERVAL_MS = 5000  // 最小重新提交间隔（5 秒）
```

**注意**: 此前设为 15 秒是为了防止 Open-Meteo API 429 限流。现在后端已有 429 重试逻辑（`fetch_point_forecast` 和 `fetch_grid_forecast` 都有指数退避重试），5 秒间隔是安全的。`SIGNIFICANT_VIEWPORT_RATIO = 2` 保持不变，大面积变化仍可绕过间隔。

### 变更 6: 确保 `wrapLon` 正确处理跨日界线网格 (问题 4 补充)

**文件**: `Code/frontend/src/components/map/wind-particle-canvas.ts`

**原因**: `buildWindGridFromGeoJSON` 从 GeoJSON 提取的 grid bounds 可能跨越日界线（如 [170°-(-170°)]），但 `west`/`east` 值可能不连续。`computeCanvasLayout` 的 `wrapLon` 处理后，投影可能不正确。

**修改**: 在 `WindParticleCanvas` 的 `project` 调用处，也需要使用 wrap 后的经度。但这是在 `draw()` 的每帧调用中，性能敏感。

**实际方案**: 在 `computeCanvasLayout` 中正确处理 wrap 后，`map.project([wrappedLon, lat])` 返回正确的屏幕位置。粒子 `draw()` 中的 `project([p.lon, p.lat])` 也需要 wrap，但粒子的 lon 已经在 grid bounds 内，只要 grid bounds 被 wrap 到可见范围，粒子 lon 也需要相应 wrap。

在 `WindParticleCanvas` 中添加 `lonOffset` 字段，记录当前 wrap 偏移量：

```typescript
private lonWrapOffset = 0  // 经度 wrap 偏移（0 或 ±360）

// 在 updateCanvasBounds 中计算 wrap 偏移
private updateCanvasBounds(): void {
  // ...
  const bounds = this.map.getBounds()
  const visibleCenterLon = (bounds.getWest() + bounds.getEast()) / 2
  // 计算 grid 中心需要 wrap 的偏移量
  const gridCenterLon = (this.grid.west + this.grid.east) / 2
  this.lonWrapOffset = 0
  let adjustedCenter = gridCenterLon
  while (adjustedCenter < visibleCenterLon - 180) { adjustedCenter += 360; this.lonWrapOffset += 360 }
  while (adjustedCenter > visibleCenterLon + 180) { adjustedCenter -= 360; this.lonWrapOffset -= 360 }
  // ...
}

// 在 project 调用处使用 wrap 后的经度
private projectParticle(lon: number, lat: number): [number, number] {
  const screen = this.map.project([lon + this.lonWrapOffset, lat])
  return [screen.x, screen.y]
}
```

**简化方案**: 由于 `computeCanvasLayout` 已经在内部处理了 wrap，粒子 canvas 只需确保 `initParticles` 和 `draw` 中的 `project` 调用使用 wrap 后的经度。最简单的方式是在 `computeCanvasLayout` 中返回 wrap 偏移量，让调用方使用。

**最终方案**: 修改 `CanvasLayout` 接口添加 `lonWrapOffset` 字段，`computeCanvasLayout` 计算并返回它，`WindParticleCanvas` 和 `WindContourLayer` 在 project 时加上这个偏移。

## Assumptions & Decisions

1. **不删除 `MIN_VISIBLE_ZOOM` 常量** — 改为 0 而非删除，保持代码结构和引用不变
2. **不修改 `snapRequestCenter` 逻辑** — snap 网格是减少重复请求的优化，保持不变
3. **不修改 `WEATHER_REQUEST_BUCKETS`** — 后端动态分辨率已处理大范围请求
4. **不修改 `VIEWPORT_DEBOUNCE_MS = 500`** — 500ms 防抖是合理的
5. **保留 `movestart` 清空 canvas 的逻辑** — 防止旧尺寸轨迹残留
6. **保留 `moveend` 完整重置的逻辑** — 确保交互结束后状态正确
7. **`MAX_ZOOM_FACTOR` 从 8 降为 4** — zoom=3 时 zoomFactor=4 而非 8，速度减半， jitter 减少
8. **`WORKFLOW_REFRESH_MIN_INTERVAL_MS` 从 15s 降为 5s** — 后端已有 429 重试保护

## Verification Steps

1. **TypeScript 编译**: `cd Code/frontend && npx vue-tsc --noEmit` 确认无类型错误
2. **全球缩放测试**: 缩放到 zoom < 3，确认粒子流/风羽/等值线可见（粒子数量降级）
3. **跨日界线测试**: 平移跨越 ±180° 经度线，确认 canvas 叠加层不偏移
4. **缩放响应测试**: 中等缩放后 < 5 秒内应重新提交工作流
5. **平移流畅度测试**: 平移地图时粒子 canvas 应跟随移动，不应空白
6. **线条稳定性**: zoom=3 时粒子线条不应抽搐
