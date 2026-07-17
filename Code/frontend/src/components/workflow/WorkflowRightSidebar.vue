<script setup lang="ts">
/**
 * WorkflowRightSidebar.vue
 *
 * 工作流编辑器右侧面板：收起/展开按钮 + 节点库 + 可拖动分割条 + 属性检查器。
 * 从 WorkflowEditorPanel.vue 拆分，降低主面板代码复杂度。
 */
import { onBeforeUnmount, ref } from 'vue'

import WorkflowNodePalette from './WorkflowNodePalette.vue'
import WorkflowInspector from './WorkflowInspector.vue'

import type { LGraphNodeClass } from './litegraph-setup'
import type { NodeTemplate } from '../../services/workflow-definition-api'

const props = defineProps<{
  collapsed: boolean
  selectedNode: LGraphNodeClass | null
  readonly: boolean
}>()

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
  'add-node': [template: NodeTemplate]
  'update-property': [key: string, value: unknown]
  'update-title': [title: string]
}>()

// ─── 可拖动分割条：节点库与属性检查器之间 ───────────────────────────────────
const inspectorHeightPx = ref(240)
const resizingRightSplit = ref(false)
let _resizeStartY = 0
let _resizeStartHeight = 0

function startRightSplitResize(event: MouseEvent) {
  resizingRightSplit.value = true
  _resizeStartY = event.clientY
  _resizeStartHeight = inspectorHeightPx.value
  document.addEventListener('mousemove', onRightSplitMove)
  document.addEventListener('mouseup', stopRightSplitResize)
  document.body.style.cursor = 'ns-resize'
  document.body.style.userSelect = 'none'
  event.preventDefault()
}

function onRightSplitMove(event: MouseEvent) {
  if (!resizingRightSplit.value) return
  // 属性面板在下方：向上拖分割条（delta<0）→ 属性面板变大；向下拖（delta>0）→ 变小
  // 因此 newHeight 与 delta 反号
  const delta = event.clientY - _resizeStartY
  const newHeight = _resizeStartHeight - delta
  // 限制范围：最小 100px，最大 600px
  inspectorHeightPx.value = Math.max(100, Math.min(newHeight, 600))
}

function stopRightSplitResize() {
  resizingRightSplit.value = false
  document.removeEventListener('mousemove', onRightSplitMove)
  document.removeEventListener('mouseup', stopRightSplitResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

// 组件销毁时清理拖动监听器和 body 样式，避免泄漏
// 场景：用户正在拖动分割条时关闭编辑器面板
onBeforeUnmount(() => {
  if (resizingRightSplit.value) {
    stopRightSplitResize()
  }
})

function toggleCollapsed() {
  emit('update:collapsed', !props.collapsed)
}
</script>

<template>
  <aside class="editor-sidebar right" :class="{ collapsed }">
    <button
      class="sidebar-toggle right-toggle"
      type="button"
      :title="collapsed ? '展开右侧面板' : '收起右侧面板'"
      @click="toggleCollapsed"
    >
      <span aria-hidden="true">{{ collapsed ? '◀' : '▶' }}</span>
    </button>
    <template v-if="!collapsed">
      <div class="sidebar-palette">
        <WorkflowNodePalette @add-node="emit('add-node', $event)" />
      </div>
      <div
        class="sidebar-resizer"
        :class="{ active: resizingRightSplit }"
        @mousedown="startRightSplitResize"
        title="拖动调整属性面板高度"
      >
        <span class="resizer-handle" aria-hidden="true"></span>
      </div>
      <div
        class="sidebar-inspector"
        :style="{ height: inspectorHeightPx + 'px', flex: 'none' }"
      >
        <WorkflowInspector
          :selected-node="selectedNode"
          :readonly="readonly"
          @update-property="(key: string, value: unknown) => emit('update-property', key, value)"
          @update-title="emit('update-title', $event)"
        />
      </div>
    </template>
  </aside>
</template>

<style scoped>
.editor-sidebar {
  display: flex;
  flex-direction: column;
  flex: none;
  position: relative;
  transition: width 0.22s ease;
}

.editor-sidebar.right {
  width: 16rem;
  border-left: 1px solid rgba(136, 192, 255, 0.1);
}

.editor-sidebar.right.collapsed {
  width: 1.6rem;
}

.sidebar-toggle {
  position: absolute;
  top: 0.42rem;
  z-index: 10;
  width: 1.2rem;
  height: 1.6rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.32rem;
  background: rgba(12, 24, 42, 0.88);
  color: #8aa8bf;
  font-size: 0.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.16s ease, border-color 0.16s ease, background 0.16s ease;
}

.sidebar-toggle:hover {
  color: #ffd38a;
  border-color: rgba(255, 184, 77, 0.36);
  background: rgba(20, 34, 56, 0.92);
}

.right-toggle {
  left: 0.3rem;
}

.editor-sidebar.collapsed .sidebar-toggle {
  top: 50%;
  transform: translateY(-50%);
}

/* 展开状态下为子组件头部留出 toggle 按钮空间，避免重叠 */
.editor-sidebar.right:not(.collapsed) :deep(.palette-header) {
  padding-left: 2rem;
}

/* 右侧栏分割 */
.sidebar-palette {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

/* 可拖动分割条：节点库与属性检查器之间 */
.sidebar-resizer {
  flex: none;
  height: 5px;
  cursor: ns-resize;
  background: rgba(136, 192, 255, 0.06);
  border-top: 1px solid rgba(136, 192, 255, 0.1);
  border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.16s ease;
  user-select: none;
  position: relative;
}

.sidebar-resizer:hover,
.sidebar-resizer.active {
  background: rgba(90, 213, 255, 0.18);
}

.resizer-handle {
  width: 28px;
  height: 2px;
  border-radius: 1px;
  background: rgba(136, 192, 255, 0.28);
  transition: background 0.16s ease;
}

.sidebar-resizer:hover .resizer-handle,
.sidebar-resizer.active .resizer-handle {
  background: rgba(90, 213, 255, 0.7);
}

.sidebar-inspector {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

/* 右侧面板滚动条：薄型深色主题（替换浏览器默认白色粗滚动条） */
.editor-sidebar.right :deep(.palette-content),
.editor-sidebar.right :deep(.inspector-content) {
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 180, 255, 0.28) transparent;
}

.editor-sidebar.right :deep(.palette-content)::-webkit-scrollbar,
.editor-sidebar.right :deep(.inspector-content)::-webkit-scrollbar {
  width: 5px;
}

.editor-sidebar.right :deep(.palette-content)::-webkit-scrollbar-track,
.editor-sidebar.right :deep(.inspector-content)::-webkit-scrollbar-track {
  background: transparent;
}

.editor-sidebar.right :deep(.palette-content)::-webkit-scrollbar-thumb,
.editor-sidebar.right :deep(.inspector-content)::-webkit-scrollbar-thumb {
  background: rgba(90, 180, 255, 0.26);
  border-radius: 3px;
}

.editor-sidebar.right :deep(.palette-content)::-webkit-scrollbar-thumb:hover,
.editor-sidebar.right :deep(.inspector-content)::-webkit-scrollbar-thumb:hover {
  background: rgba(90, 180, 255, 0.45);
}

@media (max-width: 1100px) {
  .editor-sidebar.right {
    width: 13rem;
  }
}

@media (max-width: 800px) {
  .editor-sidebar.right {
    width: 100%;
    height: 12rem;
    border-left: none;
    border-top: 1px solid rgba(136, 192, 255, 0.1);
  }
  .editor-sidebar.right.collapsed {
    width: 100%;
    height: 1.6rem;
  }
}
</style>
