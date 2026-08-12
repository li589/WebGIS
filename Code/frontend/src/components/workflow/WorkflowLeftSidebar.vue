<script setup lang="ts">
/**
 * WorkflowLeftSidebar.vue
 *
 * 工作流编辑器左侧面板：收起/展开 + 可向外拖拽调整宽度 + 工作流列表。
 */
import { computed, onBeforeUnmount, ref } from 'vue'

import WorkflowList from './WorkflowList.vue'
import './workflow-editor-chrome.css'

const LEFT_MIN = 180
const LEFT_MAX = 520
const LEFT_DEFAULT = 256
const STORAGE_KEY = 'wf-editor-left-width'

function loadWidth(): number {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const n = raw ? Number(raw) : LEFT_DEFAULT
    if (Number.isFinite(n)) return Math.max(LEFT_MIN, Math.min(LEFT_MAX, n))
  } catch {
    /* ignore */
  }
  return LEFT_DEFAULT
}

const props = defineProps<{
  collapsed: boolean
}>()

const emit = defineEmits<{
  'update:collapsed': [value: boolean]
  select: [workflowId: string]
  create: []
}>()

const widthPx = ref(loadWidth())
const resizing = ref(false)
let _startX = 0
let _startW = 0

const sidebarStyle = computed(() => (props.collapsed ? undefined : { width: `${widthPx.value}px` }))

function toggleCollapsed() {
  emit('update:collapsed', !props.collapsed)
}

function startResize(event: MouseEvent) {
  if (props.collapsed) return
  resizing.value = true
  _startX = event.clientX
  _startW = widthPx.value
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', stopResize)
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  event.preventDefault()
}

function onResizeMove(event: MouseEvent) {
  if (!resizing.value) return
  // 左侧面板：向右拖（delta>0）加宽
  const next = _startW + (event.clientX - _startX)
  widthPx.value = Math.max(LEFT_MIN, Math.min(LEFT_MAX, next))
}

function stopResize() {
  if (!resizing.value) return
  resizing.value = false
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  try {
    localStorage.setItem(STORAGE_KEY, String(widthPx.value))
  } catch {
    /* ignore */
  }
}

onBeforeUnmount(() => {
  if (resizing.value) stopResize()
})
</script>

<template>
  <aside class="editor-sidebar left" :class="{ collapsed, resizing }" :style="sidebarStyle">
    <WorkflowList v-show="!collapsed" @select="emit('select', $event)" @create="emit('create')" />
    <button
      class="sidebar-toggle left-toggle"
      type="button"
      :title="collapsed ? '展开左侧面板' : '收起左侧面板'"
      @click="toggleCollapsed"
    >
      <span aria-hidden="true">{{ collapsed ? '▶' : '◀' }}</span>
    </button>
    <div
      v-if="!collapsed"
      class="wf-sidebar-resizer left"
      :class="{ active: resizing }"
      title="拖拽调整左侧面板宽度"
      @mousedown="startResize"
    />
  </aside>
</template>

<style scoped>
.editor-sidebar {
  display: flex;
  flex-direction: column;
  flex: none;
  border-right: 1px solid rgba(136, 192, 255, 0.1);
  position: relative;
  transition: width 0.22s ease;
  min-width: 0;
}

.editor-sidebar.resizing {
  transition: none;
}

.editor-sidebar.left {
  width: 16rem;
}

.editor-sidebar.left.collapsed {
  width: 1.6rem;
}

.sidebar-toggle {
  position: absolute;
  top: 0.42rem;
  z-index: 10;
  width: 1.2rem;
  height: 1.6rem;
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: rgba(12, 24, 42, 0.88);
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    color 0.16s ease,
    border-color 0.16s ease,
    background 0.16s ease;
}

.sidebar-toggle:hover {
  color: #ffd38a;
  border-color: rgba(255, 184, 77, 0.36);
  background: rgba(20, 34, 56, 0.92);
}

.left-toggle {
  right: 0.3rem;
}

.editor-sidebar.collapsed .sidebar-toggle {
  top: 50%;
  transform: translateY(-50%);
}

.editor-sidebar.left:not(.collapsed) :deep(.list-header) {
  padding-right: 2rem;
}

.editor-sidebar.left :deep(.list-content) {
  scrollbar-width: thin;
  scrollbar-color: rgba(90, 180, 255, 0.28) transparent;
}

.editor-sidebar.left :deep(.list-content)::-webkit-scrollbar {
  width: 4px;
}

.editor-sidebar.left :deep(.list-content)::-webkit-scrollbar-track {
  background: transparent;
}

.editor-sidebar.left :deep(.list-content)::-webkit-scrollbar-thumb {
  background: rgba(90, 180, 255, 0.26);
  border-radius: 3px;
}

.editor-sidebar.left :deep(.list-content)::-webkit-scrollbar-thumb:hover {
  background: rgba(90, 180, 255, 0.45);
}

@media (max-width: 768px) {
  .editor-sidebar.left {
    width: 100% !important;
    height: 12rem;
    border-right: none;
    border-bottom: 1px solid rgba(136, 192, 255, 0.1);
  }
  .editor-sidebar.left.collapsed {
    width: 100% !important;
    height: 1.6rem;
  }
  .wf-sidebar-resizer {
    display: none;
  }
}
</style>
