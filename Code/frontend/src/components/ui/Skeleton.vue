<script setup lang="ts">
/**
 * Skeleton — 加载占位符（设计系统 §3.1）
 *
 * 显示同色块 + 微光 sweep（motion-slow），尊重 reduced-motion。
 * 用于首屏数据加载等待、列表项占位。
 *
 * 用法：
 *   <Skeleton width="100%" height="44px" />
 *   <Skeleton :count="3" />
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 宽度（CSS 值） */
    width?: string
    /** 高度（CSS 值） */
    height?: string
    /** 圆角 */
    radius?: string
    /** 重复数量 */
    count?: number
    /** 间距 */
    gap?: string
    /** 圆形（头像占位） */
    circle?: boolean
  }>(),
  {
    width: '100%',
    height: '16px',
    radius: 'var(--radius-md)',
    count: 1,
    gap: 'var(--space-3)',
    circle: false,
  },
)

const items = computed(() => Array(props.count).fill(null))
const computedRadius = computed(() => (props.circle ? '50%' : props.radius))
</script>

<template>
  <div class="skeleton-container" :style="{ gap: count > 1 ? gap : undefined }">
    <div
      v-for="(_, idx) in items"
      :key="idx"
      class="skeleton"
      :class="{ 'skeleton--circle': circle }"
      :style="{
        width,
        height,
        borderRadius: computedRadius,
      }"
      data-ui="skeleton"
      aria-hidden="true"
    />
  </div>
</template>

<style scoped>
.skeleton-container {
  display: flex;
  flex-direction: column;
}

.skeleton {
  background: var(--surface-1);
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
}

.skeleton::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(100deg, transparent 30%, var(--surface-hover) 50%, transparent 70%);
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.8s ease-in-out infinite;
}

@keyframes skeleton-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton {
    animation: none;
  }
  .skeleton::after {
    animation: none;
  }
  .skeleton {
    opacity: 0.6;
  }
}
</style>
