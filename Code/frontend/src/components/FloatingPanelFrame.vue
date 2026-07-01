<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    panelLabel: string
    panelKey?: string
    draggable?: boolean
    collapsible?: boolean
    defaultCollapsed?: boolean
    maxOffsetX?: number
    maxOffsetY?: number
  }>(),
  {
    draggable: true,
    collapsible: true,
    defaultCollapsed: false,
    maxOffsetX: 120,
    maxOffsetY: 100,
  },
)

interface PersistedPanelState {
  visible: boolean
  collapsed: boolean
  offsetX: number
  offsetY: number
}

function getStorageKey(panelKey: string | undefined) {
  return panelKey ? `geo-panel:${panelKey}` : ''
}

function readPersistedState(panelKey: string | undefined): PersistedPanelState | null {
  if (typeof window === 'undefined' || !panelKey) {
    return null
  }

  try {
    const raw = window.localStorage.getItem(getStorageKey(panelKey))
    if (!raw) {
      return null
    }

    return JSON.parse(raw) as PersistedPanelState
  } catch {
    return null
  }
}

const persistedState = readPersistedState(props.panelKey)
const visible = ref(persistedState?.visible ?? true)
const collapsed = ref(persistedState?.collapsed ?? props.defaultCollapsed)
const offsetX = ref(persistedState?.offsetX ?? 0)
const offsetY = ref(persistedState?.offsetY ?? 0)
let persistTimer: number | null = null

let dragStartX = 0
let dragStartY = 0
let baseOffsetX = 0
let baseOffsetY = 0
let dragging = false

const frameStyle = computed(() => ({
  transform: `translate(${offsetX.value}px, ${offsetY.value}px)`,
}))

function toggleCollapsed() {
  if (!props.collapsible) {
    return
  }

  collapsed.value = !collapsed.value
}

function hidePanel() {
  visible.value = false
}

function showPanel() {
  visible.value = true
}

function resetPosition() {
  offsetX.value = 0
  offsetY.value = 0
}

function clampOffset(value: number, limit: number) {
  return Math.min(limit, Math.max(-limit, value))
}

function handlePointerMove(event: PointerEvent) {
  if (!dragging) {
    return
  }

  offsetX.value = clampOffset(baseOffsetX + event.clientX - dragStartX, props.maxOffsetX)
  offsetY.value = clampOffset(baseOffsetY + event.clientY - dragStartY, props.maxOffsetY)
}

function stopDragging() {
  dragging = false
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', stopDragging)
}

function startDragging(event: PointerEvent) {
  if (!props.draggable || window.innerWidth < 900) {
    return
  }

  dragging = true
  dragStartX = event.clientX
  dragStartY = event.clientY
  baseOffsetX = offsetX.value
  baseOffsetY = offsetY.value

  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', stopDragging)
}

onBeforeUnmount(() => {
  stopDragging()
  if (persistTimer !== null) {
    window.clearTimeout(persistTimer)
  }
})

watch(
  [visible, collapsed, offsetX, offsetY],
  () => {
    if (typeof window === 'undefined' || !props.panelKey) {
      return
    }

    if (persistTimer !== null) {
      window.clearTimeout(persistTimer)
    }

    persistTimer = window.setTimeout(() => {
      const nextState: PersistedPanelState = {
        visible: visible.value,
        collapsed: collapsed.value,
        offsetX: offsetX.value,
        offsetY: offsetY.value,
      }

      window.localStorage.setItem(getStorageKey(props.panelKey), JSON.stringify(nextState))
      persistTimer = null
    }, 120)
  },
  { deep: false },
)
</script>

<template>
  <div class="panel-anchor" :style="frameStyle">
    <button v-if="!visible" class="restore-pill" type="button" @click="showPanel">
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path
          d="M2 8s2.2-3.5 6-3.5S14 8 14 8s-2.2 3.5-6 3.5S2 8 2 8Zm6 1.8A1.8 1.8 0 1 0 8 6.2a1.8 1.8 0 0 0 0 3.6Z"
        />
      </svg>
      <span>{{ panelLabel }}</span>
    </button>

    <section v-else class="panel-frame" :class="{ collapsed }">
      <header class="panel-tools">
        <button
          v-if="draggable"
          class="drag-handle"
          type="button"
          title="拖动"
          @pointerdown.prevent="startDragging"
        >
          <span></span>
          <span></span>
          <span></span>
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
          <button class="tool-button icon-button" type="button" title="复位" aria-label="复位" @click="resetPosition">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8a5 5 0 1 0 1.5-3.6M3 3v3.4h3.4" />
            </svg>
          </button>
          <button class="tool-button icon-button" type="button" title="隐藏" aria-label="隐藏" @click="hidePanel">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="m2.4 2.4 11.2 11.2M6.2 6.2A2.6 2.6 0 0 0 10 9.8M3 8s2.2-3.5 5-3.5c.8 0 1.5.1 2.2.4M13 8s-1.1 1.8-3 2.8" />
            </svg>
          </button>
        </div>
      </header>

      <div v-show="!collapsed" class="panel-body">
        <slot></slot>
      </div>
    </section>
  </div>
</template>

<style scoped>
.panel-anchor {
  pointer-events: auto;
  transition: transform 0.18s ease;
}

.restore-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.42rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 999px;
  padding: 0.42rem 0.68rem;
  background: rgba(8, 18, 33, 0.78);
  color: #dfeefe;
  cursor: pointer;
  font: inherit;
  font-size: 0.72rem;
  backdrop-filter: blur(12px);
}

.panel-frame {
  min-width: 0;
  border-radius: 1rem;
  background: rgba(4, 11, 22, 0.16);
  box-shadow: 0 14px 30px rgba(1, 8, 16, 0.18);
  opacity: 0.92;
  transition: opacity 0.2s ease, box-shadow 0.2s ease;
}

.panel-frame:hover {
  opacity: 1;
  box-shadow: 0 18px 36px rgba(1, 8, 16, 0.24);
}

.panel-frame.collapsed {
  background: transparent;
  box-shadow: none;
}

.panel-tools {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.26rem 0.34rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.82rem;
  background: rgba(8, 18, 33, 0.54);
  backdrop-filter: blur(16px);
}

.drag-handle,
.tool-button {
  border: 1px solid rgba(136, 192, 255, 0.12);
  border-radius: 0.68rem;
  background: rgba(8, 18, 33, 0.64);
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
}

.drag-handle span {
  width: 0.2rem;
  height: 0.2rem;
  border-radius: 999px;
  background: #8cb5d9;
}

.panel-label {
  min-width: 0;
  margin-right: auto;
  color: #d9ebfb;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
}

.tool-actions {
  display: inline-flex;
  gap: 0.3rem;
}

.tool-button {
  padding: 0.34rem 0.52rem;
  font-size: 0.7rem;
  transition: border-color 0.18s ease, color 0.18s ease, background-color 0.18s ease;
}

.tool-button:hover,
.drag-handle:hover {
  border-color: rgba(136, 192, 255, 0.28);
  color: #f3fbff;
}

.panel-body {
  margin-top: 0.32rem;
}

.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.95rem;
  height: 1.95rem;
  padding: 0;
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
}
</style>
