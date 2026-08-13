<script setup lang="ts">
/**
 * TextField — 统一输入框（设计系统 §3.1）
 *
 * 规格：统一聚焦环 border-strong + 微光，字号 body（13px）
 * 变体：default / search（左侧放大镜图标）
 * 尺寸：sm / md（默认）
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    type?: 'text' | 'search' | 'password' | 'number'
    variant?: 'default' | 'search'
    size?: 'sm' | 'md'
    disabled?: boolean
    readonly?: boolean
    /** 显示清除按钮 */
    clearable?: boolean
    /** 错误状态 */
    error?: string
    /** 左侧标签 */
    label?: string
    /** 最小宽度（px） */
    minWidth?: number
  }>(),
  {
    placeholder: '',
    type: 'text',
    variant: 'default',
    size: 'md',
    disabled: false,
    readonly: false,
    clearable: false,
    error: '',
    label: '',
    minWidth: 0,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  clear: []
  focus: [event: FocusEvent]
  blur: [event: FocusEvent]
}>()

const cls = computed(() => [
  'text-field',
  `text-field--${props.variant}`,
  `text-field--${props.size}`,
  {
    'text-field--disabled': props.disabled,
    'text-field--error': !!props.error,
    'text-field--has-label': !!props.label,
  },
])

function onInput(e: Event) {
  const target = e.target as HTMLInputElement
  emit('update:modelValue', target.value)
}

function onClear() {
  emit('update:modelValue', '')
  emit('clear')
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
    data-ui="text-field"
  >
    <label v-if="label" class="text-field-label">{{ label }}</label>
    <div class="text-field-input-wrap">
      <span v-if="variant === 'search'" class="text-field-icon" aria-hidden="true">
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
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
      </span>
      <input
        :type="type === 'search' ? 'search' : type"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :readonly="readonly"
        class="text-field-input"
        :class="{ 'text-field-input--has-icon': variant === 'search' }"
        @input="onInput"
        @focus="onFocus"
        @blur="onBlur"
      />
      <button
        v-if="clearable && modelValue && !disabled"
        class="text-field-clear"
        type="button"
        aria-label="清除"
        @click="onClear"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M18 6 6 18" />
          <path d="m6 6 12 12" />
        </svg>
      </button>
    </div>
    <p v-if="error" class="text-field-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.text-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.text-field-label {
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
  user-select: none;
}

.text-field-input-wrap {
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

.text-field--md .text-field-input-wrap {
  height: 36px;
}

.text-field--sm .text-field-input-wrap {
  height: 30px;
}

.text-field-input-wrap:focus-within {
  border-color: var(--border-strong);
  box-shadow: 0 0 0 3px var(--accent-focus-ring);
}

.text-field--error .text-field-input-wrap {
  border-color: var(--danger-border);
}

.text-field--error .text-field-input-wrap:focus-within {
  border-color: var(--danger);
  box-shadow: 0 0 0 3px var(--danger-surface);
}

.text-field-input-wrap:focus-within .text-field-icon {
  color: var(--accent);
}

.text-field-input {
  flex: 1;
  min-width: 0;
  height: 100%;
  padding: 0 var(--space-4);
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--font-size-body);
  font-family: inherit;
  line-height: 1;
}

.text-field-input::placeholder {
  color: var(--text-muted);
}

.text-field-input:disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.text-field-input--has-icon {
  padding-left: 2rem;
}

.text-field-icon {
  position: absolute;
  left: 0.6rem;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  color: var(--text-muted);
  pointer-events: none;
}

.text-field-clear {
  position: absolute;
  right: 0.4rem;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: var(--surface-sunken);
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft);
}

.text-field-clear:hover {
  background: var(--surface-hover);
  color: var(--text-strong);
}

.text-field-clear:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.text-field-error {
  margin: 0;
  font-size: var(--font-size-caption);
  color: var(--danger);
  line-height: 1.3;
}

.text-field--disabled .text-field-input-wrap {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (prefers-reduced-motion: reduce) {
  .text-field-input-wrap,
  .text-field-clear {
    transition: none;
  }
}
</style>
