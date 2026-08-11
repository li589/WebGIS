<script setup lang="ts">
/**
 * IconButton — 统一图标按钮（设计系统 §3.1）
 *
 * 尺寸：xs / sm / md（默认）—— 与 AppButton 对齐
 *   xs=24px  sm=28px  md=36px
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    size?: 'xs' | 'sm' | 'md'
    disabled?: boolean
    active?: boolean
    /** 图标 SVG 路径（单个 <path> 的 d 属性，或完整 SVG 片段） */
    icon?: string
    /** 替代 aria-label 标题 */
    label?: string
    type?: 'button' | 'submit' | 'reset'
  }>(),
  {
    size: 'md',
    disabled: false,
    active: false,
    icon: '',
    label: '',
    type: 'button',
  },
)

const cls = computed(() => [
  'icon-btn',
  `icon-btn--${props.size}`,
  {
    'icon-btn--active': props.active,
    'icon-btn--disabled': props.disabled,
  },
])

const iconSize = computed(() => {
  switch (props.size) {
    case 'xs':
      return 14
    case 'sm':
      return 16
    default:
      return 18
  }
})
const viewBox = computed(() => `0 0 24 24`)
</script>

<template>
  <button
    :class="cls"
    :type="type"
    :disabled="disabled"
    :aria-label="label || undefined"
    data-ui="icon-btn"
  >
    <svg
      v-if="icon"
      :width="iconSize"
      :height="iconSize"
      :viewBox="viewBox"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path :d="icon" />
    </svg>
    <slot v-else name="icon" />
    <slot />
  </button>
</template>

<style scoped>
.icon-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  flex: 0 0 auto;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard),
    transform var(--motion-fast) var(--ease-standard);
}

.icon-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.icon-btn:disabled,
.icon-btn--disabled {
  color: var(--text-disabled);
  pointer-events: none;
  opacity: 0.5;
}

/* 尺寸体系（与 AppButton 对齐） */
.icon-btn--xs {
  width: 24px;
  height: 24px;
  min-width: 24px;
}
.icon-btn--sm {
  width: 28px;
  height: 28px;
  min-width: 28px;
}
.icon-btn--md {
  width: 36px;
  height: 36px;
  min-width: 36px;
}

/* hover / active */
.icon-btn:hover:not(:disabled) {
  background: var(--surface-sunken);
  border-color: var(--border-default);
  color: var(--text-strong);
  transform: translateY(-1px);
  box-shadow: var(--elevation-1);
}

.icon-btn--active {
  background: var(--accent-surface);
  border-color: var(--border-accent);
  color: var(--accent);
}

.icon-btn--active:hover:not(:disabled) {
  background: var(--accent-surface);
  border-color: var(--border-strong);
  color: var(--accent-strong);
}

@media (prefers-reduced-motion: reduce) {
  .icon-btn {
    transition: none;
  }
  .icon-btn:hover:not(:disabled) {
    transform: none;
  }
}
</style>
