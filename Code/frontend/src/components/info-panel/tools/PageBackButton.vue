<script setup lang="ts">
/** 工具子页返回按钮 — 明显的按钮化样式（替代原先 12px 次要色文本链接） */
import { ArrowLeft } from '../../ui/icons'

withDefaults(defineProps<{ label?: string }>(), { label: '返回工具列表' })

const emit = defineEmits<{ back: [] }>()
</script>

<template>
  <button type="button" class="page-back-btn" @click="emit('back')">
    <ArrowLeft :size="13" />
    <span>{{ label }}</span>
  </button>
</template>

<style scoped>
.page-back-btn {
  justify-self: start;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  margin-bottom: 0.2rem;
  transition:
    border-color 0.15s ease,
    color 0.15s ease,
    background 0.15s ease;
}

.page-back-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--surface-hover);
}
</style>
