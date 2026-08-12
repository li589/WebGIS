<script setup lang="ts">
/**
 * 科学栅格（MAT/NC/HDF）导入配置：多变量、网格预设、CRS、范围、无效值。
 * 全部配置完成且校验通过后才允许提交导入。
 */
import { computed, ref, watch } from 'vue'
import { listCrs } from '@/services/crs'
import { fetchCrsOptionsExpanded } from '@/services/data-import'
import type { CRSOption } from '@/services/crs'
import { detectRasterInvalidValues } from '../core/api'
import { DATA_COPY } from '../../ui-copy'
import {
  buildImportTemporalPayload,
  guessTimeLabelFromFilename,
  type ImportTemporalMode,
} from '../../utils/import-temporal'

export interface ScienceVariable {
  id: string
  name: string
  shape?: number[] | null
  dtype?: string | null
  fill_value?: number | null
  needs_transpose?: boolean
  axis_hint?: string | null
}

export interface GridPreset {
  id: string
  label: string
  crs?: string | null
  cols?: number | null
  rows?: number | null
  resolution?: number | null
  bounds?: [number, number, number, number] | null
  geographic_bounds?: [number, number, number, number] | null
  category?: string | null
}

export interface ScienceRasterCommitPayload {
  variableIds: string[]
  timeIndex: number
  sourceCrs: string
  gridPreset: string
  bounds: [number, number, number, number] | null
  invalidValues: number[]
  nodata: number | null
  autoConfirm: boolean
  axisOrder: 'auto' | 'as_is' | 'transpose'
  conflictPolicy: 'overwrite' | 'rename' | 'error'
  temporalMode?: 'auto' | 'static' | 'point' | 'range'
  timePoint?: string
  timeStart?: string
  timeEnd?: string
  nativeStep?: string
}

const props = defineProps<{
  visible: boolean
  fileName: string
  format?: string
  uploadId?: string | null
  variables: ScienceVariable[]
  gridPresets: GridPreset[]
  suggestedGridPreset?: string | null
  suggestedCrs?: string | null
  suggestedNeedsTranspose?: boolean
  importing?: boolean
}>()

const emit = defineEmits<{
  confirm: [payload: ScienceRasterCommitPayload]
  cancel: []
}>()

const selectedIds = ref<string[]>([])
const timeIndex = ref(0)
const gridPreset = ref('custom')
const sourceCrs = ref('EPSG:4326')
const west = ref(0)
const south = ref(0)
const east = ref(0)
const north = ref(0)
const invalidText = ref('-9999, -999')
const nodataText = ref('')
const autoConfirm = ref(true)
const axisOrder = ref<'auto' | 'as_is' | 'transpose'>('auto')
const conflictPolicy = ref<'overwrite' | 'rename' | 'error'>('overwrite')
const detectingInvalid = ref(false)
const invalidDetectNote = ref('')
const temporalMode = ref<ImportTemporalMode>('auto')
const temporalPoint = ref('')
const temporalStart = ref('')
const temporalEnd = ref('')
const temporalNativeStep = ref('')

const temporalPreview = computed(() =>
  buildImportTemporalPayload({
    mode: temporalMode.value,
    fileName: props.fileName,
    timePoint: temporalPoint.value,
    timeStart: temporalStart.value,
    timeEnd: temporalEnd.value,
    nativeStep: temporalNativeStep.value || undefined,
  }),
)
const crsOptions = ref<CRSOption[]>([])
const crsFilter = ref('')

const filteredCrsOptions = computed(() => {
  const q = crsFilter.value.trim().toLowerCase()
  if (!q) return crsOptions.value
  return crsOptions.value.filter(
    (c) =>
      c.code.toLowerCase().includes(q) ||
      String(c.label || '')
        .toLowerCase()
        .includes(q),
  )
})

async function loadCrsOptions() {
  try {
    const data = await fetchCrsOptionsExpanded()
    crsOptions.value = data.items || []
  } catch {
    crsOptions.value = listCrs().map((c) => ({
      code: c.code,
      label: c.label,
      category: c.category,
      area: c.area,
      deprecated: c.deprecated,
    }))
  }
}

watch(
  () => props.visible,
  async (v) => {
    if (!v) return
    await loadCrsOptions()
    crsFilter.value = ''
    selectedIds.value = props.variables.slice(0, 1).map((x) => x.id)
    timeIndex.value = 0
    gridPreset.value = props.suggestedGridPreset || 'custom'
    sourceCrs.value = props.suggestedCrs || 'EPSG:4326'
    axisOrder.value = props.suggestedNeedsTranspose ? 'auto' : 'auto'
    conflictPolicy.value = 'overwrite'
    invalidText.value = '-9999, -999'
    invalidDetectNote.value = ''
    detectingInvalid.value = false
    const fillHints = props.variables
      .map((x) => x.fill_value)
      .filter((x): x is number => x != null && Number.isFinite(x))
    if (fillHints.length) {
      invalidText.value = Array.from(new Set([...fillHints, -9999, -999])).join(', ')
    }
    nodataText.value = ''
    autoConfirm.value = true
    temporalMode.value = 'auto'
    temporalPoint.value = ''
    temporalStart.value = ''
    temporalEnd.value = ''
    temporalNativeStep.value = ''
    const guessed = guessTimeLabelFromFilename(props.fileName)
    if (guessed?.kind === 'point') {
      temporalPoint.value = guessed.label
      temporalNativeStep.value = guessed.nativeStep
    } else if (guessed?.kind === 'range') {
      const [a, b] = guessed.label.split('_')
      temporalStart.value = a || ''
      temporalEnd.value = b || ''
      temporalNativeStep.value = guessed.nativeStep
    }
    applyPreset(gridPreset.value)
  },
  { immediate: true },
)

const presetMap = computed(() => new Map(props.gridPresets.map((p) => [p.id, p])))

function applyPreset(id: string) {
  const p = presetMap.value.get(id)
  if (!p) return
  if (p.crs) sourceCrs.value = p.crs
  // 投影 bounds 用对称官方角点；预览地理范围可参考 geographic_bounds
  if (p.bounds && p.bounds.length === 4) {
    west.value = p.bounds[0]
    south.value = p.bounds[1]
    east.value = p.bounds[2]
    north.value = p.bounds[3]
  }
}

watch(gridPreset, (id) => applyPreset(id))

const shapeHint = computed(() => {
  const first = props.variables.find((v) => selectedIds.value.includes(v.id))
  if (!first?.shape?.length) return ''
  return first.shape.join(' × ')
})

const transposeHint = computed(() => {
  const first = props.variables.find((v) => selectedIds.value.includes(v.id))
  if (first?.needs_transpose || props.suggestedNeedsTranspose) {
    return '检测到相对网格预设的行列颠倒（常见于 MATLAB v7.3/HDF5）。轴序选「自动」将转置为正确地理方向。'
  }
  return ''
})

const parsedInvalid = computed(() => {
  const out: number[] = []
  for (const part of invalidText.value.split(/[,;\s]+/)) {
    if (!part) continue
    const n = Number(part)
    if (Number.isFinite(n)) out.push(n)
  }
  return out
})

const parsedNodata = computed(() => {
  const t = nodataText.value.trim()
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
})

const boundsValid = computed(() => {
  const w = west.value
  const s = south.value
  const e = east.value
  const n = north.value
  return (
    Number.isFinite(w) &&
    Number.isFinite(s) &&
    Number.isFinite(e) &&
    Number.isFinite(n) &&
    w < e &&
    s < n
  )
})

const canSubmit = computed(
  () =>
    !props.importing &&
    selectedIds.value.length > 0 &&
    Boolean(sourceCrs.value) &&
    boundsValid.value,
)

function toggleVar(id: string) {
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((x) => x !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

async function runDetectInvalid() {
  const uploadId = props.uploadId
  const variableId = selectedIds.value[0]
  if (!uploadId || !variableId) {
    invalidDetectNote.value = '请先选择变量（并确保上传已完成）'
    return
  }
  detectingInvalid.value = true
  invalidDetectNote.value = '检测中…'
  try {
    const data = await detectRasterInvalidValues({ uploadId, variableId })
    const suggested = Array.isArray(data.suggested_invalid_values)
      ? data.suggested_invalid_values
      : []
    if (suggested.length) {
      invalidText.value = suggested.join(', ')
      invalidDetectNote.value = `已填入建议无效值（共 ${suggested.length} 个）`
    } else {
      invalidDetectNote.value = '未检测到明确哨兵值；可手工填写'
    }
  } catch (err) {
    invalidDetectNote.value = err instanceof Error ? err.message : String(err)
  } finally {
    detectingInvalid.value = false
  }
}

function selectAllVars() {
  selectedIds.value = props.variables.map((v) => v.id)
}

function clearVars() {
  selectedIds.value = []
}

function handleConfirm() {
  if (!canSubmit.value) return
  if (
    (temporalMode.value === 'point' || temporalMode.value === 'range') &&
    !temporalPreview.value.preview
  ) {
    return
  }
  emit('confirm', {
    variableIds: [...selectedIds.value],
    timeIndex: timeIndex.value,
    sourceCrs: sourceCrs.value,
    gridPreset: gridPreset.value,
    bounds: [west.value, south.value, east.value, north.value],
    invalidValues: parsedInvalid.value,
    nodata: parsedNodata.value,
    autoConfirm: autoConfirm.value,
    axisOrder: axisOrder.value,
    conflictPolicy: conflictPolicy.value,
    temporalMode: temporalMode.value,
    timePoint: temporalPoint.value,
    timeStart: temporalStart.value,
    timeEnd: temporalEnd.value,
    nativeStep: temporalNativeStep.value || undefined,
  })
}

function handleCancel() {
  if (props.importing) return
  emit('cancel')
}
</script>

<template>
  <div v-if="visible" class="sci-overlay" @click.self="handleCancel">
    <div class="sci-panel" role="dialog" aria-modal="true">
      <header class="sci-head">
        <div>
          <h3>科学栅格导入配置</h3>
          <p class="sub">{{ fileName }}{{ format ? ` · ${format}` : '' }}</p>
        </div>
        <button type="button" class="x-btn" :disabled="importing" @click="handleCancel">✕</button>
      </header>

      <section class="sci-section">
        <div class="sec-title">
          <span>1. 选择变量（可多选，每个变量导入为一层）</span>
          <span class="sec-actions">
            <button type="button" class="link-btn" @click="selectAllVars">全选</button>
            <button type="button" class="link-btn" @click="clearVars">清空</button>
          </span>
        </div>
        <ul class="var-list">
          <li v-for="v in variables" :key="v.id">
            <label>
              <input
                type="checkbox"
                :checked="selectedIds.includes(v.id)"
                @change="toggleVar(v.id)"
              />
              <strong>{{ v.name }}</strong>
              <span class="meta">
                {{ v.shape ? v.shape.join('×') : '—' }}
                <template v-if="v.dtype"> · {{ v.dtype }}</template>
                <template v-if="v.fill_value != null"> · fill={{ v.fill_value }}</template>
              </span>
            </label>
          </li>
        </ul>
        <p v-if="!variables.length" class="hint">未检测到可用二维变量</p>
      </section>

      <section class="sci-section">
        <div class="sec-title">2. 坐标系与网格范围</div>
        <div class="grid-2">
          <label>
            网格预设
            <select v-model="gridPreset">
              <option v-for="p in gridPresets" :key="p.id" :value="p.id">{{ p.label }}</option>
            </select>
          </label>
          <label>
            源坐标系
            <input
              v-model="crsFilter"
              type="search"
              placeholder="搜索 EPSG / 名称（全量 UTM/GK）"
              style="margin-bottom: 0.35rem"
            />
            <select v-model="sourceCrs">
              <option v-for="c in filteredCrsOptions" :key="c.code" :value="c.code">
                {{ c.code }} — {{ c.label }}
              </option>
            </select>
          </label>
        </div>
        <p v-if="shapeHint" class="hint">当前选中变量尺寸：{{ shapeHint }}（行×列）</p>
        <p v-if="transposeHint" class="hint">{{ transposeHint }}</p>
        <label>
          轴序（XY）
          <select v-model="axisOrder">
            <option value="auto">自动（推荐，按网格预设校正颠倒）</option>
            <option value="as_is">保持原样</option>
            <option value="transpose">强制转置（等同 swap_xy）</option>
          </select>
        </label>
        <p class="hint">轴序与 swap_xy 一致：transpose = 交换行列；EASE 全球图拉伸时优先用自动。</p>
        <div class="grid-4">
          <label>West<input v-model.number="west" type="number" step="any" /></label>
          <label>South<input v-model.number="south" type="number" step="any" /></label>
          <label>East<input v-model.number="east" type="number" step="any" /></label>
          <label>North<input v-model.number="north" type="number" step="any" /></label>
        </div>
        <p class="hint" :class="{ bad: !boundsValid }">
          {{
            boundsValid
              ? 'bounds 将写入 GeoTIFF 地理参考；非 WGS84 时导入后自动重投影到地图显示'
              : '请填写有效范围（West < East，South < North）'
          }}
        </p>
      </section>

      <section class="sci-section">
        <div class="sec-title">3. 无效值转换（导入前）</div>
        <div class="grid-2">
          <label>
            无效值列表（逗号分隔）
            <input v-model="invalidText" type="text" placeholder="-9999, -999" />
          </label>
          <label>
            输出 nodata（可空=NaN）
            <input v-model="nodataText" type="text" placeholder="留空则用 NaN" />
          </label>
        </div>
        <div class="detect-row">
          <button
            type="button"
            class="ghost"
            :disabled="detectingInvalid || importing || !uploadId"
            @click="runDetectInvalid"
          >
            {{ detectingInvalid ? '检测中…' : '自动检测无效值' }}
          </button>
          <span v-if="invalidDetectNote" class="hint">{{ invalidDetectNote }}</span>
        </div>
        <label class="time-row">
          {{ DATA_COPY.timeIndex }}
          <input v-model.number="timeIndex" type="number" min="0" step="1" />
        </label>
        <label class="check-row">
          <input v-model="autoConfirm" type="checkbox" />
          导入后自动重投影到 WGS84 并注册图层（推荐）
        </label>
        <label>
          同名图层
          <select v-model="conflictPolicy">
            <option value="overwrite">覆盖已导入的同名图层（不额外占配额，推荐）</option>
            <option value="rename">另存为新图层（需有剩余配额）</option>
            <option value="error">若已存在则报错</option>
          </select>
        </label>
      </section>

      <section class="sci-section">
        <div class="sec-title"><span>数据时间（文件名可自动识别）</span></div>
        <div class="temporal-modes">
          <label><input v-model="temporalMode" type="radio" value="auto" /> 自动</label>
          <label><input v-model="temporalMode" type="radio" value="static" /> 静态</label>
          <label><input v-model="temporalMode" type="radio" value="point" /> 时间点</label>
          <label><input v-model="temporalMode" type="radio" value="range" /> 时间段</label>
        </div>
        <div v-if="temporalMode === 'point'" class="grid-2">
          <label>
            日期
            <input v-model="temporalPoint" type="text" placeholder="YYYYMMDD" />
          </label>
          <label>
            步长
            <input v-model="temporalNativeStep" type="text" placeholder="1d" />
          </label>
        </div>
        <div v-else-if="temporalMode === 'range'" class="grid-2">
          <label>
            起
            <input v-model="temporalStart" type="text" placeholder="YYYYMMDD" />
          </label>
          <label>
            止
            <input v-model="temporalEnd" type="text" placeholder="YYYYMMDD" />
          </label>
          <label>
            步长
            <input v-model="temporalNativeStep" type="text" placeholder="8d" />
          </label>
        </div>
        <p v-if="temporalPreview.preview" class="hint">
          将写入：{{ temporalPreview.preview.kind }} · {{ temporalPreview.preview.label
          }}{{
            temporalPreview.preview.nativeStep ? ` · ${temporalPreview.preview.nativeStep}` : ''
          }}
        </p>
      </section>

      <footer class="sci-foot">
        <button type="button" class="ghost" :disabled="importing" @click="handleCancel">
          取消
        </button>
        <button type="button" class="primary" :disabled="!canSubmit" @click="handleConfirm">
          {{ importing ? '导入中…' : `确认导入 ${selectedIds.length || 0} 个图层` }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.sci-overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(2, 8, 16, 0.62);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.sci-panel {
  width: min(720px, 96vw);
  max-height: min(88vh, 900px);
  overflow: auto;
  border-radius: 0.7rem;
  border: 1px solid rgba(136, 192, 255, 0.22);
  background: linear-gradient(180deg, rgba(12, 26, 42, 0.98), rgba(6, 14, 24, 0.98));
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.45);
  padding: 1rem 1.1rem 0.9rem;
  color: #d7e6f5;
}
.sci-head {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  margin-bottom: 0.75rem;
}
.sci-head h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 650;
}
.sub {
  margin: 0.2rem 0 0;
  font-size: var(--font-size-caption);
  color: #8aa0b4;
}
.x-btn {
  border: 0;
  background: transparent;
  color: #9ab0c4;
  cursor: pointer;
  font-size: 1rem;
}
.sci-section {
  margin-bottom: 0.85rem;
  padding: 0.65rem 0.7rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.12);
  background: rgba(4, 12, 22, 0.45);
}
.sec-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--font-size-caption);
  color: #9ec4e0;
  margin-bottom: 0.5rem;
}
.sec-actions {
  display: flex;
  gap: 0.45rem;
}
.link-btn {
  border: 0;
  background: transparent;
  color: #7ee0a8;
  cursor: pointer;
  font-size: var(--font-size-caption);
}
.var-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  max-height: 10rem;
  overflow: auto;
}
.var-list label {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: var(--font-size-caption);
  cursor: pointer;
}
.var-list .meta {
  color: #8aa0b4;
  font-size: var(--font-size-caption);
}
.temporal-modes {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem 0.9rem;
  margin-bottom: 0.45rem;
  font-size: var(--font-size-caption);
  color: #c5d7ea;
}
.temporal-modes label {
  display: inline-flex;
  flex-direction: row;
  align-items: center;
  gap: 0.28rem;
  cursor: pointer;
  font-size: var(--font-size-caption);
  color: #c5d7ea;
}
.grid-2,
.grid-4 {
  display: grid;
  gap: 0.45rem 0.55rem;
}
.grid-2 {
  grid-template-columns: 1fr 1fr;
}
.grid-4 {
  grid-template-columns: repeat(4, 1fr);
  margin-top: 0.45rem;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.18rem;
  font-size: var(--font-size-caption);
  color: #8aa0b4;
}
input,
select {
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.34rem;
  padding: 0.3rem 0.4rem;
  background: rgba(4, 12, 23, 0.75);
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
}
.hint {
  margin: 0.4rem 0 0;
  font-size: var(--font-size-caption);
  color: #8aa0b4;
}
.detect-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin: 0.35rem 0 0.25rem;
}
.detect-row .hint {
  margin: 0;
}
.hint.bad {
  color: #ffb0b0;
}
.time-row {
  margin-top: 0.45rem;
  max-width: 10rem;
}
.check-row {
  margin-top: 0.5rem;
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
  font-size: var(--font-size-caption);
  color: #c5d8ea;
}
.sci-foot {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding-top: 0.35rem;
}
.ghost,
.primary {
  border-radius: 0.4rem;
  padding: 0.42rem 0.85rem;
  font: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
}
.ghost {
  border: 1px solid rgba(136, 192, 255, 0.22);
  background: transparent;
  color: #c5d8ea;
}
.primary {
  border: 1px solid rgba(126, 224, 168, 0.4);
  background: rgba(24, 70, 48, 0.65);
  color: #d6ffe8;
}
.primary:disabled,
.ghost:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
@media (max-width: 640px) {
  .grid-2,
  .grid-4 {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
