import { computed, nextTick, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import {
  fetchLayerCatalog,
  getWorkflowEvents,
  getWorkflowRun,
  listActiveWorkflowRuns,
  submitWorkflow,
  cancelWorkflowRun,
  retryWorkflowRun,
  getWeatherPoint,
  materializeWorkflowMapLayers,
} from '../../services/runtime-api'
import {
  supportsMapLayerCapability,
  supportsParticleFlowCapability,
  supportsViewportDrivenRefreshCapability,
} from '../../services/layer-capabilities'
import { useWeatherTileManager } from '../weather-tile-manager'
import { useWeatherSourcePrefsStore } from '../weather-source-prefs'
import { useUiStore } from '../ui'
import { formatClockHourLabel } from '../../utils/weather-timeline'
import { buildDefaultWeatherRenderHint } from '../../components/map/weather-render'
import type {
  BoundingBox,
  RuntimeLayerDescriptor,
  WeatherPointResponse,
  WorkflowEvent,
} from '../../services/runtime-api'
import { LAYER_CATEGORIES, LAYER_LIBRARY } from './catalog'
import { allocateLayerAccent } from './layer-accent'
import { isWeatherEngineCatalogId } from './weather-session'
import { createWeatherViewportSlice } from './weather-viewport'
import { buildJobLayer, extractOverlayImportsFromResultRefs } from './result-adapter'
import { buildImportedVectorPayload, computeBounds, inferGeometryType } from './imported-vector'
import { buildImportedRasterPayload } from './imported-raster'
import { deleteImportedRaster } from '../../services/data-import'
import { useWorkflowOutputLayersStore } from '../workflow-output-layers'
import { persistLayerDisplayName, resolvePersistedDisplayName } from './layer-display-names'
import {
  buildWorkspaceSnapshot,
  isCatalogDismissed,
  isOverlayDismissed,
  isRunDismissed,
  isVectorDismissed,
  loadWorkspaceSnapshot,
  rememberDismissedLayer,
  saveWorkspaceSnapshot,
  type PersistedActiveLayer,
  type PersistedCatalogLayer,
  type PersistedVectorLayer,
} from './workspace-persist'
import { formatProgressShell, pickLatestNodeProgress } from '../../utils/workflow-progress-format'
import { claimOrphanWorkflowRun, isSubmitTimeoutError } from '../../utils/workflow-submit-reconcile'
import { WORKFLOW_COPY } from '../../ui-copy/workflow'
import { formatWorkflowEventLine } from '../../utils/workflow-event-label'
import { localizeWorkflowErrorMessage } from '../../utils/workflow-error-messages'
import {
  timelineTargetFromWorkflowTimeKey,
  type WorkflowProgressTimeSeekHint,
} from '../../utils/workflow-timekey-seek'
import type {
  ActiveLayer,
  ActiveLayerDisplay,
  ActiveRunLayerGroup,
  JobLayerItem,
  JobStatus,
  LayerCatalogItem,
  LayerHotspot,
  LayerSidebarView,
  NodeProgress,
  RuntimeLayerLibraryItem,
  WorkflowSummary,
} from './types'

function genInstanceId() {
  return crypto.randomUUID()
}

/** 本地导入（矢量 / 栅格）不走 catalog / tile manager */
function isLocalImport(layer: ActiveLayer): boolean {
  return Boolean(layer.importedVector || layer.importedRaster)
}

/** 产品标签归一：OMEGA_BLOCK / OMEGA_PIXEL → OMEGA，便于绑入计算组 */
function normalizeProductTag(raw: string | null | undefined): string {
  const tag = String(raw || '')
    .trim()
    .toUpperCase()
    .replace(/^ALGORITHM MAP LAYER:\s*/i, '')
  if (!tag) return ''
  if (tag === 'OMEGA_BLOCK' || tag.startsWith('OMEGA_BLOCK') || tag.includes('OMEGA_BLOCK')) {
    return 'OMEGA'
  }
  if (tag === 'OMEGA_PIXEL' || tag.includes('OMEGA_PIXEL') || tag.includes('OMEGA_PIX')) {
    return 'OMEGA'
  }
  if (tag === 'OMEGA' || tag.endsWith('_OMEGA') || tag.endsWith('-OMEGA')) return 'OMEGA'
  if (tag === 'SM' || tag.endsWith('_SM') || tag.endsWith('-SM')) return 'SM'
  if (tag === 'VOD' || tag.endsWith('_VOD') || tag.endsWith('-VOD')) return 'VOD'
  return tag
}

function isTerminalStatus(status: string) {
  // retry_pending 是非终态（等待重试），不应包含在此处
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

function debugLog(module: string, ...args: unknown[]) {
  console.log(`[${performance.now().toFixed(1)}ms] [LayersStore:${module}]`, ...args)
}

// ─── 真实数据适配器 ──────────────────────────────────────────────────────────

/** 从 jobLayer 提取真实数据显示数据 */
function buildRealLayerDisplay(
  layer: ActiveLayer,
  item: RuntimeLayerLibraryItem,
): Partial<ActiveLayerDisplay> {
  const jobLayer = layer.jobLayer
  if (!jobLayer) return {}

  const primaryMetric = jobLayer.metrics?.find((m) => m.label !== '队列')
  const metricValue = primaryMetric?.value ?? '--'
  const renderHint = jobLayer.mapLayerPayload?.renderHint
  const resultDto = asRecord(jobLayer.resultDto)
  const providerKey = typeof resultDto?.provider_key === 'string' ? resultDto.provider_key : null
  const resultCategory =
    typeof resultDto?.result_category === 'string' ? resultDto.result_category : null
  const providerSummary = typeof resultDto?.summary === 'string' ? resultDto.summary : null
  const providerStatusLabel =
    typeof resultDto?.status_label === 'string' ? resultDto.status_label : null
  const providerConfidenceLabel =
    typeof resultDto?.confidence_label === 'string' ? resultDto.confidence_label : null
  const isSampleProvider =
    item.backendStatus === 'sample' ||
    (resultCategory === 'provider' && providerKey?.startsWith('lab_output'))
  let confidenceLabel = '以工作流结果为准'
  if (renderHint?.notes?.length) {
    confidenceLabel = renderHint.notes[0]
  } else if (providerConfidenceLabel) {
    confidenceLabel = providerConfidenceLabel
  } else if (jobLayer.diagnosticNotes?.length) {
    confidenceLabel = jobLayer.diagnosticNotes[0]
  }

  return {
    metricValue,
    summary:
      providerSummary ??
      jobLayer.resultView?.summary ??
      jobLayer.reportSummary ??
      jobLayer.message ??
      item.description,
    statusLabel:
      jobLayer.status === 'succeeded'
        ? isSampleProvider
          ? (providerStatusLabel ?? '实验结果')
          : '真实数据'
        : jobLayer.status === 'failed'
          ? '数据异常'
          : jobLayer.status === 'cancelled'
            ? '任务已取消'
            : '任务处理中',
    trendLabel:
      jobLayer.status === 'succeeded'
        ? isSampleProvider
          ? '实验 provider 已执行，可用于联调验收'
          : '最新工作流结果已接入'
        : jobLayer.status === 'failed'
          ? '最近一次运行失败'
          : '等待工作流返回结果',
    sourceLabel:
      isSampleProvider && providerKey ? `实验 Provider · ${providerKey}` : item.sourceLabel,
    confidenceLabel,
    availabilityState:
      jobLayer.status === 'succeeded'
        ? 'ready'
        : jobLayer.status === 'failed'
          ? 'empty'
          : 'partial',
    availabilityLabel:
      jobLayer.status === 'succeeded'
        ? '完整数据'
        : jobLayer.status === 'failed'
          ? '数据异常'
          : '加载中',
    availabilityDescription:
      jobLayer.status === 'succeeded'
        ? isSampleProvider
          ? '实验 provider 已生成结果，可用于联调与界面验收。'
          : jobLayer.message || '工作流结果已生成。'
        : jobLayer.status === 'failed'
          ? (jobLayer.diagnosticNotes?.[0] ?? '数据加载失败')
          : jobLayer.message || '正在加载工作流结果...',
    observationTimeLabel:
      jobLayer.reportSummary?.match(/\d{2}:\d{2}/)?.[0] ?? formatClockLabel(jobLayer.updatedAt),
    missingFieldsLabel:
      jobLayer.status === 'succeeded'
        ? '无缺失字段'
        : (jobLayer.diagnosticNotes?.join(' / ') ?? '待加载'),
    hotspots: extractLayerHotspots(layer, item, metricValue),
  }
}

// 事件增量消费主循环：高频拉取事件，低频同步权威状态。
const EVENT_POLL_ACTIVE_INTERVAL_MS = 1200
const EVENT_POLL_IDLE_INTERVAL_MS = 2600
const STATUS_SYNC_INTERVAL_MS = 9000
/** 无新事件且状态同步后仍非终态时，才判为“事件等待超时”。长批（omega_sf 等）可数小时。 */
const EVENT_POLL_IDLE_TIMEOUT_MS = 30 * 60_000
const MAX_EVENT_MESSAGE_COUNT = 5
const MAX_CONSECUTIVE_POLL_ERRORS = 3
/** 刷新后恢复用：记住本机跟踪中的 run，避免仅依赖内存态丢失进度。 */
const TRACKED_RUNS_STORAGE_KEY = 'geo:tracked-workflow-runs:v1'

interface TrackedWorkflowRun {
  runId: string
  catalogId: string
  name?: string
  updatedAt: string
  groupId?: string
  memberCatalogIds?: string[]
}

function loadTrackedWorkflowRuns(): TrackedWorkflowRun[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(TRACKED_RUNS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (item): item is TrackedWorkflowRun =>
        !!item && typeof item.runId === 'string' && typeof item.catalogId === 'string',
    )
  } catch {
    return []
  }
}

function saveTrackedWorkflowRuns(runs: TrackedWorkflowRun[]) {
  if (typeof window === 'undefined') return
  try {
    // Keep recent 40 entries
    window.localStorage.setItem(TRACKED_RUNS_STORAGE_KEY, JSON.stringify(runs.slice(0, 40)))
  } catch {
    // ignore quota errors
  }
}

/** Normalize workflow/node progress to 0–100, preferring chunk ratios when available. */
function normalizeWorkflowProgress(
  raw: number | null | undefined,
  detail?: {
    chunksDone?: number
    chunksTotal?: number
    pixelsDone?: number
    pixelsTotal?: number
  } | null,
): number {
  let pct = 0
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    pct = raw >= 0 && raw <= 1 ? raw * 100 : raw
  }
  if (
    detail &&
    typeof detail.chunksTotal === 'number' &&
    detail.chunksTotal > 0 &&
    typeof detail.chunksDone === 'number' &&
    Number.isFinite(detail.chunksDone)
  ) {
    pct = Math.max(pct, (detail.chunksDone / detail.chunksTotal) * 100)
  } else if (
    detail &&
    typeof detail.pixelsTotal === 'number' &&
    detail.pixelsTotal > 0 &&
    typeof detail.pixelsDone === 'number' &&
    Number.isFinite(detail.pixelsDone)
  ) {
    pct = Math.max(pct, (detail.pixelsDone / detail.pixelsTotal) * 100)
  }
  return Math.max(0, Math.min(100, Math.round(pct)))
}
function getCatalogDisplayName(catalogId: string) {
  return LAYER_LIBRARY.find((item) => item.catalogId === catalogId)?.name ?? catalogId
}

function isBlockedRunReadiness(readiness?: string | null) {
  return readiness === 'blocked'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function isRecognizedJobStatus(status: unknown): status is JobStatus {
  return (
    typeof status === 'string' &&
    ['running', 'succeeded', 'failed', 'queued', 'cancelled', 'retry_pending'].includes(status)
  )
}

function formatHotspotValue(value: unknown, unit?: unknown) {
  const unitLabel = typeof unit === 'string' ? unit : ''
  if (typeof value === 'number') {
    const text = Number.isInteger(value) ? String(value) : value.toFixed(2)
    return `${text}${unitLabel}`
  }
  if (typeof value === 'string' && value.trim()) {
    return `${value}${unitLabel}`
  }
  return '--'
}

function buildHotspotFromFeature(
  feature: Record<string, unknown> | null,
  fallbackId: string,
  fallbackName: string,
  fallbackValue: string,
): LayerHotspot | null {
  const geometry = asRecord(feature?.geometry)
  const coordinates = Array.isArray(geometry?.coordinates) ? geometry.coordinates : null
  const lng = coordinates && coordinates.length >= 2 ? asNumber(coordinates[0]) : null
  const lat = coordinates && coordinates.length >= 2 ? asNumber(coordinates[1]) : null
  if (lng === null || lat === null) {
    return null
  }

  const properties = asRecord(feature?.properties)
  const pointValue = formatHotspotValue(properties?.value, properties?.unit)
  return {
    id: typeof properties?.id === 'string' && properties.id.trim() ? properties.id : fallbackId,
    name:
      (typeof properties?.place_name === 'string' && properties.place_name.trim()) ||
      (typeof properties?.name === 'string' && properties.name.trim()) ||
      fallbackName,
    lng,
    lat,
    value: pointValue !== '--' ? pointValue : fallbackValue,
  }
}

function extractLayerHotspots(
  layer: ActiveLayer,
  item: RuntimeLayerLibraryItem,
  metricValue: string,
): LayerHotspot[] {
  const jobLayer = layer.jobLayer
  if (!jobLayer) return []

  const pointFeature = asRecord(jobLayer.mapLayerPayload?.pointFeature)
  const pointHotspot = buildHotspotFromFeature(
    pointFeature,
    `${layer.catalogId}-primary`,
    item.name,
    metricValue,
  )
  if (pointHotspot) {
    return [pointHotspot]
  }

  const resultDto = asRecord(jobLayer.resultDto)
  const metadata = asRecord(resultDto?.metadata)
  const latitude = asNumber(metadata?.latitude)
  const longitude = asNumber(metadata?.longitude)
  if (latitude === null || longitude === null) {
    return []
  }

  return [
    {
      id: `${layer.catalogId}-metadata`,
      name: (typeof metadata?.place_name === 'string' && metadata.place_name.trim()) || item.name,
      lng: longitude,
      lat: latitude,
      value: metricValue,
    },
  ]
}

function mergeRecentEventMessages(existing: string[] | undefined, incoming: WorkflowEvent[]) {
  const merged = [...(existing ?? [])]
  for (const event of incoming) {
    const text = formatWorkflowEventLine(event.channel, event.message)
    if (merged[merged.length - 1] !== text) {
      merged.push(text)
    }
  }
  return merged.slice(-MAX_EVENT_MESSAGE_COUNT)
}

function hasRenderableMapLayerAsset(jobLayer: JobLayerItem | null | undefined) {
  const assets = jobLayer?.mapLayerPayload?.layerAssets
  return Boolean(
    assets?.geojsonData ||
    assets?.geojsonUrl ||
    assets?.cogUrl ||
    assets?.cogPreviewUrl ||
    assets?.overlayLayerId,
  )
}

const STATIC_LIBRARY_BY_ID = new Map(LAYER_LIBRARY.map((item) => [item.catalogId, item]))
const CATEGORY_INDEX_BY_ID = new Map(
  LAYER_CATEGORIES.map((category, index) => [category.id, index]),
)

function getStaticLayerLibraryItem(catalogId: string) {
  return STATIC_LIBRARY_BY_ID.get(catalogId)
}

function formatClockLabel(value?: string | null) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function resolveCategory(descriptor: RuntimeLayerDescriptor, fallbackCategory?: string) {
  const category = descriptor.category || fallbackCategory
  if (category && CATEGORY_INDEX_BY_ID.has(category)) {
    return category
  }
  return fallbackCategory ?? 'research-group'
}

function buildUpdateLabel(
  descriptor: RuntimeLayerDescriptor,
  fallback?: Pick<LayerCatalogItem, 'updateLabel'> | null,
) {
  if (fallback?.updateLabel) return fallback.updateLabel
  if (descriptor.status === 'sample') return '实验工作流'
  if (descriptor.is_realtime) return '实时更新'
  if (descriptor.supports_time) return '按时间维度'
  if (descriptor.status === 'placeholder') return '占位图层'
  return descriptor.engine ? '按工作流运行' : '按需加载'
}

function buildSourceLabel(
  descriptor: RuntimeLayerDescriptor,
  fallback?: Pick<LayerCatalogItem, 'sourceLabel'> | null,
) {
  if (fallback?.sourceLabel) return fallback.sourceLabel
  const sourceType = descriptor.source_type || 'runtime'
  const engine = descriptor.engine ? ` · ${descriptor.engine}` : ''
  return `${sourceType}${engine}`
}

function buildRuntimeLayerLibraryItem(descriptor: RuntimeLayerDescriptor): RuntimeLayerLibraryItem {
  const fallback = getStaticLayerLibraryItem(descriptor.layer_id)
  const category = resolveCategory(descriptor, fallback?.category)
  const categoryMeta = LAYER_CATEGORIES.find((item) => item.id === category)
  const descriptorSub =
    typeof (descriptor as { sub_category?: string | null }).sub_category === 'string'
      ? (descriptor as { sub_category?: string }).sub_category
      : undefined
  const subCategory =
    (descriptorSub as RuntimeLayerLibraryItem['subCategory'] | undefined) ?? fallback?.subCategory

  return {
    catalogId: descriptor.layer_id,
    name: descriptor.display_name,
    category,
    subCategory,
    description: descriptor.description,
    metricLabel: fallback?.metricLabel ?? '主指标',
    metricUnit: fallback?.metricUnit ?? '',
    metricPrecision: fallback?.metricPrecision ?? 1,
    updateLabel: buildUpdateLabel(descriptor, fallback ?? null),
    sourceLabel: buildSourceLabel(descriptor, fallback ?? null),
    accentColor: fallback?.accentColor ?? categoryMeta?.accentColor ?? '#67d4ff',
    accentGlow: fallback?.accentGlow ?? 'rgba(103, 212, 255, 0.28)',
    chipTone: fallback?.chipTone ?? categoryMeta?.chipTone ?? 'rgba(103, 212, 255, 0.16)',
    sources: fallback?.sources ?? [],
    isAdminBoundary: fallback?.isAdminBoundary,
    engine: descriptor.engine,
    sourceType: descriptor.source_type,
    renderType: descriptor.render_type,
    workflowName: descriptor.workflow_name,
    runReadiness: descriptor.run_readiness ?? 'ready',
    runReadinessSummary: descriptor.run_readiness_summary,
    runReadinessNotes: descriptor.run_readiness_notes ?? [],
    backendStatus: descriptor.status,
    defaultVisible: descriptor.default_visible,
    supportsTime: descriptor.supports_time,
  }
}

function buildCatalogFallbackItem(
  item: RuntimeLayerLibraryItem | null,
  catalogId: string,
): RuntimeLayerLibraryItem {
  if (item) return item
  const fallback = getStaticLayerLibraryItem(catalogId)
  if (fallback) {
    return {
      ...fallback,
      description: `${fallback.name} 课题组数据信息尚未返回。`,
      runReadiness: 'unknown',
      runReadinessSummary: '课题组数据加载中',
      runReadinessNotes: [],
      backendStatus: null,
      engine: null,
      sourceType: null,
      renderType: null,
      workflowName: null,
      defaultVisible: undefined,
      supportsTime: undefined,
    }
  }

  return {
    catalogId,
    name: catalogId,
    category: 'research-group',
    description: '课题组数据尚未收录该图层。',
    metricLabel: '主指标',
    metricUnit: '',
    metricPrecision: 1,
    updateLabel: '待识别',
    sourceLabel: '课题组数据',
    accentColor: '#5a6a80',
    accentGlow: 'rgba(90, 106, 128, 0.3)',
    chipTone: 'rgba(90, 106, 128, 0.16)',
    sources: [],
    runReadiness: 'unknown',
    runReadinessSummary: '课题组数据加载中',
    runReadinessNotes: [],
    backendStatus: null,
    engine: null,
    sourceType: null,
    renderType: null,
    workflowName: null,
    defaultVisible: undefined,
    supportsTime: undefined,
  }
}

function buildAvailabilityState(
  layer: ActiveLayer,
  item: RuntimeLayerLibraryItem,
  jobLayer?: JobLayerItem,
) {
  if (jobLayer) {
    if (jobLayer.status === 'succeeded') {
      return {
        state: 'ready' as const,
        label: '完整数据',
        description: jobLayer.reportSummary ?? jobLayer.message ?? '工作流结果已生成。',
      }
    }
    if (jobLayer.status === 'running') {
      return {
        state: 'partial' as const,
        label: '运行中',
        description: jobLayer.message || '正在生成最新结果。',
      }
    }
    if (jobLayer.status === 'queued' || jobLayer.status === 'retry_pending') {
      return {
        state: 'partial' as const,
        label: jobLayer.status === 'queued' ? '排队中' : '等待重试',
        description: jobLayer.message || '任务已提交，等待后端调度。',
      }
    }
    if (jobLayer.status === 'failed') {
      return {
        state: 'empty' as const,
        label: '数据异常',
        description: jobLayer.diagnosticNotes?.[0] ?? jobLayer.message ?? '工作流执行失败。',
      }
    }
    if (jobLayer.status === 'cancelled') {
      return {
        state: 'empty' as const,
        label: '已取消',
        description: jobLayer.message || '工作流已取消。',
      }
    }
  }

  if (isBlockedRunReadiness(item.runReadiness)) {
    return {
      state: 'empty' as const,
      label: '数据未就绪',
      description: item.runReadinessSummary ?? item.runReadinessNotes[0] ?? '默认数据源尚未就绪。',
    }
  }

  if (item.backendStatus === 'sample') {
    return {
      state: 'partial' as const,
      label: '实验可运行',
      description:
        item.runReadinessSummary ??
        item.runReadinessNotes[0] ??
        '当前为实验 provider 链路，可用于算法联调与验收。',
    }
  }

  if (item.backendStatus === 'placeholder') {
    return {
      state: 'partial' as const,
      label: '占位图层',
      description: item.description || '该图层当前仍为占位产物，待数据源接入。',
    }
  }

  return {
    state: layer.dataState === 'real' ? ('partial' as const) : ('empty' as const),
    label: layer.dataState === 'real' ? '等待结果' : '待运行',
    description: item.runReadinessSummary ?? '图层已加入工作区，可按需运行工作流。',
  }
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useLayersStore = defineStore('layers', () => {
  const weatherTileManager = useWeatherTileManager()
  const uiStore = useUiStore()
  const weatherSourcePrefs = useWeatherSourcePrefsStore()

  /** Resolve tile manager provider arg (always explicit: auto | provider_id). */
  function weatherProviderArg(catalogId: string): string {
    return weatherSourcePrefs.getProvider(catalogId) || 'auto'
  }

  /** Query param for APIs; undefined when auto so backend uses registry priority. */
  function weatherProviderQuery(catalogId: string): string | undefined {
    return weatherSourcePrefs.getProviderQuery(catalogId)
  }

  // ── Active layers (已添加的图层实例) ──────────────────────────────────────
  const activeLayers = ref<ActiveLayer[]>([])
  const runLayerGroups = ref<ActiveRunLayerGroup[]>([])

  // ── Sidebar view mode ────────────────────────────────────────────────────
  const sidebarView = ref<LayerSidebarView>('empty')

  // ── Selected instance ID (点击某个已添加图层时在 InfoPanel 展示详情) ──────
  const selectedInstanceId = ref<string | null>(null)

  // ── Job layers (作业生产数据，从后端 workflow 拉取) ─────────────────────────
  const jobLayers = ref<JobLayerItem[]>([])

  // ── Current hour (用于工作流提交与时间轴状态展示) ─────────────────────────────
  const currentHour = ref(12)
  const workflowError = ref<string | null>(null)
  const workflowPollingHandles = new Map<string, number>()
  const workflowLastStatusSyncAt = new Map<string, number>()
  const activeWorkflowCatalogIds = new Set<string>()
  const submittingCatalogIds = new Set<string>()
  const isSubmitting = computed(() => submittingCatalogIds.size > 0)

  // ── 429 容量限制自动重试（业务 workflow 池）────────────────────────────
  // 后端 business 池默认 max_active_runs=8；天气瓦片热路径走 /weather/tiles，不占此池。
  // 显式 weather_tile_render workflow 使用独立的 max_active_weather_tile_runs。
  // 这里记录重试定时器和次数，business 池 429 时创建 queued jobLayer 并自动重试。
  const workflowRetryTimers = new Map<string, number>()
  const workflowRetryCounts = new Map<string, number>()
  const MAX_WORKFLOW_429_RETRIES = 6
  const WORKFLOW_429_RETRY_DELAY_MS = 3000

  /** 运行中 node_progress.timeKey → 时间轴自动 seek（DashboardView 消费） */
  const workflowProgressTimeSeek = ref<WorkflowProgressTimeSeekHint | null>(null)
  let lastWorkflowTimeSeekToken = ''

  function emitWorkflowProgressTimeSeek(
    jobLayer: JobLayerItem,
    status: JobLayerItem['status'],
    detail: { timeKey?: string; dateStart?: string; dateEnd?: string; phase?: string } | undefined,
  ) {
    if (status !== 'running') return
    const phase = detail?.phase
    if (phase !== 'block_commit' && phase !== 'block_refresh' && phase !== 'artifact') return
    const timeKey = detail?.timeKey || detail?.dateStart
    if (!timeKey || !jobLayer.catalogId) return
    const token = `${jobLayer.jobId}:${timeKey}`
    if (token === lastWorkflowTimeSeekToken) return
    lastWorkflowTimeSeekToken = token
    const target = timelineTargetFromWorkflowTimeKey(timeKey, detail?.dateEnd)
    if (!target) return
    workflowProgressTimeSeek.value = {
      runId: jobLayer.jobId,
      catalogId: jobLayer.catalogId,
      timeKey,
      sliceLabel: target.sliceLabel,
      at: new Date().toISOString(),
    }
  }

  // ── 工作流全局状态汇总 ─────────────────────────────────────────────────
  const workflowSummary = computed<WorkflowSummary>(() => {
    const layers = jobLayers.value
    if (layers.length === 0) {
      return {
        total: 0,
        running: 0,
        queued: 0,
        succeeded: 0,
        failed: 0,
        cancelled: 0,
        retryPending: 0,
        overall: 'idle',
        tone: 'idle',
        hasError: false,
      }
    }
    const counts = {
      running: 0,
      queued: 0,
      succeeded: 0,
      failed: 0,
      cancelled: 0,
      retry_pending: 0,
    }
    for (const layer of layers) {
      if (layer.status in counts) counts[layer.status as keyof typeof counts]++
    }
    const active = counts.running + counts.queued + counts.retry_pending
    let overall: WorkflowSummary['overall'] = 'idle'
    let tone: WorkflowSummary['tone'] = 'idle'
    if (active > 0) {
      overall = 'active'
      tone = 'active'
    } else if (counts.failed > 0 && counts.succeeded > 0) {
      overall = 'mixed'
      tone = 'warning'
    } else if (counts.failed > 0) {
      overall = 'failed'
      tone = 'error'
    } else if (counts.succeeded > 0) {
      overall = 'succeeded'
      tone = 'success'
    }
    return {
      total: layers.length,
      running: counts.running,
      queued: counts.queued,
      succeeded: counts.succeeded,
      failed: counts.failed,
      cancelled: counts.cancelled,
      retryPending: counts.retry_pending,
      overall,
      tone,
      hasError: !!workflowError.value || counts.failed > 0,
    }
  })

  const runtimeLayerCatalog = ref<Record<string, RuntimeLayerDescriptor>>({})
  const runtimeLayerCatalogLoading = ref(false)
  let runtimeLayerCatalogRequest: Promise<void> | null = null

  // 风场三态 + 地图视口 + 双 debounce：见 weather-viewport.ts
  const weatherViewport = createWeatherViewportSlice({
    getActiveLayers: () => activeLayers.value,
    isWeatherEngineLayer: (catalogId) => isWeatherEngineLayer(catalogId),
    supportsViewportDrivenRefresh: (catalogId) => supportsViewportDrivenRefresh(catalogId),
    getCurrentHour: () => currentHour.value,
    weatherProviderArg,
    setWeatherTileViewport: (catalogId, center, zoom, hour, model, bbox, provider) => {
      weatherTileManager.setViewport(catalogId, center, zoom, hour, model, bbox, provider)
    },
    onWorkflowViewportRefresh: (epoch) => {
      void refreshActiveWeatherWorkflows(epoch)
    },
    debugLog,
  })
  const {
    particleFlowCatalogId,
    windDisplayMode,
    currentMapCenter,
    currentMapBBox,
    currentMapZoom,
    smoothRendering,
    setWindDisplayMode,
    toggleParticleFlow,
    setParticleFlow,
    clearWindForCatalog,
    enableParticleIfUnset,
    setSmoothRendering,
    isViewportRefreshStale,
    getViewportRefreshEpoch,
    handleViewportChange,
    setMapViewport,
    flushWeatherTileViewports,
  } = weatherViewport

  const layerLibrary = computed<RuntimeLayerLibraryItem[]>(() => {
    const runtimeItems = Object.values(runtimeLayerCatalog.value).map((descriptor) =>
      buildRuntimeLayerLibraryItem(descriptor),
    )
    const items =
      runtimeItems.length > 0
        ? runtimeItems
        : LAYER_LIBRARY.filter((item) => !item.isAdminBoundary).map((item) =>
            buildCatalogFallbackItem(null, item.catalogId),
          )

    // 合并工作流产出图层（前端本地注册表）
    const outputStore = useWorkflowOutputLayersStore()
    const outputItems: RuntimeLayerLibraryItem[] = outputStore.entries.map((entry) => ({
      catalogId: entry.localId,
      name: entry.name,
      category: 'workflow-output',
      metricLabel: '产出',
      metricUnit: '',
      metricPrecision: 1,
      updateLabel: '工作流驱动',
      sourceLabel: `工作流: ${entry.sourceWorkflowId}`,
      accentColor: '#ffb84d',
      accentGlow: 'rgba(255, 184, 77, 0.28)',
      chipTone: 'rgba(255, 184, 77, 0.16)',
      sources: [],
      description: `分组: ${entry.group} · 源图层: ${entry.sourceLayerId}`,
      engine: entry.engine,
      workflowName: entry.name,
      runReadiness: 'ready',
      runReadinessSummary: '工作流产出图层，可运行源工作流刷新数据',
      runReadinessNotes: [],
      backendStatus: 'sample',
      supportsTime: false,
    }))

    // 行政边界不作为数据集目录展示；无数据源的空壳条目也不展示
    const isDatasetLibraryItem = (item: RuntimeLayerLibraryItem) =>
      item.category !== 'boundary' &&
      !item.isAdminBoundary &&
      item.catalogId !== 'admin-boundary' &&
      item.catalogId !== 'admin-boundary-cn' &&
      item.catalogId !== 'smap-soil'

    return items
      .concat(outputItems)
      .filter(isDatasetLibraryItem)
      .sort((a, b) => {
        const categoryOrderA = CATEGORY_INDEX_BY_ID.get(a.category) ?? Number.MAX_SAFE_INTEGER
        const categoryOrderB = CATEGORY_INDEX_BY_ID.get(b.category) ?? Number.MAX_SAFE_INTEGER
        if (categoryOrderA !== categoryOrderB) {
          return categoryOrderA - categoryOrderB
        }
        return a.name.localeCompare(b.name, 'zh-CN')
      })
  })

  const layerLibraryMap = computed(
    () => new Map(layerLibrary.value.map((item) => [item.catalogId, item])),
  )

  const activeLayersDisplay = computed<ActiveLayerDisplay[]>(() => {
    return activeLayers.value
      .slice()
      .filter((layer) => !layer.isAdminBoundary && layer.catalogId !== 'admin-boundary')
      .sort((a, b) => b.order - a.order)
      .map((layer): ActiveLayerDisplay | null => {
        if (layer.importedVector) {
          const payload = layer.importedVector
          const persisted = resolvePersistedDisplayName(
            layer.catalogId,
            payload.backendLayerId,
            layer.instanceId,
          )
          const displayName = layer.name ?? persisted ?? payload.fileName ?? '导入图层'
          return {
            instanceId: layer.instanceId,
            catalogId: layer.catalogId,
            name: displayName,
            category: 'imported',
            description: `本地导入矢量（${payload.geometryType}）`,
            engine: 'local',
            supportsTime: false,
            runReadiness: 'ready',
            runReadinessSummary: '本地文件已加载',
            summary: `${payload.featureCount} 个要素 · ${payload.geometryType}`,
            metricLabel: '要素数',
            metricValue: String(payload.featureCount),
            trendLabel: '本地矢量叠加',
            statusLabel: '已导入',
            updateLabel: '本地文件',
            sourceLabel: payload.fileName ?? '本地导入',
            confidenceLabel: '本地数据',
            accentColor: layer.accentColor ?? '#7ee0a8',
            accentGlow: layer.accentGlow ?? 'rgba(126, 224, 168, 0.28)',
            chipTone: layer.chipTone ?? 'rgba(126, 224, 168, 0.16)',
            availabilityState: 'ready',
            availabilityLabel: '完整数据',
            availabilityDescription: `已载入 ${payload.featureCount} 个要素，可在图层列表控制显隐与导出。`,
            observationTimeLabel: '本地',
            missingFieldsLabel: '无',
            hotspots: [],
            isAdminBoundary: false,
            isImported: true,
            isImportedRaster: false,
            jobLayer: undefined,
            visible: layer.visible,
            opacity: layer.opacity,
            order: layer.order,
            dataState: 'imported',
            importedGeometryType: payload.geometryType,
            importedFeatureCount: payload.featureCount,
            importedVectorBackendLayerId: payload.backendLayerId,
            importedBounds: payload.bounds,
            importedFileName: payload.fileName,
            importedVectorStyle: payload.style,
          }
        }

        if (layer.importedRaster) {
          const payload = layer.importedRaster
          const displayName =
            layer.name ??
            resolvePersistedDisplayName(
              layer.catalogId,
              payload.overlayLayerId,
              layer.instanceId,
            ) ??
            payload.fileName ??
            '导入栅格'
          const hasTimes = Boolean(payload.timeList?.length)
          return {
            instanceId: layer.instanceId,
            catalogId: layer.catalogId,
            name: displayName,
            category: 'imported',
            description: hasTimes
              ? '科学时间序列栅格（按块 / 时刻）'
              : '本地导入栅格（TIF overlay）',
            engine: 'local',
            supportsTime: hasTimes,
            runReadiness: 'ready',
            runReadinessSummary: '本地栅格已注册',
            summary: hasTimes ? '时间序列栅格叠加' : '本地 TIF 栅格叠加',
            metricLabel: '类型',
            metricValue: '栅格',
            trendLabel: hasTimes ? '科学时间序列' : '本地栅格叠加',
            statusLabel: '已导入',
            updateLabel: '本地文件',
            sourceLabel: payload.fileName ?? '本地导入',
            confidenceLabel: '本地数据',
            accentColor: layer.accentColor ?? '#7eb8e0',
            accentGlow: layer.accentGlow ?? 'rgba(126, 184, 224, 0.28)',
            chipTone: layer.chipTone ?? 'rgba(126, 184, 224, 0.16)',
            availabilityState: 'ready',
            availabilityLabel: hasTimes ? `${payload.timeList!.length} 个时间块` : '完整数据',
            availabilityDescription: hasTimes
              ? '时间序列已注册；底部时间轴按块覆盖日期着色。'
              : '已通过后端注册为 overlay，可在图层列表控制显隐与透明度。',
            observationTimeLabel:
              payload.effectiveTimeLabel ||
              (hasTimes ? payload.timeList![payload.timeList!.length - 1]! : '静态'),
            missingFieldsLabel: '无',
            hotspots: [],
            isAdminBoundary: false,
            isImported: false,
            isImportedRaster: true,
            jobLayer: undefined,
            visible: layer.visible,
            opacity: layer.opacity,
            order: layer.order,
            dataState: 'imported',
            importedRasterBounds: payload.bounds,
            importedBounds: payload.bounds,
            importedRasterSourceCrs: payload.sourceCrs,
            importedRasterNativeStep:
              typeof payload.nativeStep === 'string'
                ? payload.nativeStep
                : payload.nativeStep
                  ? `${payload.nativeStep.value}${payload.nativeStep.unit === 'hour' ? 'h' : payload.nativeStep.unit === 'day' ? 'd' : payload.nativeStep.unit === 'month' ? 'm' : 'yr'}`
                  : undefined,
            importedRasterEffectiveTime: payload.effectiveTimeLabel,
            importedRasterTimeCount: payload.timeList?.length,
            importedFileName: payload.fileName,
            runGroupId: layer.runGroupId,
            runGroupProductTag: layer.runGroupProductTag,
            runGroupLocked: layer.runGroupLocked,
          }
        }

        const item = buildCatalogFallbackItem(
          layerLibraryMap.value.get(layer.catalogId) ?? null,
          layer.catalogId,
        )
        const availability = buildAvailabilityState(layer, item, layer.jobLayer)
        const realDisplay = layer.jobLayer ? buildRealLayerDisplay(layer, item) : {}
        const descriptor = runtimeLayerCatalog.value[layer.catalogId] ?? null

        const isWeatherLayer = !layer.isAdminBoundary && isWeatherEngineLayer(layer.catalogId)
        const tileStats =
          isWeatherLayer && layer.visible ? weatherTileManager.getStats(layer.catalogId) : null
        const baseRenderHint = isWeatherLayer
          ? buildDefaultWeatherRenderHint(layer.catalogId, descriptor)
          : (layer.jobLayer?.mapLayerPayload?.renderHint ?? null)
        // 应用用户自定义配色方案覆盖
        const weatherRenderHint =
          baseRenderHint && layer.paletteOverride
            ? { ...baseRenderHint, palette: layer.paletteOverride }
            : baseRenderHint
        let finalAvailability = availability
        if (isWeatherLayer && tileStats) {
          const layerStatus = weatherTileManager.getLayerStatus(layer.catalogId)
          if (layerStatus.errorType === 'data-empty') {
            finalAvailability = {
              state: 'empty' as const,
              label: '无有效数据',
              description: layerStatus.errorMessage || '本地模型无数据，请同步 Open-Meteo',
            }
          } else if (
            tileStats.cached > 0 &&
            tileStats.cached >= tileStats.visible &&
            tileStats.pending === 0
          ) {
            // 勿在 activeLayersDisplay 热路径调用 getMergedGeojsonForViewport：
            // 同步合并视口瓦片会卡主线程，表现为点「已添加图层」无响应。
            // 无数据场景由上方 data-empty 状态覆盖。
            finalAvailability = {
              state: 'ready' as const,
              label: '完整数据',
              description: `已缓存全部 ${tileStats.visible} 个可视瓦片`,
            }
          } else if (tileStats.cached > 0 || tileStats.pending > 0) {
            finalAvailability = {
              state: 'partial' as const,
              label: '加载中',
              description: `已缓存 ${tileStats.cached} / 可视 ${tileStats.visible} / 加载中 ${tileStats.pending}`,
            }
          } else {
            finalAvailability = {
              state: 'partial' as const,
              label: '等待瓦片',
              description: '正在等待瓦片调度',
            }
          }
        }

        return {
          instanceId: layer.instanceId,
          catalogId: layer.catalogId,
          name: layer.isAdminBoundary
            ? '行政区边界'
            : (layer.name ??
              resolvePersistedDisplayName(layer.catalogId, layer.instanceId) ??
              item.name),
          category: layer.isAdminBoundary ? 'boundary' : item.category,
          description: layer.isAdminBoundary ? '广东省市级行政区边界叠加层。' : item.description,
          engine: layer.isAdminBoundary ? 'builtin' : item.engine,
          supportsTime: item.supportsTime,
          runReadiness: item.runReadiness,
          runReadinessSummary: item.runReadinessSummary,
          renderHint: weatherRenderHint ?? undefined,
          summary: layer.isAdminBoundary
            ? '广东省市级行政区边界叠加层'
            : (realDisplay.summary ?? item.description),
          metricLabel: layer.isAdminBoundary ? '边界层级' : item.metricLabel,
          metricValue: layer.isAdminBoundary ? '省市级' : (realDisplay.metricValue ?? '--'),
          trendLabel: layer.isAdminBoundary
            ? '静态矢量边界叠加'
            : isWeatherLayer
              ? 'tile manager 已接入'
              : (realDisplay.trendLabel ??
                (item.backendStatus === 'sample'
                  ? '实验 provider 链路已接入'
                  : item.supportsTime
                    ? '支持时间维度查询'
                    : '课题组数据已接入')),
          statusLabel: layer.isAdminBoundary
            ? '静态数据'
            : isWeatherLayer
              ? '瓦片数据'
              : (realDisplay.statusLabel ??
                (item.backendStatus === 'sample'
                  ? '实验 Provider'
                  : item.backendStatus === 'placeholder'
                    ? '占位图层'
                    : '目录已接入')),
          updateLabel: layer.isAdminBoundary ? '静态数据' : item.updateLabel,
          sourceLabel: layer.isAdminBoundary
            ? '广东省市级边界'
            : (realDisplay.sourceLabel ?? item.sourceLabel),
          confidenceLabel: layer.isAdminBoundary
            ? '置信度 100%'
            : (realDisplay.confidenceLabel ?? '以课题组数据为准'),
          accentColor: layer.accentColor ?? item.accentColor,
          accentGlow: layer.accentGlow ?? item.accentGlow,
          chipTone: layer.chipTone ?? item.chipTone,
          availabilityState: layer.isAdminBoundary ? 'ready' : finalAvailability.state,
          availabilityLabel: layer.isAdminBoundary ? '完整数据' : finalAvailability.label,
          availabilityDescription: layer.isAdminBoundary
            ? '静态矢量边界数据，已完整加载。'
            : (realDisplay.availabilityDescription ?? finalAvailability.description),
          observationTimeLabel: layer.isAdminBoundary
            ? '静态数据'
            : isWeatherLayer
              ? // 用 ui 钟点，勿用 layersStore.currentHour（0–47 瓦片索引）
                formatClockHourLabel(uiStore.currentHour)
              : (realDisplay.observationTimeLabel ??
                (item.supportsTime ? formatClockHourLabel(uiStore.currentHour) : '--')),
          missingFieldsLabel: layer.isAdminBoundary
            ? '无'
            : (realDisplay.missingFieldsLabel ?? item.runReadinessNotes[0] ?? '无'),
          hotspots: layer.isAdminBoundary ? [] : (realDisplay.hotspots ?? []),
          isAdminBoundary: layer.isAdminBoundary,
          isImported: false,
          isImportedRaster: false,
          jobLayer: layer.jobLayer,
          visible: layer.visible,
          opacity: layer.opacity,
          order: layer.order,
          dataState: layer.dataState,
          paletteOverride: layer.paletteOverride ?? null,
          runGroupId: layer.runGroupId,
          runGroupProductTag: layer.runGroupProductTag,
          runGroupLocked: layer.runGroupLocked,
        }
      })
      .filter((d): d is ActiveLayerDisplay => d !== null)
  })

  const selectedLayerDisplay = computed<ActiveLayerDisplay | null>(() => {
    if (!selectedInstanceId.value) return null
    return activeLayersDisplay.value.find((d) => d.instanceId === selectedInstanceId.value) ?? null
  })

  const activeLayerCount = computed(() => activeLayers.value.length)
  const sidebarViewLabel = computed(() => {
    if (sidebarView.value === 'empty') return '图层'
    if (sidebarView.value === 'library') return '图层库'
    // 数量由右上角 badge 展示，标题不再重复写「图层 (N)」
    return '已添加图层'
  })

  // ─────────────────────────────────────────────────────────────────────────────

  function usedLayerAccentColors(): string[] {
    return activeLayers.value
      .map((l) => l.accentColor)
      .filter((c): c is string => typeof c === 'string' && c.length > 0)
  }

  function assignLayerAccent(preferred?: string | null) {
    return allocateLayerAccent(usedLayerAccentColors(), preferred)
  }

  function addLayer(catalogId: string, isAdminBoundary = false, jobLayer?: JobLayerItem) {
    // 行政边界不再作为可添加数据集
    if (
      isAdminBoundary ||
      catalogId === 'admin-boundary' ||
      catalogId === 'admin-boundary-cn' ||
      catalogId === 'smap-soil'
    ) {
      return
    }

    // 防止重复添加同 catalogId (除非来自不同 job)
    if (!jobLayer) {
      if (
        activeLayers.value.some(
          (l) => l.catalogId === catalogId && !l.jobLayer && !isLocalImport(l),
        )
      ) {
        return
      }
    }

    const libraryItem = layerLibraryMap.value.get(catalogId)
    const accent = assignLayerAccent(libraryItem?.accentColor)
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const layer: ActiveLayer = {
      instanceId: genInstanceId(),
      catalogId,
      visible: true,
      opacity: 1,
      order: maxOrder + 1,
      isAdminBoundary: false,
      jobLayer,
      dataState: jobLayer ? 'real' : 'catalog',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId

    // 仅从空态进入「已添加」；从图层库添加时留在库页，立刻显示「已添加 ✓」
    // （若立刻切走，风场瓦片调度又会卡住主线程，库卡片状态看起来像没加上）
    if (sidebarView.value === 'empty') {
      sidebarView.value = 'active'
    }

    // 天气图层接入瓦片管理器，由 tile manager 按需拉取瓦片。
    // setLayerActive 是轻量操作（仅设置 visible 标志），同步执行以确保
    // overlay watcher 和 map 事件处理器在同一 flush 周期内能看到图层已激活。
    // setViewport 是重操作（计算瓦片 + 入队 + drainQueue），推迟到下一宏任务，
    // 让 Vue 先完成「已添加 ✓」与角标刷新。
    if (isWeatherEngineLayer(catalogId)) {
      weatherTileManager.setLayerActive(catalogId, true)
      const cc = currentMapCenter.value
      const cz = currentMapZoom.value
      const ch = currentHour.value
      const cb = currentMapBBox.value
      nextTick(() => {
        window.setTimeout(() => {
          weatherTileManager.setViewport(
            catalogId,
            cc,
            cz,
            ch,
            undefined,
            cb,
            weatherProviderArg(catalogId),
          )
          if (supportsParticleFlow(catalogId)) {
            enableParticleIfUnset(catalogId)
            if (particleFlowCatalogId.value === catalogId) {
              debugLog('addLayer', 'auto-enable particle flow for', catalogId)
            }
          }
        }, 0)
      })
    }
    scheduleWorkspacePersist()
  }

  /** 将导入矢量添加到活动图层列表（本地解析或后端统一导入） */
  function addImportedVectorLayer(
    name: string,
    geojson: GeoJSON.FeatureCollection,
    options?: { backendLayerId?: string; featureCount?: number; truncated?: boolean },
  ): ActiveLayer {
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const instanceId = genInstanceId()
    const catalogId = options?.backendLayerId || `imported-${instanceId}`
    const payload = buildImportedVectorPayload(geojson, name, {
      backendLayerId: options?.backendLayerId,
      featureCount: options?.featureCount,
    })
    if (options?.truncated) payload.truncated = true
    const accent = assignLayerAccent('#7ee0a8')
    const layer: ActiveLayer = {
      instanceId,
      catalogId,
      name:
        name.replace(
          /\.(geojson|json|shp|zip|rar|csv|xlsx|xls|txt|dbf|shx|prj|cpg|sbn|sbx|qix|tif|tiff|nc|hdf|h5|he5|mat)$/i,
          '',
        ) || name,
      visible: true,
      opacity: 0.85,
      order: maxOrder + 1,
      isAdminBoundary: false,
      importedVector: payload,
      dataState: 'imported',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId
    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
    scheduleWorkspacePersist()
    return layer
  }

  function getImportedVectorGeojson(instanceId: string): GeoJSON.FeatureCollection | null {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    return layer?.importedVector?.geojson ?? null
  }

  function updateImportedVectorGeojson(
    instanceId: string,
    geojson: GeoJSON.FeatureCollection,
    extras?: { featureCount?: number; truncated?: boolean },
  ) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer?.importedVector) return
    layer.importedVector = {
      ...layer.importedVector,
      geojson,
      featureCount: extras?.featureCount ?? geojson.features.length,
      truncated: extras?.truncated ?? layer.importedVector.truncated,
      geometryType: inferGeometryType(geojson),
      bounds: computeBounds(geojson),
    }
  }

  function setImportedVectorStyle(
    instanceId: string,
    style: NonNullable<import('./imported-vector').ImportedVectorPayload['style']>,
  ) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer?.importedVector) return
    layer.importedVector = {
      ...layer.importedVector,
      style: { ...layer.importedVector.style, ...style },
    }
    scheduleWorkspacePersist()
  }

  /** 将后端已注册的 TIF overlay 挂入活动图层列表 */
  function addImportedRasterLayer(
    name: string,
    overlayLayerId: string,
    bounds?: [number, number, number, number],
    options?: {
      sourceCrs?: string
      lngOffset?: number
      latOffset?: number
      nativeStep?: string | null
      timeList?: string[]
      followPolicy?: import('../../utils/temporal-interval').TemporalFollowPolicy
    },
  ): ActiveLayer {
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const instanceId = genInstanceId()
    const payload = buildImportedRasterPayload(overlayLayerId, {
      bounds,
      fileName: name,
      sourceCrs: options?.sourceCrs,
      lngOffset: options?.lngOffset,
      latOffset: options?.latOffset,
      nativeStep: options?.nativeStep,
      timeList: options?.timeList,
      followPolicy: options?.followPolicy,
    })
    const accent = assignLayerAccent('#7eb8e0')
    const layer: ActiveLayer = {
      instanceId,
      // catalogId 与后端 overlay_layer_id 对齐，便于 overlay-image-module 加载
      catalogId: overlayLayerId,
      name: name.replace(/\.(tif|tiff)$/i, '') || name,
      visible: true,
      opacity: 0.7,
      order: maxOrder + 1,
      isAdminBoundary: false,
      importedRaster: payload,
      dataState: 'imported',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId
    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
    scheduleWorkspacePersist()
    return layer
  }

  function maybeDismissWorkflowRun(runId: string | undefined) {
    if (!runId || isLocalSubmitJobId(runId)) return
    const stillReferenced = activeLayers.value.some((l) => {
      if (l.jobLayer?.jobId === runId) return true
      if (!l.runGroupId) return false
      const g = runLayerGroups.value.find((x) => x.groupId === l.runGroupId)
      return g?.runId === runId
    })
    if (!stillReferenced) {
      rememberDismissedLayer({ runId })
      forgetTrackedWorkflowRun(runId)
    }
  }

  function removeLayer(instanceId: string) {
    const idx = activeLayers.value.findIndex((l) => l.instanceId === instanceId)
    if (idx === -1) return
    pendingVisibilitySync.delete(instanceId)
    const layer = activeLayers.value[idx]!
    const groupBeforeRemove = layer.runGroupId
      ? runLayerGroups.value.find((x) => x.groupId === layer.runGroupId)
      : undefined
    const runIdHint = layer.jobLayer?.jobId || groupBeforeRemove?.runId

    if (layer.jobLayer?.jobId) {
      stopWorkflowPolling(layer.jobLayer.jobId)
    }
    const retryTimer = workflowRetryTimers.get(layer.catalogId)
    if (retryTimer !== undefined) {
      window.clearTimeout(retryTimer)
      workflowRetryTimers.delete(layer.catalogId)
    }
    workflowRetryCounts.delete(layer.catalogId)
    if (!layer.isAdminBoundary && !isLocalImport(layer) && isWeatherEngineLayer(layer.catalogId)) {
      weatherTileManager.clearLayer(layer.catalogId)
    }
    const overlayId = layer.importedRaster?.overlayLayerId
    if (overlayId) {
      void deleteImportedRaster(overlayId).catch((err) => {
        console.warn('[layers] deleteImportedRaster failed', overlayId, err)
      })
    }
    const vecBackendId = layer.importedVector?.backendLayerId
    if (vecBackendId) {
      void import('../../services/data-io').then(({ deleteImportedLayer }) =>
        deleteImportedLayer(vecBackendId).catch((err) => {
          console.warn('[layers] deleteImportedLayer failed', vecBackendId, err)
        }),
      )
    }
    rememberDismissedLayer({
      overlayLayerId: overlayId,
      catalogId: isLocalImport(layer) ? undefined : layer.catalogId,
      vectorBackendLayerId: layer.importedVector?.backendLayerId,
      runId: undefined,
    })

    clearWindForCatalog(layer.catalogId)
    if (layer.runGroupId) {
      const g = runLayerGroups.value.find((x) => x.groupId === layer.runGroupId)
      if (g) {
        g.memberInstanceIds = g.memberInstanceIds.filter((id) => id !== instanceId)
        if (!g.memberInstanceIds.length) {
          runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== g.groupId)
        }
      }
    }
    activeLayers.value.splice(idx, 1)

    if (selectedInstanceId.value === instanceId) {
      selectedInstanceId.value = activeLayers.value[0]?.instanceId ?? null
    }
    maybeDismissWorkflowRun(runIdHint)
    flushWorkspacePersistNow()
  }

  /** 同帧内多次显隐：只把最终 visible 同步给 tile manager，避免狂点冲刷 generation */
  const pendingVisibilitySync = new Map<string, ActiveLayer>()
  let visibilitySyncRaf: number | null = null

  function flushVisibilitySyncToTileManager() {
    visibilitySyncRaf = null
    const layers = Array.from(pendingVisibilitySync.values())
    pendingVisibilitySync.clear()
    for (const layer of layers) {
      if (layer.isAdminBoundary) continue
      // 以当前 activeLayers 中的真实状态为准，防止 flush 前图层已被移除
      const live = activeLayers.value.find((item) => item.instanceId === layer.instanceId)
      if (!live) {
        if (!isLocalImport(layer) && isWeatherEngineLayer(layer.catalogId)) {
          weatherTileManager.clearLayer(layer.catalogId)
        }
        continue
      }
      if (isLocalImport(live)) continue
      if (!isWeatherEngineLayer(live.catalogId)) {
        weatherTileManager.clearLayer(live.catalogId)
        continue
      }
      weatherTileManager.setLayerActive(live.catalogId, live.visible)
      if (live.visible && isWeatherEngineLayer(live.catalogId)) {
        weatherTileManager.setViewport(
          live.catalogId,
          currentMapCenter.value,
          currentMapZoom.value,
          currentHour.value,
          undefined,
          currentMapBBox.value,
          weatherProviderArg(live.catalogId),
        )
      }
    }
  }

  function scheduleVisibilitySyncToTileManager(layer: ActiveLayer) {
    pendingVisibilitySync.set(layer.instanceId, layer)
    if (visibilitySyncRaf !== null) return
    visibilitySyncRaf = globalThis.requestAnimationFrame(() => {
      flushVisibilitySyncToTileManager()
    })
  }

  function toggleLayerVisibility(instanceId: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    layer.visible = !layer.visible
    scheduleVisibilitySyncToTileManager(layer)
    scheduleWorkspacePersist()
  }

  /** 批量设置所有图层可见性 */
  function setAllLayerVisibility(visible: boolean) {
    // 批量操作立即同步：取消同帧 toggle 排队，避免顺序颠倒
    if (visibilitySyncRaf !== null) {
      globalThis.cancelAnimationFrame(visibilitySyncRaf)
      visibilitySyncRaf = null
    }
    pendingVisibilitySync.clear()
    for (const layer of activeLayers.value) {
      layer.visible = visible
      if (layer.isAdminBoundary || isLocalImport(layer)) continue
      if (!isWeatherEngineLayer(layer.catalogId)) {
        if (visible) continue
        weatherTileManager.clearLayer(layer.catalogId)
        continue
      }
      weatherTileManager.setLayerActive(layer.catalogId, visible)
      if (visible && isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.setViewport(
          layer.catalogId,
          currentMapCenter.value,
          currentMapZoom.value,
          currentHour.value,
          undefined,
          currentMapBBox.value,
          weatherProviderArg(layer.catalogId),
        )
      }
    }
    scheduleWorkspacePersist()
  }

  /** 批量移除所有图层 */
  function removeAllLayers(_keepBoundary = false) {
    if (visibilitySyncRaf !== null) {
      globalThis.cancelAnimationFrame(visibilitySyncRaf)
      visibilitySyncRaf = null
    }
    pendingVisibilitySync.clear()
    const layersToRemove = [...activeLayers.value]
    const removedJobIds = layersToRemove
      .map((layer) => layer.jobLayer?.jobId)
      .filter((jobId): jobId is string => Boolean(jobId))
    for (const jobId of removedJobIds) {
      stopWorkflowPolling(jobId)
    }
    // 清理所有 429 重试定时器
    for (const timer of workflowRetryTimers.values()) {
      window.clearTimeout(timer)
    }
    workflowRetryTimers.clear()
    workflowRetryCounts.clear()
    for (const layer of layersToRemove) {
      rememberDismissedLayer({
        overlayLayerId: layer.importedRaster?.overlayLayerId,
        catalogId: isLocalImport(layer) ? undefined : layer.catalogId,
        vectorBackendLayerId: layer.importedVector?.backendLayerId,
        runId: layer.jobLayer?.jobId,
      })
      if (!isLocalImport(layer) && isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.clearLayer(layer.catalogId)
      }
      clearWindForCatalog(layer.catalogId)
      activeWorkflowCatalogIds.delete(layer.catalogId)
      if (layer.jobLayer?.jobId) forgetTrackedWorkflowRun(layer.jobLayer.jobId)
    }
    activeLayers.value = []
    runLayerGroups.value = []
    selectedInstanceId.value = null
    saveTrackedWorkflowRuns([])
    flushWorkspacePersistNow()
  }

  function setLayerOpacity(instanceId: string, opacity: number) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.opacity = Math.max(0, Math.min(1, opacity))
      scheduleWorkspacePersist()
    }
  }

  /** 设置图层配色方案覆盖（null 恢复为默认配色） */
  function setLayerPaletteOverride(instanceId: string, palette: string | null) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.paletteOverride = palette
    }
  }

  function setLayerOrder(instanceId: string, newOrder: number) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.order = newOrder
      scheduleWorkspacePersist()
    }
  }

  /** 覆盖图层显示名（导入层 / 工作流输出等），并同步持久化与关联状态 */
  function setLayerDisplayName(instanceId: string, name: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    const trimmed = name.trim()
    if (!trimmed) return
    layer.name = trimmed

    // 同步导入载荷上的展示名（导出文件名 / 源标签 / 图例）
    if (layer.importedVector) {
      layer.importedVector = { ...layer.importedVector, fileName: trimmed }
    }
    if (layer.importedRaster) {
      layer.importedRaster = { ...layer.importedRaster, fileName: trimmed }
    }

    const keys = new Set<string>()
    keys.add(layer.catalogId)
    keys.add(layer.instanceId)
    if (layer.importedVector?.backendLayerId) {
      keys.add(layer.importedVector.backendLayerId)
    }
    if (layer.importedRaster?.overlayLayerId) {
      keys.add(layer.importedRaster.overlayLayerId)
    }
    for (const key of keys) {
      persistLayerDisplayName(key, trimmed)
    }

    // 同步 jobLayers / 运行跟踪名（分析面板、状态条）
    if (layer.jobLayer) {
      layer.jobLayer = { ...layer.jobLayer, name: trimmed }
    }
    for (const job of jobLayers.value) {
      if (job.catalogId === layer.catalogId || job.jobId === layer.jobLayer?.jobId) {
        job.name = trimmed
      }
    }

    // 同步工作流产出注册表（图层面板库）
    if (layer.catalogId.startsWith('wf-out-')) {
      try {
        useWorkflowOutputLayersStore().renameOutputLayer(layer.catalogId, trimmed)
      } catch {
        /* store may be unavailable in tests */
      }
    }

    // 通知地图矢量弹窗标题刷新
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('cgda:layer-renamed', {
          detail: { instanceId, catalogId: layer.catalogId, name: trimmed },
        }),
      )
    }

    // 导入图层：异步写回后端 meta.display_name（失败不影响本地）
    const backendId =
      layer.importedVector?.backendLayerId ||
      layer.importedRaster?.overlayLayerId ||
      (layer.catalogId.startsWith('imported-') ? layer.catalogId : null)
    if (backendId) {
      void import('../../data-manager/core/api')
        .then(({ renameImportedLayerDisplayName }) =>
          renameImportedLayerDisplayName(backendId, trimmed),
        )
        .catch(() => undefined)
    }
    scheduleWorkspacePersist()
  }

  /** 置顶：order = max+1 */
  function bringLayerToFront(instanceId: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    layer.order = maxOrder + 1
    scheduleWorkspacePersist()
  }

  /** 置底：order = min-1 */
  function sendLayerToBack(instanceId: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    const minOrder = activeLayers.value.reduce((min, l) => Math.min(min, l.order), 0)
    layer.order = minOrder - 1
    scheduleWorkspacePersist()
  }

  function selectLayer(instanceId: string | null) {
    selectedInstanceId.value = instanceId
  }

  function setSidebarView(view: LayerSidebarView) {
    sidebarView.value = view
  }

  function setCurrentHour(hour: number) {
    currentHour.value = hour
  }

  function getRuntimeLayerDescriptor(catalogId: string) {
    return runtimeLayerCatalog.value[catalogId] ?? null
  }

  /**
   * 对于工作流产出图层（catalogId 以 wf-out- / wf-run- 为前缀），返回其源 layer_id；
   * 普通图层则返回自身 catalogId。用于后端提交时解析引擎请求。
   */
  function resolveBackendLayerId(catalogId: string): string {
    if (catalogId.startsWith('wf-out-')) {
      const outputStore = useWorkflowOutputLayersStore()
      const entry = outputStore.getByLocalId(catalogId)
      return entry?.sourceLayerId ?? catalogId
    }
    if (catalogId.startsWith('wf-run-')) {
      const layer = activeLayers.value.find((l) => l.catalogId === catalogId)
      if (layer?.runGroupId) {
        const g = runLayerGroups.value.find((x) => x.groupId === layer.runGroupId)
        if (g?.sourceLayerId) return g.sourceLayerId
      }
    }
    return catalogId
  }

  /**
   * 对于工作流产出图层，返回其源图层的 descriptor（用于能力判断）；
   * 普通图层则返回自身 descriptor。
   */
  function resolveEffectiveDescriptor(catalogId: string): RuntimeLayerDescriptor | null {
    if (catalogId.startsWith('wf-out-') || catalogId.startsWith('wf-run-')) {
      const backendId = resolveBackendLayerId(catalogId)
      return getRuntimeLayerDescriptor(backendId)
    }
    return getRuntimeLayerDescriptor(catalogId)
  }

  async function ensureRuntimeLayerCatalog(force = false) {
    if (!force && Object.keys(runtimeLayerCatalog.value).length > 0) {
      return
    }
    if (runtimeLayerCatalogRequest && !force) {
      return runtimeLayerCatalogRequest
    }

    runtimeLayerCatalogLoading.value = true
    runtimeLayerCatalogRequest = fetchLayerCatalog()
      .catch(async (error) => {
        const message = error instanceof Error ? error.message : String(error)
        const shouldRetry = /AbortError|aborted without reason|Failed to fetch|NetworkError/i.test(
          message,
        )
        if (!shouldRetry) {
          throw error
        }
        await new Promise((resolve) => window.setTimeout(resolve, 250))
        return fetchLayerCatalog()
      })
      .then((response) => {
        runtimeLayerCatalog.value = Object.fromEntries(
          response.items.map((item) => [item.layer_id, item]),
        )
        reconcileActiveWeatherLayers()
      })
      .catch((error) => {
        // 请求失败时清理状态，避免后续调用返回已拒绝的 Promise
        console.warn(
          '[LayersStore] ensureRuntimeLayerCatalog failed, will retry on next call:',
          error.message,
        )
        runtimeLayerCatalogRequest = null
        throw error
      })
      .finally(() => {
        runtimeLayerCatalogLoading.value = false
        runtimeLayerCatalogRequest = null
      })

    return runtimeLayerCatalogRequest
  }

  /** 可走 /workflow-runs 分析桥的图层引擎（天气瓦片层走 tile manager，不算在内） */
  function getCatalogWorkflowEngine(catalogId: string): string | null {
    const descriptor = getRuntimeLayerDescriptor(catalogId)
    if (descriptor?.engine) return descriptor.engine
    const libItem = layerLibraryMap.value.get(catalogId)
    return libItem?.engine ?? null
  }

  function supportsAnalysisWorkflow(catalogId: string): boolean {
    const backendLayerId = resolveBackendLayerId(catalogId)
    if (isWeatherEngineLayer(backendLayerId) || isWeatherEngineLayer(catalogId)) return false
    return Boolean(getCatalogWorkflowEngine(backendLayerId) || getCatalogWorkflowEngine(catalogId))
  }

  function getCatalogRunBlockReason(catalogId: string) {
    const backendLayerId = resolveBackendLayerId(catalogId)
    if (isWeatherEngineLayer(backendLayerId) || isWeatherEngineLayer(catalogId)) {
      return null
    }
    if (!supportsAnalysisWorkflow(catalogId)) {
      return `${getCatalogDisplayName(catalogId)} 未配置分析工作流引擎（静态叠加请直接加载图层）`
    }

    const descriptor =
      getRuntimeLayerDescriptor(backendLayerId) ?? getRuntimeLayerDescriptor(catalogId)
    if (!descriptor || !isBlockedRunReadiness(descriptor.run_readiness)) {
      return null
    }

    return (
      descriptor.run_readiness_summary ??
      descriptor.run_readiness_notes?.[0] ??
      `${getCatalogDisplayName(catalogId)} 默认数据源未就绪`
    )
  }

  function canRunCatalog(catalogId: string) {
    return !getCatalogRunBlockReason(catalogId)
  }

  function localSubmitJobId(catalogId: string) {
    return `local-submit-${catalogId}`
  }

  function isLocalSubmitJobId(jobId: string | null | undefined): boolean {
    return Boolean(jobId && String(jobId).startsWith('local-submit-'))
  }

  function removeJobLayerById(jobId: string) {
    const idx = jobLayers.value.findIndex((item) => item.jobId === jobId)
    if (idx >= 0) {
      jobLayers.value.splice(idx, 1)
    }
    // 同步清掉活跃图层上挂的同 id jobLayer，避免「排队中」幽灵状态
    for (const layer of activeLayers.value) {
      if (layer.jobLayer?.jobId === jobId) {
        layer.jobLayer = undefined
      }
    }
  }

  /** 按成员 catalog 更新计算组进度（local-submit 阶段 group.runId 尚为空） */
  function updateRunGroupForCatalog(
    catalogId: string,
    job: Pick<JobLayerItem, 'jobId' | 'status' | 'progress' | 'message' | 'nodeProgress'>,
  ) {
    const layer = activeLayers.value.find((l) => l.catalogId === catalogId && l.runGroupId)
    if (!layer?.runGroupId) {
      updateRunGroupFromJob(job.jobId, job)
      return
    }
    const g = runLayerGroups.value.find((x) => x.groupId === layer.runGroupId)
    if (!g) {
      updateRunGroupFromJob(job.jobId, job)
      return
    }
    // 真实 run id 才写入组；local-submit 只更新展示态
    if (!isLocalSubmitJobId(job.jobId) && job.jobId) {
      g.runId = job.jobId
    }
    if (job.status === 'succeeded') g.status = 'ready'
    else if (job.status === 'failed') g.status = 'failed'
    else if (job.status === 'cancelled') g.status = 'cancelled'
    else g.status = 'computing'
    if (typeof job.progress === 'number') g.progress = job.progress
    if (job.message) g.message = job.message
    refreshRunGroupDissolvable(g.groupId)
  }

  function setJobLayers(jobs: JobLayerItem[]) {
    jobLayers.value = jobs
  }

  function stopWorkflowPolling(jobId: string) {
    const handle = workflowPollingHandles.get(jobId)
    if (handle !== undefined) {
      window.clearTimeout(handle)
      workflowPollingHandles.delete(jobId)
    }
    workflowLastStatusSyncAt.delete(jobId)
  }

  function syncJobLayerToActiveLayer(catalogId: string, jobLayer: JobLayerItem) {
    const existingRealLayer = activeLayers.value.find(
      (layer) => layer.jobLayer?.jobId === jobLayer.jobId,
    )
    if (existingRealLayer) {
      existingRealLayer.jobLayer = jobLayer
      existingRealLayer.dataState = 'real'
      return
    }

    const existingCatalogLayer = activeLayers.value.find(
      (layer) => layer.catalogId === catalogId && !layer.isAdminBoundary,
    )
    if (existingCatalogLayer) {
      existingCatalogLayer.jobLayer = jobLayer
      existingCatalogLayer.dataState = 'real'
      // 不在工作流更新时修改 selectedInstanceId，避免视口变化重提交导致图层选中被篡改
      return
    }

    addLayer(catalogId, false, jobLayer)
  }

  function rememberTrackedWorkflowRun(catalogId: string, jobLayer: JobLayerItem) {
    // 乐观提交 ID 不是后端真 run，禁止写入恢复列表（否则会 404 / 误点重试）
    if (isLocalSubmitJobId(jobLayer.jobId)) return
    if (isTerminalStatus(jobLayer.status) && jobLayer.status === 'cancelled') {
      forgetTrackedWorkflowRun(jobLayer.jobId)
      return
    }
    const group = runLayerGroups.value.find((g) => g.runId === jobLayer.jobId)
    const memberCatalogIds = group
      ? group.memberInstanceIds
          .map((id) => activeLayers.value.find((l) => l.instanceId === id)?.catalogId)
          .filter((id): id is string => Boolean(id))
      : undefined
    const existing = loadTrackedWorkflowRuns().filter((item) => item.runId !== jobLayer.jobId)
    existing.unshift({
      runId: jobLayer.jobId,
      catalogId,
      name: jobLayer.name,
      updatedAt: jobLayer.updatedAt || new Date().toISOString(),
      groupId: group?.groupId,
      memberCatalogIds,
    })
    saveTrackedWorkflowRuns(existing)
  }

  function forgetTrackedWorkflowRun(runId: string) {
    saveTrackedWorkflowRuns(loadTrackedWorkflowRuns().filter((item) => item.runId !== runId))
  }

  function upsertJobLayer(catalogId: string, jobLayer: JobLayerItem) {
    // 确保 catalogId 被记录在 jobLayer 上，便于面板列表展示孤儿工作流（无活跃图层时）
    const enrichedJobLayer: JobLayerItem = jobLayer.catalogId
      ? jobLayer
      : { ...jobLayer, catalogId }
    const existingIndex = jobLayers.value.findIndex((item) => item.jobId === enrichedJobLayer.jobId)
    if (existingIndex >= 0) {
      jobLayers.value.splice(existingIndex, 1, enrichedJobLayer)
    } else {
      jobLayers.value.unshift(enrichedJobLayer)
    }
    syncJobLayerToActiveLayer(catalogId, enrichedJobLayer)
    rememberTrackedWorkflowRun(catalogId, enrichedJobLayer)
    updateRunGroupForCatalog(catalogId, enrichedJobLayer)
    if (isTerminalStatus(enrichedJobLayer.status)) {
      if (enrichedJobLayer.status === 'cancelled' || enrichedJobLayer.status === 'failed') {
        // local-submit 失败时按 catalog 找组清理占位；真 run 按 runId
        if (isLocalSubmitJobId(enrichedJobLayer.jobId)) {
          const layer = activeLayers.value.find((l) => l.catalogId === catalogId)
          if (layer?.runGroupId) {
            const g = runLayerGroups.value.find((x) => x.groupId === layer.runGroupId)
            if (g && !g.runId) {
              g.status = 'failed'
              g.dissolvable = true
              g.message = enrichedJobLayer.message || '提交失败'
            }
          }
        } else {
          cleanupUnproducedRunLayers(enrichedJobLayer.jobId)
        }
      }
      // Keep succeeded/failed in storage briefly for refresh restore of final state,
      // but drop cancelled noise.
      if (enrichedJobLayer.status === 'cancelled') {
        forgetTrackedWorkflowRun(enrichedJobLayer.jobId)
      }
    }
    scheduleWorkspacePersist()
  }

  function buildWorkflowPayloadForCatalog(
    catalogId: string,
    catalogName: string,
    requestedOutputs: string[],
    requestBBox: BoundingBox | null,
    backendLayerId?: string,
    algorithmRequest?: Record<string, unknown>,
    weatherRequest?: Record<string, unknown>,
  ) {
    const layerId = backendLayerId ?? catalogId
    const payload: Record<string, unknown> = {
      command_type: 'analysis' as const,
      command_label: `运行 ${catalogName} 分析`,
      layer_id: layerId,
      priority: 'normal' as const,
      resource_profile: 'standard' as const,
      realtime_preferred: false,
      requested_outputs: requestedOutputs,
      parameters: {
        hour: currentHour.value,
        latitude: currentMapCenter.value.lat,
        longitude: currentMapCenter.value.lng,
      },
      client: {
        page: 'dashboard',
        view_id: 'map-2d',
      },
      map_context: {
        active_layer_id: catalogId,
        map_mode: '2d' as const,
        viewport_bbox: requestBBox ?? undefined,
      },
    }
    if (algorithmRequest && Object.keys(algorithmRequest).length > 0) {
      payload.algorithm_request = algorithmRequest
    }
    if (weatherRequest && Object.keys(weatherRequest).length > 0) {
      payload.weather_request = weatherRequest
    }
    return payload
  }

  const progressiveMaterializeAt = new Map<string, number>()
  const progressiveMaterializeInFlight = new Set<string>()

  function formatProgressiveSyncMessage(count: number, hadError: boolean): string {
    if (hadError && count > 0) {
      return WORKFLOW_COPY.progressiveSyncPartial.replace('{count}', String(count))
    }
    if (hadError) return WORKFLOW_COPY.progressiveSyncFailed
    if (count > 0) {
      return WORKFLOW_COPY.progressiveSyncOk.replace('{count}', String(count))
    }
    return ''
  }

  function applyProgressiveSyncToJob(
    catalogId: string,
    runId: string,
    count: number,
    hadError: boolean,
    errorMsg?: string,
  ) {
    const now = new Date().toISOString()
    const msg = formatProgressiveSyncMessage(count, hadError)
    const job = jobLayers.value.find((j) => j.jobId === runId)
    if (job) {
      job.progressiveOverlayCount = count
      job.progressiveOverlayAt = hadError ? job.progressiveOverlayAt : now
      job.progressiveOverlayError = hadError
        ? errorMsg || WORKFLOW_COPY.progressiveSyncFailed
        : undefined
      if (msg) job.message = msg
      syncJobLayerToActiveLayer(catalogId, job)
      updateRunGroupForCatalog(catalogId, job)
    }
  }

  /** 运行中块产物增量物化（节流）。 */
  async function syncProgressiveBlockOverlays(runId: string, catalogId: string) {
    if (!runId) return
    const now = Date.now()
    const last = progressiveMaterializeAt.get(runId) ?? 0
    if (now - last < 8_000) return
    if (progressiveMaterializeInFlight.has(runId)) return
    progressiveMaterializeAt.set(runId, now)
    progressiveMaterializeInFlight.add(runId)
    try {
      const count = await attachAlgorithmProductOverlays([], catalogId, runId)
      applyProgressiveSyncToJob(catalogId, runId, count, false)
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : WORKFLOW_COPY.progressiveSyncFailed
      console.warn('[layers] progressive block overlay sync failed', runId, error)
      const prev = jobLayers.value.find((j) => j.jobId === runId)?.progressiveOverlayCount ?? 0
      applyProgressiveSyncToJob(catalogId, runId, prev, true, errMsg)
    } finally {
      progressiveMaterializeInFlight.delete(runId)
    }
  }

  function applyWorkflowEventsToJobLayer(
    jobLayer: JobLayerItem,
    events: WorkflowEvent[],
  ): JobLayerItem {
    if (events.length === 0) return jobLayer

    let nextStatus = jobLayer.status
    let nextProgress = jobLayer.progress
    let nextMessage = jobLayer.message
    let nextUpdatedAt = jobLayer.updatedAt
    let lastEventId = jobLayer.lastEventId
    let lastEventAt = jobLayer.lastEventAt
    // 节点级进度累计：保留已有节点，按 node_id 合并最新阶段
    const nextNodeProgress: NodeProgress[] = [...(jobLayer.nodeProgress ?? [])]

    for (const event of events) {
      if (typeof event.progress === 'number') {
        nextProgress = Math.max(nextProgress, normalizeWorkflowProgress(event.progress))
      }
      if (event.message) {
        nextMessage = event.message
      }
      if (isRecognizedJobStatus(event.payload?.status)) {
        nextStatus = event.payload.status
      }
      // 解析节点级进度事件
      const rawNodeProgress = (event.payload as { node_progress?: unknown } | null | undefined)
        ?.node_progress
      if (rawNodeProgress && typeof rawNodeProgress === 'object') {
        const np = rawNodeProgress as {
          node_id?: string
          node_label?: string
          stage?: string
          progress?: number
          message?: string
          artifacts?: string[]
          detail?: Record<string, unknown>
        }
        const detailRaw = np.detail
        const detail =
          detailRaw && typeof detailRaw === 'object'
            ? {
                chunksDone:
                  typeof detailRaw.chunks_done === 'number'
                    ? detailRaw.chunks_done
                    : typeof detailRaw.chunksDone === 'number'
                      ? detailRaw.chunksDone
                      : undefined,
                chunksTotal:
                  typeof detailRaw.chunks_total === 'number'
                    ? detailRaw.chunks_total
                    : typeof detailRaw.chunksTotal === 'number'
                      ? detailRaw.chunksTotal
                      : undefined,
                pixelsDone:
                  typeof detailRaw.pixels_done === 'number'
                    ? detailRaw.pixels_done
                    : typeof detailRaw.pixelsDone === 'number'
                      ? detailRaw.pixelsDone
                      : undefined,
                pixelsTotal:
                  typeof detailRaw.pixels_total === 'number'
                    ? detailRaw.pixels_total
                    : typeof detailRaw.pixelsTotal === 'number'
                      ? detailRaw.pixelsTotal
                      : undefined,
                phase: typeof detailRaw.phase === 'string' ? detailRaw.phase : undefined,
                blocksDone:
                  typeof detailRaw.blocks_done === 'number' ? detailRaw.blocks_done : undefined,
                blocksTotal:
                  typeof detailRaw.blocks_total === 'number' ? detailRaw.blocks_total : undefined,
                dateStart:
                  typeof detailRaw.date_start === 'string' ? detailRaw.date_start : undefined,
                dateEnd: typeof detailRaw.date_end === 'string' ? detailRaw.date_end : undefined,
                blockDir: typeof detailRaw.block_dir === 'string' ? detailRaw.block_dir : undefined,
                timeKey:
                  typeof detailRaw.time_key === 'string'
                    ? detailRaw.time_key
                    : typeof detailRaw.timeKey === 'string'
                      ? detailRaw.timeKey
                      : undefined,
                tileId:
                  typeof detailRaw.tile_id === 'string'
                    ? detailRaw.tile_id
                    : typeof detailRaw.tileId === 'string'
                      ? detailRaw.tileId
                      : undefined,
                chunkId:
                  typeof detailRaw.chunk_id === 'string'
                    ? detailRaw.chunk_id
                    : typeof detailRaw.chunkId === 'string'
                      ? detailRaw.chunkId
                      : undefined,
                blockId:
                  typeof detailRaw.block_id === 'string'
                    ? detailRaw.block_id
                    : typeof detailRaw.blockId === 'string'
                      ? detailRaw.blockId
                      : undefined,
                productTag:
                  typeof detailRaw.product_tag === 'string'
                    ? detailRaw.product_tag
                    : typeof detailRaw.productTag === 'string'
                      ? detailRaw.productTag
                      : typeof detailRaw.artifact_type === 'string'
                        ? detailRaw.artifact_type
                        : undefined,
                moduleName:
                  typeof detailRaw.module_name === 'string'
                    ? detailRaw.module_name
                    : typeof detailRaw.moduleName === 'string'
                      ? detailRaw.moduleName
                      : undefined,
              }
            : undefined
        if (
          detail?.phase === 'block_commit' ||
          detail?.phase === 'block_refresh' ||
          detail?.phase === 'artifact'
        ) {
          // progressive overlay sync (throttled inside helper)
          const progressiveCatalogId = jobLayer.catalogId
          if (progressiveCatalogId) {
            void syncProgressiveBlockOverlays(jobLayer.jobId, progressiveCatalogId)
          }
          if (detail.dateStart && detail.dateEnd) {
            nextMessage = `块 ${detail.blocksDone ?? '?'}/${detail.blocksTotal ?? '?'} · ${detail.dateStart}–${detail.dateEnd}`
          } else {
            const shell = formatProgressShell({
              progress: typeof np.progress === 'number' ? np.progress : undefined,
              message: typeof np.message === 'string' ? np.message : undefined,
              stage: typeof np.stage === 'string' ? np.stage : undefined,
              nodeLabel: typeof np.node_label === 'string' ? np.node_label : undefined,
              detail,
            })
            if (shell) nextMessage = shell
          }
        }
        const nodePct = normalizeWorkflowProgress(
          typeof np.progress === 'number' ? np.progress : undefined,
          detail,
        )
        if (typeof np.node_id === 'string') {
          const eventAt = event.created_at
          const existing = nextNodeProgress.find((p) => p.nodeId === np.node_id)
          if (existing) {
            Object.assign(existing, {
              stage: typeof np.stage === 'string' ? np.stage : existing.stage,
              progress:
                typeof np.progress === 'number' || detail
                  ? Math.max(existing.progress, nodePct)
                  : existing.progress,
              message: typeof np.message === 'string' ? np.message : existing.message,
              artifacts: Array.isArray(np.artifacts) ? np.artifacts : existing.artifacts,
              detail: detail ?? existing.detail,
              updatedAt: eventAt,
            })
          } else {
            nextNodeProgress.push({
              nodeId: np.node_id,
              nodeLabel: typeof np.node_label === 'string' ? np.node_label : np.node_id,
              stage: typeof np.stage === 'string' ? np.stage : '',
              progress: nodePct,
              message: typeof np.message === 'string' ? np.message : undefined,
              artifacts: Array.isArray(np.artifacts) ? np.artifacts : undefined,
              detail,
              updatedAt: eventAt,
            })
          }
          nextProgress = Math.max(nextProgress, nodePct)
          emitWorkflowProgressTimeSeek(
            { ...jobLayer, catalogId: jobLayer.catalogId },
            nextStatus,
            detail,
          )
        }
      }
      lastEventId = event.event_id
      lastEventAt = event.created_at
      nextUpdatedAt = event.created_at
    }

    const eventMessages = mergeRecentEventMessages(
      jobLayer.eventMessages ?? jobLayer.diagnosticNotes,
      events,
    )
    const showEventMessages =
      nextStatus === 'queued' || nextStatus === 'running' || nextStatus === 'retry_pending'

    return {
      ...jobLayer,
      status: nextStatus,
      progress: nextProgress,
      message: nextMessage,
      updatedAt: nextUpdatedAt,
      lastEventId,
      lastEventAt,
      eventMessages,
      nodeProgress: nextNodeProgress,
      diagnosticNotes: showEventMessages ? eventMessages : jobLayer.diagnosticNotes,
    }
  }

  async function syncWorkflowRunSnapshot(
    jobId: string,
    catalogId: string,
    force = false,
    expectedViewportEpoch?: number,
  ) {
    if (isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      return true
    }

    const now = Date.now()
    if (!force) {
      const lastSyncedAt = workflowLastStatusSyncAt.get(jobId) ?? 0
      if (now - lastSyncedAt < STATUS_SYNC_INTERVAL_MS) {
        return false
      }
    }

    const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
    const run = await getWorkflowRun(jobId)
    if (isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      return true
    }
    const jobLayer = await buildJobLayer(run, catalogId, { previousJobLayer: existingJobLayer })
    if (isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      return true
    }
    const mergedJobLayer =
      existingJobLayer && !isTerminalStatus(jobLayer.status)
        ? {
            ...jobLayer,
            // Keep the higher of server snapshot vs event-derived progress
            progress: Math.max(
              normalizeWorkflowProgress(jobLayer.progress),
              normalizeWorkflowProgress(existingJobLayer.progress),
              ...(existingJobLayer.nodeProgress ?? []).map((np) =>
                normalizeWorkflowProgress(np.progress, np.detail),
              ),
            ),
            lastEventId: existingJobLayer.lastEventId,
            lastEventAt: existingJobLayer.lastEventAt,
            eventMessages: existingJobLayer.eventMessages,
            nodeProgress: existingJobLayer.nodeProgress,
            diagnosticNotes: jobLayer.diagnosticNotes?.length
              ? jobLayer.diagnosticNotes
              : (existingJobLayer.eventMessages ?? existingJobLayer.diagnosticNotes),
          }
        : {
            ...jobLayer,
            progress: normalizeWorkflowProgress(jobLayer.progress),
          }

    upsertJobLayer(catalogId, mergedJobLayer)
    workflowLastStatusSyncAt.set(jobId, now)

    if (isTerminalStatus(mergedJobLayer.status)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      if (mergedJobLayer.status === 'succeeded' && !isRunDismissed(run.run_id)) {
        void attachAlgorithmProductOverlays(run.result_refs, catalogId, run.run_id)
      }
      if (
        particleFlowCatalogId.value === catalogId &&
        supportsParticleFlow(catalogId) &&
        !hasRenderableMapLayerAsset(mergedJobLayer)
      ) {
        clearWindForCatalog(catalogId)
      }
      if (
        mergedJobLayer.status === 'succeeded' &&
        supportsParticleFlow(catalogId) &&
        hasRenderableMapLayerAsset(mergedJobLayer)
      ) {
        enableParticleIfUnset(catalogId)
      }
      return true
    }

    return false
  }

  /** Attach algorithm-published overlays so the map shows SM/VOD/OMEGA content. */
  async function attachAlgorithmProductOverlays(
    resultRefs: Parameters<typeof extractOverlayImportsFromResultRefs>[0],
    preferredCatalogId: string,
    runId?: string,
  ): Promise<number> {
    if (runId && isRunDismissed(runId)) return 0

    let imports = extractOverlayImportsFromResultRefs(resultRefs)
    let materializedLayers: Awaited<ReturnType<typeof materializeWorkflowMapLayers>>['layers'] = []
    if ((!imports.length || runId) && runId) {
      try {
        const materialized = await materializeWorkflowMapLayers(runId)
        materializedLayers = materialized.layers ?? []
        if (!imports.length) {
          imports = materializedLayers
            .filter((layer) => typeof layer.overlay_layer_id === 'string' && layer.overlay_layer_id)
            .map((layer) => {
              const rawBounds = layer.bounds
              const bounds =
                Array.isArray(rawBounds) &&
                rawBounds.length === 4 &&
                rawBounds.every((v) => typeof v === 'number' && Number.isFinite(v))
                  ? ([rawBounds[0], rawBounds[1], rawBounds[2], rawBounds[3]] as [
                      number,
                      number,
                      number,
                      number,
                    ])
                  : undefined
              return {
                overlayLayerId: layer.overlay_layer_id,
                title: layer.title || layer.overlay_layer_id,
                productTag: layer.product_tag || undefined,
                bounds,
                sourceCrs: layer.source_crs || undefined,
                timeList: layer.time_list || undefined,
                nativeStep: layer.native_step || undefined,
                defaultTime: layer.default_time || undefined,
              }
            })
        }
      } catch (error) {
        console.warn('[layers] materializeWorkflowMapLayers failed', runId, error)
        // 发布就绪修复（P0-9）：materialize 失败不再静默吞掉——落到 workflowError，
        // 避免"工作流显示 succeeded 但地图无图层、无任何错误提示"。
        workflowError.value = `工作流结果图层加载失败：${
          error instanceof Error ? error.message : String(error)
        }`
      }
    }
    if (!imports.length) return 0
    imports = imports.filter((item) => !isOverlayDismissed(item.overlayLayerId))
    if (!imports.length) return 0

    const outputStore = useWorkflowOutputLayersStore()
    for (const item of imports) {
      if (isOverlayDismissed(item.overlayLayerId)) continue
      const matMeta = materializedLayers.find(
        (layer) => layer.overlay_layer_id === item.overlayLayerId,
      )
      const timeList = (item as { timeList?: string[] }).timeList || matMeta?.time_list || undefined
      const nativeStep =
        (item as { nativeStep?: string }).nativeStep || matMeta?.native_step || undefined

      const existingByOverlay = activeLayers.value.find(
        (layer) => layer.importedRaster?.overlayLayerId === item.overlayLayerId,
      )
      if (existingByOverlay?.importedRaster) {
        if (timeList?.length) {
          existingByOverlay.importedRaster.timeList = [...timeList]
          existingByOverlay.importedRaster.timeSlices = undefined
          existingByOverlay.importedRaster.nativeStep =
            nativeStep || existingByOverlay.importedRaster.nativeStep || '8d'
        }
        // 若游离 OMEGA_BLOCK 可并入组内 OMEGA 占位，不要在此 continue
        const canMergeIntoGroup =
          normalizeProductTag(item.productTag || item.title || existingByOverlay.name) ===
            'OMEGA' &&
          Boolean(
            (runId
              ? runLayerGroups.value.find((g) => g.runId === runId)
              : runLayerGroups.value.find((g) =>
                  g.memberInstanceIds.includes(existingByOverlay.instanceId),
                )) ||
            activeLayers.value.some(
              (layer) =>
                !layer.importedRaster &&
                normalizeProductTag(layer.runGroupProductTag || layer.name) === 'OMEGA',
            ),
          )
        if (!canMergeIntoGroup) {
          continue
        }
      }

      const tag = normalizeProductTag(item.productTag || item.title || '')
      const matchingOutput = outputStore.entries.find((entry) => {
        const name = entry.name.toUpperCase()
        return Boolean(tag) && (name.includes(tag) || name.endsWith(`_${tag}`))
      })
      const displayName =
        matchingOutput?.name ||
        (tag === 'OMEGA' ? 'OMEGA' : item.title.replace(/^Algorithm Map Layer:\s*/i, '')) ||
        item.productTag ||
        item.overlayLayerId

      // Bind only within this run's computing group (never cross-run by tag alone).
      const groupByRun = runId ? runLayerGroups.value.find((g) => g.runId === runId) : undefined
      const groupMember =
        groupByRun &&
        activeLayers.value.find(
          (layer) =>
            layer.runGroupId === groupByRun.groupId &&
            normalizeProductTag(layer.runGroupProductTag) === tag,
        )

      // 已有同 overlay 的游离层 + 组内占位：并入组并移除游离层
      if (
        groupMember &&
        existingByOverlay &&
        existingByOverlay.instanceId !== groupMember.instanceId
      ) {
        groupMember.importedRaster = existingByOverlay.importedRaster
          ? { ...existingByOverlay.importedRaster }
          : buildImportedRasterPayload(item.overlayLayerId, {
              bounds: item.bounds,
              fileName: groupMember.name || displayName,
              sourceCrs: item.sourceCrs,
              nativeStep: nativeStep || (timeList?.length ? '8d' : null),
              timeList,
              followPolicy: timeList?.length ? 'containing' : undefined,
            })
        groupMember.dataState = 'imported'
        groupMember.name = groupMember.name || displayName
        // 去掉游离层但不删后端文件
        const orphanId = existingByOverlay.instanceId
        const idx = activeLayers.value.findIndex((l) => l.instanceId === orphanId)
        if (idx >= 0) {
          const orphan = activeLayers.value[idx]!
          orphan.importedRaster = undefined
          activeLayers.value.splice(idx, 1)
          if (orphan.runGroupId) {
            const og = runLayerGroups.value.find((x) => x.groupId === orphan.runGroupId)
            if (og) {
              og.memberInstanceIds = og.memberInstanceIds.filter((id) => id !== orphanId)
            }
          }
        }
        if (groupMember.runGroupId) refreshRunGroupDissolvable(groupMember.runGroupId)
        scheduleWorkspacePersist()
        continue
      }

      if (groupMember) {
        groupMember.importedRaster = buildImportedRasterPayload(item.overlayLayerId, {
          bounds: item.bounds,
          fileName: groupMember.name || displayName,
          sourceCrs: item.sourceCrs,
          nativeStep: nativeStep || (timeList?.length ? '8d' : null),
          timeList,
          followPolicy: timeList?.length ? 'containing' : undefined,
        })
        groupMember.dataState = 'imported'
        if (groupMember.name === 'OMEGA' || !groupMember.name) {
          groupMember.name = displayName === 'OMEGA_BLOCK' ? 'OMEGA' : displayName
        }
        if (groupMember.runGroupId) refreshRunGroupDissolvable(groupMember.runGroupId)
        continue
      }

      // 无组时：若已有「OMEGA」占位（任意组）且本条是 OMEGA_BLOCK，并入
      if (tag === 'OMEGA') {
        const omegaPlaceholder = activeLayers.value.find(
          (layer) =>
            !layer.importedRaster &&
            normalizeProductTag(layer.runGroupProductTag || layer.name) === 'OMEGA',
        )
        if (omegaPlaceholder) {
          omegaPlaceholder.importedRaster = buildImportedRasterPayload(item.overlayLayerId, {
            bounds: item.bounds,
            fileName: omegaPlaceholder.name || 'OMEGA',
            sourceCrs: item.sourceCrs,
            nativeStep: nativeStep || (timeList?.length ? '8d' : null),
            timeList,
            followPolicy: timeList?.length ? 'containing' : undefined,
          })
          omegaPlaceholder.dataState = 'imported'
          omegaPlaceholder.name = 'OMEGA'
          if (omegaPlaceholder.runGroupId) {
            refreshRunGroupDissolvable(omegaPlaceholder.runGroupId)
          }
          // 若本 overlay 已作为游离层存在，删掉游离条目
          if (existingByOverlay && existingByOverlay.instanceId !== omegaPlaceholder.instanceId) {
            const idx = activeLayers.value.findIndex(
              (l) => l.instanceId === existingByOverlay.instanceId,
            )
            if (idx >= 0) {
              activeLayers.value[idx]!.importedRaster = undefined
              activeLayers.value.splice(idx, 1)
            }
          }
          scheduleWorkspacePersist()
          continue
        }
      }

      // Prefer binding onto an existing wf-out active layer when present.
      const targetCatalogId = matchingOutput?.localId
      const existingActive = targetCatalogId
        ? activeLayers.value.find(
            (layer) => layer.catalogId === targetCatalogId && !layer.isAdminBoundary,
          )
        : activeLayers.value.find(
            (layer) => layer.catalogId === preferredCatalogId && !layer.isAdminBoundary,
          )

      if (existingActive && !existingActive.importedRaster) {
        existingActive.importedRaster = buildImportedRasterPayload(item.overlayLayerId, {
          bounds: item.bounds,
          fileName: displayName,
          sourceCrs: item.sourceCrs,
          nativeStep: nativeStep || (timeList?.length ? '8d' : null),
          timeList,
          followPolicy: timeList?.length ? 'containing' : undefined,
        })
        existingActive.dataState = 'imported'
        if (!existingActive.name) existingActive.name = displayName
        if (existingActive.runGroupId) refreshRunGroupDissolvable(existingActive.runGroupId)
        continue
      }

      const added = addImportedRasterLayer(displayName, item.overlayLayerId, item.bounds, {
        sourceCrs: item.sourceCrs,
        nativeStep: nativeStep || (timeList?.length ? '8d' : null),
        timeList,
        followPolicy: timeList?.length ? 'containing' : undefined,
      })
      if (added && groupByRun) {
        added.runGroupId = groupByRun.groupId
        added.runGroupProductTag = item.productTag || tag || 'result'
        added.runGroupLocked = groupByRun.status === 'computing'
        if (!groupByRun.memberInstanceIds.includes(added.instanceId)) {
          groupByRun.memberInstanceIds.push(added.instanceId)
        }
        refreshRunGroupDissolvable(groupByRun.groupId)
      }
    }
    if (runId) {
      const g = runLayerGroups.value.find((x) => x.runId === runId)
      if (g) refreshRunGroupDissolvable(g.groupId)
    }
    reconcileOmegaBlockLayers()
    scheduleWorkspacePersist()
    return imports.length
  }

  /** 把游离的 OMEGA_BLOCK 并入组内 OMEGA 占位，去掉重复条目（不删后端文件） */
  function reconcileOmegaBlockLayers() {
    const orphans = activeLayers.value.filter((layer) => {
      if (!layer.importedRaster?.overlayLayerId) return false
      const name = `${layer.name || ''} ${layer.importedRaster.fileName || ''}`.toUpperCase()
      return name.includes('OMEGA_BLOCK') || normalizeProductTag(layer.name) === 'OMEGA'
    })
    for (const orphan of [...orphans]) {
      // 只处理名为 OMEGA_BLOCK 的游离层
      const orphanName = String(orphan.name || orphan.importedRaster?.fileName || '').toUpperCase()
      if (!orphanName.includes('OMEGA_BLOCK')) continue
      const placeholder = activeLayers.value.find(
        (layer) =>
          layer.instanceId !== orphan.instanceId &&
          !layer.importedRaster &&
          normalizeProductTag(layer.runGroupProductTag || layer.name) === 'OMEGA',
      )
      if (!placeholder) {
        // 无占位：直接把游离层改名为 OMEGA
        orphan.name = 'OMEGA'
        if (orphan.runGroupProductTag) orphan.runGroupProductTag = 'OMEGA'
        continue
      }
      placeholder.importedRaster = { ...orphan.importedRaster! }
      placeholder.dataState = 'imported'
      placeholder.name = 'OMEGA'
      placeholder.runGroupProductTag = placeholder.runGroupProductTag || 'OMEGA'
      // 摘掉游离层引用后从列表移除（不清后端）
      orphan.importedRaster = undefined
      const idx = activeLayers.value.findIndex((l) => l.instanceId === orphan.instanceId)
      if (idx >= 0) activeLayers.value.splice(idx, 1)
      if (orphan.runGroupId) {
        const og = runLayerGroups.value.find((x) => x.groupId === orphan.runGroupId)
        if (og) {
          og.memberInstanceIds = og.memberInstanceIds.filter((id) => id !== orphan.instanceId)
          if (!og.memberInstanceIds.length) {
            runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== og.groupId)
          }
        }
      }
      if (placeholder.runGroupId) refreshRunGroupDissolvable(placeholder.runGroupId)
    }
  }

  async function pollWorkflowRun(
    jobId: string,
    catalogId: string,
    lastActivityAt = Date.now(),
    consecutiveErrors = 0,
    expectedViewportEpoch?: number,
  ) {
    if (isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      return
    }
    if (Date.now() - lastActivityAt > EVENT_POLL_IDLE_TIMEOUT_MS) {
      // Soft timeout: trust the server. Never invent a local failure over a
      // succeeded/running run (long omega_sf jobs routinely exceed idle gaps).
      try {
        const run = await getWorkflowRun(jobId)
        const serverStatus = run.status === 'accepted' ? 'queued' : run.status
        if (!isTerminalStatus(serverStatus)) {
          const handle = window.setTimeout(() => {
            void pollWorkflowRun(jobId, catalogId, Date.now(), 0, expectedViewportEpoch)
          }, EVENT_POLL_IDLE_INTERVAL_MS)
          workflowPollingHandles.set(jobId, handle)
          return
        }
        // Terminal on server — sync authoritative snapshot (incl. succeeded)
        await syncWorkflowRunSnapshot(jobId, catalogId, true, expectedViewportEpoch)
        return
      } catch {
        // Network blip: keep polling instead of marking failed.
        const handle = window.setTimeout(() => {
          void pollWorkflowRun(
            jobId,
            catalogId,
            Date.now(),
            consecutiveErrors,
            expectedViewportEpoch,
          )
        }, EVENT_POLL_IDLE_INTERVAL_MS)
        workflowPollingHandles.set(jobId, handle)
        return
      }
    }

    let nextConsecutiveErrors = consecutiveErrors
    let nextDelayMs = EVENT_POLL_IDLE_INTERVAL_MS
    let nextActivityAt = lastActivityAt

    try {
      const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
      const events = await getWorkflowEvents(jobId, {
        afterEventId: existingJobLayer?.lastEventId,
        limit: 24,
      })
      if (isViewportRefreshStale(expectedViewportEpoch)) {
        stopWorkflowPolling(jobId)
        activeWorkflowCatalogIds.delete(catalogId)
        return
      }
      const newItems = events.items ?? []

      if (existingJobLayer && newItems.length > 0) {
        upsertJobLayer(catalogId, applyWorkflowEventsToJobLayer(existingJobLayer, newItems))
        nextDelayMs = EVENT_POLL_ACTIVE_INTERVAL_MS
        nextActivityAt = Date.now()
      }

      workflowError.value = null
      nextConsecutiveErrors = 0

      const shouldForceSync = newItems.some(
        (event) =>
          isRecognizedJobStatus(event.payload?.status) && isTerminalStatus(event.payload.status),
      )
      const didReachTerminal = await syncWorkflowRunSnapshot(
        jobId,
        catalogId,
        shouldForceSync,
        expectedViewportEpoch,
      )
      if (didReachTerminal) {
        return
      }
      // Status sync that still shows running also counts as activity
      if (shouldForceSync || newItems.length > 0) {
        nextActivityAt = Date.now()
      } else {
        // Periodic status sync: if still running, treat as activity
        const current = jobLayers.value.find((item) => item.jobId === jobId)
        if (
          current &&
          (current.status === 'running' ||
            current.status === 'queued' ||
            current.status === 'retry_pending')
        ) {
          nextActivityAt = Date.now()
          void syncProgressiveBlockOverlays(jobId, catalogId)
        }
      }
    } catch (error) {
      if (isViewportRefreshStale(expectedViewportEpoch)) {
        stopWorkflowPolling(jobId)
        activeWorkflowCatalogIds.delete(catalogId)
        return
      }
      const errMsg = error instanceof Error ? error.message : String(error)
      if (errMsg.includes('404')) {
        stopWorkflowPolling(jobId)
        activeWorkflowCatalogIds.delete(catalogId)
        workflowError.value = `工作流 ${jobId} 不存在（可能已过期）`
        const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
        if (existingJobLayer) {
          upsertJobLayer(catalogId, {
            ...existingJobLayer,
            status: 'failed',
            message: '工作流记录不存在',
            progress: existingJobLayer.progress,
          })
        }
        return
      }

      // AbortError（requestJson 30s 超时）是临时性错误，不显示给用户，直接重试
      const isAbortError = error instanceof DOMException && error.name === 'AbortError'
      if (isAbortError) {
        // 超时后用 idle 间隔重试，不递增错误计数，不设置 workflowError
        nextDelayMs = EVENT_POLL_IDLE_INTERVAL_MS
        nextActivityAt = Date.now()
      } else {
        nextConsecutiveErrors = consecutiveErrors + 1
        if (nextConsecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          // Before giving up, ask the server — never invent failure over a live/succeeded run.
          try {
            const run = await getWorkflowRun(jobId)
            const serverStatus = run.status === 'accepted' ? 'queued' : run.status
            if (!isTerminalStatus(serverStatus) || serverStatus === 'succeeded') {
              await syncWorkflowRunSnapshot(jobId, catalogId, true, expectedViewportEpoch)
              if (!isTerminalStatus(serverStatus)) {
                const handle = window.setTimeout(() => {
                  void pollWorkflowRun(jobId, catalogId, Date.now(), 0, expectedViewportEpoch)
                }, EVENT_POLL_IDLE_INTERVAL_MS)
                workflowPollingHandles.set(jobId, handle)
              }
              return
            }
          } catch {
            // fall through
          }
          stopWorkflowPolling(jobId)
          activeWorkflowCatalogIds.delete(catalogId)
          workflowError.value = `工作流 ${jobId} 事件同步连续失败 ${nextConsecutiveErrors} 次：${errMsg}`
          const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
          if (existingJobLayer && existingJobLayer.status !== 'succeeded') {
            upsertJobLayer(catalogId, {
              ...existingJobLayer,
              status: 'failed',
              message: `事件同步连续失败：${errMsg}`,
              progress: existingJobLayer.progress,
            })
          }
          return
        }
        workflowError.value = errMsg
      }
    }

    // 页面不可见时延长轮询间隔，避免后台积压定时器导致回来后卡顿
    const effectiveDelay = document.hidden ? Math.max(nextDelayMs, 10000) : nextDelayMs
    const handle = window.setTimeout(() => {
      void pollWorkflowRun(
        jobId,
        catalogId,
        nextActivityAt,
        nextConsecutiveErrors,
        expectedViewportEpoch,
      )
    }, effectiveDelay)
    workflowPollingHandles.set(jobId, handle)
  }

  /**
   * 注册一个外部触发的工作流 run（如定时器触发、后端直接提交），
   * 将其写入 jobLayers 并启动轮询跟踪。
   * catalogId 用于关联图层；若未知则用 run.engine 或 fallback。
   */
  async function registerExternalWorkflowRun(runId: string, catalogIdHint?: string) {
    // 已在跟踪则跳过
    if (workflowPollingHandles.has(runId)) return
    const existing = jobLayers.value.find((item) => item.jobId === runId)
    if (existing && !isTerminalStatus(existing.status)) return

    try {
      const run = await getWorkflowRun(runId)
      // 推断 catalogId：优先 hint，其次从 run payload 的 layer_id 取
      const inferredCatalogId =
        catalogIdHint ?? ((run as Record<string, unknown>).layer_id as string) ?? runId
      const jobLayer = await buildJobLayer(run, inferredCatalogId, {})
      upsertJobLayer(inferredCatalogId, jobLayer)
      if (!isTerminalStatus(jobLayer.status)) {
        activeWorkflowCatalogIds.add(inferredCatalogId)
        void pollWorkflowRun(runId, inferredCatalogId)
      }
    } catch (err) {
      console.error('[layers] registerExternalWorkflowRun failed:', runId, err)
    }
  }

  function resolveRestoredCatalogId(runLayerId: string | null | undefined, runId: string): string {
    const layerId = (runLayerId || '').trim()
    const tracked = loadTrackedWorkflowRuns().find((item) => item.runId === runId)
    if (tracked?.catalogId) return tracked.catalogId
    if (layerId) {
      const outputStore = useWorkflowOutputLayersStore()
      const match = outputStore.entries.find(
        (entry) => entry.sourceLayerId === layerId && entry.lastRunId === runId,
      )
      if (match) return match.localId
      const bySource = outputStore.getBySourceLayerId(layerId)
      if (bySource.length === 1) return bySource[0].localId
      if (bySource.length > 1) {
        // Prefer most recently created output entry
        return bySource[0].localId
      }
      return layerId
    }
    return runId
  }

  /** Replay recent events so node progress bars survive page refresh. */
  async function hydrateJobLayerFromEvents(jobLayer: JobLayerItem): Promise<JobLayerItem> {
    try {
      const events = await getWorkflowEvents(jobLayer.jobId, { limit: 50 })
      const items = events.items ?? []
      if (!items.length) return jobLayer
      return applyWorkflowEventsToJobLayer(jobLayer, items)
    } catch {
      return jobLayer
    }
  }

  /**
   * 从后端 + localStorage 恢复工作流列表。在页面加载 / 刷新后调用，
   * 确保跨会话与长批任务的进度条/节点进度不会丢失。
   */
  async function restoreActiveWorkflows() {
    try {
      // 先恢复本机已产出图层/组，再合并后端活跃 run
      const instanceIdMap = hydrateWorkspaceFromSnapshot()
      await hydrateVectorLayersFromSnapshot(instanceIdMap)
      reconcileOmegaBlockLayers()

      const activeRuns = await listActiveWorkflowRuns().catch(() => [])
      const tracked = loadTrackedWorkflowRuns()
      const seen = new Set<string>()

      const candidates: Array<{ runId: string; catalogIdHint?: string }> = []
      for (const run of activeRuns) {
        candidates.push({
          runId: run.run_id,
          catalogIdHint: ((run as Record<string, unknown>).layer_id as string) || undefined,
        })
      }
      for (const item of tracked) {
        if (isLocalSubmitJobId(item.runId)) {
          forgetTrackedWorkflowRun(item.runId)
          continue
        }
        if (!candidates.some((c) => c.runId === item.runId)) {
          candidates.push({ runId: item.runId, catalogIdHint: item.catalogId })
        }
      }

      // 清掉残留的乐观提交占位（排队幽灵）
      for (const job of [...jobLayers.value]) {
        if (isLocalSubmitJobId(job.jobId)) {
          removeJobLayerById(job.jobId)
        }
      }

      for (const candidate of candidates) {
        if (seen.has(candidate.runId)) continue
        seen.add(candidate.runId)
        if (isRunDismissed(candidate.runId)) {
          forgetTrackedWorkflowRun(candidate.runId)
          continue
        }
        if (workflowPollingHandles.has(candidate.runId)) continue
        const existing = jobLayers.value.find((item) => item.jobId === candidate.runId)
        if (
          existing &&
          !isTerminalStatus(existing.status) &&
          workflowPollingHandles.has(candidate.runId)
        ) {
          continue
        }

        let run
        try {
          run = await getWorkflowRun(candidate.runId)
        } catch (err) {
          console.warn('[layers] restore skip missing run', candidate.runId, err)
          forgetTrackedWorkflowRun(candidate.runId)
          continue
        }

        const catalogId = resolveRestoredCatalogId(
          ((run as Record<string, unknown>).layer_id as string) || candidate.catalogIdHint,
          run.run_id,
        )
        let jobLayer = await buildJobLayer(run, catalogId, {
          previousJobLayer: existing,
        })
        jobLayer = await hydrateJobLayerFromEvents(jobLayer)
        // Prefer hydrated progress over bare server snapshot (often stuck at 18/35)
        if (existing) {
          jobLayer = {
            ...jobLayer,
            progress: Math.max(
              normalizeWorkflowProgress(jobLayer.progress),
              normalizeWorkflowProgress(existing.progress),
              ...(jobLayer.nodeProgress ?? []).map((np) =>
                normalizeWorkflowProgress(np.progress, np.detail),
              ),
            ),
            nodeProgress: jobLayer.nodeProgress?.length
              ? jobLayer.nodeProgress
              : existing.nodeProgress,
            eventMessages: jobLayer.eventMessages?.length
              ? jobLayer.eventMessages
              : existing.eventMessages,
          }
        }
        upsertJobLayer(catalogId, jobLayer)

        const outputStore = useWorkflowOutputLayersStore()
        if (catalogId.startsWith('wf-out-')) {
          outputStore.updateRunStatus(catalogId, run.run_id, jobLayer.status)
        }

        if (!isTerminalStatus(jobLayer.status)) {
          const trackedItem = tracked.find((t) => t.runId === run.run_id)
          const layerId = String((run as Record<string, unknown>).layer_id || catalogId)
          if (
            layerId.includes('omega-sf') ||
            catalogId.includes('omega-sf') ||
            catalogId.startsWith('wf-run-')
          ) {
            ensureRestoredRunGroup(run.run_id, catalogId, trackedItem, {
              createPlaceholders: true,
              title: jobLayer.name || 'SF 块反演（SMAP）',
            })
          }
          activeWorkflowCatalogIds.add(catalogId)
          void pollWorkflowRun(run.run_id, catalogId)
        } else if (jobLayer.status === 'succeeded' && !isRunDismissed(run.run_id)) {
          // 确保计算组结构存在，便于 attach 绑到 SM/VOD/OMEGA 成员
          ensureRestoredRunGroup(
            run.run_id,
            catalogId,
            tracked.find((t) => t.runId === run.run_id),
          )
          void attachAlgorithmProductOverlays(run.result_refs, catalogId, run.run_id).then(() =>
            scheduleWorkspacePersist(),
          )
        }
      }
      scheduleWorkspacePersist()
    } catch (err) {
      console.error('[layers] restoreActiveWorkflows failed:', err)
    }
  }

  function ensureRestoredRunGroup(
    runId: string,
    catalogId: string,
    tracked?: TrackedWorkflowRun,
    options?: { createPlaceholders?: boolean; title?: string },
  ) {
    if (runLayerGroups.value.some((g) => g.runId === runId)) return
    const groupId =
      tracked?.groupId || `run-group-restored-${runId.replace(/[^a-zA-Z0-9]/g, '').slice(-10)}`
    const tags = ['SM', 'VOD', 'OMEGA'] as const
    const memberCatalogIds =
      tracked?.memberCatalogIds?.length === 3
        ? tracked.memberCatalogIds
        : tags.map((tag) => `wf-run-${groupId}-${tag.toLowerCase()}`)

    const existingMembers = memberCatalogIds
      .map((cid) => activeLayers.value.find((l) => l.catalogId === cid))
      .filter((l): l is ActiveLayer => Boolean(l))

    if (existingMembers.length) {
      for (const m of existingMembers) {
        m.runGroupId = groupId
        m.runGroupLocked = options?.createPlaceholders === true
      }
      runLayerGroups.value.push({
        groupId,
        runId,
        title: options?.title || tracked?.name || 'SF 块反演产物',
        status: options?.createPlaceholders ? 'computing' : 'ready',
        memberInstanceIds: existingMembers.map((m) => m.instanceId),
        dissolvable: !options?.createPlaceholders,
        sourceLayerId: 'omega-sf-fenkuai',
        workflowId: 'omega_sf_fenkuai_smap_single',
      })
      return
    }

    if (!options?.createPlaceholders) {
      void catalogId
      return
    }

    const created = createRunLayerGroup({
      title: options.title || tracked?.name || 'SF 块反演（SMAP）',
      targets: tags.map((tag) => ({ name: tag, productTag: tag })),
      sourceLayerId: 'omega-sf-fenkuai',
      workflowId: 'omega_sf_fenkuai_smap_single',
      memberCatalogIds,
    })
    bindRunIdToGroup(created.groupId, runId)
  }

  /** 中断指定 catalogId 的活跃工作流（平移时调用）：停止轮询、取消 API（fire-and-forget），但保留旧的 jobLayer */
  function interruptWorkflowForCatalog(catalogId: string) {
    // 清理 429 重试定时器，避免与新的提交冲突
    const retryTimer = workflowRetryTimers.get(catalogId)
    if (retryTimer !== undefined) {
      window.clearTimeout(retryTimer)
      workflowRetryTimers.delete(catalogId)
    }
    // 查找该 catalogId 的活跃 jobId（非终态）
    const activeJobLayer = jobLayers.value.find(
      (item) =>
        activeLayers.value.some(
          (l) => l.catalogId === catalogId && l.jobLayer?.jobId === item.jobId,
        ) && !isTerminalStatus(item.status),
    )
    const runJobId = activeJobLayer?.jobId ?? null
    if (runJobId) {
      stopWorkflowPolling(runJobId)
      activeWorkflowCatalogIds.delete(catalogId)
      // fire-and-forget 取消 API 调用，不阻塞新提交
      void cancelWorkflowRun(runJobId).catch(() => {})
    }
  }

  async function runWorkflowForCatalog(
    catalogId: string,
    options: {
      expectedViewportEpoch?: number
      algorithmRequest?: Record<string, unknown>
      weatherRequest?: Record<string, unknown>
      commandLabel?: string
    } = {},
  ) {
    if (submittingCatalogIds.has(catalogId)) {
      debugLog('runWorkflow', catalogId, 'skip: already submitting')
      throw new Error('该图层工作流正在提交中，请稍候再试')
    }
    workflowError.value = null
    submittingCatalogIds.add(catalogId)
    debugLog('runWorkflow', catalogId, 'start')

    const backendLayerId = resolveBackendLayerId(catalogId)
    const isOutputLayer = backendLayerId !== catalogId
    const catalogName = isOutputLayer
      ? (layerLibrary.value.find((l) => l.catalogId === catalogId)?.name ?? catalogId)
      : (runtimeLayerCatalog.value[catalogId]?.display_name ??
        runtimeLayerCatalog.value[backendLayerId]?.display_name ??
        getCatalogDisplayName(catalogId))
    const submitJobId = localSubmitJobId(catalogId)
    const submitStartedAt = new Date().toISOString()

    try {
      const hasEditorWeather = Boolean(
        options.weatherRequest &&
        (options.weatherRequest.workflow ||
          (options.weatherRequest as { workflow_id?: string }).workflow_id),
      )
      // 天气图层默认走瓦片管道；编辑器编译出 weather 画布时走 weather_request
      if (isWeatherEngineLayer(backendLayerId) && !hasEditorWeather) {
        weatherTileManager.setLayerActive(catalogId, true)
        weatherTileManager.setViewport(
          catalogId,
          currentMapCenter.value,
          currentMapZoom.value,
          currentHour.value,
          undefined,
          currentMapBBox.value,
          weatherProviderArg(catalogId),
        )
        throw new Error(
          `${catalogName} 为天气引擎图层：由瓦片按需加载，已触发当前视口刷新。请查看地图与「工作流状态」中的天气瓦片进度，无需提交分析工作流。`,
        )
      }
      let runtimeCatalogReady = false
      try {
        await ensureRuntimeLayerCatalog()
        runtimeCatalogReady = true
      } catch (error) {
        const canProceedWithoutCatalog = isWeatherEngineLayer(backendLayerId)
        if (!canProceedWithoutCatalog) {
          throw error
        }
        console.warn(
          '[LayersStore] runtime layer catalog unavailable, proceeding with static fallback for',
          catalogId,
          error,
        )
      }

      const hasCanvasDefinition = Boolean(
        (options.algorithmRequest &&
          (options.algorithmRequest.workflow_definition ||
            options.algorithmRequest.workflow_name)) ||
        (options.weatherRequest && options.weatherRequest.workflow),
      )
      const blockedReason =
        runtimeCatalogReady && !isOutputLayer && !hasCanvasDefinition
          ? getCatalogRunBlockReason(backendLayerId)
          : null
      if (blockedReason) {
        throw new Error(blockedReason)
      }
      if (!isOutputLayer && !hasCanvasDefinition && !supportsAnalysisWorkflow(backendLayerId)) {
        throw new Error(`${catalogName} 未配置分析工作流引擎，无法提交 /workflow-runs`)
      }

      const supportsMapLayer = supportsMapLayerResult(backendLayerId)
      const requestedOutputs = supportsMapLayer
        ? ['json', 'text', 'table', 'map_layer']
        : ['json', 'text', 'table']
      const requestBBox = currentMapBBox.value

      // 中断旧位置的活跃工作流（取消 API 调用），但保留旧 mapLayerPayload 使地图资产在新工作流运行期间保持可见
      const previousJobLayer = activeLayers.value.find(
        (l) => l.catalogId === catalogId && !l.isAdminBoundary,
      )?.jobLayer

      interruptWorkflowForCatalog(catalogId)

      // 提交一开始就写入 jobLayer，使标题栏/状态面板立即显示「排队」，不依赖天气瓦片路径
      upsertJobLayer(catalogId, {
        jobId: submitJobId,
        catalogId,
        name: catalogName,
        commandType: 'analysis',
        status: 'queued',
        progress: 5,
        createdAt: submitStartedAt,
        updatedAt: new Date().toISOString(),
        message: '正在提交工作流…',
        metrics: [],
        reportSummary: '正在提交工作流…',
        resultUrl: undefined,
        mapLayerPayload: previousJobLayer?.mapLayerPayload,
      })

      debugLog(
        'runWorkflow',
        catalogId,
        'submitting new workflow',
        'bbox',
        requestBBox,
        'backendLayerId',
        backendLayerId,
      )
      const payload = buildWorkflowPayloadForCatalog(
        catalogId,
        catalogName,
        requestedOutputs,
        requestBBox,
        backendLayerId,
        options.algorithmRequest,
        options.weatherRequest,
      )
      if (options.commandLabel) {
        payload.command_label = options.commandLabel
      }
      const accepted = await submitWorkflow(payload as Parameters<typeof submitWorkflow>[0])
      if (isViewportRefreshStale(options.expectedViewportEpoch)) {
        debugLog('runWorkflow', catalogId, 'discard stale submit after accept', accepted.run_id)
        removeJobLayerById(submitJobId)
        void cancelWorkflowRun(accepted.run_id).catch(() => {})
        return
      }
      debugLog('runWorkflow', catalogId, 'submitted', accepted.run_id)

      removeJobLayerById(submitJobId)
      upsertJobLayer(catalogId, {
        jobId: accepted.run_id,
        catalogId,
        name: catalogName,
        commandType: 'analysis',
        status: 'queued',
        progress: 12,
        createdAt: accepted.created_at,
        updatedAt: accepted.created_at,
        message: accepted.message,
        metrics: [],
        reportSummary: accepted.message,
        resultUrl: undefined,
        // 保留旧 mapLayerPayload，使粒子流/网格填充在新工作流运行期间保持可见
        mapLayerPayload: previousJobLayer?.mapLayerPayload,
      })
      if (catalogId.startsWith('wf-out-')) {
        useWorkflowOutputLayersStore().updateRunStatus(catalogId, accepted.run_id, 'queued')
      }

      activeWorkflowCatalogIds.add(catalogId)
      // 工作流提交成功，清除 429 重试计数
      workflowRetryCounts.delete(catalogId)
      void pollWorkflowRun(accepted.run_id, catalogId, Date.now(), 0, options.expectedViewportEpoch)
      return accepted.run_id
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : '提交 workflow 失败'
      // 天气瓦片路径：已触发刷新，不算失败作业
      if (/天气引擎图层|瓦片按需加载/.test(errMsg)) {
        workflowError.value = errMsg
        throw error
      }
      if (isSubmitTimeoutError(error)) {
        try {
          const activeRuns = await listActiveWorkflowRuns()
          const claimed = claimOrphanWorkflowRun(
            activeRuns.map((run) => ({
              run_id: run.run_id,
              command_label: run.command_label,
              created_at: run.created_at,
              status: run.status,
              layer_id: run.layer_id,
            })),
            {
              commandLabel: options.commandLabel,
              catalogIdHint: backendLayerId,
              submitStartedAt,
            },
          )
          if (claimed?.run_id) {
            removeJobLayerById(submitJobId)
            const reconciledMsg = WORKFLOW_COPY.reconcilingSubmit
            const prevLayer = activeLayers.value.find(
              (l) => l.catalogId === catalogId && !l.isAdminBoundary,
            )?.jobLayer
            upsertJobLayer(catalogId, {
              jobId: claimed.run_id,
              catalogId,
              name: catalogName,
              commandType: 'analysis',
              status: 'queued',
              progress: 12,
              createdAt: claimed.created_at ?? submitStartedAt,
              updatedAt: new Date().toISOString(),
              message: reconciledMsg,
              metrics: [],
              reportSummary: reconciledMsg,
              resultUrl: undefined,
              mapLayerPayload: prevLayer?.mapLayerPayload,
            })
            activeWorkflowCatalogIds.add(catalogId)
            workflowRetryCounts.delete(catalogId)
            void pollWorkflowRun(
              claimed.run_id,
              catalogId,
              Date.now(),
              0,
              options.expectedViewportEpoch,
            )
            return claimed.run_id
          }
        } catch (reconcileError) {
          console.warn('[LayersStore] submit timeout reconcile failed', catalogId, reconcileError)
        }
      }
      if (errMsg.includes('429')) {
        workflowError.value = WORKFLOW_COPY.capacityWaiting
        // 429 时创建 queued jobLayer 让用户看到状态指示，并调度自动重试
        upsertJobLayer(catalogId, {
          jobId: submitJobId,
          catalogId,
          name: catalogName,
          commandType: 'analysis',
          status: 'queued',
          progress: 5,
          createdAt: submitStartedAt,
          updatedAt: new Date().toISOString(),
          message: WORKFLOW_COPY.capacityRetrying,
          metrics: [],
          reportSummary: WORKFLOW_COPY.capacityRetrying,
          resultUrl: undefined,
        })
        scheduleWorkflowRetry(catalogId)
      } else {
        const localized = localizeWorkflowErrorMessage(errMsg)
        workflowError.value = localized
        upsertJobLayer(catalogId, {
          jobId: submitJobId,
          catalogId,
          name: catalogName,
          commandType: 'analysis',
          status: 'failed',
          progress: 0,
          createdAt: submitStartedAt,
          updatedAt: new Date().toISOString(),
          message: localized,
          metrics: [],
          reportSummary: localized,
          diagnosticNotes: [localized],
          resultUrl: undefined,
        })
      }
      throw error
    } finally {
      submittingCatalogIds.delete(catalogId)
    }
  }

  /** 429 容量限制时调度自动重试，最多重试 MAX_WORKFLOW_429_RETRIES 次 */
  function scheduleWorkflowRetry(catalogId: string) {
    const existingTimer = workflowRetryTimers.get(catalogId)
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer)
    }
    const retryCount = workflowRetryCounts.get(catalogId) ?? 0
    if (retryCount >= MAX_WORKFLOW_429_RETRIES) {
      workflowRetryCounts.delete(catalogId)
      upsertJobLayer(catalogId, {
        jobId: `retry-${catalogId}-${Date.now()}`,
        name: getCatalogDisplayName(catalogId),
        commandType: 'analysis',
        status: 'failed',
        progress: 0,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        message: WORKFLOW_COPY.capacityExhausted,
        metrics: [],
        reportSummary: WORKFLOW_COPY.capacityExhausted,
        resultUrl: undefined,
      })
      return
    }
    workflowRetryCounts.set(catalogId, retryCount + 1)
    const timer = window.setTimeout(() => {
      workflowRetryTimers.delete(catalogId)
      void runWorkflowForCatalog(catalogId).catch((err) => {
        console.warn(`[LayersStore] 429 retry failed for ${catalogId}:`, err)
      })
    }, WORKFLOW_429_RETRY_DELAY_MS)
    workflowRetryTimers.set(catalogId, timer)
  }

  async function cancelWorkflowRunForJob(jobId: string, catalogId: string) {
    try {
      if (isLocalSubmitJobId(jobId)) {
        removeJobLayerById(jobId)
        forgetTrackedWorkflowRun(jobId)
        const layer = activeLayers.value.find((l) => l.catalogId === catalogId)
        if (layer?.runGroupId) {
          const g = runLayerGroups.value.find((x) => x.groupId === layer.runGroupId)
          if (g && (!g.runId || isLocalSubmitJobId(g.runId))) {
            g.status = 'cancelled'
            g.dissolvable = true
            g.message = '已取消提交'
            for (const id of [...g.memberInstanceIds]) {
              const m = activeLayers.value.find((l) => l.instanceId === id)
              if (m && !m.importedRaster?.overlayLayerId) {
                const idx = activeLayers.value.findIndex((l) => l.instanceId === id)
                if (idx >= 0) activeLayers.value.splice(idx, 1)
              }
            }
            g.memberInstanceIds = g.memberInstanceIds.filter((id) =>
              activeLayers.value.some((l) => l.instanceId === id),
            )
            if (!g.memberInstanceIds.length) {
              runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== g.groupId)
            }
          }
        }
        scheduleWorkspacePersist()
        return
      }
      const run = await cancelWorkflowRun(jobId)
      const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
      const jobLayer = await buildJobLayer(run, catalogId, { previousJobLayer: existingJobLayer })
      upsertJobLayer(catalogId, jobLayer)
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      cleanupUnproducedRunLayers(jobId)
    } catch (error) {
      workflowError.value = error instanceof Error ? error.message : '取消 workflow 失败'
    }
  }

  async function retryWorkflowRunForJob(jobId: string, catalogId: string) {
    if (submittingCatalogIds.has(catalogId)) return
    // 乐观 ID / 从未真正落库的提交：走重新提交，而不是 /retry
    if (isLocalSubmitJobId(jobId)) {
      removeJobLayerById(jobId)
      forgetTrackedWorkflowRun(jobId)
      return runWorkflowForCatalog(catalogId)
    }
    // 中断旧位置的活跃工作流，允许重试提交新工作流
    interruptWorkflowForCatalog(catalogId)
    workflowError.value = null
    submittingCatalogIds.add(catalogId)
    try {
      const accepted = await retryWorkflowRun(jobId)
      const catalogName =
        runtimeLayerCatalog.value[catalogId]?.display_name ?? getCatalogDisplayName(catalogId)
      upsertJobLayer(catalogId, {
        jobId: accepted.run_id,
        name: catalogName,
        commandType: 'analysis',
        status: 'queued',
        progress: 12,
        createdAt: accepted.created_at,
        updatedAt: accepted.created_at,
        message: accepted.message,
        metrics: [],
        reportSummary: accepted.message,
        resultUrl: undefined,
      })
      activeWorkflowCatalogIds.add(catalogId)
      void pollWorkflowRun(accepted.run_id, catalogId)
      return accepted.run_id
    } catch (error) {
      workflowError.value = error instanceof Error ? error.message : '重试 workflow 失败'
      throw error
    } finally {
      submittingCatalogIds.delete(catalogId)
    }
  }

  function reorderLayers(fromIndex: number, toIndex: number) {
    // Display order is descending (list top = map top = high order)
    const sorted = activeLayers.value.slice().sort((a, b) => b.order - a.order)
    const moved = sorted[fromIndex]
    if (!moved) return

    // 锁定组成员：只允许组内调序
    if (moved.runGroupId && moved.runGroupLocked) {
      const group = runLayerGroups.value.find((g) => g.groupId === moved.runGroupId)
      if (group) {
        const memberSet = new Set(group.memberInstanceIds)
        const target = sorted[toIndex]
        if (!target || !memberSet.has(target.instanceId)) return
        reorderWithinRunGroup(
          moved.runGroupId,
          group.memberInstanceIds.indexOf(moved.instanceId),
          group.memberInstanceIds.indexOf(target.instanceId),
        )
        return
      }
    }

    // 禁止把外部图层插进锁定组块中间
    const target = sorted[toIndex]
    if (
      target?.runGroupId &&
      target.runGroupLocked &&
      (!moved.runGroupId || moved.runGroupId !== target.runGroupId)
    ) {
      return
    }

    const [item] = sorted.splice(fromIndex, 1)
    if (!item) return
    sorted.splice(toIndex, 0, item)
    sorted.forEach((layer, i) => {
      layer.order = sorted.length - 1 - i
    })
    scheduleWorkspacePersist()
  }

  function syncGroupMemberOrders(group: ActiveRunLayerGroup) {
    const members = group.memberInstanceIds
      .map((id) => activeLayers.value.find((l) => l.instanceId === id))
      .filter((l): l is ActiveLayer => Boolean(l))
    if (!members.length) return
    const minOrder = Math.min(...members.map((m) => m.order))
    // memberInstanceIds[0] should sit at list top within the block → highest order
    members.forEach((m, i) => {
      m.order = minOrder + (members.length - 1 - i)
    })
    // 压缩全局 order，保持相对块位置（升序存储，显示时再降序）
    const sorted = activeLayers.value.slice().sort((a, b) => a.order - b.order)
    sorted.forEach((layer, i) => {
      layer.order = i
    })
  }

  function createRunLayerGroup(options: {
    title: string
    targets: Array<{ name: string; productTag: string }>
    sourceLayerId: string
    workflowId: string
    memberCatalogIds?: string[]
  }): { groupId: string; memberInstanceIds: string[]; memberCatalogIds: string[] } {
    const groupId = `run-group-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    const memberInstanceIds: string[] = []
    const memberCatalogIds: string[] = []
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), -1)
    const accent = assignLayerAccent(undefined)

    options.targets.forEach((t, i) => {
      const catalogId =
        options.memberCatalogIds?.[i] ||
        `wf-run-${groupId}-${String(t.productTag || 'result').toLowerCase()}`
      const layer: ActiveLayer = {
        instanceId: genInstanceId(),
        catalogId,
        name: t.name,
        visible: true,
        opacity: 1,
        order: maxOrder + options.targets.length - i,
        isAdminBoundary: false,
        dataState: 'catalog',
        accentColor: accent.accentColor,
        accentGlow: accent.accentGlow,
        chipTone: accent.chipTone,
        runGroupId: groupId,
        runGroupProductTag: t.productTag,
        runGroupLocked: true,
      }
      activeLayers.value.push(layer)
      memberInstanceIds.push(layer.instanceId)
      memberCatalogIds.push(catalogId)
    })

    runLayerGroups.value.push({
      groupId,
      runId: '',
      title: options.title,
      status: 'computing',
      memberInstanceIds,
      dissolvable: false,
      sourceLayerId: options.sourceLayerId,
      workflowId: options.workflowId,
      progress: 0,
      message: '等待计算…',
    })

    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
    if (memberInstanceIds[0]) {
      selectedInstanceId.value = memberInstanceIds[0]
    }
    return { groupId, memberInstanceIds, memberCatalogIds }
  }

  function bindRunIdToGroup(groupId: string, runId: string) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    g.runId = runId
    scheduleWorkspacePersist()
  }

  /**
   * 停止/失败后清理未产出占位图层：无 overlay 的组成员移除；
   * 已有栅格产物的成员保留并解锁，便于用户继续查看部分结果。
   */
  function cleanupUnproducedRunLayers(runId: string) {
    if (!runId) return
    progressiveMaterializeAt.delete(runId)
    progressiveMaterializeInFlight.delete(runId)

    const g = runLayerGroups.value.find((x) => x.runId === runId)
    if (!g) return

    const removeIds: string[] = []
    for (const instanceId of [...g.memberInstanceIds]) {
      const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
      if (!layer) {
        removeIds.push(instanceId)
        continue
      }
      if (!layer.importedRaster?.overlayLayerId) {
        removeIds.push(instanceId)
      } else {
        layer.runGroupLocked = false
        if (layer.name && !layer.name.includes('（部分）')) {
          layer.name = `${layer.name}（部分）`
        }
      }
    }
    for (const instanceId of removeIds) {
      // 占位无 overlay：removeLayer 不会删后端文件
      removeLayer(instanceId)
    }

    const left = runLayerGroups.value.find((x) => x.groupId === g.groupId)
    if (left) {
      left.dissolvable = true
      left.status = left.status === 'failed' ? 'failed' : 'cancelled'
      if (!left.memberInstanceIds.length) {
        runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== left.groupId)
      }
    }
    scheduleWorkspacePersist()
  }

  let workspacePersistTimer: ReturnType<typeof setTimeout> | null = null

  function flushWorkspacePersistNow() {
    if (typeof window === 'undefined') return
    if (workspacePersistTimer != null) {
      window.clearTimeout(workspacePersistTimer)
      workspacePersistTimer = null
    }
    saveWorkspaceSnapshot(buildWorkspaceSnapshot(activeLayers.value, runLayerGroups.value))
  }

  function scheduleWorkspacePersist() {
    if (typeof window === 'undefined') return
    if (workspacePersistTimer != null) window.clearTimeout(workspacePersistTimer)
    workspacePersistTimer = window.setTimeout(() => {
      workspacePersistTimer = null
      flushWorkspacePersistNow()
    }, 400)
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('pagehide', () => flushWorkspacePersistNow())
  }

  function restoreCatalogLayerFromSnapshot(
    saved: PersistedCatalogLayer,
    instanceIdMap?: Map<string, string>,
  ) {
    if (isCatalogDismissed(saved.catalogId)) return
    if (
      activeLayers.value.some(
        (l) => l.catalogId === saved.catalogId && !isLocalImport(l) && !l.jobLayer,
      )
    ) {
      return
    }
    const libraryItem = layerLibraryMap.value.get(saved.catalogId)
    const accent = saved.accentColor
      ? {
          accentColor: saved.accentColor,
          accentGlow: saved.accentGlow ?? 'rgba(255, 255, 255, 0.2)',
          chipTone: saved.chipTone ?? 'rgba(255, 255, 255, 0.1)',
        }
      : assignLayerAccent(libraryItem?.accentColor)
    const instanceId = genInstanceId()
    instanceIdMap?.set(saved.instanceId, instanceId)
    const layer: ActiveLayer = {
      instanceId,
      catalogId: saved.catalogId,
      name: saved.name,
      visible: saved.visible !== false,
      opacity: typeof saved.opacity === 'number' ? saved.opacity : 1,
      order: typeof saved.order === 'number' ? saved.order : activeLayers.value.length,
      isAdminBoundary: false,
      dataState: saved.dataState === 'real' ? 'real' : 'catalog',
      accentColor: accent.accentColor,
      accentGlow: accent.accentGlow,
      chipTone: accent.chipTone,
      runGroupId: saved.runGroupId,
      runGroupProductTag: saved.runGroupProductTag,
    }
    activeLayers.value.push(layer)
    if (isWeatherEngineLayer(saved.catalogId) && layer.visible) {
      weatherTileManager.setLayerActive(saved.catalogId, true)
      nextTick(() => {
        window.setTimeout(() => {
          weatherTileManager.setViewport(
            saved.catalogId,
            currentMapCenter.value,
            currentMapZoom.value,
            currentHour.value,
            undefined,
            currentMapBBox.value,
            weatherProviderArg(saved.catalogId),
          )
        }, 0)
      })
    }
  }

  function restoreRunGroupsFromSnapshot(
    snap: NonNullable<ReturnType<typeof loadWorkspaceSnapshot>>,
    instanceIdMap: Map<string, string>,
  ) {
    for (const savedGroup of snap.groups || []) {
      if (savedGroup.runId && isRunDismissed(savedGroup.runId)) continue
      if (
        runLayerGroups.value.some(
          (g) => g.groupId === savedGroup.groupId || g.runId === savedGroup.runId,
        )
      ) {
        continue
      }
      const memberInstanceIds = (savedGroup.memberInstanceIds || [])
        .map((oldId) => instanceIdMap.get(oldId))
        .filter((id): id is string => Boolean(id))
      if (!memberInstanceIds.length) {
        for (const layer of activeLayers.value) {
          if (layer.runGroupId === savedGroup.groupId) {
            memberInstanceIds.push(layer.instanceId)
          }
        }
      }
      if (!memberInstanceIds.length) continue
      runLayerGroups.value.push({
        groupId: savedGroup.groupId,
        runId: savedGroup.runId || '',
        title: savedGroup.title,
        status: savedGroup.status === 'computing' ? 'ready' : savedGroup.status || 'ready',
        memberInstanceIds,
        dissolvable: true,
        sourceLayerId: savedGroup.sourceLayerId,
        workflowId: savedGroup.workflowId,
        progress: savedGroup.progress,
        message: savedGroup.message,
      })
      for (const id of memberInstanceIds) {
        const layer = activeLayers.value.find((l) => l.instanceId === id)
        if (layer) layer.runGroupId = savedGroup.groupId
      }
    }
  }

  function hydrateWorkspaceFromSnapshot(): Map<string, string> {
    const snap = loadWorkspaceSnapshot()
    const instanceIdMap = new Map<string, string>()
    if (!snap) return instanceIdMap
    const hasRaster = snap.layers?.length > 0
    const hasCatalog = (snap.catalogLayers?.length ?? 0) > 0
    const hasVector = (snap.vectorLayers?.length ?? 0) > 0
    if (!hasRaster && !hasCatalog && !hasVector) return instanceIdMap

    const existingOverlayIds = new Set(
      activeLayers.value
        .map((l) => l.importedRaster?.overlayLayerId)
        .filter((id): id is string => Boolean(id)),
    )

    for (const saved of snap.layers as PersistedActiveLayer[]) {
      if (!saved.importedRaster?.overlayLayerId) continue
      if (isOverlayDismissed(saved.importedRaster.overlayLayerId)) continue
      if (existingOverlayIds.has(saved.importedRaster.overlayLayerId)) continue

      const instanceId = genInstanceId()
      instanceIdMap.set(saved.instanceId, instanceId)
      const layer: ActiveLayer = {
        instanceId,
        catalogId: saved.catalogId,
        name: saved.name,
        visible: saved.visible !== false,
        opacity: typeof saved.opacity === 'number' ? saved.opacity : 1,
        order: typeof saved.order === 'number' ? saved.order : activeLayers.value.length,
        isAdminBoundary: false,
        dataState: 'imported',
        importedRaster: buildImportedRasterPayload(saved.importedRaster.overlayLayerId, {
          bounds: saved.importedRaster.bounds,
          fileName: saved.importedRaster.fileName || saved.name,
          sourceCrs: saved.importedRaster.sourceCrs,
          lngOffset: saved.importedRaster.lngOffset,
          latOffset: saved.importedRaster.latOffset,
          nativeStep: saved.importedRaster.nativeStep,
          timeList: saved.importedRaster.timeList,
          followPolicy: saved.importedRaster.followPolicy,
          effectiveTimeLabel: saved.importedRaster.effectiveTimeLabel,
        }),
        accentColor: saved.accentColor,
        accentGlow: saved.accentGlow,
        chipTone: saved.chipTone,
        runGroupId: saved.runGroupId,
        runGroupProductTag: saved.runGroupProductTag,
        runGroupLocked: false,
      }
      activeLayers.value.push(layer)
      existingOverlayIds.add(saved.importedRaster.overlayLayerId)
    }

    for (const saved of snap.catalogLayers ?? []) {
      restoreCatalogLayerFromSnapshot(saved, instanceIdMap)
    }

    restoreRunGroupsFromSnapshot(snap, instanceIdMap)

    if (activeLayers.value.length && sidebarView.value === 'empty') {
      sidebarView.value = 'active'
    }
    return instanceIdMap
  }

  async function hydrateVectorLayersFromSnapshot(instanceIdMap: Map<string, string>) {
    const snap = loadWorkspaceSnapshot()
    if (!snap?.vectorLayers?.length) return

    const existingBackendIds = new Set(
      activeLayers.value
        .map((l) => l.importedVector?.backendLayerId)
        .filter((id): id is string => Boolean(id)),
    )

    const { fetchImportedLayerGeojson, fetchImportedLayerMeta } =
      await import('../../data-manager/core/api')

    for (const saved of snap.vectorLayers as PersistedVectorLayer[]) {
      if (!saved.backendLayerId) continue
      if (isVectorDismissed(saved.backendLayerId)) continue
      if (existingBackendIds.has(saved.backendLayerId)) continue

      try {
        const [geojson, meta] = await Promise.all([
          fetchImportedLayerGeojson(saved.backendLayerId, true),
          fetchImportedLayerMeta(saved.backendLayerId).catch(() => null),
        ])
        const instanceId = genInstanceId()
        instanceIdMap.set(saved.instanceId, instanceId)
        const displayName =
          saved.name ||
          (typeof meta?.source_name === 'string' ? meta.source_name : undefined) ||
          saved.fileName ||
          saved.backendLayerId
        const payload = buildImportedVectorPayload(geojson, saved.fileName || displayName, {
          backendLayerId: saved.backendLayerId,
          featureCount: typeof meta?.feature_count === 'number' ? meta.feature_count : undefined,
        })
        if (saved.truncated ?? meta?.truncated) payload.truncated = true
        if (saved.style) payload.style = saved.style

        const accent = saved.accentColor
          ? {
              accentColor: saved.accentColor,
              accentGlow: saved.accentGlow ?? 'rgba(255, 255, 255, 0.2)',
              chipTone: saved.chipTone ?? 'rgba(255, 255, 255, 0.1)',
            }
          : assignLayerAccent('#7ee0a8')

        activeLayers.value.push({
          instanceId,
          catalogId: saved.catalogId || saved.backendLayerId,
          name: displayName,
          visible: saved.visible !== false,
          opacity: typeof saved.opacity === 'number' ? saved.opacity : 0.85,
          order: typeof saved.order === 'number' ? saved.order : activeLayers.value.length,
          isAdminBoundary: false,
          dataState: 'imported',
          importedVector: payload,
          accentColor: accent.accentColor,
          accentGlow: accent.accentGlow,
          chipTone: accent.chipTone,
        })
        existingBackendIds.add(saved.backendLayerId)
      } catch (err) {
        console.warn('[layers] restore vector layer failed', saved.backendLayerId, err)
      }
    }

    if (activeLayers.value.length && sidebarView.value === 'empty') {
      sidebarView.value = 'active'
    }
  }

  function refreshRunGroupDissolvable(groupId: string) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    const members = g.memberInstanceIds
      .map((id) => activeLayers.value.find((l) => l.instanceId === id))
      .filter((l): l is ActiveLayer => Boolean(l))
    const allDisplayable =
      members.length > 0 && members.every((m) => Boolean(m.importedRaster?.overlayLayerId))
    if (g.status === 'failed' || g.status === 'cancelled') {
      g.dissolvable = true
      members.forEach((m) => {
        m.runGroupLocked = false
      })
      return
    }
    if (g.status === 'ready' && allDisplayable) {
      g.dissolvable = true
      members.forEach((m) => {
        m.runGroupLocked = false
      })
    }
  }

  function updateRunGroupFromJob(
    runId: string,
    job: Pick<JobLayerItem, 'status' | 'progress' | 'message' | 'nodeProgress'>,
  ) {
    const g = runLayerGroups.value.find((x) => x.runId === runId)
    if (!g) return
    if (job.status === 'succeeded') g.status = 'ready'
    else if (job.status === 'failed') g.status = 'failed'
    else if (job.status === 'cancelled') g.status = 'cancelled'
    else g.status = 'computing'
    if (typeof job.progress === 'number') g.progress = job.progress
    const latest = pickLatestNodeProgress(job.nodeProgress)
    const shell = formatProgressShell({
      progress: job.progress,
      message: job.message,
      stage: latest?.stage,
      nodeLabel: latest?.nodeLabel,
      detail: latest?.detail,
    })
    if (shell) g.message = shell
    else if (job.message) g.message = job.message
    refreshRunGroupDissolvable(g.groupId)
  }

  function dissolveRunGroup(groupId: string) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    for (const id of g.memberInstanceIds) {
      const layer = activeLayers.value.find((l) => l.instanceId === id)
      if (!layer) continue
      layer.runGroupId = undefined
      layer.runGroupProductTag = undefined
      layer.runGroupLocked = undefined
    }
    runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== groupId)
    scheduleWorkspacePersist()
  }

  function reorderWithinRunGroup(groupId: string, fromMemberIndex: number, toMemberIndex: number) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    if (
      fromMemberIndex < 0 ||
      toMemberIndex < 0 ||
      fromMemberIndex >= g.memberInstanceIds.length ||
      toMemberIndex >= g.memberInstanceIds.length
    ) {
      return
    }
    const ids = [...g.memberInstanceIds]
    const [moved] = ids.splice(fromMemberIndex, 1)
    if (!moved) return
    ids.splice(toMemberIndex, 0, moved)
    g.memberInstanceIds = ids
    syncGroupMemberOrders(g)
    scheduleWorkspacePersist()
  }

  /** 将整组在 TOC 中上下移动：toAnchorInstanceId 为落点图层（组外）的 instanceId */
  function moveRunGroupBlock(
    groupId: string,
    toAnchorInstanceId: string | null,
    placeAfter: boolean,
  ) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    const memberSet = new Set(g.memberInstanceIds)
    const sorted = activeLayers.value.slice().sort((a, b) => a.order - b.order)
    const block = sorted.filter((l) => memberSet.has(l.instanceId))
    const rest = sorted.filter((l) => !memberSet.has(l.instanceId))
    if (!block.length) return

    let insertAt = rest.length
    if (toAnchorInstanceId) {
      const idx = rest.findIndex((l) => l.instanceId === toAnchorInstanceId)
      if (idx >= 0) insertAt = placeAfter ? idx + 1 : idx
    }
    const next = [...rest.slice(0, insertAt), ...block, ...rest.slice(insertAt)]
    next.forEach((layer, i) => {
      layer.order = i
    })
    g.memberInstanceIds = block.map((l) => l.instanceId)
    scheduleWorkspacePersist()
  }

  function findRunGroupByMember(instanceId: string): ActiveRunLayerGroup | null {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer?.runGroupId) return null
    return runLayerGroups.value.find((g) => g.groupId === layer.runGroupId) ?? null
  }

  function findRunGroupById(groupId: string): ActiveRunLayerGroup | null {
    return runLayerGroups.value.find((g) => g.groupId === groupId) ?? null
  }

  /** 判断 catalogId 是否由 weatherengine 后端支持（用于自动运行工作流） */
  function isWeatherEngineLayer(catalogId: string): boolean {
    return isWeatherEngineCatalogId(catalogId, getRuntimeLayerDescriptor(catalogId))
  }

  function reconcileActiveWeatherLayers() {
    const cc = currentMapCenter.value
    const cz = currentMapZoom.value
    const ch = currentHour.value
    const cb = currentMapBBox.value

    for (const layer of activeLayers.value) {
      if (layer.isAdminBoundary || isLocalImport(layer)) continue
      if (layer.visible && isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.setLayerActive(layer.catalogId, true)
        weatherTileManager.setViewport(
          layer.catalogId,
          cc,
          cz,
          ch,
          undefined,
          cb,
          weatherProviderArg(layer.catalogId),
        )
        if (supportsParticleFlow(layer.catalogId)) {
          enableParticleIfUnset(layer.catalogId)
        }
      } else if (!isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.clearLayer(layer.catalogId)
      }
    }
  }

  /** After user changes per-layer weather provider preference, refresh tiles + point query. */
  function applyWeatherProviderPreference(catalogId: string, providerId: string) {
    weatherSourcePrefs.setProvider(catalogId, providerId === 'auto' ? 'auto' : providerId)
    const layer = activeLayers.value.find((item) => item.catalogId === catalogId && item.visible)
    if (layer && isWeatherEngineLayer(catalogId)) {
      weatherTileManager.setViewport(
        catalogId,
        currentMapCenter.value,
        currentMapZoom.value,
        currentHour.value,
        undefined,
        currentMapBBox.value,
        weatherProviderArg(catalogId),
      )
    }
    const last = lastPointWeatherQuery.value
    if (last && last.catalogId === catalogId) {
      void fetchPointWeather(last.lng, last.lat, catalogId)
    } else if (pointWeather.value) {
      // Provider changed but no remembered click — clear stale point card.
      clearPointWeather()
    }
  }

  function supportsMapLayerResult(catalogId: string) {
    return supportsMapLayerCapability(getRuntimeLayerDescriptor(catalogId))
  }

  function supportsViewportDrivenRefresh(catalogId: string) {
    return supportsViewportDrivenRefreshCapability(getRuntimeLayerDescriptor(catalogId))
  }

  /** 判断 catalogId 是否支持粒子流渲染（所有 wind-field 变体都支持） */
  function supportsParticleFlow(catalogId: string): boolean {
    const descriptor = getRuntimeLayerDescriptor(catalogId)
    if (descriptor) {
      return supportsParticleFlowCapability(descriptor)
    }
    // 运行时目录未加载时的静态兖底：wind-field* 前缀始终支持粒子流，
    // 避免后端目录请求延迟/失败导致三态开关从分析面板消失。
    return catalogId.startsWith('wind-field')
  }

  /** 获取图层的 primary_metric 字段名（如 wind_speed_80m），从 capabilities 读取 */
  function getLayerPrimaryMetric(catalogId: string): string | null {
    return getRuntimeLayerDescriptor(catalogId)?.capabilities?.primary_metric ?? null
  }

  // ─── 点天气查询（单工作流管理：同一时间只允许一个点查询运行） ──────────────
  const pointWeather = ref<WeatherPointResponse | null>(null)
  const pointWeatherLoading = ref(false)
  const pointWeatherError = ref<string | null>(null)
  const lastPointWeatherQuery = ref<{ lng: number; lat: number; catalogId: string } | null>(null)
  let pointWeatherAbortController: AbortController | null = null

  /** 清除点天气查询结果与状态 */
  function clearPointWeather() {
    if (pointWeatherAbortController) {
      pointWeatherAbortController.abort()
      pointWeatherAbortController = null
    }
    pointWeather.value = null
    pointWeatherError.value = null
    pointWeatherLoading.value = false
    lastPointWeatherQuery.value = null
  }

  /**
   * 提交点天气查询（作为单一工作流管理）。
   * 每次调用会中断上一次尚未完成的查询，确保同一时间只有一条点查询工作流在运行。
   */
  async function fetchPointWeather(
    lng: number,
    lat: number,
    catalogId: string,
    options?: { forecastHours?: number },
  ) {
    if (!isWeatherEngineLayer(catalogId)) {
      clearPointWeather()
      return
    }
    // 中断上一次查询，保证单工作流约束
    if (pointWeatherAbortController) {
      pointWeatherAbortController.abort()
    }
    const controller = new AbortController()
    pointWeatherAbortController = controller
    pointWeatherLoading.value = true
    pointWeatherError.value = null
    lastPointWeatherQuery.value = { lng, lat, catalogId }
    // 覆盖时间轴当前 hour（0-based）及短时预报；至少 6 小时
    const forecastHours = Math.min(
      48,
      Math.max(6, Math.floor(options?.forecastHours ?? currentHour.value + 1)),
    )
    try {
      const weather = await getWeatherPoint({
        layer_id: catalogId,
        latitude: lat,
        longitude: lng,
        forecast_hours: forecastHours,
        place_name: `${lat.toFixed(3)}, ${lng.toFixed(3)}`,
        provider: weatherProviderQuery(catalogId),
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      pointWeather.value = weather
    } catch (error) {
      if (controller.signal.aborted) return
      pointWeather.value = null
      pointWeatherError.value =
        error instanceof Error ? error.message : 'Failed to load point weather'
    } finally {
      if (!controller.signal.aborted) {
        pointWeatherLoading.value = false
      }
      if (pointWeatherAbortController === controller) {
        pointWeatherAbortController = null
      }
    }
  }

  /** 刷新所有活跃的地图型工作流图层（视口变化时调用），天气图层由 tile manager 处理，不在此处刷新 */
  async function refreshActiveWeatherWorkflows(expectedViewportEpoch?: number) {
    const epoch = expectedViewportEpoch ?? getViewportRefreshEpoch()
    const activeMapLayers = activeLayers.value.filter(
      (layer) =>
        layer.visible &&
        supportsViewportDrivenRefresh(layer.catalogId) &&
        !isWeatherEngineLayer(layer.catalogId) &&
        layer.jobLayer,
    )
    debugLog(
      'refreshActive',
      'layers',
      activeMapLayers.map((l) => l.catalogId),
      'bbox',
      currentMapBBox.value,
      'epoch',
      epoch,
    )

    for (const layer of activeMapLayers) {
      if (isViewportRefreshStale(epoch)) {
        debugLog('refreshActive', 'abort stale epoch', epoch, 'current', getViewportRefreshEpoch())
        return
      }
      if (!canRunCatalog(layer.catalogId)) continue
      try {
        await runWorkflowForCatalog(layer.catalogId, { expectedViewportEpoch: epoch })
      } catch (error) {
        // 单个图层失败不影响其他图层
        console.warn(`[LayersStore] Failed to refresh map workflow for ${layer.catalogId}:`, error)
      }
    }
  }

  // 时间轴小时变化时，通知 tile manager 刷新所有可见天气图层。
  // 小时变化是离散用户操作，需立即执行；取消挂起的视口防抖，避免用旧 hour 覆盖。
  watch(currentHour, (hour) => {
    flushWeatherTileViewports(hour)
  })

  /** catalogId → 工作流状态映射，用于 library 卡片显示自动运行反馈 */
  const catalogJobStatus = computed(() => {
    const map = new Map<string, JobStatus>()
    // 先写入全局 jobLayers（含孤儿/已完成），再以活跃图层上的 jobLayer 覆盖，保证最新
    for (const job of jobLayers.value) {
      if (job.catalogId) map.set(job.catalogId, job.status)
    }
    for (const layer of activeLayers.value) {
      if (layer.jobLayer) {
        map.set(layer.catalogId, layer.jobLayer.status)
      }
    }
    return map
  })

  const catalogRunReadiness = computed(() => {
    const map = new Map<string, string>()
    for (const descriptor of Object.values(runtimeLayerCatalog.value)) {
      map.set(descriptor.layer_id, descriptor.run_readiness ?? 'ready')
    }
    return map
  })

  return {
    // State
    activeLayers,
    runLayerGroups,
    sidebarView,
    selectedInstanceId,
    jobLayers,
    currentHour,
    workflowError,
    workflowProgressTimeSeek,
    isSubmitting,
    workflowSummary,
    runtimeLayerCatalogLoading,
    particleFlowCatalogId,
    windDisplayMode,
    currentMapCenter,
    currentMapBBox,
    currentMapZoom,
    smoothRendering,
    // Computed
    activeLayersDisplay,
    selectedLayerDisplay,
    activeLayerCount,
    sidebarViewLabel,
    catalogJobStatus,
    catalogRunReadiness,
    // Data
    layerLibrary,
    layerCategories: LAYER_CATEGORIES,
    // Actions
    addLayer,
    addImportedVectorLayer,
    addImportedRasterLayer,
    getImportedVectorGeojson,
    updateImportedVectorGeojson,
    setImportedVectorStyle,
    removeLayer,
    toggleLayerVisibility,
    setAllLayerVisibility,
    removeAllLayers,
    setLayerOpacity,
    setLayerPaletteOverride,
    setLayerOrder,
    setLayerDisplayName,
    bringLayerToFront,
    sendLayerToBack,
    selectLayer,
    setSidebarView,
    setCurrentHour,
    setJobLayers,
    ensureRuntimeLayerCatalog,
    reorderLayers,
    createRunLayerGroup,
    bindRunIdToGroup,
    dissolveRunGroup,
    reorderWithinRunGroup,
    moveRunGroupBlock,
    findRunGroupByMember,
    findRunGroupById,
    refreshRunGroupDissolvable,
    updateRunGroupFromJob,
    runWorkflowForCatalog,
    cancelWorkflowRunForJob,
    retryWorkflowRunForJob,
    stopWorkflowPolling,
    getCatalogRunBlockReason,
    canRunCatalog,
    supportsAnalysisWorkflow,
    isWeatherEngineLayer,
    supportsMapLayerResult,
    supportsViewportDrivenRefresh,
    supportsParticleFlow,
    getLayerPrimaryMetric,
    setWindDisplayMode,
    toggleParticleFlow,
    setParticleFlow,
    setSmoothRendering,
    resolveBackendLayerId,
    resolveEffectiveDescriptor,
    applyWeatherProviderPreference,
    // 点天气查询（单工作流管理）
    pointWeather,
    pointWeatherLoading,
    pointWeatherError,
    fetchPointWeather,
    clearPointWeather,
    setMapViewport,
    handleViewportChange,
    flushWeatherTileViewports,
    refreshActiveWeatherWorkflows,
    cleanupUnproducedRunLayers,
    scheduleWorkspacePersist,
    // 外部工作流跟踪与恢复
    registerExternalWorkflowRun,
    restoreActiveWorkflows,
  }
})
