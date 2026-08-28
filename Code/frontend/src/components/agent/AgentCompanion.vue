<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  getAgentCompanionPosition,
  setAgentCompanionPosition,
} from '../../services/settings-local'
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
let greetingTimer: number | null = null
let clickPulseTimer: number | null = null

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
const dockExpanded = computed(
  () => open.value || hovered.value || dragging.value || greeting.value,
)

const visualX = computed(() => {
  const offset = dockExpanded.value ? 0 : companionDockOffset(dock.value)
  return x.value + offset
})

const style = computed(() => {
  const dragFx = dragging.value ? ' scale(1.08) rotate(-4deg)' : ''
  return {
    width: `${COMPANION_SIZE_PX}px`,
    height: `${COMPANION_SIZE_PX}px`,
    transform: `translate3d(${stageOffset.value.left + visualX.value}px, ${stageOffset.value.top + y.value}px, 0)${dragFx}`,
  }
})

const panelAnchor = computed(() => ({
  x: stageOffset.value.left + visualX.value,
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
  stageSize()
  hovered.value = true
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
  stageSize()
  if (dock.value !== 'none') {
    dock.value = 'none'
  }
}

function onPointerMove(ev: PointerEvent) {
  if (!dragging.value || pointerId !== ev.pointerId) return
  const dx = ev.clientX - startClientX
  const dy = ev.clientY - startClientY
  if (isCompanionDragGesture(dx, dy)) dragMoved = true
  const snapped = snapCompanionPosition(
    { x: originX + dx, y: originY + dy },
    stageSize(),
  )
  x.value = snapped.x
  y.value = snapped.y
  dock.value = 'none'
}

function onPointerUp(ev: PointerEvent) {
  if (!dragging.value || pointerId !== ev.pointerId) return
  dragging.value = false
  pointerId = null
  try {
    ;(ev.currentTarget as HTMLElement).releasePointerCapture(ev.pointerId)
  } catch {
    /* ignore */
  }
  const snapped = snapCompanionPosition({ x: x.value, y: y.value }, stageSize())
  x.value = snapped.x
  y.value = snapped.y
  dock.value = snapped.dock
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
  if (dock.value !== 'none') dock.value = snapped.dock
  persist()
}

onMounted(() => {
  applyDefaultPosition()
  window.addEventListener('resize', onResize)
  window.setTimeout(() => playGreeting(), 600)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (greetingTimer != null) window.clearTimeout(greetingTimer)
  if (clickPulseTimer != null) window.clearTimeout(clickPulseTimer)
})

watch(open, (v) => {
  if (v && dock.value !== 'none') {
    const stage = stageSize()
    if (dock.value === 'right') {
      x.value = Math.max(0, stage.width - COMPANION_SIZE_PX - 8)
    } else if (dock.value === 'left') {
      x.value = 8
    }
  }
})
</script>

<template>
  <Teleport to="body">
    <div ref="rootRef" class="agent-companion-root">
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
        :style="style"
        :aria-label="open ? '关闭地图助手' : '打开地图助手'"
        :aria-expanded="open"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerUp"
        @pointercancel="onPointerUp"
        @pointerenter="onHoverEnter"
        @pointerleave="hovered = false"
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

      <AgentChatPanel
        :open="open"
        :anchor="panelAnchor"
        :fit-to-layer-extent="fitToLayerExtent"
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
  /* 高于设置/日志/工作流面板，避免被侧栏与浮层盖住 */
  z-index: 1600;
}

.agent-companion {
  --agent-size: 56px;
  position: absolute;
  left: 0;
  top: 0;
  pointer-events: auto;
  border: 1px solid color-mix(in srgb, var(--accent-border) 70%, var(--border-default));
  border-radius: 20px;
  background:
    radial-gradient(120% 80% at 30% 20%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 55%),
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
    opacity 220ms ease,
    box-shadow 220ms ease,
    border-color 220ms ease,
    filter 220ms ease,
    transform 280ms cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform, opacity;
  touch-action: none;
  user-select: none;
  overflow: visible;
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
  /* 拖动时关闭 transform 过渡，避免滞后 */
  transition:
    opacity 120ms ease,
    box-shadow 120ms ease,
    filter 120ms ease;
}

.agent-companion--click .agent-companion-body {
  animation: agent-click-pop 420ms cubic-bezier(0.22, 1, 0.36, 1);
}

.agent-companion--click .agent-companion-ripple {
  animation: agent-ripple 420ms ease-out;
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
    linear-gradient(180deg, color-mix(in srgb, var(--accent-surface) 90%, white), var(--accent-surface)),
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
  top: -18px;
  right: 100%;
  margin-right: 6px;
  padding: 0.15rem 0.45rem;
  border-radius: 8px;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--accent-strong);
  background: var(--surface-3);
  border: 1px solid var(--accent-border);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
  white-space: nowrap;
  pointer-events: none;
  animation: agent-bubble-in 240ms ease-out;
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
