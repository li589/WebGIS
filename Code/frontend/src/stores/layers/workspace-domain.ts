/**
 * D2: Workspace domain — shared state + active layer CRUD + runtime catalog.
 *
 * Extracted from the original god store ``index.ts``. Owns:
 * - Cross-cutting state: ``currentHour``, ``activeWorkflowCatalogIds``,
 *   ``submittingCatalogIds``, ``workflowRetryTimers/Counts``.
 * - ``activeLayersSlice``: layer list CRUD, display, import, ordering.
 * - ``catalogRuntimeSlice``: runtime catalog fetch, library, readiness.
 *
 * Cross-domain dependencies are resolved lazily via the ``CrossDomainBindings``
 * object (populated by ``index.ts`` after all domains are created).
 */
import { computed, ref } from 'vue'

import { debugLog as probeDebugLog } from '../../utils/perf-probe'
import { createActiveLayersSlice } from './active-layers'
import { createCatalogRuntimeSlice, type CatalogRuntimeSlice } from './catalog-runtime'
import { saveTrackedWorkflowRuns } from './workflow-runner'
import type { CrossDomainBindings } from './bindings'

function debugLog(module: string, ...args: unknown[]) {
  probeDebugLog(`[${performance.now().toFixed(1)}ms] [LayersStore:${module}]`, ...args)
}

export function createWorkspaceDomain(bindings: CrossDomainBindings) {
  // ── Cross-cutting shared state ──
  const currentHour = ref(12)
  const activeWorkflowCatalogIds = new Set<string>()
  const submittingCatalogIds = new Set<string>()
  const isSubmitting = computed(() => submittingCatalogIds.size > 0)
  const workflowRetryTimers = new Map<string, number>()
  const workflowRetryCounts = new Map<string, number>()

  function isLocalSubmitJobId(jobId: string | null | undefined): boolean {
    return Boolean(jobId && String(jobId).startsWith('local-submit-'))
  }

  // ── Late-bound intra-domain catalog (circular: activeLayers ↔ catalog) ──
  // eslint-disable-next-line prefer-const
  let catalog!: CatalogRuntimeSlice

  // ── activeLayersSlice ──
  const activeLayersSlice = createActiveLayersSlice({
    getLayerLibraryMap: () => catalog.layerLibraryMap.value,
    getRuntimeLayerCatalog: () => catalog.runtimeLayerCatalog.value,
    getRunLayerGroups: () => bindings.getRunLayerGroups(),
    setRunLayerGroups: (groups) => bindings.setRunLayerGroups(groups),
    getJobLayers: () => bindings.getJobLayers(),
    isWeatherEngineLayer: (catalogId) => catalog.isWeatherEngineLayer(catalogId),
    supportsParticleFlow: (catalogId) => catalog.supportsParticleFlow(catalogId),
    weatherProviderArg: (catalogId) => bindings.weatherProviderArg(catalogId),
    getMapCenter: () => bindings.getMapCenter(),
    getMapZoom: () => bindings.getMapZoom(),
    getMapBBox: () => bindings.getMapBBox(),
    getCurrentHour: () => currentHour.value,
    getParticleFlowCatalogId: () => bindings.getParticleFlowCatalogId(),
    enableParticleIfUnset: (catalogId) => bindings.enableParticleIfUnset(catalogId),
    clearWindForCatalog: (catalogId) => bindings.clearWindForCatalog(catalogId),
    stopWorkflowPolling: (jobId) => bindings.stopWorkflowPolling(jobId),
    cancelWorkflowRunForJob: (jobId, catalogId) =>
      bindings.cancelWorkflowRunForJob(jobId, catalogId),
    forgetTrackedWorkflowRun: (runId) => bindings.forgetTrackedWorkflowRun(runId),
    saveTrackedWorkflowRuns: (runs) => saveTrackedWorkflowRuns(runs as never),
    getWorkflowRetryTimers: () => workflowRetryTimers,
    getWorkflowRetryCounts: () => workflowRetryCounts,
    getActiveWorkflowCatalogIds: () => activeWorkflowCatalogIds,
    isLocalSubmitJobId,
    scheduleWorkspacePersist: () => bindings.scheduleWorkspacePersist(),
    flushWorkspacePersistNow: (opts) => bindings.flushWorkspacePersistNow(opts),
    debugLog,
    canRunCatalog: (catalogId) => catalog.canRunCatalog(catalogId),
    runWorkflowForCatalog: (catalogId) => bindings.runWorkflowForCatalog(catalogId),
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
    addDrawDraftLayer,
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

  // ── catalogRuntimeSlice ──
  catalog = createCatalogRuntimeSlice({
    getActiveLayers: () => activeLayers.value,
    getRunLayerGroups: () => bindings.getRunLayerGroups(),
    getJobLayers: () => bindings.getJobLayers(),
    onCatalogLoaded: () => bindings.onCatalogLoaded(),
  })
  const {
    runtimeLayerCatalog,
    runtimeLayerCatalogLoading,
    layerCategories,
    reloadLayerCategories,
    layerLibrary,
    layerLibraryMap,
    catalogJobStatus,
    catalogRunReadiness,
    ensureRuntimeLayerCatalog,
    resolveBackendLayerId,
    resolveEffectiveDescriptor,
    supportsAnalysisWorkflow,
    getCatalogRunBlockReason,
    getCatalogAddBlockReason,
    canRunCatalog,
    isWeatherEngineLayer,
    supportsMapLayerResult,
    supportsViewportDrivenRefresh,
    supportsParticleFlow,
    supportsOnlineTemporal,
    getOnlineTemporalConfig,
    getLayerPrimaryMetric,
    getCatalogWorkflowEngine,
    getRuntimeLayerDescriptor,
    isOverlayDisplayOnlyLayer,
    setRuntimeLayerCatalog,
  } = catalog

  function setCurrentHour(hour: number) {
    currentHour.value = hour
  }

  return {
    currentHour,
    activeWorkflowCatalogIds,
    submittingCatalogIds,
    isSubmitting,
    workflowRetryTimers,
    workflowRetryCounts,
    isLocalSubmitJobId,
    setCurrentHour,
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
    addDrawDraftLayer,
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
    runtimeLayerCatalog,
    runtimeLayerCatalogLoading,
    layerCategories,
    reloadLayerCategories,
    layerLibrary,
    layerLibraryMap,
    catalogJobStatus,
    catalogRunReadiness,
    ensureRuntimeLayerCatalog,
    resolveBackendLayerId,
    resolveEffectiveDescriptor,
    supportsAnalysisWorkflow,
    getCatalogRunBlockReason,
    getCatalogAddBlockReason,
    canRunCatalog,
    isWeatherEngineLayer,
    supportsMapLayerResult,
    supportsViewportDrivenRefresh,
    supportsParticleFlow,
    supportsOnlineTemporal,
    getOnlineTemporalConfig,
    getLayerPrimaryMetric,
    getCatalogWorkflowEngine,
    getRuntimeLayerDescriptor,
    isOverlayDisplayOnlyLayer,
    setRuntimeLayerCatalog,
  }
}

export type WorkspaceDomain = ReturnType<typeof createWorkspaceDomain>
