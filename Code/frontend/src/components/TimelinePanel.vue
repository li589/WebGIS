<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

type PanelProps = {
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
}

interface PersistedPanelState {
  visible: boolean
  collapsed: boolean
  offsetX: number
  offsetY: number
  width?: number
  height?: number
  pillOffsetX?: number
  pillOffsetY?: number
}

interface VisibleLayoutSnapshot {
  offsetX: number
  offsetY: number
  width: number
  height: number
  collapsed: boolean
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

const props = withDefaults(defineProps<PanelProps>(), {
  draggable: true, // 允许拖拽
  collapsible: true, // 允许折叠
  defaultCollapsed: false, // 默认展开
  maxOffsetX: 140, // 最大水平偏移
  maxOffsetY: 70, // 最大垂直偏移
  defaultWidth: 720, // 默认宽度
  defaultHeight: 205, // 默认高度（展开时，预留充足间距）
  minWidth: 500, // 最小宽度
  minHeight: 195, // 最小高度
  maxWidth: 980, // 最大宽度
  maxHeight: 260, // 最大高度
})

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
const width = ref(
  persistedState?.width && persistedState.width >= props.minWidth
    ? persistedState.width
    : props.defaultWidth,
)
const height = ref(persistedState?.height ?? props.defaultHeight)
const persistTimer = ref<number | null>(null)

const visibleLayoutSnapshot = ref<VisibleLayoutSnapshot | null>(
  persistedState
    ? {
        offsetX: persistedState.offsetX ?? 0,
        offsetY: persistedState.offsetY ?? 0,
        width:
          persistedState.width && persistedState.width >= props.minWidth
            ? persistedState.width
            : props.defaultWidth,
        height: persistedState.height ?? props.defaultHeight,
        collapsed: persistedState.collapsed ?? props.defaultCollapsed,
      }
    : null,
)

let dragStartX = 0
let dragStartY = 0
let baseOffsetX = 0
let baseOffsetY = 0
const dragging = ref(false)
const draggingPill = ref(false)
let pillGestureMoved = false
const PILL_DRAG_THRESHOLD_PX = 5
const suppressTransformTransition = ref(false)

const frameStyle = computed(() => ({
  transform: `translate(${offsetX.value}px, ${offsetY.value}px)`,
}))
const panelStyle = computed(() => ({
  width: `${Math.max(props.minWidth, Math.min(props.maxWidth, width.value))}px`,
  height: collapsed.value ? '2.55rem' : 'fit-content',
  maxHeight: collapsed.value
    ? '2.55rem'
    : `${Math.max(props.minHeight, Math.min(props.maxHeight, height.value))}px`,
}))
const anchorClass = computed(() => ({
  'timeline-anchor--interacting': dragging.value || suppressTransformTransition.value,
}))

function clamp(value: number, limit: number) {
  return Math.min(limit, Math.max(-limit, value))
}

function captureVisibleLayout(): VisibleLayoutSnapshot {
  return {
    offsetX: offsetX.value,
    offsetY: offsetY.value,
    width: width.value,
    height: height.value,
    collapsed: collapsed.value,
  }
}

function applyVisibleLayout(snap: VisibleLayoutSnapshot) {
  offsetX.value = snap.offsetX
  offsetY.value = snap.offsetY
  width.value = snap.width
  height.value = snap.height
  collapsed.value = snap.collapsed
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
  window.addEventListener('pointermove', handleDragMove)
  window.addEventListener('pointerup', stopDragging)
}

function handleDragMove(event: PointerEvent) {
  if (!dragging.value) return
  const dx = event.clientX - dragStartX
  const dy = event.clientY - dragStartY
  if (Math.abs(dx) > PILL_DRAG_THRESHOLD_PX || Math.abs(dy) > PILL_DRAG_THRESHOLD_PX) {
    pillGestureMoved = true
  }
  if (draggingPill.value || !visible.value) {
    offsetX.value = baseOffsetX + dx
    offsetY.value = baseOffsetY + dy
    return
  }
  offsetX.value = clamp(baseOffsetX + dx, props.maxOffsetX)
  offsetY.value = clamp(baseOffsetY + dy, props.maxOffsetY)
}

function stopDragging() {
  dragging.value = false
  draggingPill.value = false
  window.removeEventListener('pointermove', handleDragMove)
  window.removeEventListener('pointerup', stopDragging)
}

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
  window.addEventListener('pointermove', handleDragMove)
  window.addEventListener('pointerup', stopPillDragging)
}

function stopPillDragging() {
  const moved = pillGestureMoved
  dragging.value = false
  draggingPill.value = false
  window.removeEventListener('pointermove', handleDragMove)
  window.removeEventListener('pointerup', stopPillDragging)
  if (!moved) showPanel()
}

function toggleCollapsed() {
  if (!props.collapsible) return
  collapsed.value = !collapsed.value
}

function resetPanel() {
  offsetX.value = 0
  offsetY.value = 0
  width.value = props.defaultWidth
  height.value = props.defaultHeight
  collapsed.value = props.defaultCollapsed
  visible.value = true
  visibleLayoutSnapshot.value = captureVisibleLayout()
}

function hidePanel() {
  visibleLayoutSnapshot.value = captureVisibleLayout()
  suppressTransformTransition.value = true
  visible.value = false
  window.requestAnimationFrame(() => {
    suppressTransformTransition.value = false
  })
}

function showPanel() {
  suppressTransformTransition.value = true
  if (visibleLayoutSnapshot.value) {
    applyVisibleLayout(visibleLayoutSnapshot.value)
  }
  visible.value = true
  window.requestAnimationFrame(() => {
    suppressTransformTransition.value = false
  })
}

watch([visible, collapsed, offsetX, offsetY, width, height, visibleLayoutSnapshot], () => {
  if (typeof window === 'undefined' || !props.panelKey) return
  if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
  persistTimer.value = window.setTimeout(() => {
    const snap = visibleLayoutSnapshot.value
    const nextState: PersistedPanelState = {
      visible: visible.value,
      collapsed: visible.value ? collapsed.value : (snap?.collapsed ?? collapsed.value),
      offsetX: visible.value ? offsetX.value : (snap?.offsetX ?? offsetX.value),
      offsetY: visible.value ? offsetY.value : (snap?.offsetY ?? offsetY.value),
      width: visible.value ? width.value : (snap?.width ?? width.value),
      height: visible.value ? height.value : (snap?.height ?? height.value),
      pillOffsetX: visible.value ? undefined : offsetX.value,
      pillOffsetY: visible.value ? undefined : offsetY.value,
    }
    window.localStorage.setItem(getStorageKey(props.panelKey), JSON.stringify(nextState))
    persistTimer.value = null
  }, 120)
})

onBeforeUnmount(() => {
  stopDragging()
  stopPillDragging()
  if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
})
</script>

<template>
  <div class="timeline-anchor" :class="anchorClass" :style="frameStyle">
    <button
      v-if="!visible"
      class="restore-pill"
      type="button"
      :class="{ 'restore-pill--dragging': dragging }"
      title="时间轴 · 拖动自由移动 / 点击展开并恢复原布局"
      @pointerdown="startPillDragging"
      @click.prevent
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path
          d="M2 8s2.2-3.5 6-3.5S14 8 14 8s-2.2 3.5-6 3.5S2 8 2 8Zm6 1.8A1.8 1.8 0 1 0 8 6.2a1.8 1.8 0 0 0 0 3.6Z"
        />
      </svg>
      <span>时间轴</span>
    </button>

    <section v-else class="timeline-panel" :class="{ collapsed }" :style="panelStyle">
      <header
        class="timeline-header"
        :class="{ 'timeline-header-dragging': dragging }"
        @pointerdown.prevent="startDragging"
      >
        <div class="timeline-title">
          <span class="timeline-grip" aria-hidden="true"> <i></i><i></i><i></i> </span>
          <strong>{{ panelLabel }}</strong>
        </div>
        <div class="timeline-actions">
          <button
            v-if="collapsible"
            class="tool-button icon-button"
            type="button"
            :title="collapsed ? '展开' : '收起'"
            @click.stop="toggleCollapsed"
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
            title="复位面板位置"
            @click.stop="resetPanel"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8a5 5 0 1 0 1.5-3.6M3 3v3.4h3.4" />
            </svg>
          </button>
          <button
            class="tool-button icon-button"
            type="button"
            title="隐藏时间轴"
            @click.stop="hidePanel"
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path
                d="m2.4 2.4 11.2 11.2M6.2 6.2A2.6 2.6 0 0 0 10 9.8M3 8s2.2-3.5 5-3.5c.8 0 1.5.1 2.2.4M13 8s-1.1 1.8-3 2.8"
              />
            </svg>
          </button>
        </div>
      </header>

      <div v-show="!collapsed" class="timeline-body">
        <slot> </slot>
      </div>
    </section>
  </div>
</template>

<style scoped>
.timeline-anchor {
  position: relative;
  width: 100%;
  height: 100%;
  display: block;
  pointer-events: auto;
  will-change: transform;
  transition: transform 0.18s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}
.timeline-anchor--interacting {
  transition: none;
}
.timeline-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-sizing: border-box;
  width: 100%;
  border: 1px solid rgba(155, 180, 210, 0.18);
  border-radius: 1rem;
  background:
    linear-gradient(180deg, rgba(20, 32, 54, 0.76), rgba(10, 18, 32, 0.6)),
    radial-gradient(circle at top left, rgba(255, 255, 255, 0.08), transparent 34%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.08),
    inset 0 -1px 0 rgba(255, 255, 255, 0.03),
    0 14px 30px rgba(1, 8, 16, 0.14);
  backdrop-filter: blur(16px) saturate(1.08);
  -webkit-backdrop-filter: blur(16px) saturate(1.08);
  transition: opacity 0.25s cubic-bezier(0.4, 0, 0.2, 1), transform 0.25s ease, border-color 0.2s ease;
}

.timeline-panel.collapsed {
  opacity: 0.55;
}

.timeline-panel.collapsed:hover {
  opacity: 1;
  transform: translateY(-2px);
  border-color: rgba(136, 192, 255, 0.35);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.45), 0 0 14px rgba(56, 189, 248, 0.2);
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
  box-shadow: 0 14px 28px rgba(1, 8, 16, 0.3), 0 0 12px rgba(56, 189, 248, 0.25);
}

.restore-pill--dragging {
  cursor: grabbing;
  opacity: 1;
}
.timeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  min-height: 2.3rem;
  padding: 0.26rem 0.36rem;
  border-bottom: 1px solid rgba(136, 192, 255, 0.12);
  background: linear-gradient(180deg, rgba(18, 28, 46, 0.74), rgba(8, 18, 33, 0.62));
  backdrop-filter: blur(12px) saturate(1.08);
  -webkit-backdrop-filter: blur(12px) saturate(1.08);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
  cursor: grab;
  user-select: none;
}
.timeline-header-dragging {
  cursor: grabbing;
}
.timeline-title {
  display: flex;
  align-items: center;
  gap: 0.34rem;
  min-width: 0;
}
.timeline-grip {
  display: grid;
  gap: 0.14rem;
  align-content: center;
  padding: 0.1rem 0;
  flex: none;
}
.timeline-grip i {
  display: block;
  width: 0.22rem;
  height: 0.22rem;
  border-radius: 999px;
  background: rgba(141, 178, 214, 0.72);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.05);
}
.timeline-title strong {
  color: #eef6ff;
  font-size: 0.68rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.timeline-actions {
  display: inline-flex;
  gap: 0.22rem;
  flex: 0 0 auto;
}
.tool-button {
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.62rem;
  background: rgba(8, 18, 33, 0.58);
  color: #d5e5f5;
  cursor: pointer;
  font: inherit;
  padding: 0.24rem 0.38rem;
  transition:
    border-color 0.18s ease,
    color 0.18s ease,
    background-color 0.18s ease,
    transform 0.18s ease,
    box-shadow 0.18s ease;
}
.tool-button:hover {
  border-color: rgba(136, 192, 255, 0.28);
  color: #f3fbff;
  background: rgba(12, 24, 42, 0.72);
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgba(1, 8, 16, 0.12);
}
.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.55rem;
  height: 1.55rem;
  padding: 0;
}
.timeline-body {
  padding: 0.18rem 0.22rem 0.26rem;
  overflow-x: hidden;
  overflow-y: auto;
  min-height: 0;
  height: auto;
  border-radius: 0 0 1rem 1rem;
  scrollbar-width: none;
  scrollbar-color: rgba(136, 192, 255, 0.22) transparent;
}
.timeline-body:hover {
  scrollbar-width: thin;
}
.timeline-body::-webkit-scrollbar {
  width: 0;
}
.timeline-body:hover::-webkit-scrollbar {
  width: 4px;
}
.timeline-body::-webkit-scrollbar-track {
  background: transparent;
}
.timeline-body::-webkit-scrollbar-thumb {
  background: rgba(136, 192, 255, 0.22);
  border-radius: 999px;
}
.timeline-body:hover::-webkit-scrollbar-thumb {
  background: rgba(136, 192, 255, 0.34);
}
.restore-pill svg,
.icon-button svg {
  width: 0.86rem;
  height: 0.86rem;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
@media (max-width: 900px) {
  .timeline-header {
    padding: 0.24rem 0.3rem;
    cursor: default;
  }
  .timeline-grip {
    display: none;
  }
  .timeline-body {
    padding: 0.14rem 0.14rem 0.2rem;
  }
}
</style>
