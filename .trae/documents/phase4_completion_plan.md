# Phase 4 UI 增强 — 完成计划（剩余工作）

## 摘要

本计划延续上一轮已批准的 `system_optimization_phase4_ui_enhancement.md`，
仅聚焦于**尚未完成**的三个阶段，避免重复已完成的工作：

1. **阶段 4.3 收尾**：WorkflowList.vue 的 `<template>` 部分修改（脚本部分已完成）
2. **阶段 4.4**：画布交互优化（litegraph-setup.ts + WorkflowCanvas.vue）— minimap、对齐辅助线、连接线悬停高亮、节点标题颜色、快捷键
3. **阶段 6**：验证（vue-tsc + py_compile + JSON 校验）

---

## 当前状态分析

### 已完成（无需重复）

- ✅ 阶段 4.1：WorkflowNodePalette.vue 完全重写（引擎过滤、颜色标识、收藏夹、最近使用、折叠持久化）
- ✅ 阶段 4.2：WorkflowInspector.vue 完全重写（参数分组、默认值对比、数组编辑器、tooltip、单位徽章）
- ✅ 阶段 4.3 (部分)：
  - 3 个模板 JSON 已创建（`gis_terrain_analysis.json` / `preprocess_pipeline.json` / `stats_analysis.json`），均含 `_meta.is_template: true`
  - WorkflowList.vue `<script setup>` 已添加：`TEMPLATE_IDS` 常量、`templateWorkflows` / `systemWorkflowsNonTemplate` computed、`useTemplateSourceId` / `useTemplateNewId` / `useTemplateNewName` refs、`handleUseTemplate()` / `confirmUseTemplate()` / `cancelUseTemplate()` 方法

### 剩余工作

**阶段 4.3 模板部分**：WorkflowList.vue `<template>` 中：
- 当前仍使用 `systemWorkflows`（storeToRefs 暴露的原始系统工作流列表）渲染系统预设 section
- 缺少"📋 模板"独立 section
- 缺少使用模板确认对话框

**阶段 4.4 画布交互**：
- `litegraph-setup.ts` 第 191-203 行 `getEngineColor()` 配色偏暗（标题栏色 `#0f1828` / `#1e3a28` / `#1e3a4a` / `#2a1e4a`），不够醒目
- `WorkflowCanvas.vue` `configureCanvas()` 仅配置基本交互（框选/右键平移/右键菜单/Delete 快捷键），缺：
  - minimap（右下角小地图预览）
  - 拖动节点时的对齐辅助线
  - 连接线悬停高亮
  - Ctrl+A/C/V/D 等编辑快捷键

---

## 实施方案

### 阶段 4.3 收尾：WorkflowList.vue 模板 UI

**目标文件**：`Code/frontend/src/components/workflow/WorkflowList.vue`（仅修改 `<template>` 部分）

#### 改动 1：新增"📋 模板" section

在 `.list-content` 内、系统预设 section（第 156-184 行）**上方**插入：

```vue
<!-- 模板工作流 -->
<section v-if="templateWorkflows.length" class="list-section">
  <h3 class="section-title">
    <span class="section-icon" aria-hidden="true">📋</span>
    <span>模板</span>
    <span class="section-count">{{ templateWorkflows.length }}</span>
  </h3>
  <div class="section-items">
    <button
      v-for="summary in templateWorkflows"
      :key="summary.workflow_id"
      class="workflow-item template-item"
      :class="{ active: isActive(summary) }"
      type="button"
      @click="handleSelect(summary)"
    >
      <div class="item-header">
        <span class="item-title">{{ summary.name }}</span>
        <span class="template-badge">模板</span>
      </div>
      <div v-if="summary.description" class="item-desc">{{ summary.description }}</div>
      <div class="item-meta">
        <span class="meta-engine">{{ summary.engine }}</span>
        <span class="meta-nodes">{{ summary.node_count }} 节点</span>
      </div>
      <button
        class="use-template-btn"
        type="button"
        title="基于此模板创建新工作流"
        @click.stop="handleUseTemplate(summary)"
      >
        <span aria-hidden="true">⚡</span>
        <span>使用此模板</span>
      </button>
    </button>
  </div>
</section>
```

#### 改动 2：系统预设 section 改用 `systemWorkflowsNonTemplate`

将第 157 行 `v-if="systemWorkflows.length"` 改为 `v-if="systemWorkflowsNonTemplate.length"`；
第 161 行 `{{ systemWorkflows.length }}` 改为 `{{ systemWorkflowsNonTemplate.length }}`；
第 165 行 `v-for="summary in systemWorkflows"` 改为 `v-for="summary in systemWorkflowsNonTemplate"`。

#### 改动 3：新增"使用模板"对话框

在复制对话框（第 253-271 行）之后插入：

```vue
<!-- 使用模板对话框 -->
<div v-if="useTemplateSourceId" class="dialog-overlay" @click.self="cancelUseTemplate">
  <div class="dialog">
    <h3 class="dialog-title">基于模板创建工作流</h3>
    <p class="dialog-text">
      将基于模板 "{{ useTemplateSourceId }}" 创建一个新的用户工作流副本，您可在副本上自由修改。
    </p>
    <div class="dialog-form">
      <div class="form-row">
        <label class="form-label">新工作流 ID</label>
        <input v-model="useTemplateNewId" type="text" class="form-input" placeholder="workflow_id" />
      </div>
      <div class="form-row">
        <label class="form-label">新名称（可选）</label>
        <input v-model="useTemplateNewName" type="text" class="form-input" placeholder="显示名称" />
      </div>
    </div>
    <div class="dialog-actions">
      <button class="dialog-btn cancel" type="button" @click="cancelUseTemplate">取消</button>
      <button
        class="dialog-btn primary"
        type="button"
        :disabled="!useTemplateNewId.trim()"
        @click="confirmUseTemplate"
      >
        创建
      </button>
    </div>
  </div>
</div>
```

#### 改动 4：新增样式

在 `<style scoped>` 末尾追加：

```css
/* 模板项样式 */
.template-item {
  position: relative;
}

.template-badge {
  padding: 0.02rem 0.32rem;
  border-radius: 0.2rem;
  background: rgba(255, 184, 77, 0.16);
  color: #ffd38a;
  font-size: 0.5rem;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.use-template-btn {
  margin-top: 0.32rem;
  padding: 0.28rem 0.5rem;
  border: 1px dashed rgba(255, 184, 77, 0.4);
  border-radius: 0.32rem;
  background: rgba(255, 184, 77, 0.06);
  color: #ffd38a;
  cursor: pointer;
  font: inherit;
  font-size: 0.56rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.22rem;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.use-template-btn:hover {
  background: rgba(255, 184, 77, 0.16);
  border-color: rgba(255, 184, 77, 0.6);
}
```

---

### 阶段 4.4：画布交互优化

**目标文件 1**：`Code/frontend/src/components/workflow/litegraph-setup.ts`

#### 改动 1：调整 `getEngineColor()` 配色（第 191-203 行）

将标题栏色调亮一档以提升可读性：

```typescript
function getEngineColor(nodeType: string): EngineColor {
  if (nodeType.startsWith('weather/')) {
    return { nodeBg: '#1a2230', nodeHeader: '#2a4a5a', accent: '#ffb84d' }
  }
  if (nodeType.startsWith('python_provider/')) {
    return { nodeBg: '#1a2a1e', nodeHeader: '#2a4a38', accent: '#78ffa0' }
  }
  if (nodeType.startsWith('gee/')) {
    return { nodeBg: '#1a2030', nodeHeader: '#3a2e5a', accent: '#5ad5ff' }
  }
  // general / common
  return { nodeBg: '#1a2740', nodeHeader: '#1a2540', accent: '#88dfff' }
}
```

**目标文件 2**：`Code/frontend/src/components/workflow/WorkflowCanvas.vue`

#### 改动 2：minimap 实现（自定义独立 canvas）

**模板**：在 `.workflow-canvas-container`（第 655 行）末尾添加：

```vue
<canvas
  ref="minimapRef"
  class="workflow-minimap"
  width="160"
  height="100"
  aria-hidden="true"
/>
```

**脚本**：
- 新增 `const minimapRef = ref<HTMLCanvasElement | null>(null)`
- 新增 `let _minimapTimer: ReturnType<typeof setInterval> | null = null`
- 新增 `drawMinimap()` 函数：清空 minimap canvas → 计算所有节点的 bbox → 按比例缩放绘制每个节点的矩形（用引擎色）+ 当前视口框（橙色矩形）
- 在 `initializeCanvas()` 末尾启动：`_minimapTimer = setInterval(drawMinimap, 200)`（5 FPS，节流）
- 在 `onBeforeUnmount` 中 `clearInterval(_minimapTimer)`
- 添加 minimap 点击/拖动同步主视口：监听 `mousedown` 转换坐标后设置 `canvas.ds.offset`，并 `setDirty(true, true)`

**样式**：
```css
.workflow-minimap {
  position: absolute;
  right: 0.6rem;
  bottom: 0.6rem;
  width: 160px;
  height: 100px;
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.32rem;
  background: rgba(8, 15, 28, 0.85);
  pointer-events: auto;
  cursor: pointer;
  z-index: 5;
}
```

#### 改动 3：对齐辅助线

**状态**：新增 `const alignmentGuides = ref<Array<{ orientation: 'vertical' | 'horizontal'; pos: number; start: number; end: number }>>([])`

**实现**：在 `configureCanvas()` 中 monkey-patch `canvas.onNodeMoved`（已有），新增逻辑：

```typescript
// 计算当前节点与其他节点的对齐
function computeAlignmentGuides(draggedNode: LGraphNodeClass) {
  if (!graphInstance.value) return
  const guides: Array<{ orientation: 'vertical' | 'horizontal'; pos: number; start: number; end: number }> = []
  const others = graphInstance.value._nodes.filter((n) => n.id !== draggedNode.id)
  const threshold = 5
  const d = draggedNode
  const dLeft = d.pos[0]
  const dTop = d.pos[1]
  const dW = d.size?.[0] ?? 200
  const dH = d.size?.[1] ?? 100
  const dRight = dLeft + dW
  const dBottom = dTop + dH
  const dCenterX = dLeft + dW / 2
  const dCenterY = dTop + dH / 2

  for (const o of others) {
    const oLeft = o.pos[0]
    const oTop = o.pos[1]
    const oW = o.size?.[0] ?? 200
    const oH = o.size?.[1] ?? 100
    const oRight = oLeft + oW
    const oBottom = oTop + oH
    const oCenterX = oLeft + oW / 2
    const oCenterY = oTop + oH / 2

    // 垂直对齐线
    const xCandidates = [oLeft, oRight, oCenterX]
    const dXs = [dLeft, dRight, dCenterX]
    for (const xc of xCandidates) {
      for (const dx of dXs) {
        if (Math.abs(xc - dx) < threshold) {
          const x = xc
          const yStart = Math.min(dTop, oTop)
          const yEnd = Math.max(dBottom, oBottom)
          guides.push({ orientation: 'vertical', pos: x, start: yStart, end: yEnd })
        }
      }
    }
    // 水平对齐线
    const yCandidates = [oTop, oBottom, oCenterY]
    const dYs = [dTop, dBottom, dCenterY]
    for (const yc of yCandidates) {
      for (const dy of dYs) {
        if (Math.abs(yc - dy) < threshold) {
          const y = yc
          const xStart = Math.min(dLeft, oLeft)
          const xEnd = Math.max(dRight, oRight)
          guides.push({ orientation: 'horizontal', pos: y, start: xStart, end: xEnd })
        }
      }
    }
  }
  alignmentGuides.value = guides
}
```

**绘制**：在 `configureCanvas()` 中设置 `canvas.onDrawOverlay`：

```typescript
;(canvas as unknown as { onDrawOverlay?: (ctx: CanvasRenderingContext2D) => void }).onDrawOverlay = (ctx: CanvasRenderingContext2D) => {
  if (!alignmentGuides.value.length) return
  ctx.save()
  ctx.strokeStyle = 'rgba(255, 184, 77, 0.7)'
  ctx.lineWidth = 1
  ctx.setLineDash([4, 4])
  for (const g of alignmentGuides.value) {
    ctx.beginPath()
    if (g.orientation === 'vertical') {
      ctx.moveTo(g.pos, g.start)
      ctx.lineTo(g.pos, g.end)
    } else {
      ctx.moveTo(g.start, g.pos)
      ctx.lineTo(g.end, g.pos)
    }
    ctx.stroke()
  }
  ctx.restore()
}
```

**清理**：在 `onNodeMoved` 之后或 `mouseup` 时清空 `alignmentGuides.value = []`。可监听 canvas 的 mouseup：

```typescript
canvasRef.value?.addEventListener('mouseup', () => {
  alignmentGuides.value = []
}, { once: false })
```

#### 改动 4：连接线悬停高亮

在 `configureCanvas()` 中设置 `canvas.onDrawLink`：

```typescript
;(canvas as unknown as {
  onDrawLink?: (link: unknown, ctx: CanvasRenderingContext2D) => void
}).onDrawLink = (link: unknown, ctx: CanvasRenderingContext2D) => {
  // LiteGraph 已完成默认绘制，这里仅对悬停连接加粗
  const canvasAny = canvas as unknown as { mouse?: [number, number]; link_type_color?: string }
  if (!canvasAny.mouse) return
  // link 是 LLink 实例，含 _pos 中点位置（运行时计算）
  // 简化：根据 link 起点/终点计算距离
  const l = link as {
    _pos?: { x: number; y: number }
    _data?: unknown
  }
  if (!l._pos) return
  // mouse 坐标已经是 canvas 局部坐标
  const mx = canvasAny.mouse[0]
  const my = canvasAny.mouse[1]
  const dx = mx - l._pos.x
  const dy = my - l._pos.y
  const dist = Math.sqrt(dx * dx + dy * dy)
  if (dist < 10) {
    ctx.save()
    ctx.strokeStyle = 'rgba(255, 184, 77, 0.9)'
    ctx.lineWidth = 4
    ctx.beginPath()
    // 仅在原 link 上绘制一条加粗的高亮线（不重复绘制路径）
    ctx.stroke()
    ctx.restore()
  }
}
```

注意：实际 `LLink._pos` 仅在 `drawBezier` 内部计算后赋值，可能为 undefined。**简化方案**：改用 `onAfterDrawLinks`（如果存在）或在 `onDrawForeground` 中遍历 `graph.links`，根据每条 link 的 origin_id/target_id 计算其起止点，再判断鼠标距离。若实现复杂度过高，则**降级为只改变 `LiteGraph.LINK_HOVER_COLOR`**（LiteGraph 内置 hover 颜色变量），效果是鼠标悬停在连接线上时颜色变化（无需自定义绘制）：

```typescript
// 在 configureCanvas 中（已有 LiteGraph 块内追加）
LiteGraph.LINK_HOVER_COLOR = '#ffd38a' // 默认为 '#FFF ，改为橙色
```

**决策**：采用降级方案（设置 `LINK_HOVER_COLOR`），不实现自定义绘制。这是最稳妥的实现，符合"避免引入风险"的原则。

#### 改动 5：新增编辑快捷键

在 `configureCanvas()` 中（`if (!props.readonly)` 块内）追加键盘监听：

```typescript
if (!props.readonly) {
  const canvasEl = canvasRef.value
  if (canvasEl) {
    const keydownHandler = (e: KeyboardEvent) => {
      // 输入框/文本域中不拦截
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) {
        return
      }
      const mod = e.ctrlKey || e.metaKey
      if (mod && e.key.toLowerCase() === 'a') {
        e.preventDefault()
        selectAllNodes()
      } else if (mod && e.key.toLowerCase() === 'c') {
        e.preventDefault()
        copySelectedNodes()
      } else if (mod && e.key.toLowerCase() === 'v') {
        e.preventDefault()
        pasteNodes()
      } else if (mod && e.key.toLowerCase() === 'd') {
        e.preventDefault()
        duplicateSelectedNodes()
      } else if (e.key === 'Escape') {
        if (graphInstance.value) {
          for (const n of graphInstance.value._nodes) n.selected = false
          graphInstance.value._nodes.forEach(n => { /* deselect */ })
          canvas.setDirty(true, true)
        }
      }
    }
    canvasEl.addEventListener('keydown', keydownHandler)
    // 保存到组件级变量以便 onBeforeUnmount 清理
    _keydownHandlerRef = keydownHandler
  }
}
```

辅助函数（模块级或组件级）：

```typescript
// 模块级剪贴板
let _clipboard: Array<{ type: string; pos: [number, number]; properties: Record<string, unknown>; title?: string }> = []
let _keydownHandlerRef: ((e: KeyboardEvent) => void) | null = null

function selectAllNodes() {
  if (!graphInstance.value) return
  for (const n of graphInstance.value._nodes) {
    n.selected = true
  }
  canvasInstance.value?.setDirty(true, true)
}

function copySelectedNodes() {
  if (!graphInstance.value) return
  _clipboard = graphInstance.value._nodes
    .filter((n) => n.selected)
    .map((n) => ({
      type: n.type ?? '',
      pos: [n.pos[0], n.pos[1]] as [number, number],
      properties: { ...(n.properties ?? {}) } as Record<string, unknown>,
      title: n.title,
    }))
}

function pasteNodes() {
  if (!graphInstance.value || !LiteGraph) return
  for (const item of _clipboard) {
    try {
      const node = LiteGraph.createNode<LGraphNodeClass>(item.type)
      if (!node) continue
      node.pos = [item.pos[0] + 30, item.pos[1] + 30]
      if (item.title) node.title = item.title
      if (item.properties) node.properties = { ...item.properties }
      graphInstance.value.add(node)
    } catch (err) {
      console.error('[WorkflowCanvas] Failed to paste node:', err)
    }
  }
  emitChange()
}

function duplicateSelectedNodes() {
  if (!graphInstance.value) return
  const selected = graphInstance.value._nodes.filter((n) => n.selected)
  for (const n of selected) {
    try {
      if (!LiteGraph) continue
      const node = LiteGraph.createNode<LGraphNodeClass>(n.type ?? '')
      if (!node) continue
      node.pos = [n.pos[0] + 30, n.pos[1] + 30]
      node.title = n.title
      node.properties = { ...(n.properties ?? {}) }
      graphInstance.value.add(node)
    } catch (err) {
      console.error('[WorkflowCanvas] Failed to duplicate node:', err)
    }
  }
  emitChange()
}
```

**清理**：在 `onBeforeUnmount` 中移除 keydown 监听：

```typescript
if (_keydownHandlerRef && canvasRef.value) {
  canvasRef.value.removeEventListener('keydown', _keydownHandlerRef)
  _keydownHandlerRef = null
}
```

注意：canvas 元素需要 `tabindex="-1"` 才能获得焦点以接收键盘事件。在模板的 `<canvas>` 上添加 `tabindex="-1"`。

---

### 阶段 6：验证

#### 步骤 1：前端类型检查

```bash
cd Code/frontend
npx vue-tsc --noEmit
```

期望：无错误输出。

#### 步骤 2：后端编译检查（仅校验相关文件）

```bash
cd Code/backend
python -m py_compile app/services/node_template_registry.py
python -m py_compile app/services/python_provider_bridge_service.py
```

期望：无错误。

#### 步骤 3：JSON 文件校验

```bash
python -c "import json; [json.load(open(f, encoding='utf-8')) for f in [
  'Code/backend/.data/workflow_definitions/system/gis_terrain_analysis.json',
  'Code/backend/.data/workflow_definitions/system/preprocess_pipeline.json',
  'Code/backend/.data/workflow_definitions/system/stats_analysis.json',
]]; print('OK')"
```

期望：输出 `OK`。

#### 步骤 4：浏览器手动验证

刷新 http://localhost:5175/ 后：
1. **工作流列表**：看到"📋 模板"分区（含 3 个模板项，每项含"使用此模板"按钮）
2. **使用模板**：点击"使用此模板"→ 弹出对话框 → 输入新 ID/名称 → 创建后自动选中新工作流
3. **系统预设**：原 5 个系统预设工作流仍正常显示（不含 3 个模板项）
4. **画布**：
   - 节点标题栏色更醒目
   - 右下角显示 160×100 minimap，定期刷新显示节点位置
   - 拖动节点时显示橙色虚线对齐辅助线
   - 鼠标悬停连接线时颜色变为橙色
   - 焦点在画布时 Ctrl+A 全选、Ctrl+C 复制、Ctrl+V 粘贴、Ctrl+D 复制选中、Escape 取消选中

---

## 假设与决策

### 假设

1. **localStorage 可用**：浏览器环境支持 localStorage（已在 4.1 中使用）
2. **LiteGraph 版本兼容**：当前 LiteGraph.js 支持 `onDrawOverlay` / `onDrawLink` / `onNodeMoved` 回调（基于现有代码已 monkey-patch 多个回调）
3. **`LiteGraph.LINK_HOVER_COLOR` 内置存在**：LiteGraph 在 hover 连接线时会绘制此颜色的加粗线（不依赖自定义 onDrawLink 绘制路径，避免不可控的渲染叠加问题）
4. **后端 stub 拦截已生效**：3 个模板 JSON 已被 workflow_definition_service.py 加载，无需修改后端
5. **前端 HMR 自动刷新**：Vite 开发服务器已运行，文件修改后自动热更新

### 决策

1. **不引入新依赖**：minimap 自定义实现，避免增加包体积
2. **模板识别方式**：硬编码 `TEMPLATE_IDS` Set（已在 script 部分实现），不依赖后端 `_meta.is_template` 字段，前端识别更稳定
3. **minimap 节流**：使用 `setInterval(drawMinimap, 200)` 即 5 FPS，避免阻塞主画布渲染循环
4. **对齐线触发阈值**：5px（参考 Figma/Sketch 等设计工具的常见值）
5. **连接线悬停高亮降级方案**：仅设置 `LiteGraph.LINK_HOVER_COLOR`，不实现自定义 onDrawLink 绘制路径（避免因 `LLink._pos` 在某些时机为 undefined 导致渲染异常）
6. **快捷键作用域**：监听 canvas 元素的 keydown，需要 canvas 拥有焦点（`tabindex="-1"`）；在 INPUT/TEXTAREA/SELECT/contentEditable 元素中不拦截
7. **剪贴板存储**：模块级变量 `_clipboard`，仅在当前页面会话有效（不持久化到 localStorage，避免类型信息丢失）

### 风险与缓解

1. **风险**：`onDrawOverlay` 在某些 LiteGraph 版本中签名不同或不存在
   **缓解**：调用前使用 `as unknown as` 类型断言；运行时无 effect 时静默忽略，不影响主功能

2. **风险**：Ctrl+A/C/V 快捷键与浏览器/输入框冲突
   **缓解**：检查 `e.target.tagName`，INPUT/TEXTAREA/SELECT/contentEditable 中不拦截；canvas 需先获得焦点（已通过 `tabindex="-1"` 实现）

3. **风险**：minimap canvas 与主画布的鼠标事件冲突（minimap 覆盖在主画布上）
   **缓解**：minimap 默认尺寸 160×100px 仅占右下角小区域，主画布其他区域不受影响；minimap 上 `pointer-events: auto` 仅接收自身事件

4. **风险**：使用模板时 `useTemplateSourceId` 等响应式变量与已有复制对话框变量同名冲突
   **缓解**：使用独立变量名 `useTemplateSourceId` / `useTemplateNewId` / `useTemplateNewName`（已在 script 中区分），无冲突

---

## 执行顺序

1. **阶段 4.3 收尾** → 修改 `WorkflowList.vue` 的 `<template>` 部分（4 个改动）
2. **阶段 4.4** → 修改 `litegraph-setup.ts`（getEngineColor 配色）+ `WorkflowCanvas.vue`（minimap、对齐线、悬停高亮、快捷键）
3. **阶段 6** → 运行 vue-tsc + py_compile + JSON 校验

阶段 4.3 收尾与阶段 4.4 互相独立，可按顺序串行执行。阶段 6 必须在所有改动完成后执行。
