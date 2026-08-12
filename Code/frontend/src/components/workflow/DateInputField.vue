<script setup lang="ts">
/**
 * DateInputField.vue
 *
 * 日期输入组件：支持原生 date picker 与 YYYYMMDD / YYYY-MM-DD 双向格式转换。
 * 当 widget='datetime' 时额外显示时间输入。
 */
import { computed } from 'vue'

const props = defineProps<{
  modelValue: unknown
  readonly?: boolean
  error?: boolean
  /** 'date' 仅日期，'datetime' 日期+时间 */
  mode?: 'date' | 'datetime'
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

/** 将 YYYYMMDD 或 ISO 字符串转为 <input type="date"> 需要的 YYYY-MM-DD */
function toIsoDate(value: unknown): string {
  const s = String(value ?? '').trim()
  if (!s) return ''
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10)
  if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
  return ''
}

/** 将 YYYYMMDD 或 ISO 字符串转为 <input type="datetime-local"> 需要的 YYYY-MM-DDTHH:mm */
function toIsoDateTime(value: unknown): string {
  const s = String(value ?? '').trim()
  if (!s) return ''
  // 已经是 ISO datetime
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) return s.slice(0, 16)
  // YYYYMMDDHHmm 格式
  if (/^\d{12}$/.test(s)) {
    return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(8, 10)}:${s.slice(10, 12)}`
  }
  // YYYYMMDD 格式 → 补 00:00
  if (/^\d{8}$/.test(s)) {
    return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T00:00`
  }
  // ISO date only → 补 00:00
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return `${s}T00:00`
  return ''
}

/** 将 ISO 格式转回 YYYYMMDD（或 YYYYMMDDHHmm for datetime） */
function fromIso(value: string, mode: 'date' | 'datetime'): string {
  if (!value) return ''
  if (mode === 'datetime') {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value)
    if (m) return `${m[1]}${m[2]}${m[3]}${m[4]}${m[5]}`
  }
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  if (m) return `${m[1]}${m[2]}${m[3]}`
  return value.replace(/[-T:]/g, '').slice(0, mode === 'datetime' ? 12 : 8)
}

const isoValue = computed(() => {
  return props.mode === 'datetime' ? toIsoDateTime(props.modelValue) : toIsoDate(props.modelValue)
})

const inputType = computed(() => (props.mode === 'datetime' ? 'datetime-local' : 'date'))

function onInput(event: Event) {
  const raw = (event.target as HTMLInputElement).value
  emit('update:modelValue', fromIso(raw, props.mode ?? 'date'))
}
</script>

<template>
  <div class="date-input-wrapper" :class="{ error }">
    <input
      :type="inputType"
      class="date-input"
      :value="isoValue"
      :readonly="readonly"
      @input="onInput"
    />
    <span v-if="modelValue" class="date-raw-hint">{{ modelValue }}</span>
  </div>
</template>

<style scoped>
.date-input-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.32rem;
}

.date-input {
  width: 100%;
  padding: 0.28rem 0.42rem;
  border: 1px solid var(--border-default);
  border-radius: 0.32rem;
  background: var(--surface-raised);
  color: var(--text-strong);
  font: inherit;
  font-size: var(--font-size-caption);
  color-scheme: dark;
}

.date-input:focus {
  outline: none;
  border-color: var(--border-strong);
}

.date-input-wrapper.error .date-input {
  border-color: rgba(255, 120, 120, 0.55);
}

.date-raw-hint {
  flex-shrink: 0;
  font-size: var(--font-size-caption);
  color: var(--text-disabled);
  font-family: 'Consolas', 'Monaco', monospace;
  white-space: nowrap;
}
</style>
