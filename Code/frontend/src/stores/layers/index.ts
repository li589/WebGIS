import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import { useWeatherTileManager } from '../weather-tile-manager'
import { useWeatherSourcePrefsStore } from '../weather-source-prefs'
import { debugLog as probeDebugLog } from '../../utils/perf-probe'
import { LAYER_CATEGORIES } from './catalog'
import { createActiveLayersSlice } from './active-layers'
import { createCatalogRuntimeSlice, type CatalogRuntimeSlice } from './catalog-runtime'
import { createRunLayersSlice } from './run-layers'
import { createWeatherViewportSlice } from './weather-viewport'
import { createPointWeatherSlice } from './point-weather'
import { createWorkflowPoller } from './workflow-poller'
import { createWorkflowRunner, saveTrackedWorkflowRuns } from './workflow-runner'
import { buildJobLayer } from './result-adapter'
import { createWorkspaceHydrateSlice } from './workspace-hydrate'
import { isRunDismissed } from './workspace-persist'
import type { JobLayerItem } from './types'

function debugLog(module: string, ...args: unknown[]) {
  probeDebugLog(`[${performance.now().toFixed(1)}ms] [LayersStore:${module}]`, ...args)
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

  // ── Current hour (用于工作流提交与时间轴状态展示) ─────────────────────────────
  const currentHour = ref(12)
  const activeWorkflowCatalogIds = new Set<string>()
  const submittingCatalogIds = new Set<string>()
  const isSubmitting = computed(() => submittingCatalogIds.size > 0)

  // ── 429 容量限制自动重试（业务 workflow 池）────────────────────────────
  const workflowRetryTimers = new Map<string, number>()
  const workflowRetryCounts = new Map<string, number>()

  function isLocalSubmitJobId(jobId: string | null | undefined): boolean {
    return Boolean(jobId && String(jobId).startsWith('local-submit-'))
  }

  // Late-bound deps (poller / runner / viewport / persist / catalog)
  // catalog is assigned after active/run slices; deps close over the binding.
  // eslint-disable-next-line prefer-const -- late-bound across slice init order
  let catalog!: CatalogRuntimeSlice
  let scheduleWorkspacePersist = () => {}
  let flushWorkspacePersistNow = () => {}
  let stopWorkflowPollingFn: (jobId: string) => void = () => {}
  let forgetTrackedWorkflowRunFn: (runId: string) => void = () => {}
  let rememberTrackedWorkflowRunFn: (catalogId: string, jobLayer: JobLayerItem) => void = () => {}
  let enableParticleIfUnsetFn: (catalogId: string) => void = () => {}
  let clearWindForCatalogFn: (catalogId: string) => void = () => {}
  let getParticleFlowCatalogId: () => string | null = () => null
  let getMapCenter: () => { lng: number; lat: number } = () => ({ lng: 0, lat: 0 })
  let getMapZoom: () => number = () => 0
  let getMapBBox: () => import('../../services/runtime-api').BoundingBox | null = () => null

  // Active CRUD / display：见 active-layers.ts
  const activeLayersSlice = createActiveLayersSlice({
    getLayerLibraryMap: () => catalog.layerLibraryMap.value,
    getRuntimeLayerCatalog: () => catalog.runtimeLayerCatalog.value,
    getRunLayerGroups: () => runLayerGroups.value,
    setRunLayerGroups: (groups) => {
      runLayerGroups.value = groups
    },
    getJobLayers: () => jobLayers.value,
    isWeatherEngineLayer: (catalogId) => catalog.isWeatherEngineLayer(catalogId),
    supportsParticleFlow: (catalogId) => catalog.supportsParticleFlow(catalogId),
    weatherProviderArg,
    getMapCenter: () => getMapCenter(),
    getMapZoom: () => getMapZoom(),
    getMapBBox: () => getMapBBox(),
    getCurrentHour: () => currentHour.value,
    getParticleFlowCatalogId: () => getParticleFlowCatalogId(),
    enableParticleIfUnset: (catalogId) => enableParticleIfUnsetFn(catalogId),
    clearWindForCatalog: (catalogId) => clearWindForCatalogFn(catalogId),
    stopWorkflowPolling: (jobId) => stopWorkflowPollingFn(jobId),
    forgetTrackedWorkflowRun: (runId) => forgetTrackedWorkflowRunFn(runId),
    saveTrackedWorkflowRuns: (runs) => saveTrackedWorkflowRuns(runs as never),
    getWorkflowRetryTimers: () => workflowRetryTimers,
    getWorkflowRetryCounts: () => workflowRetryCounts,
    getActiveWorkflowCatalogIds: () => activeWorkflowCatalogIds,
    isLocalSubmitJobId,
    scheduleWorkspacePersist: () => scheduleWorkspacePersist(),
    flushWorkspacePersistNow: () => flushWorkspacePersistNow(),
    debugLog,
  })
  const {
    activeLayers,
    sidebarView,
    selectedInstanceId,
    activeLayersDisplay,
    selectedLayerDisplay,
    activeLayerCount,
    sidebarViewLabel,
    assignLayerAccent,
    addLayer,
    addImportedVectorLayer,
    getImportedVectorGeojson,
    updateImportedVectorGeojson,
    setImportedVectorStyle,
    addImportedRasterLayer,
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
    isLocalImport,
    genInstanceId,
  } = activeLayersSlice

  // Job / materialize / run groups：见 run-layers.ts
  const runLayersSlice = createRunLayersSlice({
    getActiveLayers: () => activeLayers.value,
    addLayer: (catalogId, isAdminBoundary, jobLayer) =>
      addLayer(catalogId, isAdminBoundary, jobLayer),
    removeLayer: (instanceId) => removeLayer(instanceId),
    assignLayerAccent: (preferred) => assignLayerAccent(preferred),
    setSelectedInstanceId: (id) => {
      selectedInstanceId.value = id
    },
    getSidebarView: () => sidebarView.value,
    setSidebarView: (view) => setSidebarView(view),
    getMapCenter: () => getMapCenter(),
    getCurrentHour: () => currentHour.value,
    forgetTrackedWorkflowRun: (runId) => forgetTrackedWorkflowRunFn(runId),
    rememberTrackedWorkflowRun: (catalogId, jobLayer) =>
      rememberTrackedWorkflowRunFn(catalogId, jobLayer),
    isLocalSubmitJobId,
    scheduleWorkspacePersist: () => scheduleWorkspacePersist(),
    genInstanceId,
    addImportedRasterLayer,
  })
  const {
    jobLayers,
    runLayerGroups,
    workflowError,
    workflowProgressTimeSeek,
    workflowSummary,
    emitWorkflowProgressTimeSeek,
    removeJobLayerById,
    setJobLayers,
    upsertJobLayer,
    buildWorkflowPayloadForCatalog,
    syncProgressiveBlockOverlays,
    attachAlgorithmProductOverlays,
    reconcileOmegaBlockLayers,
    reorderLayers,
    createRunLayerGroup,
    bindRunIdToGroup,
    cleanupUnproducedRunLayers,
    refreshRunGroupDissolvable,
    updateRunGroupFromJob,
    dissolveRunGroup,
    reorderWithinRunGroup,
    moveRunGroupBlock,
    findRunGroupByMember,
    findRunGroupById,
  } = runLayersSlice

  // Runtime catalog / library / readiness：见 catalog-runtime.ts
  catalog = createCatalogRuntimeSlice({
    getActiveLayers: () => activeLayers.value,
    getRunLayerGroups: () => runLayerGroups.value,
    getJobLayers: () => jobLayers.value,
    onCatalogLoaded: () => reconcileActiveWeatherLayers(),
  })
  const {
    runtimeLayerCatalog,
    runtimeLayerCatalogLoading,
    layerLibrary,
    layerLibraryMap,
    catalogJobStatus,
    catalogRunReadiness,
    ensureRuntimeLayerCatalog,
    resolveBackendLayerId,
    resolveEffectiveDescriptor,
    supportsAnalysisWorkflow,
    getCatalogRunBlockReason,
    canRunCatalog,
    isWeatherEngineLayer,
    supportsMapLayerResult,
    supportsViewportDrivenRefresh,
    supportsParticleFlow,
    getLayerPrimaryMetric,
  } = catalog

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

  // Bind viewport helpers used by active/run slices (created above as late lets).
  getParticleFlowCatalogId = () => particleFlowCatalogId.value
  enableParticleIfUnsetFn = enableParticleIfUnset
  clearWindForCatalogFn = clearWindForCatalog
  getMapCenter = () => currentMapCenter.value
  getMapZoom = () => currentMapZoom.value
  getMapBBox = () => currentMapBBox.value
  stopWorkflowPollingFn = workflowPoller.stopWorkflowPolling

  function setCurrentHour(hour: number) {
    currentHour.value = hour
  }

  // Workspace persist / hydrate：见 workspace-hydrate.ts
  // Created after viewport bind so getMap* late lets are populated.
  const workspaceHydrate = createWorkspaceHydrateSlice({
    getActiveLayers: () => activeLayers.value,
    getRunLayerGroups: () => runLayerGroups.value,
    getSidebarView: () => sidebarView.value,
    setSidebarView: (view) => setSidebarView(view),
    getLayerLibraryMap: () => layerLibraryMap.value,
    assignLayerAccent: (preferred) => assignLayerAccent(preferred),
    genInstanceId,
    isLocalImport,
    isWeatherEngineLayer: (catalogId) => isWeatherEngineLayer(catalogId),
    weatherProviderArg,
    getMapCenter: () => getMapCenter(),
    getMapZoom: () => getMapZoom(),
    getMapBBox: () => getMapBBox(),
    getCurrentHour: () => currentHour.value,
    bindPersistFns: (fns) => {
      scheduleWorkspacePersist = fns.scheduleWorkspacePersist
      flushWorkspacePersistNow = fns.flushWorkspacePersistNow
    },
  })
  const { hydrateWorkspaceFromSnapshot, hydrateVectorLayersFromSnapshot } = workspaceHydrate

  // isWeatherEngineLayer / supports* / getLayerPrimaryMetric：见 catalog-runtime.ts

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

  // catalogJobStatus / catalogRunReadiness：见 catalog-runtime.ts

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
    rememberTrackedWorkflowRun: rememberTrackedWorkflowRunImpl,
    forgetTrackedWorkflowRun: forgetTrackedWorkflowRunImpl,
  } = workflowRunner
  rememberTrackedWorkflowRunFn = rememberTrackedWorkflowRunImpl
  forgetTrackedWorkflowRunFn = forgetTrackedWorkflowRunImpl

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
