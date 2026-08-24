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

import type { FeatureCollection } from 'geojson'
import { useDrawStore, type DrawFeature } from '../draw-store'
import { LAYER_CATEGORIES } from './catalog'
import { createCrossDomainBindings } from './bindings'
import { createWorkspaceDomain } from './workspace-domain'
import { createViewportDomain } from './viewport-domain'
import { createWorkflowRunDomain } from './workflow-run-domain'
import { createLifecycleDomain } from './lifecycle-domain'

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

  // ── 4. Lifecycle domain（图层平台子系统 P0）──
  // 聚合「资产 + 工作流 + 时间轴」为统一生命周期视图；在 workflow-run 之后创建，
  // 读取 jobLayers 与 overlayTimeStates（MapCanvas 双写过渡期经 bindings 注入）。
  const lifecycle = createLifecycleDomain({
    bindings,
    getJobLayers: () => workflowRun.jobLayers.value,
  })
  // 图层添加后刷新 lifecycle（后端真源；失败静默走本地推导）
  watch(
    () => workspace.activeLayers.value.length,
    () => {
      const ids = workspace.activeLayers.value
        .filter((l) => !l.importedRaster && !l.importedVector && !l.isAdminBoundary)
        .map((l) => l.catalogId)
      if (ids.length > 0) void lifecycle.refreshAll(ids)
    },
  )

  // ── Watch: currentHour → flush weather tile viewports ──
  // 小时变化是离散用户操作，需立即执行；取消挂起的视口防抖，避免用旧 hour 覆盖。
  watch(workspace.currentHour, (hour) => {
    viewport.flushWeatherTileViewports(hour)
  })

  // ── Watch: draw features → sync importedVector（O4 绘制图层元数据实时读）──
  // 绘制要素原本只存在 draw-store（工具条/属性表正确），但 ActiveLayer.importedVector
  // 停留在创建时的空 GeoJSON（featureCount=0 / geometryType undefined）→
  // 元数据 Tab 显示 Unknown/0 要素。此处把 draw-store 要素单向同步回 importedVector
  // （updateImportedVectorGeojson 会重推 featureCount/geometryType/bounds/revision），
  // 元数据/导出/属性表全部自动恢复正确。
  const drawStore = useDrawStore()
  watch(
    () => [drawStore.features, drawStore.editingLayerId, drawStore.draftLayerId] as const,
    ([feats, editingId, draftId]) => {
      const targetId = editingId ?? draftId
      if (!targetId) return
      const geojson: FeatureCollection = {
        type: 'FeatureCollection',
        features: (feats as DrawFeature[]).map((f, i) => ({
          type: 'Feature' as const,
          id: i + 1,
          geometry: f.geometry,
          properties: f.properties ?? {},
        })),
      }
      workspace.updateImportedVectorGeojson(targetId, geojson)
    },
    { deep: true },
  )

  // ── Flat return（P3 收口后的定位，2026-08-23）──
  // 本 return 不再是公共 API——已降级为 **selectors 的底座**：
  // 1. selectors.ts 的 toRef(store, key) / store.xxx 经由此面取成员；
  // 2. 整店传递白名单（MapCanvas / LayerSidebar 侧栏三件套，见
  //    eslint no-restricted-imports 配置）仍需完整实例——窄接口专项收口对象；
  // 3. 外部直连已被 eslint 禁令阻止（pattern: layers store 入口），
  //    新消费方一律经 useLayerWorkspace/useLayerViewport/useWorkflowRun。
  // 成员面与 selectors 依赖面保持一致（收窄无收益且破坏底座契约）。
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
    // ── Computed: lifecycle（图层平台子系统 P0）──
    layerLifecycle: lifecycle.layerLifecycle,
    // ── Data ──
    layerLibrary: workspace.layerLibrary,
    layerCategories: LAYER_CATEGORIES,
    // ── Actions: lifecycle（图层平台子系统 P0）──
    refreshLayerLifecycle: lifecycle.refreshLayerLifecycle,
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
    autoAttachProductsForNewLayer: workflowRun.autoAttachProductsForNewLayer,
    cleanupAllRetryTimers: workflowRun.cleanupAllRetryTimers,
    stopWorkflowPolling: workflowRun.stopWorkflowPolling,
    getCatalogRunBlockReason: workspace.getCatalogRunBlockReason,
    getCatalogAddBlockReason: workspace.getCatalogAddBlockReason,
    isOverlayDisplayOnlyLayer: workspace.isOverlayDisplayOnlyLayer,
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
