# Phase 4 UI 增强详细实施计划

## 摘要

本计划延续 Phase 3 的剩余工作，聚焦于工作流编辑器 UI 的四个方向增强：
1. **节点库增强**（WorkflowNodePalette.vue）— 引擎过滤、颜色标识、收藏夹、最近使用
2. **参数编辑增强**（WorkflowInspector.vue）— 参数分组、默认值对比、数组编辑器、tooltip
3. **工作流模板**（3 个新 JSON + WorkflowList.vue 模板分区）— 提供预制工作流供用户基于模板创建
4. **画布交互优化**（WorkflowCanvas.vue + litegraph-setup.ts）— 迷你地图、对齐辅助线、连接线悬停高亮

最后通过 vue-tsc + py_compile + JSON 校验完成验证。

---

## 当前状态分析

### 已完成（Phase 3 前期工作）
- 5 个算法文件合规性改造（physics/omega/block_inversion/ndvi/station/fy.py）
- 3 个 JSON 数据流修复（inversion_daily/block_inversion/omega_block 添加 time_range 端口和连接）
- 9 个 GIS 模块注册到 node_template_registry.py（第 826-999 行）
- 23 个未实现模块名添加到 _PENDING_IMPLEMENTATION_MODULES frozenset（python_provider_bridge_service.py）

### 现有 UI 状态（基于代码探索）

**WorkflowNodePalette.vue（节点库）**：
- 仅有搜索框 + 分类折叠
- 无引擎过滤标签
- 节点项无引擎色条标识
- 无收藏夹/最近使用功能
- 不持久化用户偏好

**WorkflowInspector.vue（属性检查器）**：
- 已有 4 个分区：节点描述/基本信息/输入端口/输出端口/自定义属性
- 已支持 enum(select)、boolean(toggle)、number(带 min/max/step)
- array 类型用 text input + placeholder（逗号分隔），缺乏专门编辑器
- 缺乏参数 tooltip 帮助图标
- 缺乏默认值对比指示
- 缺乏依赖联动（如 unit 改变时步长未对应变化）

**WorkflowList.vue（工作流列表）**：
- 仅两类分区：系统预设 / 用户工作流
- 无"模板库"分区
- 用户新建工作流时从空白开始，缺乏模板引导

**WorkflowCanvas.vue + litegraph-setup.ts（画布）**：
- 已有按引擎前缀的节点颜色（getEngineColor 函数，litegraph-setup.ts 第 191-203 行）
- 已有按端口类型的连接线颜色（getPortColor 函数，第 248-258 行）
- 已有框选、右键菜单、Delete 快捷键
- 未启用 LiteGraph 内置 minimap
- 拖动节点时无对齐辅助线
- 连接线悬停无高亮

---

## 实施方案

### 阶段 4.1：节点库增强（WorkflowNodePalette.vue）

**目标文件**：`Code/frontend/src/components/workflow/WorkflowNodePalette.vue`

**改动 1：引擎过滤标签栏**

在 `.palette-search` 下方新增 `.palette-engine-filters` 容器，包含 5 个过滤按钮：
- 全部（默认选中）
- 天气（filter: type 以 `weather/` 开头）
- Python（filter: type 以 `python_provider/` 开头）
- GEE（filter: type 以 `gee/` 开头）
- 通用（filter: type 不属于以上任何前缀）

新增 `activeEngineFilter` ref<string>('all')，修改 `filteredTemplatesByCategory` computed 加入引擎过滤逻辑。

按钮样式：圆角小标签，激活态用对应引擎色（weather=#ffb84d, python_provider=#78ffa0, gee=#5ad5ff, common=#88dfff）。

**改动 2：节点项引擎色条**

在 `.node-item` 内左侧添加 3px 宽的引擎色条（`.node-item-engine-bar`），使用 CSS `border-left: 3px solid <engineColor>`。

新增 `getEngineColor(nodeType: string): string` 工具函数（参考 litegraph-setup.ts 中已有实现，但简化为只返回 accent 色）：
```typescript
function getEngineAccentColor(nodeType: string): string {
  if (nodeType.startsWith('weather/')) return '#ffb84d'
  if (nodeType.startsWith('python_provider/')) return '#78ffa0'
  if (nodeType.startsWith('gee/')) return '#5ad5ff'
  return '#88dfff'
}
```

**改动 3：收藏夹功能**

新增 `favorites` ref<Set<string>>（存储 node.type），初始化时从 localStorage 读取 key `workflow_node_favorites`。

新增"★ 收藏"分区（位于搜索框下方、引擎过滤标签上方），仅当 favorites 非空时显示，列出所有收藏的节点模板。

节点项右上角添加星标按钮 `.node-item-favorite-btn`：
- 已收藏：★（金色 #ffd38a）
- 未收藏：☆（灰色 #5a7080）
- 点击切换收藏状态，阻止冒泡避免触发 addNode

新增 `toggleFavorite(type: string)` 方法，更新 Set 和 localStorage。

**改动 4：最近使用**

新增 `recentTypes` ref<string[]>（最多 10 个），初始化时从 localStorage 读取 key `workflow_node_recent`。

修改 `handleAddNode(template)` 方法：调用 emit 前将 template.type 插入 recentTypes 头部（去重，超出 10 个截断），同步到 localStorage。

新增"🕐 最近使用"分区（位于收藏夹分区下方），仅当 recentTypes 非空时显示。

**改动 5：分区折叠状态持久化**

将 `collapsedCategories` 持久化到 localStorage key `workflow_node_collapsed_categories`（JSON 数组形式）。

---

### 阶段 4.2：参数编辑增强（WorkflowInspector.vue）

**目标文件**：`Code/frontend/src/components/workflow/WorkflowInspector.vue`

**改动 1：参数分组**

在"自定义属性"section 内按参数类型分组显示：
- **基础参数**：string/number/boolean/enum 类型
- **高级参数**：array 类型、key 含 `_advanced` 后缀的参数
- **数据源参数**：key 为 `dataset_key`/`path`/`pattern` 的参数

新增 `groupedProperties` computed，返回 `{ basic: [key, value][], advanced: [key, value][], datasource: [key, value][] }`。

模板渲染时遍历三个分组，每组一个小标题（.param-group-title）。

**改动 2：默认值对比**

修改 `localProperties` watch 逻辑：除了深拷贝 properties，同时保存 `originalProperties`（即模板默认值或上次保存的值）。

每个参数项右侧添加"重置默认"按钮（↺ 图标），仅当当前值 ≠ 默认值时显示。点击后恢复默认值并触发 `handlePropertyChange`。

新增 `isModified(key: string): boolean` 方法对比 `localProperties[key]` 与 `originalProperties[key]`。修改过的参数 label 后显示 `*` 标记。

**改动 3：数组编辑器**

替换 array 类型的 text input 为专门的数组编辑器组件（内联实现，不新建文件）：

```vue
<div v-if="getParamMeta(String(key))?.type === 'array'" class="array-editor">
  <span v-for="(item, idx) in parseArrayValue(value)" :key="idx" class="array-chip">
    {{ item }}
    <button class="chip-remove" @click="removeArrayItem(key, idx)">✕</button>
  </span>
  <input
    v-model="arrayInputBuffer[String(key)]"
    class="array-input"
    placeholder="输入值后按回车添加"
    @keydown.enter="addArrayItem(key, $event)"
  />
</div>
```

新增方法：
- `parseArrayValue(value: unknown): string[]` — 将字符串（逗号分隔）或数组转为 string[]
- `addArrayItem(key, event)` — 将 input 值追加到数组，清空 input
- `removeArrayItem(key, idx)` — 从数组移除指定索引项

数组结果以 `string[]` 形式存储到 localProperties 并 emit。

**改动 4：参数 tooltip**

每个参数 label 旁添加信息图标（ⓘ），使用原生 `<span title="...">` 实现（避免引入第三方 tooltip 库）：

```vue
<span class="param-info-icon" :title="getParamTooltip(String(key))">ⓘ</span>
```

`getParamTooltip(key)` 合成完整描述：`description + (unit ? ' (单位: ' + unit + ')' : '') + (options ? '\n可选: ' + options.join(', ') : '')`。

**改动 5：物理单位提示强化**

修改 `getParamLabel(key)`：当存在 unit 时，label 后追加单位徽章（独立 span，而非字符串拼接）：

```vue
<label class="form-label">
  {{ getParamLabel(String(key)) }}
  <span v-if="getParamMeta(String(key))?.unit" class="param-unit-badge">
    {{ getParamMeta(String(key))?.unit }}
  </span>
</label>
```

CSS：`.param-unit-badge` 为浅色圆角小标签（rgba(90,213,255,0.18) 背景 + #5ad5ff 文字）。

---

### 阶段 4.3：工作流模板

**目标文件**：
- `Code/backend/.data/workflow_definitions/system/gis_terrain_analysis.json`（新建）
- `Code/backend/.data/workflow_definitions/system/preprocess_pipeline.json`（新建）
- `Code/backend/.data/workflow_definitions/system/stats_analysis.json`（新建）
- `Code/frontend/src/components/workflow/WorkflowList.vue`（修改）

**改动 1：创建 3 个新工作流模板 JSON**

**gis_terrain_analysis.json**（地形分析工作流）：
```
nodes:
  1. data/source (DEM 数据源, path: I:/Geograph_DataSet/DEM)
  2. data/time_range (时间范围)
  3. gis/slope_aspect (坡度坡向)
  4. gis/contour (等值线提取)
  5. output/map_layer (地图图层输出, layer_id: terrain-analysis)

links:
  [1,1,0,3,0,"data:raster"]
  [2,2,0,3,1,"value:time_range"]  # 注意：slope_aspect 只有 1 个 input，这里改为不连接 time_range
  [3,3,0,4,0,"data:raster"]
  [4,4,0,5,0,"data:geojson"]
```

实际等值线只有 1 个输入（raster），所以连接简化为：
```
links:
  [1,1,0,3,0,"data:raster"]   # source -> slope_aspect
  [2,3,0,4,0,"data:raster"]   # slope_aspect(slope输出) -> contour
  [3,4,0,5,0,"data:geojson"]  # contour -> output
```

**preprocess_pipeline.json**（预处理流水线）：
```
nodes:
  1. data/source (数据源)
  2. data/time_range (时间范围)
  3. preprocess/reproject (重投影)
  4. preprocess/resample (重采样)
  5. preprocess/clip (裁剪, 需要 bbox 输入)
  6. output/map_layer (输出)

links:
  [1,1,0,3,0,"data:raster"]   # source -> reproject
  [2,3,0,4,0,"data:raster"]   # reproject -> resample
  [3,4,0,5,0,"data:raster"]   # resample -> clip (raster 端口)
  # clip 的 bbox 端口需要用户手动连接或使用默认值
  [4,5,0,6,0,"data:raster"]   # clip -> output
```

**stats_analysis.json**（统计分析工作流）：
```
nodes:
  1. data/source (数据源)
  2. data/time_range (时间范围)
  3. stats/spatial_mean (空间均值)
  4. stats/histogram (直方图)
  5. stats/temporal_trend (时间趋势)
  6. output/map_layer (输出)

links:
  [1,1,0,3,0,"data:raster"]      # source -> spatial_mean
  [2,1,0,4,0,"data:raster"]      # source -> histogram
  [3,1,0,5,0,"data:timeseries"]  # source -> temporal_trend (注意：source 输出 raster，这里类型不匹配，应使用 data:source 兼容)
  [4,3,0,6,0,"value:number"]     # spatial_mean -> output (数值类型)
```

由于 source 输出 `data:source` 类型，而 spatial_mean/histogram 输入要求 `data:raster`，根据 checkConnectionValid 规则 `data <-> data:*` 允许（向后兼容），连接合法。

**改动 2：WorkflowList.vue 新增模板分区**

在 `.list-content` 内、系统预设 section 上方新增"📋 模板"section，仅当 templates 列表非空时显示。

新增 store getter `templateWorkflows`（按 _meta.kind === 'system' && workflow_id 包含 '_template' 后缀过滤，或新增 _meta.template === true 字段）。

实际上简化方案：直接在 WorkflowList.vue 中根据 workflow_id 前缀识别模板（如 `gis_terrain_analysis`/`preprocess_pipeline`/`stats_analysis` 这 3 个固定 ID），硬编码为模板列表。

更优方案：在 _meta 中新增 `is_template: true` 字段标记，store 中新增 `templateWorkflows` getter 过滤此字段。

每个模板项添加"使用此模板"按钮，点击后调用 `store.duplicate(templateId, newId, newName)` 创建用户工作流副本并自动选中。

---

### 阶段 4.4：画布交互优化

**目标文件**：
- `Code/frontend/src/components/workflow/litegraph-setup.ts`（修改）
- `Code/frontend/src/components/workflow/WorkflowCanvas.vue`（修改）

**改动 1：启用 LiteGraph 内置 minimap**

在 `configureCanvas(canvas)` 函数中添加：
```typescript
// 启用迷你地图（右上角小地图）
const canvasAny = canvas as unknown as {
  _minimap?: { visible: boolean; scale: number; location: string }
}
// LiteGraph 内置 minimap 通过设置 canvas 上的属性启用
// 实际上 LiteGraph 0.7+ 的 minimap 需要额外脚本，且当前版本可能不内置
// 改为自定义实现：在 WorkflowCanvas.vue 中添加 <div class="minimap"> 元素
```

由于 LiteGraph.js core 不内置 minimap，改为自定义实现：
- 在 WorkflowCanvas.vue 模板中添加 `<canvas ref="minimapRef" class="workflow-minimap">`
- 监听 graph 变化时绘制简化版节点位置预览（每秒最多 10 帧，用 setInterval 节流）
- minimap 点击/拖动同步主画布视口
- 默认尺寸 120×80px，位于画布右下角

**改动 2：对齐辅助线**

在 `enableCanvasInteractions(canvas)` 中 monkey-patch `_mousemove_callback`：

当节点被拖动时（`canvas.node_dragged` 非空），计算当前节点边缘与其他节点的水平/垂直对齐：
- 若当前节点左边缘 X 与其他节点左边缘 X 差值 < 5px，记录对齐线 {x, y1, y2}
- 若当前节点上边缘 Y 与其他节点上边缘 Y 差值 < 5px，记录对齐线 {y, x1, x2}
- 若当前节点中心 X 与其他节点中心 X 差值 < 5px，记录对齐线
- 若当前节点中心 Y 与其他节点中心 Y 差值 < 5px，记录对齐线

收集到的对齐线存入 `alignmentGuides` ref，在 LiteGraph 的 `onDrawOverlay` 回调中绘制：
```typescript
canvas.onDrawOverlay = (ctx: CanvasRenderingContext2D) => {
  if (!alignmentGuides.value.length) return
  ctx.save()
  ctx.strokeStyle = 'rgba(255, 184, 77, 0.6)'
  ctx.lineWidth = 1
  ctx.setLineDash([4, 4])
  for (const guide of alignmentGuides.value) {
    ctx.beginPath()
    if (guide.orientation === 'vertical') {
      ctx.moveTo(guide.pos, guide.start)
      ctx.lineTo(guide.pos, guide.end)
    } else {
      ctx.moveTo(guide.start, guide.pos)
      ctx.lineTo(guide.end, guide.pos)
    }
    ctx.stroke()
  }
  ctx.restore()
}
```

**改动 3：连接线悬停高亮**

monkey-patch `LLink.prototype.draw` 或在 `onDrawLink` 回调中检测鼠标位置与连接线距离：
- 若距离 < 5px，将连接线宽度从 2.2 增加到 4，颜色加亮 30%
- 显示连接线 tooltip（from_node.title → to_node.title）

实际实现：在 `configureCanvas` 中设置 `canvas.onDrawLink` 回调，根据 `canvas.mouse` 坐标判断悬停状态。

**改动 4：节点标题栏颜色更醒目**

修改 `getEngineColor` 函数（litegraph-setup.ts 第 191-203 行），将 nodeHeader 色调更鲜艳：
- weather: '#1e3a4a' → '#2a4a5a'（更亮）
- python_provider: '#1e3a28' → '#2a4a38'
- gee: '#2a1e4a' → '#3a2e5a'
- common: '#0f1828' → '#1a2540'

同时调整 NODE_TITLE_COLOR 配色，确保对比度。

**改动 5：新增快捷键**

在 `configureCanvas` 中添加 keydown 监听（仅在 canvas 获得焦点时生效）：
- `Ctrl+A`：全选所有节点
- `Ctrl+C`：复制选中节点到剪贴板（存入 component-level 变量）
- `Ctrl+V`：粘贴剪贴板节点（偏移 20px 避免重叠）
- `Ctrl+D`：复制选中节点（同位置偏移）
- `Escape`：取消选中

剪贴板存储在 WorkflowCanvas.vue 的 module-level 变量 `_clipboard: WorkflowDefinitionNode[]`。

---

### 阶段 6：验证

**步骤 1：前端类型检查**
```bash
cd Code/frontend
npx vue-tsc --noEmit
```

**步骤 2：后端编译检查**
```bash
cd Code/backend
python -m py_compile app/services/python_provider_bridge_service.py
python -m py_compile app/services/node_template_registry.py
```

**步骤 3：JSON 文件校验**
```bash
python -c "import json; [json.load(open(f, encoding='utf-8')) for f in [
  'Code/backend/.data/workflow_definitions/system/gis_terrain_analysis.json',
  'Code/backend/.data/workflow_definitions/system/preprocess_pipeline.json',
  'Code/backend/.data/workflow_definitions/system/stats_analysis.json',
]]"
```

**步骤 4：浏览器手动验证**

启动前端开发服务器（已运行则刷新 http://localhost:5175/）：
1. 打开流配置面板
2. 验证节点库：引擎过滤标签可切换、节点项左侧有色条、星标收藏可点击、最近使用分区显示添加过的节点
3. 验证属性检查器：选中节点后参数按基础/高级/数据源分组、有单位徽章、有 ⓘ tooltip、修改过的参数显示 *、array 类型有 chip 编辑器
4. 验证工作流列表：模板分区显示 3 个新模板、点击"使用此模板"创建用户工作流副本
5. 验证画布：右下角显示 minimap、拖动节点时显示橙色对齐线、连接线悬停高亮、Ctrl+A/C/V 快捷键可用

---

## 假设与决策

### 假设
1. **localStorage 可用**：浏览器环境支持 localStorage（已在前端代码中使用）
2. **LiteGraph 版本兼容**：当前 LiteGraph.js 版本支持 `onDrawOverlay` 和 `onDrawLink` 回调（基于现有代码已 monkey-patch 多个回调，假设可行）
3. **后端 stub 拦截已生效**：_PENDING_IMPLEMENTATION_MODULES 已包含所有未实现模块，新增模板运行时会返回 `pending_implementation` 状态（预期行为）
4. **前端 HMR 自动刷新**：Vite 开发服务器已运行，文件修改后自动热更新

### 决策
1. **不引入新依赖**：minimap、对齐线、数组编辑器均自定义实现，避免增加包体积
2. **模板识别方式**：使用 _meta 新增 `is_template: true` 字段标记模板（比 workflow_id 前缀更灵活）
3. **localStorage key 命名**：统一使用 `workflow_node_*` 前缀（favorites/recent/collapsed_categories）
4. **快捷键作用域**：仅在 canvas 容器获得焦点时生效（避免与浏览器全局快捷键冲突）
5. **minimap 节流**：使用 setInterval 100ms 节流（10 FPS），避免主画布渲染阻塞
6. **对齐线触发阈值**：5px（参考 Figma/Sketch 等设计工具的常见值）
7. **数组编辑器存储格式**：以 `string[]` 存储（而非逗号分隔字符串），后端可原生处理数组

### 风险与缓解
1. **风险**：LiteGraph onDrawOverlay 回调可能不存在或签名不同
   **缓解**：在调用前检查 `typeof canvas.onDrawOverlay`，不存在时跳过对齐线绘制功能
2. **风险**：minimap 自定义实现可能影响主画布渲染性能
   **缓解**：使用独立 canvas 元素 + setInterval 节流，不与主画布共享渲染循环
3. **风险**：Ctrl+A/C/V 快捷键可能与浏览器/输入框冲突
   **缓解**：监听 keydown 时检查 `document.activeElement` 是否为 INPUT/TEXTAREA/SELECT，是则不拦截

---

## 执行顺序

1. **阶段 4.1** → 修改 `WorkflowNodePalette.vue`（节点库增强）
2. **阶段 4.2** → 修改 `WorkflowInspector.vue`（参数编辑增强）
3. **阶段 4.3** → 创建 3 个 JSON + 修改 `WorkflowList.vue`（工作流模板）
4. **阶段 4.4** → 修改 `litegraph-setup.ts` + `WorkflowCanvas.vue`（画布交互优化）
5. **阶段 6** → 验证（vue-tsc + py_compile + JSON 校验 + 浏览器手动验证）

阶段 4.1-4.4 相互独立，可按顺序串行执行（每个阶段完成后标记 todo 完成）。阶段 6 必须在所有改动完成后执行。
