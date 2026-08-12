<script setup lang="ts">
/**
 * Chip — 芯片/标签（设计系统 §3.1）
 *
 * 替换当前散落的 status-chip。
 * 支持语义色（success/warning/danger/info）+ 可选移除按钮。
 * 规格：圆角 pill，字号 caption（12px），padding 0.4rem 0.8rem。
 */
import { computed } from 'vue'
import { X } from './icons'

const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'muted'
    /** 是否可移除 */
    removable?: boolean
    /** 禁用态 */
    disabled?: boolean
  }>(),
  {
    variant: 'default',
    removable: false,
    disabled: false,
  },
)

const emit = defineEmits<{
  remove: []
}>()

const cls = computed(() => [
  'chip',
  `chip--${props.variant}`,
  {
    'chip--removable': props.removable,
    'chip--disabled': props.disabled,
  },
])

function handleRemove(e: MouseEvent) {
  e.stopPropagation()
  emit('remove')
}
</script>

<template>
  <span :class="cls" data-ui="chip">
    <slot />
    <button
      v-if="removable && !disabled"
      class="chip-remove"
      type="button"
      aria-label="移除"
      @click="handleRemove"
    >
      <X :size="12" aria-hidden="true" />
    </button>
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.4rem 0.8rem;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  line-height: 1;
  white-space: nowrap;
  user-select: none;
  transition:
    background-color var(--motion-fast),
    border-color var(--motion-fast),
    color var(--motion-fast);
}

/* 变体：default */
.chip--default {
  background: var(--surface-2);
  border-color: var(--border-default);
  color: var(--text-primary);
}

/* 变体：success */
.chip--success {
  background: var(--success-surface);
  border-color: var(--success-border);
  color: var(--success);
}

/* 变体：warning */
.chip--warning {
  background: var(--warning-surface);
  border-color: var(--warning-border);
  color: var(--warning);
}

/* 变体：danger */
.chip--danger {
  background: var(--danger-surface);
  border-color: var(--danger-border);
  color: var(--danger);
}

/* 变体：info */
.chip--info {
  background: var(--info-surface);
  border-color: var(--info-border);
  color: var(--info);
}

/* 变体：muted */
.chip--muted {
  background: var(--surface-sunken);
  border-color: var(--border-subtle);
  color: var(--text-faint);
}

.chip--disabled {
  color: var(--text-disabled);
  opacity: 0.6;
}

/* 移除按钮 */
.chip-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  margin: -0.2rem -0.2rem -0.2rem 0.2rem;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: var(--surface-sunken);
  color: inherit;
  font-size: var(--font-size-caption);
  cursor: pointer;
  transition: background-color var(--motion-fast);
  opacity: 0.7;
}

.chip-remove:hover {
  background: var(--surface-sunken);
  opacity: 1;
}

.chip-remove:focus-visible {
  outline: 1px solid currentColor;
  outline-offset: 1px;
}

@media (prefers-reduced-motion: reduce) {
  .chip {
    transition: none;
  }
}
</style>
