<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { storeToRefs } from 'pinia'
import { useLayersStore } from '../../stores/layers'
import { useWeatherTileManager } from '../../stores/weather-tile-manager'
import type { JobStatus } from '../../stores/layers/types'

const layersStore = useLayersStore()
const weatherTileManager = useWeatherTileManager()
const { activityVersion, statusVersion } = storeToRefs(weatherTileManager)
const emit = defineEmits<{ close: [] }>()

// 每秒刷新 tick，用于运行中工作流的时长动态更新
const tick = ref(0)
let tickTimer: number | null = null

// 从 activeLayersDisplay 中提取有 jobLayer 的条目，并合并 jobLayers 中的孤儿工作流
// （活跃图层已被移除但工作流记录仍在的失败/排队/已完成工作流）
const workflowItems = computed(() => {
  void tick.value
  // 1. 从活跃图层中提取有 jobLayer 的条目
  const fromActive = layersStore.activeLayersDisplay
    .filter((layer) => layer.jobLayer)
    .map((layer) => ({
      catalogId: layer.catalogId,
      name: layer.name,
      accentColor: layer.accentColor,
      category: layer.category,
      jobLayer: layer.jobLayer!,
    }))

  // 2. 从 jobLayers 中提取不在活跃图层中的孤儿工作流（失败/排队/取消等）
  const activeJobIds = new Set(fromActive.map((item) => item.jobLayer.jobId))
  const catalogMeta = new Map(
    layersStore.layerLibrary.map((item) => [item.catalogId, item]),
  )
  const fromOrphan = layersStore.jobLayers
    .filter((job) => !activeJobIds.has(job.jobId))
    .map((job) => {
      const catId = job.catalogId ?? ''
      const meta = catalogMeta.get(catId)
      const cat = layersStore.layerCategories.find((c) => c.id === meta?.category)
      return {
        catalogId: catId,
        name: meta?.name ?? job.name,
        accentColor: meta?.accentColor ?? cat?.accentColor ?? '#5a7080',
        category: meta?.category ?? 'research-group',
        jobLayer: job,
      }
    })

  return [...fromActive, ...fromOrphan].sort((a, b) => {
    // 运行中优先，然后按更新时间倒序
    const order: Record<string, number> = { running: 0, queued: 1, retry_pending: 2, failed: 3, cancelled: 4, succeeded: 5 }
    const diff = (order[a.jobLayer.status] ?? 9) - (order[b.jobLayer.status] ?? 9)
    if (diff !== 0) return diff
    return new Date(b.jobLayer.updatedAt).getTime() - new Date(a.jobLayer.updatedAt).getTime()
  })
})

/** 工作流摘要（不含天气瓦片调度） */
const summary = computed(() => layersStore.workflowSummary)

/** 衍生统计指标 */
const derivedStats = computed(() => {
  void tick.value
  const s = summary.value
  const active = s.running + s.queued + s.retryPending
  const completed = s.succeeded + s.failed + s.cancelled
  const successRate = completed > 0 ? Math.round((s.succeeded / completed) * 100) : null
  const overallProgress = s.total > 0 ? Math.round((completed / s.total) * 100) : 0
  return { active, completed, successRate, overallProgress }
})

/** 按分类分组统计工作流 */
const categoryBreakdown = computed(() => {
  void tick.value
  const map = new Map<string, { total: number; running: number; succeeded: number; failed: number }>()
  for (const item of workflowItems.value) {
    const cat = item.category
    if (!map.has(cat)) map.set(cat, { total: 0, running: 0, succeeded: 0, failed: 0 })
    const entry = map.get(cat)!
    entry.total++
    if (item.jobLayer.status === 'running' || item.jobLayer.status === 'queued' || item.jobLayer.status === 'retry_pending') entry.running++
    if (item.jobLayer.status === 'succeeded') entry.succeeded++
    if (item.jobLayer.status === 'failed') entry.failed++
  }
  return Array.from(map.entries())
    .map(([category, counts]) => ({ category, ...counts }))
    .sort((a, b) => b.total - a.total)
})

const statusMeta: Record<JobStatus, { label: string; color: string; bg: string }> = {
  running: { label: '运行中', color: '#5ad5ff', bg: 'rgba(90, 213, 255, 0.12)' },
  queued: { label: '排队中', color: '#88dfff', bg: 'rgba(136, 223, 255, 0.1)' },
  succeeded: { label: '已完成', color: '#9ff8cf', bg: 'rgba(159, 248, 207, 0.1)' },
  failed: { label: '失败', color: '#ff8a8a', bg: 'rgba(255, 138, 138, 0.1)' },
  cancelled: { label: '已取消', color: '#8aa8bf', bg: 'rgba(138, 168, 191, 0.1)' },
  retry_pending: { label: '等待重试', color: '#ffd38a', bg: 'rgba(255, 211, 138, 0.1)' },
}

/** 天气瓦片并发状态（自适应调节，仅在活跃时显示） */
const tileConcurrency = computed(() => {
  void activityVersion.value
  const active = weatherTileManager.getGlobalActiveTileCount()
  const hasWeatherLayers = weatherTileLayers.value.length > 0
  if (active === 0 && !hasWeatherLayers) return null
  return weatherTileManager.getConcurrencyInfo()
})

/** 活跃天气图层的瓦片状态详情 */
const weatherTileLayers = computed(() => {
  void activityVersion.value
  void statusVersion.value
  return layersStore.activeLayersDisplay
    .filter((layer) => layer.category === 'online-weather' && layer.visible)
    .map((layer) => {
      const status = weatherTileManager.getLayerStatus(layer.catalogId)
      return {
        catalogId: layer.catalogId,
        name: layer.name,
        accentColor: layer.accentColor,
        status,
      }
    })
    .filter((item) => item.status.active)
})

/** 全局天气瓦片缓存汇总 */
const globalTileStats = computed(() => {
  void activityVersion.value
  let totalCached = 0
  let totalViewport = 0
  let totalPending = 0
  for (const layer of weatherTileLayers.value) {
    totalCached += layer.status.cachedInViewport
    totalViewport += layer.status.viewportTotal
    totalPending += layer.status.pending
  }
  const hitRate = totalViewport > 0 ? Math.round((totalCached / totalViewport) * 100) : null
  return { totalCached, totalViewport, totalPending, hitRate }
})

/** 展开的诊断/事件面板 */
const expandedItems = ref<Set<string>>(new Set())
function toggleExpand(jobId: string) {
  if (expandedItems.value.has(jobId)) {
    expandedItems.value.delete(jobId)
  } else {
    expandedItems.value.add(jobId)
  }
}

function isExpanded(jobId: string): boolean {
  return expandedItems.value.has(jobId)
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatDuration(createdAt: string, updatedAt: string, status: JobStatus): string {
  void tick.value
  const start = new Date(createdAt).getTime()
  if (Number.isNaN(start)) return ''
  const isOngoing = status === 'running' || status === 'queued' || status === 'retry_pending'
  const end = isOngoing ? Date.now() : new Date(updatedAt).getTime()
  if (Number.isNaN(end) || end < start) return ''
  const seconds = Math.floor((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remSeconds = seconds % 60
  if (minutes < 60) return `${minutes}m${remSeconds}s`
  const hours = Math.floor(minutes / 60)
  const remMinutes = minutes % 60
  return `${hours}h${remMinutes}m`
}

function getCategoryName(categoryId: string): string {
  const cat = layersStore.layerCategories.find((c) => c.id === categoryId)
  return cat?.name ?? categoryId
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
  tickTimer = window.setInterval(() => {
    tick.value++
  }, 1000)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  if (tickTimer !== null) {
    clearInterval(tickTimer)
    tickTimer = null
  }
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
        <div class="wf-header-stats" v-if="summary.total > 0">
          <span class="wf-header-stat">
            <span class="wf-header-stat-value">{{ summary.total }}</span>
            <span class="wf-header-stat-label">总计</span>
          </span>
          <span class="wf-header-stat" v-if="derivedStats.active > 0">
            <span class="wf-header-stat-value" style="color: #5ad5ff">{{ derivedStats.active }}</span>
            <span class="wf-header-stat-label">活跃</span>
          </span>
          <span class="wf-header-stat" v-if="derivedStats.successRate !== null">
            <span class="wf-header-stat-value" :style="{ color: derivedStats.successRate >= 80 ? '#9ff8cf' : derivedStats.successRate >= 50 ? '#ffd38a' : '#ff8a8a' }">{{ derivedStats.successRate }}%</span>
            <span class="wf-header-stat-label">成功率</span>
          </span>
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

      <!-- 整体进度条 -->
      <div v-if="summary.total > 0" class="wf-overall-progress">
        <div class="wf-overall-progress-bar">
          <div class="wf-overall-progress-fill" :style="{ width: `${derivedStats.overallProgress}%` }"></div>
        </div>
        <span class="wf-overall-progress-text">整体完成度 {{ derivedStats.overallProgress }}%</span>
      </div>

      <!-- 天气瓦片并发状态（自适应调节） -->
      <div v-if="tileConcurrency" class="wf-tile-section">
        <div class="wf-tile-bar">
          <span class="wf-tile-icon">🌀</span>
          <span class="wf-tile-text">
            天气瓦片调度 — 在途 <strong>{{ tileConcurrency.active }}</strong> / 并发上限 <strong>{{ tileConcurrency.max }}</strong>
          </span>
          <span class="wf-tile-hint">自适应调节（CPU/内存/限流）</span>
        </div>
        <!-- 全局缓存统计 -->
        <div v-if="globalTileStats.totalViewport > 0" class="wf-tile-cache-bar">
          <span class="wf-tile-cache-label">视口缓存</span>
          <div class="wf-tile-cache-progress">
            <div class="wf-tile-cache-fill" :style="{ width: `${globalTileStats.hitRate ?? 0}%` }"></div>
          </div>
          <span class="wf-tile-cache-text">
            <strong>{{ globalTileStats.totalCached }}</strong> / {{ globalTileStats.totalViewport }}
            <template v-if="globalTileStats.totalPending > 0"> · 待加载 {{ globalTileStats.totalPending }}</template>
            <template v-if="globalTileStats.hitRate !== null"> · {{ globalTileStats.hitRate }}%</template>
          </span>
        </div>
        <!-- 分图层状态 -->
        <div v-if="weatherTileLayers.length > 0" class="wf-tile-layers">
          <div v-for="layer in weatherTileLayers" :key="layer.catalogId" class="wf-tile-layer-item">
            <span class="wf-tile-layer-dot" :style="{ background: layer.accentColor }"></span>
            <span class="wf-tile-layer-name">{{ layer.name }}</span>
            <span class="wf-tile-layer-stats">
              {{ layer.status.cachedInViewport }}/{{ layer.status.viewportTotal }}
              <template v-if="layer.status.pending > 0"> · 待{{ layer.status.pending }}</template>
            </span>
            <span v-if="layer.status.errorType" class="wf-tile-layer-error" :title="layer.status.errorMessage ?? ''">
              {{ layer.status.errorType }}
            </span>
          </div>
        </div>
      </div>

      <!-- 分类统计 -->
      <section v-if="categoryBreakdown.length > 1" class="wf-category-stats">
        <div v-for="cat in categoryBreakdown" :key="cat.category" class="wf-category-stat-item">
          <span class="wf-category-stat-name">{{ getCategoryName(cat.category) }}</span>
          <span class="wf-category-stat-counts">
            <span class="wf-cat-count" style="color: #5ad5ff" v-if="cat.running > 0">{{ cat.running }}</span>
            <span class="wf-cat-count" style="color: #9ff8cf" v-if="cat.succeeded > 0">{{ cat.succeeded }}</span>
            <span class="wf-cat-count" style="color: #ff8a8a" v-if="cat.failed > 0">{{ cat.failed }}</span>
            <span class="wf-cat-count-total">{{ cat.total }}</span>
          </span>
        </div>
      </section>

      <!-- 工作流列表 -->
      <section class="wf-list-section">
        <div v-if="workflowItems.length === 0 && !tileConcurrency" class="wf-empty">
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
                <span v-if="item.jobLayer.commandType" class="wf-item-cmd">{{ item.jobLayer.commandType }}</span>
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

            <!-- 指标 -->
            <div v-if="item.jobLayer.metrics?.length" class="wf-item-metrics">
              <span v-for="m in item.jobLayer.metrics.slice(0, 4)" :key="m.label" class="wf-metric-chip">
                <span class="wf-metric-label">{{ m.label }}</span>
                <span class="wf-metric-value">{{ m.value }}</span>
              </span>
            </div>

            <!-- 诊断（可展开） -->
            <ul v-if="item.jobLayer.diagnosticNotes?.length" class="wf-item-notes">
              <li v-for="note in (isExpanded(item.jobLayer.jobId) ? item.jobLayer.diagnosticNotes : item.jobLayer.diagnosticNotes.slice(0, 2))" :key="note">{{ note }}</li>
              <button v-if="item.jobLayer.diagnosticNotes.length > 2" class="wf-expand-btn" @click="toggleExpand(item.jobLayer.jobId)">
                {{ isExpanded(item.jobLayer.jobId) ? '收起' : `展开全部 (${item.jobLayer.diagnosticNotes.length})` }}
              </button>
            </ul>

            <!-- 事件消息（可展开） -->
            <ul v-if="item.jobLayer.eventMessages?.length" class="wf-item-events">
              <li v-for="evt in (isExpanded(item.jobLayer.jobId) ? item.jobLayer.eventMessages : item.jobLayer.eventMessages.slice(-2))" :key="evt">{{ evt }}</li>
              <button v-if="item.jobLayer.eventMessages.length > 2" class="wf-expand-btn" @click="toggleExpand(item.jobLayer.jobId)">
                {{ isExpanded(item.jobLayer.jobId) ? '收起' : `展开全部 (${item.jobLayer.eventMessages.length})` }}
              </button>
            </ul>

            <!-- 底部行：时间 + 时长 + 结果链接 + 操作 -->
            <div class="wf-item-footer">
              <div class="wf-item-time-info">
                <span class="wf-item-time" :title="`创建于 ${formatDateTime(item.jobLayer.createdAt)}`">
                  {{ formatTime(item.jobLayer.createdAt) }}
                </span>
                <span v-if="formatDuration(item.jobLayer.createdAt, item.jobLayer.updatedAt, item.jobLayer.status)" class="wf-item-duration">
                  · {{ formatDuration(item.jobLayer.createdAt, item.jobLayer.updatedAt, item.jobLayer.status) }}
                </span>
                <span v-if="item.jobLayer.resultUrl" class="wf-item-result-link">
                  · <a :href="item.jobLayer.resultUrl" target="_blank" rel="noopener">查看结果</a>
                </span>
              </div>
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
  width: min(720px, 100%);
  max-height: min(85vh, 800px);
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
  gap: 0.6rem;
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

.wf-header-stats {
  display: flex;
  gap: 0.8rem;
  margin-left: auto;
  margin-right: 0.6rem;
}

.wf-header-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.1rem;
}

.wf-header-stat-value {
  font-size: 0.95rem;
  font-weight: 700;
  line-height: 1;
  color: #d8e6f5;
}

.wf-header-stat-label {
  color: #5a7080;
  font-size: 0.5rem;
  letter-spacing: 0.04em;
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

/* 整体进度条 */
.wf-overall-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0 1.2rem 0.4rem;
}

.wf-overall-progress-bar {
  flex: 1;
  height: 4px;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.08);
  overflow: hidden;
}

.wf-overall-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #5ad5ff, #9ff8cf);
  transition: width 0.4s ease;
}

.wf-overall-progress-text {
  color: #7f96ab;
  font-size: 0.55rem;
  white-space: nowrap;
}

/* 天气瓦片区域 */
.wf-tile-section {
  margin: 0 1.2rem 0.4rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.wf-tile-bar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.7rem;
  border: 1px solid rgba(90, 213, 255, 0.16);
  border-radius: 0.6rem;
  background: rgba(10, 40, 60, 0.42);
}

.wf-tile-icon { font-size: 0.7rem; flex: none; }

.wf-tile-text {
  color: #c8dff0;
  font-size: 0.62rem;
}

.wf-tile-text strong {
  color: #5ad5ff;
  font-weight: 700;
}

.wf-tile-hint {
  margin-left: auto;
  color: #5a7080;
  font-size: 0.52rem;
}

/* 全局缓存进度 */
.wf-tile-cache-bar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.7rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: 0.5rem;
  background: rgba(4, 12, 23, 0.42);
}

.wf-tile-cache-label {
  color: #7f96ab;
  font-size: 0.52rem;
  flex: none;
}

.wf-tile-cache-progress {
  flex: 1;
  height: 3px;
  border-radius: 999px;
  background: rgba(136, 192, 255, 0.08);
  overflow: hidden;
}

.wf-tile-cache-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #5ad5ff, #2f7eff);
  transition: width 0.4s ease;
}

.wf-tile-cache-text {
  color: #c8dff0;
  font-size: 0.52rem;
  white-space: nowrap;
}

.wf-tile-cache-text strong {
  color: #5ad5ff;
  font-weight: 700;
}

/* 分图层状态 */
.wf-tile-layers {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.2rem 0.7rem;
}

.wf-tile-layer-item {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.52rem;
}

.wf-tile-layer-dot {
  width: 0.35rem;
  height: 0.35rem;
  border-radius: 50%;
  flex: none;
}

.wf-tile-layer-name {
  color: #a8c4d8;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-tile-layer-stats {
  color: #7f96ab;
  font-variant-numeric: tabular-nums;
}

.wf-tile-layer-error {
  color: #ff8a8a;
  font-size: 0.5rem;
  padding: 0 0.3rem;
  border: 1px solid rgba(255, 138, 138, 0.2);
  border-radius: 999px;
  cursor: help;
}

/* 分类统计 */
.wf-category-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0 1.2rem 0.4rem;
}

.wf-category-stat-item {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.08);
  border-radius: 999px;
  background: rgba(4, 12, 23, 0.42);
}

.wf-category-stat-name {
  color: #7f96ab;
  font-size: 0.52rem;
}

.wf-category-stat-counts {
  display: flex;
  align-items: center;
  gap: 0.2rem;
}

.wf-cat-count {
  font-size: 0.52rem;
  font-weight: 700;
}

.wf-cat-count-total {
  color: #5a7080;
  font-size: 0.5rem;
  margin-left: 0.15rem;
}

/* 汇总卡片网格 */
.wf-summary-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0.5rem;
  padding: 0.8rem 1.2rem 0.4rem;
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

.wf-item-cmd {
  color: #5a7080;
  font-size: 0.5rem;
  padding: 0.05rem 0.3rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 999px;
  flex: none;
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
  color: #a8c4d8;
  font-size: 0.6rem;
  line-height: 1.4;
}

/* 指标 */
.wf-item-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.35rem;
}

.wf-metric-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0.1rem 0.35rem;
  border: 1px solid rgba(136, 192, 255, 0.1);
  border-radius: 0.3rem;
  background: rgba(10, 30, 50, 0.42);
}

.wf-metric-label {
  color: #5a7080;
  font-size: 0.5rem;
}

.wf-metric-value {
  color: #c8dff0;
  font-size: 0.55rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.wf-item-notes,
.wf-item-events {
  margin: 0.3rem 0 0;
  padding-left: 0.7rem;
  list-style: none;
}

.wf-item-notes li,
.wf-item-events li {
  color: #8aa8bf;
  font-size: 0.55rem;
  line-height: 1.5;
}

.wf-item-events li {
  color: #7f96ab;
  border-left: 2px solid rgba(136, 192, 255, 0.12);
  padding-left: 0.4rem;
  margin-bottom: 0.15rem;
}

.wf-expand-btn {
  display: inline-block;
  margin-top: 0.2rem;
  border: none;
  background: none;
  color: #5ad5ff;
  font-size: 0.5rem;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.wf-expand-btn:hover {
  color: #88dfff;
}

.wf-item-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.4rem;
}

.wf-item-time-info {
  display: flex;
  align-items: center;
  gap: 0.15rem;
  color: #5a7080;
  font-size: 0.52rem;
  font-variant-numeric: tabular-nums;
  min-width: 0;
  overflow: hidden;
}

.wf-item-time {
  cursor: help;
}

.wf-item-duration {
  color: #7f96ab;
}

.wf-item-result-link a {
  color: #5ad5ff;
  text-decoration: none;
}

.wf-item-result-link a:hover {
  text-decoration: underline;
}

.wf-item-actions {
  display: flex;
  gap: 0.3rem;
  flex: none;
}

.wf-action-btn {
  border: 1px solid rgba(136, 192, 255, 0.16);
  border-radius: 0.3rem;
  padding: 0.15rem 0.5rem;
  font-size: 0.52rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease;
}

.wf-action-btn.cancel {
  color: #ff8a8a;
  border-color: rgba(255, 138, 138, 0.2);
  background: rgba(255, 138, 138, 0.06);
}

.wf-action-btn.cancel:hover {
  background: rgba(255, 138, 138, 0.14);
}

.wf-action-btn.retry {
  color: #5ad5ff;
  border-color: rgba(90, 213, 255, 0.2);
  background: rgba(90, 213, 255, 0.06);
}

.wf-action-btn.retry:hover {
  background: rgba(90, 213, 255, 0.14);
}
</style>
