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
  if (active > 0) return '运行中'
  if (s.failed > 0) return '失败'
  if (s.succeeded > 0) return '完成'
  if (s.cancelled > 0) return '已取消'
  return '工作流'
})

const showRunningBadge = computed(() => props.summary.running > 0)
const showQueuedBadge = computed(() => props.summary.queued > 0)
const showRetryBadge = computed(() => props.summary.retryPending > 0)
const showFailedBadge = computed(() => props.summary.failed > 0)
/** 已完成数量（含天气视口瓦片填满的图层）始终展示，便于与运行中并存对照 */
const showDoneBadge = computed(() => props.summary.succeeded > 0)
const showCancelledBadge = computed(
  () =>
    props.summary.cancelled > 0 &&
    props.summary.running === 0 &&
    props.summary.queued === 0 &&
    props.summary.retryPending === 0 &&
    props.summary.failed === 0 &&
    props.summary.succeeded === 0,
)
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
    <span v-if="showRunningBadge" class="wf-badge badge-running" title="运行中">{{
      summary.running
    }}</span>
    <span v-if="showQueuedBadge" class="wf-badge badge-queued" title="排队中">{{
      summary.queued
    }}</span>
    <span v-if="showRetryBadge" class="wf-badge badge-retry" title="等待重试">{{
      summary.retryPending
    }}</span>
    <span v-if="showFailedBadge" class="wf-badge badge-failed" title="失败">{{
      summary.failed
    }}</span>
    <span v-if="showDoneBadge" class="wf-badge badge-done" title="已完成">{{
      summary.succeeded
    }}</span>
    <span v-if="showCancelledBadge" class="wf-badge badge-cancelled" title="已取消">{{
      summary.cancelled
    }}</span>
  </button>
</template>

<style scoped>
.wf-status-btn {
  position: relative;
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
  transition:
    border-color 0.22s ease,
    color 0.22s ease,
    background 0.22s ease,
    box-shadow 0.22s ease;
  white-space: nowrap;
  overflow: hidden;
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
  transition:
    background 0.2s ease,
    box-shadow 0.2s ease;
}

.wf-label {
  font-size: 0.6rem;
  letter-spacing: 0.01em;
}

/* ── Mini count badges ──────────────────────────────────────────────────── */
.wf-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0.9rem;
  height: 0.9rem;
  padding: 0 0.22rem;
  border-radius: 999px;
  font-size: 0.5rem;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1;
}

.badge-running {
  background: rgba(90, 213, 255, 0.22);
  color: #5ad5ff;
  border: 1px solid rgba(90, 213, 255, 0.3);
}

.badge-queued {
  background: rgba(136, 223, 255, 0.18);
  color: #88dfff;
  border: 1px solid rgba(136, 223, 255, 0.28);
}

.badge-retry {
  background: rgba(255, 211, 138, 0.18);
  color: #ffd38a;
  border: 1px solid rgba(255, 196, 120, 0.28);
}

.badge-failed {
  background: rgba(255, 138, 138, 0.2);
  color: #ff8a8a;
  border: 1px solid rgba(255, 138, 138, 0.3);
}

.badge-done {
  background: rgba(159, 248, 207, 0.16);
  color: #9ff8cf;
  border: 1px solid rgba(114, 255, 207, 0.24);
}

.badge-cancelled {
  background: rgba(138, 168, 191, 0.16);
  color: #8aa8bf;
  border: 1px solid rgba(138, 168, 191, 0.28);
}

/* ── Tone: idle ─────────────────────────────────────────────────────────── */
.tone-idle {
  color: #6e8ba0;
}
.tone-idle .wf-dot {
  background: #6e8ba0;
}

/* ── Tone: active (running) — pulsing glow + rotating shimmer ───────────── */
.tone-active {
  color: #5ad5ff;
  border-color: rgba(90, 213, 255, 0.28);
  background: rgba(10, 132, 255, 0.1);
  box-shadow: 0 0 12px rgba(90, 213, 255, 0.15);
}

.tone-active .wf-dot {
  background: #5ad5ff;
  box-shadow: 0 0 0 0 rgba(90, 213, 255, 0.6);
  animation: wf-pulse-active 1.6s ease-in-out infinite;
}

.tone-active::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, rgba(90, 213, 255, 0.12), transparent);
  transform: translateX(-100%);
  animation: wf-shimmer 2.8s ease-in-out infinite;
  pointer-events: none;
}

@keyframes wf-pulse-active {
  0% {
    box-shadow: 0 0 0 0 rgba(90, 213, 255, 0.6);
    opacity: 1;
  }
  50% {
    box-shadow: 0 0 0 4px rgba(90, 213, 255, 0.08);
    opacity: 0.65;
  }
  100% {
    box-shadow: 0 0 0 0 rgba(90, 213, 255, 0);
    opacity: 1;
  }
}

@keyframes wf-shimmer {
  0% {
    transform: translateX(-100%);
  }
  60% {
    transform: translateX(100%);
  }
  100% {
    transform: translateX(100%);
  }
}

/* ── Tone: success ──────────────────────────────────────────────────────── */
.tone-success {
  color: #9ff8cf;
  border-color: rgba(114, 255, 207, 0.2);
  background: rgba(114, 255, 207, 0.06);
}

.tone-success .wf-dot {
  background: #9ff8cf;
  box-shadow: 0 0 8px rgba(159, 248, 207, 0.3);
}

/* ── Tone: warning ──────────────────────────────────────────────────────── */
.tone-warning {
  color: #ffd38a;
  border-color: rgba(255, 196, 120, 0.2);
  background: rgba(255, 196, 120, 0.06);
}

.tone-warning .wf-dot {
  background: #ffd38a;
  box-shadow: 0 0 8px rgba(255, 211, 138, 0.25);
}

/* ── Tone: error — fast pulse + red glow ────────────────────────────────── */
.tone-error {
  color: #ff8a8a;
  border-color: rgba(255, 138, 138, 0.28);
  background: rgba(255, 138, 138, 0.08);
  box-shadow: 0 0 12px rgba(255, 138, 138, 0.12);
}

.tone-error .wf-dot {
  background: #ff8a8a;
  box-shadow: 0 0 0 0 rgba(255, 138, 138, 0.6);
  animation: wf-pulse-error 1.2s ease-in-out infinite;
}

@keyframes wf-pulse-error {
  0% {
    box-shadow: 0 0 0 0 rgba(255, 138, 138, 0.6);
    opacity: 1;
  }
  50% {
    box-shadow: 0 0 0 4px rgba(255, 138, 138, 0.06);
    opacity: 0.6;
  }
  100% {
    box-shadow: 0 0 0 0 rgba(255, 138, 138, 0);
    opacity: 1;
  }
}
</style>
