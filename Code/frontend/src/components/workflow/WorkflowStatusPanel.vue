<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch, toRef, type Component } from 'vue'
import { Download, Settings, Microscope, Package, Circle, AlertTriangle, Cloud } from '../ui/icons'
import { useLayerWorkspace, useWorkflowRun } from '../../stores/layers/selectors'
import { useWeatherTileManager } from '../../stores/weather-tile-manager'
import { useWeatherSyncStatusStore } from '../../stores/weather-sync-status'
import { mergeWorkflowSummaryWithWeather } from '../../utils/workflow-status-merge'
import { formatWorkflowCommandChip } from '../../utils/workflow-error-messages'
import type { JobStatus } from '../../stores/layers/types'
import { WORKFLOW_COPY } from '../../ui-copy'
import { filterDisplayableNodeProgress } from '../../stores/layers/workflow-progress'
import {
  formatDownloadProgressDetail,
  hasDownloadProgressDetail,
} from '../../utils/workflow-download-display'
import { nodeMessageRedundantWithDetail } from '../../utils/workflow-node-progress-display'
import {
  isTechnicalRunTitle,
  resolveJobLayerDisplayName,
  stripComputingGroupSuffix,
} from '../../utils/workflow-run-display-name'
import { MAX_OPERATIONAL_LOG_COUNT } from '../../utils/workflow-operational-log'

/** 状态指示器主标题：工作流种子名优先，禁止图层 catalog 名 / wf-run-* 占位。 */
function workflowStatusDisplayName(options: {
  layerCatalogName: string
  jobLayer: { name?: string; commandLabel?: string; catalogId?: string }
}): string {
  const fromJob = stripComputingGroupSuffix(String(options.jobLayer.name || '').trim())
  if (fromJob && !isTechnicalRunTitle(fromJob)) return fromJob
  return resolveJobLayerDisplayName(
    { command_label: options.jobLayer.commandLabel, layer_id: options.jobLayer.catalogId },
    options.layerCatalogName,
    { previousName: options.jobLayer.name },
  )
}

const workspace = useLayerWorkspace()
const workflowRun = useWorkflowRun()
const { workflowError } = workflowRun
const weatherTileManager = useWeatherTileManager()
const weatherSyncStatus = useWeatherSyncStatusStore()
const activityVersion = toRef(weatherTileManager, 'activityVersion')
const statusVersion = toRef(weatherTileManager, 'statusVersion')
const syncInProgress = toRef(weatherSyncStatus, 'syncInProgress')
const emit = defineEmits<{ close: [] }>()

const eventStageFilter = ref('')
const copyFeedback = ref('')

// 每秒刷新 tick，用于运行中工作流的时长动态更新
const tick = ref(0)
let tickTimer: number | null = null

const weatherContribution = computed(() => {
  void activityVersion.value
  void statusVersion.value
  void syncInProgress.value
  return weatherTileManager.deriveWeatherWorkflowContribution({
    syncInProgress: syncInProgress.value,
  })
})

// 从 activeLayersDisplay 中提取有 jobLayer 的条目，并合并 jobLayers 中的孤儿工作流
const workflowItems = computed(() => {
  const fromActive = workspace.activeLayersDisplay.value
    .filter((layer) => layer.jobLayer)
    .map((layer) => ({
      catalogId: layer.catalogId,
      name: workflowStatusDisplayName({
        layerCatalogName: layer.name,
        jobLayer: layer.jobLayer!,
      }),
      accentColor: layer.accentColor,
      category: layer.category,
      jobLayer: layer.jobLayer!,
      synthetic: false as const,
    }))

  const activeJobIds = new Set(fromActive.map((item) => item.jobLayer.jobId))
  const catalogMeta = new Map(workspace.layerLibrary.value.map((item) => [item.catalogId, item]))
  const fromOrphan = workflowRun.jobLayers.value
    .filter((job) => !activeJobIds.has(job.jobId))
    .map((job) => {
      const catId = job.catalogId ?? ''
      const meta = catalogMeta.get(catId)
      const cat = workspace.layerCategories.value.find((c) => c.id === meta?.category)
      return {
        catalogId: catId,
        name: workflowStatusDisplayName({
          layerCatalogName: meta?.name ?? job.name,
          jobLayer: job,
        }),
        accentColor: meta?.accentColor ?? cat?.accentColor ?? 'var(--text-disabled)',
        category: meta?.category ?? 'research-group',
        jobLayer: job,
        synthetic: false as const,
      }
    })

  return [...fromActive, ...fromOrphan].sort((a, b) => {
    const order: Record<string, number> = {
      running: 0,
      queued: 1,
      retry_pending: 2,
      failed: 3,
      cancelled: 4,
      succeeded: 5,
    }
    const diff = (order[a.jobLayer.status] ?? 9) - (order[b.jobLayer.status] ?? 9)
    if (diff !== 0) return diff
    return new Date(b.jobLayer.updatedAt).getTime() - new Date(a.jobLayer.updatedAt).getTime()
  })
})

/** 天气瓦片合成行（非 workflow-runs） */
const weatherSyntheticItems = computed(() => {
  const catalogMeta = new Map(workspace.layerLibrary.value.map((item) => [item.catalogId, item]))
  return weatherContribution.value.items.map((item) => {
    const meta = catalogMeta.get(item.catalogId)
    const active = workspace.activeLayersDisplay.value.find((l) => l.catalogId === item.catalogId)
    const fillPercent =
      item.viewportTotal > 0 ? Math.round((item.cachedInViewport / item.viewportTotal) * 100) : 0
    return {
      catalogId: item.catalogId,
      name: active?.name ?? meta?.name ?? item.catalogId,
      accentColor: active?.accentColor ?? meta?.accentColor ?? 'var(--accent)',
      category: active?.category ?? meta?.category ?? 'weather',
      status: item.status,
      message: item.message,
      errorType: item.errorType,
      pending: item.pending,
      missingInViewport: item.missingInViewport,
      cachedInViewport: item.cachedInViewport,
      viewportTotal: item.viewportTotal,
      fillPercent,
    }
  })
})

/** 纯业务工作流摘要（不含天气瓦片） */
const jobSummary = computed(() => workflowRun.workflowSummary.value)

/** 与 ModeToolbar 口径一致：合并天气合成六态 */
const summary = computed(() => {
  void activityVersion.value
  void statusVersion.value
  return mergeWorkflowSummaryWithWeather(jobSummary.value, weatherContribution.value)
})

/** 是否存在活跃工作流（含天气瓦片），用于启用 tick / 进度刷新 */
const hasActiveWorkflows = computed(() => {
  const s = summary.value
  return s.running + s.queued + s.retryPending > 0
})

/** 衍生统计指标 */
const derivedStats = computed(() => {
  const s = summary.value
  const jobs = jobSummary.value
  const active = s.running + s.queued + s.retryPending
  const completed = jobs.succeeded + jobs.failed + jobs.cancelled
  const successRate = completed > 0 ? Math.round((jobs.succeeded / completed) * 100) : null
  const overallProgress = jobs.total > 0 ? Math.round((completed / jobs.total) * 100) : 0
  return { active, completed, successRate, overallProgress }
})

const tileErrorLabel: Record<string, string> = {
  timeout: '请求超时',
  'rate-limited': '频率超限',
  'circuit-open': '服务暂不可用',
  'data-empty': '本地无数据',
  'workflow-failed': '工作流失败',
  unknown: '加载失败',
}

const weatherStatusMeta: Record<string, { label: string; color: string; bg: string }> = {
  running: { label: '运行中', color: 'var(--accent)', bg: 'var(--accent-surface)' },
  queued: { label: '排队中', color: 'var(--accent-strong)', bg: 'rgba(136, 223, 255, 0.1)' },
  succeeded: { label: '已完成', color: 'var(--success)', bg: 'var(--success-surface)' },
  failed: { label: '失败', color: 'var(--danger)', bg: 'rgba(255, 138, 138, 0.1)' },
  cancelled: { label: '已取消', color: 'var(--text-muted)', bg: 'var(--border-default)' },
  retry_pending: { label: '等待重试', color: 'var(--accent-warm)', bg: 'rgba(255, 211, 138, 0.1)' },
}

/** 按分类分组统计工作流 */
const categoryBreakdown = computed(() => {
  const map = new Map<
    string,
    { total: number; running: number; succeeded: number; failed: number }
  >()
  for (const item of workflowItems.value) {
    const cat = item.category
    if (!map.has(cat)) map.set(cat, { total: 0, running: 0, succeeded: 0, failed: 0 })
    const entry = map.get(cat)!
    entry.total++
    if (
      item.jobLayer.status === 'running' ||
      item.jobLayer.status === 'queued' ||
      item.jobLayer.status === 'retry_pending'
    )
      entry.running++
    if (item.jobLayer.status === 'succeeded') entry.succeeded++
    if (item.jobLayer.status === 'failed') entry.failed++
  }
  return Array.from(map.entries())
    .map(([category, counts]) => ({ category, ...counts }))
    .sort((a, b) => b.total - a.total)
})

const statusMeta: Record<JobStatus, { label: string; color: string; bg: string }> = {
  running: { label: '运行中', color: 'var(--accent)', bg: 'var(--accent-surface)' },
  queued: { label: '排队中', color: 'var(--accent-strong)', bg: 'rgba(136, 223, 255, 0.1)' },
  succeeded: { label: '已完成', color: 'var(--success)', bg: 'var(--success-surface)' },
  failed: { label: '失败', color: 'var(--danger)', bg: 'rgba(255, 138, 138, 0.1)' },
  cancelled: { label: '已取消', color: 'var(--text-muted)', bg: 'var(--border-default)' },
  retry_pending: { label: '等待重试', color: 'var(--accent-warm)', bg: 'rgba(255, 211, 138, 0.1)' },
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
  return workspace.activeLayersDisplay.value
    .filter((layer) => layer.visible && workspace.isWeatherEngineLayer(layer.catalogId))
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

/** 与工具栏徽章同色的六态汇总（业务 job + 天气瓦片） */
const summaryCards = computed(() => {
  const s = summary.value
  const tilePending = globalTileStats.value.totalPending
  const tileCached = globalTileStats.value.totalCached
  const tileViewport = globalTileStats.value.totalViewport
  return [
    {
      key: 'running',
      label: '运行中',
      count: s.running,
      color: 'var(--accent)',
      sub: tilePending > 0 ? `含瓦片 ${tilePending}` : '',
    },
    { key: 'queued', label: '排队中', count: s.queued, color: 'var(--accent-strong)', sub: '' },
    {
      key: 'retryPending',
      label: '等待重试',
      count: s.retryPending,
      color: 'var(--accent-warm)',
      sub: '',
    },
    {
      key: 'succeeded',
      label: '已完成',
      count: s.succeeded,
      color: 'var(--success)',
      sub:
        tileCached > 0
          ? tileViewport > 0
            ? `含瓦片 ${tileCached}/${tileViewport}`
            : `含瓦片 ${tileCached}`
          : '',
    },
    { key: 'failed', label: '失败', count: s.failed, color: 'var(--danger)', sub: '' },
    { key: 'cancelled', label: '已取消', count: s.cancelled, color: 'var(--text-muted)', sub: '' },
  ] as const
})

/** 展开的诊断/事件面板 */
const expandedItems = ref<Set<string>>(new Set())
function toggleExpand(jobId: string) {
  const next = new Set(expandedItems.value)
  if (next.has(jobId)) next.delete(jobId)
  else next.add(jobId)
  expandedItems.value = next
}

function isExpanded(jobId: string): boolean {
  return expandedItems.value.has(jobId)
}

/** 失败作业 id 集合（浅层），避免 deep watch 整树 */
const failedJobIdsKey = computed(() =>
  workflowItems.value
    .filter((item) => item.jobLayer.status === 'failed')
    .map((item) => item.jobLayer.jobId)
    .sort()
    .join(','),
)

watch(failedJobIdsKey, (key) => {
  if (!key) return
  const next = new Set(expandedItems.value)
  let changed = false
  for (const jobId of key.split(',')) {
    if (jobId && !next.has(jobId)) {
      next.add(jobId)
      changed = true
    }
  }
  if (changed) expandedItems.value = next
})

function buildOperationalLogLines(job: {
  status: JobStatus
  eventMessages?: string[]
  failureHints?: string[]
}): string[] {
  const events = filteredEventMessages(job.eventMessages)
  if (job.status !== 'failed' || !job.failureHints?.length) return events
  const pinned = job.failureHints.filter((h) => !events.includes(h))
  return [...pinned, ...events]
}

/** 每 job 运行记录缓存，避免模板多次重算 */
const operationalLogByJobId = computed(() => {
  const map = new Map<string, string[]>()
  for (const item of workflowItems.value) {
    map.set(item.jobLayer.jobId, buildOperationalLogLines(item.jobLayer))
  }
  return map
})

function operationalLogLines(jobId: string): string[] {
  return operationalLogByJobId.value.get(jobId) ?? []
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
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
  const cat = workspace.layerCategories.value.find((c) => c.id === categoryId)
  return cat?.name ?? categoryId
}

/** 分类计数悬停说明（▶✓✕ 符号语义） */
function categoryTooltip(cat: {
  running: number
  succeeded: number
  failed: number
  total: number
}): string {
  return `运行 ${cat.running} · 完成 ${cat.succeeded} · 失败 ${cat.failed} · 共 ${cat.total} 项`
}

/** 下载速率/字节格式化见 workflow-download-display（与算法包同规则） */
/** 节点阶段图标映射 */
const STAGE_ICONS: Record<string, Component> = {
  download: Download,
  preprocess: Settings,
  inversion: Microscope,
  output: Package,
}

function getStageIcon(stage: string): Component {
  return STAGE_ICONS[stage] ?? Circle
}

function displayableNodeProgress<
  T extends {
    nodeId: string
    nodeLabel?: string
    stage?: string
    progress: number
    updatedAt?: string
    eventId?: string
  },
>(nodes: T[] | undefined): T[] {
  return filterDisplayableNodeProgress(nodes)
}

function handleCancel(jobId: string, catalogId: string) {
  void workflowRun.cancelWorkflowRunForJob(jobId, catalogId)
}

function handleRetry(jobId: string, catalogId: string) {
  void workflowRun.retryWorkflowRunForJob(jobId, catalogId)
}

function filteredEventMessages(messages: string[] | undefined): string[] {
  if (!messages?.length) return []
  const filter = eventStageFilter.value.trim().toLowerCase()
  if (!filter) return messages
  return messages.filter((m) => m.toLowerCase().includes(filter))
}

async function copyRunTimeline(job: {
  jobId: string
  status: string
  progress: number
  message: string
  eventMessages?: string[]
  nodeProgress?: Array<{ stage?: string; nodeLabel?: string; progress?: number; message?: string }>
  retryOfRunId?: string
}) {
  const payload = {
    run_id: job.jobId,
    status: job.status,
    progress: job.progress,
    message: job.message,
    retry_of_run_id: job.retryOfRunId,
    events: filteredEventMessages(job.eventMessages).slice(-MAX_OPERATIONAL_LOG_COUNT),
    node_progress: job.nodeProgress ?? [],
  }
  try {
    await navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
    copyFeedback.value = job.jobId
    window.setTimeout(() => {
      if (copyFeedback.value === job.jobId) copyFeedback.value = ''
    }, 2000)
  } catch {
    copyFeedback.value = ''
  }
}

function handleWeatherRetry(catalogId: string) {
  weatherTileManager.retryLayerTiles(catalogId)
}

async function handleWeatherSync(catalogId: string) {
  try {
    await weatherSyncStatus.triggerSync()
    weatherTileManager.retryLayerTiles(catalogId)
  } catch (err) {
    console.warn('[WorkflowStatusPanel] trigger sync failed', err)
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

function startTickTimer() {
  if (tickTimer !== null) return
  tickTimer = window.setInterval(() => {
    tick.value++
  }, 1000)
}

function stopTickTimer() {
  if (tickTimer !== null) {
    clearInterval(tickTimer)
    tickTimer = null
  }
}

// 监听活跃工作流状态，动态启停 tick 定时器（仅在有 running/queued/retry_pending 时运行）
watch(
  hasActiveWorkflows,
  (active) => {
    if (active) startTickTimer()
    else stopTickTimer()
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  void weatherSyncStatus.refreshOverview()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  stopTickTimer()
})
</script>

<template>
  <div class="wf-panel-overlay" @click.self="emit('close')">
    <div class="wf-panel">
      <!-- 顶部标题栏 -->
      <header class="wf-panel-header">
        <div>
          <p class="wf-panel-eyebrow">WORKFLOW STATUS</p>
          <h2>{{ WORKFLOW_COPY.statusOverview }}</h2>
        </div>
        <div v-if="summary.total > 0 || globalTileStats.totalPending > 0" class="wf-header-stats">
          <span class="wf-header-stat">
            <span class="wf-header-stat-value">{{ summary.total }}</span>
            <span class="wf-header-stat-label">总计</span>
          </span>
          <span v-if="derivedStats.active > 0" class="wf-header-stat">
            <span class="wf-header-stat-value" style="color: var(--accent)">{{
              derivedStats.active
            }}</span>
            <span class="wf-header-stat-label">活跃</span>
          </span>
          <span
            v-if="jobSummary.total > 0 && derivedStats.successRate !== null"
            class="wf-header-stat"
          >
            <span
              class="wf-header-stat-value"
              :style="{
                color:
                  derivedStats.successRate >= 80
                    ? 'var(--success)'
                    : derivedStats.successRate >= 50
                      ? 'var(--accent-warm)'
                      : 'var(--danger)',
              }"
              >{{ derivedStats.successRate }}%</span
            >
            <span class="wf-header-stat-label">成功率</span>
          </span>
        </div>
        <button class="wf-close-btn" title="关闭 (ESC)" @click="emit('close')">×</button>
      </header>

      <!-- 错误提示 -->
      <div v-if="workflowError" class="wf-error-banner">
        <span class="wf-error-icon"><AlertTriangle :size="14" aria-hidden="true" /></span>
        <span>{{ workflowError }}</span>
      </div>

      <!-- 汇总卡片（运行中含天气瓦片在途，与工具栏徽章同色同口径） -->
      <section class="wf-summary-grid" aria-label="工作流状态汇总">
        <div
          v-for="card in summaryCards"
          :key="card.key"
          class="wf-summary-card"
          :class="{ active: card.count > 0, idle: card.count === 0 }"
        >
          <span
            class="wf-summary-count"
            :style="{ color: card.count > 0 ? card.color : undefined }"
            >{{ card.count }}</span
          >
          <span class="wf-summary-label">{{ card.label }}</span>
          <span v-if="card.sub" class="wf-summary-sub">{{ card.sub }}</span>
        </div>
      </section>

      <!-- 整体进度条（仅业务工作流，不含天气瓦片） -->
      <div v-if="jobSummary.total > 0" class="wf-overall-progress">
        <div class="wf-overall-progress-bar">
          <div
            class="wf-overall-progress-fill"
            :style="{ width: `${derivedStats.overallProgress}%` }"
          ></div>
        </div>
        <span class="wf-overall-progress-text">整体完成度 {{ derivedStats.overallProgress }}%</span>
      </div>

      <!-- 天气瓦片并发状态（自适应调节） -->
      <div v-if="tileConcurrency" class="wf-tile-section">
        <div class="wf-tile-bar">
          <span class="wf-tile-icon"><Cloud :size="14" aria-hidden="true" /></span>
          <span class="wf-tile-text">
            天气瓦片调度 — 在途 <strong>{{ tileConcurrency.active }}</strong> / 并发上限
            <strong>{{ tileConcurrency.max }}</strong>
          </span>
          <span class="wf-tile-hint">自适应调节（CPU/内存/限流）</span>
        </div>
        <!-- 全局缓存统计 -->
        <div v-if="globalTileStats.totalViewport > 0" class="wf-tile-cache-bar">
          <span class="wf-tile-cache-label">视口缓存</span>
          <div class="wf-tile-cache-progress">
            <div
              class="wf-tile-cache-fill"
              :style="{ width: `${globalTileStats.hitRate ?? 0}%` }"
            ></div>
          </div>
          <span class="wf-tile-cache-text">
            <strong>{{ globalTileStats.totalCached }}</strong> / {{ globalTileStats.totalViewport }}
            <template v-if="globalTileStats.totalPending > 0">
              · 待加载 {{ globalTileStats.totalPending }}</template
            >
            <template v-if="globalTileStats.hitRate !== null">
              · {{ globalTileStats.hitRate }}%</template
            >
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
              <template v-else-if="layer.status.missingInViewport > 0">
                · 缺{{ layer.status.missingInViewport }}</template
              >
            </span>
            <span
              v-if="layer.status.missingInViewport > 0 && layer.status.gapSweepActive"
              class="wf-tile-layer-gap"
              title="视口仍有空洞，后台低频补拉中"
            >
              补洞中
            </span>
            <span
              v-else-if="layer.status.errorType"
              class="wf-tile-layer-error"
              :title="layer.status.errorMessage ?? ''"
            >
              {{ tileErrorLabel[layer.status.errorType] ?? layer.status.errorType }}
            </span>
          </div>
        </div>
      </div>

      <!-- 分类统计（2026-08-25 修复「两个 1 重复计数」观感：三色数字
           无标签并排，成功数+总数看起来像重复。改为符号前缀：
           ▶运行 ✓完成 ✕失败 + /总数，仅显示 >0 的项） -->
      <section v-if="categoryBreakdown.length > 1" class="wf-category-stats">
        <div v-for="cat in categoryBreakdown" :key="cat.category" class="wf-category-stat-item">
          <span class="wf-category-stat-name">{{ getCategoryName(cat.category) }}</span>
          <span class="wf-category-stat-counts" :title="categoryTooltip(cat)">
            <span v-if="cat.running > 0" class="wf-cat-count" style="color: var(--accent)"
              >▶{{ cat.running }}</span
            >
            <span v-if="cat.succeeded > 0" class="wf-cat-count" style="color: var(--success)"
              >✓{{ cat.succeeded }}</span
            >
            <span v-if="cat.failed > 0" class="wf-cat-count" style="color: var(--danger)"
              >✕{{ cat.failed }}</span
            >
            <span class="wf-cat-count-total">/{{ cat.total }}</span>
          </span>
        </div>
      </section>

      <!-- 工作流列表 -->
      <section class="wf-list-section">
        <div
          v-if="
            workflowItems.length === 0 && weatherSyntheticItems.length === 0 && !tileConcurrency
          "
          class="wf-empty"
        >
          <span class="wf-empty-icon">◇</span>
          <p>{{ WORKFLOW_COPY.emptyStatus }}</p>
          <p class="wf-empty-hint">从左侧面板添加图层并运行工作流后，状态将显示在这里</p>
        </div>

        <div v-else class="wf-list">
          <div class="wf-list-toolbar">
            <label class="wf-stage-filter">
              {{ WORKFLOW_COPY.filterByStage }}
              <input
                v-model="eventStageFilter"
                type="text"
                :placeholder="WORKFLOW_COPY.allStages"
              />
            </label>
          </div>
          <!-- 天气瓦片合成行 -->
          <div
            v-for="item in weatherSyntheticItems"
            :key="`weather-${item.catalogId}`"
            class="wf-item"
          >
            <div class="wf-item-header">
              <div class="wf-item-name">
                <span class="wf-item-dot" :style="{ background: item.accentColor }"></span>
                <span class="wf-item-title">{{ item.name }}</span>
                <span class="wf-item-cmd">天气瓦片</span>
              </div>
              <span
                class="wf-item-status"
                :style="{
                  color: weatherStatusMeta[item.status].color,
                  background: weatherStatusMeta[item.status].bg,
                }"
              >
                {{ weatherStatusMeta[item.status].label }}
                <template v-if="item.status === 'running' && item.viewportTotal > 0"
                  >{{ item.fillPercent }}%</template
                >
              </span>
            </div>
            <div v-if="item.status === 'running' && item.viewportTotal > 0" class="wf-progress-bar">
              <div class="wf-progress-fill" :style="{ width: `${item.fillPercent}%` }"></div>
            </div>
            <p v-if="item.message" class="wf-item-message">{{ item.message }}</p>
            <div class="wf-item-footer">
              <div class="wf-item-time-info">
                <span v-if="item.errorType" class="wf-item-duration">
                  {{ tileErrorLabel[item.errorType] ?? item.errorType }}
                </span>
                <span v-if="item.missingInViewport > 0" class="wf-item-duration">
                  · 缺 {{ item.missingInViewport }} 瓦片
                </span>
              </div>
              <div class="wf-item-actions">
                <button
                  v-if="item.status === 'failed' || item.status === 'retry_pending'"
                  class="wf-action-btn retry"
                  @click="handleWeatherRetry(item.catalogId)"
                >
                  重试
                </button>
                <button
                  v-if="item.errorType === 'data-empty' || item.status === 'failed'"
                  class="wf-action-btn retry"
                  @click="handleWeatherSync(item.catalogId)"
                >
                  触发同步
                </button>
              </div>
            </div>
          </div>

          <div v-for="item in workflowItems" :key="item.jobLayer.jobId" class="wf-item">
            <div class="wf-item-header">
              <div class="wf-item-name">
                <span class="wf-item-dot" :style="{ background: item.accentColor }"></span>
                <span class="wf-item-title">{{ item.name }}</span>
                <span
                  v-if="
                    formatWorkflowCommandChip(
                      item.jobLayer.commandType,
                      item.jobLayer.commandLabel,
                    ) &&
                    formatWorkflowCommandChip(
                      item.jobLayer.commandType,
                      item.jobLayer.commandLabel,
                    ) !== item.name
                  "
                  class="wf-item-cmd"
                  >{{
                    formatWorkflowCommandChip(item.jobLayer.commandType, item.jobLayer.commandLabel)
                  }}</span
                >
              </div>
              <span
                class="wf-item-status"
                :style="{
                  color: statusMeta[item.jobLayer.status].color,
                  background: statusMeta[item.jobLayer.status].bg,
                }"
              >
                {{ statusMeta[item.jobLayer.status].label }}
                <template v-if="item.jobLayer.status === 'running'"
                  >{{ item.jobLayer.progress }}%</template
                >
              </span>
            </div>

            <!-- 进度条 -->
            <div v-if="item.jobLayer.status === 'running'" class="wf-progress-bar">
              <div class="wf-progress-fill" :style="{ width: `${item.jobLayer.progress}%` }"></div>
            </div>

            <p
              v-if="
                item.jobLayer.executionRetryCount &&
                (item.jobLayer.status === 'running' || item.jobLayer.status === 'retry_pending')
              "
              class="wf-item-message wf-item-retry-hint"
            >
              工作流正在重试（第 {{ item.jobLayer.executionRetryCount }} 次），已完成步骤将尽量跳过
            </p>

            <!-- 消息 -->
            <p v-if="item.jobLayer.message" class="wf-item-message">{{ item.jobLayer.message }}</p>
            <p
              v-if="
                item.jobLayer.progressiveOverlayError &&
                item.jobLayer.progressiveOverlayError !== item.jobLayer.message
              "
              class="wf-item-message wf-item-progressive-error"
            >
              {{ item.jobLayer.progressiveOverlayError }}
            </p>
            <p
              v-else-if="
                item.jobLayer.progressiveOverlayCount &&
                item.jobLayer.status === 'running' &&
                !item.jobLayer.message?.includes('时间片')
              "
              class="wf-item-message wf-item-progressive-hint"
            >
              {{
                WORKFLOW_COPY.progressiveSyncOk.replace(
                  '{count}',
                  String(item.jobLayer.progressiveOverlayCount),
                )
              }}
            </p>
            <p
              v-if="
                item.jobLayer.reportSummary && item.jobLayer.reportSummary !== item.jobLayer.message
              "
              class="wf-item-summary"
            >
              {{ item.jobLayer.reportSummary }}
            </p>

            <!-- 指标 -->
            <div v-if="item.jobLayer.metrics?.length" class="wf-item-metrics">
              <span
                v-for="m in item.jobLayer.metrics.slice(0, 4)"
                :key="m.label"
                class="wf-metric-chip"
              >
                <span class="wf-metric-label">{{ m.label }}</span>
                <span class="wf-metric-value">{{ m.value }}</span>
              </span>
            </div>

            <!-- 诊断（可展开；事件列表存在时互斥隐藏，避免同一内容双列） -->
            <ul
              v-if="!item.jobLayer.eventMessages?.length && item.jobLayer.diagnosticNotes?.length"
              class="wf-item-notes"
            >
              <li
                v-for="note in isExpanded(item.jobLayer.jobId)
                  ? item.jobLayer.diagnosticNotes
                  : item.jobLayer.diagnosticNotes.slice(0, 2)"
                :key="note"
              >
                {{ note }}
              </li>
              <button
                v-if="item.jobLayer.diagnosticNotes.length > 2"
                class="wf-expand-btn"
                @click="toggleExpand(item.jobLayer.jobId)"
              >
                {{
                  isExpanded(item.jobLayer.jobId)
                    ? '收起'
                    : `展开全部 (${item.jobLayer.diagnosticNotes.length})`
                }}
              </button>
            </ul>

            <!-- 技术日志（默认折叠，避免烘焙工具 stdout 淹没主状态） -->
            <details v-if="item.jobLayer.techLogs?.length" class="wf-tech-logs">
              <summary>技术日志（{{ item.jobLayer.techLogs.length }}）</summary>
              <pre
                v-for="(log, idx) in item.jobLayer.techLogs"
                :key="`${item.jobLayer.jobId}-tech-${idx}`"
                class="wf-tech-log-body"
                >{{ log }}</pre>
            </details>

            <!-- 运行记录（调度/节点起止/错误；不含高频下载 tick） -->
            <ul v-if="operationalLogLines(item.jobLayer.jobId).length" class="wf-item-events">
              <li class="wf-events-title">运行记录</li>
              <li
                v-for="(evt, evtIdx) in isExpanded(item.jobLayer.jobId)
                  ? operationalLogLines(item.jobLayer.jobId)
                  : operationalLogLines(item.jobLayer.jobId).slice(
                      0,
                      item.jobLayer.status === 'failed' ? 6 : 2,
                    )"
                :key="`${item.jobLayer.jobId}-${evtIdx}-${evt}`"
                :class="{ 'wf-event-error': /ERROR|失败|failed/i.test(evt) }"
              >
                {{ evt }}
              </li>
              <button
                v-if="
                  operationalLogLines(item.jobLayer.jobId).length >
                  (item.jobLayer.status === 'failed' ? 6 : 2)
                "
                class="wf-expand-btn"
                @click="toggleExpand(item.jobLayer.jobId)"
              >
                {{
                  isExpanded(item.jobLayer.jobId)
                    ? '收起'
                    : `展开全部 (${operationalLogLines(item.jobLayer.jobId).length})`
                }}
              </button>
            </ul>

            <!-- 节点级进度 -->
            <div
              v-if="displayableNodeProgress(item.jobLayer.nodeProgress).length"
              class="node-progress-section"
            >
              <h4 class="progress-section-title">节点进度</h4>
              <div
                v-for="np in displayableNodeProgress(item.jobLayer.nodeProgress)"
                :key="np.nodeId"
                class="node-progress-item"
              >
                <div class="node-progress-header">
                  <span class="node-stage-icon"
                    ><component :is="getStageIcon(np.stage)" :size="14"
                  /></span>
                  <span class="node-label">{{ np.nodeLabel }}</span>
                  <span v-if="np.terminalHint === 'skipped'" class="node-skipped-badge"
                    >已跳过</span
                  >
                  <span
                    v-else-if="np.terminalHint === 'complete' && np.progress >= 100"
                    class="node-done-badge"
                    >已完成</span
                  >
                  <span class="node-progress-value">{{ np.progress }}%</span>
                </div>
                <div v-if="np.terminalHint !== 'skipped'" class="node-progress-bar">
                  <div class="node-progress-fill" :style="{ width: np.progress + '%' }"></div>
                </div>
                <div v-else class="node-progress-bar node-progress-bar-skipped">
                  <div class="node-progress-fill" style="width: 100%"></div>
                </div>
                <span
                  v-if="np.message && !nodeMessageRedundantWithDetail(np)"
                  class="node-progress-message"
                  >{{ np.message }}</span
                >
                <!-- P0-10：节点产物下载入口（/artifacts/{id} 由后端 FileResponse 直接下载） -->
                <div v-if="np.artifacts?.length" class="node-artifacts">
                  <a
                    v-for="artifactId in np.artifacts"
                    :key="artifactId"
                    class="node-artifact-link"
                    :href="`/artifacts/${encodeURIComponent(artifactId)}`"
                    :download="artifactId"
                    :title="`下载产物 ${artifactId}`"
                  >
                    ⬇ {{ artifactId.split('/').pop() }}
                  </a>
                </div>
                <div
                  v-if="
                    np.detail &&
                    (hasDownloadProgressDetail(np.detail) ||
                      np.detail.chunksTotal ||
                      np.detail.pixelsTotal ||
                      np.detail.blocksTotal ||
                      np.detail.dateStart)
                  "
                  class="node-progress-detail"
                >
                  <span
                    v-if="hasDownloadProgressDetail(np.detail)"
                    class="download-progress-detail"
                  >
                    {{ formatDownloadProgressDetail(np.detail) }}
                  </span>
                  <span v-if="np.detail.blocksTotal && !hasDownloadProgressDetail(np.detail)">
                    块 {{ np.detail.blocksDone ?? 0 }}/{{ np.detail.blocksTotal
                    }}<template v-if="np.detail.dateStart && np.detail.dateEnd">
                      · {{ np.detail.dateStart }}–{{ np.detail.dateEnd }}
                    </template>
                  </span>
                  <span v-else-if="np.detail.chunksTotal && !hasDownloadProgressDetail(np.detail)">
                    chunk {{ np.detail.chunksDone ?? 0 }}/{{ np.detail.chunksTotal }}
                  </span>
                  <span v-if="np.detail.pixelsTotal">
                    pixel {{ np.detail.pixelsDone ?? 0 }}/{{ np.detail.pixelsTotal }}
                  </span>
                  <span
                    v-if="
                      np.detail.phase &&
                      !hasDownloadProgressDetail(np.detail) &&
                      np.detail.phase !== 'downloading'
                    "
                    >{{ np.detail.phase }}</span
                  >
                </div>
              </div>
            </div>

            <!-- 底部行：时间 + 时长 + 结果链接 + 操作 -->
            <div class="wf-item-footer">
              <div class="wf-item-time-info">
                <span
                  class="wf-item-time"
                  :title="`创建于 ${formatDateTime(item.jobLayer.createdAt)}`"
                >
                  {{ formatTime(item.jobLayer.createdAt) }}
                </span>
                <span
                  v-if="
                    formatDuration(
                      item.jobLayer.createdAt,
                      item.jobLayer.updatedAt,
                      item.jobLayer.status,
                    )
                  "
                  class="wf-item-duration"
                >
                  ·
                  {{
                    formatDuration(
                      item.jobLayer.createdAt,
                      item.jobLayer.updatedAt,
                      item.jobLayer.status,
                    )
                  }}
                </span>
                <span v-if="item.jobLayer.resultUrl" class="wf-item-result-link">
                  · <a :href="item.jobLayer.resultUrl" target="_blank" rel="noopener">查看结果</a>
                </span>
                <span v-if="item.jobLayer.retryOfRunId" class="wf-item-retry-of">
                  · {{ WORKFLOW_COPY.retryOf }} {{ item.jobLayer.retryOfRunId }}
                </span>
              </div>
              <div class="wf-item-actions">
                <button
                  class="wf-action-btn copy"
                  type="button"
                  @click="copyRunTimeline(item.jobLayer)"
                >
                  {{
                    copyFeedback === item.jobLayer.jobId ? '已复制' : WORKFLOW_COPY.copyRunTimeline
                  }}
                </button>
                <button
                  v-if="
                    item.jobLayer.status === 'running' ||
                    item.jobLayer.status === 'queued' ||
                    item.jobLayer.status === 'retry_pending'
                  "
                  class="wf-action-btn cancel"
                  @click="handleCancel(item.jobLayer.jobId, item.catalogId)"
                >
                  {{ WORKFLOW_COPY.cancelAction }}
                </button>
                <button
                  v-if="item.jobLayer.status === 'failed' || item.jobLayer.status === 'cancelled'"
                  class="wf-action-btn retry"
                  @click="handleRetry(item.jobLayer.jobId, item.catalogId)"
                >
                  {{ WORKFLOW_COPY.retryAction }}
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
  background: var(--surface-1);
  backdrop-filter: blur(12px);
}

.wf-panel {
  width: min(720px, 100%);
  max-height: min(85vh, 800px);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-default);
  border-radius: 1.2rem;
  background: linear-gradient(180deg, var(--surface-1), var(--surface-1)), var(--surface-1);
  box-shadow: 0 24px 60px rgba(1, 8, 16, 0.5);
  overflow: hidden;
}

.wf-panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.6rem;
  padding: 1rem 1.2rem 0.8rem;
  border-bottom: 1px solid var(--border-subtle);
}

.wf-panel-eyebrow {
  margin: 0 0 0.2rem;
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.wf-panel-header h2 {
  margin: 0;
  font-size: 1rem;
  color: var(--text-strong);
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
  color: var(--text-primary);
}

.wf-header-stat-label {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  letter-spacing: 0.04em;
}

.wf-close-btn {
  border: none;
  background: var(--border-subtle);
  color: var(--text-muted);
  font-size: 1.2rem;
  width: 1.8rem;
  height: 1.8rem;
  border-radius: 0.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    background 0.16s ease,
    color 0.16s ease;
  flex: none;
}

.wf-close-btn:hover {
  background: rgba(255, 138, 138, 0.16);
  color: var(--danger);
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
  color: var(--danger);
  font-size: var(--font-size-caption);
}

.wf-error-icon {
  font-size: 0.8rem;
  flex: none;
}

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
  background: var(--border-subtle);
  overflow: hidden;
}

.wf-overall-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--success));
  transition: width 0.4s ease;
}

.wf-overall-progress-text {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
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
  border: 1px solid var(--accent-surface);
  border-radius: 0.6rem;
  background: var(--surface-raised);
}

.wf-tile-icon {
  font-size: var(--font-size-caption);
  flex: none;
}

.wf-tile-text {
  color: var(--text-primary);
  font-size: var(--font-size-caption);
}

.wf-tile-text strong {
  color: var(--accent);
  font-weight: 700;
}

.wf-tile-hint {
  margin-left: auto;
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}

/* 全局缓存进度 */
.wf-tile-cache-bar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.5rem;
  background: var(--surface-raised);
}

.wf-tile-cache-label {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  flex: none;
}

.wf-tile-cache-progress {
  flex: 1;
  height: 3px;
  border-radius: 999px;
  background: var(--border-subtle);
  overflow: hidden;
}

.wf-tile-cache-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--accent-blue-deep));
  transition: width 0.4s ease;
}

.wf-tile-cache-text {
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  white-space: nowrap;
}

.wf-tile-cache-text strong {
  color: var(--accent);
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
  font-size: var(--font-size-caption);
}

.wf-tile-layer-dot {
  width: 0.35rem;
  height: 0.35rem;
  border-radius: 50%;
  flex: none;
}

.wf-tile-layer-name {
  color: var(--text-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-tile-layer-stats {
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.wf-tile-layer-error {
  color: var(--danger);
  font-size: var(--font-size-caption);
  padding: 0 0.3rem;
  border: 1px solid rgba(255, 138, 138, 0.2);
  border-radius: 999px;
  cursor: help;
}

.wf-tile-layer-gap {
  color: var(--success);
  font-size: var(--font-size-caption);
  padding: 0 0.3rem;
  border: 1px solid var(--success-border);
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
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-raised);
}

.wf-category-stat-name {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
}

.wf-category-stat-counts {
  display: flex;
  align-items: center;
  gap: 0.2rem;
}

.wf-cat-count {
  font-size: var(--font-size-caption);
  font-weight: 700;
}

.wf-cat-count-total {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  margin-left: 0.15rem;
}

/* 汇总卡片网格：宽屏 6 列，窄屏自动折行，与工具栏徽章色一致 */
.wf-summary-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 0.4rem;
  padding: 0.8rem 1.2rem 0.4rem;
}

@media (max-width: 768px) {
  .wf-summary-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.wf-summary-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.18rem;
  min-width: 0;
  padding: 0.48rem 0.28rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.6rem;
  background: var(--surface-raised);
  transition:
    border-color 0.2s ease,
    background-color 0.2s ease,
    opacity 0.2s ease;
}

.wf-summary-card.active {
  border-color: var(--border-strong);
  background: var(--surface-raised);
}

.wf-summary-card.idle {
  opacity: 0.55;
}

.wf-summary-count {
  font-size: clamp(0.92rem, 2.2vw, 1.1rem);
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--text-disabled);
}

.wf-summary-label {
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  letter-spacing: 0.04em;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.wf-summary-sub {
  display: block;
  margin-top: 1px;
  color: var(--text-faint);
  font-size: var(--font-size-caption);
  letter-spacing: 0.02em;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

/* 列表区 */
.wf-list-section {
  flex: 1;
  overflow-y: auto;
  padding: 0 1.2rem 1.2rem;
}

.wf-list-toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.45rem;
}

.wf-stage-filter {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: var(--font-size-caption);
  color: rgba(200, 220, 235, 0.78);
}

.wf-stage-filter input {
  min-width: 8rem;
  padding: 0.15rem 0.35rem;
  border-radius: 0.25rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-size: var(--font-size-caption);
}

.wf-item-retry-of {
  color: rgba(255, 211, 138, 0.9);
  font-size: var(--font-size-caption);
}

.wf-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 3rem 1rem;
  color: var(--text-faint);
  text-align: center;
}

.wf-empty-icon {
  font-size: 2rem;
  opacity: 0.4;
}

.wf-empty p {
  margin: 0;
  font-size: var(--font-size-caption);
}
.wf-empty-hint {
  font-size: var(--font-size-caption);
  color: var(--text-disabled);
}

.wf-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.wf-item {
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.7rem;
  background: var(--surface-raised);
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
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wf-item-cmd {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  padding: 0.05rem 0.3rem;
  border: 1px solid var(--border-subtle);
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
  font-size: var(--font-size-caption);
  font-weight: 600;
  white-space: nowrap;
  flex: none;
}

.wf-progress-bar {
  margin-top: 0.4rem;
  height: 3px;
  border-radius: 999px;
  background: var(--border-subtle);
  overflow: hidden;
}

.wf-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--accent-blue-deep));
  transition: width 0.3s ease;
}

/* 节点级进度 */
.node-progress-section {
  margin-top: 0.4rem;
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.5rem;
  background: var(--surface-raised);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.progress-section-title {
  margin: 0;
  color: var(--accent-strong);
  font-size: var(--font-size-caption);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.node-progress-item {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.node-progress-header {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.node-stage-icon {
  font-size: var(--font-size-caption);
  flex: none;
  line-height: 1;
}

.node-label {
  flex: 1;
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-progress-value {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted);
}

.node-skipped-badge,
.node-done-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 4px;
  margin-left: 6px;
}

.node-skipped-badge {
  color: var(--text-muted);
  background: var(--border-default);
}

.node-done-badge {
  color: var(--success);
  background: var(--success-surface);
}

.node-progress-bar-skipped .node-progress-fill {
  opacity: 0.35;
}

.wf-events-title {
  list-style: none;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.wf-event-error {
  color: var(--danger);
}

.node-progress-bar {
  height: 4px;
  border-radius: 999px;
  background: var(--border-subtle);
  overflow: hidden;
}

.node-progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--accent-blue-deep));
  transition: width 0.3s ease;
}

.node-progress-message {
  display: block;
  margin-top: 4px;
  font-size: var(--font-size-caption);
  opacity: 0.75;
  word-break: break-word;
}

.node-artifacts {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.node-artifact-link {
  font-size: var(--font-size-caption);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--accent-surface);
  color: var(--accent);
  text-decoration: none;
  word-break: break-all;
}

.node-artifact-link:hover {
  background: var(--accent-surface);
  text-decoration: underline;
}

.node-progress-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
  font-size: var(--font-size-caption);
  opacity: 0.8;
}

.wf-item-message {
  margin: 0.35rem 0 0;
  color: var(--text-secondary);
  font-size: var(--font-size-caption);
  line-height: 1.4;
}

.wf-tech-logs {
  margin: 0.4rem 0 0;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
  padding: 0.35rem 0.55rem;
  font-size: var(--font-size-caption);
  color: var(--text-muted);
}

.wf-tech-logs summary {
  cursor: pointer;
  user-select: none;
  color: var(--text-secondary);
  font-weight: 500;
}

.wf-tech-log-body {
  margin: 0.4rem 0 0;
  max-height: 12rem;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.7rem;
  line-height: 1.4;
  color: var(--text-secondary);
}

.wf-item-progressive-error {
  color: var(--danger);
  border-left: 2px solid rgba(220, 80, 80, 0.75);
  padding-left: 0.4rem;
}

.wf-item-progressive-hint {
  color: var(--accent);
  opacity: 0.92;
}

.wf-item-retry-hint {
  color: var(--accent-warm);
  border-left: 2px solid rgba(255, 211, 138, 0.55);
  padding-left: 0.4rem;
}

.wf-item-summary {
  margin: 0.25rem 0 0;
  color: var(--text-primary);
  font-size: var(--font-size-caption);
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
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
  border: 1px solid var(--border-subtle);
  border-radius: 0.3rem;
  background: var(--surface-raised);
}

.wf-metric-label {
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
}

.wf-metric-value {
  color: var(--text-primary);
  font-size: var(--font-size-caption);
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
  color: var(--text-muted);
  font-size: var(--font-size-caption);
  line-height: 1.5;
}

.wf-item-events li {
  color: var(--text-muted);
  border-left: 2px solid var(--border-default);
  padding-left: 0.4rem;
  margin-bottom: 0.15rem;
}

.wf-expand-btn {
  display: inline-block;
  margin-top: 0.2rem;
  border: none;
  background: none;
  color: var(--accent);
  font-size: var(--font-size-caption);
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.wf-expand-btn:hover {
  color: var(--accent-strong);
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
  color: var(--text-disabled);
  font-size: var(--font-size-caption);
  font-variant-numeric: tabular-nums;
  min-width: 0;
  overflow: hidden;
}

.wf-item-time {
  cursor: help;
}

.wf-item-duration {
  color: var(--text-muted);
}

.wf-item-result-link a {
  color: var(--accent);
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
  border: 1px solid var(--border-default);
  border-radius: 0.3rem;
  padding: 0.15rem 0.5rem;
  font-size: var(--font-size-caption);
  font-weight: 600;
  cursor: pointer;
  transition:
    background 0.16s ease,
    border-color 0.16s ease;
}

.wf-action-btn.cancel {
  color: var(--danger);
  border-color: rgba(255, 138, 138, 0.2);
  background: rgba(255, 138, 138, 0.06);
}

.wf-action-btn.cancel:hover {
  background: rgba(255, 138, 138, 0.14);
}

.wf-action-btn.retry {
  color: var(--accent);
  border-color: var(--accent-border);
  background: var(--accent-surface);
}

.wf-action-btn.retry:hover {
  background: var(--accent-surface);
}

.wf-action-btn.copy {
  color: var(--text-secondary);
  border-color: var(--border-default);
}

.wf-action-btn.copy:hover {
  color: var(--accent);
  border-color: var(--accent);
}

.download-progress-detail {
  font-size: var(--font-size-caption);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
</style>
