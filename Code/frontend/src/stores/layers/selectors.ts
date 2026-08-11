/**
 * D2: Domain selector composables.
 *
 * Provide narrower APIs over ``useLayersStore()`` so consumers can depend on
 * only the domain they need, reducing implicit coupling.
 *
 * Usage:
 * ```ts
 * import { useLayerWorkspace } from '@/stores/layers/selectors'
 * const workspace = useLayerWorkspace()
 * workspace.addLayer('catalog-id')
 * ```
 *
 * For reactive state, use ``storeToRefs`` on the store directly:
 * ```ts
 * const store = useLayersStore()
 * const { activeLayers } = storeToRefs(store)
 * ```
 */
import { useLayersStore } from './index'

/** Workspace domain: layer CRUD, catalog, shared state. */
export function useLayerWorkspace() {
  const store = useLayersStore()
  return {
    // State
    activeLayers: store.activeLayers,
    sidebarView: store.sidebarView,
    selectedInstanceId: store.selectedInstanceId,
    currentHour: store.currentHour,
    isSubmitting: store.isSubmitting,
    runtimeLayerCatalogLoading: store.runtimeLayerCatalogLoading,
    // Computed
    activeLayersDisplay: store.activeLayersDisplay,
    selectedLayerDisplay: store.selectedLayerDisplay,
    activeLayerCount: store.activeLayerCount,
    sidebarViewLabel: store.sidebarViewLabel,
    catalogJobStatus: store.catalogJobStatus,
    catalogRunReadiness: store.catalogRunReadiness,
    // Data
    layerLibrary: store.layerLibrary,
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
    getLayerPrimaryMetric: store.getLayerPrimaryMetric,
    resolveBackendLayerId: store.resolveBackendLayerId,
    resolveEffectiveDescriptor: store.resolveEffectiveDescriptor,
    scheduleWorkspacePersist: store.scheduleWorkspacePersist,
  }
}

/** Viewport domain: weather viewport, wind display, map state. */
export function useLayerViewport() {
  const store = useLayersStore()
  return {
    // State
    particleFlowCatalogId: store.particleFlowCatalogId,
    windDisplayMode: store.windDisplayMode,
    currentMapCenter: store.currentMapCenter,
    currentMapBBox: store.currentMapBBox,
    currentMapZoom: store.currentMapZoom,
    smoothRendering: store.smoothRendering,
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
  return {
    // State
    runLayerGroups: store.runLayerGroups,
    jobLayers: store.jobLayers,
    workflowError: store.workflowError,
    workflowProgressTimeSeek: store.workflowProgressTimeSeek,
    workflowSummary: store.workflowSummary,
    // Point weather
    pointWeather: store.pointWeather,
    pointWeatherLoading: store.pointWeatherLoading,
    pointWeatherError: store.pointWeatherError,
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
    cancelWorkflowRunForJob: store.cancelWorkflowRunForJob,
    retryWorkflowRunForJob: store.retryWorkflowRunForJob,
    stopWorkflowPolling: store.stopWorkflowPolling,
    fetchPointWeather: store.fetchPointWeather,
    clearPointWeather: store.clearPointWeather,
    refreshActiveWeatherWorkflows: store.refreshActiveWeatherWorkflows,
    cleanupUnproducedRunLayers: store.cleanupUnproducedRunLayers,
    registerExternalWorkflowRun: store.registerExternalWorkflowRun,
    restoreActiveWorkflows: store.restoreActiveWorkflows,
  }
}
