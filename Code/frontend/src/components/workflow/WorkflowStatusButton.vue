<script setup lang="ts">
import { computed } from 'vue'
import type { WorkflowSummary } from '../../stores/layers/types'
import { WORKFLOW_COPY } from '../../ui-copy'

const props = defineProps<{
  summary: WorkflowSummary
}>()

defineEmits<{
  click: []
}>()

const toneClass = computed(() => `tone-${props.summary.tone}`)

const label = computed(() => {
  const s = props.summary
  if (s.total === 0) return WORKFLOW_COPY.entry
  const active = s.running + s.queued + s.retryPending
  if (active > 0) return '运行中'
  if (s.failed > 0) return '失败'
  if (s.succeeded > 0) return WORKFLOW_COPY.statusDone
  if (s.cancelled > 0) return '已取消'
  return WORKFLOW_COPY.entry
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
    :title="`点击查看${WORKFLOW_COPY.statusOverview}`"
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
    <span v-if="showDoneBadge" class="wf-badge badge-done" :title="WORKFLOW_COPY.statusDone">{{
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
  gap: var(--space-2);
  height: 30px;
  padding: 0 var(--space-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-faint);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-medium);
  transition:
    border-color var(--motion-fast) var(--ease-standard),
    color var(--motion-fast) var(--ease-standard),
    background-color var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
  white-space: nowrap;
  overflow: hidden;
}

.wf-status-btn:hover {
  border-color: var(--border-accent);
  background: var(--accent-surface);
  color: var(--accent);
  box-shadow: var(--elevation-1);
}

.wf-status-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.wf-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
  background: currentColor;
  transition:
    background var(--motion-fast) var(--ease-standard),
    box-shadow var(--motion-fast) var(--ease-standard);
}

.wf-label {
  font-size: var(--font-size-caption);
  letter-spacing: 0.01em;
  line-height: 1;
}

/* ── Mini count badges ──────────────────────────────────────────────────── */
.wf-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-pill);
  font-size: var(--font-size-caption);
  font-weight: var(--font-weight-bold);
  letter-spacing: 0;
  line-height: 1;
}

.badge-running {
  background: var(--accent-surface);
  color: var(--accent);
  border: 1px solid var(--border-accent);
}

.badge-queued {
  background: rgba(136, 223, 255, 0.12);
  color: var(--accent-strong);
  border: 1px solid rgba(136, 223, 255, 0.25);
}

.badge-retry {
  background: var(--warning-surface);
  color: var(--warning);
  border: 1px solid var(--warning-border);
}

.badge-failed {
  background: var(--danger-surface);
  color: var(--danger);
  border: 1px solid var(--danger-border);
}

.badge-done {
  background: var(--success-surface);
  color: var(--success);
  border: 1px solid var(--success-border);
}

.badge-cancelled {
  background: var(--surface-2);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
}

/* ── Tone: idle ─────────────────────────────────────────────────────────── */
.tone-idle {
  color: var(--text-faint);
}
.tone-idle .wf-dot {
  background: var(--text-faint);
}

/* ── Tone: active (running) — pulsing glow + rotating shimmer ───────────── */
.tone-active {
  color: var(--accent);
  border-color: var(--border-accent);
  background: var(--accent-surface);
  box-shadow: 0 0 12px rgba(90, 213, 255, 0.15);
}

.tone-active .wf-dot {
  background: var(--accent);
  box-shadow: 0 0 0 0 var(--border-strong);
  animation: wf-pulse-active 1.6s ease-in-out infinite;
}

.tone-active::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, var(--accent-surface), transparent);
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
    box-shadow: 0 0 0 4px var(--accent-surface);
    opacity: 0.65;
  }
  100% {
    box-shadow: 0 0 0 0 var(--accent-surface);
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
  color: var(--success);
  border-color: var(--success-border);
  background: var(--success-surface);
}

.tone-success .wf-dot {
  background: var(--success);
  box-shadow: 0 0 8px var(--success-border);
}

/* ── Tone: warning ──────────────────────────────────────────────────────── */
.tone-warning {
  color: var(--warning);
  border-color: var(--warning-border);
  background: var(--warning-surface);
}

.tone-warning .wf-dot {
  background: var(--warning);
  box-shadow: 0 0 8px rgba(255, 176, 112, 0.25);
}

/* ── Tone: error — fast pulse + red glow ────────────────────────────────── */
.tone-error {
  color: var(--danger);
  border-color: var(--danger-border);
  background: var(--danger-surface);
  box-shadow: 0 0 12px var(--danger-surface);
}

.tone-error .wf-dot {
  background: var(--danger);
  box-shadow: 0 0 0 0 var(--danger-border);
  animation: wf-pulse-error 1.2s ease-in-out infinite;
}

@keyframes wf-pulse-error {
  0% {
    box-shadow: 0 0 0 0 var(--danger-border);
    opacity: 1;
  }
  50% {
    box-shadow: 0 0 0 4px var(--danger-surface);
    opacity: 0.6;
  }
  100% {
    box-shadow: 0 0 0 0 var(--danger-surface);
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .wf-status-btn,
  .wf-dot {
    transition: none;
  }
  .tone-active .wf-dot,
  .tone-error .wf-dot,
  .tone-active::after {
    animation: none;
  }
}
</style>
