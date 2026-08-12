<script setup lang="ts">
/**
 * AppButton — 统一按钮（设计系统 §3.1）
 *
 * 变体：primary（品牌实底）/ secondary（表面+边框，默认）/ ghost（透明文字）
 * 尺寸：xs / sm / md（默认）/ lg —— 统一 4 档，基于 4px 网格
 *   xs=24px  sm=28px  md=36px  lg=44px
 * 规格：圆角 --radius-md，hover 微抬升 + elevation-1，focus-visible 强调环
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'xs' | 'sm' | 'md' | 'lg'
    /** 禁用态（pointer-events none + 禁用文字色） */
    disabled?: boolean
    /** 块级占满父宽 */
    block?: boolean
    type?: 'button' | 'submit' | 'reset'
    /** 图标前缀（置于文字前） */
    icon?: string
    /** 是否显示 loading 态（替换图标） */
    loading?: boolean
    ariaLabel?: string
  }>(),
  {
    variant: 'secondary',
    size: 'md',
    disabled: false,
    block: false,
    type: 'button',
    icon: '',
    loading: false,
    ariaLabel: '',
  },
)

const cls = computed(() => [
  `app-btn`,
  `app-btn--${props.variant}`,
  `app-btn--${props.size}`,
  {
    'app-btn--block': props.block,
    'app-btn--loading': props.loading,
    'app-btn--disabled': props.disabled,
  },
])

const label = computed(() => props.ariaLabel || undefined)
</script>

<template>
  <button
    :class="cls"
    :type="type"
    :disabled="disabled || loading"
    :aria-label="label"
    :aria-busy="loading || undefined"
    data-ui="app-btn"
  >
    <span v-if="loading" class="app-btn-spinner" aria-hidden="true"></span>
    <span v-else-if="icon" class="app-btn-icon" aria-hidden="true">{{ icon }}</span>
    <span v-if="$slots.default" class="app-btn-label"><slot /></span>
  </button>
</template>

<style scoped>
.app-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  font-family: inherit;
  font-weight: var(--font-weight-medium);
  font-size: var(--font-size-caption);
  line-height: 1;
  white-space: nowrap;
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

.app-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.app-btn:disabled,
.app-btn--disabled {
  color: var(--text-disabled);
  pointer-events: none;
  box-shadow: none;
  opacity: 0.6;
}

/* 尺寸体系（4px 网格） */
.app-btn--xs {
  height: 26px;
  padding: 0 0.5rem;
  font-size: var(--font-size-caption);
}
.app-btn--sm {
  height: 28px;
  padding: 0 0.6rem;
  font-size: var(--font-size-caption);
}
.app-btn--md {
  height: 36px;
  padding: 0 0.85rem;
  font-size: var(--font-size-body);
}
.app-btn--lg {
  height: 44px;
  padding: 0 1.2rem;
  font-size: var(--font-size-body);
}

.app-btn--block {
  width: 100%;
}

/* 变体：primary */
.app-btn--primary {
  background: var(--accent);
  color: #06121f;
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.14) inset,
    0 1px 2px rgba(0, 0, 0, 0.3);
}
.app-btn--primary:hover:not(:disabled) {
  background: var(--accent-strong);
  transform: translateY(-1px);
  box-shadow: var(--elevation-1);
}
.app-btn--primary:active:not(:disabled) {
  transform: translateY(0);
}

/* 变体：secondary */
.app-btn--secondary {
  background: var(--surface-2);
  border-color: var(--border-default);
  color: var(--text-primary);
}
.app-btn--secondary:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--border-strong);
  color: var(--text-strong);
  transform: translateY(-1px);
  box-shadow: var(--elevation-1);
}
.app-btn--secondary:active:not(:disabled) {
  transform: translateY(0);
}

/* 变体：ghost（透明背景 + 无边框，依赖文字/图标表达） */
.app-btn--ghost {
  background: transparent;
  border-color: transparent;
  color: var(--text-secondary);
}
.app-btn--ghost:hover:not(:disabled) {
  background: var(--surface-sunken);
  color: var(--text-strong);
}
.app-btn--ghost:active:not(:disabled) {
  transform: translateY(0);
}

/* 变体：danger */
.app-btn--danger {
  background: var(--danger);
  border-color: var(--danger);
  color: #06121f;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
}
.app-btn--danger:hover:not(:disabled) {
  background: var(--warning);
  border-color: var(--warning);
  transform: translateY(-1px);
  box-shadow: var(--elevation-1);
}
.app-btn--danger:active:not(:disabled) {
  transform: translateY(0);
}

/* 图标 / 标签 */
.app-btn-icon {
  font-size: 1em;
  line-height: 1;
  display: inline-flex;
}
.app-btn-label {
  display: inline-flex;
  align-items: center;
}

/* loading spinner */
.app-btn-spinner {
  width: 0.85rem;
  height: 0.85rem;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: app-btn-spin 0.7s linear infinite;
  opacity: 0.85;
}
@keyframes app-btn-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 尊重 reduced-motion */
@media (prefers-reduced-motion: reduce) {
  .app-btn {
    transition: none;
  }
  .app-btn:hover:not(:disabled) {
    transform: none;
  }
}
</style>
