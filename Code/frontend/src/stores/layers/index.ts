import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  fetchLayerCatalog,
  getWorkflowEvents,
  getWorkflowRun,
  submitWorkflow,
  cancelWorkflowRun,
  retryWorkflowRun,
  getWeatherPoint,
} from '../../services/runtime-api'
import type { BoundingBox, RuntimeLayerDescriptor, WeatherPointResponse, WorkflowEvent } from '../../services/runtime-api'
import { LAYER_CATEGORIES, LAYER_LIBRARY } from './catalog'
import { buildJobLayer } from './result-adapter'
import type {
  ActiveLayer,
  ActiveLayerDisplay,
  JobLayerItem,
  JobStatus,
  LayerCatalogItem,
  LayerHotspot,
  LayerSidebarView,
  RuntimeLayerLibraryItem,
  WorkflowSummary,
} from './types'

function genInstanceId() {
  return crypto.randomUUID()
}

function isTerminalStatus(status: string) {
  // retry_pending 是非终态（等待重试），不应包含在此处
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

// ─── 真实数据适配器 ──────────────────────────────────────────────────────────

/** 从 jobLayer 提取真实数据显示数据 */
function buildRealLayerDisplay(layer: ActiveLayer, item: RuntimeLayerLibraryItem): Partial<ActiveLayerDisplay> {
  const jobLayer = layer.jobLayer
  if (!jobLayer) return {}

  const primaryMetric = jobLayer.metrics?.find((m) => m.label !== '队列')
  const metricValue = primaryMetric?.value ?? '--'
  const renderHint = jobLayer.mapLayerPayload?.renderHint
  const resultDto = asRecord(jobLayer.resultDto)
  const providerKey = typeof resultDto?.provider_key === 'string' ? resultDto.provider_key : null
  const resultCategory = typeof resultDto?.result_category === 'string' ? resultDto.result_category : null
  const providerSummary = typeof resultDto?.summary === 'string' ? resultDto.summary : null
  const providerStatusLabel = typeof resultDto?.status_label === 'string' ? resultDto.status_label : null
  const providerConfidenceLabel = typeof resultDto?.confidence_label === 'string' ? resultDto.confidence_label : null
  const isSampleProvider = item.backendStatus === 'sample' || (resultCategory === 'provider' && providerKey?.startsWith('lab_output'))
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
    summary: providerSummary ?? jobLayer.resultView?.summary ?? jobLayer.reportSummary ?? jobLayer.message ?? item.description,
    statusLabel: jobLayer.status === 'succeeded'
      ? (isSampleProvider ? (providerStatusLabel ?? '样板结果') : '真实数据')
      : jobLayer.status === 'failed'
        ? '数据异常'
        : jobLayer.status === 'cancelled'
          ? '任务已取消'
          : '任务处理中',
    trendLabel: jobLayer.status === 'succeeded'
      ? (isSampleProvider ? '样板 provider 已执行，可用于联调验收' : '最新工作流结果已接入')
      : jobLayer.status === 'failed'
        ? '最近一次运行失败'
        : '等待工作流返回结果',
    sourceLabel: isSampleProvider && providerKey ? `样板 Provider · ${providerKey}` : item.sourceLabel,
    confidenceLabel,
    availabilityState: jobLayer.status === 'succeeded' ? 'ready' : jobLayer.status === 'failed' ? 'empty' : 'partial',
    availabilityLabel: jobLayer.status === 'succeeded' ? '完整数据' : jobLayer.status === 'failed' ? '数据异常' : '加载中',
    availabilityDescription: jobLayer.status === 'succeeded'
      ? (isSampleProvider
        ? '样板 provider 已生成结果，可用于联调与界面验收，但不代表正式生产数据。'
        : (jobLayer.message || '工作流结果已生成。'))
      : jobLayer.status === 'failed'
        ? (jobLayer.diagnosticNotes?.[0] ?? '数据加载失败')
        : (jobLayer.message || '正在加载工作流结果...'),
    observationTimeLabel: jobLayer.reportSummary?.match(/\d{2}:\d{2}/)?.[0] ?? formatClockLabel(jobLayer.updatedAt),
    missingFieldsLabel: jobLayer.status === 'succeeded' ? '无缺失字段' : (jobLayer.diagnosticNotes?.join(' / ') ?? '待加载'),
    hotspots: extractLayerHotspots(layer, item, metricValue),
  }
}

// 事件增量消费主循环：高频拉取事件，低频同步权威状态。
const EVENT_POLL_ACTIVE_INTERVAL_MS = 1200
const EVENT_POLL_IDLE_INTERVAL_MS = 2600
const STATUS_SYNC_INTERVAL_MS = 9000
const EVENT_POLL_MAX_DURATION_MS = 600_000
const MAX_EVENT_MESSAGE_COUNT = 5
const MAX_CONSECUTIVE_POLL_ERRORS = 3
const MAP_LAYER_RENDER_TYPES = new Set([
  'grid_fill',
  'point',
  'point_symbol',
  'particle_flow',
  'heatmap',
  'vector',
])

function getCatalogDisplayName(catalogId: string) {
  return LAYER_LIBRARY.find((item) => item.catalogId === catalogId)?.name ?? catalogId
}

function isBlockedRunReadiness(readiness?: string | null) {
  return readiness === 'blocked'
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function isRecognizedJobStatus(status: unknown): status is JobStatus {
  return typeof status === 'string'
    && ['running', 'succeeded', 'failed', 'queued', 'cancelled', 'retry_pending'].includes(status)
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

function isWeatherEngineCatalogId(catalogId: string): boolean {
  if (catalogId.startsWith('wind-field')) return true
  if (catalogId.startsWith('temperature')) return true
  return ['precipitation', 'pressure', 'humidity', 'visibility'].includes(catalogId)
}

const WEATHER_REQUEST_WORLD_LAT_LIMIT = 85
const WEATHER_REQUEST_VIEWPORT_EXPANSION = 1.4
const WEATHER_REQUEST_TILE_STEP_RATIO = 0.5
const WEATHER_PREFETCH_CONCURRENCY = 2
const WEATHER_PREFETCH_MAX_QUEUE = 30
const WEATHER_TILE_CACHE_MAX_PER_BUCKET = 50
const WEATHER_REQUEST_BUCKETS: Array<{ key: string; maxZoom: number; lonSpan: number; latSpan: number }> = [
  { key: 'z0', maxZoom: 2.5, lonSpan: 360, latSpan: 170 },
  { key: 'z1', maxZoom: 4.0, lonSpan: 180, latSpan: 120 },
  { key: 'z2', maxZoom: 5.5, lonSpan: 120, latSpan: 80 },
  { key: 'z3', maxZoom: 7.0, lonSpan: 60, latSpan: 40 },
  { key: 'z4', maxZoom: 8.5, lonSpan: 30, latSpan: 20 },
  { key: 'z5', maxZoom: Number.POSITIVE_INFINITY, lonSpan: 15, latSpan: 10 },
]

interface WeatherTileSpec {
  zoomBucketKey: string
  tileKey: string
  bbox: BoundingBox
  center: { lng: number; lat: number }
  lonSpan: number
  latSpan: number
}

interface WeatherTileCacheEntry {
  catalogId: string
  spec: WeatherTileSpec
  status: JobStatus
  jobId?: string
  updatedAt: string
  geojsonData?: Record<string, unknown>
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function roundBboxCoordinate(value: number) {
  return Math.round(value * 1000) / 1000
}

function areBoundingBoxesEqual(a: BoundingBox | null | undefined, b: BoundingBox | null | undefined) {
  if (!a || !b) return false
  return a.west === b.west
    && a.south === b.south
    && a.east === b.east
    && a.north === b.north
}

function getBoundingBoxSpans(bbox: BoundingBox) {
  return {
    lonSpan: Math.max(0.1, bbox.east - bbox.west),
    latSpan: Math.max(0.1, bbox.north - bbox.south),
  }
}

function getWeatherRequestBucket(zoom: number) {
  return WEATHER_REQUEST_BUCKETS.find((bucket) => zoom <= bucket.maxZoom) ?? WEATHER_REQUEST_BUCKETS[WEATHER_REQUEST_BUCKETS.length - 1]
}

function snapRequestCenter(value: number, span: number, min: number, max: number) {
  const halfSpan = span / 2
  const step = Math.max(0.1, span * WEATHER_REQUEST_TILE_STEP_RATIO)
  const snapped = Math.round(value / step) * step
  return clampNumber(snapped, min + halfSpan, max - halfSpan)
}

function buildWeatherTileSpec(
  center: { lng: number; lat: number },
  viewportBBox: BoundingBox,
  zoom: number,
): WeatherTileSpec {
  const bucket = getWeatherRequestBucket(zoom)
  if (bucket.lonSpan >= 360) {
    const bbox = {
      west: -180,
      south: -WEATHER_REQUEST_WORLD_LAT_LIMIT,
      east: 180,
      north: WEATHER_REQUEST_WORLD_LAT_LIMIT,
      crs: 'EPSG:4326',
    }
    return {
      zoomBucketKey: bucket.key,
      tileKey: `${bucket.key}:world`,
      bbox,
      center: { lng: 0, lat: 0 },
      lonSpan: 360,
      latSpan: WEATHER_REQUEST_WORLD_LAT_LIMIT * 2,
    }
  }

  const viewportSpans = getBoundingBoxSpans(viewportBBox)
  const lonSpan = Math.min(360, Math.max(bucket.lonSpan, viewportSpans.lonSpan * WEATHER_REQUEST_VIEWPORT_EXPANSION))
  const latSpan = Math.min(WEATHER_REQUEST_WORLD_LAT_LIMIT * 2, Math.max(bucket.latSpan, viewportSpans.latSpan * WEATHER_REQUEST_VIEWPORT_EXPANSION))

  const snappedLng = snapRequestCenter(center.lng, lonSpan, -180, 180)
  const snappedLat = snapRequestCenter(center.lat, latSpan, -WEATHER_REQUEST_WORLD_LAT_LIMIT, WEATHER_REQUEST_WORLD_LAT_LIMIT)

  const bbox = {
    west: roundBboxCoordinate(snappedLng - lonSpan / 2),
    south: roundBboxCoordinate(snappedLat - latSpan / 2),
    east: roundBboxCoordinate(snappedLng + lonSpan / 2),
    north: roundBboxCoordinate(snappedLat + latSpan / 2),
    crs: 'EPSG:4326',
  }
  return {
    zoomBucketKey: bucket.key,
    tileKey: `${bucket.key}:${roundBboxCoordinate(snappedLng)}:${roundBboxCoordinate(snappedLat)}`,
    bbox,
    center: { lng: snappedLng, lat: snappedLat },
    lonSpan,
    latSpan,
  }
}

function buildNeighborWeatherTileSpecs(primaryTile: WeatherTileSpec): WeatherTileSpec[] {
  if (primaryTile.tileKey.endsWith(':world')) return []
  const lonStep = Math.max(0.1, primaryTile.lonSpan * WEATHER_REQUEST_TILE_STEP_RATIO)
  const latStep = Math.max(0.1, primaryTile.latSpan * WEATHER_REQUEST_TILE_STEP_RATIO)
  const seen = new Set<string>()
  const specs: WeatherTileSpec[] = []
  for (const [dx, dy] of [[-1, -1], [0, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1]]) {
    const nextCenterLng = snapRequestCenter(primaryTile.center.lng + dx * lonStep, primaryTile.lonSpan, -180, 180)
    const nextCenterLat = snapRequestCenter(primaryTile.center.lat + dy * latStep, primaryTile.latSpan, -WEATHER_REQUEST_WORLD_LAT_LIMIT, WEATHER_REQUEST_WORLD_LAT_LIMIT)
    const tileKey = `${primaryTile.zoomBucketKey}:${roundBboxCoordinate(nextCenterLng)}:${roundBboxCoordinate(nextCenterLat)}`
    if (seen.has(tileKey) || tileKey === primaryTile.tileKey) continue
    seen.add(tileKey)
    specs.push({
      zoomBucketKey: primaryTile.zoomBucketKey,
      tileKey,
      center: { lng: nextCenterLng, lat: nextCenterLat },
      lonSpan: primaryTile.lonSpan,
      latSpan: primaryTile.latSpan,
      bbox: {
        west: roundBboxCoordinate(nextCenterLng - primaryTile.lonSpan / 2),
        south: roundBboxCoordinate(nextCenterLat - primaryTile.latSpan / 2),
        east: roundBboxCoordinate(nextCenterLng + primaryTile.lonSpan / 2),
        north: roundBboxCoordinate(nextCenterLat + primaryTile.latSpan / 2),
        crs: 'EPSG:4326',
      },
    })
  }
  return specs
}

function resolvePrimaryWeatherTileSpec(
  catalogId: string,
  center: { lng: number; lat: number },
  viewportBBox: BoundingBox | null,
  zoom: number,
): WeatherTileSpec | null {
  if (!viewportBBox || !isWeatherEngineCatalogId(catalogId)) return null
  return buildWeatherTileSpec(center, viewportBBox, zoom)
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
      (typeof properties?.place_name === 'string' && properties.place_name.trim())
      || (typeof properties?.name === 'string' && properties.name.trim())
      || fallbackName,
    lng,
    lat,
    value: pointValue !== '--' ? pointValue : fallbackValue,
  }
}

function extractLayerHotspots(layer: ActiveLayer, item: RuntimeLayerLibraryItem, metricValue: string): LayerHotspot[] {
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

  return [{
    id: `${layer.catalogId}-metadata`,
    name:
      (typeof metadata?.place_name === 'string' && metadata.place_name.trim())
      || item.name,
    lng: longitude,
    lat: latitude,
    value: metricValue,
  }]
}

function mergeRecentEventMessages(existing: string[] | undefined, incoming: WorkflowEvent[]) {
  const merged = [...(existing ?? [])]
  for (const event of incoming) {
    const text = `${event.channel} · ${event.message}`
    if (merged[merged.length - 1] !== text) {
      merged.push(text)
    }
  }
  return merged.slice(-MAX_EVENT_MESSAGE_COUNT)
}

function hasRenderableMapLayerAsset(jobLayer: JobLayerItem | null | undefined) {
  const assets = jobLayer?.mapLayerPayload?.layerAssets
  return Boolean(assets?.geojsonData || assets?.geojsonUrl || assets?.cogUrl || assets?.cogPreviewUrl)
}

const STATIC_LIBRARY_BY_ID = new Map(LAYER_LIBRARY.map((item) => [item.catalogId, item]))
const CATEGORY_INDEX_BY_ID = new Map(LAYER_CATEGORIES.map((category, index) => [category.id, index]))

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
  return fallbackCategory ?? 'runtime'
}

function buildUpdateLabel(descriptor: RuntimeLayerDescriptor, fallback?: Pick<LayerCatalogItem, 'updateLabel'> | null) {
  if (fallback?.updateLabel) return fallback.updateLabel
  if (descriptor.status === 'sample') return '样板工作流'
  if (descriptor.is_realtime) return '实时更新'
  if (descriptor.supports_time) return '按时间维度'
  if (descriptor.status === 'placeholder') return '占位图层'
  return descriptor.engine ? '按工作流运行' : '按需加载'
}

function buildSourceLabel(descriptor: RuntimeLayerDescriptor, fallback?: Pick<LayerCatalogItem, 'sourceLabel'> | null) {
  if (fallback?.sourceLabel) return fallback.sourceLabel
  const sourceType = descriptor.source_type || 'runtime'
  const engine = descriptor.engine ? ` · ${descriptor.engine}` : ''
  return `${sourceType}${engine}`
}

function buildRuntimeLayerLibraryItem(descriptor: RuntimeLayerDescriptor): RuntimeLayerLibraryItem {
  const fallback = getStaticLayerLibraryItem(descriptor.layer_id)
  const category = resolveCategory(descriptor, fallback?.category)
  const categoryMeta = LAYER_CATEGORIES.find((item) => item.id === category)

  return {
    catalogId: descriptor.layer_id,
    name: descriptor.display_name,
    category,
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

function buildCatalogFallbackItem(item: RuntimeLayerLibraryItem | null, catalogId: string): RuntimeLayerLibraryItem {
  if (item) return item
  const fallback = getStaticLayerLibraryItem(catalogId)
  if (fallback) {
    return {
      ...fallback,
      description: `${fallback.name} 运行时目录信息尚未返回。`,
      runReadiness: 'unknown',
      runReadinessSummary: '运行时目录加载中',
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
    category: 'runtime',
    description: '运行时目录尚未收录该图层。',
    metricLabel: '主指标',
    metricUnit: '',
    metricPrecision: 1,
    updateLabel: '待识别',
    sourceLabel: '运行时目录',
    accentColor: '#5a6a80',
    accentGlow: 'rgba(90, 106, 128, 0.3)',
    chipTone: 'rgba(90, 106, 128, 0.16)',
    sources: [],
    runReadiness: 'unknown',
    runReadinessSummary: '运行时目录加载中',
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

function buildAvailabilityState(layer: ActiveLayer, item: RuntimeLayerLibraryItem, jobLayer?: JobLayerItem) {
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
      label: '样板可运行',
      description: item.runReadinessSummary ?? item.runReadinessNotes[0] ?? '当前为样板 provider 链路，可运行但不代表正式生产数据。',
    }
  }

  if (item.backendStatus === 'placeholder') {
    return {
      state: 'partial' as const,
      label: '占位图层',
      description: item.description || '该图层当前仍为占位或样板产物。',
    }
  }

  return {
    state: layer.dataState === 'real' ? 'partial' as const : 'empty' as const,
    label: layer.dataState === 'real' ? '等待结果' : '待运行',
    description: item.runReadinessSummary ?? '图层已加入工作区，可按需运行工作流。',
  }
}

// ─── Store ───────────────────────────────────────────────────────────────────

export const useLayersStore = defineStore('layers', () => {
  // ── Active layers (已添加的图层实例) ──────────────────────────────────────
  const activeLayers = ref<ActiveLayer[]>([])

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

  // ── 429 容量限制自动重试 ───────────────────────────────────────────────
  // 后端 max_active_runs=4，打开多个天气图层时部分请求会收到 429。
  // 这里记录重试定时器和次数，429 时创建 queued jobLayer 并自动重试。
  const workflowRetryTimers = new Map<string, number>()
  const workflowRetryCounts = new Map<string, number>()
  const MAX_WORKFLOW_429_RETRIES = 6
  const WORKFLOW_429_RETRY_DELAY_MS = 3000

  // ── 工作流全局状态汇总 ─────────────────────────────────────────────────
  const workflowSummary = computed<WorkflowSummary>(() => {
    const layers = jobLayers.value
    if (layers.length === 0) {
      return { total: 0, running: 0, queued: 0, succeeded: 0, failed: 0, cancelled: 0, retryPending: 0, overall: 'idle', tone: 'idle', hasError: false }
    }
    const counts = { running: 0, queued: 0, succeeded: 0, failed: 0, cancelled: 0, retry_pending: 0 }
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

  // ── 粒子流独占启用状态 ───────────────────────────────────────────────────
  // particle_flow 是 Canvas 叠加层，性能开销大且视觉冲突，同一时间只允许一个图层启用
  // null 表示未启用任何粒子流；值为 catalogId 时该图层独占粒子流渲染
  const particleFlowCatalogId = ref<string | null>(null)

  // ── 视口变化防抖 ───────────────────────────────────────────────────────
  // 地图移动/缩放时，使用防抖延迟避免频繁触发工作流更新
  const viewportDebounceTimer = ref<number | null>(null)
  const VIEWPORT_DEBOUNCE_MS = 500  // 防抖延迟（毫秒）
  // 记录每个 catalogId 上次提交工作流的时间戳，避免缩放时频繁重新请求 API
  const lastWorkflowSubmitTime = new Map<string, number>()
  const WORKFLOW_REFRESH_MIN_INTERVAL_MS = 2000  // 最小重新提交间隔（2 秒，后端已有 429 重试保护）
  // 记录每个 catalogId 上次提交工作流时的请求 bbox。
  // 对 weatherengine 图层，这里存的是“按缩放级别标准化后的请求范围”，不是原始视口。
  const lastWorkflowBBox = new Map<string, BoundingBox>()
  // 视口面积变化阈值：面积比 > 2 或 < 0.5 时认为是显著变化
  const SIGNIFICANT_VIEWPORT_RATIO = 2

  // ── 当前地图视口（中心点 + 可见范围）─────────────────────────────────────
  // weatherengine 图层会基于它推导“按缩放级别分桶后的请求范围”，
  // 用于从纯视口局部请求过渡到更大范围的懒加载。
  const currentMapCenter = ref<{ lng: number; lat: number }>({ lng: 113.2644, lat: 23.1291 })
  const currentMapBBox = ref<BoundingBox | null>(null)
  const currentMapZoom = ref(4.8)
  const weatherTileCache = new Map<string, WeatherTileCacheEntry>()
  const weatherCatalogPrimaryTileKey = new Map<string, string>()
  const weatherRunTileSpecs = new Map<string, { catalogId: string; spec: WeatherTileSpec; primary: boolean }>()
  const weatherPrefetchQueue: Array<{ catalogId: string; spec: WeatherTileSpec }> = []
  const weatherPrefetchActiveKeys = new Set<string>()
  /** 429 容量限制时的退避时间戳，在此时间前不 drain 预取队列 */
  let weatherPrefetchBackoffUntil = 0

  // ─────────────────────────────────────────────────────────────────────────────

  const layerLibrary = computed<RuntimeLayerLibraryItem[]>(() => {
    const runtimeItems = Object.values(runtimeLayerCatalog.value).map((descriptor) => buildRuntimeLayerLibraryItem(descriptor))
    const items = runtimeItems.length > 0
      ? runtimeItems
      : LAYER_LIBRARY
        .filter((item) => !item.isAdminBoundary)
        .map((item) => buildCatalogFallbackItem(null, item.catalogId))

    return items.slice().sort((a, b) => {
      const categoryOrderA = CATEGORY_INDEX_BY_ID.get(a.category) ?? Number.MAX_SAFE_INTEGER
      const categoryOrderB = CATEGORY_INDEX_BY_ID.get(b.category) ?? Number.MAX_SAFE_INTEGER
      if (categoryOrderA !== categoryOrderB) {
        return categoryOrderA - categoryOrderB
      }
      return a.name.localeCompare(b.name, 'zh-CN')
    })
  })

  const layerLibraryMap = computed(() => new Map(layerLibrary.value.map((item) => [item.catalogId, item])))

  const activeLayersDisplay = computed<ActiveLayerDisplay[]>(() => {
    return activeLayers.value
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((layer): ActiveLayerDisplay | null => {
        const item = buildCatalogFallbackItem(layerLibraryMap.value.get(layer.catalogId) ?? null, layer.catalogId)
        const availability = buildAvailabilityState(layer, item, layer.jobLayer)
        const realDisplay = layer.jobLayer ? buildRealLayerDisplay(layer, item) : {}

        return {
          instanceId: layer.instanceId,
          catalogId: layer.catalogId,
          name: layer.isAdminBoundary ? '行政区边界' : item.name,
          category: layer.isAdminBoundary ? 'boundary' : item.category,
          description: layer.isAdminBoundary ? '广东省市级行政区边界叠加层。' : item.description,
          engine: layer.isAdminBoundary ? 'builtin' : item.engine,
          supportsTime: item.supportsTime,
          runReadiness: item.runReadiness,
          runReadinessSummary: item.runReadinessSummary,
          summary: layer.isAdminBoundary ? '广东省市级行政区边界叠加层' : (realDisplay.summary ?? item.description),
          metricLabel: layer.isAdminBoundary ? '边界层级' : item.metricLabel,
          metricValue: layer.isAdminBoundary ? '省市级' : (realDisplay.metricValue ?? '--'),
          trendLabel: layer.isAdminBoundary ? '静态矢量边界叠加' : (realDisplay.trendLabel ?? (item.backendStatus === 'sample' ? '样板 provider 链路已接入' : item.supportsTime ? '支持时间维度查询' : '运行时目录已接入')),
          statusLabel: layer.isAdminBoundary ? '静态数据' : (realDisplay.statusLabel ?? (item.backendStatus === 'sample' ? '样板 Provider' : item.backendStatus === 'placeholder' ? '占位图层' : '目录已接入')),
          updateLabel: layer.isAdminBoundary ? '静态数据' : item.updateLabel,
          sourceLabel: layer.isAdminBoundary ? '广东省市级边界' : (realDisplay.sourceLabel ?? item.sourceLabel),
          confidenceLabel: layer.isAdminBoundary ? '置信度 100%' : (realDisplay.confidenceLabel ?? '以运行时目录为准'),
          accentColor: layer.isAdminBoundary ? '#88d8ff' : item.accentColor,
          accentGlow: layer.isAdminBoundary ? 'rgba(136, 216, 255, 0.3)' : item.accentGlow,
          chipTone: layer.isAdminBoundary ? 'rgba(136, 216, 255, 0.16)' : item.chipTone,
          availabilityState: layer.isAdminBoundary ? 'ready' : availability.state,
          availabilityLabel: layer.isAdminBoundary ? '完整数据' : availability.label,
          availabilityDescription: layer.isAdminBoundary
            ? '静态矢量边界数据，已完整加载。'
            : (realDisplay.availabilityDescription ?? availability.description),
          observationTimeLabel: layer.isAdminBoundary ? '静态数据' : (realDisplay.observationTimeLabel ?? (item.supportsTime ? `${String(currentHour.value).padStart(2, '0')}:00` : '--')),
          missingFieldsLabel: layer.isAdminBoundary ? '无' : (realDisplay.missingFieldsLabel ?? (item.runReadinessNotes[0] ?? '无')),
          hotspots: layer.isAdminBoundary ? [] : (realDisplay.hotspots ?? []),
          isAdminBoundary: layer.isAdminBoundary,
          jobLayer: layer.jobLayer,
          visible: layer.visible,
          opacity: layer.opacity,
          order: layer.order,
          dataState: layer.dataState,
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
    return `图层 (${activeLayerCount.value})`
  })

  // ─────────────────────────────────────────────────────────────────────────────

  function addLayer(catalogId: string, isAdminBoundary = false, jobLayer?: JobLayerItem) {
    // 防止重复添加同 catalogId (除非来自不同 job)
    if (!isAdminBoundary && !jobLayer) {
      if (activeLayers.value.some((l) => l.catalogId === catalogId && !l.jobLayer)) {
        return
      }
    }

    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const layer: ActiveLayer = {
      instanceId: genInstanceId(),
      catalogId,
      visible: true,
      opacity: 1,
      order: maxOrder + 1,
      isAdminBoundary,
      jobLayer,
      dataState: jobLayer ? 'real' : 'catalog',
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId

    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
  }

  function removeLayer(instanceId: string) {
    const idx = activeLayers.value.findIndex((l) => l.instanceId === instanceId)
    if (idx === -1) return
    // 修复：删除图层时停止对应工作流轮询，避免泄漏 setTimeout 句柄
    const layer = activeLayers.value[idx]
    if (layer.jobLayer?.jobId) {
      stopWorkflowPolling(layer.jobLayer.jobId)
    }
    // 清理 429 重试定时器和计数，避免图层移除后重试仍触发
    const retryTimer = workflowRetryTimers.get(layer.catalogId)
    if (retryTimer !== undefined) {
      window.clearTimeout(retryTimer)
      workflowRetryTimers.delete(layer.catalogId)
    }
    workflowRetryCounts.delete(layer.catalogId)
    activeLayers.value.splice(idx, 1)

    if (selectedInstanceId.value === instanceId) {
      selectedInstanceId.value = activeLayers.value[0]?.instanceId ?? null
    }
  }

  function toggleLayerVisibility(instanceId: string) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.visible = !layer.visible
    }
  }

  /** 批量设置所有图层可见性 */
  function setAllLayerVisibility(visible: boolean) {
    for (const layer of activeLayers.value) {
      layer.visible = visible
    }
  }

  /** 批量移除所有图层（保留行政区边界） */
  function removeAllLayers(keepBoundary = true) {
    const removedJobIds = activeLayers.value
      .filter((layer) => !keepBoundary || !layer.isAdminBoundary)
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
    if (keepBoundary) {
      activeLayers.value = activeLayers.value.filter((l) => l.isAdminBoundary)
    } else {
      activeLayers.value = []
    }
    if (!activeLayers.value.some((l) => l.instanceId === selectedInstanceId.value)) {
      selectedInstanceId.value = activeLayers.value[0]?.instanceId ?? null
    }
  }

  function setLayerOpacity(instanceId: string, opacity: number) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.opacity = Math.max(0, Math.min(1, opacity))
    }
  }

  function setLayerOrder(instanceId: string, newOrder: number) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (layer) {
      layer.order = newOrder
    }
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
        const shouldRetry =
          /AbortError|aborted without reason|Failed to fetch|NetworkError/i.test(message)
        if (!shouldRetry) {
          throw error
        }
        await new Promise((resolve) => window.setTimeout(resolve, 250))
        return fetchLayerCatalog()
      })
      .then((response) => {
        runtimeLayerCatalog.value = Object.fromEntries(response.items.map((item) => [item.layer_id, item]))
      })
      .catch((error) => {
        // 请求失败时清理状态，避免后续调用返回已拒绝的 Promise
        console.warn('[LayersStore] ensureRuntimeLayerCatalog failed, will retry on next call:', error.message)
        runtimeLayerCatalogRequest = null
        throw error
      })
      .finally(() => {
        runtimeLayerCatalogLoading.value = false
        runtimeLayerCatalogRequest = null
      })

    return runtimeLayerCatalogRequest
  }

  function getCatalogRunBlockReason(catalogId: string) {
    const descriptor = getRuntimeLayerDescriptor(catalogId)
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
    const existingRealLayer = activeLayers.value.find((layer) => layer.jobLayer?.jobId === jobLayer.jobId)
    if (existingRealLayer) {
      existingRealLayer.jobLayer = jobLayer
      existingRealLayer.dataState = 'real'
      return
    }

    const existingCatalogLayer = activeLayers.value.find((layer) => layer.catalogId === catalogId && !layer.isAdminBoundary)
    if (existingCatalogLayer) {
      existingCatalogLayer.jobLayer = jobLayer
      existingCatalogLayer.dataState = 'real'
      // 不在工作流更新时修改 selectedInstanceId，避免视口变化重提交导致图层选中被篡改
      return
    }

    addLayer(catalogId, false, jobLayer)
  }

  function upsertJobLayer(catalogId: string, jobLayer: JobLayerItem) {
    const existingIndex = jobLayers.value.findIndex((item) => item.jobId === jobLayer.jobId)
    if (existingIndex >= 0) {
      jobLayers.value.splice(existingIndex, 1, jobLayer)
    } else {
      jobLayers.value.unshift(jobLayer)
    }
    syncJobLayerToActiveLayer(catalogId, jobLayer)
  }

  function getWeatherTileCacheKey(catalogId: string, spec: WeatherTileSpec) {
    return `${catalogId}:${spec.tileKey}`
  }

  function getWeatherTileCacheEntry(catalogId: string, spec: WeatherTileSpec) {
    return weatherTileCache.get(getWeatherTileCacheKey(catalogId, spec))
  }

  function setWeatherTileCacheEntry(entry: WeatherTileCacheEntry) {
    weatherTileCache.set(getWeatherTileCacheKey(entry.catalogId, entry.spec), entry)
  }

  /** 淘汰远距离瓦片：清理其他 zoom bucket 的瓦片，当前 bucket 超过上限时按距离淘汰最远的 */
  function evictDistantWeatherTiles(catalogId: string, currentCenter: { lng: number; lat: number }, currentZoomBucketKey: string) {
    // 1. 淘汰其他 zoom bucket 的瓦片（只保留当前 bucket）
    for (const [key, entry] of weatherTileCache.entries()) {
      if (entry.catalogId === catalogId && entry.spec.zoomBucketKey !== currentZoomBucketKey) {
        weatherTileCache.delete(key)
      }
    }
    // 2. 当前 bucket 超过上限时，按距离淘汰最远的瓦片
    const sameBucketEntries: Array<{ key: string; dist: number }> = []
    for (const [key, entry] of weatherTileCache.entries()) {
      if (entry.catalogId !== catalogId || entry.spec.zoomBucketKey !== currentZoomBucketKey) continue
      if (entry.status !== 'succeeded') continue  // 只淘汰已完成的，不淘汰进行中的
      const dLng = entry.spec.center.lng - currentCenter.lng
      const dLat = entry.spec.center.lat - currentCenter.lat
      sameBucketEntries.push({ key, dist: dLng * dLng + dLat * dLat })
    }
    if (sameBucketEntries.length <= WEATHER_TILE_CACHE_MAX_PER_BUCKET) return
    sameBucketEntries.sort((a, b) => b.dist - a.dist)
    const toEvict = sameBucketEntries.length - WEATHER_TILE_CACHE_MAX_PER_BUCKET
    for (let i = 0; i < toEvict; i++) {
      weatherTileCache.delete(sameBucketEntries[i].key)
    }
  }

  function extractGeojsonDataFromJobLayer(jobLayer: JobLayerItem | null | undefined) {
    const payload = jobLayer?.mapLayerPayload?.layerAssets?.geojsonData
    return payload && typeof payload === 'object' ? payload : undefined
  }

  function buildMergedGeojsonForCatalog(catalogId: string, zoomBucketKey: string) {
    const features: Record<string, unknown>[] = []
    const seen = new Set<string>()
    for (const entry of weatherTileCache.values()) {
      if (entry.catalogId !== catalogId || entry.spec.zoomBucketKey !== zoomBucketKey || entry.status !== 'succeeded' || !entry.geojsonData) {
        continue
      }
      const entryFeatures = Array.isArray((entry.geojsonData as { features?: unknown[] }).features)
        ? ((entry.geojsonData as { features: Record<string, unknown>[] }).features)
        : []
      for (const feature of entryFeatures) {
        const geometry = asRecord(feature.geometry)
        const coordinates = Array.isArray(geometry?.coordinates) ? geometry.coordinates : []
        const properties = asRecord(feature.properties)
        // 去重 key 仅用坐标（round 到 3 位小数 ≈ 100m 容差）+ height（不同高度层是独立特征）
        // 修复：原 key 包含 value（grid 数据无此字段，恒为空），且坐标未取整，
        // 导致浮点精度差异使相邻瓦片的重叠点无法正确去重
        const lng = roundBboxCoordinate(Number(coordinates[0]) || 0)
        const lat = roundBboxCoordinate(Number(coordinates[1]) || 0)
        const dedupeKey = `${lng}:${lat}:${properties?.height ?? ''}`
        if (seen.has(dedupeKey)) continue
        seen.add(dedupeKey)
        features.push(feature)
      }
    }
    if (!features.length) return null
    return {
      type: 'FeatureCollection',
      features,
    }
  }

  function patchCatalogJobLayerGeojson(catalogId: string, mergedGeojson: Record<string, unknown>) {
    const targetLayer = activeLayers.value.find((layer) => layer.catalogId === catalogId && layer.jobLayer)
    const baseJobLayer = targetLayer?.jobLayer
      ?? jobLayers.value.find((item) => activeLayers.value.some((layer) => layer.catalogId === catalogId && layer.jobLayer?.jobId === item.jobId))
    if (!baseJobLayer) return
    const nextJobLayer: JobLayerItem = {
      ...baseJobLayer,
      updatedAt: new Date().toISOString(),
      mapLayerPayload: {
        ...baseJobLayer.mapLayerPayload,
        layerAssets: {
          ...baseJobLayer.mapLayerPayload?.layerAssets,
          geojsonData: mergedGeojson,
        },
      },
    }
    upsertJobLayer(catalogId, nextJobLayer)
  }

  function applyMergedWeatherTileData(catalogId: string, zoomBucketKey: string) {
    const mergedGeojson = buildMergedGeojsonForCatalog(catalogId, zoomBucketKey)
    if (!mergedGeojson) return false
    patchCatalogJobLayerGeojson(catalogId, mergedGeojson)
    return true
  }

  function cacheWeatherTileJobLayer(catalogId: string, spec: WeatherTileSpec, jobLayer: JobLayerItem) {
    setWeatherTileCacheEntry({
      catalogId,
      spec,
      status: jobLayer.status,
      jobId: jobLayer.jobId,
      updatedAt: jobLayer.updatedAt,
      geojsonData: extractGeojsonDataFromJobLayer(jobLayer),
    })
  }

  function buildWorkflowPayloadForCatalog(
    catalogId: string,
    catalogName: string,
    requestedOutputs: string[],
    requestBBox: BoundingBox | null,
  ) {
    return {
      command_type: 'analysis' as const,
      command_label: `运行 ${catalogName} 分析`,
      layer_id: catalogId,
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
  }

  async function pollHiddenWeatherTileRun(jobId: string, catalogId: string, spec: WeatherTileSpec) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const run = await getWorkflowRun(jobId)
      const status = run.status === 'accepted' ? 'queued' : run.status
      if (isTerminalStatus(status)) {
        const jobLayer = await buildJobLayer(run, catalogId)
        cacheWeatherTileJobLayer(catalogId, spec, jobLayer)
        weatherRunTileSpecs.delete(jobId)
        if (jobLayer.status === 'succeeded') {
          applyMergedWeatherTileData(catalogId, spec.zoomBucketKey)
          evictDistantWeatherTiles(catalogId, currentMapCenter.value, spec.zoomBucketKey)
          expandWeatherTilePrefetch(catalogId, spec)  // 预取瓦片成功后继续 BFS 扩散
        }
        return
      }
      await new Promise((resolve) => window.setTimeout(resolve, EVENT_POLL_ACTIVE_INTERVAL_MS))
    }
  }

  async function drainWeatherPrefetchQueue() {
    // 429 退避期内不 drain，避免持续撞击容量限制
    if (Date.now() < weatherPrefetchBackoffUntil) return
    if (weatherPrefetchActiveKeys.size >= WEATHER_PREFETCH_CONCURRENCY) return
    const nextTask = weatherPrefetchQueue.shift()
    if (!nextTask) return

    const cacheKey = getWeatherTileCacheKey(nextTask.catalogId, nextTask.spec)
    if (weatherPrefetchActiveKeys.has(cacheKey)) {
      void drainWeatherPrefetchQueue()
      return
    }

    weatherPrefetchActiveKeys.add(cacheKey)
    void drainWeatherPrefetchQueue()
    const catalogName = runtimeLayerCatalog.value[nextTask.catalogId]?.display_name ?? getCatalogDisplayName(nextTask.catalogId)
    const requestedOutputs = supportsMapLayerResult(nextTask.catalogId)
      ? ['json', 'text', 'table', 'map_layer']
      : ['json', 'text', 'table']

    try {
      setWeatherTileCacheEntry({
        catalogId: nextTask.catalogId,
        spec: nextTask.spec,
        status: 'queued',
        updatedAt: new Date().toISOString(),
      })
      const accepted = await submitWorkflow(
        buildWorkflowPayloadForCatalog(nextTask.catalogId, catalogName, requestedOutputs, nextTask.spec.bbox),
      )
      weatherRunTileSpecs.set(accepted.run_id, {
        catalogId: nextTask.catalogId,
        spec: nextTask.spec,
        primary: false,
      })
      setWeatherTileCacheEntry({
        catalogId: nextTask.catalogId,
        spec: nextTask.spec,
        status: 'running',
        jobId: accepted.run_id,
        updatedAt: accepted.created_at,
      })
      await pollHiddenWeatherTileRun(accepted.run_id, nextTask.catalogId, nextTask.spec)
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : String(error)
      if (errMsg.includes('429')) {
        // 429 容量限制：将任务放回队列头部，设置 3s 退避后自动重试
        weatherPrefetchQueue.unshift(nextTask)
        weatherPrefetchBackoffUntil = Date.now() + 3000
      } else {
        console.warn('[LayersStore] weather tile prefetch failed:', nextTask.catalogId, nextTask.spec.tileKey, error)
        setWeatherTileCacheEntry({
          catalogId: nextTask.catalogId,
          spec: nextTask.spec,
          status: 'failed',
          updatedAt: new Date().toISOString(),
        })
      }
    } finally {
      weatherPrefetchActiveKeys.delete(cacheKey)
      // 退避期内延迟 drain，避免立即重试撞击 429
      const backoffRemaining = weatherPrefetchBackoffUntil - Date.now()
      if (backoffRemaining > 0) {
        window.setTimeout(() => void drainWeatherPrefetchQueue(), backoffRemaining)
      } else {
        void drainWeatherPrefetchQueue()
      }
    }
  }

  function trimWeatherPrefetchQueueForCatalog(catalogId: string) {
    for (let index = weatherPrefetchQueue.length - 1; index >= 0; index -= 1) {
      if (weatherPrefetchQueue[index]?.catalogId === catalogId) {
        weatherPrefetchQueue.splice(index, 1)
      }
    }
  }

  function enqueueWeatherTilePrefetch(catalogId: string, primarySpec: WeatherTileSpec) {
    trimWeatherPrefetchQueueForCatalog(catalogId)
    if (primarySpec.tileKey.endsWith(':world')) return
    // BFS 入口：将 8 个邻居全部入队（跳过已缓存/已排队的），由 drainWeatherPrefetchQueue 并行拉取
    const neighborSpecs = buildNeighborWeatherTileSpecs(primarySpec)
    for (const spec of neighborSpecs) {
      if (weatherPrefetchQueue.length >= WEATHER_PREFETCH_MAX_QUEUE) break
      const existing = getWeatherTileCacheEntry(catalogId, spec)
      if (existing && (existing.status === 'queued' || existing.status === 'running' || existing.status === 'succeeded')) {
        continue
      }
      const cacheKey = getWeatherTileCacheKey(catalogId, spec)
      if (weatherPrefetchQueue.some((item) => getWeatherTileCacheKey(item.catalogId, item.spec) === cacheKey)) {
        continue
      }
      weatherPrefetchQueue.push({ catalogId, spec })
    }
    void drainWeatherPrefetchQueue()
  }

  /** BFS 环形扩散：当一个瓦片成功后，将其 8 个邻居入队，形成持续外扩加载 */
  function expandWeatherTilePrefetch(catalogId: string, completedSpec: WeatherTileSpec) {
    if (completedSpec.tileKey.endsWith(':world')) return
    const neighborSpecs = buildNeighborWeatherTileSpecs(completedSpec)
    for (const spec of neighborSpecs) {
      if (weatherPrefetchQueue.length >= WEATHER_PREFETCH_MAX_QUEUE) break
      const existing = getWeatherTileCacheEntry(catalogId, spec)
      if (existing && (existing.status === 'queued' || existing.status === 'running' || existing.status === 'succeeded')) {
        continue
      }
      const cacheKey = getWeatherTileCacheKey(catalogId, spec)
      if (weatherPrefetchQueue.some((item) => getWeatherTileCacheKey(item.catalogId, item.spec) === cacheKey)) {
        continue
      }
      weatherPrefetchQueue.push({ catalogId, spec })
    }
    void drainWeatherPrefetchQueue()
  }

  function applyWorkflowEventsToJobLayer(jobLayer: JobLayerItem, events: WorkflowEvent[]): JobLayerItem {
    if (events.length === 0) return jobLayer

    let nextStatus = jobLayer.status
    let nextProgress = jobLayer.progress
    let nextMessage = jobLayer.message
    let nextUpdatedAt = jobLayer.updatedAt
    let lastEventId = jobLayer.lastEventId
    let lastEventAt = jobLayer.lastEventAt

    for (const event of events) {
      if (typeof event.progress === 'number') {
        nextProgress = Math.max(nextProgress, Math.min(100, Math.round(event.progress)))
      }
      if (event.message) {
        nextMessage = event.message
      }
      if (isRecognizedJobStatus(event.payload?.status)) {
        nextStatus = event.payload.status
      }
      lastEventId = event.event_id
      lastEventAt = event.created_at
      nextUpdatedAt = event.created_at
    }

    const eventMessages = mergeRecentEventMessages(jobLayer.eventMessages ?? jobLayer.diagnosticNotes, events)
    const showEventMessages = nextStatus === 'queued' || nextStatus === 'running' || nextStatus === 'retry_pending'

    return {
      ...jobLayer,
      status: nextStatus,
      progress: nextProgress,
      message: nextMessage,
      updatedAt: nextUpdatedAt,
      lastEventId,
      lastEventAt,
      eventMessages,
      diagnosticNotes: showEventMessages ? eventMessages : jobLayer.diagnosticNotes,
    }
  }

  async function syncWorkflowRunSnapshot(jobId: string, catalogId: string, force = false) {
    const now = Date.now()
    if (!force) {
      const lastSyncedAt = workflowLastStatusSyncAt.get(jobId) ?? 0
      if (now - lastSyncedAt < STATUS_SYNC_INTERVAL_MS) {
        return false
      }
    }

    const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
    const run = await getWorkflowRun(jobId)
    const jobLayer = await buildJobLayer(run, catalogId, { previousJobLayer: existingJobLayer })
    const mergedJobLayer =
      existingJobLayer && !isTerminalStatus(jobLayer.status)
        ? {
            ...jobLayer,
            lastEventId: existingJobLayer.lastEventId,
            lastEventAt: existingJobLayer.lastEventAt,
            eventMessages: existingJobLayer.eventMessages,
            diagnosticNotes:
              jobLayer.diagnosticNotes?.length
                ? jobLayer.diagnosticNotes
                : existingJobLayer.eventMessages ?? existingJobLayer.diagnosticNotes,
          }
        : jobLayer

    upsertJobLayer(catalogId, mergedJobLayer)
    workflowLastStatusSyncAt.set(jobId, now)
    const tileRunSpec = weatherRunTileSpecs.get(jobId)
    if (tileRunSpec) {
      cacheWeatherTileJobLayer(catalogId, tileRunSpec.spec, mergedJobLayer)
    }

    if (isTerminalStatus(mergedJobLayer.status)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      if (tileRunSpec) {
        weatherRunTileSpecs.delete(jobId)
        if (mergedJobLayer.status === 'succeeded') {
          weatherCatalogPrimaryTileKey.set(catalogId, tileRunSpec.spec.tileKey)
          applyMergedWeatherTileData(catalogId, tileRunSpec.spec.zoomBucketKey)
          evictDistantWeatherTiles(catalogId, currentMapCenter.value, tileRunSpec.spec.zoomBucketKey)
          // primary 和非 primary 瓦片成功后都触发 BFS 扩散，形成持续外扩加载
          expandWeatherTilePrefetch(catalogId, tileRunSpec.spec)
        }
      }
      const mapPayload = mergedJobLayer.mapLayerPayload
      if (
        particleFlowCatalogId.value === catalogId
        && supportsParticleFlow(catalogId)
        && !hasRenderableMapLayerAsset(mergedJobLayer)
      ) {
        particleFlowCatalogId.value = null
      }
      if (
        mergedJobLayer.status === 'succeeded'
        && supportsParticleFlow(catalogId)
        && hasRenderableMapLayerAsset(mergedJobLayer)
        && !particleFlowCatalogId.value
      ) {
        particleFlowCatalogId.value = catalogId
      }
      return true
    }

    return false
  }

  async function pollWorkflowRun(jobId: string, catalogId: string, startTime = Date.now(), consecutiveErrors = 0) {
    if (Date.now() - startTime > EVENT_POLL_MAX_DURATION_MS) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      workflowError.value = `工作流 ${jobId} 事件等待超时（${EVENT_POLL_MAX_DURATION_MS / 1000}s）`
      const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
      if (existingJobLayer) {
        upsertJobLayer(catalogId, {
          ...existingJobLayer,
          status: 'failed',
          message: '事件等待超时',
          progress: 0,
        })
      }
      return
    }

    let nextConsecutiveErrors = consecutiveErrors
    let nextDelayMs = EVENT_POLL_IDLE_INTERVAL_MS

    try {
      const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
      const events = await getWorkflowEvents(jobId, {
        afterEventId: existingJobLayer?.lastEventId,
        limit: 24,
      })
      const newItems = events.items ?? []

      if (existingJobLayer && newItems.length > 0) {
        upsertJobLayer(catalogId, applyWorkflowEventsToJobLayer(existingJobLayer, newItems))
        nextDelayMs = EVENT_POLL_ACTIVE_INTERVAL_MS
      }

      workflowError.value = null
      nextConsecutiveErrors = 0

      const shouldForceSync = newItems.some((event) => isRecognizedJobStatus(event.payload?.status) && isTerminalStatus(event.payload.status))
      const didReachTerminal = await syncWorkflowRunSnapshot(jobId, catalogId, shouldForceSync)
      if (didReachTerminal) {
        return
      }
    } catch (error) {
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
            progress: 0,
          })
        }
        return
      }

      // AbortError（requestJson 30s 超时）是临时性错误，不显示给用户，直接重试
      const isAbortError = error instanceof DOMException && error.name === 'AbortError'
      if (isAbortError) {
        // 超时后用 idle 间隔重试，不递增错误计数，不设置 workflowError
        nextDelayMs = EVENT_POLL_IDLE_INTERVAL_MS
      } else {
        nextConsecutiveErrors = consecutiveErrors + 1
        if (nextConsecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          stopWorkflowPolling(jobId)
          activeWorkflowCatalogIds.delete(catalogId)
          workflowError.value = `工作流 ${jobId} 事件同步连续失败 ${nextConsecutiveErrors} 次：${errMsg}`
          const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
          if (existingJobLayer) {
            upsertJobLayer(catalogId, {
              ...existingJobLayer,
              status: 'failed',
              message: `事件同步连续失败：${errMsg}`,
              progress: 0,
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
      void pollWorkflowRun(jobId, catalogId, startTime, nextConsecutiveErrors)
    }, effectiveDelay)
    workflowPollingHandles.set(jobId, handle)
  }

  /** 中断指定 catalogId 的活跃工作流（平移时调用）：停止轮询、取消 API（fire-and-forget）、清空预取队列，但保留已成功的瓦片缓存 */
  function interruptWorkflowForCatalog(catalogId: string) {
    // 清理 429 重试定时器，避免与新的提交冲突
    const retryTimer = workflowRetryTimers.get(catalogId)
    if (retryTimer !== undefined) {
      window.clearTimeout(retryTimer)
      workflowRetryTimers.delete(catalogId)
    }
    // 从 weatherRunTileSpecs 找到 primary run
    let runJobId: string | null = null
    for (const [jid, spec] of weatherRunTileSpecs.entries()) {
      if (spec.catalogId === catalogId && spec.primary) { runJobId = jid; break }
    }
    // fallback: 查找该 catalogId 的活跃 jobId（非终态）
    if (!runJobId) {
      const activeJobLayer = jobLayers.value.find((item) =>
        activeLayers.value.some((l) => l.catalogId === catalogId && l.jobLayer?.jobId === item.jobId)
        && !isTerminalStatus(item.status)
      )
      runJobId = activeJobLayer?.jobId ?? null
    }
    if (runJobId) {
      stopWorkflowPolling(runJobId)
      activeWorkflowCatalogIds.delete(catalogId)
      weatherRunTileSpecs.delete(runJobId)
      // fire-and-forget 取消 API 调用，不阻塞新提交
      void cancelWorkflowRun(runJobId).catch(() => {})
    }
    // 清空预取队列（旧位置的待拉取瓦片不再需要）
    trimWeatherPrefetchQueueForCatalog(catalogId)
    // 注意：不清空 weatherTileCache —— 已成功的数据保留！
  }

  async function runWorkflowForCatalog(catalogId: string, options?: { skipIfRequestBBoxUnchanged?: boolean }) {
    if (submittingCatalogIds.has(catalogId)) return
    workflowError.value = null
    submittingCatalogIds.add(catalogId)
    try {
      let runtimeCatalogReady = false
      try {
        await ensureRuntimeLayerCatalog()
        runtimeCatalogReady = true
      } catch (error) {
        const canProceedWithoutCatalog = isWeatherEngineLayer(catalogId) || catalogId === 'lab-output'
        if (!canProceedWithoutCatalog) {
          throw error
        }
        console.warn('[LayersStore] runtime layer catalog unavailable, proceeding with static fallback for', catalogId, error)
      }

      const blockedReason = runtimeCatalogReady ? getCatalogRunBlockReason(catalogId) : null
      if (blockedReason) {
        throw new Error(blockedReason)
      }

      const catalogName = runtimeLayerCatalog.value[catalogId]?.display_name ?? getCatalogDisplayName(catalogId)
      const supportsMapLayer = supportsMapLayerResult(catalogId)
      const requestedOutputs = supportsMapLayer
        ? ['json', 'text', 'table', 'map_layer']
        : ['json', 'text', 'table']
      const primaryTileSpec = resolvePrimaryWeatherTileSpec(
        catalogId,
        currentMapCenter.value,
        currentMapBBox.value,
        currentMapZoom.value,
      )
      const requestBBox = primaryTileSpec?.bbox ?? currentMapBBox.value
      const lastRequestBBox = lastWorkflowBBox.get(catalogId)
      if (options?.skipIfRequestBBoxUnchanged && areBoundingBoxesEqual(lastRequestBBox, requestBBox)) {
        return
      }
      if (primaryTileSpec) {
        const cachedPrimaryTile = getWeatherTileCacheEntry(catalogId, primaryTileSpec)
        if (cachedPrimaryTile?.status === 'succeeded') {
          weatherCatalogPrimaryTileKey.set(catalogId, primaryTileSpec.tileKey)
          lastWorkflowSubmitTime.set(catalogId, Date.now())
          lastWorkflowBBox.set(catalogId, primaryTileSpec.bbox)
          applyMergedWeatherTileData(catalogId, primaryTileSpec.zoomBucketKey)
          enqueueWeatherTilePrefetch(catalogId, primaryTileSpec)
          return activeLayers.value.find((layer) => layer.catalogId === catalogId)?.jobLayer?.jobId
        }
      }

      // 中断旧位置的活跃工作流（取消 API 调用 + 清空预取队列），但保留已成功的瓦片缓存
      // 先获取旧 jobLayer 的 mapLayerPayload，以便在新工作流运行期间保持旧数据可见
      const previousJobLayer = activeLayers.value.find(
        (l) => l.catalogId === catalogId && !l.isAdminBoundary,
      )?.jobLayer

      interruptWorkflowForCatalog(catalogId)

      const accepted = await submitWorkflow(
        buildWorkflowPayloadForCatalog(catalogId, catalogName, requestedOutputs, requestBBox),
      )

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
        // 保留旧 mapLayerPayload，使粒子流/网格填充在新工作流运行期间保持可见
        mapLayerPayload: previousJobLayer?.mapLayerPayload,
      })

      // 记录提交时间戳和 bbox，用于 refreshActiveWeatherWorkflows 的时间间隔和显著变化检查
      lastWorkflowSubmitTime.set(catalogId, Date.now())
      if (requestBBox) {
        lastWorkflowBBox.set(catalogId, requestBBox)
      }
      if (primaryTileSpec) {
        weatherCatalogPrimaryTileKey.set(catalogId, primaryTileSpec.tileKey)
        weatherRunTileSpecs.set(accepted.run_id, {
          catalogId,
          spec: primaryTileSpec,
          primary: true,
        })
        setWeatherTileCacheEntry({
          catalogId,
          spec: primaryTileSpec,
          status: 'queued',
          jobId: accepted.run_id,
          updatedAt: accepted.created_at,
        })
      }

      activeWorkflowCatalogIds.add(catalogId)
      // 工作流提交成功，清除 429 重试计数
      workflowRetryCounts.delete(catalogId)
      void pollWorkflowRun(accepted.run_id, catalogId)
      return accepted.run_id
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : '提交 workflow 失败'
      if (errMsg.includes('429')) {
        workflowError.value = '工作流并发数已达上限，正在等待空闲后自动重试…'
        // 429 时创建 queued jobLayer 让用户看到状态指示，并调度自动重试
        upsertJobLayer(catalogId, {
          jobId: `retry-${catalogId}-${Date.now()}`,
          name: getCatalogDisplayName(catalogId),
          commandType: 'analysis',
          status: 'queued',
          progress: 5,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          message: '等待工作流容量，自动重试中…',
          metrics: [],
          reportSummary: '等待工作流容量，自动重试中…',
          resultUrl: undefined,
        })
        scheduleWorkflowRetry(catalogId)
      } else {
        workflowError.value = errMsg
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
        message: '工作流容量不足，已达最大重试次数，请稍后手动重试',
        metrics: [],
        reportSummary: '工作流容量不足，请稍后手动重试',
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
      const run = await cancelWorkflowRun(jobId)
      const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
      const jobLayer = await buildJobLayer(run, catalogId, { previousJobLayer: existingJobLayer })
      upsertJobLayer(catalogId, jobLayer)
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
    } catch (error) {
      workflowError.value = error instanceof Error ? error.message : '取消 workflow 失败'
    }
  }

  async function retryWorkflowRunForJob(jobId: string, catalogId: string) {
    if (submittingCatalogIds.has(catalogId)) return
    // 中断旧位置的活跃工作流，允许重试提交新工作流
    interruptWorkflowForCatalog(catalogId)
    workflowError.value = null
    submittingCatalogIds.add(catalogId)
    try {
      const accepted = await retryWorkflowRun(jobId)
      const catalogName = runtimeLayerCatalog.value[catalogId]?.display_name ?? getCatalogDisplayName(catalogId)
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
    const sorted = activeLayers.value.slice().sort((a, b) => a.order - b.order)
    const [moved] = sorted.splice(fromIndex, 1)
    sorted.splice(toIndex, 0, moved)
    sorted.forEach((layer, i) => {
      layer.order = i
    })
  }

  /** 判断 catalogId 是否由 weatherengine 后端支持（用于自动运行工作流） */
  function isWeatherEngineLayer(catalogId: string): boolean {
    return isWeatherEngineCatalogId(catalogId)
  }

  function supportsMapLayerResult(catalogId: string) {
    const descriptor = getRuntimeLayerDescriptor(catalogId)
    if (descriptor?.render_type) {
      // 天气引擎图层（温度/降水/气压/湿度/能见度等）虽 render_type=raster，
      // 但实际产出 Polygon GeoJSON + renderHint，需要请求 map_layer 输出
      return MAP_LAYER_RENDER_TYPES.has(descriptor.render_type) || isWeatherEngineLayer(catalogId)
    }
    return isWeatherEngineLayer(catalogId) || catalogId === 'lab-output'
  }

  function supportsViewportDrivenRefresh(catalogId: string) {
    const descriptor = getRuntimeLayerDescriptor(catalogId)
    if (descriptor?.render_type) {
      return MAP_LAYER_RENDER_TYPES.has(descriptor.render_type) || isWeatherEngineLayer(catalogId)
    }
    return isWeatherEngineLayer(catalogId) || catalogId === 'lab-output'
  }

  /** 判断 catalogId 是否支持粒子流渲染（所有 wind-field 变体都支持） */
  function supportsParticleFlow(catalogId: string): boolean {
    return catalogId.startsWith('wind-field')
  }

  /** 切换粒子流启用状态：再次点击同一图层会关闭，点击新图层会切换 */
  function toggleParticleFlow(catalogId: string) {
    if (particleFlowCatalogId.value === catalogId) {
      particleFlowCatalogId.value = null
    } else {
      particleFlowCatalogId.value = catalogId
    }
  }

  /** 直接设置粒子流启用图层（设为 null 关闭） */
  function setParticleFlow(catalogId: string | null) {
    particleFlowCatalogId.value = catalogId
  }

  // ─── 点天气查询（单工作流管理：同一时间只允许一个点查询运行） ──────────────
  const pointWeather = ref<WeatherPointResponse | null>(null)
  const pointWeatherLoading = ref(false)
  const pointWeatherError = ref<string | null>(null)
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
  }

  /**
   * 提交点天气查询（作为单一工作流管理）。
   * 每次调用会中断上一次尚未完成的查询，确保同一时间只有一条点查询工作流在运行。
   */
  async function fetchPointWeather(lng: number, lat: number, catalogId: string) {
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
    try {
      const weather = await getWeatherPoint({
        layer_id: catalogId,
        latitude: lat,
        longitude: lng,
        forecast_hours: 6,
        place_name: `${lat.toFixed(3)}, ${lng.toFixed(3)}`,
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      pointWeather.value = weather
    } catch (error) {
      if (controller.signal.aborted) return
      pointWeather.value = null
      pointWeatherError.value = error instanceof Error ? error.message : 'Failed to load point weather'
    } finally {
      if (!controller.signal.aborted) {
        pointWeatherLoading.value = false
      }
      if (pointWeatherAbortController === controller) {
        pointWeatherAbortController = null
      }
    }
  }

  /** 计算 bbox 的地理面积（平方度） */
  function bboxArea(bbox: BoundingBox): number {
    return Math.abs(bbox.east - bbox.west) * Math.abs(bbox.north - bbox.south)
  }

  /** 检测请求范围是否发生显著变化（面积比超过阈值），用于决定是否绕过最小刷新间隔 */
  function isSignificantViewportChange(catalogId: string, currentBBox: BoundingBox): boolean {
    const lastBBox = lastWorkflowBBox.get(catalogId)
    if (!lastBBox) return true  // 首次提交或无记录，允许立即提交
    const currentArea = bboxArea(currentBBox)
    const lastArea = bboxArea(lastBBox)
    if (lastArea <= 0) return true
    const ratio = currentArea / lastArea
    // 面积放大或缩小超过阈值（如从城市缩放到全球）时认为是显著变化
    return ratio > SIGNIFICANT_VIEWPORT_RATIO || ratio < 1 / SIGNIFICANT_VIEWPORT_RATIO
  }

  /** 刷新所有活跃的地图型工作流图层（视口变化时调用） */
  async function refreshActiveWeatherWorkflows() {
    const activeWeatherLayers = activeLayers.value.filter(
      (layer) => supportsViewportDrivenRefresh(layer.catalogId) && layer.jobLayer,
    )

    const now = Date.now()
    const currentBBox = currentMapBBox.value
    for (const layer of activeWeatherLayers) {
      const primaryTileSpec = resolvePrimaryWeatherTileSpec(
        layer.catalogId,
        currentMapCenter.value,
        currentBBox,
        currentMapZoom.value,
      )
      const requestBBox = primaryTileSpec?.bbox ?? currentBBox
      const lastRequestBBox = lastWorkflowBBox.get(layer.catalogId)
      if (requestBBox && areBoundingBoxesEqual(lastRequestBBox, requestBBox)) continue

      // 跳过正在提交的工作流
      if (submittingCatalogIds.has(layer.catalogId)) continue
      // 检查距上次提交是否超过最小间隔（对所有状态生效，不仅限 succeeded）
      const lastSubmit = lastWorkflowSubmitTime.get(layer.catalogId) ?? 0
      const elapsed = now - lastSubmit
      if (elapsed < WORKFLOW_REFRESH_MIN_INTERVAL_MS) {
        // 请求范围显著变化（如缩放切换到新的分桶）时绕过最小间隔，允许立即重新提交
        if (!requestBBox || !isSignificantViewportChange(layer.catalogId, requestBBox)) {
          // 调度一次性重试：在剩余时间 + 100ms 后重新触发，确保 2s 间隔不导致更新丢失
          // 页面不可见时延长到 10s，避免后台积压定时器导致回来后卡顿
          const remaining = WORKFLOW_REFRESH_MIN_INTERVAL_MS - elapsed
          const retryDelay = document.hidden ? Math.max(remaining + 100, 10000) : remaining + 100
          if (viewportDebounceTimer.value === null) {
            viewportDebounceTimer.value = window.setTimeout(() => {
              viewportDebounceTimer.value = null
              void refreshActiveWeatherWorkflows()
            }, retryDelay)
          }
          continue
        }
      }
      if (canRunCatalog(layer.catalogId)) {
        try {
          // 重新提交工作流，使用新的请求范围
          await runWorkflowForCatalog(layer.catalogId, { skipIfRequestBBoxUnchanged: true })
        } catch (error) {
          // 单个图层失败不影响其他图层
          console.warn(`[LayersStore] Failed to refresh weather workflow for ${layer.catalogId}:`, error)
        }
      }
    }
  }

  /** 处理视口变化：防抖后刷新活跃的地图型工作流 */
  function handleViewportChange() {
    // 取消之前的防抖定时器
    if (viewportDebounceTimer.value !== null) {
      window.clearTimeout(viewportDebounceTimer.value)
      viewportDebounceTimer.value = null
    }

    // 设置新的防抖定时器
    viewportDebounceTimer.value = window.setTimeout(() => {
      viewportDebounceTimer.value = null
      void refreshActiveWeatherWorkflows()
    }, VIEWPORT_DEBOUNCE_MS)
  }

  /** 更新当前地图视口（中心点 + 可见 bbox + zoom），由 MapCanvas 在 moveend/zoomend 时调用 */
  function setMapViewport(center: { lng: number; lat: number }, bbox: BoundingBox | null, zoom?: number) {
    const bboxChanged = JSON.stringify(currentMapBBox.value) !== JSON.stringify(bbox)
    currentMapCenter.value = center
    currentMapBBox.value = bbox
    if (typeof zoom === 'number' && Number.isFinite(zoom)) {
      currentMapZoom.value = zoom
    }

    // 视口变化时触发工作流刷新（防抖处理）
    if (bboxChanged && activeLayers.value.some((layer) => supportsViewportDrivenRefresh(layer.catalogId) && layer.jobLayer)) {
      for (const layer of activeLayers.value) {
        if (supportsViewportDrivenRefresh(layer.catalogId) && layer.jobLayer) {
          trimWeatherPrefetchQueueForCatalog(layer.catalogId)
        }
      }
      handleViewportChange()
    }
  }

  /** catalogId → 工作流状态映射，用于 library 卡片显示自动运行反馈 */
  const catalogJobStatus = computed(() => {
    const map = new Map<string, JobStatus>()
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
    sidebarView,
    selectedInstanceId,
    jobLayers,
    currentHour,
    workflowError,
    isSubmitting,
    workflowSummary,
    runtimeLayerCatalogLoading,
    particleFlowCatalogId,
    currentMapCenter,
    currentMapBBox,
    currentMapZoom,
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
    removeLayer,
    toggleLayerVisibility,
    setAllLayerVisibility,
    removeAllLayers,
    setLayerOpacity,
    setLayerOrder,
    selectLayer,
    setSidebarView,
    setCurrentHour,
    setJobLayers,
    ensureRuntimeLayerCatalog,
    reorderLayers,
    runWorkflowForCatalog,
    cancelWorkflowRunForJob,
    retryWorkflowRunForJob,
    stopWorkflowPolling,
    getCatalogRunBlockReason,
    canRunCatalog,
    isWeatherEngineLayer,
    supportsMapLayerResult,
    supportsViewportDrivenRefresh,
    supportsParticleFlow,
    toggleParticleFlow,
    setParticleFlow,
    // 点天气查询（单工作流管理）
    pointWeather,
    pointWeatherLoading,
    pointWeatherError,
    fetchPointWeather,
    clearPointWeather,
    setMapViewport,
    handleViewportChange,
    refreshActiveWeatherWorkflows,
  }
})
