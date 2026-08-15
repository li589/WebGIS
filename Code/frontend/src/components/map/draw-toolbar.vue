<script setup lang="ts">
/**
 * 绘制编辑工具栏 — 左下角可拖拽浮动面板。
 *
 * 包含：
 *   - 绘制类型切换（多边形/矩形/线段）
 *   - 操作按钮（撤销/清除/保存）
 *   - 要素计数
 *   - 仅在 draw 交互模式下显示
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { Square, Hexagon, Minus, Undo2, Trash2, Save, Table2 } from '../ui/icons'
import IconButton from '../ui/IconButton.vue'
import { useDrawStore } from '../../stores/draw-store'
import { useUiStore } from '../../stores/ui'

const drawStore = useDrawStore()
const uiStore = useUiStore()
const { drawMode, features, activeVertices, isDrawing, undoStack } = storeToRefs(drawStore)

const basePosition = ref({ x: 16, y: 0 })
const isDragging = ref(false)
const dragOffset = ref({ x: 0, y: 0 })
const toolbarRef = ref<HTMLElement | null>(null)

const visible = computed(() => uiStore.interactionMode === 'draw')

const featureCount = computed(() => features.value.length)

const canUndo = computed(() => undoStack.value.length > 0)

const modeOptions = [
  { value: 'polygon' as const, label: '多边形', icon: Hexagon },
  { value: 'rectangle' as const, label: '矩形', icon: Square },
  { value: 'line' as const, label: '线段', icon: Minus },
]

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
  if (!toolbarRef.value) return
  isDragging.value = true
  dragOffset.value = {
    x: e.clientX - toolbarRef.value.getBoundingClientRect().left,
    y: e.clientY - toolbarRef.value.getBoundingClientRect().top,
  }
  document.addEventListener('mousemove', onDragMove)
  document.addEventListener('mouseup', onDragEnd)
}

function onDragMove(e: MouseEvent) {
  if (!isDragging.value) return
  basePosition.value = {
    x: e.clientX - dragOffset.value.x,
    y: e.clientY - dragOffset.value.y,
  }
}

function onDragEnd() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
}

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDragMove)
  document.removeEventListener('mouseup', onDragEnd)
})
</script>

<template>
  <Transition name="draw-toolbar">
    <div
      v-if="visible"
      ref="toolbarRef"
      class="draw-toolbar"
      :style="{
        left: basePosition.x + 'px',
        bottom: '3.5rem',
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
  background: var(--surface-elevated);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
  user-select: none;
  min-width: 240px;
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
  background: var(--border);
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
  background: var(--border);
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
  background: var(--surface);
  border-radius: 6px;
  padding: 2px;
  border: 1px solid var(--border);
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
  background: var(--hover);
  color: var(--text);
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
