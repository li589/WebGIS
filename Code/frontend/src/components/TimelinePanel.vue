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
  draggable: true,
  collapsible: true,
  defaultCollapsed: false,
  maxOffsetX: 140,
  maxOffsetY: 70,
  defaultWidth: 720,
  defaultHeight: 190,
  minWidth: 460,
  minHeight: 170,
  maxWidth: 980,
  maxHeight: 248,
})

const persistedState = readPersistedState(props.panelKey)
const visible = ref(persistedState?.visible ?? true)
const collapsed = ref(persistedState?.collapsed ?? props.defaultCollapsed)
const offsetX = ref(persistedState?.offsetX ?? 0)
const offsetY = ref(persistedState?.offsetY ?? 0)
const width = ref(persistedState?.width ?? props.defaultWidth)
const height = ref(persistedState?.height ?? props.defaultHeight)
const persistTimer = ref<number | null>(null)

let dragStartX = 0
let dragStartY = 0
let baseOffsetX = 0
let baseOffsetY = 0
const dragging = ref(false)

const frameStyle = computed(() => ({ transform: `translate(${offsetX.value}px, ${offsetY.value}px)` }))
const panelStyle = computed(() => ({
  width: `${Math.max(props.minWidth, Math.min(props.maxWidth, width.value))}px`,
  height: collapsed.value ? '2.55rem' : `${Math.max(props.minHeight, Math.min(props.maxHeight, height.value))}px`,
}))

function clamp(value: number, limit: number) {
  return Math.min(limit, Math.max(-limit, value))
}

function startDragging(event: PointerEvent) {
  if (!props.draggable || window.innerWidth < 900) return
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
  offsetX.value = clamp(baseOffsetX + event.clientX - dragStartX, props.maxOffsetX)
  offsetY.value = clamp(baseOffsetY + event.clientY - dragStartY, props.maxOffsetY)
}

function stopDragging() {
  dragging.value = false
  window.removeEventListener('pointermove', handleDragMove)
  window.removeEventListener('pointerup', stopDragging)
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
}

function hidePanel() {
  visible.value = false
}

function showPanel() {
  visible.value = true
}

watch([visible, collapsed, offsetX, offsetY, width, height], () => {
  if (typeof window === 'undefined' || !props.panelKey) return
  if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
  persistTimer.value = window.setTimeout(() => {
    const nextState: PersistedPanelState = {
      visible: visible.value,
      collapsed: collapsed.value,
      offsetX: offsetX.value,
      offsetY: offsetY.value,
      width: width.value,
      height: height.value,
    }
    window.localStorage.setItem(getStorageKey(props.panelKey), JSON.stringify(nextState))
    persistTimer.value = null
  }, 120)
})

onBeforeUnmount(() => {
  stopDragging()
  if (persistTimer.value !== null) window.clearTimeout(persistTimer.value)
})
</script>

<template>
  <div class="timeline-anchor" :style="frameStyle">
    <button v-if="!visible" class="restore-pill" type="button" @click="showPanel">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8s2.2-3.5 6-3.5S14 8 14 8s-2.2 3.5-6 3.5S2 8 2 8Zm6 1.8A1.8 1.8 0 1 0 8 6.2a1.8 1.8 0 0 0 0 3.6Z" /></svg>
      <span>时间轴</span>
    </button>

    <section v-else class="timeline-panel" :style="panelStyle">
      <header class="timeline-header" :class="{ 'timeline-header-dragging': dragging }" @pointerdown.prevent="startDragging">
        <div class="timeline-title">
          <span class="timeline-grip" aria-hidden="true">
            <i></i><i></i><i></i>
          </span>
          <span class="timeline-kicker">时间控制</span>
          <strong>{{ panelLabel }}</strong>
        </div>
        <div class="timeline-actions">
          <button v-if="collapsible" class="tool-button icon-button" type="button" :title="collapsed ? '展开' : '收起'" @click.stop="toggleCollapsed">
            <svg v-if="collapsed" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M8 3l5 5-5 5" /></svg>
            <svg v-else viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M8 13 3 8l5-5" /></svg>
          </button>
          <button class="tool-button icon-button" type="button" title="复位" @click.stop="resetPanel">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8a5 5 0 1 0 1.5-3.6M3 3v3.4h3.4" /></svg>
          </button>
          <button class="tool-button icon-button" type="button" title="隐藏" @click.stop="hidePanel">
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m2.4 2.4 11.2 11.2M6.2 6.2A2.6 2.6 0 0 0 10 9.8M3 8s2.2-3.5 5-3.5c.8 0 1.5.1 2.2.4M13 8s-1.1 1.8-3 2.8" /></svg>
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
.timeline-anchor{position:relative;width:100%;height:100%;display:inline-block;pointer-events:auto;will-change:transform;transition:transform .18s cubic-bezier(.25,.46,.45,.94)}
.timeline-panel{display:flex;flex-direction:column;overflow:hidden;width:100%;border:1px solid rgba(155,180,210,.18);border-radius:1rem;background:linear-gradient(180deg, rgba(18, 28, 46, 0.72), rgba(8, 15, 28, 0.52)), radial-gradient(circle at top left, rgba(255,255,255,0.08), transparent 34%);box-shadow:inset 0 1px 0 rgba(255,255,255,.08), inset 0 -1px 0 rgba(255,255,255,.03), 0 14px 30px rgba(1,8,16,.14);backdrop-filter:blur(14px) saturate(1.08);-webkit-backdrop-filter:blur(14px) saturate(1.08)}
.timeline-header{display:flex;align-items:center;justify-content:space-between;gap:.5rem;min-height:2.3rem;padding:.26rem .36rem;border-bottom:1px solid rgba(136,192,255,.12);background:linear-gradient(180deg, rgba(18, 28, 46, 0.74), rgba(8, 18, 33, 0.62));backdrop-filter:blur(12px) saturate(1.08);-webkit-backdrop-filter:blur(12px) saturate(1.08);box-shadow:inset 0 1px 0 rgba(255,255,255,.08);cursor:grab;user-select:none}
.timeline-header-dragging{cursor:grabbing}
.timeline-title{display:grid;grid-template-columns:auto 1fr;grid-template-rows:auto auto;column-gap:.34rem;row-gap:.02rem;align-items:center;min-width:0}
.timeline-grip{grid-row:1 / span 2;display:grid;gap:.14rem;align-content:center;padding:.1rem 0}
.timeline-grip i{display:block;width:.22rem;height:.22rem;border-radius:999px;background:rgba(141,178,214,.72);box-shadow:0 0 0 1px rgba(255,255,255,.05)}
.timeline-kicker{color:#7f93a9;font-size:.5rem;letter-spacing:.08em;text-transform:uppercase}
.timeline-title strong{color:#eef6ff;font-size:.68rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.timeline-actions{display:inline-flex;gap:.22rem;flex:0 0 auto}
.tool-button{border:1px solid rgba(136,192,255,.12);border-radius:.62rem;background:rgba(8,18,33,.58);color:#d5e5f5;cursor:pointer;font:inherit;padding:.24rem .38rem;transition:border-color .18s ease,color .18s ease,background-color .18s ease,transform .18s ease,box-shadow .18s ease}.tool-button:hover{border-color:rgba(136,192,255,.28);color:#f3fbff;background:rgba(12,24,42,.72);transform:translateY(-1px);box-shadow:0 8px 18px rgba(1,8,16,.12)}
.icon-button{display:inline-flex;align-items:center;justify-content:center;width:1.55rem;height:1.55rem;padding:0}
.timeline-body{padding:.18rem .22rem .26rem;overflow-x:hidden;overflow-y:auto;min-height:0;height:auto;border-radius:0 0 1rem 1rem;scrollbar-width:none;scrollbar-color:rgba(136,192,255,.22) transparent}
.timeline-body:hover{scrollbar-width:thin}
.timeline-body::-webkit-scrollbar{width:0}
.timeline-body:hover::-webkit-scrollbar{width:4px}
.timeline-body::-webkit-scrollbar-track{background:transparent}
.timeline-body::-webkit-scrollbar-thumb{background:rgba(136,192,255,.22);border-radius:999px}
.timeline-body:hover::-webkit-scrollbar-thumb{background:rgba(136,192,255,.34)}
.restore-pill{display:inline-flex;align-items:center;gap:.42rem;border:1px solid rgba(136,192,255,.16);border-radius:999px;padding:.42rem .68rem;background:rgba(8,18,33,.88);color:#dfeefe;cursor:pointer;font:inherit;font-size:.72rem;box-shadow:0 10px 22px rgba(1,8,16,.14);transition:border-color .18s ease,transform .18s ease,box-shadow .18s ease}
.restore-pill:hover{border-color:rgba(136,192,255,.3);transform:translateY(-1px);box-shadow:0 14px 28px rgba(1,8,16,.2)}
.restore-pill svg,.icon-button svg{width:.86rem;height:.86rem;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
@media (max-width:900px){.timeline-header{padding:.24rem .3rem;cursor:default}.timeline-grip{display:none}.timeline-body{padding:.14rem .14rem .2rem}}
</style>
