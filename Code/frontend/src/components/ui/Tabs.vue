<script setup lang="ts">
/**
 * Tabs — 选项卡 / SegmentedControl（设计系统 §3.1）
 *
 * 两种模式：
 *   - tabs（默认）：标签页切换
 *   - segmented：胶囊分段控件（用于时间粒度、底图风格等）
 *
 * 规格：容器 surface-sunken + pill；active 用 accent 描边 + 微亮
 * 字号：caption（12px），字重 medium
 */
import { computed } from 'vue'

export interface TabItem {
  value: string
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    items: TabItem[]
    modelValue: string
    variant?: 'tabs' | 'segmented'
    compact?: boolean
  }>(),
  {
    variant: 'tabs',
    compact: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const cls = computed(() => ['tabs', `tabs--${props.variant}`, { 'tabs--compact': props.compact }])

function select(value: string) {
  if (value === props.modelValue) return
  emit('update:modelValue', value)
}
</script>

<template>
  <div :class="cls" role="tablist" data-ui="tabs">
    <button
      v-for="item in items"
      :key="item.value"
      class="tabs-item"
      :class="{
        'tabs-item--active': item.value === modelValue,
        'tabs-item--disabled': item.disabled,
      }"
      :disabled="item.disabled"
      :aria-selected="item.value === modelValue"
      role="tab"
      type="button"
      @click="select(item.value)"
    >
      {{ item.label }}
    </button>
  </div>
</template>

<style scoped>
.tabs {
  display: inline-flex;
  position: relative;
  align-items: stretch;
  gap: 0;
  user-select: none;
}

/* 变体：tabs（下划线指示） */
.tabs--tabs {
  border-bottom: 1px solid var(--border-subtle);
}

.tabs--tabs .tabs-item {
  padding: var(--space-3) var(--space-4);
  border: none;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition:
    color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard);
}

.tabs--tabs .tabs-item--active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tabs--tabs .tabs-item:hover:not(:disabled) {
  color: var(--text-strong);
}

/* 变体：segmented（胶囊） */
.tabs--segmented {
  background: var(--surface-sunken);
  border-radius: var(--radius-pill);
  padding: 2px;
  gap: 2px;
}

.tabs--segmented .tabs-item {
  padding: var(--space-2) var(--space-4);
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  white-space: nowrap;
  transition:
    background-color var(--motion-fast) var(--ease-standard),
    border-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
}

.tabs--segmented .tabs-item--active {
  background: var(--surface-2);
  border-color: var(--border-accent);
  color: var(--accent);
  box-shadow: var(--elevation-1);
}

.tabs--segmented .tabs-item:hover:not(:disabled) {
  color: var(--text-strong);
}

/* 通用 */
.tabs-item:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

.tabs-item--disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
  opacity: 0.5;
}

/* compact 模式：缩小内边距，字号保持 floor（12px） */
.tabs--compact.tabs--tabs .tabs-item {
  padding: var(--space-2) var(--space-3);
}

.tabs--compact.tabs--segmented .tabs-item {
  padding: var(--space-1) var(--space-3);
}

@media (prefers-reduced-motion: reduce) {
  .tabs-item {
    transition: none;
  }
}
</style>
