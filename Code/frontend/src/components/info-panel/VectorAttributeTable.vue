<script setup lang="ts">
/**
 * 矢量属性表 — 绘制要素的选择 / 编辑 / 校验 / 保存。
 *
 * 职责：
 *   1. 表格化展示 drawStore.features（要素序号 + 几何类型 + 动态属性列）
 *   2. 行选择 → 联动地图高亮（selectedFeatureIndex）
 *   3. 单元格编辑 → updateFeatureProperties + 调度草稿持久化
 *   4. 删除行 → removeFeature
 *   5. 保存 → 几何自动检查（S 校验），通过后派发 draw:save
 *
 * 定位：跟随绘制工具栏（drawStore.toolbarRect）——工具栏在上半区时展示在
 * 其下方，在下半区时展示在其上方；水平方向与工具栏中心对齐并钳制在舞台内。
 * 尺寸：右下角可拖拽调整，默认尺寸 = 既往固定尺寸（460×320），持久化到 localStorage。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { X, Trash2, Save, Table2, CheckCircle2, AlertTriangle } from '../ui/icons'
import IconButton from '../ui/IconButton.vue'
import { useDrawStore } from '../../stores/draw-store'
import { useUiStore } from '../../stores/ui'
import { useDrawSave, type DrawValidationIssue } from '../../composables/useDrawSave'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const drawStore = useDrawStore()
const uiStore = useUiStore()
const drawSave = useDrawSave()

const newPropKey = ref('')
const editingCell = ref<string | null>(null)
const validationErrors = ref<DrawValidationIssue[]>([])
const lastSavedAt = ref<string | null>(null)
const isSaving = drawSave.isSaving

const visible = computed(() => uiStore.interactionMode === 'draw')

const geometryTypeLabel: Record<string, string> = {
  Polygon: '面',
  LineString: '线',
}

// ── 尺寸（可调 + 持久化；默认值 = 原固定尺寸）─────────────────────────
const SIZE_STORAGE_KEY = 'geo:draw-attr-table-size:v1'
const DEFAULT_WIDTH = 460
const DEFAULT_HEIGHT = 320
const MIN_WIDTH = 360
const MIN_HEIGHT = 220

function loadSize(): { width: number; height: number } {
  try {
    const raw = localStorage.getItem(SIZE_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { width?: unknown; height?: unknown }
      const width = Number(parsed.width)
      const height = Number(parsed.height)
      if (
        Number.isFinite(width) &&
        Number.isFinite(height) &&
        width >= MIN_WIDTH &&
        height >= MIN_HEIGHT
      ) {
        return { width, height }
      }
    }
  } catch {
    /* ignore */
  }
  return { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT }
}

const panelSize = ref(loadSize())

function persistSize() {
  try {
    localStorage.setItem(SIZE_STORAGE_KEY, JSON.stringify(panelSize.value))
  } catch {
    /* quota exceeded, ignore */
  }
}

// ── 跟随工具栏定位 ────────────────────────────────────────────────────
const GAP_PX = 10
const EDGE_PX = 8

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max))
}

/** 工具栏在上半区 → 表格向下展示；下半区 → 向上展示；空间不足自动翻转 */
const panelStyle = computed(() => {
  const rect = drawStore.toolbarRect
  const shell = drawStore.shellSize
  const { width, height } = panelSize.value
  if (!rect || shell.width <= 0 || shell.height <= 0) {
    // 工具栏几何未就绪：退回舞台顶部居中
    return { top: '120px', left: '50%', transform: 'translateX(-50%)', width: `${width}px` }
  }
  const toolbarCenterY = rect.y + rect.height / 2
  const preferBelow = toolbarCenterY < shell.height / 2
  const centerX = rect.x + rect.width / 2

  const maxW = shell.width - EDGE_PX * 2
  const maxH = shell.height - EDGE_PX * 2
  const w = clamp(width, MIN_WIDTH, Math.min(MIN_WIDTH + 400, maxW))
  const h = clamp(height, MIN_HEIGHT, Math.min(MIN_HEIGHT + 400, maxH))

  const left = clamp(Math.round(centerX - w / 2), EDGE_PX, shell.width - w - EDGE_PX)
  let top: number
  if (preferBelow) {
    top = rect.y + rect.height + GAP_PX
    if (top + h > shell.height - EDGE_PX) top = Math.max(EDGE_PX, rect.y - GAP_PX - h)
  } else {
    top = rect.y - GAP_PX - h
    if (top < EDGE_PX) top = Math.min(shell.height - h - EDGE_PX, rect.y + rect.height + GAP_PX)
  }
  return { left: `${left}px`, top: `${Math.round(top)}px`, width: `${w}px`, height: `${h}px` }
})

// ── 缩放手柄（右下角）─────────────────────────────────────────────────
const isResizing = ref(false)
let resizeStart = { pointerX: 0, pointerY: 0, width: 0, height: 0 }

function onResizeStart(e: MouseEvent) {
  isResizing.value = true
  resizeStart = {
    pointerX: e.clientX,
    pointerY: e.clientY,
    width: panelSize.value.width,
    height: panelSize.value.height,
  }
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
  e.preventDefault()
}

function onResizeMove(e: MouseEvent) {
  if (!isResizing.value) return
  const shell = drawStore.shellSize
  const maxW = shell.width > 0 ? shell.width - EDGE_PX * 2 : window.innerWidth - 32
  const maxH = shell.height > 0 ? shell.height - EDGE_PX * 2 : window.innerHeight - 32
  panelSize.value = {
    width: clamp(
      resizeStart.width + (e.clientX - resizeStart.pointerX),
      MIN_WIDTH,
      Math.max(MIN_WIDTH, maxW),
    ),
    height: clamp(
      resizeStart.height + (e.clientY - resizeStart.pointerY),
      MIN_HEIGHT,
      Math.max(MIN_HEIGHT, maxH),
    ),
  }
}

function onResizeEnd() {
  isResizing.value = false
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
  persistSize()
}

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
})

// ── 业务逻辑（保持不变）───────────────────────────────────────────────

/** 汇总所有要素出现过的属性键（保持首次出现顺序） */
const propertyKeys = computed(() => {
  const keys: string[] = []
  for (const f of drawStore.features) {
    for (const k of Object.keys(f.properties)) {
      if (!keys.includes(k)) keys.push(k)
    }
  }
  return keys
})

const rows = computed(() =>
  drawStore.features.map((f, i) => ({
    index: i,
    type: geometryTypeLabel[f.geometry.type] ?? f.geometry.type,
    props: f.properties,
  })),
)

const selectedRowIndex = computed(() => drawStore.selectedFeatureIndex)

function toggleSelectRow(index: number) {
  drawStore.setSelectedFeature(drawStore.selectedFeatureIndex === index ? null : index)
}

function startEditCell(key: string) {
  editingCell.value = key
}

/**
 * 单元格值清洗：仅当为纯数字且无前导零时才转为数字，否则保留原字符串，
 * 避免破坏像元编码/地类号等前导零属性（"001" 不应变成 1）。
 */
function coerceCellValue(raw: string): unknown {
  if (raw === '') return ''
  if (/^-?\d+(\.\d+)?$/.test(raw) && !/^-?0\d+/.test(raw)) {
    return Number(raw)
  }
  return raw
}

function commitCell(index: number, key: string, event: Event) {
  const target = event.target as HTMLInputElement
  drawStore.updateFeatureProperties(index, { [key]: coerceCellValue(target.value) })
  drawStore.scheduleDraftPersist()
  editingCell.value = null
}

function removeRow(index: number) {
  drawStore.removeFeature(index)
  drawStore.scheduleDraftPersist()
}

function addPropertyColumn() {
  const key = newPropKey.value.trim()
  if (!key || propertyKeys.value.includes(key)) return
  for (let i = 0; i < drawStore.features.length; i++) {
    drawStore.updateFeatureProperties(i, { [key]: '' })
  }
  newPropKey.value = ''
  drawStore.scheduleDraftPersist()
}

/** 保存：几何校验 + 真实异步上传，成功后才显示"已保存" */
async function handleSave() {
  validationErrors.value = []
  const res = await drawSave.saveDrawLayer()
  if (!res.ok) {
    validationErrors.value = res.validationErrors
    return
  }
  lastSavedAt.value = new Date().toLocaleTimeString('zh-CN')
}
</script>

<template>
  <div
    v-if="visible"
    class="attr-table-panel"
    :class="{ 'attr-table-panel--resizing': isResizing }"
    :style="panelStyle"
  >
    <div class="attr-table-header">
      <span class="attr-table-title">
        <Table2 :size="13" />
        属性表
      </span>
      <span v-if="lastSavedAt" class="attr-table-saved">
        <CheckCircle2 :size="11" />
        {{ lastSavedAt }} 已保存
      </span>
      <button class="attr-table-close" title="关闭" @click="emit('close')">
        <X :size="13" />
      </button>
    </div>

    <div v-if="validationErrors.length > 0" class="attr-table-errors">
      <div v-for="(e, i) in validationErrors" :key="i" class="attr-table-error-item">
        <AlertTriangle :size="11" />
        <span>{{ e.label }}：{{ e.message }}</span>
      </div>
    </div>

    <div v-if="rows.length === 0" class="attr-table-empty">暂无要素</div>

    <div v-else class="attr-table-scroll">
      <table class="attr-table">
        <thead>
          <tr>
            <th class="col-select"></th>
            <th class="col-type">类型</th>
            <th v-for="key in propertyKeys" :key="key" class="col-prop">{{ key }}</th>
            <th class="col-op"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.index"
            :class="{ selected: selectedRowIndex === row.index }"
            @click="toggleSelectRow(row.index)"
          >
            <td class="col-select">{{ row.index + 1 }}</td>
            <td class="col-type">{{ row.type }}</td>
            <td
              v-for="key in propertyKeys"
              :key="key"
              class="col-prop"
              @dblclick="startEditCell(`${row.index}:${key}`)"
            >
              <input
                v-if="editingCell === `${row.index}:${key}`"
                class="cell-input"
                :value="String(row.props[key] ?? '')"
                @click.stop
                @keyup.enter="commitCell(row.index, key, $event)"
                @blur="commitCell(row.index, key, $event)"
              />
              <span v-else class="cell-text">{{ row.props[key] ?? '' }}</span>
            </td>
            <td class="col-op">
              <button class="row-delete" title="删除要素" @click.stop="removeRow(row.index)">
                <Trash2 :size="11" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="attr-table-footer">
      <div class="attr-table-add-col">
        <input
          v-model="newPropKey"
          class="add-col-input"
          placeholder="新增字段名"
          @keyup.enter="addPropertyColumn"
        />
        <button class="add-col-btn" :disabled="!newPropKey.trim()" @click="addPropertyColumn">
          添加字段
        </button>
      </div>
      <IconButton size="sm" :disabled="isSaving" label="校验并保存图层" @click="handleSave">
        <template #icon><Save :size="13" /></template>
      </IconButton>
    </div>
    <div class="attr-table-hint">双击单元格编辑 · 点击行选中地图高亮 · 保存前自动检查几何</div>

    <!-- 右下角尺寸手柄 -->
    <div class="attr-table-resize" title="拖动调整尺寸" @mousedown="onResizeStart">
      <span class="resize-grip"></span>
    </div>
  </div>
</template>

<style scoped>
.attr-table-panel {
  position: absolute;
  z-index: 19;
  background: var(--surface-2);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  padding: 8px 10px;
  max-width: calc(100vw - 1rem);
  user-select: none;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.attr-table-panel--resizing {
  border-color: var(--border-accent);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
}

.attr-table-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-default);
  flex: none;
}

.attr-table-title {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.attr-table-saved {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  font-size: 10px;
  color: var(--success);
}

.attr-table-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.attr-table-close:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.attr-table-errors {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 0;
  flex: none;
}

.attr-table-error-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--danger, #dc2626);
}

.attr-table-empty {
  padding: 16px 0;
  text-align: center;
  font-size: 12px;
  color: var(--text-secondary);
  flex: 1;
}

.attr-table-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.attr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}

.attr-table th {
  position: sticky;
  top: 0;
  background: var(--surface-2);
  color: var(--text-secondary);
  font-weight: 500;
  padding: 4px 6px;
  text-align: left;
  border-bottom: 1px solid var(--border-default);
  white-space: nowrap;
}

.attr-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border-default);
  color: var(--text-primary);
  white-space: nowrap;
}

.attr-table tbody tr {
  cursor: pointer;
}

.attr-table tbody tr:hover {
  background: var(--surface-hover);
}

.attr-table tbody tr.selected {
  background: color-mix(in srgb, var(--accent) 18%, transparent);
}

.col-select {
  width: 28px;
  color: var(--text-secondary);
}

.col-type {
  width: 36px;
}

.col-op {
  width: 28px;
}

.cell-text {
  display: block;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.attr-table-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border-default);
  flex: none;
}

.attr-table-add-col {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
}

.add-col-input {
  width: 100px;
  padding: 2px 6px;
  border: 1px solid var(--border-default);
  border-radius: 4px;
  background: var(--surface-1);
  color: var(--text-primary);
  font-size: 11px;
  outline: none;
}

.add-col-input:focus {
  border-color: var(--accent);
}

.add-col-btn {
  padding: 2px 8px;
  border: 1px solid var(--border-default);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.add-col-btn:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--accent);
}

.add-col-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cell-input {
  width: 100%;
  min-width: 60px;
  padding: 1px 4px;
  border: 1px solid var(--accent);
  border-radius: 3px;
  background: var(--surface-1);
  color: var(--text-primary);
  font-size: 11px;
  outline: none;
}

.row-delete {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 3px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.row-delete:hover {
  background: var(--danger, #dc2626);
  color: #fff;
}

.attr-table-hint {
  margin-top: 4px;
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.8;
  flex: none;
}

/* ── 右下角缩放手柄 ────────────────────────────────────────────────── */
.attr-table-resize {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: nwse-resize;
  touch-action: none;
  z-index: 2;
}

.resize-grip {
  display: block;
  width: 8px;
  height: 8px;
  border-right: 2px solid var(--border-strong);
  border-bottom: 2px solid var(--border-strong);
  border-bottom-right-radius: 2px;
  opacity: 0.55;
  transition: opacity 0.15s ease;
}

.attr-table-panel:hover .resize-grip,
.attr-table-panel--resizing .resize-grip {
  opacity: 1;
  border-color: var(--accent);
}
</style>
