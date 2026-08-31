<script setup lang="ts">
/**
 * WorkflowRightSidebar.vue
 *
 * 工作流编辑器右侧面板：收起/展开 + 可向外拖拽调整宽度 + 节点库/属性分割。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import WorkflowNodePalette from './WorkflowNodePalette.vue'
import WorkflowInspector from './WorkflowInspector.vue'
import './workflow-editor-chrome.css'

import type { LGraphNodeClass } from './litegraph-setup'
import type { NodeTemplate } from '../../services/workflow-definition-api'
import type { ValidationIssue } from '../../composables/workflow-validator'

const RIGHT_MIN = 200
const RIGHT_MAX = 560
const RIGHT_DEFAULT = 256
const STORAGE_KEY_W = 'wf-editor-right-width'
const STORAGE_KEY_H = 'wf-editor-inspector-height'

function loadNum(key: string, fallback: number, min: number, max: number): number {
  try {
    const raw = localStorage.getItem(key)
    const n = raw ? Number(raw) : fallback
    if (Number.isFinite(n)) return Math.max(min, Math.min(max, n))
  } catch {
    /* ignore */
  }
  return fallback
}

const props = defineProps<{
  collapsed: boolean
  selectedNode: LGraphNodeClass | null
  readonly: boolean
  validationIssues?: ValidationIssue[]
}>()

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
  'add-node': [template: NodeTemplate]
  'update-property': [key: string, value: unknown]
  'update-title': [title: string]
}>()

const widthPx = ref(loadNum(STORAGE_KEY_W, RIGHT_DEFAULT, RIGHT_MIN, RIGHT_MAX))
const resizingWidth = ref(false)
let _startX = 0
let _startW = 0

const inspectorHeightPx = ref(loadNum(STORAGE_KEY_H, 240, 100, 600))
const resizingRightSplit = ref(false)
let _resizeStartY = 0
let _resizeStartHeight = 0

const _vw = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
function _onResize() {
  _vw.value = window.innerWidth
}
onMounted(() => window.addEventListener('resize', _onResize, { passive: true }))
onBeforeUnmount(() => window.removeEventListener('resize', _onResize))

const sidebarStyle = computed(() => {
  if (props.collapsed || _vw.value < 768) return undefined
  return { width: `${widthPx.value}px` }
})

function startWidthResize(event: MouseEvent) {
  if (props.collapsed) return
  resizingWidth.value = true
  _startX = event.clientX
  _startW = widthPx.value
  document.addEventListener('mousemove', onWidthResizeMove)
  document.addEventListener('mouseup', stopWidthResize)
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  event.preventDefault()
}

function onWidthResizeMove(event: MouseEvent) {
  if (!resizingWidth.value) return
  // 右侧面板：向左拖（delta<0）加宽
  const next = _startW - (event.clientX - _startX)
  widthPx.value = Math.max(RIGHT_MIN, Math.min(RIGHT_MAX, next))
}

function stopWidthResize() {
  if (!resizingWidth.value) return
  resizingWidth.value = false
  document.removeEventListener('mousemove', onWidthResizeMove)
  document.removeEventListener('mouseup', stopWidthResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  try {
    localStorage.setItem(STORAGE_KEY_W, String(widthPx.value))
  } catch {
    /* ignore */
  }
}

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
  const delta = event.clientY - _resizeStartY
  inspectorHeightPx.value = Math.max(100, Math.min(_resizeStartHeight - delta, 600))
}

function stopRightSplitResize() {
  if (!resizingRightSplit.value) return
  resizingRightSplit.value = false
  document.removeEventListener('mousemove', onRightSplitMove)
  document.removeEventListener('mouseup', stopRightSplitResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  try {
    localStorage.setItem(STORAGE_KEY_H, String(inspectorHeightPx.value))
  } catch {
    /* ignore */
  }
}

onBeforeUnmount(() => {
  if (resizingRightSplit.value) stopRightSplitResize()
  if (resizingWidth.value) stopWidthResize()
})

function toggleCollapsed() {
  emit('update:collapsed', !props.collapsed)
}
</script>

<template>
  <aside
    class="editor-sidebar right"
    :class="{ collapsed, resizing: resizingWidth }"
    :style="sidebarStyle"
  >
    <div
      v-if="!collapsed"
      class="wf-sidebar-resizer right"
      :class="{ active: resizingWidth }"
      title="拖拽调整右侧面板宽度"
      @mousedown="startWidthResize"
    />
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
        title="拖动调整属性面板高度"
        @mousedown="startRightSplitResize"
      >
        <span class="resizer-handle" aria-hidden="true"></span>
      </div>
      <div class="sidebar-inspector" :style="{ height: inspectorHeightPx + 'px', flex: 'none' }">
        <WorkflowInspector
          :selected-node="selectedNode"
          :readonly="readonly"
          :validation-issues="validationIssues"
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
  min-width: 0;
}

.editor-sidebar.resizing {
  transition: none;
}

.editor-sidebar.right {
  width: 16rem;
  border-left: 1px solid var(--border-subtle);
}

.editor-sidebar.right.collapsed {
  width: 1.6rem;
}

.sidebar-toggle {
  position: absolute;
  top: 0.55rem;
  z-index: 10;
  width: 1.2rem;
  height: 1.6rem;
  padding: 0;
  border: 1px solid var(--border-default);
  border-radius: 0.4rem;
  background: var(--surface-1);
  color: var(--text-muted);
  font-size: 0.6rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--elevation-1);
  transition:
    color 0.22s ease,
    border-color 0.22s ease,
    background 0.22s ease,
    box-shadow 0.22s ease,
    top 0.22s ease,
    left 0.22s ease,
    transform 0.22s ease;
}

.sidebar-toggle:hover {
  color: var(--accent);
  border-color: var(--border-accent);
  background: var(--surface-2);
  box-shadow: var(--elevation-2);
}

.right-toggle {
  left: 0.25rem;
}

/* 收起态：按钮在窄轨道内水平 + 垂直居中（与左侧对称） */
.editor-sidebar.right.collapsed .sidebar-toggle {
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}

.editor-sidebar.right:not(.collapsed) :deep(.palette-header) {
  padding-left: 2rem;
}

.sidebar-palette {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.sidebar-resizer {
  flex: none;
  height: 5px;
  cursor: ns-resize;
  background: var(--border-subtle);
  border-top: 1px solid var(--border-subtle);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.16s ease;
  user-select: none;
  position: relative;
}

.sidebar-resizer:hover,
.sidebar-resizer.active {
  background: var(--accent-surface);
}

.resizer-handle {
  width: 28px;
  height: 2px;
  border-radius: 1px;
  background: var(--border-strong);
  transition: background 0.16s ease;
}

.sidebar-resizer:hover .resizer-handle,
.sidebar-resizer.active .resizer-handle {
  background: var(--border-strong);
}

.sidebar-inspector {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.editor-sidebar.right :deep(.palette-content),
.editor-sidebar.right :deep(.inspector-content) {
  scrollbar-width: thin;
  scrollbar-color: var(--border-accent) transparent;
}

.editor-sidebar.right :deep(.palette-content)::-webkit-scrollbar,
.editor-sidebar.right :deep(.inspector-content)::-webkit-scrollbar {
  width: 4px;
}

.editor-sidebar.right :deep(.palette-content)::-webkit-scrollbar-track,
.editor-sidebar.right :deep(.inspector-content)::-webkit-scrollbar-track {
  background: transparent;
}

.editor-sidebar.right :deep(.palette-content)::-webkit-scrollbar-thumb,
.editor-sidebar.right :deep(.inspector-content)::-webkit-scrollbar-thumb {
  background: var(--border-accent);
  border-radius: 3px;
}

.editor-sidebar.right :deep(.palette-content)::-webkit-scrollbar-thumb:hover,
.editor-sidebar.right :deep(.inspector-content)::-webkit-scrollbar-thumb:hover {
  background: var(--border-strong);
}

@media (max-width: 768px) {
  .editor-sidebar.right {
    width: 100%;
    height: 12rem;
    border-left: none;
    border-top: 1px solid var(--border-subtle);
  }
  .editor-sidebar.right.collapsed {
    width: 100%;
    height: 1.6rem;
  }
  .wf-sidebar-resizer {
    display: none;
  }
}
</style>
