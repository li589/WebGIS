# 叠加图层信息关联显示 — 完成剩余前端接线

## 摘要

上一轮已完成 7 项变更（后端 OverlaySpec 扩展 + `/overlay-value` 端点 + 3 个工作流模块 + overlay-image-module.ts 多图层时间联动 + MapCanvas.vue 联动按钮与事件透传）。本计划覆盖**剩余 3 项**：InfoPanel.vue 元数据与像素值显示、DashboardView.vue 状态接线与查询透传、端到端验证。

## 当前状态分析

### 已完成（任务 1-7，无需重复）
1. `overlay_registry.py` — OverlaySpec 已有 `source_path/source_pattern/source_variable/source_reader` 字段 + `resolve_value()` 方法
2. `layer_router.py` — `/overlay-value/{layer_id}` 端点已就绪
3. `modules/export.py`、`modules/fitting.py`、`modules/statistics.py` — 3 个工作流模块已注册
4. `overlay-image-module.ts` — `linkTimeEnabled` 状态 + `setLinkTime()` + `_findNearestTime()` + `setOverlayTime` 联动逻辑已就绪
5. `MapCanvas.vue` — `overlayTimeUpdate` emit + `overlayLinkTimeEnabled` computed + `overlayToggleLinkTime()` + `watch(overlayTimeStates)` + 联动按钮模板已就绪

### 待完成（任务 8-10）

**InfoPanel.vue 当前缺口**（基于 [InfoPanel.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/InfoPanel.vue) 实读）：
- Props（L17-28）：无 `overlayTimeStates` / `overlayPointValues`
- `overlayLayers` computed（L155-164）：仅映射 `name/category/availabilityState/accentColor`，缺 `palette/vmin/vmax/unit/currentTime`
- 模板叠加图层列表（L706-725）：仅显示名称+类别+状态，无调色板色带、值域、时间标签
- 无 overlay 像素值查询结果区

**DashboardView.vue 当前缺口**（基于 [DashboardView.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/views/DashboardView.vue) 实读）：
- `handleMapPointSelect`（L128-131）：仅调用 `fetchPointWeather`，无 overlay 像素值查询
- InfoPanel 渲染（L267-281）：未传递 `overlayTimeStates` / `overlayPointValues`
- MapCanvas 绑定（L213-221）：未监听 `@overlay-time-update`
- 无 `overlayTimeStates` / `overlayPointValues` ref 状态

**runtime-api.ts 缺口**：无 `getOverlayValue` 函数调用 `/overlay-value/{layer_id}`

## 变更计划

### 变更 1：runtime-api.ts 新增 getOverlayValue 函数

**文件**：[runtime-api.ts](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/services/runtime-api.ts)

**位置**：在 `getWeatherPoint` 函数后（L217 后）插入

**内容**：
- 定义 `OverlayPointValue` 接口（本地 TypeScript interface，因为后端返回的是 plain dict 无 Pydantic response_model）：
  ```typescript
  export interface OverlayPointValue {
    layer_id: string
    value: number | null
    unit: string
    time: string | null
    lng: number
    lat: number
    error?: string
  }
  ```
- 新增 `getOverlayValue` 函数：
  ```typescript
  export function getOverlayValue(
    layerId: string,
    lng: number,
    lat: number,
    time?: string | null,
    signal?: AbortSignal,
  ): Promise<OverlayPointValue> {
    const search = new URLSearchParams({
      lng: String(lng),
      lat: String(lat),
    })
    if (time) search.set('time', time)
    return requestJson<OverlayPointValue>(`/overlay-value/${layerId}?${search.toString()}`, {
      signal,
    })
  }
  ```

**理由**：遵循现有 `getWeatherPoint` 模式（URLSearchParams + requestJson），保持一致性。

### 变更 2：InfoPanel.vue 增强 — props + 元数据 + 像素值区段

**文件**：[InfoPanel.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/components/InfoPanel.vue)

#### 2a. 新增 props（L28 后追加）
```typescript
overlayTimeStates?: import('../components/map/overlay-image-module').OverlayTimeState[]
overlayPointValues?: import('../services/runtime-api').OverlayPointValue[]
```

#### 2b. 增强 overlayLayers computed（L155-164）
将 `props.overlayTimeStates` 与 `layersStore.activeLayersDisplay` join，补充元数据字段：
```typescript
const overlayLayers = computed(() => {
  const timeStateMap = new Map(
    (props.overlayTimeStates ?? []).map((s) => [s.layerId, s]),
  )
  return layersStore.activeLayersDisplay
    .filter((l) => l.instanceId !== displayLayer.value.instanceId && l.visible)
    .map((l) => {
      const ts = timeStateMap.get(l.catalogId)
      return {
        name: l.name,
        category: l.category,
        availabilityState: l.availabilityState,
        accentColor: l.accentColor,
        catalogId: l.catalogId,
        palette: ts?.palette ?? null,
        vmin: ts?.vmin ?? null,
        vmax: ts?.vmax ?? null,
        unit: ts?.unit ?? '',
        currentTime: ts?.currentTime ?? null,
        isTimeSeries: ts?.category === 'time-series',
      }
    })
})
```

#### 2c. 新增 overlayPointValueMap computed
将 `props.overlayPointValues` 转为 Map 便于模板查找：
```typescript
const overlayPointValueMap = computed(() => {
  const m = new Map<string, import('../services/runtime-api').OverlayPointValue>()
  for (const v of props.overlayPointValues ?? []) {
    m.set(v.layer_id, v)
  }
  return m
})
const hasOverlayPointValues = computed(() => overlayPointValueMap.value.size > 0)
```

#### 2d. 扩展叠加图层列表模板（L711-724）
在每个 `<li>` 中追加：
- 调色板名称标签（如 `viridis`）
- 值域标签（如 `0.0 – 0.5 m³/m³`）
- 当前时间标签（仅时间序列图层，如 `2023-01-15`）
- 像素值（若 `overlayPointValueMap` 中有对应值）

```html
<li
  v-for="layer in overlayLayers"
  :key="layer.catalogId || layer.name"
  :style="{ '--layer-accent': layer.accentColor }"
>
  <span class="overlay-dot" aria-hidden="true"></span>
  <div class="overlay-info">
    <strong class="overlay-name">{{ layer.name }}</strong>
    <span class="overlay-category">
      {{ layer.category }}
      <span v-if="layer.palette" class="overlay-palette-tag">{{ layer.palette }}</span>
    </span>
    <span v-if="layer.vmin !== null || layer.vmax !== null" class="overlay-range">
      {{ layer.vmin ?? '—' }} – {{ layer.vmax ?? '—' }} {{ layer.unit }}
    </span>
    <span v-if="layer.isTimeSeries && layer.currentTime" class="overlay-time-tag">
      {{ layer.currentTime }}
    </span>
  </div>
  <div class="overlay-value-col">
    <span class="overlay-state" :class="`state-${layer.availabilityState}`">{{ layer.availabilityState }}</span>
    <span
      v-if="overlayPointValueMap.get(layer.catalogId)"
      class="overlay-point-value"
      :class="{ na: overlayPointValueMap.get(layer.catalogId)?.value === null }"
    >
      {{ overlayPointValueMap.get(layer.catalogId)?.value !== null
          ? formatOverlayValue(overlayPointValueMap.get(layer.catalogId)!)
          : 'N/A' }}
    </span>
  </div>
</li>
```

#### 2e. 新增 formatOverlayValue 辅助函数
```typescript
function formatOverlayValue(v: import('../services/runtime-api').OverlayPointValue): string {
  if (v.value === null || v.value === undefined) return 'N/A'
  const digits = Math.abs(v.value) >= 100 ? 1 : 3
  return `${v.value.toFixed(digits)} ${v.unit}`.trim()
}
```

#### 2f. 新增 CSS 样式
为新增的 `.overlay-palette-tag`、`.overlay-range`、`.overlay-time-tag`、`.overlay-value-col`、`.overlay-point-value` 添加样式，沿用现有暗色主题色调（参考 `.overlay-category` 和 `.overlay-state` 的风格）。

### 变更 3：DashboardView.vue 状态接线 + 查询透传

**文件**：[DashboardView.vue](file:///d:/temp_desktop/Proj/Comprehensive%20Geographic%20Data%20Analysis%20system/Code/frontend/src/views/DashboardView.vue)

#### 3a. 新增 import 与状态 ref
- 在 import 区追加：`import { getOverlayValue, type OverlayPointValue } from '../services/runtime-api'`
- 新增 ref：
  ```typescript
  const overlayTimeStates = ref<import('../components/map/overlay-image-module').OverlayTimeState[]>([])
  const overlayPointValues = ref<OverlayPointValue[]>([])
  ```

#### 3b. 新增 handleOverlayTimeUpdate 函数
```typescript
function handleOverlayTimeUpdate(states: import('../components/map/overlay-image-module').OverlayTimeState[]) {
  overlayTimeStates.value = states
}
```

#### 3c. 扩展 handleMapPointSelect（L128-131）
在现有 `fetchPointWeather` 后，并行查询所有已加载 overlay 的像素值：
```typescript
async function handleMapPointSelect(point: { lng: number; lat: number }) {
  selectedMapPoint.value = point
  void layersStore.fetchPointWeather(point.lng, point.lat, activeLayer.value.catalogId)
  // 查询所有已加载 overlay 图层的像素值
  void fetchOverlayPointValues(point.lng, point.lat)
}

async function fetchOverlayPointValues(lng: number, lat: number) {
  const states = overlayTimeStates.value
  if (states.length === 0) {
    overlayPointValues.value = []
    return
  }
  const results = await Promise.allSettled(
    states.map((s) => getOverlayValue(s.layerId, lng, lat, s.currentTime ?? undefined)),
  )
  overlayPointValues.value = results
    .map((r, idx) => r.status === 'fulfilled' ? r.value : null)
    .filter((v): v is OverlayPointValue => v !== null)
}
```

#### 3d. MapCanvas 绑定 @overlay-time-update（L213-221）
在 `<MapCanvas>` 标签上追加：
```html
@overlay-time-update="handleOverlayTimeUpdate"
```

#### 3e. InfoPanel 传递新 props（L267-281）
在 `<InfoPanel>` 标签上追加：
```html
:overlay-time-states="overlayTimeStates"
:overlay-point-values="overlayPointValues"
```

### 变更 4：验证

1. **后端启动**：重启 backend，确认无导入错误
2. **API 测试**：`GET /overlay-value/dem-etopo?lng=116&lat=40` 返回 `{"value": ..., "unit": "m", ...}`
3. **前端编译**：`npm run build` 无 TS 错误
4. **UI 验证**：
   - 启用 DEM overlay + SMAP 时间序列 overlay
   - InfoPanel 叠加分析区显示调色板名称、值域、（时间序列图层的）当前时间
   - 点击地图后，叠加分析区每个图层显示像素值（如 `1234.5 m` 或 `N/A`）
   - 切换 SMAP 时间标签后，InfoPanel 中的当前时间标签同步更新
   - 启用联动按钮后，切换一个时间序列图层时间，InfoPanel 中其他时间序列图层的当前时间标签同步更新

## 假设与决策

1. **不修改后端**：`/overlay-value` 端点和 OverlaySpec.resolve_value() 已在上一轮完成且无需调整
2. **不修改 MapCanvas.vue**：联动按钮和事件透传已完成
3. **不修改 overlay-image-module.ts**：多图层时间联动已完成
4. **像素值查询并发**：使用 `Promise.allSettled` 并行查询所有 overlay，单个失败不影响其他
5. **不缓存像素值**：每次点击地图重新查询（与 fetchPointWeather 一致的策略）
6. **类型定义**：`OverlayPointValue` 在 `runtime-api.ts` 中本地定义（后端返回 plain dict 无 Pydantic response_model，不依赖自动生成类型）
7. **时间格式化**：InfoPanel 中直接显示 `currentTime` 原始字符串（如 `20230115`），不做格式转换（MapCanvas 已有 `overlayFormatTime` 但 InfoPanel 保持简单）

## 实施顺序

1. 变更 1：runtime-api.ts 新增 `getOverlayValue`（最小改动，无依赖）
2. 变更 2：InfoPanel.vue 增强 props + computed + 模板 + CSS
3. 变更 3：DashboardView.vue 接线（依赖变更 1 的 `getOverlayValue` 和变更 2 的 props）
4. 变更 4：验证
