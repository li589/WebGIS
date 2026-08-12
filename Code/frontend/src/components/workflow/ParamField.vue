<script setup lang="ts">
/**
 * 单参数编辑行内容区：按 meta.widget 或 meta.type 选择对应控件。
 * widget 优先级最高：date/datetime → 日期选择器，bbox → 经纬度输入器，
 * textarea → 多行文本，path → 路径输入（等宽字体+图标），
 * coordinate → 单点经纬度双输入框。
 * 其余按 options/typeof value/type 自动推断：combobox / toggle / number / array / text。
 */
import ParamCombobox from './ParamCombobox.vue'
import DateInputField from './DateInputField.vue'
import BboxInputField from './BboxInputField.vue'
import { Folder, X } from '../ui/icons'
import type { NodeParamSpec } from '../../services/workflow-definition-api'

defineProps<{
  paramKey: string
  value: unknown
  meta?: NodeParamSpec | null
  readonly?: boolean
  error?: boolean
  placeholder?: string
  arrayBuffer?: string
}>()

const emit = defineEmits<{
  change: [value: unknown]
  'update:arrayBuffer': [value: string]
  addArray: [event: KeyboardEvent]
  removeArray: [index: number]
}>()

/** 默认允许自定义；显式 allow_custom=false / enum 类型 / 闭集键 → 仅可选 */
const CLOSED_OPTION_KEYS = new Set([
  'orbit_mode',
  'source_type',
  'mode',
  'exp_mode',
  'statistic',
  'trend_method',
  'chart_type',
  'resampling',
  'flow_direction',
  'algorithm',
  'nodata_handling',
  'dtype',
  'granularity',
  'resolution_unit',
  'distance_unit',
  'z_unit',
  'native_resolution_unit',
  'method',
  'preset',
])

function allowCustom(meta?: NodeParamSpec | null, paramKey?: string): boolean {
  if (!meta) return true
  if (meta.allow_custom === false) return false
  if (meta.allow_custom === true) return true
  if (meta.type === 'enum' || meta.type === 'option') return false
  if (paramKey && CLOSED_OPTION_KEYS.has(paramKey)) return false
  // format / input_format / output_format 等开放枚举：允许自定义
  return true
}

function onNumberInput(event: Event) {
  const raw = (event.target as HTMLInputElement).value
  if (raw.trim() === '') {
    emit('change', null)
    return
  }
  const n = Number(raw)
  emit('change', Number.isFinite(n) ? n : null)
}

function onCombo(v: string) {
  emit('change', v)
}

/** 从 value 中提取纬度（支持 "lat,lng" 字符串或 {lat,lng} 对象） */
function coordLat(v: unknown): number | string {
  if (v == null) return ''
  if (typeof v === 'object' && !Array.isArray(v)) {
    const obj = v as Record<string, unknown>
    return Number(obj.lat ?? obj.latitude) || ''
  }
  const s = String(v)
  const parts = s.split(',')
  return parts.length >= 2 ? Number(parts[0]) || '' : ''
}

/** 从 value 中提取经度 */
function coordLng(v: unknown): number | string {
  if (v == null) return ''
  if (typeof v === 'object' && !Array.isArray(v)) {
    const obj = v as Record<string, unknown>
    return Number(obj.lng ?? obj.lon ?? obj.longitude) || ''
  }
  const s = String(v)
  const parts = s.split(',')
  return parts.length >= 2 ? Number(parts[1]) || '' : ''
}

/** 更新坐标值，返回新的 "lat,lng" 字符串 */
function updateCoord(v: unknown, field: 'lat' | 'lng', raw: string): string {
  const lat = field === 'lat' ? raw : String(coordLat(v) ?? '')
  const lng = field === 'lng' ? raw : String(coordLng(v) ?? '')
  return `${lat},${lng}`
}
</script>

<template>
  <!-- widget=date/datetime：日期选择器 -->
  <DateInputField
    v-if="meta?.widget === 'date' || meta?.widget === 'datetime'"
    :model-value="value"
    :readonly="readonly"
    :error="error"
    :mode="meta.widget === 'datetime' ? 'datetime' : 'date'"
    @update:model-value="emit('change', $event)"
  />

  <!-- widget=bbox：经纬度输入器 -->
  <BboxInputField
    v-else-if="meta?.widget === 'bbox'"
    :model-value="value"
    :readonly="readonly"
    :error="error"
    :field-keys="meta.bbox_keys"
    @update:model-value="emit('change', $event)"
  />

  <!-- widget=textarea：多行文本 -->
  <textarea
    v-else-if="meta?.widget === 'textarea'"
    class="form-input form-textarea"
    :class="{ error }"
    :value="String(value ?? '')"
    :placeholder="placeholder"
    :readonly="readonly"
    rows="3"
    @input="emit('change', ($event.target as HTMLTextAreaElement).value)"
  ></textarea>

  <!-- widget=path：路径输入（等宽字体 + 目录图标） -->
  <div v-else-if="meta?.widget === 'path'" class="path-input-wrapper" :class="{ error }">
    <span class="path-icon" title="路径"><Folder :size="14" aria-hidden="true" /></span>
    <input
      type="text"
      class="form-input path-input"
      :value="String(value ?? '')"
      :placeholder="placeholder || '输入路径...'"
      :readonly="readonly"
      @input="emit('change', ($event.target as HTMLInputElement).value)"
    />
  </div>

  <!-- widget=coordinate：单点经纬度 -->
  <div v-else-if="meta?.widget === 'coordinate'" class="coord-input-wrapper" :class="{ error }">
    <input
      type="number"
      class="form-input coord-input"
      :value="coordLat(value)"
      :min="-90"
      :max="90"
      :step="0.0001"
      :readonly="readonly"
      placeholder="纬度"
      @input="emit('change', updateCoord(value, 'lat', ($event.target as HTMLInputElement).value))"
    />
    <input
      type="number"
      class="form-input coord-input"
      :value="coordLng(value)"
      :min="-180"
      :max="180"
      :step="0.0001"
      :readonly="readonly"
      placeholder="经度"
      @input="emit('change', updateCoord(value, 'lng', ($event.target as HTMLInputElement).value))"
    />
  </div>

  <!-- 有 options：可输入 + 可选择 -->
  <ParamCombobox
    v-else-if="meta?.options?.length"
    :model-value="String(value ?? '')"
    :options="meta.options"
    :disabled="readonly"
    :allow-custom="allowCustom(meta, paramKey)"
    :placeholder="placeholder"
    :error="error"
    @update:model-value="onCombo"
  />

  <label
    v-else-if="typeof value === 'boolean'"
    class="toggle-switch"
    :class="{ disabled: readonly }"
  >
    <input
      type="checkbox"
      :checked="value"
      :disabled="readonly"
      @change="emit('change', ($event.target as HTMLInputElement).checked)"
    />
    <span class="toggle-slider"></span>
  </label>

  <input
    v-else-if="typeof value === 'number'"
    type="number"
    class="form-input"
    :class="{ error }"
    :value="value"
    :min="meta?.min"
    :max="meta?.max"
    :step="meta?.step"
    :readonly="readonly"
    @input="onNumberInput"
  />

  <div v-else-if="meta?.type === 'array'" class="array-editor">
    <span
      v-for="(item, idx) in Array.isArray(value)
        ? value.map(String)
        : String(value ?? '')
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)"
      :key="idx"
      class="array-chip"
    >
      {{ item }}
      <button v-if="!readonly" class="chip-remove" type="button" @click="emit('removeArray', idx)">
        <X :size="12" aria-hidden="true" />
      </button>
    </span>
    <input
      v-if="!readonly"
      type="text"
      class="array-input"
      :value="arrayBuffer ?? ''"
      placeholder="输入值后按回车添加"
      @input="emit('update:arrayBuffer', ($event.target as HTMLInputElement).value)"
      @keydown.enter="emit('addArray', $event)"
    />
  </div>

  <input
    v-else
    type="text"
    class="form-input"
    :class="{ error }"
    :value="String(value ?? '')"
    :placeholder="placeholder"
    :readonly="readonly"
    @input="emit('change', ($event.target as HTMLInputElement).value)"
  />
</template>

<style scoped>
.form-input {
  width: 100%;
  padding: 0.28rem 0.42rem;
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: var(--surface-raised);
  color: var(--text-strong);
  font: inherit;
  font-size: var(--font-size-caption);
}

.form-input:focus {
  outline: none;
  border-color: var(--border-strong);
}

.form-input.error {
  border-color: rgba(255, 120, 120, 0.55);
}

.form-textarea {
  resize: vertical;
  min-height: 2.4rem;
  line-height: 1.4;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 2rem;
  height: 1rem;
  flex-shrink: 0;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--border-default);
  border-radius: 1rem;
  transition: 0.2s;
}

.toggle-slider::before {
  position: absolute;
  content: '';
  height: 0.72rem;
  width: 0.72rem;
  left: 0.14rem;
  bottom: 0.14rem;
  background: var(--text-faint);
  border-radius: 50%;
  transition: 0.2s;
}

.toggle-switch input:checked + .toggle-slider {
  background: var(--accent-border);
}

.toggle-switch input:checked + .toggle-slider::before {
  transform: translateX(1rem);
  background: var(--accent);
}

.toggle-switch.disabled {
  opacity: 0.5;
  pointer-events: none;
}

.array-editor {
  display: flex;
  flex-wrap: wrap;
  gap: 0.22rem;
  padding: 0.32rem 0.42rem;
  border: 1px solid var(--border-default);
  border-radius: 0.36rem;
  background: var(--surface-raised);
  min-height: 2rem;
  align-items: center;
}

.array-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  padding: 0.16rem 0.36rem;
  border-radius: 0.28rem;
  background: var(--accent-surface);
  color: var(--accent);
  font-size: var(--font-size-caption);
  font-weight: 500;
}

.chip-remove {
  width: 0.72rem;
  height: 0.72rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-size: var(--font-size-caption);
  line-height: 1;
  padding: 0;
}

.chip-remove:hover {
  color: var(--danger);
}

.array-input {
  flex: 1;
  min-width: 6rem;
  border: none;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: var(--font-size-caption);
  outline: none;
}

.array-input::placeholder {
  color: var(--text-disabled);
}

.path-input-wrapper {
  display: flex;
  align-items: center;
  gap: 0.28rem;
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: var(--surface-raised);
  padding: 0 0.42rem;
}

.path-input-wrapper.error {
  border-color: rgba(255, 120, 120, 0.55);
}

.path-icon {
  flex-shrink: 0;
  font-size: var(--font-size-caption);
  opacity: 0.7;
}

.path-input {
  border: none;
  border-radius: 0;
  background: transparent;
  padding: 0.28rem 0;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: var(--font-size-caption);
}

.path-input:focus {
  border-color: transparent;
}

.coord-input-wrapper {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.28rem;
}

.coord-input {
  text-align: center;
  font-size: var(--font-size-caption);
}
</style>
