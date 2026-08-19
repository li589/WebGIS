<script setup lang="ts">
/**
 * 绘制编辑工具栏 — 可拖拽浮动面板（默认：主界面顶栏下方水平居中）。
 *
 * 包含：
 *   - 绘制类型切换（多边形/矩形/线段）
 *   - 操作按钮（撤销/清除/属性表/保存）
 *   - 要素计数
 *   - 仅在 draw 交互模式下显示
 *
 * 定位协议：位置相对 .map-stage（offsetParent），x/y 均可拖拽；
 * 几何（位置+尺寸）实时写入 drawStore.toolbarRect，供属性表联动跟随。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { Square, Hexagon, Minus, Undo2, Trash2, Save, Table2 } from '../ui/icons'
import IconButton from '../ui/IconButton.vue'
import { useDrawStore } from '../../stores/draw-store'
import { useUiStore } from '../../stores/ui'

const drawStore = useDrawStore()
const uiStore = useUiStore()
const { drawMode, features, activeVertices, isDrawing, undoStack } = storeToRefs(drawStore)

const visible = computed(() => uiStore.interactionMode === 'draw')

const featureCount = computed(() => features.value.length)

const canUndo = computed(() => undoStack.value.length > 0)

const modeOptions = [
  { value: 'polygon' as const, label: '多边形', icon: Hexagon },
  { value: 'rectangle' as const, label: '矩形', icon: Square },
  { value: 'line' as const, label: '线段', icon: Minus },
]

/** 默认纵坐标：顶栏（top 0.8rem + 高约 48px）之下留出间隙 */
const DEFAULT_TOP_PX = 72
const EDGE_MARGIN_PX = 8

/** null = 尚未定位（首次显示时落到默认位置）；拖拽后保留用户位置 */
const position = ref<{ x: number; y: number } | null>(null)
const isDragging = ref(false)
const toolbarRef = ref<HTMLElement | null>(null)

let dragStart = { pointerX: 0, pointerY: 0, x: 0, y: 0 }

const shellEl = computed<HTMLElement | null>(
  () => (toolbarRef.value?.offsetParent as HTMLElement | null) ?? null,
)

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

/** 默认位置：水平居中、顶栏正下方 */
function applyDefaultPosition() {
  const shell = shellEl.value
  const el = toolbarRef.value
  if (!shell || !el) return
  const x = Math.round((shell.clientWidth - el.offsetWidth) / 2)
  position.value = { x: clamp(x, EDGE_MARGIN_PX, Infinity), y: DEFAULT_TOP_PX }
}

/** 把工具栏几何同步到 store（属性表跟随依赖此数据） */
function syncRectToStore() {
  const el = toolbarRef.value
  const shell = shellEl.value
  if (!el || !shell) return
  drawStore.setShellSize(shell.clientWidth, shell.clientHeight)
  drawStore.setToolbarRect({
    x: el.offsetLeft,
    y: el.offsetTop,
    width: el.offsetWidth,
    height: el.offsetHeight,
  })
}

function onModeChange(mode: 'polygon' | 'rectangle' | 'line') {
  drawStore.setDrawMode(mode)
}

function handleUndo() {
  drawStore.undo()
}

function handleClear() {
  drawStore.clearAll()
}

function handleSave() {
  // 由 MapCanvas 的 handleDrawSave 处理
  window.dispatchEvent(new CustomEvent('draw:save'))
}

function handleToggleAttrTable() {
  window.dispatchEvent(new CustomEvent('draw:toggle-attr-table'))
}

function onDragStart(e: MouseEvent) {
  if (!toolbarRef.value || !position.value) return
  isDragging.value = true
  dragStart = {
    pointerX: e.clientX,
    pointerY: e.clientY,
    x: position.value.x,
    y: position.value.y,
  }
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
  e.preventDefault()
}

function onDragMove(e: MouseEvent) {
  if (!isDragging.value || !toolbarRef.value) return
  const shell = shellEl.value
  const el = toolbarRef.value
  if (!shell) return
  const x = dragStart.x + (e.clientX - dragStart.pointerX)
  const y = dragStart.y + (e.clientY - dragStart.pointerY)
  position.value = {
    x: clamp(x, 0, shell.clientWidth - el.offsetWidth),
    y: clamp(y, 0, shell.clientHeight - el.offsetHeight),
  }
  syncRectToStore()
}

function onDragEnd() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
  syncRectToStore()
}

function onWindowResize() {
  // 视口变化：未拖拽过的回默认居中；拖拽过的钳回容器内
  if (!position.value) return
  applyDefaultPositionIfPristine()
  clampIntoShell()
  void nextTick(syncRectToStore)
}

function applyDefaultPositionIfPristine() {
  if (position.value === null) applyDefaultPosition()
}

function clampIntoShell() {
  const shell = shellEl.value
  const el = toolbarRef.value
  if (!shell || !el || !position.value) return
  position.value = {
    x: clamp(position.value.x, 0, Math.max(0, shell.clientWidth - el.offsetWidth)),
    y: clamp(position.value.y, 0, Math.max(0, shell.clientHeight - el.offsetHeight)),
  }
}

onMounted(() => {
  window.addEventListener('resize', onWindowResize)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
  window.removeEventListener('resize', onWindowResize)
  drawStore.setToolbarRect(null)
})

// 显示时：首帧测量后落位（首次=默认位置），并把几何同步给属性表；
// immediate 兜底：组件挂载时已处于 draw 模式（如视图重建）也能落位
watch(
  visible,
  async (v) => {
    if (!v) return
    await nextTick()
    await nextTick() // 等 Transition 首帧 + 尺寸稳定
    applyDefaultPositionIfPristine()
    clampIntoShell()
    syncRectToStore()
  },
  { immediate: true },
)
</script>

<template>
  <Transition name="draw-toolbar">
    <div
      v-if="visible"
      ref="toolbarRef"
      class="draw-toolbar"
      :class="{ 'draw-toolbar--dragging': isDragging }"
      :style="{
        left: (position?.x ?? 0) + 'px',
        top: (position?.y ?? DEFAULT_TOP_PX) + 'px',
        visibility: position ? 'visible' : 'hidden',
      }"
    >
      <div class="draw-toolbar-handle" @mousedown="onDragStart">
        <span class="handle-bar"></span>
      </div>

      <div class="draw-toolbar-body">
        <div class="draw-toolbar-section">
          <span class="draw-toolbar-label">类型</span>
          <div class="draw-mode-group">
            <button
              v-for="opt in modeOptions"
              :key="opt.value"
              class="draw-mode-btn"
              :class="{ active: drawMode === opt.value }"
              :title="opt.label"
              @click="onModeChange(opt.value)"
            >
              <component :is="opt.icon" :size="14" />
            </button>
          </div>
        </div>

        <div class="draw-toolbar-divider" />

        <div class="draw-toolbar-section">
          <IconButton size="sm" :disabled="!canUndo" label="撤销 (Ctrl+Z)" @click="handleUndo">
            <template #icon><Undo2 :size="14" /></template>
          </IconButton>
          <IconButton
            size="sm"
            :disabled="features.length === 0 && activeVertices.length === 0"
            label="清除全部"
            @click="handleClear"
          >
            <template #icon><Trash2 :size="14" /></template>
          </IconButton>
          <IconButton
            size="sm"
            :disabled="features.length === 0"
            label="属性表"
            @click="handleToggleAttrTable"
          >
            <template #icon><Table2 :size="14" /></template>
          </IconButton>
          <IconButton
            size="sm"
            :disabled="features.length === 0"
            label="保存图层"
            @click="handleSave"
          >
            <template #icon><Save :size="14" /></template>
          </IconButton>
        </div>

        <div class="draw-toolbar-divider" />

        <div class="draw-toolbar-section">
          <span class="draw-toolbar-count">
            {{
              featureCount > 0 ? `${featureCount} 个要素` : isDrawing ? '绘制中…' : '点击地图开始'
            }}
          </span>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.draw-toolbar {
  position: absolute;
  z-index: 20;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  user-select: none;
  min-width: 240px;
}

.draw-toolbar--dragging {
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
  border-color: var(--border-accent);
}

.draw-toolbar-handle {
  display: flex;
  justify-content: center;
  padding: 5px 0 1px;
  cursor: grab;
}

.draw-toolbar-handle:active {
  cursor: grabbing;
}

.handle-bar {
  display: block;
  width: 28px;
  height: 3px;
  border-radius: 2px;
  background: var(--border-strong);
}

.draw-toolbar-body {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px 8px;
  flex-wrap: wrap;
}

.draw-toolbar-section {
  display: flex;
  align-items: center;
  gap: 2px;
}

.draw-toolbar-label {
  font-size: 10px;
  color: var(--text-secondary);
  margin-right: 4px;
  white-space: nowrap;
}

.draw-toolbar-divider {
  width: 1px;
  height: 20px;
  background: var(--border-default);
  margin: 0 4px;
}

.draw-toolbar-count {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.draw-mode-group {
  display: flex;
  gap: 1px;
  background: var(--surface-1);
  border-radius: 6px;
  padding: 2px;
  border: 1px solid var(--border-default);
}

.draw-mode-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 26px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background 0.15s,
    color 0.15s;
}

.draw-mode-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.draw-mode-btn.active {
  background: var(--accent);
  color: #fff;
}

/* Transition */
.draw-toolbar-enter-active,
.draw-toolbar-leave-active {
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}

.draw-toolbar-enter-from,
.draw-toolbar-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
