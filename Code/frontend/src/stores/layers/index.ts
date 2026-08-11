/**
 * D2: Layer store composition root.
 *
 * Previously a 556-line god store; now a thin wiring layer that creates three
 * domain modules and merges their public APIs for backward compatibility.
 *
 * Domain modules:
 * - ``workspace-domain.ts``: shared state + activeLayers + catalogRuntime
 * - ``viewport-domain.ts``: weatherViewport + weatherReconcile
 * - ``workflow-run-domain.ts``: runLayers + pointWeather + workflowPoller
 *   + workflowRunner + workspaceHydrate
 *
 * Cross-domain circular dependencies are resolved via ``CrossDomainBindings``
 * (a shared mutable object populated after all domains are created).
 *
 * Selector composables for narrower consumer APIs:
 * - ``useLayerWorkspace()`` — workspace domain only
 * - ``useLayerViewport()`` — viewport domain only
 * - ``useWorkflowRun()`` — workflow-run domain only
 * (see ``./selectors.ts``)
 */
import { watch } from 'vue'
import { defineStore } from 'pinia'

import { LAYER_CATEGORIES } from './catalog'
import { createCrossDomainBindings } from './bindings'
import { createWorkspaceDomain } from './workspace-domain'
import { createViewportDomain } from './viewport-domain'
import { createWorkflowRunDomain } from './workflow-run-domain'

export const useLayersStore = defineStore('layers', () => {
  // ── Cross-domain bindings (populated by domain modules) ──
  const bindings = createCrossDomainBindings()

  // ── 1. Workspace domain (shared state + activeLayers + catalog) ──
  const workspace = createWorkspaceDomain(bindings)

  // ── 2. Viewport domain (weatherViewport + weatherReconcile) ──
  // Created after workspace; populates viewport-side bindings.
  const viewport = createViewportDomain(bindings, {
    getCurrentHour: () => workspace.currentHour.value,
    getActiveLayers: () => workspace.activeLayers.value,
    isLocalImport: workspace.isLocalImport,
    isWeatherEngineLayer: (catalogId) => workspace.isWeatherEngineLayer(catalogId),
    supportsViewportDrivenRefresh: (catalogId) =>
      workspace.supportsViewportDrivenRefresh(catalogId),
    supportsParticleFlow: (catalogId) => workspace.supportsParticleFlow(catalogId),
  })

  // ── 3. Workflow-run domain (runLayers + pointWeather + poller + runner + hydrate) ──
  // Created after workspace + viewport; populates workflow-run-side bindings.
  const workflowRun = createWorkflowRunDomain(bindings, workspace, viewport)

  // ── Watch: currentHour → flush weather tile viewports ──
  // 小时变化是离散用户操作，需立即执行；取消挂起的视口防抖，避免用旧 hour 覆盖。
  watch(workspace.currentHour, (hour) => {
    viewport.flushWeatherTileViewports(hour)
  })

  // ── Backward-compatible flat return ──
  // All 84+ members from the three domains are exposed through the single
  // store. Consumers can migrate to selector composables (./selectors.ts)
  // for a narrower API.
  return {
    // ── State ──
    activeLayers: workspace.activeLayers,
    runLayerGroups: workflowRun.runLayerGroups,
    sidebarView: workspace.sidebarView,
    selectedInstanceId: workspace.selectedInstanceId,
    jobLayers: workflowRun.jobLayers,
    currentHour: workspace.currentHour,
    workflowError: workflowRun.workflowError,
    workflowProgressTimeSeek: workflowRun.workflowProgressTimeSeek,
    isSubmitting: workspace.isSubmitting,
    workflowSummary: workflowRun.workflowSummary,
    runtimeLayerCatalogLoading: workspace.runtimeLayerCatalogLoading,
    particleFlowCatalogId: viewport.particleFlowCatalogId,
    windDisplayMode: viewport.windDisplayMode,
    currentMapCenter: viewport.currentMapCenter,
    currentMapBBox: viewport.currentMapBBox,
    currentMapZoom: viewport.currentMapZoom,
    smoothRendering: viewport.smoothRendering,
    // ── Computed ──
    activeLayersDisplay: workspace.activeLayersDisplay,
    selectedLayerDisplay: workspace.selectedLayerDisplay,
    activeLayerCount: workspace.activeLayerCount,
    sidebarViewLabel: workspace.sidebarViewLabel,
    catalogJobStatus: workspace.catalogJobStatus,
    catalogRunReadiness: workspace.catalogRunReadiness,
    // ── Data ──
    layerLibrary: workspace.layerLibrary,
    layerCategories: LAYER_CATEGORIES,
    // ── Actions: workspace ──
    addLayer: workspace.addLayer,
    addImportedVectorLayer: workspace.addImportedVectorLayer,
    addImportedRasterLayer: workspace.addImportedRasterLayer,
    getImportedVectorGeojson: workspace.getImportedVectorGeojson,
    updateImportedVectorGeojson: workspace.updateImportedVectorGeojson,
    setImportedVectorStyle: workspace.setImportedVectorStyle,
    removeLayer: workspace.removeLayer,
    toggleLayerVisibility: workspace.toggleLayerVisibility,
    setAllLayerVisibility: workspace.setAllLayerVisibility,
    removeAllLayers: workspace.removeAllLayers,
    setLayerOpacity: workspace.setLayerOpacity,
    setLayerPaletteOverride: workspace.setLayerPaletteOverride,
    setLayerRangeOverride: workspace.setLayerRangeOverride,
    setLayerNodataDisplay: workspace.setLayerNodataDisplay,
    setLayerOrder: workspace.setLayerOrder,
    setLayerDisplayName: workspace.setLayerDisplayName,
    bringLayerToFront: workspace.bringLayerToFront,
    sendLayerToBack: workspace.sendLayerToBack,
    selectLayer: workspace.selectLayer,
    setSidebarView: workspace.setSidebarView,
    setCurrentHour: workspace.setCurrentHour,
    // ── Actions: catalog ──
    setJobLayers: workflowRun.setJobLayers,
    ensureRuntimeLayerCatalog: workspace.ensureRuntimeLayerCatalog,
    // ── Actions: run layers ──
    reorderLayers: workflowRun.reorderLayers,
    createRunLayerGroup: workflowRun.createRunLayerGroup,
    bindRunIdToGroup: workflowRun.bindRunIdToGroup,
    dissolveRunGroup: workflowRun.dissolveRunGroup,
    reorderWithinRunGroup: workflowRun.reorderWithinRunGroup,
    moveRunGroupBlock: workflowRun.moveRunGroupBlock,
    findRunGroupByMember: workflowRun.findRunGroupByMember,
    findRunGroupById: workflowRun.findRunGroupById,
    refreshRunGroupDissolvable: workflowRun.refreshRunGroupDissolvable,
    updateRunGroupFromJob: workflowRun.updateRunGroupFromJob,
    // ── Actions: workflow ──
    runWorkflowForCatalog: workflowRun.runWorkflowForCatalog,
    cancelWorkflowRunForJob: workflowRun.cancelWorkflowRunForJob,
    retryWorkflowRunForJob: workflowRun.retryWorkflowRunForJob,
    stopWorkflowPolling: workflowRun.stopWorkflowPolling,
    getCatalogRunBlockReason: workspace.getCatalogRunBlockReason,
    canRunCatalog: workspace.canRunCatalog,
    supportsAnalysisWorkflow: workspace.supportsAnalysisWorkflow,
    isWeatherEngineLayer: workspace.isWeatherEngineLayer,
    supportsMapLayerResult: workspace.supportsMapLayerResult,
    supportsViewportDrivenRefresh: workspace.supportsViewportDrivenRefresh,
    supportsParticleFlow: workspace.supportsParticleFlow,
    getLayerPrimaryMetric: workspace.getLayerPrimaryMetric,
    // ── Actions: viewport ──
    setWindDisplayMode: viewport.setWindDisplayMode,
    toggleParticleFlow: viewport.toggleParticleFlow,
    setParticleFlow: viewport.setParticleFlow,
    setSmoothRendering: viewport.setSmoothRendering,
    resolveBackendLayerId: workspace.resolveBackendLayerId,
    resolveEffectiveDescriptor: workspace.resolveEffectiveDescriptor,
    applyWeatherProviderPreference: viewport.applyWeatherProviderPreference,
    // ── Point weather ──
    pointWeather: workflowRun.pointWeather,
    pointWeatherLoading: workflowRun.pointWeatherLoading,
    pointWeatherError: workflowRun.pointWeatherError,
    fetchPointWeather: workflowRun.fetchPointWeather,
    clearPointWeather: workflowRun.clearPointWeather,
    // ── Map viewport ──
    setMapViewport: viewport.setMapViewport,
    handleViewportChange: viewport.handleViewportChange,
    flushWeatherTileViewports: viewport.flushWeatherTileViewports,
    // ── Workflow lifecycle ──
    refreshActiveWeatherWorkflows: workflowRun.refreshActiveWeatherWorkflows,
    cleanupUnproducedRunLayers: workflowRun.cleanupUnproducedRunLayers,
    scheduleWorkspacePersist: () => bindings.scheduleWorkspacePersist(),
    // ── External workflow tracking ──
    registerExternalWorkflowRun: workflowRun.registerExternalWorkflowRun,
    restoreActiveWorkflows: workflowRun.restoreActiveWorkflows,
  }
})
