/**
 * D2: Viewport domain — weather viewport (wind display, map state, debounce)
 * + weather reconcile (provider preference, tile viewport activation).
 *
 * Extracted from the original god store ``index.ts``. Owns:
 * - ``weatherViewportSlice``: particle flow, wind display mode, map center/zoom/bbox,
 *   viewport debounce, smooth rendering toggle.
 * - ``weatherReconcileSlice``: weather provider preference, active weather layer
 *   reconciliation, tile viewport activation.
 *
 * Cross-domain dependencies are resolved lazily via the ``CrossDomainBindings``
 * object (populated by ``index.ts`` after all domains are created).
 */
import { useWeatherTileManager } from '../weather-tile-manager'
import { debugLog as probeDebugLog } from '../../utils/perf-probe'
import { createWeatherViewportSlice } from './weather-viewport'
import { createWeatherReconcileSlice, type WeatherReconcileSlice } from './weather-reconcile'
import type { CrossDomainBindings } from './bindings'

function debugLog(module: string, ...args: unknown[]) {
  probeDebugLog(`[${performance.now().toFixed(1)}ms] [LayersStore:${module}]`, ...args)
}

export function createViewportDomain(
  bindings: CrossDomainBindings,
  deps: {
    getCurrentHour: () => number
    getActiveLayers: () => import('./types').ActiveLayer[]
    isLocalImport: (layer: import('./types').ActiveLayer) => boolean
    isWeatherEngineLayer: (catalogId: string) => boolean
    supportsViewportDrivenRefresh: (catalogId: string) => boolean
    supportsParticleFlow: (catalogId: string) => boolean
  },
) {
  const weatherTileManager = useWeatherTileManager()

  // ── Late-bound intra-domain weatherReconcile (circular: viewport ↔ reconcile) ──
  // eslint-disable-next-line prefer-const
  let weatherReconcile!: WeatherReconcileSlice

  // ── weatherViewportSlice ──
  const weatherViewport = createWeatherViewportSlice({
    getActiveLayers: () => deps.getActiveLayers(),
    isWeatherEngineLayer: (catalogId) => deps.isWeatherEngineLayer(catalogId),
    supportsViewportDrivenRefresh: (catalogId) => deps.supportsViewportDrivenRefresh(catalogId),
    getCurrentHour: () => deps.getCurrentHour(),
    weatherProviderArg: (catalogId) => weatherReconcile.weatherProviderArg(catalogId),
    setWeatherTileViewport: (catalogId, center, zoom, hour, model, bbox, provider) => {
      weatherTileManager.setViewport(catalogId, center, zoom, hour, model, bbox, provider)
    },
    onWorkflowViewportRefresh: (epoch) => {
      bindings.onWorkflowViewportRefresh(epoch)
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

  // ── weatherReconcileSlice ──
  weatherReconcile = createWeatherReconcileSlice({
    getActiveLayers: () => deps.getActiveLayers(),
    isLocalImport: deps.isLocalImport,
    isWeatherEngineLayer: (catalogId) => deps.isWeatherEngineLayer(catalogId),
    supportsParticleFlow: (catalogId) => deps.supportsParticleFlow(catalogId),
    enableParticleIfUnset: (catalogId) => enableParticleIfUnset(catalogId),
    getMapCenter: () => currentMapCenter.value,
    getMapZoom: () => currentMapZoom.value,
    getMapBBox: () => currentMapBBox.value,
    getCurrentHour: () => deps.getCurrentHour(),
    getLastPointWeatherQuery: () => bindings.getLastPointWeatherQuery(),
    fetchPointWeather: (lng, lat, catalogId) => bindings.fetchPointWeather(lng, lat, catalogId),
    clearPointWeather: () => bindings.clearPointWeather(),
    hasPointWeather: () => bindings.hasPointWeather(),
  })
  const { applyWeatherProviderPreference, activateWeatherTileViewport } = weatherReconcile

  // ── Populate bindings: viewport → other domains ──
  bindings.getMapCenter = () => currentMapCenter.value
  bindings.getMapZoom = () => currentMapZoom.value
  bindings.getMapBBox = () => currentMapBBox.value
  bindings.getParticleFlowCatalogId = () => particleFlowCatalogId.value
  bindings.enableParticleIfUnset = (catalogId) => enableParticleIfUnset(catalogId)
  bindings.clearWindForCatalog = (catalogId) => clearWindForCatalog(catalogId)
  bindings.weatherProviderArg = (catalogId) => weatherReconcile.weatherProviderArg(catalogId)
  bindings.weatherProviderQuery = (catalogId) => weatherReconcile.weatherProviderQuery(catalogId)
  bindings.onCatalogLoaded = () => weatherReconcile.reconcileActiveWeatherLayers()
  bindings.isViewportRefreshStale = (epoch) => isViewportRefreshStale(epoch)
  bindings.getViewportRefreshEpoch = () => getViewportRefreshEpoch()
  bindings.activateWeatherTileViewport = (catalogId) => activateWeatherTileViewport(catalogId)

  return {
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
    applyWeatherProviderPreference,
    activateWeatherTileViewport,
  }
}

export type ViewportDomain = ReturnType<typeof createViewportDomain>
