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
 *
 * P2-13: Sub-module barrel export inventory (30 files).
 * Consumers should import from ``./selectors.ts`` or specific sub-modules
 * rather than reaching into the flat store return.
 *
 * ── Domain orchestrators ──
 * - ``workspace-domain.ts`` — activeLayers state, catalog runtime, layer CRUD
 * - ``viewport-domain.ts`` — weather viewport, particle flow, map bbox/zoom
 * - ``workflow-run-domain.ts`` — workflow submission, polling, run layer groups
 *
 * ── State & types ──
 * - ``types.ts`` — ActiveLayer, JobLayerItem, ActiveRunLayerGroup interfaces
 * - ``catalog.ts`` — LAYER_CATEGORIES, layer library type definitions
 * - ``bindings.ts`` — CrossDomainBindings shared mutable bridge
 *
 * ── Workspace ──
 * - ``active-layers.ts`` — addLayer/removeLayer/toggleVisibility/setLayerOrder
 * - ``catalog-runtime.ts`` — ensureRuntimeLayerCatalog, catalog readiness checks
 * - ``workspace-persist.ts`` — localStorage persistence for active layers
 * - ``workspace-hydrate.ts`` — restore workspace from snapshot on page reload
 * - ``layer-naming.ts`` — setLayerDisplayName, name validation
 * - ``layer-display-names.ts`` — display name resolution for catalog layers
 * - ``layer-accent.ts`` — accent color for selected layers
 * - ``imported-vector.ts`` — addImportedVectorLayer, GeoJSON management
 * - ``imported-raster.ts`` — addImportedRasterLayer, COG preview
 * - ``materialize-empty.ts`` — materialize empty layer placeholders
 *
 * ── Viewport ──
 * - ``weather-viewport.ts`` — weather tile viewport scheduling, epoch tracking
 * - ``weather-reconcile.ts`` — reconcile weather layers after viewport change
 * - ``weather-session.ts`` — weather session lifecycle management
 * - ``display-projection.ts`` — layer display projection / CRS resolution
 *
 * ── Workflow ──
 * - ``workflow-runner.ts`` — runWorkflowForCatalog, cancel, retry, 429 backoff
 * - ``workflow-poller.ts`` — startPolling/stopPolling, snapshot sync
 * - ``workflow-progress.ts`` — normalizeWorkflowProgress, progress display
 * - ``run-layers.ts`` — run layer group CRUD, dissolve, reorder
 * - ``result-adapter.ts`` — buildJobLayer from WorkflowRun response
 * - ``point-weather.ts`` — point weather query, loading/error state
 * - ``restore-workflow-bridge.ts`` — resolve workflow bridge for restoration
 * - ``catalog-builders.ts`` — getCatalogDisplayName, isTerminalStatus
 * - ``selectors.ts`` — useLayerWorkspace / useLayerViewport / useWorkflowRun
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
  /**
   * @deprecated 逐步迁移到 selector composables（`./selectors.ts`）。
   * 新代码请使用 useLayerWorkspace() / useLayerViewport() / useWorkflowRun()。
   * 响应式 state 通过 selector 返回的 Refs 访问。
   */
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
    addDrawDraftLayer: workspace.addDrawDraftLayer,
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
    workflowVariantPreference: workflowRun.workflowVariantPreference,
    getWorkflowVariantPreference: workflowRun.getWorkflowVariantPreference,
    setWorkflowVariantPreference: workflowRun.setWorkflowVariantPreference,
    cancelWorkflowRunForJob: workflowRun.cancelWorkflowRunForJob,
    retryWorkflowRunForJob: workflowRun.retryWorkflowRunForJob,
    cleanupAllRetryTimers: workflowRun.cleanupAllRetryTimers,
    stopWorkflowPolling: workflowRun.stopWorkflowPolling,
    getCatalogRunBlockReason: workspace.getCatalogRunBlockReason,
    canRunCatalog: workspace.canRunCatalog,
    supportsAnalysisWorkflow: workspace.supportsAnalysisWorkflow,
    isWeatherEngineLayer: workspace.isWeatherEngineLayer,
    supportsMapLayerResult: workspace.supportsMapLayerResult,
    supportsViewportDrivenRefresh: workspace.supportsViewportDrivenRefresh,
    supportsParticleFlow: workspace.supportsParticleFlow,
    supportsOnlineTemporal: workspace.supportsOnlineTemporal,
    getOnlineTemporalConfig: workspace.getOnlineTemporalConfig,
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
    setWorkspaceHydrationGuard: workflowRun.setWorkspaceHydrationGuard,
  }
})
