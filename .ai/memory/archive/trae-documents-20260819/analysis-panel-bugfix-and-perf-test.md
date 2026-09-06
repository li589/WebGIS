# 分析面板 Bug 修复与 GPU 性能检测功能实现计划

## 概述

本计划覆盖 5 个 Bug 修复、2 项体验优化和 1 个新功能（GPU 性能检测）。所有改动均基于对现有代码结构的详细探查，遵循项目既有模式（Vue 3 + TypeScript + MapLibre、Conventional Commits、token 设计系统、Teleport 模态对话框模式）。

---

## Bug 1：分析工具 "Unexpected token '<'" 错误

### 根因

`Code/frontend/src/services/analysis-api.ts` 第 80 行向 `/analysis/tools` 发起请求，但 `Code/frontend/vite.config.ts` 的 proxy 配置（第 25-54 行）缺少 `/analysis` 路径。Vite dev server 无法匹配该路径时返回 `index.html`（200 text/html），前端 `JSON.parse()` 该 HTML 即抛出 `Unexpected token '<'`。

后端已注册 `analysis_router`（`Code/backend/app/main.py` 第 274 行），路由前缀为 `/analysis`。

### 修改

**文件**：`Code/frontend/vite.config.ts`

在 proxy 对象中（`/health` 之前）添加：

```typescript
'/analysis': { target: apiTarget, changeOrigin: true },
```

### 验证

1. 重启 Vite dev server
2. 打开 InfoPanel 工具 Tab，确认分析工具列表正常加载（无控制台 `Unexpected token` 错误）
3. 浏览器 DevTools Network 面板确认 `/analysis/tools` 请求被代理到 `127.0.0.1:8000` 且返回 `application/json`
4. `cd Code/frontend && npm run test`

---

## Bug 2：调节透明度时图层配色方案突变

### 根因

`Code/frontend/src/components/map/map-canvas-non-weather-layer-sync-module.ts` 第 157-172 行的 watcher 将 `opacity` 与样式字段合并在同一个监听字符串中。当用户仅调节透明度滑块时：

1. watcher 触发 `syncOverlayLayers()`
2. `syncOverlayLayers()` 第 67-80 行从**用户覆盖字段**重建 `styleParams`——当无覆盖时，`palette`/`vmin`/`vmax` 均为 `undefined`，`forceStyle` 为 `false`
3. `syncOverlays()`（overlay-image-module.ts 第 833-835 行）调用 `setOverlayStyle(layerId, style)`
4. `setOverlayStyle()`（第 959-966 行）比较 `styleKeyOf(style)`——新 key 为 `|||||0`（空），已加载 key 为 `viridis|...|1`（含 meta palette），不匹配
5. 触发完整重渲染，使用"裸"样式（无 palette query params），后端回退默认配色

初始加载时（`_addOverlay()` 第 723-732 行），meta 增强的样式（`meta.palette`、`meta.vmin`、`meta.vmax`、`forceStyle=true`）被注入。

### 修改（Plan A：分离透明度 watcher）

**文件**：`Code/frontend/src/components/map/map-canvas-non-weather-layer-sync-module.ts`

**步骤 1**：新增 `syncOverlayOpacity()` 函数，仅调用 `setOverlayOpacity()`（仅设 `raster-opacity` paint 属性，不触发 `setOverlayStyle`）。

**步骤 2**：将原 watcher 拆分为两个独立 watcher：
- **透明度专用 watcher**：仅监听 `opacity` 字段变化，调用 `syncOverlayOpacity()`
- **样式/结构 watcher**：监听 `instanceId`、`catalogId`、`visible`、`importedRaster` 标记及全部样式字段，但**不包含** `opacity`，调用 `syncOverlayLayers()`

**步骤 3（防御性加固）**：在 `overlay-image-module.ts` 的 `syncOverlays()` 中，仅当 `style.forceStyle` 为 true 时才调用 `setOverlayStyle()`，避免无用户覆盖时误触发。

### 验证

1. 加载有源 overlay 图层（如 NDVI 或温度图层），确认初始配色正确
2. 调节透明度滑块，确认**配色不变**、仅透明度变化、无瓦片重新请求
3. 切换图层显隐，确认配色不变
4. 更换调色板，确认配色正确更新
5. `cd Code/frontend && npm run test`

---

## Bug 3：NaN 透明度下拉框过高

### 根因

`Code/frontend/src/components/info-panel/InfoPanelStyleTab.vue` 第 398 行的 `AppSelect` 未传 `size` 属性，默认 `size="md"`（36px 高度），而相邻标签使用 `var(--font-size-caption)`（12px），视觉上不协调。

### 修改

**文件**：`Code/frontend/src/components/info-panel/InfoPanelStyleTab.vue`

给第 398 行的 `<AppSelect>` 添加 `size="sm"`（对应 30px 高度）：

```vue
<AppSelect
  v-model="nodataModeValue"
  size="sm"
  :options="[...]"
  title="无效像元显示"
/>
```

### 验证

1. 选中可编辑配色的栅格图层，打开样式 Tab
2. 确认 "无效值 (NaN)" 下拉框高度与相邻文本对齐
3. `cd Code/frontend && npm run lint`

---

## Bug 4：图层单位显示不一致

### 根因

`Code/backend/app/catalog_seeds/weather_descriptors.json` 中 `style.unit_label` 与 `presentation.metric_unit` 不一致：
- 温度类图层（4 个）：`unit_label` = `"degC"`，`metric_unit` = `"°C"`
- 露点温度图层：`unit_label` = `"C"`，`metric_unit` = `"°C"`

前端 `useLayerSymbology.ts` 第 130 行优先取 `unit_label`，显示为 "degC" 或 "C" 而非 "°C"。

### 修改（双管齐下）

#### 4a. 后端数据修正

**文件**：`Code/backend/app/catalog_seeds/weather_descriptors.json`

将所有 `style.unit_label` 中的 `"degC"` 替换为 `"°C"`（4 处），将 `"C"` 替换为 `"°C"`（1 处）。

#### 4b. 前端单位归一化

**文件**：`Code/frontend/src/components/info-panel/useLayerSymbology.ts`

添加单位归一化映射函数：

```typescript
const UNIT_NORMALIZE_MAP: Record<string, string> = {
  degC: '°C',
  degF: '°F',
  C: '°C',
  F: '°F',
  ms: 'm/s',
  'm/s2': 'm/s²',
}

function normalizeUnit(raw: string | null | undefined): string {
  if (!raw) return ''
  return UNIT_NORMALIZE_MAP[raw.trim()] ?? raw.trim()
}
```

在 `styleRangeMeta` computed 中应用：`const unit = normalizeUnit(hint?.unit_label || meta?.unit || '')`

新增 `normalizedUnitLabel` computed 用于图例区域显示。

对于无法确定单位的值，模板中已有空值兜底，可按需改为 `'—'` 占位符。

### 验证

1. 后端：`Env/Python312/python.exe -m pytest Test/backend -q -k "weather" --tb=short`
2. 前端：`cd Code/frontend && npm run test`
3. 联调：加载温度图层，确认单位显示为 "°C"
4. `cd Code/frontend && npm run check:catalog`

---

## Bug 5：配色方案下拉框在面板底部被裁剪

### 根因

`Code/frontend/src/components/info-panel/InfoPanel.styles.css` 第 1261-1278 行 `.palette-dropdown` 使用 `position: absolute; top: 100%`，始终向下展开。`.panel-scroll`（第 211-220 行）设置了 `overflow-y: auto`，裁剪超出容器的绝对定位元素。无翻转逻辑。

### 修改（JS 动态定位）

**文件**：`Code/frontend/src/components/info-panel/InfoPanelStyleTab.vue`

**步骤 1**：添加动态定位逻辑：

```typescript
const paletteDropdownRef = ref<HTMLElement | null>(null)
const dropdownOpenUp = ref(false)

watch(paletteDropdownOpen, async (open) => {
  if (!open) return
  await nextTick()
  const el = paletteDropdownRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom
  const dropdownH = el.offsetHeight
  dropdownOpenUp.value = spaceBelow < dropdownH + 8 && rect.top > dropdownH + 8
})
```

**步骤 2**：模板中给 dropdown 添加 ref 和动态 class：

```vue
<div ref="paletteDropdownRef" class="palette-dropdown" :class="{ 'palette-dropdown--up': dropdownOpenUp }">
```

**步骤 3**：CSS 中添加向上展开样式：

```css
.palette-dropdown--up {
  top: auto;
  bottom: 100%;
  margin-top: 0;
  margin-bottom: 0.2rem;
}
```

**步骤 4**：面板滚动时自动关闭下拉框（监听 `.panel-scroll` 的 scroll 事件）。

### 验证

1. 滚动 InfoPanel 到底部使配色选择器靠近面板底边
2. 点击展开配色下拉框，确认向上展开、不被裁剪
3. 在面板中部展开，确认正常向下展开
4. 展开后面板滚动，确认下拉框自动关闭
5. `cd Code/frontend && npm run lint && npm run build`

---

## Other 1：暗色模式面板背景过暗

### 根因

`tokens.css` 第 75、81 行：`--surface-sunken: rgba(4, 12, 23, 0.5)` 和 `--surface-raised: rgba(4, 12, 23, 0.6)`。InfoPanel 和 LayerSidebar 均使用这两个 token 的渐变作为背景，暗色模式下几乎看不到底图。

### 修改（面板专用 token）

**文件**：`Code/frontend/src/styles/tokens.css`

在 `:root`（暗色）中新增：

```css
--panel-bg-top: rgba(10, 20, 35, 0.75);
--panel-bg-bottom: rgba(10, 20, 35, 0.65);
```

在 `[data-theme='light']` 中添加：

```css
--panel-bg-top: rgba(248, 251, 255, 0.92);
--panel-bg-bottom: rgba(240, 246, 252, 0.86);
```

**文件**：`Code/frontend/src/components/info-panel/InfoPanel.styles.css`（第 180 行）

```css
background: linear-gradient(180deg, var(--panel-bg-top), var(--panel-bg-bottom));
```

**文件**：`Code/frontend/src/components/layer-sidebar/LayerSidebar.styles.css`（第 13 行）

同上修改。

### 验证

1. 暗色模式：确认 InfoPanel 和 LayerSidebar 背景更通透，能隐约看到底图
2. 浅色模式：确认面板背景仍保持可读性
3. 其他使用 `--surface-raised`/`--surface-sunken` 的组件不受影响
4. `cd Code/frontend && npm run build`

---

## Other 2：系统 CPU 始终显示 0%

### 根因

`Code/backend/app/services/workflow/runtime_status_service.py` 第 312 行 `psutil.cpu_percent(interval=None)` 首次调用返回 0.0（psutil 语义：非阻塞模式需两次调用间隔才有值）。TTL 缓存 5s，首次调用后缓存 0.0。后端重启或多 worker 时每个进程首次调用均为 0.0。

### 修改

**文件**：`Code/backend/app/main.py`

在 `lifespan()` 函数中添加 psutil 预热调用（同步执行，非阻塞）：

```python
try:
    import psutil
    psutil.cpu_percent(interval=None)
    logger.debug("psutil cpu_percent warmup done")
except Exception:
    logger.debug("psutil warmup skipped")
```

放置位置：lifespan 开头，warmup 线程启动后。

### 验证

1. 后端：`Env/Python312/python.exe -m pytest Test/backend -q -k "runtime_status or resource" --tb=short`
2. 重启后端：`launch.py restart backend`
3. 打开设置 → 系统状态，确认系统 CPU 显示非 0 值
4. 等待 60s 后再次刷新，确认 CPU 数值有变化

---

## Other 3：GPU 性能检测按钮与对话框

### 需求

在 `SystemResourceMetrics.vue` 的 GPU 信息行右侧添加 "性能检测" 按钮，点击后弹出对话框执行浏览器图形性能测试。测试期间暂停地图渲染、天气瓦片、动画等性能消耗项。纯前端功能，不保存到后端。

### 修改

#### 3a. 新建 GPU 性能检测对话框组件

**新文件**：`Code/frontend/src/components/settings/GpuPerfTestDialog.vue`

遵循项目中 `NodeCacheDialog.vue` 的 Teleport 模态模式。

**组件结构**：
- `defineProps<{ open: boolean }>()` + `defineEmits<{ close: [] }>()`
- 测试状态管理：`idle` / `running` / `done`
- 4 项测试：
  1. **WebGL 渲染速度**：创建离屏 WebGL canvas，绘制 1000 帧带纹理三角形，测量平均帧耗时（ms）和吞吐量（FPS）
  2. **Canvas 2D 填充速率**：创建离屏 2D canvas，连续 fillRect 10000 次，测量吞吐量（ops/s）
  3. **动画帧率（RAF FPS）**：使用 requestAnimationFrame 循环 3 秒，统计实际 FPS（≥55 pass, 30-54 warn, <30 fail）
  4. **GPU 信息详情**：获取 WebGL renderer/vendor、MAX_TEXTURE_SIZE、扩展列表等
- 进度条显示
- 结果报告列表（name / value / detail / status）
- 开始检测按钮、关闭按钮

**模板**（遵循 NodeCacheDialog 模式）：
```vue
<Teleport to="body">
  <div v-if="props.open" class="gpu-modal-mask" @click.self="emit('close')">
    <div class="gpu-modal" role="dialog">
      <!-- header / intro / progress / results / empty -->
    </div>
  </div>
</Teleport>
```

**样式**：使用 `<style scoped>`，遵循 token 设计系统。

#### 3b. 在 SystemResourceMetrics.vue 中集成

**文件**：`Code/frontend/src/components/settings/SystemResourceMetrics.vue`

1. 导入 `GpuPerfTestDialog`，添加 `gpuPerfDialogOpen` 状态
2. 在 GPU metric-row（第 213-220 行）的 `.metric-main` div 内，GPU 名称 span 之后添加按钮：

```vue
<button class="gpu-perf-btn" type="button" @click="gpuPerfDialogOpen = true">
  性能检测
</button>
```

3. 模板末尾添加 `<GpuPerfTestDialog :open="gpuPerfDialogOpen" @close="gpuPerfDialogOpen = false" />`
4. 添加按钮样式（`var(--accent-surface)` / `var(--accent-strong)` / 右对齐 `margin-left: auto`）

#### 3c. 测试期间暂停页面性能消耗项

通过自定义事件通知地图组件暂停：

```typescript
// GpuPerfTestDialog.vue runAllTests() 中
window.dispatchEvent(new CustomEvent('cgda:perf-test-start'))
try {
  // ... 运行测试 ...
} finally {
  window.dispatchEvent(new CustomEvent('cgda:perf-test-end'))
}
```

在 `Code/frontend/src/views/DashboardView.vue` 或 `usePanelManager.ts` 中监听该事件，调用 `mapCanvasRef.value?.setWindAnimationPaused?.(true)` 并暂停 weather tile manager 视口更新。测试结束后恢复。

### 验证

1. 打开设置 → 系统状态，确认 GPU 行右侧出现"性能检测"按钮
2. 点击按钮，确认对话框弹出
3. 点击"开始检测"，确认：
   - 地图动画暂停（风场粒子流停止）
   - 天气瓦片更新暂停
   - 进度条正常推进
   - 4 项测试均有结果输出
4. 测试完成后，确认地图动画和瓦片更新恢复
5. 关闭并重新打开对话框，确认状态正确
6. `cd Code/frontend && npm run lint && npm run build && npm run test`

---

## 实施顺序

按依赖关系和风险程度排序：

1. **Bug 1**（vite proxy）— 最低风险，一行改动
2. **Bug 3**（AppSelect size）— 最低风险，一个属性
3. **Other 2**（CPU 预热）— 低风险，后端启动逻辑
4. **Bug 4**（单位归一化）— 低风险，后端 JSON + 前端映射
5. **Other 1**（暗色面板背景）— 低风险，CSS token 新增
6. **Bug 5**（下拉框翻转）— 中风险，JS 定位逻辑
7. **Bug 2**（透明度 watcher 拆分）— 中高风险，核心地图渲染逻辑
8. **Other 3**（GPU 性能检测）— 新功能，新组件 + 跨组件事件

## 提交规范

遵循 Conventional Commits：

- `fix(frontend): add /analysis proxy to vite dev server config`
- `fix(map): separate opacity watcher to prevent style reset on transparency change`
- `fix(info-panel): add size=sm to NaN nodata-mode AppSelect`
- `fix(layers): normalize inconsistent temperature unit labels (degC/C → °C)`
- `fix(info-panel): add dynamic flip-up for palette dropdown at panel bottom`
- `style(theme): introduce panel-specific bg tokens for lighter dark-mode panels`
- `fix(backend): warmup psutil cpu_percent at startup to avoid 0% report`
- `feat(settings): add GPU performance test dialog with WebGL/canvas/FPS benchmarks`

## 验证总览

完成所有修改后执行：

```bash
# 前端
cd Code/frontend && npm run lint && npm run build && npm run test

# 后端
Env/Python312/python.exe -m pytest Test/backend -q -k "runtime_status or weather" --tb=short

# 契约检查
cd Code/frontend && npm run check:catalog && npm run check:openapi
```
