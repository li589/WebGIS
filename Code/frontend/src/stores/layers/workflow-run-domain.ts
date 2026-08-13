/**
 * D2: Workflow-run domain — job/run layer lifecycle, point weather, polling,
 * workflow runner, and workspace hydration.
 *
 * Extracted from the original god store ``index.ts``. Owns:
 * - ``runLayersSlice``: job layers, run groups, workflow error/summary/progress.
 * - ``pointWeatherSlice``: single-point weather query state.
 * - ``workflowPoller``: event polling + snapshot sync.
 * - ``workflowRunner``: submit/cancel/retry + restore orchestration.
 * - ``workspaceHydrateSlice``: snapshot hydration + persist binding.
 * - ``refreshActiveWeatherWorkflows``: viewport-triggered workflow refresh.
 *
 * Created after workspace and viewport domains; receives their state/actions
 * as deps. Reverse-direction cross-domain calls go through ``CrossDomainBindings``.
 */
import { debugLog as probeDebugLog } from '../../utils/perf-probe'
import { createRunLayersSlice } from './run-layers'
import { createPointWeatherSlice } from './point-weather'
import { createWorkflowPoller } from './workflow-poller'
import { createWorkflowRunner } from './workflow-runner'
import { buildJobLayer } from './result-adapter'
import { createWorkspaceHydrateSlice } from './workspace-hydrate'
import { isRunDismissed } from './workspace-persist'
import type { CrossDomainBindings } from './bindings'
import type { WorkspaceDomain } from './workspace-domain'
import type { ViewportDomain } from './viewport-domain'
import type { ActiveLayer, LayerSidebarView } from './types'

function debugLog(module: string, ...args: unknown[]) {
  probeDebugLog(`[${performance.now().toFixed(1)}ms] [LayersStore:${module}]`, ...args)
}

export function createWorkflowRunDomain(
  bindings: CrossDomainBindings,
  workspace: WorkspaceDomain,
  viewport: ViewportDomain,
) {
  // ── runLayersSlice ──
  const runLayersSlice = createRunLayersSlice({
    getActiveLayers: () => workspace.activeLayers.value,
    addLayer: (catalogId, isAdminBoundary, jobLayer) =>
      workspace.addLayer(catalogId, isAdminBoundary, jobLayer),
    removeLayer: (instanceId) => workspace.removeLayer(instanceId),
    assignLayerAccent: (preferred) => workspace.assignLayerAccent(preferred),
    setSelectedInstanceId: (id) => {
      workspace.selectedInstanceId.value = id
    },
    getSidebarView: () => workspace.sidebarView.value,
    setSidebarView: (view: LayerSidebarView) => workspace.setSidebarView(view),
    getMapCenter: () => bindings.getMapCenter(),
    getCurrentHour: () => workspace.currentHour.value,
    forgetTrackedWorkflowRun: (runId) => bindings.forgetTrackedWorkflowRun(runId),
    rememberTrackedWorkflowRun: (catalogId, jobLayer) =>
      bindings.rememberTrackedWorkflowRun(catalogId, jobLayer),
    isLocalSubmitJobId: workspace.isLocalSubmitJobId,
    scheduleWorkspacePersist: () => bindings.scheduleWorkspacePersist(),
    genInstanceId: workspace.genInstanceId,
    addImportedRasterLayer: workspace.addImportedRasterLayer,
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

  // ── pointWeatherSlice ──
  const pointWeatherSlice = createPointWeatherSlice({
    getCurrentHour: () => workspace.currentHour.value,
    isWeatherEngineLayer: (catalogId) => workspace.isWeatherEngineLayer(catalogId),
    weatherProviderQuery: (catalogId) => bindings.weatherProviderQuery(catalogId),
  })
  const {
    pointWeather,
    pointWeatherLoading,
    pointWeatherError,
    lastPointWeatherQuery,
    clearPointWeather,
    fetchPointWeather,
  } = pointWeatherSlice

  // ── workflowPoller ──
  const workflowPoller = createWorkflowPoller({
    getJobLayer: (jobId) => jobLayers.value.find((item) => item.jobId === jobId),
    isViewportRefreshStale: (epoch) => viewport.isViewportRefreshStale(epoch),
    isRunDismissed: (runId) => isRunDismissed(runId),
    getParticleFlowCatalogId: () => viewport.particleFlowCatalogId.value,
    supportsParticleFlow: (catalogId) => workspace.supportsParticleFlow(catalogId),
    upsertJobLayer: (catalogId, jobLayer) => upsertJobLayer(catalogId, jobLayer),
    setWorkflowError: (msg) => {
      workflowError.value = msg
    },
    removeActiveCatalog: (catalogId) => workspace.activeWorkflowCatalogIds.delete(catalogId),
    syncProgressiveBlockOverlays: (runId, catalogId) =>
      void syncProgressiveBlockOverlays(runId, catalogId),
    emitWorkflowProgressTimeSeek: (jobLayer, status, detail) =>
      emitWorkflowProgressTimeSeek(jobLayer, status, detail),
    attachAlgorithmProductOverlays: (refs, catalogId, runId) =>
      attachAlgorithmProductOverlays(refs as never, catalogId, runId),
    clearWindForCatalog: (catalogId) => viewport.clearWindForCatalog(catalogId),
    enableParticleIfUnset: (catalogId) => viewport.enableParticleIfUnset(catalogId),
    buildJobLayer: (run, catalogId, opts) => buildJobLayer(run as never, catalogId, opts),
  })
  const { stopWorkflowPolling } = workflowPoller

  // ── workspaceHydrateSlice ──
  const workspaceHydrate = createWorkspaceHydrateSlice({
    getActiveLayers: () => workspace.activeLayers.value,
    getRunLayerGroups: () => runLayerGroups.value,
    getSidebarView: () => workspace.sidebarView.value,
    setSidebarView: (view) => workspace.setSidebarView(view),
    getLayerLibraryMap: () => workspace.layerLibraryMap.value,
    assignLayerAccent: (preferred) => workspace.assignLayerAccent(preferred),
    genInstanceId: workspace.genInstanceId,
    isLocalImport: workspace.isLocalImport,
    isWeatherEngineLayer: (catalogId) => workspace.isWeatherEngineLayer(catalogId),
    weatherProviderArg: (catalogId) => bindings.weatherProviderArg(catalogId),
    getMapCenter: () => bindings.getMapCenter(),
    getMapZoom: () => bindings.getMapZoom(),
    getMapBBox: () => bindings.getMapBBox(),
    getCurrentHour: () => workspace.currentHour.value,
    bindPersistFns: (fns) => {
      bindings.scheduleWorkspacePersist = fns.scheduleWorkspacePersist
      bindings.flushWorkspacePersistNow = fns.flushWorkspacePersistNow
    },
  })
  const { hydrateWorkspaceFromSnapshot, hydrateVectorLayersFromSnapshot } = workspaceHydrate

  // ── refreshActiveWeatherWorkflows (cross-domain orchestration) ──
  async function refreshActiveWeatherWorkflows(expectedViewportEpoch?: number) {
    const epoch = expectedViewportEpoch ?? viewport.getViewportRefreshEpoch()
    const activeMapLayers = workspace.activeLayers.value.filter(
      (layer: ActiveLayer) =>
        layer.visible &&
        workspace.supportsViewportDrivenRefresh(layer.catalogId) &&
        !workspace.isWeatherEngineLayer(layer.catalogId) &&
        layer.jobLayer,
    )
    debugLog(
      'refreshActive',
      'layers',
      activeMapLayers.map((l) => l.catalogId),
      'bbox',
      viewport.currentMapBBox.value,
      'epoch',
      epoch,
    )

    for (const layer of activeMapLayers) {
      if (viewport.isViewportRefreshStale(epoch)) {
        debugLog(
          'refreshActive',
          'abort stale epoch',
          epoch,
          'current',
          viewport.getViewportRefreshEpoch(),
        )
        return
      }
      if (!workspace.canRunCatalog(layer.catalogId)) continue
      try {
        await runWorkflowForCatalog(layer.catalogId, { expectedViewportEpoch: epoch })
      } catch (error) {
        console.warn(`[LayersStore] Failed to refresh map workflow for ${layer.catalogId}:`, error)
      }
    }
  }

  // ── workflowRunner (must be after poller + hydrate) ──
  const workflowRunner = createWorkflowRunner({
    startPolling: (jobId, catalogId, epoch) => workflowPoller.startPolling(jobId, catalogId, epoch),
    stopWorkflowPolling: (jobId) => workflowPoller.stopWorkflowPolling(jobId),
    isPolling: (jobId) => workflowPoller.isPolling(jobId),
    syncWorkflowRunSnapshot: (jobId, catalogId, force, epoch) =>
      workflowPoller.syncWorkflowRunSnapshot(jobId, catalogId, force, epoch),
    applyWorkflowEventsToJobLayer: (jobLayer, events) =>
      workflowPoller.applyWorkflowEventsToJobLayer(jobLayer, events),
    getActiveLayers: () => workspace.activeLayers.value,
    getJobLayers: () => jobLayers.value,
    getRunLayerGroups: () => runLayerGroups.value,
    getRuntimeLayerCatalog: () => workspace.runtimeLayerCatalog.value,
    getLayerLibrary: () => workspace.layerLibrary.value,
    getMapBBox: () => viewport.currentMapBBox.value,
    activeWorkflowCatalogIds: workspace.activeWorkflowCatalogIds,
    submittingCatalogIds: workspace.submittingCatalogIds,
    workflowRetryTimers: workspace.workflowRetryTimers,
    workflowRetryCounts: workspace.workflowRetryCounts,
    setRunLayerGroups: (groups) => {
      runLayerGroups.value = groups
    },
    upsertJobLayer: (catalogId, jobLayer) => upsertJobLayer(catalogId, jobLayer),
    removeJobLayerById: (jobId) => removeJobLayerById(jobId),
    setWorkflowError: (msg) => {
      workflowError.value = msg
    },
    scheduleWorkspacePersist: () => bindings.scheduleWorkspacePersist(),
    cleanupUnproducedRunLayers: (runId) => cleanupUnproducedRunLayers(runId),
    createRunLayerGroup: (options) => createRunLayerGroup(options),
    bindRunIdToGroup: (groupId, runId) => bindRunIdToGroup(groupId, runId),
    attachAlgorithmProductOverlays: (refs, catalogId, runId, opts) =>
      attachAlgorithmProductOverlays(refs as never, catalogId, runId, opts),
    isLocalSubmitJobId: (jobId) => workspace.isLocalSubmitJobId(jobId),
    isViewportRefreshStale: (epoch) => viewport.isViewportRefreshStale(epoch),
    isWeatherEngineLayer: (catalogId) => workspace.isWeatherEngineLayer(catalogId),
    resolveBackendLayerId: (catalogId) => workspace.resolveBackendLayerId(catalogId),
    ensureRuntimeLayerCatalog: (force) => workspace.ensureRuntimeLayerCatalog(force),
    getCatalogRunBlockReason: (catalogId) => workspace.getCatalogRunBlockReason(catalogId),
    supportsAnalysisWorkflow: (catalogId) => workspace.supportsAnalysisWorkflow(catalogId),
    supportsMapLayerResult: (catalogId) => workspace.supportsMapLayerResult(catalogId),
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
    activateWeatherTileViewport: (catalogId) => viewport.activateWeatherTileViewport(catalogId),
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
    cleanupAllRetryTimers,
    rememberTrackedWorkflowRun: rememberTrackedWorkflowRunImpl,
    forgetTrackedWorkflowRun: forgetTrackedWorkflowRunImpl,
  } = workflowRunner

  // ── Populate bindings: workflow-run → other domains ──
  bindings.getRunLayerGroups = () => runLayerGroups.value
  bindings.setRunLayerGroups = (groups) => {
    runLayerGroups.value = groups
  }
  bindings.getJobLayers = () => jobLayers.value
  bindings.stopWorkflowPolling = (jobId) => stopWorkflowPolling(jobId)
  bindings.forgetTrackedWorkflowRun = (runId) => forgetTrackedWorkflowRunImpl(runId)
  bindings.rememberTrackedWorkflowRun = (catalogId, jobLayer) =>
    rememberTrackedWorkflowRunImpl(catalogId, jobLayer)
  bindings.getLastPointWeatherQuery = () => lastPointWeatherQuery.value
  bindings.fetchPointWeather = (lng, lat, catalogId) => fetchPointWeather(lng, lat, catalogId)
  bindings.clearPointWeather = () => clearPointWeather()
  bindings.hasPointWeather = () => Boolean(pointWeather.value)
  bindings.onWorkflowViewportRefresh = (epoch) => void refreshActiveWeatherWorkflows(epoch)

  return {
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
    pointWeather,
    pointWeatherLoading,
    pointWeatherError,
    lastPointWeatherQuery,
    clearPointWeather,
    fetchPointWeather,
    stopWorkflowPolling,
    restoreActiveWorkflows,
    registerExternalWorkflowRun,
    runWorkflowForCatalog,
    cancelWorkflowRunForJob,
    retryWorkflowRunForJob,
    cleanupAllRetryTimers,
    rememberTrackedWorkflowRun: rememberTrackedWorkflowRunImpl,
    forgetTrackedWorkflowRun: forgetTrackedWorkflowRunImpl,
    hydrateWorkspaceFromSnapshot,
    hydrateVectorLayersFromSnapshot,
    refreshActiveWeatherWorkflows,
  }
}

export type WorkflowRunDomain = ReturnType<typeof createWorkflowRunDomain>
