<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import BasePanel from './BasePanel.vue'

const props = withDefaults(
  defineProps<{
    panelLabel: string
    panelKey?: string
    draggable?: boolean
    collapsible?: boolean
    defaultCollapsed?: boolean
    maxOffsetX?: number
    maxOffsetY?: number
    defaultWidth?: number
    defaultHeight?: number
    minWidth?: number
    minHeight?: number
    maxWidth?: number
    maxHeight?: number
    resizable?: boolean
    handlePosition?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'
    showResizeHandle?: boolean
    bodyOverflow?: 'auto' | 'hidden'
  }>(),
  {
    draggable: true,
    collapsible: true,
    defaultCollapsed: false,
    maxOffsetX: 120,
    maxOffsetY: 100,
    defaultWidth: 0,
    defaultHeight: 0,
    minWidth: 200,
    minHeight: 80,
    maxWidth: 600,
    maxHeight: 800,
    resizable: true,
    handlePosition: 'bottom-right',
    showResizeHandle: true,
    bodyOverflow: 'auto',
  },
)

interface PersistedPanelState {
  visible: boolean
  collapsed: boolean
  offsetX: number
  offsetY: number
  width?: number
  height?: number
}

function getStorageKey(panelKey: string | undefined) {
  return panelKey ? `geo-panel:${panelKey}` : ''
}

function readPersistedState(panelKey: string | undefined): PersistedPanelState | null {
  if (typeof window === 'undefined' || !panelKey) return null
  try {
    const raw = window.localStorage.getItem(getStorageKey(panelKey))
    return raw ? (JSON.parse(raw) as PersistedPanelState) : null
  } catch {
    return null
  }
}

const persistedState = readPersistedState(props.panelKey)
const visible = ref(persistedState?.visible ?? true)
const collapsed = ref(persistedState?.collapsed ?? props.defaultCollapsed)
const offsetX = ref(persistedState?.offsetX ?? 0)
const offsetY = ref(persistedState?.offsetY ?? 0)
const panelWidth = ref(persistedState?.width ?? props.defaultWidth)
const panelHeight = ref(persistedState?.height ?? props.defaultHeight)
const userResized = ref(Boolean(persistedState?.width || persistedState?.height))
const persistTimer = ref<number | null>(null)

const viewportEdgePadding = 12

const resolvedMinWidth = computed(() => Math.max(220, props.minWidth))
const resolvedMinHeight = computed(() => Math.max(120, props.minHeight))
const resolvedMaxWidth = computed(() => Math.max(resolvedMinWidth.value, props.maxWidth))
const resolvedMaxHeight = computed(() => Math.max(resolvedMinHeight.value, props.maxHeight))
const resizeEnabled = computed(() => props.resizable && !collapsed.value && props.showResizeHandle)
const isMobile = computed(() => typeof window !== 'undefined' && window.innerWidth < 820)
const titleBarClass = computed(() => {
  const base = ['panel-tools', `panel-tools--${props.panelKey ?? 'generic'}`]
  if (props.panelKey === 'analysis') base.push('panel-tools--analysis')
  return base
})
const resizeHandleClass = computed(() => ['resize-handle', `resize-handle--${props.handlePosition}`, `resize-handle--${props.panelKey ?? 'generic'}`])
const bodyClass = computed(() => ['panel-body', { 'panel-body--mobile': isMobile.value, 'panel-body--hidden': props.bodyOverflow === 'hidden' }])
const anchorRef = ref<HTMLElement | null>(null)
const collapsedHeight = computed(() => (collapsed.value ? '3rem' : undefined))
const mobileDockClass = computed(() => ({
  'control-panel--mobile': isMobile.value,
  'control-panel--timeline': props.panelKey === 'timeline',
}))
const panelDockStyle = computed(() => ({
  '--panel-title-height': '2.35rem',
  '--panel-padding': '0.4rem',
  '--panel-body-padding': '0.45rem',
  '--panel-collapsed-height': '2.9rem',
  '--panel-scrollbar-track': 'rgba(255,255,255,0.05)',
  '--panel-scrollbar-thumb': 'rgba(136,192,255,0.22)',
  '--panel-backdrop-blur': '12px',
}))

let dragStartX = 0
let dragStartY = 0
let baseOffsetX = 0
let baseOffsetY = 0
let dragging = false
let resizeStartX = 0
let resizeStartY = 0
let baseWidth = 0
let baseHeight = 0
let baseRightEdge = 0
let resizing = false

const frameStyle = computed(() => ({ transform: `translate(${offsetX.value}px, ${offsetY.value}px)` }))
const panelSizeStyle = computed(() => {
  const style: Record<string, string> = {}
  const width = panelWidth.value > 0 ? panelWidth.value : props.defaultWidth
  const height = panelHeight.value > 0 ? panelHeight.value : props.defaultHeight
  if (width > 0) style.width = `${clampPanelWidth(width)}px`
  if (height > 0) style.height = `${clampPanelHeight(height)}px`
  style.minWidth = `${resolvedMinWidth.value}px`
  style.maxWidth = `${resolvedMaxWidth.value}px`
  style.minHeight = `${resolvedMinHeight.value}px`
  style.maxHeight = `${resolvedMaxHeight.value}px`
  return style
})

function toggleCollapsed() {
  if (!props.collapsible) return
  collapsed.value = !collapsed.value
}

function hidePanel() {
  visible.value = false
}

function showPanel() {
  visible.value = true
}

function clampOffset(value: number, limit: number) {
  return Math.min(limit, Math.max(-limit, value))
}

function clampPanelWidth(value: number) {
  return Math.min(resolvedMaxWidth.value, Math.max(resolvedMinWidth.value, value))
}

function clampPanelHeight(value: number) {
  return Math.min(resolvedMaxHeight.value, Math.max(resolvedMinHeight.value, value))
}

function getAnalysisRightEdgeLimit() {
  const rect = anchorRef.value?.getBoundingClientRect()
  if (!rect || typeof window === 'undefined') return baseRightEdge
  return Math.min(baseRightEdge, window.innerWidth - rect.left - viewportEdgePadding)
}

function clampAnalysisLeftAnchoredWidth(width: number, rightEdge: number) {
  const maxVisibleWidth = Math.max(resolvedMinWidth.value, rightEdge - viewportEdgePadding)
  const boundedMaxWidth = Math.min(resolvedMaxWidth.value, maxVisibleWidth)
  return Math.min(boundedMaxWidth, Math.max(resolvedMinWidth.value, width))
}

function handlePointerMove(event: PointerEvent) {
  if (!dragging) return
  offsetX.value = clampOffset(baseOffsetX + event.clientX - dragStartX, props.maxOffsetX)
  offsetY.value = clampOffset(baseOffsetY + event.clientY - dragStartY, props.maxOffsetY)
}

function stopDragging() {
  dragging = false
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', stopDragging)
}

function startDragging(event: PointerEvent) {
  if (!props.draggable || window.innerWidth < 900) return
  dragging = true
  dragStartX = event.clientX
  dragStartY = event.clientY
  baseOffsetX = offsetX.value
  baseOffsetY = offsetY.value
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopDragging)
}

function handleResizeMove(event: PointerEvent) {
  if (!resizing) return
  userResized.value = true
  const deltaX = event.clientX - resizeStartX
  const deltaY = event.clientY - resizeStartY
  const resizingFromLeft = props.handlePosition === 'bottom-left' || props.handlePosition === 'top-left'
  const resizingFromTop = props.handlePosition === 'top-left' || props.handlePosition === 'top-right'
  const nextWidth = resizingFromLeft ? baseWidth - deltaX : baseWidth + deltaX
  const nextHeight = resizingFromTop ? baseHeight - deltaY : baseHeight + deltaY
  const clampedHeight = clampPanelHeight(nextHeight)

  if (props.panelKey === 'analysis') {
    const rightEdge = getAnalysisRightEdgeLimit()
    const clampedWidth = clampAnalysisLeftAnchoredWidth(nextWidth, rightEdge)
    panelWidth.value = clampedWidth
    panelHeight.value = clampedHeight
    offsetX.value = rightEdge - clampedWidth
  } else {
    const clampedWidth = clampPanelWidth(nextWidth)
    panelWidth.value = clampedWidth
    panelHeight.value = clampedHeight
    if (resizingFromLeft) {
      const nextRightEdge = baseOffsetX + baseWidth
      offsetX.value = clampOffset(nextRightEdge - clampedWidth, props.maxOffsetX)
    }
  }

  if (resizingFromTop) {
    const bottomEdge = baseOffsetY + baseHeight
    offsetY.value = clampOffset(bottomEdge - clampedHeight, props.maxOffsetY)
  }
}

function stopResizing() {
  resizing = false
  window.removeEventListener('pointermove', handleResizeMove)
  window.removeEventListener('pointerup', stopResizing)
}

function startResizing(event: PointerEvent) {
  if (!resizeEnabled.value) return
  event.preventDefault()
  resizing = true
  resizeStartX = event.clientX
  resizeStartY = event.clientY
  baseWidth = panelWidth.value || props.defaultWidth || resolvedMinWidth.value
  baseHeight = panelHeight.value || props.defaultHeight || resolvedMinHeight.value
  baseRightEdge = offsetX.value + baseWidth
  if (props.panelKey === 'analysis') {
    baseRightEdge = getAnalysisRightEdgeLimit()
    offsetX.value = baseRightEdge - baseWidth
  }
  window.addEventListener('pointermove', handleResizeMove)
  window.addEventListener('pointerup', stopResizing)
}

function resetPanel() {
  offsetX.value = 0
  offsetY.value = 0
  panelWidth.value = props.defaultWidth || 0
  panelHeight.value = props.defaultHeight || 0
  collapsed.value = props.defaultCollapsed
  visible.value = true
  userResized.value = false
}

onBeforeUnmount(() => {
  stopDragging()
  stopResizing()
  if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
})

watch([visible, collapsed, offsetX, offsetY, panelWidth, panelHeight], () => {
  if (typeof window === 'undefined' || !props.panelKey) return
  if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
  persistTimer.value = window.setTimeout(() => {
    const nextState: PersistedPanelState = {
      visible: visible.value,
      collapsed: collapsed.value,
      offsetX: offsetX.value,
      offsetY: offsetY.value,
      width: userResized.value ? panelWidth.value : undefined,
      height: userResized.value ? panelHeight.value : undefined,
    }
    window.localStorage.setItem(getStorageKey(props.panelKey), JSON.stringify(nextState))
    persistTimer.value = null
  }, 120)
})

defineExpose({ showPanel, hidePanel, resetPanel, toggleCollapsed })
</script>

<template>
  <div ref="anchorRef" class="panel-anchor" :style="frameStyle">
    <button v-if="!visible" class="restore-pill" type="button" @click="showPanel">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8s2.2-3.5 6-3.5S14 8 14 8s-2.2 3.5-6 3.5S2 8 2 8Zm6 1.8A1.8 1.8 0 1 0 8 6.2a1.8 1.8 0 0 0 0 3.6Z" /></svg>
      <span>{{ panelLabel }}</span>
    </button>

    <BasePanel v-else class="control-panel" :class="[mobileDockClass, { collapsed }]" :style="[panelSizeStyle, panelDockStyle, collapsedHeight ? { height: collapsedHeight } : {}]">
      <header :class="titleBarClass">
        <button v-if="draggable" class="drag-handle" type="button" title="拖动" @pointerdown.prevent="startDragging"><span></span><span></span><span></span></button>
        <span class="panel-label">{{ panelLabel }}</span>
        <div class="tool-actions">
          <button v-if="collapsible" class="tool-button icon-button" type="button" :title="collapsed ? '展开' : '收起'" :aria-label="collapsed ? '展开' : '收起'" @click="toggleCollapsed">
            <svg v-if="collapsed" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M8 3l5 5-5 5" /></svg>
            <svg v-else viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M8 13 3 8l5-5" /></svg>
          </button>
          <button class="tool-button icon-button" type="button" title="复位" aria-label="复位" @click="resetPanel"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8a5 5 0 1 0 1.5-3.6M3 3v3.4h3.4" /></svg></button>
          <button class="tool-button icon-button" type="button" title="隐藏" aria-label="隐藏" @click="hidePanel"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m2.4 2.4 11.2 11.2M6.2 6.2A2.6 2.6 0 0 0 10 9.8M3 8s2.2-3.5 5-3.5c.8 0 1.5.1 2.2.4M13 8s-1.1 1.8-3 2.8" /></svg></button>
        </div>
      </header>

      <div :class="bodyClass"><slot /></div>
      <button
        v-if="resizeEnabled"
        :class="resizeHandleClass"
        type="button"
        title="拖动调整尺寸 · 双击恢复默认"
        aria-label="调整面板尺寸"
        @pointerdown.prevent="startResizing"
        @dblclick="resetPanel"
      >
        <span class="resize-corner resize-corner--one"></span>
        <span class="resize-corner resize-corner--two"></span>
      </button>
    </BasePanel>
  </div>
</template>

<style scoped>
.panel-anchor{position:relative;pointer-events:auto;will-change:transform;transition:transform .18s cubic-bezier(.25,.46,.45,.94);width:100%;height:100%;display:inline-block;min-width:200px}.restore-pill{display:inline-flex;align-items:center;gap:.42rem;border:1px solid rgba(136,192,255,.16);border-radius:999px;padding:.42rem .68rem;background:rgba(8,18,33,.88);color:#dfeefe;cursor:pointer;font:inherit;font-size:.72rem}.control-panel{position:relative;min-width:0;display:flex;flex-direction:column;transition:opacity .2s ease,box-shadow .2s ease;overflow:visible;min-height:0;border-color:transparent;background:transparent;box-shadow:none;backdrop-filter:none;-webkit-backdrop-filter:none}.control-panel:hover{opacity:1;box-shadow:none}.control-panel.collapsed{background:transparent;box-shadow:none}.control-panel--mobile{width:100%!important;max-width:none!important;min-width:0!important}.control-panel--timeline{max-width:none}.control-panel--timeline .panel-tools{justify-content:space-between}.control-panel--timeline .panel-body{overflow:hidden}.panel-tools{position:relative;z-index:2;display:flex;align-items:center;gap:.45rem;padding:.34rem .38rem;border:1px solid rgba(136,192,255,.12);border-bottom-color:rgba(136,192,255,.07);border-radius:.86rem .86rem 0 0;background:linear-gradient(180deg, rgba(13, 23, 39, 0.88), rgba(5, 13, 25, 0.78));min-height:2.22rem;backdrop-filter: blur(var(--panel-backdrop-blur)) saturate(1.08);-webkit-backdrop-filter: blur(var(--panel-backdrop-blur)) saturate(1.08);box-shadow:inset 0 1px 0 rgba(255,255,255,.075),0 8px 18px rgba(1,8,16,.08)}.panel-tools--analysis{padding-left:.34rem;padding-right:.34rem;justify-content:space-between;min-height:var(--panel-title-height)}.panel-tools--analysis .panel-label{letter-spacing:.03em}.panel-tools--analysis .tool-actions{gap:.2rem}.panel-tools--analysis .tool-button{padding:.3rem .44rem}.panel-tools--analysis .drag-handle{padding:.34rem .38rem}.drag-handle,.tool-button{border:1px solid rgba(136,192,255,.12);border-radius:.68rem;background:rgba(8,18,33,.58);color:#d5e5f5;cursor:pointer;font:inherit}.drag-handle{display:inline-flex;align-items:center;gap:.16rem;padding:.38rem .46rem;touch-action:none;flex:0 0 auto}.drag-handle span{width:.2rem;height:.2rem;border-radius:999px;background:#8cb5d9}.panel-label{min-width:0;margin-right:0;color:#d9ebfb;font-size:.72rem;letter-spacing:.04em}.tool-actions{display:inline-flex;gap:.26rem;margin-left:auto}.tool-button{padding:.34rem .52rem;font-size:.7rem;transition:border-color .18s ease,color .18s ease,background-color .18s ease;flex:0 0 auto}.tool-button:hover,.drag-handle:hover{border-color:rgba(136,192,255,.28);color:#f3fbff}.panel-body{margin-top:0;flex:1;min-height:0;overflow-y:auto;position:relative;z-index:1;padding:.42rem .38rem .42rem;border:1px solid rgba(136,192,255,.08);border-top:0;border-radius:0 0 .92rem .92rem;background:linear-gradient(180deg, rgba(8,18,33,.4), rgba(6,14,26,.28));box-shadow:inset 0 1px 0 rgba(255,255,255,.02),0 8px 18px rgba(1,8,16,.055);scrollbar-width:thin;scrollbar-color:var(--panel-scrollbar-thumb) var(--panel-scrollbar-track)}.panel-body::-webkit-scrollbar{width:4px}.panel-body::-webkit-scrollbar-track{background:var(--panel-scrollbar-track)}.panel-body::-webkit-scrollbar-thumb{background:var(--panel-scrollbar-thumb);border-radius:999px}.panel-body--mobile{overflow-y:auto;-webkit-overflow-scrolling:touch}.panel-body--hidden{overflow:hidden}.icon-button{display:inline-flex;align-items:center;justify-content:center;width:1.95rem;height:1.95rem;padding:0}.resize-handle{position:absolute;width:1rem;height:1rem;border:none;background:transparent;opacity:0;transition:opacity .16s ease,transform .16s ease;z-index:10;padding:0;display:grid;place-items:center;cursor:nwse-resize}.control-panel:hover .resize-handle,.panel-anchor:focus-within .resize-handle{opacity:.86}.resize-handle--bottom-right{right:-.02rem;bottom:-.02rem}.resize-handle--bottom-left{left:-.02rem;bottom:-.02rem;cursor:nesw-resize}.resize-handle--top-right{right:-.02rem;top:-.02rem;cursor:nesw-resize;transform:rotate(180deg)}.resize-handle--top-left{left:-.02rem;top:-.02rem;cursor:nwse-resize}.resize-handle--layers .resize-corner--one{right:.04rem;bottom:.18rem;width:.66rem;height:2px;transform:rotate(45deg);transform-origin:right bottom}.resize-handle--layers .resize-corner--two{right:.18rem;bottom:.04rem;width:2px;height:.66rem;transform:rotate(45deg);transform-origin:right bottom}.resize-handle--analysis .resize-corner--one{left:.04rem;bottom:.18rem;width:.66rem;height:2px;transform:rotate(-45deg);transform-origin:left bottom}.resize-handle--analysis .resize-corner--two{left:.18rem;bottom:.04rem;width:2px;height:.66rem;transform:rotate(-45deg);transform-origin:left bottom}.resize-corner{position:absolute;background:rgba(90,162,255,.72);border-radius:999px;box-shadow:0 0 0 1px rgba(255,255,255,.04) inset}.resize-corner--one{right:.12rem;bottom:.24rem;width:.42rem;height:2px}.resize-corner--two{right:.24rem;bottom:.12rem;width:2px;height:.42rem}.panel-anchor:hover .resize-handle{transform:scale(1.02)}.restore-pill svg,.icon-button svg{width:.9rem;height:.9rem;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.restore-pill svg{width:.86rem;height:.86rem}@media (max-width:900px){.panel-anchor{transform:none!important}.drag-handle{display:none}.panel-tools{padding:.38rem .44rem}.panel-body{padding:.4rem}.resize-handle{display:none}}
</style>
