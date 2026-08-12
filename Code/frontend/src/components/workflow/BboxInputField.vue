<script setup lang="ts">
/**
 * BboxInputField.vue
 *
 * 空间范围输入组件：4 个数字输入框（西/南/东/北），带范围校验和预设快捷选项。
 * 支持中国区域、全球、自定义预设。
 */
import { computed } from 'vue'

import { getMapDefaults, type MapAoiPreset } from '../../services/map-defaults'

const props = defineProps<{
  /** 当前值，格式 { west, south, east, north } 或 null */
  modelValue: unknown
  readonly?: boolean
  error?: boolean
  /** 分量 key 映射，默认 west/south/east/north */
  fieldKeys?: {
    west?: string
    east?: string
    south?: string
    north?: string
  }
}>()

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, number>]
}>()

const DEFAULT_KEYS = { west: 'west', east: 'east', south: 'south', north: 'north' }

const keys = computed(() => ({ ...DEFAULT_KEYS, ...props.fieldKeys }))

const bbox = computed(() => {
  const v = props.modelValue
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    const obj = v as Record<string, unknown>
    return {
      west: Number(obj[keys.value.west]) || 0,
      south: Number(obj[keys.value.south]) || 0,
      east: Number(obj[keys.value.east]) || 0,
      north: Number(obj[keys.value.north]) || 0,
    }
  }
  return { west: 0, south: 0, east: 0, north: 0 }
})

function emitField(field: 'west' | 'south' | 'east' | 'north', value: number) {
  const updated = { ...bbox.value }
  updated[field] = value
  const result: Record<string, number> = {}
  result[keys.value.west] = updated.west
  result[keys.value.south] = updated.south
  result[keys.value.east] = updated.east
  result[keys.value.north] = updated.north
  emit('update:modelValue', result)
}

function onInput(field: 'west' | 'south' | 'east' | 'north', event: Event) {
  const raw = (event.target as HTMLInputElement).value
  const n = raw.trim() === '' ? 0 : Number(raw)
  if (Number.isFinite(n)) emitField(field, n)
}

const BUILTIN_PRESETS: MapAoiPreset[] = [
  { label: '中国', west: 73, south: 15, east: 137, north: 59 },
  { label: '全球', west: -180, south: -90, east: 180, north: 90 },
]

const PRESETS = computed(() => {
  const org = getMapDefaults().aoiPresets
  const seen = new Set(BUILTIN_PRESETS.map((p) => p.label))
  const extra = org.filter((p) => !seen.has(p.label))
  return [...BUILTIN_PRESETS, ...extra]
})

function applyPreset(preset: MapAoiPreset) {
  const result: Record<string, number> = {}
  result[keys.value.west] = preset.west
  result[keys.value.south] = preset.south
  result[keys.value.east] = preset.east
  result[keys.value.north] = preset.north
  emit('update:modelValue', result)
}

const isValid = computed(() => {
  const b = bbox.value
  return (
    b.west >= -180 &&
    b.west <= 180 &&
    b.east >= -180 &&
    b.east <= 180 &&
    b.south >= -90 &&
    b.south <= 90 &&
    b.north >= -90 &&
    b.north <= 90 &&
    b.west < b.east &&
    b.south < b.north
  )
})
</script>

<template>
  <div class="bbox-field" :class="{ error: error || !isValid }">
    <div class="bbox-grid">
      <div class="bbox-cell">
        <label class="bbox-label">西经</label>
        <input
          type="number"
          class="bbox-input"
          :value="bbox.west"
          :min="-180"
          :max="180"
          :step="0.01"
          :readonly="readonly"
          placeholder="-180~180"
          @input="onInput('west', $event)"
        />
      </div>
      <div class="bbox-cell">
        <label class="bbox-label">南纬</label>
        <input
          type="number"
          class="bbox-input"
          :value="bbox.south"
          :min="-90"
          :max="90"
          :step="0.01"
          :readonly="readonly"
          placeholder="-90~90"
          @input="onInput('south', $event)"
        />
      </div>
      <div class="bbox-cell">
        <label class="bbox-label">东经</label>
        <input
          type="number"
          class="bbox-input"
          :value="bbox.east"
          :min="-180"
          :max="180"
          :step="0.01"
          :readonly="readonly"
          placeholder="-180~180"
          @input="onInput('east', $event)"
        />
      </div>
      <div class="bbox-cell">
        <label class="bbox-label">北纬</label>
        <input
          type="number"
          class="bbox-input"
          :value="bbox.north"
          :min="-90"
          :max="90"
          :step="0.01"
          :readonly="readonly"
          placeholder="-90~90"
          @input="onInput('north', $event)"
        />
      </div>
    </div>
    <div v-if="!readonly" class="bbox-presets">
      <button
        v-for="preset in PRESETS"
        :key="preset.label"
        type="button"
        class="preset-btn"
        :title="`西${preset.west} 南${preset.south} 东${preset.east} 北${preset.north}`"
        @click="applyPreset(preset)"
      >
        {{ preset.label }}
      </button>
    </div>
    <span v-if="!isValid" class="bbox-warn">范围无效：需满足 west &lt; east, south &lt; north</span>
  </div>
</template>

<style scoped>
.bbox-field {
  display: flex;
  flex-direction: column;
  gap: 0.32rem;
}

.bbox-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.32rem;
}

.bbox-cell {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}

.bbox-label {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  font-weight: 500;
}

.bbox-input {
  width: 100%;
  padding: 0.22rem 0.36rem;
  border: 1px solid var(--border-default);
  border-radius: 0.28rem;
  background: var(--surface-raised);
  color: var(--text-strong);
  font: inherit;
  font-size: var(--font-size-caption);
}

.bbox-input:focus {
  outline: none;
  border-color: var(--border-strong);
}

.bbox-field.error .bbox-input {
  border-color: rgba(255, 120, 120, 0.4);
}

.bbox-presets {
  display: flex;
  gap: 0.22rem;
  flex-wrap: wrap;
}

.preset-btn {
  padding: 0.14rem 0.36rem;
  border: 1px solid var(--border-strong);
  border-radius: 0.28rem;
  background: var(--accent-surface);
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  cursor: pointer;
  transition: all 0.15s;
}

.preset-btn:hover {
  background: var(--accent-surface);
  color: var(--accent);
  border-color: var(--border-strong);
}

.bbox-warn {
  font-size: var(--font-size-caption);
  color: var(--warning);
}
</style>
