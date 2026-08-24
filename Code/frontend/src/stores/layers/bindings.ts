/**
 * D2: Cross-domain bindings — late-bound function references shared across
 * the three layer store domains (workspace / viewport / workflow-run).
 *
 * The three domains have circular dependencies (workspace ↔ viewport ↔
 * workflow-run). To avoid initialization-order issues, each domain receives
 * this bindings object whose function properties start as no-op stubs and
 * are populated by ``index.ts`` after all domains are created.
 *
 * This replaces the previous pattern of scattered ``let`` variables in the
 * god store's setup function.
 */
import type { ActiveRunLayerGroup, JobLayerItem } from './types'
import type { BoundingBox } from '../../services/runtime-api'

export interface CrossDomainBindings {
  // ── workspace → viewport ──
  getMapCenter: () => { lng: number; lat: number }
  getMapZoom: () => number
  getMapBBox: () => BoundingBox | null
  getParticleFlowCatalogId: () => string | null
  enableParticleIfUnset: (catalogId: string) => void
  clearWindForCatalog: (catalogId: string) => void

  // ── workspace → viewport (weatherReconcile) ──
  weatherProviderArg: (catalogId: string) => string
  /** weatherReconcile.weatherProviderQuery — used by pointWeatherSlice (workflow-run). */
  weatherProviderQuery: (catalogId: string) => string | undefined

  // ── workspace / viewport → workflow-run ──
  getRunLayerGroups: () => ActiveRunLayerGroup[]
  setRunLayerGroups: (groups: ActiveRunLayerGroup[]) => void
  getJobLayers: () => JobLayerItem[]
  stopWorkflowPolling: (jobId: string) => void
  cancelWorkflowRunForJob: (jobId: string, catalogId: string) => Promise<unknown>
  forgetTrackedWorkflowRun: (runId: string) => void
  rememberTrackedWorkflowRun: (catalogId: string, jobLayer: JobLayerItem) => void
  scheduleWorkspacePersist: () => void
  flushWorkspacePersistNow: () => void

  // ── viewport → workflow-run (point weather) ──
  getLastPointWeatherQuery: () => { lng: number; lat: number; catalogId: string } | null
  fetchPointWeather: (lng: number, lat: number, catalogId: string) => void
  clearPointWeather: () => void
  hasPointWeather: () => boolean

  // ── workflow-run → viewport ──
  isViewportRefreshStale: (epoch: number) => boolean
  getViewportRefreshEpoch: () => number
  activateWeatherTileViewport: (catalogId: string) => void

  // ── catalog → viewport (onCatalogLoaded) ──
  onCatalogLoaded: () => void

  // ── viewport → workflow-run (refreshActiveWeatherWorkflows) ──
  onWorkflowViewportRefresh: (epoch: number) => void

  // ── workspace → workflow-run (auto-run on layer add) ──
  runWorkflowForCatalog: (catalogId: string) => Promise<void>

  // ── lifecycle 域（图层平台子系统 P0）：地图 overlay 时间状态回传 ──
  /** MapCanvas 双写过渡：overlay-image-module 的 overlayTimeStates 透传（无地图时返回空数组）。 */
  getOverlayTimeStates: () => Array<{
    layerId: string
    category: string
    timeList: string[]
    currentTime: string | null
  }>
  /** lifecycle 域→workflow-run：刷新某图层 lifecycle 后触发资产工作流（可选）。 */
  onLifecycleRefreshed: (layerId: string, lifecycleState: string) => void
}

/**
 * Create a bindings object with no-op stubs. Populated by ``index.ts``
 * after all three domains are created.
 */
export function createCrossDomainBindings(): CrossDomainBindings {
  return {
    getMapCenter: () => ({ lng: 0, lat: 0 }),
    getMapZoom: () => 0,
    getMapBBox: () => null,
    getParticleFlowCatalogId: () => null,
    enableParticleIfUnset: () => {},
    clearWindForCatalog: () => {},
    weatherProviderArg: () => '',
    weatherProviderQuery: () => undefined,
    getRunLayerGroups: () => [],
    setRunLayerGroups: () => {},
    getJobLayers: () => [],
    stopWorkflowPolling: () => {},
    cancelWorkflowRunForJob: () => Promise.resolve(),
    forgetTrackedWorkflowRun: () => {},
    rememberTrackedWorkflowRun: () => {},
    scheduleWorkspacePersist: () => {},
    flushWorkspacePersistNow: () => {},
    getLastPointWeatherQuery: () => null,
    fetchPointWeather: () => {},
    clearPointWeather: () => {},
    hasPointWeather: () => false,
    isViewportRefreshStale: () => false,
    getViewportRefreshEpoch: () => 0,
    activateWeatherTileViewport: () => {},
    onCatalogLoaded: () => {},
    onWorkflowViewportRefresh: () => {},
    runWorkflowForCatalog: () => Promise.resolve(),
    getOverlayTimeStates: () => [],
    onLifecycleRefreshed: () => {},
  }
}
