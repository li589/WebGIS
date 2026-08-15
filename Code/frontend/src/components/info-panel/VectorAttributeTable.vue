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
 */
import { computed, ref } from 'vue'
import { X, Trash2, Save, Table2, CheckCircle2, AlertTriangle } from '../ui/icons'
import IconButton from '../ui/IconButton.vue'
import { useDrawStore } from '../../stores/draw-store'
import { useUiStore } from '../../stores/ui'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const drawStore = useDrawStore()
const uiStore = useUiStore()

const newPropKey = ref('')
const editingCell = ref<string | null>(null)
const validationErrors = ref<string[]>([])
const lastSavedAt = ref<string | null>(null)
const isSaving = ref(false)

const visible = computed(() => uiStore.interactionMode === 'draw')

const geometryTypeLabel: Record<string, string> = {
  Polygon: '面',
  LineString: '线',
}

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

function commitCell(index: number, key: string, event: Event) {
  const target = event.target as HTMLInputElement
  const raw = target.value
  let value: unknown = raw
  if (raw !== '' && !Number.isNaN(Number(raw))) value = Number(raw)
  drawStore.updateFeatureProperties(index, { [key]: value })
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

/** 保存前几何自动检查 */
function validateFeatures(): string[] {
  const errors: string[] = []
  const features = drawStore.features
  if (features.length === 0) {
    errors.push('图层为空，将按空图层丢弃处理')
    return errors
  }
  for (let i = 0; i < features.length; i++) {
    const f = features[i]
    const label = `要素 ${i + 1}`
    if (f.geometry.type === 'Polygon') {
      const ring = f.geometry.coordinates[0] ?? []
      if (ring.length < 4) {
        errors.push(`${label}：面环至少需要 4 个坐标（含闭合点）`)
      } else {
        const first = ring[0]
        const last = ring[ring.length - 1]
        if (first[0] !== last[0] || first[1] !== last[1]) {
          errors.push(`${label}：面环未闭合`)
        }
      }
    } else if (f.geometry.type === 'LineString') {
      if ((f.geometry.coordinates ?? []).length < 2) {
        errors.push(`${label}：线至少需要 2 个顶点`)
      }
    }
    const coords =
      f.geometry.type === 'Polygon'
        ? (f.geometry.coordinates[0] ?? [])
        : (f.geometry.coordinates ?? [])
    for (const c of coords) {
      if (!Number.isFinite(c[0]) || !Number.isFinite(c[1])) {
        errors.push(`${label}：包含非法坐标`)
        break
      }
    }
  }
  return errors
}

async function handleSave() {
  validationErrors.value = validateFeatures()
  // 空图层（无硬性几何错误）允许走保存流程 —— handleDrawSave 会丢弃
  const blocking = validationErrors.value.filter((e) => !e.includes('空图层'))
  if (blocking.length > 0) return

  isSaving.value = true
  try {
    window.dispatchEvent(new CustomEvent('draw:save'))
    lastSavedAt.value = new Date().toLocaleTimeString('zh-CN')
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div v-if="visible" class="attr-table-panel">
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
        <span>{{ e }}</span>
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
  </div>
</template>

<style scoped>
.attr-table-panel {
  position: absolute;
  left: 1rem;
  bottom: 10rem;
  z-index: 19;
  background: var(--surface-elevated);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  padding: 8px 10px;
  width: 460px;
  max-width: calc(100vw - 2rem);
  user-select: none;
}

.attr-table-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

.attr-table-title {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
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
  background: var(--hover);
  color: var(--text);
}

.attr-table-errors {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 0;
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
}

.attr-table-scroll {
  max-height: 220px;
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
  background: var(--surface-elevated);
  color: var(--text-secondary);
  font-weight: 500;
  padding: 4px 6px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.attr-table td {
  padding: 3px 6px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  white-space: nowrap;
}

.attr-table tbody tr {
  cursor: pointer;
}

.attr-table tbody tr:hover {
  background: var(--hover);
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

.cell-input {
  width: 100%;
  min-width: 60px;
  padding: 1px 4px;
  border: 1px solid var(--accent);
  border-radius: 3px;
  background: var(--surface);
  color: var(--text);
  font-size: 11px;
  outline: none;
}

.cell-text {
  display: block;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
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

.attr-table-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
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
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface);
  color: var(--text);
  font-size: 11px;
  outline: none;
}

.add-col-input:focus {
  border-color: var(--accent);
}

.add-col-btn {
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.add-col-btn:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}

.add-col-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.attr-table-hint {
  margin-top: 4px;
  font-size: 10px;
  color: var(--text-secondary);
  opacity: 0.8;
}
</style>
