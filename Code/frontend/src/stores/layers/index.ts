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
} from '../../services/runtime-api'
import {
  supportsMapLayerCapability,
  supportsParticleFlowCapability,
  supportsViewportDrivenRefreshCapability,
} from '../../services/layer-capabilities'
import { useWeatherTileManager } from '../weather-tile-manager'
import { useWeatherSourcePrefsStore } from '../weather-source-prefs'
import { buildDefaultWeatherRenderHint } from '../../components/map/weather-render'
import type {
  BoundingBox,
  RuntimeLayerDescriptor,
  WeatherPointResponse,
  WorkflowEvent,
} from '../../services/runtime-api'
import { LAYER_CATEGORIES, LAYER_LIBRARY } from './catalog'
import { isWeatherEngineCatalogId } from './weather-session'
import { createWeatherViewportSlice } from './weather-viewport'
import { buildJobLayer } from './result-adapter'
import { buildImportedVectorPayload } from './imported-vector'
import { buildImportedRasterPayload } from './imported-raster'
import { deleteImportedRaster } from '../../services/data-import'
import { useWorkflowOutputLayersStore } from '../workflow-output-layers'
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

/** 本地导入（矢量 / 栅格）不走 catalog / tile manager */
function isLocalImport(layer: ActiveLayer): boolean {
  return Boolean(layer.importedVector || layer.importedRaster)
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
const EVENT_POLL_MAX_DURATION_MS = 600_000
const MAX_EVENT_MESSAGE_COUNT = 5
const MAX_CONSECUTIVE_POLL_ERRORS = 3
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
    const text = `${event.channel} · ${event.message}`
    if (merged[merged.length - 1] !== text) {
      merged.push(text)
    }
  }
  return merged.slice(-MAX_EVENT_MESSAGE_COUNT)
}

function hasRenderableMapLayerAsset(jobLayer: JobLayerItem | null | undefined) {
  const assets = jobLayer?.mapLayerPayload?.layerAssets
  return Boolean(
    assets?.geojsonData || assets?.geojsonUrl || assets?.cogUrl || assets?.cogPreviewUrl,
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

    return items.concat(outputItems).sort((a, b) => {
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
      .sort((a, b) => a.order - b.order)
      .map((layer): ActiveLayerDisplay | null => {
        if (layer.importedVector) {
          const payload = layer.importedVector
          const displayName = layer.name ?? payload.fileName ?? '导入图层'
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
            accentColor: '#7ee0a8',
            accentGlow: 'rgba(126, 224, 168, 0.28)',
            chipTone: 'rgba(126, 224, 168, 0.16)',
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
            importedBounds: payload.bounds,
          }
        }

        if (layer.importedRaster) {
          const payload = layer.importedRaster
          const displayName = layer.name ?? payload.fileName ?? '导入栅格'
          return {
            instanceId: layer.instanceId,
            catalogId: layer.catalogId,
            name: displayName,
            category: 'imported',
            description: '本地导入栅格（TIF overlay）',
            engine: 'local',
            supportsTime: false,
            runReadiness: 'ready',
            runReadinessSummary: '本地栅格已注册',
            summary: '本地 TIF 栅格叠加',
            metricLabel: '类型',
            metricValue: '栅格',
            trendLabel: '本地栅格叠加',
            statusLabel: '已导入',
            updateLabel: '本地文件',
            sourceLabel: payload.fileName ?? '本地导入',
            confidenceLabel: '本地数据',
            accentColor: '#7eb8e0',
            accentGlow: 'rgba(126, 184, 224, 0.28)',
            chipTone: 'rgba(126, 184, 224, 0.16)',
            availabilityState: 'ready',
            availabilityLabel: '完整数据',
            availabilityDescription: '已通过后端注册为 overlay，可在图层列表控制显隐与透明度。',
            observationTimeLabel: '本地',
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
            // 空 GeoJSON 被缓存时不应显示「完整数据」
            const merged = weatherTileManager.getMergedGeojsonForViewport(layer.catalogId)
            const featureCount = merged?.features?.length ?? 0
            if (featureCount === 0) {
              finalAvailability = {
                state: 'empty' as const,
                label: '无有效数据',
                description: '视口瓦片已缓存但无要素，可能模型未同步或时段无数据',
              }
            } else {
              finalAvailability = {
                state: 'ready' as const,
                label: '完整数据',
                description: `已缓存全部 ${tileStats.visible} 个可视瓦片`,
              }
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
          name: layer.isAdminBoundary ? '行政区边界' : item.name,
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
          accentColor: layer.isAdminBoundary ? '#88d8ff' : item.accentColor,
          accentGlow: layer.isAdminBoundary ? 'rgba(136, 216, 255, 0.3)' : item.accentGlow,
          chipTone: layer.isAdminBoundary ? 'rgba(136, 216, 255, 0.16)' : item.chipTone,
          availabilityState: layer.isAdminBoundary ? 'ready' : finalAvailability.state,
          availabilityLabel: layer.isAdminBoundary ? '完整数据' : finalAvailability.label,
          availabilityDescription: layer.isAdminBoundary
            ? '静态矢量边界数据，已完整加载。'
            : (realDisplay.availabilityDescription ?? finalAvailability.description),
          observationTimeLabel: layer.isAdminBoundary
            ? '静态数据'
            : isWeatherLayer
              ? `${String(currentHour.value).padStart(2, '0')}:00`
              : (realDisplay.observationTimeLabel ??
                (item.supportsTime ? `${String(currentHour.value).padStart(2, '0')}:00` : '--')),
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

  function addLayer(catalogId: string, isAdminBoundary = false, jobLayer?: JobLayerItem) {
    // 防止重复添加同 catalogId (除非来自不同 job)
    if (!isAdminBoundary && !jobLayer) {
      if (
        activeLayers.value.some(
          (l) => l.catalogId === catalogId && !l.jobLayer && !isLocalImport(l),
        )
      ) {
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
  }

  /** 将本地 SHP / GeoJSON / CSV 矢量添加到活动图层列表，可在侧栏控制显隐并导出 */
  function addImportedVectorLayer(name: string, geojson: GeoJSON.FeatureCollection): ActiveLayer {
    const maxOrder = activeLayers.value.reduce((max, l) => Math.max(max, l.order), 0)
    const instanceId = genInstanceId()
    const catalogId = `imported-${instanceId}`
    const payload = buildImportedVectorPayload(geojson, name)
    const layer: ActiveLayer = {
      instanceId,
      catalogId,
      name: name.replace(/\.(geojson|json|shp|zip|csv)$/i, '') || name,
      visible: true,
      opacity: 0.85,
      order: maxOrder + 1,
      isAdminBoundary: false,
      importedVector: payload,
      dataState: 'imported',
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId
    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
    return layer
  }

  function getImportedVectorGeojson(instanceId: string): GeoJSON.FeatureCollection | null {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    return layer?.importedVector?.geojson ?? null
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
    })
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
    }
    activeLayers.value.push(layer)
    selectedInstanceId.value = layer.instanceId
    if (sidebarView.value === 'empty' || sidebarView.value === 'library') {
      sidebarView.value = 'active'
    }
    return layer
  }

  function removeLayer(instanceId: string) {
    const idx = activeLayers.value.findIndex((l) => l.instanceId === instanceId)
    if (idx === -1) return
    pendingVisibilitySync.delete(instanceId)
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
    // 清理 tile manager 中对应图层状态
    if (!layer.isAdminBoundary && !isLocalImport(layer) && isWeatherEngineLayer(layer.catalogId)) {
      weatherTileManager.clearLayer(layer.catalogId)
    }
    // 导入栅格：best-effort 清理后端 overlay 与磁盘文件
    const overlayId = layer.importedRaster?.overlayLayerId
    if (overlayId) {
      void deleteImportedRaster(overlayId).catch((err) => {
        console.warn('[layers] deleteImportedRaster failed', overlayId, err)
      })
    }
    clearWindForCatalog(layer.catalogId)
    activeLayers.value.splice(idx, 1)

    if (selectedInstanceId.value === instanceId) {
      selectedInstanceId.value = activeLayers.value[0]?.instanceId ?? null
    }
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
  }

  /** 批量移除所有图层（保留行政区边界） */
  function removeAllLayers(keepBoundary = true) {
    if (visibilitySyncRaf !== null) {
      globalThis.cancelAnimationFrame(visibilitySyncRaf)
      visibilitySyncRaf = null
    }
    pendingVisibilitySync.clear()
    const layersToRemove = activeLayers.value.filter(
      (layer) => !keepBoundary || !layer.isAdminBoundary,
    )
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
      if (!isLocalImport(layer) && isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.clearLayer(layer.catalogId)
      }
      clearWindForCatalog(layer.catalogId)
      activeWorkflowCatalogIds.delete(layer.catalogId)
    }
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

  /**
   * 对于工作流产出图层（catalogId 以 wf-out- 为前缀），返回其源 layer_id；
   * 普通图层则返回自身 catalogId。用于后端提交时解析引擎请求。
   */
  function resolveBackendLayerId(catalogId: string): string {
    if (!catalogId.startsWith('wf-out-')) return catalogId
    const outputStore = useWorkflowOutputLayersStore()
    const entry = outputStore.getByLocalId(catalogId)
    return entry?.sourceLayerId ?? catalogId
  }

  /**
   * 对于工作流产出图层，返回其源图层的 descriptor（用于能力判断）；
   * 普通图层则返回自身 descriptor。
   */
  function resolveEffectiveDescriptor(catalogId: string): RuntimeLayerDescriptor | null {
    if (!catalogId.startsWith('wf-out-')) {
      return getRuntimeLayerDescriptor(catalogId)
    }
    const backendId = resolveBackendLayerId(catalogId)
    return getRuntimeLayerDescriptor(backendId)
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

  function removeJobLayerById(jobId: string) {
    const idx = jobLayers.value.findIndex((item) => item.jobId === jobId)
    if (idx >= 0) {
      jobLayers.value.splice(idx, 1)
    }
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
  }

  function buildWorkflowPayloadForCatalog(
    catalogId: string,
    catalogName: string,
    requestedOutputs: string[],
    requestBBox: BoundingBox | null,
    backendLayerId?: string,
    algorithmRequest?: Record<string, unknown>,
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
    return payload
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
            lastEventId: existingJobLayer.lastEventId,
            lastEventAt: existingJobLayer.lastEventAt,
            eventMessages: existingJobLayer.eventMessages,
            diagnosticNotes: jobLayer.diagnosticNotes?.length
              ? jobLayer.diagnosticNotes
              : (existingJobLayer.eventMessages ?? existingJobLayer.diagnosticNotes),
          }
        : jobLayer

    upsertJobLayer(catalogId, mergedJobLayer)
    workflowLastStatusSyncAt.set(jobId, now)

    if (isTerminalStatus(mergedJobLayer.status)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
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

  async function pollWorkflowRun(
    jobId: string,
    catalogId: string,
    startTime = Date.now(),
    consecutiveErrors = 0,
    expectedViewportEpoch?: number,
  ) {
    if (isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      return
    }
    if (Date.now() - startTime > EVENT_POLL_MAX_DURATION_MS) {
      stopWorkflowPolling(jobId)
      activeWorkflowCatalogIds.delete(catalogId)
      workflowError.value = `工作流 ${jobId} 事件等待超时（${EVENT_POLL_MAX_DURATION_MS / 1000}s）`
      const existingJobLayer = jobLayers.value.find((item) => item.jobId === jobId)
      if (existingJobLayer && !isViewportRefreshStale(expectedViewportEpoch)) {
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
      if (isViewportRefreshStale(expectedViewportEpoch)) {
        stopWorkflowPolling(jobId)
        activeWorkflowCatalogIds.delete(catalogId)
        return
      }
      const newItems = events.items ?? []

      if (existingJobLayer && newItems.length > 0) {
        upsertJobLayer(catalogId, applyWorkflowEventsToJobLayer(existingJobLayer, newItems))
        nextDelayMs = EVENT_POLL_ACTIVE_INTERVAL_MS
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
      void pollWorkflowRun(
        jobId,
        catalogId,
        startTime,
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

  /**
   * 从后端恢复活跃工作流列表。在页面加载 / 刷新后调用，
   * 确保跨会话和定时器触发的工作流也能被状态栏跟踪。
   */
  async function restoreActiveWorkflows() {
    try {
      const activeRuns = await listActiveWorkflowRuns()
      for (const run of activeRuns) {
        // 跳过已在跟踪的
        if (workflowPollingHandles.has(run.run_id)) continue
        const existing = jobLayers.value.find((item) => item.jobId === run.run_id)
        if (existing && !isTerminalStatus(existing.status)) continue

        const catalogId = ((run as Record<string, unknown>).layer_id as string) ?? run.run_id
        const jobLayer = await buildJobLayer(run, catalogId, {})
        upsertJobLayer(catalogId, jobLayer)
        if (!isTerminalStatus(jobLayer.status)) {
          activeWorkflowCatalogIds.add(catalogId)
          void pollWorkflowRun(run.run_id, catalogId)
        }
      }
    } catch (err) {
      console.error('[layers] restoreActiveWorkflows failed:', err)
    }
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
      // 天气图层走瓦片管道，不提交 /workflow-runs（此前 silent return 导致「运行无反应」）
      if (isWeatherEngineLayer(backendLayerId)) {
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
        options.algorithmRequest &&
        (options.algorithmRequest.workflow_definition || options.algorithmRequest.workflow_name),
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
      if (errMsg.includes('429')) {
        workflowError.value = '工作流并发数已达上限，正在等待空闲后自动重试…'
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
          message: '等待工作流容量，自动重试中…',
          metrics: [],
          reportSummary: '等待工作流容量，自动重试中…',
          resultUrl: undefined,
        })
        scheduleWorkflowRetry(catalogId)
      } else {
        workflowError.value = errMsg
        upsertJobLayer(catalogId, {
          jobId: submitJobId,
          catalogId,
          name: catalogName,
          commandType: 'analysis',
          status: 'failed',
          progress: 0,
          createdAt: submitStartedAt,
          updatedAt: new Date().toISOString(),
          message: errMsg,
          metrics: [],
          reportSummary: errMsg,
          diagnosticNotes: [errMsg],
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
    const sorted = activeLayers.value.slice().sort((a, b) => a.order - b.order)
    const [moved] = sorted.splice(fromIndex, 1)
    sorted.splice(toIndex, 0, moved)
    sorted.forEach((layer, i) => {
      layer.order = i
    })
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
    lastPointWeatherQuery.value = { lng, lat, catalogId }
    try {
      const weather = await getWeatherPoint({
        layer_id: catalogId,
        latitude: lat,
        longitude: lng,
        forecast_hours: 6,
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
    sidebarView,
    selectedInstanceId,
    jobLayers,
    currentHour,
    workflowError,
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
    removeLayer,
    toggleLayerVisibility,
    setAllLayerVisibility,
    removeAllLayers,
    setLayerOpacity,
    setLayerPaletteOverride,
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
    refreshActiveWeatherWorkflows,
    // 外部工作流跟踪与恢复
    registerExternalWorkflowRun,
    restoreActiveWorkflows,
  }
})
