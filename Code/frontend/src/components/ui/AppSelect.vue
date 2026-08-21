<script setup lang="ts">
/**
 * AppSelect — 统一下拉选择器（设计系统 §3.1）
 *
 * 规格：与 TextField 对齐的聚焦环 + 边框体系，右侧 chevron 图标
 * 尺寸：sm / md（默认）—— 与 TextField 一致
 * 支持两种 options 传入方式：
 *   1. :options="[{ label, value, disabled? }]" — 推荐方式
 *   2. <slot> — 用于需要复杂 option 内容时（如条件渲染）
 */
import { computed, useSlots } from 'vue'

interface SelectOption {
  label: string | number
  value: string | number
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    /** v-model 绑定值 */
    modelValue: string | number
    /** 选项数组（与 slot 二选一） */
    options?: SelectOption[]
    /** 占位符（无选中值时显示） */
    placeholder?: string
    /** 尺寸 */
    size?: 'sm' | 'md'
    /** 禁用整个选择器 */
    disabled?: boolean
    /** 左侧标签 */
    label?: string
    /** 错误状态 */
    error?: string
    /** tooltip */
    title?: string
    /** 最小宽度（px） */
    minWidth?: number
    /** 是否占满父宽 */
    block?: boolean
  }>(),
  {
    options: () => [],
    placeholder: '',
    size: 'md',
    disabled: false,
    label: '',
    error: '',
    title: '',
    minWidth: 0,
    block: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  change: [value: string]
  focus: [event: FocusEvent]
  blur: [event: FocusEvent]
}>()

const slots = useSlots()
const hasSlot = computed(() => !!slots.default)

const cls = computed(() => [
  'app-select',
  `app-select--${props.size}`,
  {
    'app-select--disabled': props.disabled,
    'app-select--error': !!props.error,
    'app-select--has-label': !!props.label,
    'app-select--block': props.block,
  },
])

const selectCls = computed(() => ['app-select-native', `app-select-native--${props.size}`])

function onChange(e: Event) {
  const target = e.target as HTMLSelectElement
  const raw = target.value
  const matched = props.options.find((opt) => String(opt.value) === raw)
  const next = matched ? String(matched.value) : raw
  emit('update:modelValue', next)
  emit('change', next)
}

function onFocus(e: FocusEvent) {
  emit('focus', e)
}

function onBlur(e: FocusEvent) {
  emit('blur', e)
}
</script>

<template>
  <div
    :class="cls"
    :style="minWidth ? { minWidth: `${minWidth}px` } : undefined"
    :title="title || undefined"
    data-ui="app-select"
  >
    <label v-if="label" class="app-select-label">{{ label }}</label>
    <div class="app-select-wrap">
      <select
        :class="selectCls"
        :value="modelValue"
        :disabled="disabled"
        :aria-invalid="!!error || undefined"
        :aria-label="label || undefined"
        @change="onChange"
        @focus="onFocus"
        @blur="onBlur"
      >
        <option v-if="placeholder && !modelValue" value="" disabled>{{ placeholder }}</option>
        <template v-if="hasSlot">
          <slot />
        </template>
        <template v-else>
          <option
            v-for="opt in options"
            :key="opt.value"
            :value="opt.value"
            :disabled="opt.disabled"
          >
            {{ opt.label }}
          </option>
        </template>
      </select>
      <span class="app-select-chevron" aria-hidden="true">
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </span>
    </div>
    <p v-if="error" class="app-select-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.app-select {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.app-select--block {
  width: 100%;
}

.app-select-label {
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
  user-select: none;
}

.app-select-wrap {
  position: relative;
  display: flex;
  align-items: center;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  transition:
    border-color var(--motion-fast) var(--ease-soft),
    box-shadow var(--motion-fast) var(--ease-soft);
}

.app-select-wrap:focus-within {
  border-color: var(--border-strong);
  box-shadow: 0 0 0 3px rgba(90, 213, 255, 0.1);
}

.app-select--error .app-select-wrap {
  border-color: var(--danger-border);
}

.app-select--error .app-select-wrap:focus-within {
  border-color: var(--danger);
  box-shadow: 0 0 0 3px rgba(255, 140, 100, 0.1);
}

.app-select--md .app-select-wrap {
  height: 36px;
}

.app-select--sm .app-select-wrap {
  height: 30px;
}

.app-select-native {
  flex: 1;
  min-width: 0;
  height: 100%;
  padding: 0 2rem 0 var(--space-4);
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--font-size-body);
  font-family: inherit;
  line-height: 1;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  -moz-appearance: none;
}

.app-select-native--sm {
  font-size: var(--font-size-caption);
}

.app-select-native:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

/* 下拉弹出面板（原生 option 列表）配色：Chromium 系尊重 option 的
 * background/color——深浅两种主题下均保证面板背景与文字对比度
 * （报障 2026-08-22：选源下拉文字不清晰，白底浅字）。 */
.app-select-native option {
  background: var(--bg-elevated, #fff);
  color: var(--text-primary, #1f2328);
  font-family: inherit;
}

.app-select-native::placeholder {
  color: var(--text-muted);
}

/* Remove default select arrow in IE */
.app-select-native::-ms-expand {
  display: none;
}

.app-select-chevron {
  position: absolute;
  right: 0.5rem;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  color: var(--text-muted);
  pointer-events: none;
  transition: color var(--motion-fast) var(--ease-soft);
}

.app-select-wrap:focus-within .app-select-chevron {
  color: var(--text-secondary);
}

.app-select--disabled .app-select-chevron {
  opacity: 0.5;
}

.app-select-error {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--danger);
  line-height: 1.3;
}

.app-select--disabled .app-select-wrap {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (prefers-reduced-motion: reduce) {
  .app-select-wrap,
  .app-select-chevron {
    transition: none;
  }
}
</style>
