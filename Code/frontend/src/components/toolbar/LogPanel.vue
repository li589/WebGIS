<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ClipboardList, X } from '../ui/icons'
import { useLogStore, type LogCategory } from '../../stores/log'
import { loadSettingsUiLocal, saveSettingsUiLocal } from '../../services/settings-local'

const emit = defineEmits<{
  close: []
}>()

const logStore = useLogStore()

type FilterTag = 'all' | LogCategory | 'errors'
const activeFilter = ref<FilterTag>('all')
const expandedId = ref<string | null>(null)

const filteredEntries = computed(() => {
  const entries = logStore.entries
  if (activeFilter.value === 'errors') {
    return entries.filter((e) => e.severity === 'error')
  }
  if (activeFilter.value === 'all') return entries
  return entries.filter((e) => e.category === activeFilter.value)
})

// 倒序显示（最新在上）
const displayEntries = computed(() => [...filteredEntries.value].reverse())

const operationCount = computed(
  () => logStore.entries.filter((e) => e.category === 'operation').length,
)
const workflowCount = computed(
  () => logStore.entries.filter((e) => e.category === 'workflow').length,
)

/** 错误数显示：≥100 显示 99+ */
const errorCountDisplay = computed(() => {
  const n = logStore.errorCount
  return n >= 100 ? '99+' : String(n)
})

function formatTime(ts: number): string {
  const d = new Date(ts)
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  const s = String(d.getSeconds()).padStart(2, '0')
  return `${h}:${m}:${s}`
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function handleExport() {
  logStore.downloadExport()
}

/** 系统日志侧栏：左缘拖动加宽（面板贴右，向左拖 = 变宽） */
const LOG_WIDTH_DEFAULT_PX = Math.round(26 * 16)
const LOG_WIDTH_MIN_PX = Math.round(22 * 16)
const LOG_WIDTH_MAX_CAP_PX = Math.round(56 * 16)

function clampLogPanelWidth(px: number): number {
  const maxByViewport = Math.floor(window.innerWidth * 0.92)
  const max = Math.min(LOG_WIDTH_MAX_CAP_PX, Math.max(LOG_WIDTH_MIN_PX, maxByViewport))
  return Math.min(max, Math.max(LOG_WIDTH_MIN_PX, Math.round(px)))
}

const savedWidth = loadSettingsUiLocal().logPanelWidthPx
const logPanelWidthPx = ref(
  clampLogPanelWidth(
    typeof savedWidth === 'number' && Number.isFinite(savedWidth)
      ? savedWidth
      : LOG_WIDTH_DEFAULT_PX,
  ),
)
const panelStyle = computed(() => ({ width: `${logPanelWidthPx.value}px` }))

let resizeStartX = 0
let resizeStartWidth = 0
const isResizing = ref(false)
let suppressOverlayClose = false
let suppressOverlayCloseTimer: ReturnType<typeof setTimeout> | null = null
let resizeCaptureEl: Element | null = null
let resizePointerId: number | null = null

function onOverlayClick() {
  if (suppressOverlayClose || isResizing.value) return
  emit('close')
}

function armOverlayCloseSuppress() {
  suppressOverlayClose = true
  if (suppressOverlayCloseTimer !== null) clearTimeout(suppressOverlayCloseTimer)
  suppressOverlayCloseTimer = setTimeout(() => {
    suppressOverlayClose = false
    suppressOverlayCloseTimer = null
  }, 100)
}

function onResizePointerMove(event: PointerEvent) {
  if (!isResizing.value) return
  const next = resizeStartWidth + (resizeStartX - event.clientX)
  logPanelWidthPx.value = clampLogPanelWidth(next)
}

function stopResize() {
  if (!isResizing.value) return
  isResizing.value = false
  if (resizeCaptureEl && resizePointerId !== null) {
    try {
      resizeCaptureEl.releasePointerCapture(resizePointerId)
    } catch {
      /* capture 可能已释放 */
    }
  }
  resizeCaptureEl = null
  resizePointerId = null
  window.removeEventListener('pointermove', onResizePointerMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  armOverlayCloseSuppress()
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), logPanelWidthPx: logPanelWidthPx.value })
}

function onResizePointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  isResizing.value = true
  resizeStartX = event.clientX
  resizeStartWidth = logPanelWidthPx.value
  document.body.style.cursor = 'ew-resize'
  document.body.style.userSelect = 'none'
  const target = event.currentTarget
  if (target instanceof Element) {
    resizeCaptureEl = target
    resizePointerId = event.pointerId
    try {
      target.setPointerCapture(event.pointerId)
    } catch {
      resizeCaptureEl = null
      resizePointerId = null
    }
  }
  window.addEventListener('pointermove', onResizePointerMove)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

function onWindowResize() {
  logPanelWidthPx.value = clampLogPanelWidth(logPanelWidthPx.value)
}

onMounted(() => {
  window.addEventListener('resize', onWindowResize)
})

onUnmounted(() => {
  stopResize()
  if (suppressOverlayCloseTimer !== null) clearTimeout(suppressOverlayCloseTimer)
  window.removeEventListener('resize', onWindowResize)
})
</script>

<template>
  <div class="log-panel-overlay" @click.self="onOverlayClick">
    <div class="log-panel" :class="{ 'log-panel--resizing': isResizing }" :style="panelStyle">
      <div
        class="log-resize-handle"
        title="向左拖动加宽"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整系统日志面板宽度"
        @pointerdown="onResizePointerDown"
        @click.stop
      />
      <div class="panel-header">
        <ClipboardList :size="16" class="panel-icon" aria-hidden="true" />
        <span class="panel-title">系统日志</span>
        <!-- 仅显示错误数量，无错误时不显示 -->
        <span
          v-if="logStore.errorCount > 0"
          class="error-badge"
          :title="`${logStore.errorCount} 个错误`"
        >
          {{ errorCountDisplay }}
        </span>
        <button class="close-btn" title="关闭" aria-label="关闭" @click="emit('close')">
          <X :size="14" aria-hidden="true" />
        </button>
      </div>

      <!-- 筛选标签 -->
      <div class="filter-tabs">
        <button
          class="filter-tab"
          :class="{ active: activeFilter === 'all' }"
          @click="activeFilter = 'all'"
        >
          全部
          <span class="tab-count">{{
            logStore.entries.length >= 100 ? '99+' : logStore.entries.length
          }}</span>
        </button>
        <button
          class="filter-tab"
          :class="{ active: activeFilter === 'operation' }"
          @click="activeFilter = 'operation'"
        >
          操作 <span class="tab-count">{{ operationCount >= 100 ? '99+' : operationCount }}</span>
        </button>
        <button
          class="filter-tab"
          :class="{ active: activeFilter === 'workflow' }"
          @click="activeFilter = 'workflow'"
        >
          工作流 <span class="tab-count">{{ workflowCount >= 100 ? '99+' : workflowCount }}</span>
        </button>
        <button
          class="filter-tab tab-error"
          :class="{ active: activeFilter === 'errors' }"
          @click="activeFilter = 'errors'"
        >
          错误 <span class="tab-count">{{ errorCountDisplay }}</span>
        </button>
        <div class="tab-spacer"></div>
        <button class="export-btn" title="导出日志 JSON" @click="handleExport">导出</button>
        <button class="clear-btn" title="清空所有日志" @click="logStore.clearLogs()">清空</button>
      </div>

      <!-- 日志列表 -->
      <div class="log-list">
        <div v-if="displayEntries.length === 0" class="empty-hint">暂无日志记录</div>
        <div
          v-for="entry in displayEntries"
          :key="entry.id"
          class="log-entry"
          :class="[`cat-${entry.category}`, `sev-${entry.severity}`]"
          role="button"
          :tabindex="entry.details ? 0 : -1"
          :aria-expanded="entry.details ? expandedId === entry.id : undefined"
          @click="toggleExpand(entry.id)"
          @keydown.enter.prevent="toggleExpand(entry.id)"
          @keydown.space.prevent="toggleExpand(entry.id)"
        >
          <div class="entry-row">
            <span class="entry-time">{{ formatTime(entry.timestamp) }}</span>
            <span class="entry-cat" :class="`cat-badge-${entry.category}`">
              {{ entry.category === 'operation' ? '操作' : '工作流' }}
            </span>
            <span class="entry-type">{{ logStore.typeLabel(entry.type) }}</span>
            <span class="entry-message">{{ entry.message }}</span>
            <span v-if="entry.details" class="entry-expand" aria-hidden="true">
              {{ expandedId === entry.id ? '▾' : '▸' }}
            </span>
          </div>
          <div v-if="entry.details && expandedId === entry.id" class="entry-details">
            <div class="entry-details-hint">详细信息</div>
            {{ entry.details }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 998;
  display: flex;
  justify-content: flex-end;
  background: var(--surface-raised);
}

.log-panel {
  position: relative;
  width: 26rem;
  max-width: 92vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--surface-2);
  border-left: 1px solid var(--border-default);
  box-shadow:
    -16px 0 48px rgba(1, 8, 16, 0.4),
    inset 1px 0 0 rgba(136, 223, 255, 0.06);
  transition: width var(--motion-surface-duration) var(--motion-surface-ease);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
}

.log-panel--resizing {
  transition: none;
  will-change: width;
  cursor: ew-resize;
}

.log-resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 0.5rem;
  transform: translateX(-50%);
  cursor: ew-resize;
  z-index: 2;
  touch-action: none;
}

.log-resize-handle::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: 0.18rem;
  height: 2.4rem;
  transform: translate(-50%, -50%);
  border-radius: 999px;
  background: var(--border-default);
  opacity: 0;
  transition:
    opacity var(--motion-fast) var(--ease-soft),
    background var(--motion-fast) var(--ease-soft);
}

.log-resize-handle:hover::after,
.log-panel--resizing .log-resize-handle::after {
  opacity: 1;
  background: var(--accent);
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-strong);
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  flex: none;
}

.panel-icon {
  font-size: var(--font-size-body);
  color: var(--accent);
  line-height: 1;
}

.panel-title {
  line-height: 1;
}

.error-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 5px;
  border-radius: var(--radius-pill);
  background: var(--danger-surface);
  color: var(--danger);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-bold);
  line-height: 1;
  border: 1px solid var(--danger-border);
}

.close-btn {
  margin-left: auto;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: var(--font-size-caption);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    background-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft);
}
.close-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.filter-tabs {
  display: flex;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-subtle);
  flex: none;
  flex-wrap: wrap;
  align-items: center;
}

.tab-spacer {
  flex: 1;
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  transition:
    background-color var(--motion-fast) var(--ease-soft),
    border-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft);
}

.filter-tab:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.filter-tab.active {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
}

.filter-tab.tab-error.active {
  border-color: var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger);
}

.tab-count {
  font-size: var(--font-size-caption);
  opacity: 0.7;
  font-variant-numeric: tabular-nums;
}

.clear-btn {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--danger);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  transition: background-color var(--motion-interactive-duration) var(--motion-interactive-ease);
}
.clear-btn:hover {
  background: var(--danger-surface);
}

.export-btn {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border-accent);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  transition: background-color var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.export-btn:hover {
  background: var(--accent-surface);
}

.log-entry.sev-error .entry-message {
  color: var(--danger);
}

.log-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-1) 0;
}

.empty-hint {
  padding: var(--space-8) var(--space-4);
  text-align: center;
  color: var(--text-faint);
  font-size: var(--font-size-caption);
}

.log-entry {
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: background-color var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.log-entry:hover {
  background: var(--surface-sunken);
}

.entry-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.entry-time {
  color: var(--text-faint);
  font-size: var(--font-size-caption);
  font-variant-numeric: tabular-nums;
  flex: none;
  min-width: 3.8rem;
}

.entry-cat {
  flex: none;
  padding: 2px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-semibold);
}

.cat-badge-operation {
  background: rgba(103, 212, 255, 0.12);
  color: var(--accent);
}

.cat-badge-workflow {
  background: rgba(201, 163, 255, 0.12);
  color: var(--accent-strong);
}

.entry-type {
  flex: none;
  max-width: 5rem;
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-message {
  flex: 1;
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-expand {
  color: var(--text-faint);
  font-size: var(--font-size-caption);
  flex: none;
  line-height: 1;
}

.entry-details {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

.entry-details-hint {
  margin-bottom: var(--space-1);
  color: var(--text-faint);
  font-size: var(--font-size-caption);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  opacity: 0.7;
}

/* 滚动条样式匹配主题 */
.log-list::-webkit-scrollbar {
  width: 6px;
}
.log-list::-webkit-scrollbar-track {
  background: transparent;
}
.log-list::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 3px;
}
.log-list::-webkit-scrollbar-thumb:hover {
  background: var(--border-strong);
}
</style>
