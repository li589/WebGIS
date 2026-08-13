<script setup lang="ts">
/**
 * Card — 卡片容器（设计系统 §3.1）
 *
 * 统一浮层卡片：--surface-2 + --border-default + --radius-lg + --elevation-1
 * 右侧分析面板、信息窗、设置分组等都用这个。
 *
 * 用法：
 *   <Card title="图层属性">
 *     ...内容...
 *   </Card>
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 卡片标题（可选） */
    title?: string
    /** 是否显示边框（默认 true） */
    bordered?: boolean
    /** 是否填充（占满父宽） */
    block?: boolean
    /** 无 padding 内容区（用于表格/列表满宽） */
    flush?: boolean
  }>(),
  {
    title: '',
    bordered: true,
    block: false,
    flush: false,
  },
)

const cls = computed(() => [
  'app-card',
  {
    'app-card--bordered': props.bordered,
    'app-card--block': props.block,
    'app-card--flush': props.flush,
  },
])
</script>

<template>
  <section :class="cls" data-ui="card">
    <header v-if="title" class="app-card__head">
      <h3 class="app-card__title">{{ title }}</h3>
      <div v-if="$slots.actions" class="app-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="app-card__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.app-card {
  display: flex;
  flex-direction: column;
  background: var(--surface-2);
  border-radius: var(--radius-lg);
  overflow: hidden;
  min-width: 0;
  position: relative;
  transition:
    box-shadow var(--motion-base) var(--ease-standard),
    transform var(--motion-base) var(--ease-standard);
}

.app-card--bordered {
  border: 1px solid var(--border-default);
  box-shadow: var(--elevation-1);
}

.app-card--bordered::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(
    135deg,
    var(--border-default) 0%,
    var(--border-subtle) 50%,
    var(--border-default) 100%
  );
  -webkit-mask:
    linear-gradient(var(--text-strong) 0 0) content-box,
    linear-gradient(var(--text-strong) 0 0);
  mask:
    linear-gradient(var(--text-strong) 0 0) content-box,
    linear-gradient(var(--text-strong) 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  pointer-events: none;
  z-index: 0;
}

.app-card--bordered:hover {
  box-shadow: var(--elevation-2);
}

.app-card--block {
  width: 100%;
}

.app-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
  flex: 0 0 auto;
  position: relative;
}

.app-card__head::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: var(--space-4);
  right: var(--space-4);
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border-default), transparent);
}

.app-card__title {
  margin: 0;
  font-size: var(--font-size-title);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  letter-spacing: 0.01em;
}

.app-card__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
}

.app-card__body {
  padding: var(--space-4);
  min-width: 0;
}

.app-card--flush .app-card__body {
  padding: 0;
}

@media (prefers-reduced-motion: reduce) {
  .app-card {
    transition: none;
  }
}
</style>
