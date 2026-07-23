<script setup lang="ts">
/**
 * 单参数编辑行内容区：按 meta 选择 combobox / toggle / number / array / text。
 */
import ParamCombobox from './ParamCombobox.vue'
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
</script>

<template>
  <!-- 有 options：可输入 + 可选择 -->
  <ParamCombobox
    v-if="meta?.options?.length"
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
        ✕
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
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.32rem;
  background: rgba(8, 17, 31, 0.55);
  color: #e8f3fc;
  font: inherit;
  font-size: 0.6rem;
}

.form-input:focus {
  outline: none;
  border-color: rgba(90, 213, 255, 0.5);
}

.form-input.error {
  border-color: rgba(255, 120, 120, 0.55);
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
  background: rgba(136, 192, 255, 0.15);
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
  background: #6e8ba0;
  border-radius: 50%;
  transition: 0.2s;
}

.toggle-switch input:checked + .toggle-slider {
  background: rgba(90, 213, 255, 0.3);
}

.toggle-switch input:checked + .toggle-slider::before {
  transform: translateX(1rem);
  background: #5ad5ff;
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
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.36rem;
  background: rgba(4, 12, 23, 0.6);
  min-height: 2rem;
  align-items: center;
}

.array-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  padding: 0.16rem 0.36rem;
  border-radius: 0.28rem;
  background: rgba(90, 213, 255, 0.18);
  color: #5ad5ff;
  font-size: 0.54rem;
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
  color: #5ad5ff;
  cursor: pointer;
  font-size: 0.5rem;
  line-height: 1;
  padding: 0;
}

.chip-remove:hover {
  color: #ff8a8a;
}

.array-input {
  flex: 1;
  min-width: 6rem;
  border: none;
  background: transparent;
  color: #d8e6f5;
  font: inherit;
  font-size: 0.58rem;
  outline: none;
}

.array-input::placeholder {
  color: #5a7080;
}
</style>
