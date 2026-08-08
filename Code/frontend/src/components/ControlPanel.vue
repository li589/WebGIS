<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import BasePanel from './BasePanel.vue'
import {
  clampPanelDim,
  clampPanelOffset,
  isRightDockedPanel,
  nextSizeFromResizeDelta,
  offsetXToPinRightEdge,
  offsetYToPinBottomEdge,
  shouldCompensateOffsetOnResize,
} from './control-panel-geometry'

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
  /** 显示态位置/尺寸（取消隐藏时恢复） */
  offsetX: number
  offsetY: number
  width?: number
  height?: number
  /** 隐藏态胶囊位置（可选） */
  pillOffsetX?: number
  pillOffsetY?: number
}

interface VisibleLayoutSnapshot {
  offsetX: number
  offsetY: number
  width: number
  height: number
  collapsed: boolean
  userResized: boolean
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
const offsetX = ref(
  !visible.value && typeof persistedState?.pillOffsetX === 'number'
    ? persistedState.pillOffsetX
    : (persistedState?.offsetX ?? 0),
)
const offsetY = ref(
  !visible.value && typeof persistedState?.pillOffsetY === 'number'
    ? persistedState.pillOffsetY
    : (persistedState?.offsetY ?? 0),
)
const panelWidth = ref(persistedState?.width ?? props.defaultWidth)
const panelHeight = ref(persistedState?.height ?? props.defaultHeight)
const userResized = ref(Boolean(persistedState?.width || persistedState?.height))
const persistTimer = ref<number | null>(null)

/** 点击隐藏前的显示态布局；取消隐藏时还原 */
const visibleLayoutSnapshot = ref<VisibleLayoutSnapshot | null>(
  persistedState
    ? {
        offsetX: persistedState.offsetX ?? 0,
        offsetY: persistedState.offsetY ?? 0,
        width: persistedState.width ?? props.defaultWidth,
        height: persistedState.height ?? props.defaultHeight,
        collapsed: persistedState.collapsed ?? props.defaultCollapsed,
        userResized: Boolean(persistedState.width || persistedState.height),
      }
    : null,
)

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
const resizeHandleClass = computed(() => [
  'resize-handle',
  `resize-handle--${props.handlePosition}`,
  `resize-handle--${props.panelKey ?? 'generic'}`,
])
const bodyClass = computed(() => [
  'panel-body',
  { 'panel-body--mobile': isMobile.value, 'panel-body--hidden': props.bodyOverflow === 'hidden' },
])
const collapsedHeight = computed(() =>
  collapsed.value ? 'var(--panel-collapsed-height)' : undefined,
)
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
const dragging = ref(false)
/** 当前是否在拖隐藏态胶囊（位置不设限） */
const draggingPill = ref(false)
/** 隐藏态胶囊拖拽：区分点击展开 vs 拖动移位 */
let pillGestureMoved = false
const PILL_DRAG_THRESHOLD_PX = 5
let resizeStartX = 0
let resizeStartY = 0
let baseWidth = 0
let baseHeight = 0
let baseResizeOffsetX = 0
let baseResizeOffsetY = 0
const resizing = ref(false)
/** 显隐切换时短暂关闭 transform 过渡，避免卡顿感 */
const suppressTransformTransition = ref(false)

const layoutPinsRightEdge = computed(() => isRightDockedPanel(props.panelKey))
const anchorClass = computed(() => ({
  'panel-anchor--dock-right': layoutPinsRightEdge.value,
  'panel-anchor--interacting':
    dragging.value || resizing.value || suppressTransformTransition.value,
}))

const frameStyle = computed(() => ({
  transform: `translate(${offsetX.value}px, ${offsetY.value}px)`,
}))
const panelSizeStyle = computed(() => {
  const style: Record<string, string> = {}
  if (collapsed.value) {
    style.height = 'var(--panel-collapsed-height)'
    style.minHeight = 'var(--panel-collapsed-height)'
    style.maxHeight = 'var(--panel-collapsed-height)'
    const width = panelWidth.value > 0 ? panelWidth.value : props.defaultWidth
    if (width > 0) style.width = `${clampPanelWidth(width)}px`
    style.minWidth = `${resolvedMinWidth.value}px`
    style.maxWidth = `${resolvedMaxWidth.value}px`
    return style
  }
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

function captureVisibleLayout(): VisibleLayoutSnapshot {
  return {
    offsetX: offsetX.value,
    offsetY: offsetY.value,
    width: panelWidth.value,
    height: panelHeight.value,
    collapsed: collapsed.value,
    userResized: userResized.value,
  }
}

function applyVisibleLayout(snap: VisibleLayoutSnapshot) {
  offsetX.value = snap.offsetX
  offsetY.value = snap.offsetY
  panelWidth.value = snap.width
  panelHeight.value = snap.height
  collapsed.value = snap.collapsed
  userResized.value = snap.userResized
}

function hidePanel() {
  // 隐藏前记录显示态位置与尺寸
  visibleLayoutSnapshot.value = captureVisibleLayout()
  suppressTransformTransition.value = true
  visible.value = false
  window.requestAnimationFrame(() => {
    suppressTransformTransition.value = false
  })
}

function showPanel() {
  suppressTransformTransition.value = true
  // 取消隐藏：恢复隐藏前的位置与缩放，忽略胶囊拖动位置
  if (visibleLayoutSnapshot.value) {
    applyVisibleLayout(visibleLayoutSnapshot.value)
  }
  visible.value = true
  window.requestAnimationFrame(() => {
    suppressTransformTransition.value = false
  })
}

function clampPanelWidth(value: number) {
  return clampPanelDim(value, resolvedMinWidth.value, resolvedMaxWidth.value)
}

function clampPanelHeight(value: number) {
  return clampPanelDim(value, resolvedMinHeight.value, resolvedMaxHeight.value)
}

function handlePointerMove(event: PointerEvent) {
  if (!dragging.value) return
  const dx = event.clientX - dragStartX
  const dy = event.clientY - dragStartY
  if (Math.abs(dx) > PILL_DRAG_THRESHOLD_PX || Math.abs(dy) > PILL_DRAG_THRESHOLD_PX) {
    pillGestureMoved = true
  }
  if (draggingPill.value || !visible.value) {
    // 隐藏态：位置移动不受限
    offsetX.value = baseOffsetX + dx
    offsetY.value = baseOffsetY + dy
    return
  }
  offsetX.value = clampPanelOffset(baseOffsetX + dx, props.maxOffsetX)
  offsetY.value = clampPanelOffset(baseOffsetY + dy, props.maxOffsetY)
}

function stopDragging() {
  dragging.value = false
  draggingPill.value = false
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', stopDragging)
}

function startDragging(event: PointerEvent) {
  if (!props.draggable || window.innerWidth < 900) return
  pillGestureMoved = false
  draggingPill.value = false
  dragging.value = true
  dragStartX = event.clientX
  dragStartY = event.clientY
  baseOffsetX = offsetX.value
  baseOffsetY = offsetY.value
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopDragging)
}

/** 隐藏态胶囊：拖动改位置（不设限）；未移动则点击展开并恢复显示态布局 */
function startPillDragging(event: PointerEvent) {
  if (!props.draggable) {
    showPanel()
    return
  }
  if (event.button !== 0) return
  event.preventDefault()
  pillGestureMoved = false
  draggingPill.value = true
  dragging.value = true
  dragStartX = event.clientX
  dragStartY = event.clientY
  baseOffsetX = offsetX.value
  baseOffsetY = offsetY.value
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopPillDragging)
}

function stopPillDragging() {
  const moved = pillGestureMoved
  dragging.value = false
  draggingPill.value = false
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', stopPillDragging)
  if (!moved) showPanel()
}

function handleResizeMove(event: PointerEvent) {
  if (!resizing.value) return
  userResized.value = true
  const deltaX = event.clientX - resizeStartX
  const deltaY = event.clientY - resizeStartY
  const raw = nextSizeFromResizeDelta({
    handlePosition: props.handlePosition,
    baseWidth,
    baseHeight,
    deltaX,
    deltaY,
  })
  const clampedWidth = clampPanelWidth(raw.width)
  const clampedHeight = clampPanelHeight(raw.height)
  panelWidth.value = clampedWidth
  panelHeight.value = clampedHeight

  // 分析框等右侧 dock：CSS 已钉右上，只改尺寸，不改 offset（位置记忆保持）
  // 其它面板：左/上手柄时用 transform 钉住对边
  if (
    !shouldCompensateOffsetOnResize({
      panelKey: props.panelKey,
      handlePosition: props.handlePosition,
      layoutPinsRightEdge: layoutPinsRightEdge.value,
    })
  ) {
    return
  }

  const fromLeft = props.handlePosition === 'bottom-left' || props.handlePosition === 'top-left'
  const fromTop = props.handlePosition === 'top-left' || props.handlePosition === 'top-right'
  if (fromLeft) {
    offsetX.value = offsetXToPinRightEdge(
      baseResizeOffsetX,
      baseWidth,
      clampedWidth,
      props.maxOffsetX,
    )
  }
  if (fromTop) {
    offsetY.value = offsetYToPinBottomEdge(
      baseResizeOffsetY,
      baseHeight,
      clampedHeight,
      props.maxOffsetY,
    )
  }
}

function stopResizing() {
  resizing.value = false
  window.removeEventListener('pointermove', handleResizeMove)
  window.removeEventListener('pointerup', stopResizing)
}

function startResizing(event: PointerEvent) {
  if (!resizeEnabled.value) return
  event.preventDefault()
  resizing.value = true
  resizeStartX = event.clientX
  resizeStartY = event.clientY
  baseWidth = panelWidth.value || props.defaultWidth || resolvedMinWidth.value
  baseHeight = panelHeight.value || props.defaultHeight || resolvedMinHeight.value
  baseResizeOffsetX = offsetX.value
  baseResizeOffsetY = offsetY.value
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
  visibleLayoutSnapshot.value = captureVisibleLayout()
}

onBeforeUnmount(() => {
  stopDragging()
  stopPillDragging()
  stopResizing()
  if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
})

watch(
  [visible, collapsed, offsetX, offsetY, panelWidth, panelHeight, visibleLayoutSnapshot],
  () => {
    if (typeof window === 'undefined' || !props.panelKey) return
    if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
    persistTimer.value = window.setTimeout(() => {
      const snap = visibleLayoutSnapshot.value
      const layoutOffsetX = visible.value ? offsetX.value : (snap?.offsetX ?? offsetX.value)
      const layoutOffsetY = visible.value ? offsetY.value : (snap?.offsetY ?? offsetY.value)
      const layoutWidth = visible.value
        ? userResized.value
          ? panelWidth.value
          : undefined
        : snap?.userResized
          ? snap.width
          : undefined
      const layoutHeight = visible.value
        ? userResized.value
          ? panelHeight.value
          : undefined
        : snap?.userResized
          ? snap.height
          : undefined
      const nextState: PersistedPanelState = {
        visible: visible.value,
        collapsed: visible.value ? collapsed.value : (snap?.collapsed ?? collapsed.value),
        offsetX: layoutOffsetX,
        offsetY: layoutOffsetY,
        width: layoutWidth,
        height: layoutHeight,
        pillOffsetX: visible.value ? undefined : offsetX.value,
        pillOffsetY: visible.value ? undefined : offsetY.value,
      }
      window.localStorage.setItem(getStorageKey(props.panelKey), JSON.stringify(nextState))
      persistTimer.value = null
    }, 120)
  },
)

defineExpose({ showPanel, hidePanel, resetPanel, toggleCollapsed })
</script>

<template>
  <div class="panel-anchor" :class="anchorClass" :style="frameStyle">
    <button
      v-if="!visible"
      class="restore-pill"
      type="button"
      :class="{ 'restore-pill--dragging': dragging }"
      :title="`${panelLabel} · 拖动自由移动 / 点击展开并恢复原布局`"
      @pointerdown="startPillDragging"
      @click.prevent
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path
          d="M2 8s2.2-3.5 6-3.5S14 8 14 8s-2.2 3.5-6 3.5S2 8 2 8Zm6 1.8A1.8 1.8 0 1 0 8 6.2a1.8 1.8 0 0 0 0 3.6Z"
        />
      </svg>
      <span>{{ panelLabel }}</span>
    </button>

    <BasePanel
      v-else
      class="control-panel"
      :class="[mobileDockClass, { collapsed }]"
      :style="[panelSizeStyle, panelDockStyle, collapsedHeight ? { height: collapsedHeight } : {}]"
    >
      <header :class="titleBarClass">
        <button
          v-if="draggable"
          class="drag-handle"
          type="button"
          title="拖动"
          @pointerdown.prevent="startDragging"
        >
          <span></span><span></span><span></span>
        </button>
        <span class="panel-label">{{ panelLabel }}</span>
        <div class="tool-actions">
          <button
            v-if="collapsible"
            class="tool-button icon-button"
            type="button"
            :title="collapsed ? '展开' : '收起'"
            :aria-label="collapsed ? '展开' : '收起'"
            @click="toggleCollapsed"
          >
            <svg v-if="collapsed" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8h10M8 3l5 5-5 5" />
            </svg>
            <svg v-else viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8h10M8 13 3 8l5-5" />
            </svg>
          </button>
          <button
            class="tool-button icon-button"
            type="button"
            title="复位"
            aria-label="复位"
            @click="resetPanel"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8a5 5 0 1 0 1.5-3.6M3 3v3.4h3.4" />
            </svg>
          </button>
          <button
            class="tool-button icon-button"
            type="button"
            title="隐藏"
            aria-label="隐藏"
            @click="hidePanel"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="m2.4 2.4 11.2 11.2M6.2 6.2A2.6 2.6 0 0 0 10 9.8M3 8s2.2-3.5 5-3.5c.8 0 1.5.1 2.2.4M13 8s-1.1 1.8-3 2.8"
              />
            </svg>
          </button>
        </div>
      </header>

      <div v-show="!collapsed" :class="bodyClass"><slot /></div>
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
.panel-anchor {
  position: relative;
  pointer-events: auto;
  will-change: transform;
  transition: transform 0.18s cubic-bezier(0.25, 0.46, 0.45, 0.94);
  /* 收缩到面板实际尺寸，避免占满 overlay 导致左下缩放时右上角跟着跑 */
  width: fit-content;
  height: fit-content;
  max-width: 100%;
  display: block;
  min-width: 200px;
}
.panel-anchor--dock-right {
  /* 右侧 dock：不被窄 overlay 的 100% 卡住；右缘由父级 right + max-content 钉住 */
  max-width: calc(100vw - 1.6rem);
  margin-inline-start: auto;
}
.panel-anchor--dock-right :deep(.control-panel) {
  /* 若锚点偶发宽于面板，仍靠右生长 */
  margin-inline-start: auto;
}
.panel-anchor--interacting {
  transition: none;
}
.restore-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.25);
  border-radius: 999px;
  padding: 0.42rem 0.68rem;
  background: rgba(12, 22, 38, 0.65);
  color: #dfeefe;
  cursor: grab;
  font: inherit;
  font-size: 0.72rem;
  box-shadow: 0 10px 22px rgba(1, 8, 16, 0.14);
  opacity: 0.72;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  user-select: none;
  touch-action: none;
  transition:
    opacity 0.18s ease,
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}
.restore-pill:hover {
  opacity: 1;
  border-color: rgba(136, 192, 255, 0.48);
  box-shadow:
    0 14px 28px rgba(1, 8, 16, 0.3),
    0 0 12px rgba(56, 189, 248, 0.25);
}
.restore-pill--dragging {
  cursor: grabbing;
  opacity: 1;
}
.control-panel {
  position: relative;
  min-width: 0;
  display: flex;
  flex-direction: column;
  transition:
    opacity 0.25s cubic-bezier(0.4, 0, 0.2, 1),
    transform 0.25s ease,
    box-shadow 0.25s ease;
  overflow: visible;
  min-height: 0;
  border-color: transparent;
  background: transparent;
  box-shadow: none;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}
.control-panel:hover {
  opacity: 1;
  box-shadow: none;
}
.control-panel.collapsed {
  background: transparent;
  box-shadow: none;
  opacity: 0.55;
}
.control-panel.collapsed:hover {
  opacity: 1;
  transform: translateY(-2px);
}
.control-panel.collapsed .panel-tools {
  border-radius: 0.86rem;
  border-bottom-color: rgba(136, 192, 255, 0.18);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  transition:
    border-color 0.25s ease,
    box-shadow 0.25s ease;
}
.control-panel.collapsed:hover .panel-tools {
  border-color: rgba(136, 192, 255, 0.45);
  box-shadow:
    0 12px 28px rgba(0, 0, 0, 0.5),
    0 0 14px rgba(56, 189, 248, 0.25);
}
.control-panel--mobile {
  width: 100% !important;
  max-width: none !important;
  min-width: 0 !important;
}
.control-panel--timeline {
  max-width: none;
}
.control-panel--timeline .panel-tools {
  justify-content: space-between;
}
.control-panel--timeline .panel-body {
  overflow: hidden;
}
.panel-tools {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.34rem 0.38rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-bottom-color: rgba(136, 192, 255, 0.07);
  border-radius: 0.86rem 0.86rem 0 0;
  background: linear-gradient(180deg, rgba(13, 23, 39, 0.88), rgba(5, 13, 25, 0.78));
  min-height: var(--panel-title-height);
  backdrop-filter: blur(var(--panel-backdrop-blur)) saturate(1.08);
  -webkit-backdrop-filter: blur(var(--panel-backdrop-blur)) saturate(1.08);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.075),
    0 8px 18px rgba(1, 8, 16, 0.08);
}
.panel-tools--analysis {
  padding-left: 0.34rem;
  padding-right: 0.34rem;
  justify-content: space-between;
}
.panel-tools--analysis .panel-label {
  letter-spacing: 0.03em;
}
.panel-tools--analysis .tool-actions {
  gap: 0.2rem;
}
.panel-tools--analysis .tool-button {
  padding: 0.3rem 0.44rem;
}
.panel-tools--analysis .drag-handle {
  padding: 0.34rem 0.38rem;
}
.drag-handle,
.tool-button {
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.68rem;
  background: rgba(8, 18, 33, 0.58);
  color: #d5e5f5;
  cursor: pointer;
  font: inherit;
}
.drag-handle {
  display: inline-flex;
  align-items: center;
  gap: 0.16rem;
  padding: 0.38rem 0.46rem;
  touch-action: none;
  flex: 0 0 auto;
}
.drag-handle span {
  width: 0.2rem;
  height: 0.2rem;
  border-radius: 999px;
  background: #8cb5d9;
}
.panel-label {
  min-width: 0;
  margin-right: 0;
  color: #d9ebfb;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tool-actions {
  display: inline-flex;
  gap: 0.26rem;
  margin-left: auto;
  flex: 0 0 auto;
}
.tool-button {
  padding: 0.34rem 0.52rem;
  font-size: 0.7rem;
  transition:
    border-color 0.18s ease,
    color 0.18s ease,
    background-color 0.18s ease;
  flex: 0 0 auto;
}
.tool-button:hover,
.drag-handle:hover {
  border-color: rgba(136, 192, 255, 0.28);
  color: #f3fbff;
}
.panel-body {
  margin-top: 0;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  position: relative;
  z-index: 1;
  padding: var(--panel-body-padding) calc(var(--panel-body-padding) - 0.07rem)
    var(--panel-body-padding);
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-top: 0;
  border-radius: 0 0 0.92rem 0.92rem;
  background: linear-gradient(180deg, rgba(8, 18, 33, 0.4), rgba(6, 14, 26, 0.28));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.02),
    0 8px 18px rgba(1, 8, 16, 0.055);
  scrollbar-width: thin;
  scrollbar-color: var(--panel-scrollbar-thumb) var(--panel-scrollbar-track);
}
.panel-body::-webkit-scrollbar {
  width: 4px;
}
.panel-body::-webkit-scrollbar-track {
  background: var(--panel-scrollbar-track);
}
.panel-body::-webkit-scrollbar-thumb {
  background: var(--panel-scrollbar-thumb);
  border-radius: 999px;
}
.panel-body--mobile {
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
.panel-body--hidden {
  overflow: hidden;
}
.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.95rem;
  height: 1.95rem;
  padding: 0;
}
.resize-handle {
  position: absolute;
  width: 1rem;
  height: 1rem;
  border: none;
  background: transparent;
  opacity: 0;
  transition:
    opacity 0.16s ease,
    transform 0.16s ease;
  z-index: 10;
  padding: 0;
  display: grid;
  place-items: center;
  cursor: nwse-resize;
}
.control-panel:hover .resize-handle,
.panel-anchor:focus-within .resize-handle {
  opacity: 0.86;
}
.resize-handle--bottom-right {
  right: -0.02rem;
  bottom: -0.02rem;
}
.resize-handle--bottom-left {
  left: -0.02rem;
  bottom: -0.02rem;
  cursor: nesw-resize;
}
.resize-handle--top-right {
  right: -0.02rem;
  top: -0.02rem;
  cursor: nesw-resize;
  transform: rotate(180deg);
}
.resize-handle--top-left {
  left: -0.02rem;
  top: -0.02rem;
  cursor: nwse-resize;
}
.resize-handle--layers .resize-corner--one {
  right: 0.04rem;
  bottom: 0.18rem;
  width: 0.66rem;
  height: 2px;
  transform: rotate(45deg);
  transform-origin: right bottom;
}
.resize-handle--layers .resize-corner--two {
  right: 0.18rem;
  bottom: 0.04rem;
  width: 2px;
  height: 0.66rem;
  transform: rotate(45deg);
  transform-origin: right bottom;
}
.resize-handle--analysis .resize-corner--one {
  left: 0.04rem;
  bottom: 0.18rem;
  width: 0.66rem;
  height: 2px;
  transform: rotate(-45deg);
  transform-origin: left bottom;
}
.resize-handle--analysis .resize-corner--two {
  left: 0.18rem;
  bottom: 0.04rem;
  width: 2px;
  height: 0.66rem;
  transform: rotate(-45deg);
  transform-origin: left bottom;
}
.resize-corner {
  position: absolute;
  background: rgba(90, 162, 255, 0.72);
  border-radius: 999px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.04) inset;
}
.resize-corner--one {
  right: 0.12rem;
  bottom: 0.24rem;
  width: 0.42rem;
  height: 2px;
}
.resize-corner--two {
  right: 0.24rem;
  bottom: 0.12rem;
  width: 2px;
  height: 0.42rem;
}
.panel-anchor:hover .resize-handle {
  transform: scale(1.02);
}
.restore-pill svg,
.icon-button svg {
  width: 0.9rem;
  height: 0.9rem;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.restore-pill svg {
  width: 0.86rem;
  height: 0.86rem;
}
@media (max-width: 900px) {
  .panel-anchor {
    transform: none !important;
  }
  .drag-handle {
    display: none;
  }
  .panel-tools {
    padding: 0.38rem 0.44rem;
  }
  .panel-body {
    padding: 0.4rem;
  }
  .resize-handle {
    display: none;
  }
}
</style>
