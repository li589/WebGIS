<script setup lang="ts">
/**
 * SegmentedControl — 互斥分段控件（设计系统 §3.3）
 *
 * 用于在一组互斥选项间切换，视觉上表现为紧邻的按钮组。
 * 键盘：方向键导航、Enter/Space 确认、Tab 跳出。
 */
import { type Component } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 当前选中值（v-model） */
    modelValue?: string | number
    /** 选项列表 */
    options: Array<{
      label?: string
      value: string | number
      icon?: Component
      disabled?: boolean
    }>
    /** 尺寸 */
    size?: 'xs' | 'sm' | 'md'
    /** 整体禁用 */
    disabled?: boolean
    /** 互斥高亮使用 danger 色系（用于「关闭」等否定选项） */
    dangerActive?: boolean
  }>(),
  {
    modelValue: '',
    size: 'sm',
    disabled: false,
    dangerActive: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
  change: [value: string | number]
}>()

function select(value: string | number, disabled?: boolean) {
  if (disabled || props.disabled) return
  emit('update:modelValue', value)
  emit('change', value)
}

function onKeydown(e: KeyboardEvent) {
  if (props.disabled) return
  const opts = props.options.filter((o) => !o.disabled)
  if (opts.length === 0) return
  const currentIdx = opts.findIndex((o) => o.value === props.modelValue)
  let nextIdx: number

  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
    e.preventDefault()
    nextIdx = currentIdx < opts.length - 1 ? currentIdx + 1 : 0
  } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
    e.preventDefault()
    nextIdx = currentIdx > 0 ? currentIdx - 1 : opts.length - 1
  } else if (e.key === 'Home') {
    e.preventDefault()
    nextIdx = 0
  } else if (e.key === 'End') {
    e.preventDefault()
    nextIdx = opts.length - 1
  } else {
    return
  }

  const next = opts[nextIdx]
  if (next) select(next.value, next.disabled)
}
</script>

<template>
  <div
    class="seg-ctrl"
    :class="[`seg-ctrl--${size}`, { 'seg-ctrl--disabled': disabled }]"
    role="radiogroup"
    @keydown="onKeydown"
  >
    <button
      v-for="opt in options"
      :key="opt.value"
      type="button"
      class="seg-ctrl-item"
      :class="{
        active: opt.value === modelValue,
        'active--danger': dangerActive && opt.value === modelValue,
        'seg-ctrl-item--disabled': opt.disabled || disabled,
      }"
      :data-mode="opt.value"
      role="radio"
      :aria-checked="opt.value === modelValue"
      :tabindex="opt.value === modelValue ? 0 : -1"
      :disabled="opt.disabled || disabled"
      @click="select(opt.value, opt.disabled)"
    >
      <component
        :is="opt.icon"
        v-if="opt.icon"
        :size="size === 'xs' ? 12 : 14"
        aria-hidden="true"
      />
      <span v-if="opt.label" class="seg-ctrl-label">{{ opt.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.seg-ctrl {
  display: inline-flex;
  align-items: center;
  border-radius: var(--radius-md);
  background: var(--surface-sunken);
  border: 1px solid var(--border-subtle);
  overflow: hidden;
}

.seg-ctrl-item {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.3rem;
  border: none;
  border-radius: 0;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  transition:
    background-color var(--motion-interactive-duration) var(--motion-interactive-ease),
    color var(--motion-interactive-duration) var(--motion-interactive-ease),
    transform var(--motion-press) var(--motion-interactive-ease);
  font-family: inherit;
}

.seg-ctrl-item:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
  z-index: 1;
}

.seg-ctrl-item:hover:not(:disabled):not(.active) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.seg-ctrl-item:active:not(:disabled) {
  transform: translateY(1px);
}

.seg-ctrl-item:disabled,
.seg-ctrl-item--disabled {
  opacity: 0.4;
  cursor: not-allowed;
  pointer-events: none;
}

.seg-ctrl-item.active {
  background: var(--accent-surface);
  color: var(--accent);
  font-weight: var(--font-weight-medium);
  position: relative;
}

.seg-ctrl-item.active::after {
  content: '';
  position: absolute;
  bottom: 2px;
  left: 25%;
  right: 25%;
  height: 2px;
  background: var(--accent);
  border-radius: var(--radius-pill);
  box-shadow: 0 0 6px var(--accent-border);
}

.seg-ctrl-item.active--danger {
  background: var(--danger-surface);
  color: var(--danger);
}

/* 尺寸 */
.seg-ctrl--xs .seg-ctrl-item {
  height: 24px;
  padding: 0 0.5rem;
  font-size: var(--font-size-caption);
}

.seg-ctrl--sm .seg-ctrl-item {
  height: 28px;
  padding: 0 0.6rem;
  font-size: var(--font-size-caption);
}

.seg-ctrl--md .seg-ctrl-item {
  height: 36px;
  padding: 0 0.85rem;
  font-size: var(--font-size-body);
}

.seg-ctrl-label {
  line-height: 1;
}

@media (prefers-reduced-motion: reduce) {
  .seg-ctrl-item {
    transition: none;
  }
}

html.reduce-motion .seg-ctrl-item:active:not(:disabled) {
  transform: none;
}
</style>
