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
  gap: 0.45rem;
  color: #8aa8bf;
  font-size: 0.62rem;
}

.inline-loader.block {
  display: flex;
  width: 100%;
  min-height: 4rem;
  justify-content: center;
  padding: 1rem 0.5rem;
}

.inline-spinner {
  flex: 0 0 auto;
  border: 2px solid rgba(90, 213, 255, 0.18);
  border-top-color: #5ad5ff;
  border-radius: 50%;
  animation: inline-spin 0.75s linear infinite;
}

.size-sm .inline-spinner {
  width: 0.85rem;
  height: 0.85rem;
  border-width: 1.5px;
}

.size-md .inline-spinner {
  width: 1.15rem;
  height: 1.15rem;
}

.inline-label {
  letter-spacing: 0.02em;
}

@keyframes inline-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
