/**
 * D2: Domain selector composables.
 *
 * Provide narrower APIs over ``useLayersStore()`` so consumers can depend on
 * only the domain they need, reducing implicit coupling.
 *
 * Reactive state (State + Computed) is returned as Refs / ComputedRefs via
 * ``storeToRefs`` — destructuring in consumers preserves reactivity.
 * Actions are returned as plain function references (no reactivity needed).
 *
 * Usage:
 * ```ts
 * import { useLayerWorkspace } from '@/stores/layers/selectors'
 * const workspace = useLayerWorkspace()
 * const { activeLayers, activeLayerCount } = workspace  // Refs
 * workspace.addLayer('catalog-id')                       // action
 * ```
 */
import { storeToRefs } from 'pinia'
import { useLayersStore } from './index'

/** Workspace domain: layer CRUD, catalog, shared state. */
export function useLayerWorkspace() {
  const store = useLayersStore()
  const {
    // State (as Refs)
    activeLayers,
    sidebarView,
    selectedInstanceId,
    currentHour,
    isSubmitting,
    runtimeLayerCatalogLoading,
    // Computed (as ComputedRefs)
    activeLayersDisplay,
    selectedLayerDisplay,
    activeLayerCount,
    sidebarViewLabel,
    catalogJobStatus,
    catalogRunReadiness,
    // Data (as Refs)
    layerLibrary,
  } = storeToRefs(store)

  return {
    // Reactive state (Refs / ComputedRefs)
    activeLayers,
    sidebarView,
    selectedInstanceId,
    currentHour,
    isSubmitting,
    runtimeLayerCatalogLoading,
    activeLayersDisplay,
    selectedLayerDisplay,
    activeLayerCount,
    sidebarViewLabel,
    catalogJobStatus,
    catalogRunReadiness,
    layerLibrary,
    // Non-reactive static data
    layerCategories: store.layerCategories,
    // Actions
    addLayer: store.addLayer,
    addImportedVectorLayer: store.addImportedVectorLayer,
    addImportedRasterLayer: store.addImportedRasterLayer,
    getImportedVectorGeojson: store.getImportedVectorGeojson,
    updateImportedVectorGeojson: store.updateImportedVectorGeojson,
    setImportedVectorStyle: store.setImportedVectorStyle,
    removeLayer: store.removeLayer,
    toggleLayerVisibility: store.toggleLayerVisibility,
    setAllLayerVisibility: store.setAllLayerVisibility,
    removeAllLayers: store.removeAllLayers,
    setLayerOpacity: store.setLayerOpacity,
    setLayerPaletteOverride: store.setLayerPaletteOverride,
    setLayerRangeOverride: store.setLayerRangeOverride,
    setLayerNodataDisplay: store.setLayerNodataDisplay,
    setLayerOrder: store.setLayerOrder,
    setLayerDisplayName: store.setLayerDisplayName,
    bringLayerToFront: store.bringLayerToFront,
    sendLayerToBack: store.sendLayerToBack,
    selectLayer: store.selectLayer,
    setSidebarView: store.setSidebarView,
    setCurrentHour: store.setCurrentHour,
    ensureRuntimeLayerCatalog: store.ensureRuntimeLayerCatalog,
    getCatalogRunBlockReason: store.getCatalogRunBlockReason,
    canRunCatalog: store.canRunCatalog,
    supportsAnalysisWorkflow: store.supportsAnalysisWorkflow,
    isWeatherEngineLayer: store.isWeatherEngineLayer,
    supportsMapLayerResult: store.supportsMapLayerResult,
    supportsViewportDrivenRefresh: store.supportsViewportDrivenRefresh,
    supportsParticleFlow: store.supportsParticleFlow,
    supportsOnlineTemporal: store.supportsOnlineTemporal,
    getOnlineTemporalConfig: store.getOnlineTemporalConfig,
    getLayerPrimaryMetric: store.getLayerPrimaryMetric,
    resolveBackendLayerId: store.resolveBackendLayerId,
    resolveEffectiveDescriptor: store.resolveEffectiveDescriptor,
    scheduleWorkspacePersist: store.scheduleWorkspacePersist,
  }
}

/** Viewport domain: weather viewport, wind display, map state. */
export function useLayerViewport() {
  const store = useLayersStore()
  const {
    particleFlowCatalogId,
    windDisplayMode,
    currentMapCenter,
    currentMapBBox,
    currentMapZoom,
    smoothRendering,
  } = storeToRefs(store)

  return {
    // Reactive state (Refs)
    particleFlowCatalogId,
    windDisplayMode,
    currentMapCenter,
    currentMapBBox,
    currentMapZoom,
    smoothRendering,
    // Actions
    setWindDisplayMode: store.setWindDisplayMode,
    toggleParticleFlow: store.toggleParticleFlow,
    setParticleFlow: store.setParticleFlow,
    setSmoothRendering: store.setSmoothRendering,
    applyWeatherProviderPreference: store.applyWeatherProviderPreference,
    setMapViewport: store.setMapViewport,
    handleViewportChange: store.handleViewportChange,
    flushWeatherTileViewports: store.flushWeatherTileViewports,
  }
}

/** Workflow-run domain: job layers, polling, runner, point weather. */
export function useWorkflowRun() {
  const store = useLayersStore()
  const {
    runLayerGroups,
    jobLayers,
    workflowError,
    workflowProgressTimeSeek,
    workflowSummary,
    workflowVariantPreference,
    pointWeather,
    pointWeatherLoading,
    pointWeatherError,
  } = storeToRefs(store)

  return {
    // Reactive state (Refs)
    runLayerGroups,
    jobLayers,
    workflowError,
    workflowProgressTimeSeek,
    workflowSummary,
    workflowVariantPreference,
    pointWeather,
    pointWeatherLoading,
    pointWeatherError,
    // Actions
    setJobLayers: store.setJobLayers,
    reorderLayers: store.reorderLayers,
    createRunLayerGroup: store.createRunLayerGroup,
    bindRunIdToGroup: store.bindRunIdToGroup,
    dissolveRunGroup: store.dissolveRunGroup,
    reorderWithinRunGroup: store.reorderWithinRunGroup,
    moveRunGroupBlock: store.moveRunGroupBlock,
    findRunGroupByMember: store.findRunGroupByMember,
    findRunGroupById: store.findRunGroupById,
    refreshRunGroupDissolvable: store.refreshRunGroupDissolvable,
    updateRunGroupFromJob: store.updateRunGroupFromJob,
    runWorkflowForCatalog: store.runWorkflowForCatalog,
    getWorkflowVariantPreference: store.getWorkflowVariantPreference,
    setWorkflowVariantPreference: store.setWorkflowVariantPreference,
    cancelWorkflowRunForJob: store.cancelWorkflowRunForJob,
    retryWorkflowRunForJob: store.retryWorkflowRunForJob,
    cleanupAllRetryTimers: store.cleanupAllRetryTimers,
    stopWorkflowPolling: store.stopWorkflowPolling,
    fetchPointWeather: store.fetchPointWeather,
    clearPointWeather: store.clearPointWeather,
    refreshActiveWeatherWorkflows: store.refreshActiveWeatherWorkflows,
    cleanupUnproducedRunLayers: store.cleanupUnproducedRunLayers,
    registerExternalWorkflowRun: store.registerExternalWorkflowRun,
    restoreActiveWorkflows: store.restoreActiveWorkflows,
    setWorkspaceHydrationGuard: store.setWorkspaceHydrationGuard,
  }
}
