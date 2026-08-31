<script setup lang="ts">
/**
 * AppButton — 统一按钮（设计系统 §3.1）
 *
 * 变体：primary（品牌实底）/ secondary（表面+边框，默认）/ ghost（透明文字）/ danger
 * 尺寸：xs / sm / md（默认）/ lg —— 统一 4 档，基于 4px 网格
 *   xs=26px  sm=28px  md=36px  lg=44px
 * 规格：圆角 --radius-md，hover 微抬升 + elevation-1，focus-visible 强调环
 *
 * 图标传入方式（二选一）：
 *   1. #icon slot —— 传入 lucide-vue-next 组件（推荐）
 *      <AppButton variant="primary"><template #icon><Play :size="14" /></template>运行</AppButton>
 *   2. icon prop —— 纯文本字符（向后兼容，如 emoji 或单字符）
 */
import { computed, useSlots } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'xs' | 'sm' | 'md' | 'lg'
    /** 禁用态（pointer-events none + 禁用文字色） */
    disabled?: boolean
    /** 块级占满父宽 */
    block?: boolean
    type?: 'button' | 'submit' | 'reset'
    /** 图标前缀（纯文本字符，向后兼容；推荐使用 #icon slot 传入 SVG 组件） */
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

const slots = useSlots()
const cls = computed(() => [
  `app-btn`,
  `app-btn--${props.variant}`,
  `app-btn--${props.size}`,
  {
    'app-btn--block': props.block,
    'app-btn--loading': props.loading,
    'app-btn--disabled': props.disabled,
    'app-btn--icon-only': !slots.default && (slots.icon || props.icon),
  },
])

const label = computed(() => props.ariaLabel || undefined)

/** Icon size in px, mapped from button size */
const iconSize = computed(() => {
  const map = { xs: 13, sm: 14, md: 16, lg: 18 } as const
  return map[props.size]
})
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
    <span v-else-if="$slots.icon" class="app-btn-icon" aria-hidden="true">
      <slot name="icon" :size="iconSize" />
    </span>
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
  position: relative;
  overflow: hidden;
  transition:
    background-color var(--motion-fast) var(--ease-soft),
    border-color var(--motion-fast) var(--ease-soft),
    color var(--motion-fast) var(--ease-soft),
    box-shadow var(--motion-fast) var(--ease-soft),
    transform var(--motion-press, var(--motion-fast)) var(--ease-soft);
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

/* 图标-only 按钮（无文字）：正方形 */
.app-btn--icon-only {
  padding: 0;
  aspect-ratio: 1;
  width: auto;
}

.app-btn--block {
  width: 100%;
}

/* 变体：primary */
.app-btn--primary {
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent-strong) 100%);
  color: var(--surface-base);
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.18) inset,
    0 1px 2px var(--surface-sunken),
    0 0 0 1px var(--accent-border);
}
.app-btn--primary::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(
    100deg,
    transparent 30%,
    rgba(255, 255, 255, 0.12) 50%,
    transparent 70%
  );
  background-size: 200% 100%;
  background-position: 200% 0;
  transition: background-position var(--motion-slow) var(--ease-soft);
  pointer-events: none;
}
.app-btn--primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.22) inset,
    var(--elevation-2),
    var(--accent-glow-sm);
}
.app-btn--primary:hover:not(:disabled)::after {
  background-position: -200% 0;
}
.app-btn--primary:active:not(:disabled) {
  transform: translateY(1px);
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.12) inset,
    0 1px 2px var(--surface-sunken);
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
  transform: translateY(1px);
  box-shadow: none;
  background: var(--surface-sunken);
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
  transform: translateY(1px);
  background: var(--surface-1);
}

/* 变体：danger */
.app-btn--danger {
  background: var(--danger);
  border-color: var(--danger);
  color: var(--surface-base);
  box-shadow: 0 1px 2px var(--surface-sunken);
}
.app-btn--danger:hover:not(:disabled) {
  background: var(--warning);
  border-color: var(--warning);
  transform: translateY(-1px);
  box-shadow: var(--elevation-1);
}
.app-btn--danger:active:not(:disabled) {
  transform: translateY(1px);
  box-shadow: none;
}

/* 图标 / 标签 */
.app-btn-icon {
  font-size: 1em;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
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

/* 设置开关 html.reduce-motion 优先；保留颜色过渡，去掉位移与扫光 */
html.reduce-motion .app-btn:hover:not(:disabled),
html.reduce-motion .app-btn:active:not(:disabled) {
  transform: none;
  box-shadow: none;
}

html.reduce-motion .app-btn--primary:hover:not(:disabled) {
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.18) inset,
    0 1px 2px var(--surface-sunken),
    0 0 0 1px var(--accent-border);
}

html.reduce-motion .app-btn--primary:hover:not(:disabled)::after {
  background-position: 200% 0;
  transition: none;
}

html.reduce-motion .app-btn-spinner {
  animation-duration: 1.2s;
}
</style>
