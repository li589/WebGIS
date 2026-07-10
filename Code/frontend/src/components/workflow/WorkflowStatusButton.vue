<script setup lang="ts">
import { computed } from 'vue'
import type { WorkflowSummary } from '../../stores/layers/types'

const props = defineProps<{
  summary: WorkflowSummary
}>()

defineEmits<{
  click: []
}>()

const toneClass = computed(() => `tone-${props.summary.tone}`)

const label = computed(() => {
  const s = props.summary
  if (s.total === 0) return '工作流'
  const active = s.running + s.queued + s.retryPending
  if (active > 0) return `工作流 ${active} 运行中`
  if (s.failed > 0 && s.succeeded > 0) return `工作流 ${s.failed} 失败`
  if (s.failed > 0) return `工作流 ${s.failed} 失败`
  if (s.succeeded > 0) return `工作流 ${s.succeeded} 完成`
  return `工作流 ${s.total}`
})
</script>

<template>
  <button
    class="wf-status-btn"
    :class="toneClass"
    title="点击查看全局工作流状态"
    @click="$emit('click')"
  >
    <span class="wf-dot" aria-hidden="true"></span>
    <span class="wf-label">{{ label }}</span>
  </button>
</template>

<style scoped>
.wf-status-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 999px;
  padding: 0.26rem 0.52rem;
  background: rgba(4, 12, 23, 0.6);
  color: #6e8ba0;
  cursor: pointer;
  font: inherit;
  font-size: 0.62rem;
  font-weight: 500;
  transition: border-color 0.18s ease, color 0.18s ease, background 0.18s ease;
  white-space: nowrap;
}

.wf-status-btn:hover {
  border-color: rgba(90, 213, 255, 0.3);
  background: rgba(10, 132, 255, 0.12);
}

.wf-dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  flex: none;
  background: currentColor;
  transition: background 0.2s ease;
}

/* tone 配色 */
.tone-idle { color: #6e8ba0; }
.tone-idle .wf-dot { background: #6e8ba0; }

.tone-active { color: #5ad5ff; }
.tone-active .wf-dot {
  background: #5ad5ff;
  box-shadow: 0 0 0 0 rgba(90, 213, 255, 0.5);
  animation: wf-pulse 1.6s ease-in-out infinite;
}

.tone-success { color: #9ff8cf; }
.tone-success .wf-dot { background: #9ff8cf; }

.tone-warning { color: #ffd38a; }
.tone-warning .wf-dot { background: #ffd38a; }

.tone-error { color: #ff8a8a; }
.tone-error .wf-dot {
  background: #ff8a8a;
  animation: wf-pulse 1.2s ease-in-out infinite;
}

@keyframes wf-pulse {
  0% { box-shadow: 0 0 0 0 currentColor; opacity: 1; }
  50% { box-shadow: 0 0 0 3px transparent; opacity: 0.6; }
  100% { box-shadow: 0 0 0 0 transparent; opacity: 1; }
}

.wf-label {
  font-size: 0.6rem;
  letter-spacing: 0.01em;
}
</style>
