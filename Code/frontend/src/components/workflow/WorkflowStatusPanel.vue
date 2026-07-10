<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount } from 'vue'
import { useLayersStore } from '../../stores/layers'
import type { JobStatus } from '../../stores/layers/types'

const layersStore = useLayersStore()
const emit = defineEmits<{ close: [] }>()

// 从 activeLayersDisplay 中提取有 jobLayer 的条目，保留 catalogId
const workflowItems = computed(() => {
  return layersStore.activeLayersDisplay
    .filter((layer) => layer.jobLayer)
    .map((layer) => ({
      catalogId: layer.catalogId,
      name: layer.name,
      accentColor: layer.accentColor,
      jobLayer: layer.jobLayer!,
    }))
    .sort((a, b) => {
      // 运行中优先，然后按更新时间倒序
      const order: Record<string, number> = { running: 0, queued: 1, retry_pending: 2, failed: 3, cancelled: 4, succeeded: 5 }
      const diff = (order[a.jobLayer.status] ?? 9) - (order[b.jobLayer.status] ?? 9)
      if (diff !== 0) return diff
      return new Date(b.jobLayer.updatedAt).getTime() - new Date(a.jobLayer.updatedAt).getTime()
    })
})

const summary = computed(() => layersStore.workflowSummary)

const statusMeta: Record<JobStatus, { label: string; color: string; bg: string }> = {
  running: { label: '运行中', color: '#5ad5ff', bg: 'rgba(90, 213, 255, 0.12)' },
  queued: { label: '排队中', color: '#88dfff', bg: 'rgba(136, 223, 255, 0.1)' },
  succeeded: { label: '已完成', color: '#9ff8cf', bg: 'rgba(159, 248, 207, 0.1)' },
  failed: { label: '失败', color: '#ff8a8a', bg: 'rgba(255, 138, 138, 0.1)' },
  cancelled: { label: '已取消', color: '#8aa8bf', bg: 'rgba(138, 168, 191, 0.1)' },
  retry_pending: { label: '等待重试', color: '#ffd38a', bg: 'rgba(255, 211, 138, 0.1)' },
}

function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function handleCancel(jobId: string, catalogId: string) {
  void layersStore.cancelWorkflowRunForJob(jobId, catalogId)
}

function handleRetry(jobId: string, catalogId: string) {
  void layersStore.retryWorkflowRunForJob(jobId, catalogId)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="wf-panel-overlay" @click.self="emit('close')">
    <div class="wf-panel">
      <!-- 顶部标题栏 -->
      <header class="wf-panel-header">
        <div>
          <p class="wf-panel-eyebrow">WORKFLOW STATUS</p>
          <h2>工作流状态总览</h2>
        </div>
        <button class="wf-close-btn" title="关闭 (ESC)" @click="emit('close')">×</button>
      </header>

      <!-- 错误提示 -->
      <div v-if="layersStore.workflowError" class="wf-error-banner">
        <span class="wf-error-icon">⚠</span>
        <span>{{ layersStore.workflowError }}</span>
      </div>

      <!-- 汇总卡片 -->
      <section class="wf-summary-grid">
        <div class="wf-summary-card" :class="{ active: summary.running > 0 }">
          <span class="wf-summary-count" style="color: #5ad5ff">{{ summary.running }}</span>
          <span class="wf-summary-label">运行中</span>
        </div>
        <div class="wf-summary-card" :class="{ active: summary.queued > 0 }">
          <span class="wf-summary-count" style="color: #88dfff">{{ summary.queued }}</span>
          <span class="wf-summary-label">排队中</span>
        </div>
        <div class="wf-summary-card" :class="{ active: summary.retryPending > 0 }">
          <span class="wf-summary-count" style="color: #ffd38a">{{ summary.retryPending }}</span>
          <span class="wf-summary-label">等待重试</span>
        </div>
        <div class="wf-summary-card" :class="{ active: summary.succeeded > 0 }">
          <span class="wf-summary-count" style="color: #9ff8cf">{{ summary.succeeded }}</span>
          <span class="wf-summary-label">已完成</span>
        </div>
        <div class="wf-summary-card" :class="{ active: summary.failed > 0 }">
          <span class="wf-summary-count" style="color: #ff8a8a">{{ summary.failed }}</span>
          <span class="wf-summary-label">失败</span>
        </div>
        <div class="wf-summary-card">
          <span class="wf-summary-count" style="color: #8aa8bf">{{ summary.cancelled }}</span>
          <span class="wf-summary-label">已取消</span>
        </div>
      </section>

      <!-- 工作流列表 -->
      <section class="wf-list-section">
        <div v-if="workflowItems.length === 0" class="wf-empty">
          <span class="wf-empty-icon">◇</span>
          <p>当前没有运行中的工作流</p>
          <p class="wf-empty-hint">从左侧面板添加图层并运行工作流后，状态将显示在这里</p>
        </div>

        <div v-else class="wf-list">
          <div
            v-for="item in workflowItems"
            :key="item.jobLayer.jobId"
            class="wf-item"
          >
            <div class="wf-item-header">
              <div class="wf-item-name">
                <span class="wf-item-dot" :style="{ background: item.accentColor }"></span>
                <span class="wf-item-title">{{ item.name }}</span>
              </div>
              <span
                class="wf-item-status"
                :style="{ color: statusMeta[item.jobLayer.status].color, background: statusMeta[item.jobLayer.status].bg }"
              >
                {{ statusMeta[item.jobLayer.status].label }}
                <template v-if="item.jobLayer.status === 'running'">{{ item.jobLayer.progress }}%</template>
              </span>
            </div>

            <!-- 进度条 -->
            <div v-if="item.jobLayer.status === 'running'" class="wf-progress-bar">
              <div class="wf-progress-fill" :style="{ width: `${item.jobLayer.progress}%` }"></div>
            </div>

            <!-- 消息 -->
            <p v-if="item.jobLayer.message" class="wf-item-message">{{ item.jobLayer.message }}</p>

            <!-- 诊断 -->
            <ul v-if="item.jobLayer.diagnosticNotes?.length" class="wf-item-notes">
              <li v-for="note in item.jobLayer.diagnosticNotes.slice(0, 2)" :key="note">{{ note }}</li>
            </ul>

            <!-- 事件消息 -->
            <ul v-if="item.jobLayer.eventMessages?.length" class="wf-item-events">
              <li v-for="evt in item.jobLayer.eventMessages.slice(-2)" :key="evt">{{ evt }}</li>
            </ul>

            <!-- 底部行：时间 + 操作 -->
            <div class="wf-item-footer">
              <span class="wf-item-time">{{ formatTime(item.jobLayer.updatedAt) }}</span>
              <div class="wf-item-actions">
                <button
                  v-if="item.jobLayer.status === 'running' || item.jobLayer.status === 'queued' || item.jobLayer.status === 'retry_pending'"
                  class="wf-action-btn cancel"
                  @click="handleCancel(item.jobLayer.jobId, item.catalogId)"
                >
                  取消
                </button>
                <button
                  v-if="item.jobLayer.status === 'failed' || item.jobLayer.status === 'cancelled'"
                  class="wf-action-btn retry"
                  @click="handleRetry(item.jobLayer.jobId, item.catalogId)"
                >
                  重试
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.wf-panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  background: rgba(2, 8, 18, 0.72);
  backdrop-filter: blur(12px);
}

.wf-panel {
  width: min(680px, 100%);
  max-height: min(80vh, 720px);
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(145, 197, 255, 0.16);
  border-radius: 1.2rem;
  background:
    linear-gradient(180deg, rgba(8, 17, 31, 0.92), rgba(7, 15, 28, 0.88)),
    rgba(8, 18, 33, 0.9);
  box-shadow: 0 24px 60px rgba(1, 8, 16, 0.5);
  overflow: hidden;
}

.wf-panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 1rem 1.2rem 0.8rem;
  border-bottom: 1px solid rgba(145, 197, 255, 0.08);
}

.wf-panel-eyebrow {
  margin: 0 0 0.2rem;
  color: #88dfff;
  font-size: 0.55rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.wf-panel-header h2 {
  margin: 0;
  font-size: 1rem;
  color: #f5fbff;
}

.wf-close-btn {
  border: none;
  background: rgba(136, 192, 255, 0.08);
  color: #8aa8bf;
  font-size: 1.2rem;
  width: 1.8rem;
  height: 1.8rem;
  border-radius: 0.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.16s ease, color 0.16s ease;
  flex: none;
}

.wf-close-btn:hover {
  background: rgba(255, 138, 138, 0.16);
  color: #ff8a8a;
}

.wf-error-banner {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0.6rem 1.2rem 0;
  padding: 0.5rem 0.7rem;
  border: 1px solid rgba(255, 138, 138, 0.2);
  border-radius: 0.6rem;
  background: rgba(255, 138, 138, 0.08);
  color: #ff8a8a;
  font-size: 0.68rem;
}

.wf-error-icon { font-size: 0.8rem; flex: none; }

/* 汇总卡片网格 */
.wf-summary-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0.5rem;
  padding: 0.8rem 1.2rem;
}

.wf-summary-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
  padding: 0.5rem 0.3rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: 0.6rem;
  background: rgba(4, 12, 23, 0.42);
  transition: border-color 0.2s ease;
}

.wf-summary-card.active {
  border-color: rgba(136, 192, 255, 0.22);
}

.wf-summary-count {
  font-size: 1.1rem;
  font-weight: 700;
  line-height: 1;
}

.wf-summary-label {
  color: #7f96ab;
  font-size: 0.55rem;
  letter-spacing: 0.04em;
}

/* 列表区 */
.wf-list-section {
  flex: 1;
  overflow-y: auto;
  padding: 0 1.2rem 1.2rem;
}

.wf-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 3rem 1rem;
  color: #6e8ba0;
  text-align: center;
}

.wf-empty-icon {
  font-size: 2rem;
  opacity: 0.4;
}

.wf-empty p { margin: 0; font-size: 0.72rem; }
.wf-empty-hint { font-size: 0.6rem; color: #5a7080; }

.wf-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.wf-item {
  padding: 0.6rem 0.7rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: 0.7rem;
  background: rgba(4, 12, 23, 0.42);
}

.wf-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.wf-item-name {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.wf-item-dot {
  width: 0.4rem;
  height: 0.4rem;
  border-radius: 50%;
  flex: none;
}

.wf-item-title {
  color: #d8e6f5;
  font-size: 0.7rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-item-status {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.16rem 0.4rem;
  border-radius: 999px;
  font-size: 0.58rem;
  font-weight: 600;
  white-space: nowrap;
  flex: none;
}

.wf-progress-bar {
  margin-top: 0.4rem;
  height: 3px;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.08);
  overflow: hidden;
}

.wf-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #5ad5ff, #2f7eff);
  transition: width 0.3s ease;
}

.wf-item-message {
  margin: 0.35rem 0 0;
  color: #93a4b8;
  font-size: 0.62rem;
  line-height: 1.4;
}

.wf-item-notes,
.wf-item-events {
  margin: 0.25rem 0 0;
  padding: 0;
  list-style: none;
}

.wf-item-notes li,
.wf-item-events li {
  color: #6e8ba0;
  font-size: 0.56rem;
  line-height: 1.5;
  padding-left: 0.5rem;
  position: relative;
}

.wf-item-notes li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: #ffd38a;
}

.wf-item-events li::before {
  content: '›';
  position: absolute;
  left: 0;
  color: #5ad5ff;
}

.wf-item-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 0.4rem;
  padding-top: 0.35rem;
  border-top: 1px solid rgba(136, 192, 255, 0.06);
}

.wf-item-time {
  color: #5a7080;
  font-size: 0.55rem;
}

.wf-item-actions {
  display: flex;
  gap: 0.3rem;
}

.wf-action-btn {
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.4rem;
  padding: 0.2rem 0.5rem;
  background: rgba(4, 12, 23, 0.6);
  color: #8aa8bf;
  cursor: pointer;
  font: inherit;
  font-size: 0.56rem;
  font-weight: 500;
  transition: all 0.16s ease;
}

.wf-action-btn.cancel:hover {
  border-color: rgba(255, 138, 138, 0.3);
  color: #ff8a8a;
  background: rgba(255, 138, 138, 0.08);
}

.wf-action-btn.retry:hover {
  border-color: rgba(90, 213, 255, 0.3);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.12);
}

@media (max-width: 600px) {
  .wf-panel-overlay { padding: 1rem; }
  .wf-summary-grid { grid-template-columns: repeat(3, 1fr); }
}
</style>
