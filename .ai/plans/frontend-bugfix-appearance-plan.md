# 前端 Bug 修复与外观功能增强计划

> 制定时间：2026-08-12
> 范围：底图渲染、加载动画、外圈背景、地图显示设置、主题切换、组件状态联动

---

## Phase 1: 底图无法显示（ critical ）

### 1.1 MapLibre background-color 使用 CSS 变量 — WebGL 不支持

**文件**: `src/components/map/map-canvas-map-options.ts:17`

**问题**: `paint: { 'background-color': 'var(--surface-1)' }` — MapLibre GL JS 的 WebGL 渲染器不支持 CSS 自定义属性，颜色值会被忽略，背景可能渲染为黑色或透明。

**修复**: 替换为字面量颜色值，并在主题切换时动态更新。

```typescript
// 方案：从 getComputedStyle 读取 CSS 变量的实际值
function resolveTokenColor(varName: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || '#0b1a2a'
}
// 使用：
{ id: 'background', type: 'background', paint: { 'background-color': resolveTokenColor('--surface-1') } }
```

- 主题切换时通过 `map.setPaintProperty('background', 'background-color', newColor)` 更新
- 在 `useThemeStore` 的 watch 中触发更新

### 1.2 getTileConfig 返回 undefined 时静默失败

**文件**: `src/components/map/basemap-module.ts:114-115, 195-196`

**问题**: `const cfg = options.getTileConfig(sourceId); if (!cfg) return` — 无错误日志，底图层保持 `visibility: 'none'`，地图显示为空白。

**修复**: 添加 console.warn 和用户可见的错误提示。

### 1.3 502 错误不计入熔断器

**文件**: `src/components/map/basemap-module.ts:295-303`

**问题**: 仅处理 `status === 0 || 403 || 404 || 503`，502 被过滤。后端上游不可达时返回 502，前端不计入熔断也不显示错误，底图静默失败。

**修复**: 将 502 加入熔断器错误码列表。

### 1.4 默认底图源 gaode-street 依赖后端代理

**文件**: `src/services/map-defaults.ts:10`, `src/services/api-config.ts:784`

**问题**: 高德底图需后端坐标转换代理。后端未启动时瓦片全部 502。

**修复**:
- 在 `basemap-module.ts` 中添加底图加载失败后的自动降级逻辑：连续失败 N 次后尝试切换到不需要后端代理的免费源（如 OSM）
- 在 `map-defaults.ts` 中将默认源改为不依赖后端代理的源（如 `osm-standard`），高德作为可选源
- 或者：在启动时检测后端是否可用，不可用时自动切换到免费源

### 1.5 TILE_SOURCE_MAP 静态构建不反映运行时禁用状态

**文件**: `src/services/api-config.ts:737-739`

**问题**: `basemap-module.ts` 通过 `getTileConfig` 使用静态 `TILE_SOURCE_MAP`，不反映后端运行时配置中 disabled 的 provider。

**修复**: 在 `basemap-module.ts` 的 `getTileConfig` 回调中加入运行时可用性检查，不可用时返回 undefined 并记录日志。

### 验证命令

```bash
cd Code/frontend && npm run test -- basemap
cd Code/frontend && npm run lint
cd Code/frontend && npm run build
# 联调：启动后端后，浏览器 DevTools Network 检查 /unified-tiles/ 请求状态码
```

---

## Phase 2: 加载动画正常显示

### 2.1 检查 LoadingOverlay 挂载

**文件**: `src/App.vue`

**问题**: 需确认 `<LoadingOverlay />` 是否在 App.vue 中正确挂载，以及 `uiLoading` store 的 show/hide 是否平衡。

**修复**:
- 验证 App.vue 中 LoadingOverlay 的 import 和使用
- 检查 `uiLoading.show()` 和 `uiLoading.hide()` 调用是否配对
- 确保 `showImmediate` 后一定有对应的 `hideImmediate`

### 2.2 MapCanvas skeleton 动画

**文件**: `src/components/map/map-stage-presentation-module.ts`, `src/components/MapCanvas.vue`

**问题**: skeleton 可见性由 `skeletonVisible` ref 控制，通过 `buildMapStageAppearanceModel` 计算。需验证：
- `prepareMount()` 是否正确设置 skeleton 可见
- `revealMap()` 的 `requestAnimationFrame` 延迟是否合适
- 260ms 的 skeleton 隐藏延迟是否过长或过短

**修复**:
- 确认 skeleton CSS 动画（sweep/node/strip）是否正确渲染
- 如果地图加载快于 260ms，skeleton 闪烁可能不明显 — 考虑最小显示时间
- 如果地图加载慢，skeleton 应持续显示直到 map ready

### 2.3 InlineLoader 和按钮 spinner

**文件**: `src/components/common/InlineLoader.vue`, `src/components/ui/AppButton.vue`

**问题**: 需确认 spinner CSS 动画是否正确渲染（可能 CSS 变量未定义导致 spinner 不可见）。

**修复**:
- 检查 InlineLoader 的 CSS 是否引用了不存在的 token
- 检查 AppButton spinner 的 `--accent` 变量在当前主题下是否有值
- 确保 `prefers-reduced-motion: reduce` 时仍有替代指示（如文字"加载中..."）

### 验证命令

```bash
cd Code/frontend && npm run test -- loading
cd Code/frontend && npm run lint
```

---

## Phase 3: 外圈黑到白过渡色背景

### 3.1 外圈背景渐变问题

**文件**: `src/styles/main.css:17-48`

**问题**:
- `:root` 暗色背景：顶部蓝色光晕 + 深空蓝垂直渐变（`--surface-base` → `--surface-sunken`）
- `[data-theme='light']` 浅色背景：顶部青色光晕 + **从浅白到深蓝灰的垂直渐变**（`--surface-base` → `--text-primary` → `--text-secondary`），这导致浅色主题下外圈从白变黑
- `#app` 的 `padding: 0.75rem` 使外圈背景透出
- `useThemeStore` 未被激活，`data-theme` 属性可能从未设置

**修复**:
1. 简化外圈背景为纯色或极淡渐变，避免黑到白的突兀过渡：
   ```css
   :root {
     background: var(--surface-base);
   }
   [data-theme='light'] {
     background: var(--surface-base);
   }
   ```
2. 或者保留渐变但使用同色系深浅过渡，不要跨色系：
   ```css
   :root {
     background: linear-gradient(180deg, var(--surface-base), var(--surface-1));
   }
   [data-theme='light'] {
     background: linear-gradient(180deg, var(--surface-base), var(--surface-1));
   }
   ```
3. 在 App.vue 中激活 `useThemeStore` 确保 `data-theme` 正确设置

### 3.2 浅色主题背景色错误

**文件**: `src/styles/main.css:38-48`

**问题**: 浅色主题渐变使用 `--text-primary`（#1a2b42）和 `--text-secondary`（#4a6076）作为背景色 — 这是文字颜色用作背景，导致浅色主题外圈从白渐变到深蓝灰，视觉上像"黑到白过渡"。

**修复**: 使用正确的表面色系：
```css
[data-theme='light'] {
  background:
    radial-gradient(circle at top, rgba(10, 143, 196, 0.08), transparent 30rem),
    linear-gradient(180deg, var(--surface-base) 0%, var(--surface-1) 100%);
}
```

### 验证命令

```bash
cd Code/frontend && npm run lint
cd Code/frontend && npm run build
# 浏览器中切换主题验证外圈背景
```

---

## Phase 4: mapDistributionChrome 选框无效

### 4.1 选框功能验证

**文件**: `src/components/settings/GeneralSettings.vue:17-22`, `src/services/settings-local.ts:155-178`, `src/components/MapCanvas.vue:260-263`, `src/components/map/map-stage-view-model.ts:141-154`

**分析**: 代码链路完整：
- GeneralSettings checkbox → `setMapDistributionChromeEnabled(checked)` → localStorage + pub/sub
- MapCanvas subscribe → `mapDistributionChromeEnabled.value` 更新
- view-model → `showAtmosphereChrome` / `showDistributionChrome` → CSS class

**可能的问题**:
1. **条件过于严格**：`showAtmosphereChrome = distributionChromeEnabled && hasVisibleDataLayers` — 无可见数据图层时始终关闭，用户可能以为选框无效
2. **视口条件**：`showDistributionChrome = showAtmosphereChrome && isGlobalViewport` — 需缩放到近全球才显示分布淡底
3. **CSS class 未正确传递**：需验证 `map-stage-chrome-off` / `map-stage-distribution` class 是否正确应用到 DOM

**修复**:
1. 在选框旁添加说明文字，明确告知效果触发条件（"需有可见数据图层且缩放到全球视图时生效"）
2. 添加即时视觉反馈：选框切换时显示 toast 提示当前状态
3. 验证 `mapDistributionChromeEnabled` ref 是否正确传入 `buildMapStageAppearanceModel`
4. 考虑放宽条件：即使无数据图层也允许氛围遮罩（fog/time-sheen），仅分布淡底需要数据图层

### 验证

```bash
cd Code/frontend && npm run test -- map-stage
# 联调：添加数据图层 → 缩放到全球 → 切换选框 → 检查 CSS class 变化
```

---

## Phase 5: 浅色/深色切换 + 外观设置项

### 5.1 激活 useThemeStore

**文件**: `src/App.vue`

**问题**: `stores/theme.ts` 定义了完整的 dark/light 主题 store，但没有任何组件导入使用。`data-theme` 属性从未被设置。

**修复**: 在 App.vue 的 `<script setup>` 中调用 `useThemeStore()` 激活主题：
```typescript
import { useThemeStore } from './stores/theme'
const themeStore = useThemeStore()
// store 初始化时会自动设置 data-theme 属性
```

### 5.2 创建 AppearanceSettings.vue

**新文件**: `src/components/settings/AppearanceSettings.vue`

**内容**:
1. **主题模式**：三选一（深色 / 浅色 / 跟随系统）
   - 使用 `useThemeStore` 的 `mode` 和 `setTheme`
   - "跟随系统"模式：监听 `prefers-color-scheme` 媒体查询
2. **地图显示**（从 GeneralSettings.vue 移入）：
   - `mapDistributionChrome` 选框
   - 添加说明文字
3. **动效偏好**：
   - `prefers-reduced-motion` 选框（写 localStorage + CSS class）
4. **界面密度**（可选）：
   - 紧凑/标准 切换（影响 padding、font-size）

### 5.3 修改 GeneralSettings.vue

**文件**: `src/components/settings/GeneralSettings.vue`

**修改**: 移除"地图显示"区块（第 420-434 行），保留系统信息、运行时参数等。

### 5.4 修改 SettingsPanel.vue

**文件**: `src/components/settings/SettingsPanel.vue`

**修改**:
1. 在 `SettingsTab` 类型中添加 `'appearance'`
2. 在 `TAB_IDS` 数组中添加 `'appearance'`（放在 `'general'` 之后）
3. 在 `tabComponents` 中注册 `AppearanceSettings`
4. 在 `ALL_TABS` 中添加 `{ id: 'appearance', label: '外观', icon: Palette }`
5. Import `AppearanceSettings` 组件和 `Palette` 图标

### 5.5 在 ModeToolbar 添加主题切换按钮

**文件**: `src/components/ModeToolbar.vue`

**修改**: 在右侧状态集群添加主题切换按钮：
```html
<IconButton
  size="sm"
  :label="themeStore.mode === 'dark' ? '切换到浅色' : '切换到深色'"
  @click="themeStore.toggle()"
>
  <template #icon>
    <Sun v-if="themeStore.mode === 'dark'" :size="14" />
    <Moon v-else :size="14" />
  </template>
</IconButton>
```

### 5.6 主题切换时更新 MapLibre 背景色

**文件**: `src/components/MapCanvas.vue` 或 `src/components/map/map-stage-presentation-module.ts`

**修改**: watch `themeStore.mode`，主题切换时调用 `map.setPaintProperty('background', 'background-color', newColor)` 更新 MapLibre 背景色。

### 5.7 丰富外观相关功能

可选增强：
- **自定义强调色**：允许用户选择 accent 色（预设几个配色）
- **地图舞台透明度**：控制 map-stage 背景透明度
- **侧栏宽度记忆**：已由 usePanelManager 实现，可在外观设置中重置

### 验证命令

```bash
cd Code/frontend && npm run test
cd Code/frontend && npm run lint && npm run build
# 浏览器验证：主题切换、设置面板"外观"tab、mapDistributionChrome 选框
```

---

## Phase 6: 组件状态联动与异步问题修复

### 6.1 【中风险】useMapInspect pointHourRefetchTimer 未清理

**文件**: `src/views/dashboard/useMapInspect.ts:221-231`

**问题**: `pointHourRefetchTimer` 在 composable 卸载后仍可能触发，执行无意义的 API 请求。

**修复**: 添加 `onBeforeUnmount` 清理：
```typescript
onBeforeUnmount(() => {
  if (pointHourRefetchTimer !== null) {
    window.clearTimeout(pointHourRefetchTimer)
    pointHourRefetchTimer = null
  }
})
```

### 6.2 【中风险】fetchSelectedOverlaySeries 数据竞态

**文件**: `src/views/dashboard/useMapInspect.ts:114-131`

**问题**: `fetchOverlayPointValues` 使用序列号防竞态，但内部调用的 `fetchSelectedOverlaySeries` 在 `await` 之后执行，不受 seq 保护。

**修复**: 在 `fetchSelectedOverlaySeries` 调用前后检查序列号：
```typescript
async function fetchOverlayPointValues(lng: number, lat: number) {
  const seq = ++overlayPointFetchSeq
  const currentResults = await Promise.allSettled(...)
  if (seq !== overlayPointFetchSeq) return
  overlayPointValues.value = ...
  await fetchSelectedOverlaySeries(lng, lat)
  if (seq !== overlayPointFetchSeq) return  // 再次检查
  // 确认结果仍属于当前请求
}
```
或将 `fetchSelectedOverlaySeries` 的结果也用 seq 保护。

### 6.3 【中风险】MapCanvas onMounted 异步初始化无卸载检查

**文件**: `src/components/MapCanvas.vue:288-453`

**问题**: `onMounted` 内有多个 `await`，组件在 `await` 期间卸载后，代码继续创建 map 实例和 watchers，这些 watchers 不会被清理。

**修复**: 在 `await` 之后检查 `isMounted` 标志：
```typescript
let isMounted = true
onBeforeUnmount(() => { isMounted = false })

onMounted(async () => {
  await presentationModule.prepareMount()
  if (!isMounted) return  // 组件已卸载
  const { default: maplibregl } = await import('maplibre-gl')
  if (!isMounted) return  // 组件已卸载
  const mapInstance = new maplibregl.Map(...)
  // ...
})
```

### 6.4 【中低风险】handleTimelineChange 无防抖

**文件**: `src/views/dashboard/useTimelineControls.ts:30-35`

**问题**: TimelineScrubber 拖拽时连续触发 `change-hour`，每次同步执行整个 watch 链（setHour → setCurrentHour → flushWeatherTileViewports），可能卡顿。

**修复**: 在 `handleTimelineChange` 中添加防抖（50-100ms），或使用 `requestAnimationFrame` 批处理：
```typescript
let hourUpdateRaf: number | null = null
function handleTimelineChange(hour: number) {
  if (hourUpdateRaf !== null) cancelAnimationFrame(hourUpdateRaf)
  hourUpdateRaf = requestAnimationFrame(() => {
    hourUpdateRaf = null
    uiStore.setHour(hour)
  })
}
```

### 6.5 【低风险】attachAlgorithmProductOverlays 未处理 rejection

**文件**: `src/stores/layers/workflow-poller.ts:361`

**修复**: 添加 `.catch`:
```typescript
void deps.attachAlgorithmProductOverlays(run.result_refs, catalogId, run.run_id)
  .catch((err) => logger.warn('attachAlgorithmProductOverlays failed', err))
```

### 6.6 【低风险】DashboardView 异步初始化无卸载保护

**文件**: `src/views/DashboardView.vue:61-62`

**修复**: 添加 `isMounted` 检查：
```typescript
let isMounted = true
onBeforeUnmount(() => { isMounted = false })

void workspace.ensureRuntimeLayerCatalog().finally(() => {
  if (isMounted) uiLoading.hideImmediate()
})
```

### 6.7 【低风险】workflow-poller 轮询无全局停止

**文件**: `src/stores/layers/workflow-poller.ts:566-569`

**修复**: 在 DashboardView 的 `onBeforeUnmount` 中调用 `stopAllPolling()`（需新增方法），或依赖现有 `stopWorkflowPolling(jobId)` 逐个停止。

### 6.8 【极低风险】locationMarkerTimer 死变量

**文件**: `src/components/MapCanvas.vue:472`

**修复**: 移除未使用的 `locationMarkerTimer` 变量和相关清理代码。

### 验证命令

```bash
cd Code/frontend && npm run test
cd Code/frontend && npm run lint && npm run build
```

---

## 执行顺序与依赖

```
Phase 1 (底图) ──────────────────────────────────┐
Phase 2 (加载动画) ──────────────────────────────┤
Phase 3 (外圈背景) ───────────┐                   │
Phase 4 (mapDistributionChrome)│                   │
                               ↓                   │
                    Phase 5 (外观/主题)             │
                               │                   │
                               ↓                   ↓
                    Phase 6 (状态联动/异步) ────────┘
                               │
                               ↓
                        最终验证 (全量)
```

- Phase 1-4 可并行执行（无相互依赖）
- Phase 5 依赖 Phase 3（主题系统激活后才能修复外圈背景）和 Phase 4（mapDistributionChrome 移入外观设置）
- Phase 6 独立于其他 Phase，但建议最后执行以避免引入新的回归
- 每个 Phase 完成后运行 `npm run test && npm run lint && npm run build` 验证

## 文件变更清单

| Phase | 文件 | 变更类型 |
|-------|------|---------|
| 1 | `src/components/map/map-canvas-map-options.ts` | 修改：CSS 变量 → 字面量颜色 |
| 1 | `src/components/map/basemap-module.ts` | 修改：添加错误日志、502 熔断、降级逻辑 |
| 1 | `src/services/map-defaults.ts` | 修改：默认底图源可能调整 |
| 2 | `src/App.vue` | 验证/修改：LoadingOverlay 挂载 |
| 2 | `src/components/map/map-stage-presentation-module.ts` | 验证/修改：skeleton 时机 |
| 3 | `src/styles/main.css` | 修改：外圈背景渐变 |
| 3 | `src/App.vue` | 修改：激活 useThemeStore |
| 4 | `src/components/settings/GeneralSettings.vue` | 修改：添加说明文字/反馈 |
| 4 | `src/components/map/map-stage-view-model.ts` | 验证/修改：放宽条件 |
| 5 | `src/components/settings/AppearanceSettings.vue` | **新增** |
| 5 | `src/components/settings/GeneralSettings.vue` | 修改：移除地图显示区块 |
| 5 | `src/components/settings/SettingsPanel.vue` | 修改：添加"外观"tab |
| 5 | `src/components/ModeToolbar.vue` | 修改：添加主题切换按钮 |
| 5 | `src/stores/theme.ts` | 修改：添加"跟随系统"模式 |
| 5 | `src/components/MapCanvas.vue` | 修改：主题切换时更新背景色 |
| 6 | `src/views/dashboard/useMapInspect.ts` | 修改：清理 timer、修复竞态 |
| 6 | `src/components/MapCanvas.vue` | 修改：isMounted 检查、移除死变量 |
| 6 | `src/views/dashboard/useTimelineControls.ts` | 修改：添加防抖 |
| 6 | `src/stores/layers/workflow-poller.ts` | 修改：catch + 全局停止 |
| 6 | `src/views/DashboardView.vue` | 修改：isMounted 保护 |
