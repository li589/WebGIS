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
import { toRef } from 'vue'
// storeToRefs（pinia 3.0.4 + vue 3.5.38）在遍历 store 时对 undefined 属性
// 访问 .effect 不防御会抛 TypeError；改用 toRef 逐字段包裹（2026-08-22）。
import { useLayersStore } from './index'

/** Workspace domain: layer CRUD, catalog, shared state. */
export function useLayerWorkspace() {
  const store = useLayersStore()
  // 逐字段 toRef 包裹（替代 storeToRefs）：见文件头注释
  const activeLayers = toRef(store, 'activeLayers')
  const sidebarView = toRef(store, 'sidebarView')
  const selectedInstanceId = toRef(store, 'selectedInstanceId')
  const currentHour = toRef(store, 'currentHour')
  const isSubmitting = toRef(store, 'isSubmitting')
  const runtimeLayerCatalogLoading = toRef(store, 'runtimeLayerCatalogLoading')
  const activeLayersDisplay = toRef(store, 'activeLayersDisplay')
  const selectedLayerDisplay = toRef(store, 'selectedLayerDisplay')
  const activeLayerCount = toRef(store, 'activeLayerCount')
  const sidebarViewLabel = toRef(store, 'sidebarViewLabel')
  const catalogJobStatus = toRef(store, 'catalogJobStatus')
  const catalogRunReadiness = toRef(store, 'catalogRunReadiness')
  const layerLibrary = toRef(store, 'layerLibrary')

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
    // 图层平台 P1：运行时分组（种子⊕管理），toRef 保持分组改名/重排后实时生效
    layerCategories: toRef(store, 'layerCategories'),
    // Actions
    addLayer: store.addLayer,
    addImportedVectorLayer: store.addImportedVectorLayer,
    addImportedRasterLayer: store.addImportedRasterLayer,
    addDrawDraftLayer: store.addDrawDraftLayer,
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
    reloadLayerCategories: store.reloadLayerCategories,
    getCatalogRunBlockReason: store.getCatalogRunBlockReason,
    getCatalogAddBlockReason: store.getCatalogAddBlockReason,
    isOverlayDisplayOnlyLayer: store.isOverlayDisplayOnlyLayer,
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
  const particleFlowCatalogId = toRef(store, 'particleFlowCatalogId')
  const windDisplayMode = toRef(store, 'windDisplayMode')
  const currentMapCenter = toRef(store, 'currentMapCenter')
  const currentMapBBox = toRef(store, 'currentMapBBox')
  const currentMapZoom = toRef(store, 'currentMapZoom')
  const smoothRendering = toRef(store, 'smoothRendering')

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
  // 逐字段 toRef 包裹（替代 storeToRefs）：见文件头注释
  const runLayerGroups = toRef(store, 'runLayerGroups')
  const jobLayers = toRef(store, 'jobLayers')
  const workflowError = toRef(store, 'workflowError')
  const workflowProgressTimeSeek = toRef(store, 'workflowProgressTimeSeek')
  const workflowSummary = toRef(store, 'workflowSummary')
  const workflowVariantPreference = toRef(store, 'workflowVariantPreference')
  const pointWeather = toRef(store, 'pointWeather')
  const pointWeatherLoading = toRef(store, 'pointWeatherLoading')
  const pointWeatherError = toRef(store, 'pointWeatherError')

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
    isWorkflowVariantPinned: store.isWorkflowVariantPinned,
    clearWorkflowVariantPin: store.clearWorkflowVariantPin,
    cancelWorkflowRunForJob: store.cancelWorkflowRunForJob,
    retryWorkflowRunForJob: store.retryWorkflowRunForJob,
    autoAttachProductsForNewLayer: store.autoAttachProductsForNewLayer,
    hasReusableProductsForTime: store.hasReusableProductsForTime,
    interruptWorkflowForCatalog: store.interruptWorkflowForCatalog,
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

/**
 * 图层平台子系统 P0：图层生命周期 selector。
 *
 * 返回 layerId → LayerLifecycleEntry 的响应式 Map（fresh/stale/updating/missing/failed），
 * 时间轴与图层卡片统一从此处读取生命周期状态，不再自行拼接
 * jobLayer / overlayTimeStates / 资产状态。
 */
export function useLayerLifecycle() {
  const store = useLayersStore()
  const layerLifecycle = toRef(store, 'layerLifecycle')

  return {
    layerLifecycle,
    refreshLayerLifecycle: store.refreshLayerLifecycle,
    /** 便捷读取：单图层生命周期条目（无数据时返回 null）。 */
    getLifecycle: (layerId: string) => layerLifecycle.value.get(layerId) ?? null,
  }
}
