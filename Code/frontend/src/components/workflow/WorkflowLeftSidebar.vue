<script setup lang="ts">
/**
 * WorkflowLeftSidebar.vue
 *
 * 工作流编辑器左侧面板：收起/展开 + 可向外拖拽调整宽度 + 工作流列表。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

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
  border-right: 1px solid var(--border-subtle);
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
    right 0.22s ease,
    transform 0.22s ease;
}

.sidebar-toggle:hover {
  color: var(--accent);
  border-color: var(--border-accent);
  background: var(--surface-2);
  box-shadow: var(--elevation-2);
}

.left-toggle {
  right: 0.25rem;
}

/* 收起态：按钮在窄轨道内水平 + 垂直居中（与右侧对称） */
.editor-sidebar.left.collapsed .sidebar-toggle {
  top: 50%;
  right: 50%;
  transform: translate(50%, -50%);
}

.editor-sidebar.left:not(.collapsed) :deep(.list-header) {
  padding-right: 2rem;
}

.editor-sidebar.left :deep(.list-content) {
  scrollbar-width: thin;
  scrollbar-color: var(--border-accent) transparent;
}

.editor-sidebar.left :deep(.list-content)::-webkit-scrollbar {
  width: 4px;
}

.editor-sidebar.left :deep(.list-content)::-webkit-scrollbar-track {
  background: transparent;
}

.editor-sidebar.left :deep(.list-content)::-webkit-scrollbar-thumb {
  background: var(--border-accent);
  border-radius: 3px;
}

.editor-sidebar.left :deep(.list-content)::-webkit-scrollbar-thumb:hover {
  background: var(--border-strong);
}

@media (max-width: 768px) {
  .editor-sidebar.left {
    width: 100%;
    height: 12rem;
    border-right: none;
    border-bottom: 1px solid var(--border-subtle);
  }
  .editor-sidebar.left.collapsed {
    width: 100%;
    height: 1.6rem;
  }
  .wf-sidebar-resizer {
    display: none;
  }
}
</style>
