<script setup lang="ts">
/**
 * 科学栅格（MAT/NC/HDF）导入配置：多变量、网格预设、CRS、范围、无效值。
 * 全部配置完成且校验通过后才允许提交导入。
 */
import { computed, ref, watch } from 'vue'
import { listCrs, type CRSDef } from '@/services/crs'
import { DATA_COPY } from '../../ui-copy'

export interface ScienceVariable {
  id: string
  name: string
  shape?: number[] | null
  dtype?: string | null
  fill_value?: number | null
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
}

const props = defineProps<{
  visible: boolean
  fileName: string
  format?: string
  variables: ScienceVariable[]
  gridPresets: GridPreset[]
  suggestedGridPreset?: string | null
  suggestedCrs?: string | null
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
const crsOptions = ref<CRSDef[]>([])

watch(
  () => props.visible,
  (v) => {
    if (!v) return
    crsOptions.value = listCrs()
    selectedIds.value = props.variables.slice(0, 1).map((x) => x.id)
    timeIndex.value = 0
    gridPreset.value = props.suggestedGridPreset || 'custom'
    sourceCrs.value = props.suggestedCrs || 'EPSG:4326'
    invalidText.value = '-9999, -999'
    const fillHints = props.variables
      .map((x) => x.fill_value)
      .filter((x): x is number => x != null && Number.isFinite(x))
    if (fillHints.length) {
      invalidText.value = Array.from(new Set([...fillHints, -9999, -999])).join(', ')
    }
    nodataText.value = ''
    autoConfirm.value = true
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

function selectAllVars() {
  selectedIds.value = props.variables.map((v) => v.id)
}

function clearVars() {
  selectedIds.value = []
}

function handleConfirm() {
  if (!canSubmit.value) return
  emit('confirm', {
    variableIds: [...selectedIds.value],
    timeIndex: timeIndex.value,
    sourceCrs: sourceCrs.value,
    gridPreset: gridPreset.value,
    bounds: [west.value, south.value, east.value, north.value],
    invalidValues: parsedInvalid.value,
    nodata: parsedNodata.value,
    autoConfirm: autoConfirm.value,
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
            <select v-model="sourceCrs">
              <option v-for="c in crsOptions" :key="c.code" :value="c.code">
                {{ c.code }} — {{ c.label }}
              </option>
            </select>
          </label>
        </div>
        <p v-if="shapeHint" class="hint">当前选中变量尺寸：{{ shapeHint }}（行×列）</p>
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
        <label class="time-row">
          {{ DATA_COPY.timeIndex }}
          <input v-model.number="timeIndex" type="number" min="0" step="1" />
        </label>
        <label class="check-row">
          <input v-model="autoConfirm" type="checkbox" />
          导入后自动重投影到 WGS84 并注册图层（推荐）
        </label>
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
  font-size: 0.72rem;
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
  font-size: 0.74rem;
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
  font-size: 0.68rem;
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
  font-size: 0.74rem;
  cursor: pointer;
}
.var-list .meta {
  color: #8aa0b4;
  font-size: 0.66rem;
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
  font-size: 0.64rem;
  color: #8aa0b4;
}
input,
select {
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.34rem;
  padding: 0.3rem 0.4rem;
  background: rgba(4, 12, 23, 0.75);
  color: #d8e6f5;
  font: inherit;
  font-size: 0.72rem;
}
.hint {
  margin: 0.4rem 0 0;
  font-size: 0.64rem;
  color: #8aa0b4;
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
  font-size: 0.7rem;
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
  font-size: 0.74rem;
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
