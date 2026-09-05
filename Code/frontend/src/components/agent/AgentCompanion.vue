<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getAgentCompanionPosition, setAgentCompanionPosition } from '../../services/settings-local'
import {
  companionDockOffset,
  COMPANION_SIZE_PX,
  isCompanionDragGesture,
  snapCompanionPosition,
  type CompanionDock,
} from '../../composables/useAgentCompanionPosition'
import AgentChatPanel from './AgentChatPanel.vue'

defineProps<{
  fitToLayerExtent?: (instanceId: string) => boolean
  fitChina?: () => boolean
  locateCoordinate?: (lng: number, lat: number, zoom?: number) => boolean
  setBasemap?: (sourceId: string) => boolean
}>()

const open = ref(false)
const x = ref(0)
const y = ref(0)
const dock = ref<CompanionDock>('right')
const dragging = ref(false)
const greeting = ref(false)
const hovered = ref(false)
const clickPulse = ref(false)
const stageOffset = ref({ left: 0, top: 0 })

const rootRef = ref<HTMLElement | null>(null)
let dragMoved = false
let pointerId: number | null = null
let startClientX = 0
let startClientY = 0
let originX = 0
let originY = 0
let cachedStageWidth = 1200
let cachedStageHeight = 800
let companionDragRaf: number | null = null
let pendingCompanionX = 0
let pendingCompanionY = 0
let greetingTimer: number | null = null
let clickPulseTimer: number | null = null
let hoverLeaveTimer: number | null = null

function flushCompanionDrag() {
  companionDragRaf = null
  x.value = pendingCompanionX
  y.value = pendingCompanionY
}

function resolveStageEl(): HTMLElement | null {
  return (
    (document.querySelector('.map-shell') as HTMLElement | null) ??
    rootRef.value?.parentElement ??
    null
  )
}

function stageSize() {
  const el = resolveStageEl()
  if (!el) {
    stageOffset.value = { left: 0, top: 0 }
    return { width: window.innerWidth, height: window.innerHeight }
  }
  const r = el.getBoundingClientRect()
  stageOffset.value = { left: r.left, top: r.top }
  return { width: r.width, height: r.height }
}

function applyDefaultPosition() {
  const stage = stageSize()
  const saved = getAgentCompanionPosition()
  if (!saved) {
    const snapped = snapCompanionPosition(
      { x: stage.width - COMPANION_SIZE_PX - 16, y: Math.max(96, stage.height * 0.55) },
      stage,
    )
    x.value = snapped.x
    y.value = snapped.y
    dock.value = snapped.dock === 'none' ? 'right' : snapped.dock
    persist()
    return
  }
  const snapped = snapCompanionPosition({ x: saved.x, y: saved.y }, stage)
  x.value = snapped.x
  y.value = snapped.y
  dock.value = saved.dock === 'none' ? snapped.dock : saved.dock
}

function persist() {
  setAgentCompanionPosition({ x: x.value, y: y.value, dock: dock.value })
}

/** 贴边半藏；hover / 打开 / 拖动时完全呼出 */
const dockExpanded = computed(() => open.value || hovered.value || dragging.value || greeting.value)

/**
 * 命中层始终停在逻辑坐标 (x,y)，不随 peek 位移——避免边缘 hover 时
 * 视觉平移导致 pointerleave/enter 振荡闪烁。
 */
const wrapStyle = computed(() => ({
  width: `${COMPANION_SIZE_PX}px`,
  height: `${COMPANION_SIZE_PX}px`,
  transform: `translate3d(${stageOffset.value.left + x.value}px, ${stageOffset.value.top + y.value}px, 0)`,
}))

/** 仅视觉 peek：在命中层内平移，命中矩形不动 */
const visualPeekStyle = computed(() => {
  const offset = dockExpanded.value ? 0 : companionDockOffset(dock.value)
  const dragFx = dragging.value ? ' scale(1.08) rotate(-4deg)' : ''
  return {
    transform: `translate3d(${offset}px, 0, 0)${dragFx}`,
  }
})

const panelAnchor = computed(() => ({
  x: stageOffset.value.left + x.value,
  y: stageOffset.value.top + y.value,
  dock: dock.value,
  viewport: true as const,
}))

function playGreeting() {
  greeting.value = true
  if (greetingTimer != null) window.clearTimeout(greetingTimer)
  greetingTimer = window.setTimeout(() => {
    greeting.value = false
    greetingTimer = null
  }, 1400)
}

function playClickPulse() {
  clickPulse.value = true
  if (clickPulseTimer != null) window.clearTimeout(clickPulseTimer)
  clickPulseTimer = window.setTimeout(() => {
    clickPulse.value = false
    clickPulseTimer = null
  }, 420)
}

function onHoverEnter() {
  if (hoverLeaveTimer != null) {
    window.clearTimeout(hoverLeaveTimer)
    hoverLeaveTimer = null
  }
  stageSize()
  hovered.value = true
}

function onHoverLeave() {
  if (hoverLeaveTimer != null) window.clearTimeout(hoverLeaveTimer)
  // 短延迟：peek 动画/子元素空隙不立刻收起
  hoverLeaveTimer = window.setTimeout(() => {
    hovered.value = false
    hoverLeaveTimer = null
  }, 180)
}

function onPointerDown(ev: PointerEvent) {
  if (ev.button !== 0) return
  const target = ev.currentTarget as HTMLElement
  pointerId = ev.pointerId
  target.setPointerCapture(ev.pointerId)
  dragging.value = true
  dragMoved = false
  startClientX = ev.clientX
  startClientY = ev.clientY
  originX = x.value
  originY = y.value
  const stage = stageSize()
  cachedStageWidth = stage.width
  cachedStageHeight = stage.height
  if (dock.value !== 'none') {
    dock.value = 'none'
  }
}

function onPointerMove(ev: PointerEvent) {
  if (!dragging.value || pointerId !== ev.pointerId) return
  const dx = ev.clientX - startClientX
  const dy = ev.clientY - startClientY
  if (isCompanionDragGesture(dx, dy)) dragMoved = true
  // 拖动中只钳制舞台，不重新测量 DOM，避免 Layout Thrashing
  const maxX = Math.max(0, cachedStageWidth - COMPANION_SIZE_PX)
  const maxY = Math.max(0, cachedStageHeight - COMPANION_SIZE_PX)
  pendingCompanionX = Math.min(maxX, Math.max(0, originX + dx))
  pendingCompanionY = Math.min(maxY, Math.max(0, originY + dy))
  if (companionDragRaf === null) {
    companionDragRaf = requestAnimationFrame(flushCompanionDrag)
  }
}

function onPointerUp(ev: PointerEvent) {
  if (!dragging.value || pointerId !== ev.pointerId) return
  if (companionDragRaf !== null) {
    cancelAnimationFrame(companionDragRaf)
    companionDragRaf = null
    x.value = pendingCompanionX
    y.value = pendingCompanionY
  }
  dragging.value = false
  pointerId = null
  try {
    ;(ev.currentTarget as HTMLElement).releasePointerCapture(ev.pointerId)
  } catch {
    /* ignore */
  }
  const stage = stageSize()
  if (open.value) {
    // 对话打开时保持自由位置，不贴边，避免面板与挂件抢位跳动
    const maxX = Math.max(0, stage.width - COMPANION_SIZE_PX)
    const maxY = Math.max(0, stage.height - COMPANION_SIZE_PX)
    x.value = Math.min(maxX, Math.max(0, x.value))
    y.value = Math.min(maxY, Math.max(0, y.value))
    dock.value = 'none'
  } else {
    const snapped = snapCompanionPosition({ x: x.value, y: y.value }, stage)
    x.value = snapped.x
    y.value = snapped.y
    dock.value = snapped.dock
  }
  persist()
  if (!dragMoved) {
    playClickPulse()
    open.value = !open.value
    if (open.value) playGreeting()
  }
}

function onResize() {
  const snapped = snapCompanionPosition({ x: x.value, y: y.value }, stageSize())
  x.value = snapped.x
  y.value = snapped.y
  if (open.value) {
    dock.value = 'none'
  } else if (dock.value !== 'none') {
    dock.value = snapped.dock
  }
  persist()
}

onMounted(() => {
  applyDefaultPosition()
  window.addEventListener('resize', onResize)
  window.setTimeout(() => playGreeting(), 600)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (companionDragRaf != null) cancelAnimationFrame(companionDragRaf)
  if (greetingTimer != null) window.clearTimeout(greetingTimer)
  if (clickPulseTimer != null) window.clearTimeout(clickPulseTimer)
  if (hoverLeaveTimer != null) window.clearTimeout(hoverLeaveTimer)
})

watch(open, (v) => {
  if (v && dock.value !== 'none') {
    const stage = stageSize()
    if (dock.value === 'right') {
      x.value = Math.max(0, stage.width - COMPANION_SIZE_PX - 8)
    } else if (dock.value === 'left') {
      x.value = 8
    }
    // 打开后改为自由拖动坐标，避免贴边 peek 与面板布局冲突
    dock.value = 'none'
    persist()
  }
})
</script>

<template>
  <Teleport to="body">
    <div ref="rootRef" class="agent-companion-root">
      <!-- 命中层固定在逻辑坐标；视觉 peek 只动内部，消除边缘闪烁 -->
      <div
        class="agent-companion-wrap"
        :class="{ 'agent-companion-wrap--dragging': dragging }"
        :style="wrapStyle"
        @pointerenter="onHoverEnter"
        @pointerleave="onHoverLeave"
      >
        <button
          type="button"
          class="agent-companion"
          :class="{
            'agent-companion--dragging': dragging,
            'agent-companion--docked': dock !== 'none' && !open && !hovered,
            'agent-companion--dock-peek': dock !== 'none' && !dockExpanded,
            'agent-companion--dock-left': dock === 'left',
            'agent-companion--dock-right': dock === 'right',
            'agent-companion--open': open,
            'agent-companion--greet': greeting,
            'agent-companion--click': clickPulse,
            'agent-companion--hover': hovered && !dragging,
          }"
          :style="visualPeekStyle"
          :aria-label="open ? '关闭地图助手' : '打开地图助手'"
          :aria-expanded="open"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
        >
          <span class="agent-companion-aura" aria-hidden="true" />
          <span class="agent-companion-ring" aria-hidden="true" />
          <span class="agent-companion-ripple" aria-hidden="true" />
          <span class="agent-companion-body" aria-hidden="true">
            <span class="agent-companion-antenna" />
            <span class="agent-companion-visor">
              <i class="agent-companion-eye" />
              <i class="agent-companion-eye" />
            </span>
            <span class="agent-companion-mouth" />
            <span class="agent-companion-badge" />
          </span>
          <span
            v-if="dock !== 'none' && !dockExpanded"
            class="agent-companion-tab"
            aria-hidden="true"
          />
          <span v-if="greeting && !open" class="agent-companion-bubble" aria-hidden="true">Hi</span>
        </button>
      </div>

      <AgentChatPanel
        :open="open"
        :anchor="panelAnchor"
        :dragging="dragging"
        :fit-to-layer-extent="fitToLayerExtent"
        :fit-china="fitChina"
        :locate-coordinate="locateCoordinate"
        :set-basemap="setBasemap"
        @close="open = false"
      />
    </div>
  </Teleport>
</template>

<style scoped>
.agent-companion-root {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 1600;
}

.agent-companion-wrap {
  position: absolute;
  left: 0;
  top: 0;
  pointer-events: auto;
  /* 命中层移动时不播过渡，避免与 peek 视觉过渡叠加 */
  transition: none;
  will-change: transform;
  touch-action: none;
}

.agent-companion {
  --agent-size: 56px;
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: auto;
  border: 1px solid color-mix(in srgb, var(--accent-border) 70%, var(--border-default));
  border-radius: 20px;
  background:
    radial-gradient(
      120% 80% at 30% 20%,
      color-mix(in srgb, var(--accent) 18%, transparent),
      transparent 55%
    ),
    linear-gradient(165deg, var(--surface-3), var(--surface-2) 62%, var(--surface-1));
  color: var(--text-primary);
  box-shadow:
    0 10px 28px rgba(0, 0, 0, 0.28),
    0 0 0 1px color-mix(in srgb, var(--accent-surface) 40%, transparent) inset;
  cursor: grab;
  padding: 0;
  display: grid;
  place-items: center;
  opacity: 1;
  transition:
    opacity var(--motion-surface-duration) var(--motion-surface-ease),
    box-shadow var(--motion-surface-duration) var(--motion-surface-ease),
    border-color var(--motion-surface-duration) var(--motion-surface-ease),
    filter var(--motion-surface-duration) var(--motion-surface-ease),
    transform 280ms cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform, opacity;
  touch-action: none;
  user-select: none;
  overflow: visible;
}

.agent-companion-wrap--dragging .agent-companion,
.agent-companion--dragging {
  transition:
    opacity var(--motion-interactive-duration) var(--motion-interactive-ease),
    box-shadow var(--motion-interactive-duration) var(--motion-interactive-ease),
    filter var(--motion-interactive-duration) var(--motion-interactive-ease);
}

.agent-companion--dock-peek {
  opacity: 0.48;
  filter: saturate(0.85);
}

.agent-companion--docked:hover,
.agent-companion--hover {
  opacity: 1;
  filter: saturate(1.08) brightness(1.03);
}

.agent-companion:hover,
.agent-companion--open {
  border-color: var(--accent-border);
  box-shadow:
    0 14px 32px rgba(0, 0, 0, 0.32),
    0 0 24px color-mix(in srgb, var(--accent) 22%, transparent);
}

.agent-companion--dragging {
  cursor: grabbing;
  opacity: 1;
  filter: brightness(1.06) saturate(1.1);
  box-shadow:
    0 22px 48px rgba(0, 0, 0, 0.4),
    0 0 32px color-mix(in srgb, var(--accent) 35%, transparent);
}

.agent-companion--click .agent-companion-body {
  animation: agent-click-pop var(--motion-slow) var(--ease-emphasized);
}

.agent-companion--click .agent-companion-ripple {
  animation: agent-ripple var(--motion-slow) var(--ease-decelerate);
}

.agent-companion-aura {
  position: absolute;
  inset: -10px;
  border-radius: 24px;
  background: radial-gradient(
    circle,
    color-mix(in srgb, var(--accent) 28%, transparent),
    transparent 68%
  );
  opacity: 0.35;
  pointer-events: none;
  z-index: 0;
}

.agent-companion-ring {
  position: absolute;
  inset: 4px;
  border-radius: 16px;
  border: 1px dashed color-mix(in srgb, var(--accent-border) 55%, transparent);
  opacity: 0.45;
  pointer-events: none;
  z-index: 0;
}

.agent-companion-ripple {
  position: absolute;
  inset: 8px;
  border-radius: 18px;
  border: 2px solid color-mix(in srgb, var(--accent) 70%, transparent);
  opacity: 0;
  pointer-events: none;
  z-index: 0;
}

.agent-companion-body {
  position: relative;
  z-index: 1;
  width: 36px;
  height: 36px;
  border-radius: 13px;
  background:
    linear-gradient(
      180deg,
      color-mix(in srgb, var(--accent-surface) 90%, white),
      var(--accent-surface)
    ),
    var(--surface-1);
  border: 1px solid var(--accent-border);
  box-shadow: inset 0 1px 0 color-mix(in srgb, white 18%, transparent);
  display: grid;
  place-items: center;
}

.agent-companion-antenna {
  position: absolute;
  top: -9px;
  left: 50%;
  width: 2px;
  height: 9px;
  transform: translateX(-50%);
  background: linear-gradient(var(--accent-strong), var(--accent));
  border-radius: 2px;
}

.agent-companion-antenna::after {
  content: '';
  position: absolute;
  top: -5px;
  left: 50%;
  width: 7px;
  height: 7px;
  transform: translateX(-50%);
  border-radius: 50%;
  background: var(--accent-strong);
  box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 70%, transparent);
}

.agent-companion-visor {
  display: flex;
  gap: 7px;
  margin-top: 1px;
  padding: 3px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--surface-base) 55%, transparent);
  border: 1px solid color-mix(in srgb, var(--border-default) 70%, transparent);
}

.agent-companion-eye {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent-strong);
  box-shadow: 0 0 6px color-mix(in srgb, var(--accent) 80%, transparent);
  display: block;
}

.agent-companion-mouth {
  position: absolute;
  bottom: 6px;
  width: 11px;
  height: 3px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--accent) 75%, var(--text-strong));
}

.agent-companion-badge {
  position: absolute;
  right: -3px;
  bottom: -3px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--success);
  border: 1.5px solid var(--surface-2);
  box-shadow: 0 0 6px color-mix(in srgb, var(--success) 50%, transparent);
}

.agent-companion-tab {
  position: absolute;
  top: 50%;
  width: 4px;
  height: 18px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--accent) 75%, transparent);
  box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 45%, transparent);
  transform: translateY(-50%);
  pointer-events: none;
  z-index: 2;
  animation: agent-tab-pulse 1.8s ease-in-out infinite;
}

.agent-companion--dock-right .agent-companion-tab {
  left: 6px;
}

.agent-companion--dock-left .agent-companion-tab {
  right: 6px;
}

.agent-companion-bubble {
  position: absolute;
  top: -20px;
  right: 100%;
  margin-right: 8px;
  padding: 0.2rem 0.5rem;
  border-radius: 8px;
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--accent-strong);
  background: var(--surface-3);
  border: 1px solid var(--accent-border);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
  white-space: nowrap;
  pointer-events: none;
  animation: agent-bubble-in var(--motion-modal) var(--ease-decelerate);
}

.agent-companion-bubble::after {
  content: '';
  position: absolute;
  right: -5px;
  top: 50%;
  width: 8px;
  height: 8px;
  transform: translateY(-50%) rotate(45deg);
  background: var(--surface-3);
  border-right: 1px solid var(--accent-border);
  border-top: 1px solid var(--accent-border);
}

@media (prefers-reduced-motion: no-preference) {
  .agent-companion:not(.agent-companion--dragging) .agent-companion-body {
    animation: agent-idle 3.2s ease-in-out infinite;
  }

  .agent-companion:not(.agent-companion--dragging) .agent-companion-aura {
    animation: agent-aura 3.2s ease-in-out infinite;
  }

  .agent-companion:not(.agent-companion--dragging) .agent-companion-ring {
    animation: agent-spin 12s linear infinite;
  }

  .agent-companion:not(.agent-companion--dragging) .agent-companion-eye {
    animation: agent-blink 5.5s ease-in-out infinite;
  }

  .agent-companion--greet:not(.agent-companion--dragging) .agent-companion-body {
    animation: agent-wave 0.7s ease-in-out 2;
  }

  .agent-companion--open .agent-companion-badge {
    animation: agent-pulse 1.6s ease-in-out infinite;
  }
}

@keyframes agent-idle {
  0%,
  100% {
    transform: translateY(0) rotate(0deg);
  }
  40% {
    transform: translateY(-3px) rotate(-1.5deg);
  }
  70% {
    transform: translateY(-1px) rotate(1deg);
  }
}

@keyframes agent-aura {
  0%,
  100% {
    opacity: 0.28;
    transform: scale(0.96);
  }
  50% {
    opacity: 0.55;
    transform: scale(1.05);
  }
}

@keyframes agent-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes agent-blink {
  0%,
  46%,
  50%,
  100% {
    transform: scaleY(1);
    opacity: 1;
  }
  48% {
    transform: scaleY(0.15);
    opacity: 0.55;
  }
}

@keyframes agent-wave {
  0%,
  100% {
    transform: translateY(0) rotate(0deg);
  }
  25% {
    transform: translateY(-4px) rotate(-8deg);
  }
  55% {
    transform: translateY(-2px) rotate(7deg);
  }
}

@keyframes agent-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.2);
    opacity: 0.75;
  }
}

@keyframes agent-bubble-in {
  from {
    opacity: 0;
    transform: translateX(6px) scale(0.9);
  }
  to {
    opacity: 1;
    transform: translateX(0) scale(1);
  }
}

@keyframes agent-click-pop {
  0% {
    transform: scale(1);
  }
  35% {
    transform: scale(0.88);
  }
  70% {
    transform: scale(1.12);
  }
  100% {
    transform: scale(1);
  }
}

@keyframes agent-ripple {
  0% {
    opacity: 0.7;
    transform: scale(0.7);
  }
  100% {
    opacity: 0;
    transform: scale(1.55);
  }
}

@keyframes agent-tab-pulse {
  0%,
  100% {
    opacity: 0.55;
    transform: translateY(-50%) scaleY(1);
  }
  50% {
    opacity: 1;
    transform: translateY(-50%) scaleY(1.15);
  }
}

@media (prefers-reduced-motion: reduce) {
  .agent-companion,
  .agent-companion--dragging {
    transition: none;
  }

  .agent-companion-bubble,
  .agent-companion-tab,
  .agent-companion--click .agent-companion-body,
  .agent-companion--click .agent-companion-ripple {
    animation: none;
  }
}
</style>
