import { computed, nextTick, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { fetchLayerCatalog, materializeWorkflowMapLayers } from '../../services/runtime-api'
import {
  supportsMapLayerCapability,
  supportsParticleFlowCapability,
  supportsViewportDrivenRefreshCapability,
} from '../../services/layer-capabilities'
import { useWeatherTileManager } from '../weather-tile-manager'
import { useWeatherSourcePrefsStore } from '../weather-source-prefs'
import { useUiStore } from '../ui'
import { formatClockHourLabel } from '../../utils/weather-timeline'
import { resolveWeatherTileReadyKind } from '../../utils/weather-tile-readiness'
import { buildDefaultWeatherRenderHint } from '../../data/weather-render-hints'
import type { BoundingBox, RuntimeLayerDescriptor } from '../../services/runtime-api'
import { LAYER_CATEGORIES, LAYER_LIBRARY } from './catalog'
import { allocateLayerAccent } from './layer-accent'
import { isWeatherEngineCatalogId } from './weather-session'
import { createWeatherViewportSlice } from './weather-viewport'
import { createPointWeatherSlice } from './point-weather'
import { createWorkflowPoller } from './workflow-poller'
import { createWorkflowRunner, saveTrackedWorkflowRuns } from './workflow-runner'
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
import {
  asRecord,
  buildAvailabilityState,
  buildCatalogFallbackItem,
  buildRuntimeLayerLibraryItem,
  CATEGORY_INDEX_BY_ID,
  extractLayerHotspots,
  formatClockLabel,
  getCatalogDisplayName,
  isBlockedRunReadiness,
  isTerminalStatus,
} from './catalog-builders'
import { WORKFLOW_COPY } from '../../ui-copy/workflow'
import { resolveEmptyOverlayWorkflowError } from './materialize-empty'
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

/** tracked runs 持久化与恢复编排：见 ./workflow-runner.ts（阶段三B 抽离） */

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
  const activeWorkflowCatalogIds = new Set<string>()
  const submittingCatalogIds = new Set<string>()
  const isSubmitting = computed(() => submittingCatalogIds.size > 0)

  // ── 429 容量限制自动重试（业务 workflow 池）────────────────────────────
  // 后端 business 池默认 max_active_runs=8；天气瓦片热路径走 /weather/tiles，不占此池。
  // 显式 weather_tile_render workflow 使用独立的 max_active_weather_tile_runs。
  // 这里记录重试定时器和次数，business 池 429 时创建 queued jobLayer 并自动重试。
  // 重试上限/间隔常量与调度逻辑在 workflow-runner.ts；Map 由 store 持有（removeLayer 等清理用）。
  const workflowRetryTimers = new Map<string, number>()
  const workflowRetryCounts = new Map<string, number>()

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

  // 点天气查询（单工作流管理）：见 point-weather.ts
  const pointWeatherSlice = createPointWeatherSlice({
    getCurrentHour: () => currentHour.value,
    isWeatherEngineLayer: (catalogId) => isWeatherEngineLayer(catalogId),
    weatherProviderQuery: (catalogId) => weatherProviderQuery(catalogId),
  })
  const {
    pointWeather,
    pointWeatherLoading,
    pointWeatherError,
    lastPointWeatherQuery,
    clearPointWeather,
    fetchPointWeather,
  } = pointWeatherSlice

  // 工作流轮询（事件增量 + 快照同步）：见 workflow-poller.ts
  const workflowPoller = createWorkflowPoller({
    getJobLayer: (jobId) => jobLayers.value.find((item) => item.jobId === jobId),
    isViewportRefreshStale: (epoch) => isViewportRefreshStale(epoch),
    isRunDismissed: (runId) => isRunDismissed(runId),
    getParticleFlowCatalogId: () => particleFlowCatalogId.value,
    supportsParticleFlow: (catalogId) => supportsParticleFlow(catalogId),
    upsertJobLayer: (catalogId, jobLayer) => upsertJobLayer(catalogId, jobLayer),
    setWorkflowError: (msg) => {
      workflowError.value = msg
    },
    removeActiveCatalog: (catalogId) => activeWorkflowCatalogIds.delete(catalogId),
    syncProgressiveBlockOverlays: (runId, catalogId) =>
      void syncProgressiveBlockOverlays(runId, catalogId),
    emitWorkflowProgressTimeSeek: (jobLayer, status, detail) =>
      emitWorkflowProgressTimeSeek(jobLayer, status, detail),
    attachAlgorithmProductOverlays: (refs, catalogId, runId) =>
      attachAlgorithmProductOverlays(refs as never, catalogId, runId),
    clearWindForCatalog: (catalogId) => clearWindForCatalog(catalogId),
    enableParticleIfUnset: (catalogId) => enableParticleIfUnset(catalogId),
    buildJobLayer: (run, catalogId, opts) => buildJobLayer(run as never, catalogId, opts),
  })
  const { stopWorkflowPolling } = workflowPoller

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
            importedRasterOverlayLayerId: payload.overlayLayerId,
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
            paletteOverride: layer.paletteOverride ?? null,
            vminOverride: layer.vminOverride ?? null,
            vmaxOverride: layer.vmaxOverride ?? null,
            nodataMode: layer.nodataMode ?? null,
            nodataColor: layer.nodataColor ?? null,
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
          } else {
            const readyKind = resolveWeatherTileReadyKind(tileStats)
            if (readyKind === 'ready') {
              // 勿在 activeLayersDisplay 热路径调用 getMergedGeojsonForViewport：
              // 同步合并视口瓦片会卡主线程，表现为点「已添加图层」无响应。
              // 无数据场景由上方 data-empty 状态覆盖。
              finalAvailability = {
                state: 'ready' as const,
                label: '完整数据',
                description: `已缓存全部 ${tileStats.visible} 个可视瓦片`,
              }
            } else if (readyKind === 'partial') {
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
        }

        const rasterPayload = layer.importedRaster as
          import('./imported-raster').ImportedRasterPayload | undefined
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
          isImportedRaster: Boolean(layer.importedRaster),
          jobLayer: layer.jobLayer,
          visible: layer.visible,
          opacity: layer.opacity,
          order: layer.order,
          dataState: layer.dataState,
          importedRasterOverlayLayerId: rasterPayload?.overlayLayerId,
          importedRasterBounds: rasterPayload?.bounds,
          importedBounds: rasterPayload?.bounds,
          importedRasterSourceCrs: rasterPayload?.sourceCrs,
          importedRasterNativeStep:
            typeof rasterPayload?.nativeStep === 'string'
              ? rasterPayload.nativeStep
              : rasterPayload?.nativeStep
                ? `${rasterPayload.nativeStep.value}${rasterPayload.nativeStep.unit === 'hour' ? 'h' : rasterPayload.nativeStep.unit === 'day' ? 'd' : rasterPayload.nativeStep.unit === 'month' ? 'm' : 'yr'}`
                : undefined,
          importedRasterEffectiveTime: rasterPayload?.effectiveTimeLabel,
          importedRasterTimeCount: rasterPayload?.timeList?.length ?? 0,
          paletteOverride: layer.paletteOverride ?? null,
          vminOverride: layer.vminOverride ?? null,
          vmaxOverride: layer.vmaxOverride ?? null,
          nodataMode: layer.nodataMode ?? null,
          nodataColor: layer.nodataColor ?? null,
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
      scheduleWorkspacePersist()
    }
  }

  function setLayerRangeOverride(
    instanceId: string,
    range: { vmin?: number | null; vmax?: number | null },
  ) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    if ('vmin' in range) layer.vminOverride = range.vmin ?? null
    if ('vmax' in range) layer.vmaxOverride = range.vmax ?? null
    scheduleWorkspacePersist()
  }

  function setLayerNodataDisplay(
    instanceId: string,
    options: { mode?: 'transparent' | 'solid' | null; color?: string | null },
  ) {
    const layer = activeLayers.value.find((l) => l.instanceId === instanceId)
    if (!layer) return
    if ('mode' in options) layer.nodataMode = options.mode ?? null
    if ('color' in options) layer.nodataColor = options.color ?? null
    scheduleWorkspacePersist()
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
      if (hadError) {
        const note = errorMsg || WORKFLOW_COPY.progressiveSyncFailed
        const notes = [...(job.diagnosticNotes ?? [])]
        if (!notes.includes(note)) notes.unshift(note)
        job.diagnosticNotes = notes.slice(0, 8)
      }
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

  /** Attach algorithm-published overlays so the map shows SM/VOD/OMEGA content. */
  async function attachAlgorithmProductOverlays(
    resultRefs: Parameters<typeof extractOverlayImportsFromResultRefs>[0],
    preferredCatalogId: string,
    runId?: string,
    opts?: { forceBind?: boolean },
  ): Promise<number> {
    if (runId && !opts?.forceBind && isRunDismissed(runId)) return 0

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
        const errMsg = error instanceof Error ? error.message : String(error)
        console.warn('[layers] materializeWorkflowMapLayers failed', runId, error)
        // Failed/cancelled runs correctly get 409 from BE — do not pin a yellow banner.
        const isNonMaterializableConflict =
          /\b409\b/.test(errMsg) ||
          /cannot materialize/i.test(errMsg) ||
          /ExecutionStatus\.(failed|cancelled)/i.test(errMsg)
        if (!isNonMaterializableConflict) {
          // 发布就绪修复（P0-9）：其它 materialize 失败落到 workflowError，
          // 避免"工作流显示 succeeded 但地图无图层、无任何错误提示"。
          workflowError.value = `工作流结果图层加载失败：${errMsg}`
        }
      }
    }
    if (!imports.length) {
      // 审查 BUG-4：原始 imports 为空（非 dismiss 滤空）时给出可见空态
      const emptyMsg = resolveEmptyOverlayWorkflowError({
        runId,
        rawImportCount: 0,
        existingWorkflowError: workflowError.value,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
      })
      if (emptyMsg) workflowError.value = emptyMsg
      return 0
    }
    imports = imports.filter((item) => opts?.forceBind || !isOverlayDismissed(item.overlayLayerId))
    if (!imports.length) return 0

    const outputStore = useWorkflowOutputLayersStore()
    for (const item of imports) {
      if (!opts?.forceBind && isOverlayDismissed(item.overlayLayerId)) continue
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
      paletteOverride: saved.paletteOverride ?? null,
      vminOverride: saved.vminOverride ?? null,
      vmaxOverride: saved.vmaxOverride ?? null,
      nodataMode: saved.nodataMode ?? null,
      nodataColor: saved.nodataColor ?? null,
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
        paletteOverride: saved.paletteOverride ?? null,
        vminOverride: saved.vminOverride ?? null,
        vmaxOverride: saved.vmaxOverride ?? null,
        nodataMode: saved.nodataMode ?? null,
        nodataColor: saved.nodataColor ?? null,
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

  // 工作流提交/取消/重试 + 恢复编排：见 workflow-runner.ts（阶段三B）
  // 实例化必须位于 workflowPoller 之后、return 之前（deps 引用的函数声明均有提升，
  // 但 slice 解构成员/箭头函数需在其实例化之后才能安全引用）。
  const workflowRunner = createWorkflowRunner({
    // ── poller（三A 产物）──
    startPolling: (jobId, catalogId, epoch) => workflowPoller.startPolling(jobId, catalogId, epoch),
    stopWorkflowPolling: (jobId) => workflowPoller.stopWorkflowPolling(jobId),
    isPolling: (jobId) => workflowPoller.isPolling(jobId),
    syncWorkflowRunSnapshot: (jobId, catalogId, force, epoch) =>
      workflowPoller.syncWorkflowRunSnapshot(jobId, catalogId, force, epoch),
    applyWorkflowEventsToJobLayer: (jobLayer, events) =>
      workflowPoller.applyWorkflowEventsToJobLayer(jobLayer, events),
    // ── 状态读 ──
    getActiveLayers: () => activeLayers.value,
    getJobLayers: () => jobLayers.value,
    getRunLayerGroups: () => runLayerGroups.value,
    getRuntimeLayerCatalog: () => runtimeLayerCatalog.value,
    getLayerLibrary: () => layerLibrary.value,
    getMapBBox: () => currentMapBBox.value,
    activeWorkflowCatalogIds,
    submittingCatalogIds,
    workflowRetryTimers,
    workflowRetryCounts,
    // ── 状态写 ──
    setRunLayerGroups: (groups) => {
      runLayerGroups.value = groups
    },
    upsertJobLayer: (catalogId, jobLayer) => upsertJobLayer(catalogId, jobLayer),
    removeJobLayerById: (jobId) => removeJobLayerById(jobId),
    setWorkflowError: (msg) => {
      workflowError.value = msg
    },
    scheduleWorkspacePersist: () => scheduleWorkspacePersist(),
    cleanupUnproducedRunLayers: (runId) => cleanupUnproducedRunLayers(runId),
    createRunLayerGroup: (options) => createRunLayerGroup(options),
    bindRunIdToGroup: (groupId, runId) => bindRunIdToGroup(groupId, runId),
    attachAlgorithmProductOverlays: (refs, catalogId, runId, opts) =>
      attachAlgorithmProductOverlays(refs as never, catalogId, runId, opts),
    // ── 业务判定 / 载荷构建 ──
    isLocalSubmitJobId: (jobId) => isLocalSubmitJobId(jobId),
    isViewportRefreshStale: (epoch) => isViewportRefreshStale(epoch),
    isWeatherEngineLayer: (catalogId) => isWeatherEngineLayer(catalogId),
    resolveBackendLayerId: (catalogId) => resolveBackendLayerId(catalogId),
    ensureRuntimeLayerCatalog: (force) => ensureRuntimeLayerCatalog(force),
    getCatalogRunBlockReason: (catalogId) => getCatalogRunBlockReason(catalogId),
    supportsAnalysisWorkflow: (catalogId) => supportsAnalysisWorkflow(catalogId),
    supportsMapLayerResult: (catalogId) => supportsMapLayerResult(catalogId),
    buildWorkflowPayloadForCatalog: (
      catalogId,
      catalogName,
      requestedOutputs,
      requestBBox,
      backendLayerId,
      algorithmRequest,
      weatherRequest,
    ) =>
      buildWorkflowPayloadForCatalog(
        catalogId,
        catalogName,
        requestedOutputs,
        requestBBox,
        backendLayerId,
        algorithmRequest,
        weatherRequest,
      ),
    activateWeatherTileViewport: (catalogId) => {
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
    },
    // ── 快照恢复 ──
    hydrateWorkspaceFromSnapshot: () => hydrateWorkspaceFromSnapshot(),
    hydrateVectorLayersFromSnapshot: (instanceIdMap) =>
      hydrateVectorLayersFromSnapshot(instanceIdMap),
    reconcileOmegaBlockLayers: () => reconcileOmegaBlockLayers(),
  })
  const {
    restoreActiveWorkflows,
    registerExternalWorkflowRun,
    runWorkflowForCatalog,
    cancelWorkflowRunForJob,
    retryWorkflowRunForJob,
    rememberTrackedWorkflowRun,
    forgetTrackedWorkflowRun,
  } = workflowRunner

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
    setLayerRangeOverride,
    setLayerNodataDisplay,
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
