# 统一渲染架构方案

> **状态更新（2026-07-09）**：步骤 1（WindContourLayer DPI 对齐）与步骤 2（WindBarbLayer 注释清理）均已完成。WindContourLayer 已导入 `computeCanvasLayout` from `./canvas-utils`，添加 `pixelRatio` 字段，删除自实现 `updateCanvasBounds()`。三个 Canvas 2D 叠加层在 DPI 处理和布局计算上已完全一致。本文档的"Proposed Changes"部分保留作为历史记录，"统一架构规范（后续开发指南）"部分仍为有效约束。

## Summary

确立项目的统一渲染架构原则：

- **所有数据驱动的标准图层** → **MapLibre** 渲染（GPU）：底图、数据集图、课题组生产的数据、行政边界、天气栅格场等一切可用标准 GIS 图层类型表达的数据。
- **所有自定义绘制的叠加层** → **Canvas 2D** 渲染（CPU）：矢量场、符号、简单特效、等温/等压/等值线等一切需要自定义绘制逻辑的叠加层。

前序工作已完成 WebGL → Canvas 2D 的迁移（WindBarbLayer 重写、`webgl-utils.ts` 删除、`canvas-utils.ts` 建立、导入路径更新）。本方案聚焦于：① 收尾剩余的层间不一致；② 建立后续开发的架构规范。

---

## Current State Analysis

### 渲染技术分布（迁移后）

| 层 | 技术 | 文件 | zIndex | DPI 处理 | 共享布局工具 |
|----|------|------|--------|----------|--------------|
| 底图瓦片 | MapLibre raster | MapCanvas.vue `ensureTileLayer` | — | MapLibre 内部 | — |
| 行政边界 | MapLibre fill/line/circle | MapCanvas.vue `ensureBoundaryLayers` | — | MapLibre 内部 | — |
| 天气 COG 栅格 | MapLibre raster (image source) | MapCanvas.vue `syncWeatherCogOverlay` | — | MapLibre 内部 | — |
| 天气网格填充/线 | MapLibre fill/line | MapCanvas.vue `syncWeatherGridFillOverlay` | — | MapLibre 内部 | — |
| 天气点/箭头 | MapLibre circle/symbol | MapCanvas.vue `syncWeatherPointOverlay` | — | MapLibre 内部 | — |
| 风速等值线 | **Canvas 2D** | [wind-contour-layer.ts](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-contour-layer.ts) | 4 | ❌ 无 | ❌ 自实现 `updateCanvasBounds` |
| 风场粒子流 | **Canvas 2D** | [wind-particle-canvas.ts](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-particle-canvas.ts) | 5 | ✅ 有 | ✅ `computeCanvasLayout` |
| 风羽符号 | **Canvas 2D** | [wind-barb-layer.ts](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-barb-layer.ts) | 6 | ✅ 有 | ✅ `computeCanvasLayout` |

### 已完成的工作

1. **WindBarbLayer 完全重写为 Canvas 2D**：删除全部着色器源码（`LINE_VERT_SRC`/`LINE_FRAG_SRC`/`CIRCLE_FRAG_SRC`）、WebGL 字段（`glCanvas`/`lineProg`/`circleProg`/`lineBuf`/`circleBuf`/`placeholderTex`/`loc_u_geoToNdc`）、`initGL()` 方法；`buildBarbGeometry()` 返回值从 `Float32Array` 改为 `{ lineSegments, circles }` 对象数组；`draw()` 改用 Canvas 2D API（`beginPath`/`moveTo`/`lineTo`/`stroke` + `arc`/`fill`）。
2. **`webgl-utils.ts` 已删除**：原文件同时承载 WebGL 工具（着色器、buffer、矩阵）和 Canvas 2D 工具（`computeCanvasLayout`），职责混乱。WebGL 部分已全部删除。
3. **`canvas-utils.ts` 已建立**：仅导出 `CanvasLayout` 接口、`computeCanvasLayout()` 函数、`CANVAS_LAYOUT_MARGIN_PX` 常量，供所有 Canvas 2D 叠加层共享。
4. **导入路径已更新**：`wind-barb-layer.ts` 和 `wind-particle-canvas.ts` 均从 `./canvas-utils` 导入。

### WebGL 残留引用验证（均为合法）

Grep 搜索 `webgl|WebGL|gl\.|shader|vertex|fragment|GLSL|texture|uniform|attribute` 后剩余 4 个文件命中，经核查全部为 **MapLibre 内部合法使用**（MapLibre 本身是 WebGL 渲染器，这正是我们要保留的）：

| 文件 | 行 | 内容 | 性质 |
|------|----|------|------|
| [wind-barb-layer.ts](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-barb-layer.ts#L191) | 191 | 注释"几何计算逻辑与原 WebGL 版本完全一致" | 历史注释，可清理 |
| [MapCanvas.vue](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/MapCanvas.vue#L1075) | 1075 | 注释"调用 map.render() 强制刷新 WebGL 帧" | 合法：描述 MapLibre framebuffer 读取 |
| [MapCanvas.vue](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/MapCanvas.vue#L1179) | 1179-1183 | `canvasContextAttributes: { preserveDrawingBuffer: false }` | 合法：配置 MapLibre 的 WebGL 上下文 |
| [main.css](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/styles/main.css#L1) / [main.ts](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/main.ts#L3) | 1/3 | `@import 'maplibre-gl/dist/maplibre-gl.css'` | 合法：CSS 文件名匹配到 `gl.` |

**结论**：项目中已无任何自定义 WebGL 代码。所有 WebGL 引用要么是 MapLibre 内部使用（保留），要么是历史注释（可清理）。

### 剩余不一致（✅ 已全部解决 — 2026-07-09）

1. ~~**WindContourLayer 是唯一未对齐的 Canvas 2D 层**~~：
   - ✅ 已改为使用共享的 `computeCanvasLayout()` from `./canvas-utils`
   - ✅ 已添加 DPI 处理：`pixelRatio = Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO)`，canvas 尺寸乘以 dpr，draw 时坐标乘以 dpr
   - ✅ 已复用 `types.ts` 中的共享类型
2. ~~**WindBarbLayer 中残留一行历史注释**~~——✅ 已清理。

---

## Proposed Changes

### 步骤 1（必须）：统一 WindContourLayer 的 DPI 处理与共享布局工具

**文件**: [Code/frontend/src/components/map/wind-contour-layer.ts](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-contour-layer.ts)

**目的**: 消除 WindContourLayer 与 WindParticleCanvas/WindBarbLayer 之间的实现差异，使三个 Canvas 2D 叠加层在 DPI 处理和布局计算上完全一致。这是"统一渲染架构"在代码层面的最后一块拼图。

**改动清单**:

1. **导入共享工具**（替换自实现）：
   ```typescript
   // 新增
   import { computeCanvasLayout, type CanvasLayout } from './canvas-utils'
   // 复用共享类型（删除文件内本地定义的 WindGeoJSONFeature/WindGeoJSON）
   import type { WindGeoJSON } from './types'
   ```

2. **添加 DPI 字段**（对齐 WindBarbLayer）：
   ```typescript
   private pixelRatio: number
   // 在 constructor 中：
   this.pixelRatio = Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO)
   ```
   其中 `MAX_PIXEL_RATIO = 2` 常量从 `canvas-utils.ts` 或本地定义（与 WindBarbLayer 保持一致）。

3. **替换 `updateCanvasBounds()` 为共享 `computeCanvasLayout()`**：
   - 删除当前 `updateCanvasBounds()` 中重复的投影/裁剪逻辑（line 102-146）
   - 改为调用 `computeCanvasLayout(this.map, west, east, south, north)`，其中 `west/east/south/north` 来自 `this.gridData`
   - canvas 尺寸设置为 `Math.round(width * dpr)` × `Math.round(height * dpr)`，CSS 尺寸保持 `width` × `height` px
   - 删除 `this.ctx.setTransform(1,0,0,1,0,0)`（不再需要恒等变换，所有坐标在 draw 时乘以 dpr）

4. **`draw()` 方法中所有坐标乘以 dpr**（对齐 WindBarbLayer 模式）：
   - `this.ctx.moveTo(p1.x - ox, p1.y - oy)` → `this.ctx.moveTo((p1.x - ox) * dpr, (p1.y - oy) * dpr)`
   - `this.ctx.lineTo(...)` 同理
   - `this.ctx.fillText(...)` 同理
   - `lineWidth` 保持原值（Canvas 2D 的 lineWidth 在乘以 dpr 的坐标系中自动缩放），或显式乘以 dpr（与 WindBarbLayer 一致）

5. **删除本地 `WindGeoJSONFeature`/`WindGeoJSON` 接口定义**（line 20-29），改用 `types.ts` 中的共享类型。

**不改动**:
- `loadData()` 的网格解析逻辑（保留）
- `marchingSquares()` 算法（保留）
- `resolveActiveLevels()` LOD 策略（保留）
- 事件绑定/rAF 节流/destroy 清理逻辑（保留）
- zIndex=4（保留）

### 步骤 2（必须）：清理 WindBarbLayer 历史注释

**文件**: [Code/frontend/src/components/map/wind-barb-layer.ts](file:///d:/temp_desktop_proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/map/wind-barb-layer.ts#L191)

**改动**: 将 line 191 注释从"几何计算逻辑与原 WebGL 版本完全一致，仅输出格式从 Float32Array 改为对象数组。"改为"几何计算逻辑：杆方向、三角旗、长线、短线均按气象风羽标准。"（去除对已删除 WebGL 版本的引用）

### 步骤 3（可选/未来）：CanvasOverlayLayer 基类提取

**当前判断**: 不执行。三个 Canvas 2D 层（WindContourLayer/WindParticleCanvas/WindBarbLayer）的共享逻辑（canvas 创建、事件绑定、rAF 节流、destroy）重复程度可接受，提取基类属于过早抽象。待未来新增第 4 个 Canvas 2D 叠加层时再评估。

**未来评估信号**: 当出现第 4 个 Canvas 2D 层，或三个层的 destroy/事件绑定逻辑出现实质性分叉时，再提取基类。

---

## 统一架构规范（后续开发指南）

### 判断标准：何时用 MapLibre，何时用 Canvas 2D

**用 MapLibre（GPU）**：如果数据可以用 GeoJSON/瓦片/COG 表达，且渲染样式可以用 MapLibre 的 layer type + paint properties + expression 描述。

**用 Canvas 2D（CPU）**：如果渲染逻辑无法用 MapLibre 的 layer type + paint properties 表达，需要逐像素/逐帧自定义绘制。

### MapLibre 层适用场景

| 数据类型 | source type | layer type | 现有实例 |
|----------|-------------|------------|----------|
| 底图瓦片 | `raster` | `raster` | `tile-base-raster` |
| COG 栅格预览 | `image` | `raster` | `weather-raster-${catalogId}` |
| 矢量面/线（行政边界、网格填充） | `geojson` | `fill` / `line` | `admin-fill`、`admin-line`、`weather-fill-${catalogId}` |
| 点数据（站点、热点） | `geojson` | `circle` | `admin-center-points`、`weather-point-${catalogId}` |
| 符号/图标（风向箭头） | `geojson` | `symbol` | `weather-arrow-${catalogId}` |
| 热力图 | `geojson` | `heatmap` | （未来） |
| 矢量瓦片 | `vector` | 各类型 | （未来） |

### Canvas 2D 层适用场景

| 渲染需求 | 算法/技术 | 现有实例 |
|----------|-----------|----------|
| 粒子流动画 | 逐帧动画 + 轨迹累积 + `destination-out` 淡化 | `WindParticleCanvas` |
| 等值线（等温/等压/等风速） | Marching Squares 几何提取 | `WindContourLayer` |
| 气象符号（风羽） | 标准符号几何绘制 + 批量 stroke | `WindBarbLayer` |
| 简单特效（光晕、脉冲、高亮） | 自定义着色/混合模式 | （未来） |
| 流线/迹线 | 自定义积分 + polyline | （未来） |

### Canvas 2D 层开发规范

1. **DPI 处理**（必须）：
   ```typescript
   private pixelRatio = Math.min(window.devicePixelRatio, 2)
   // canvas 尺寸：
   this.canvas.width = Math.round(layoutWidth * this.pixelRatio)
   this.canvas.height = Math.round(layoutHeight * this.pixelRatio)
   this.canvas.style.width = `${layoutWidth}px`
   this.canvas.style.height = `${layoutHeight}px`
   // draw 时所有坐标乘以 pixelRatio
   ```
2. **布局计算**（必须）：使用 `computeCanvasLayout(map, west, east, south, north)` from `./canvas-utils`，不自实现投影/裁剪逻辑。
3. **事件节流**（必须）：`move`/`moveend` 事件用 `requestAnimationFrame` 节流，每帧只重绘一次。
4. **zIndex 层级**：
   - 4: 等值线（底层）
   - 5: 粒子流（中层）
   - 6: 风羽/符号（顶层）
   - 7+: 未来特效层
5. **公开 API**（必须）：`constructor(map, data, options?)`、`updateData(data)`、`setVisible(bool)`、`destroy()`。
6. **清理**（必须）：`destroy()` 必须移除 canvas DOM、取消 rAF、解绑 map 事件。
7. **类型复用**（必须）：从 `./types` 导入共享类型（`WindGeoJSON`、`MAP_EVENT_*`、`DEFAULT_HEIGHT_SUFFIX`），不自定义重复接口。
8. **常量提取**（必须）：渲染参数（颜色、尺寸、阈值）提取为文件顶部 `const`，不在逻辑中硬编码。

### MapLibre 层开发规范

1. **多图层隔离**：每个数据图层用独立 source/layer ID（如 `weather-src-${catalogId}`），避免互相覆盖。
2. **样式表达式**：颜色/尺寸映射用 `weather-render.ts` 中的表达式构建工具，不内联。
3. **图层插入位置**：业务图层插入到 `admin-fill` 之前（`beforeLayerId = 'admin-fill'`），保证行政边界在数据图层之上。
4. **资源清理**：图层切换/移除时，先 `removeLayer` 再 `removeSource`，避免悬挂引用。

---

## Assumptions & Decisions

1. **不迁移到 WebGL**：Canvas 2D 对于当前规模（<6000 粒子 / <3000 风羽符号 / 等值线段 <10000）完全够用。Windy.com 等业内标杆也用 Canvas 2D。
2. **保留 MapLibre 的 WebGL 内部使用**：MapLibre 本身是 WebGL 渲染器，其内部 WebGL 上下文（`canvasContextAttributes`、framebuffer 读取）是合法且必须的，不属于"自定义 WebGL 代码"。
3. **WindContourLayer DPI 修复为必须**：在"统一渲染架构"下，三个 Canvas 2D 层的 DPI 处理必须一致，否则高 DPI 屏幕上视觉清晰度不一致。
4. **基类提取暂缓**：遵循"避免过度设计"原则，3 个层的代码重复可接受，待第 4 个层出现时再评估。
5. **`MAX_PIXEL_RATIO` 常量位置**：当前 WindBarbLayer 和 WindParticleCanvas 各自定义 `MAX_PIXEL_RATIO = 2`。WindContourLayer 修复时同样本地定义。未来若提取基类，再上移到 `canvas-utils.ts`。
6. **风羽几何逻辑不变**：步骤 1 不涉及 WindBarbLayer 的几何计算，仅改 WindContourLayer。

---

## Verification Steps

1. **编译检查**：`cd Code/frontend && npx tsc --noEmit` 确认 WindContourLayer 修改后无类型错误。
2. **DPI 一致性验证**：在 4K/Retina 屏幕上打开风场图层，确认等值线（zIndex=4）、粒子流（zIndex=5）、风羽（zIndex=6）三者清晰度一致，无模糊层。
3. **三层叠加测试**：
   - 打开风场图层，确认等值线、粒子流、风羽都正常显示
   - 缩放/平移地图，确认三层都跟随更新，无延迟/撕裂
   - 切换风场高度（10m/80m/120m/180m），确认三层都更新数据
4. **布局工具一致性**：缩放到全球视图和近景视图，确认 WindContourLayer 的 canvas 尺寸与 WindBarbLayer 一致（都使用 `computeCanvasLayout`）。
5. **清理验证**：关闭风场图层后确认三个 canvas DOM 都被移除、rAF 都被取消。
6. **WebGL 残留复查**：`Grep -i "webgl|gl\.|shader"` 确认修改后仅剩 MapLibre 内部合法引用。
7. **注释清理验证**：确认 wind-barb-layer.ts line 191 注释已更新，无"原 WebGL 版本"字样。
