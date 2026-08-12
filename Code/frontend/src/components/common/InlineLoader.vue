<script setup lang="ts">
/**
 * 组件内局部加载指示（不挡全屏）。
 * 用于面板内容区、列表刷新、画布就绪等待等。
 */
withDefaults(
  defineProps<{
    label?: string
    /** sm=16px | md=22px */
    size?: 'sm' | 'md'
    /** 是否占满父级居中 */
    block?: boolean
  }>(),
  {
    label: '加载中',
    size: 'md',
    block: true,
  },
)
</script>

<template>
  <div
    class="inline-loader"
    :class="[`size-${size}`, { block }]"
    role="status"
    aria-live="polite"
    aria-busy="true"
  >
    <span class="inline-spinner" aria-hidden="true"></span>
    <span v-if="label" class="inline-label">{{ label }}</span>
  </div>
</template>

<style scoped>
.inline-loader {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}

.inline-loader.block {
  display: flex;
  width: 100%;
  min-height: 4rem;
  justify-content: center;
  padding: var(--space-4) var(--space-2);
}

.inline-spinner {
  flex: 0 0 auto;
  border: 2px solid var(--accent-surface);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: inline-spin 0.75s linear infinite;
}

.size-sm .inline-spinner {
  width: 16px;
  height: 16px;
  border-width: 1.5px;
}

.size-md .inline-spinner {
  width: 22px;
  height: 22px;
}

.inline-label {
  letter-spacing: 0.02em;
}

@keyframes inline-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .inline-spinner {
    animation: none;
    border-top-color: var(--accent);
    border-style: dashed;
  }
}
</style>
