import type { WatchStopHandle } from 'vue'

import { createWeatherOverlayFacade, type WeatherOverlayFacade } from './weather-overlay-facade'
import {
  createWeatherOverlayResolver,
  type WeatherOverlayResolver,
} from './weather-overlay-resolver'
import { watchWeatherOverlayInputs } from './weather-overlay-watcher'
import type { WindDisplayMode } from './wind-display-mode'

type MapInstance = import('maplibre-gl').Map
type DebugLogger = (module: string, ...args: unknown[]) => void
type WeatherOverlayGeojsonData =
  import('./weather-overlay-registry').WeatherOverlayState['geojsonData']
type ActiveLayerDisplay = import('../../stores/layers/types').ActiveLayerDisplay
type WeatherLayerRenderHint = import('../../services/runtime-api').WeatherLayerRenderHint

interface WeatherOverlayModuleDependencies {
  createResolver?: (options: {
    getActiveLayers: () => ActiveLayerDisplay[]
    isWeatherEngineLayer: (catalogId: string) => boolean
    getMergedGeojsonForViewport: (catalogId: string) => WeatherOverlayGeojsonData
    getViewportBounds?: (
      catalogId: string,
    ) => import('./weather-overlay-registry').WeatherOverlayState['viewportBounds']
    buildDefaultWeatherRenderHint: (catalogId: string) => WeatherLayerRenderHint | null
    resolveApiUrl: (url: string) => string
    debugLog: DebugLogger
  }) => WeatherOverlayResolver
  createFacade?: (options: {
    map: MapInstance
    getMapReady: () => boolean
    resolver: WeatherOverlayResolver
    getEnabledParticleFlowCatalogId: () => string | null
    getWindDisplayMode?: () => WindDisplayMode
    debugLog: DebugLogger
    debounceMs?: number
  }) => WeatherOverlayFacade
  watchInputs?: typeof watchWeatherOverlayInputs
}

interface CreateWeatherOverlayModuleOptions {
  map: MapInstance
  getMapReady: () => boolean
  getActiveLayers: () => ActiveLayerDisplay[]
  isWeatherEngineLayer: (catalogId: string) => boolean
  getMergedGeojsonForViewport: (catalogId: string) => WeatherOverlayGeojsonData
  getViewportBounds?: (
    catalogId: string,
  ) => import('./weather-overlay-registry').WeatherOverlayState['viewportBounds']
  buildDefaultWeatherRenderHint: (catalogId: string) => WeatherLayerRenderHint | null
  resolveApiUrl: (url: string) => string
  getEnabledParticleFlowCatalogId: () => string | null
  getWindDisplayMode?: () => WindDisplayMode
  getSmoothRendering?: () => boolean
  getDataVersion: () => number
  getCurrentHour: () => number
  debugLog: DebugLogger
  debounceMs?: number
  dependencies?: WeatherOverlayModuleDependencies
}

export interface WeatherOverlayModule {
  setupWatchers: () => void
  scheduleSync: () => void
  runSyncNow: () => void
  dispose: () => void
}

export function createWeatherOverlayModule(
  options: CreateWeatherOverlayModuleOptions,
): WeatherOverlayModule {
  const createResolverImpl = options.dependencies?.createResolver ?? createWeatherOverlayResolver
  const createFacadeImpl = options.dependencies?.createFacade ?? createWeatherOverlayFacade
  const watchInputsImpl = options.dependencies?.watchInputs ?? watchWeatherOverlayInputs

  const resolver = createResolverImpl({
    getActiveLayers: options.getActiveLayers,
    isWeatherEngineLayer: options.isWeatherEngineLayer,
    getMergedGeojsonForViewport: options.getMergedGeojsonForViewport,
    getViewportBounds: options.getViewportBounds,
    buildDefaultWeatherRenderHint: options.buildDefaultWeatherRenderHint,
    resolveApiUrl: options.resolveApiUrl,
    debugLog: options.debugLog,
  })

  const facade = createFacadeImpl({
    map: options.map,
    getMapReady: options.getMapReady,
    resolver,
    getEnabledParticleFlowCatalogId: options.getEnabledParticleFlowCatalogId,
    getWindDisplayMode: options.getWindDisplayMode,
    getSmoothRendering: options.getSmoothRendering,
    debugLog: options.debugLog,
    debounceMs: options.debounceMs,
  })

  let stopWeatherWatcher: WatchStopHandle | null = null

  return {
    setupWatchers() {
      if (stopWeatherWatcher) return
      stopWeatherWatcher = watchInputsImpl({
        getActiveLayers: options.getActiveLayers,
        getParticleFlowCatalogId: options.getEnabledParticleFlowCatalogId,
        getWindDisplayMode: options.getWindDisplayMode,
        getSmoothRendering: options.getSmoothRendering,
        getDataVersion: options.getDataVersion,
        getCurrentHour: options.getCurrentHour,
        scheduleSync: facade.scheduleSync,
        debugLog: options.debugLog,
      })
    },
    scheduleSync() {
      facade.scheduleSync()
    },
    runSyncNow() {
      facade.runSyncNow()
    },
    dispose() {
      stopWeatherWatcher?.()
      stopWeatherWatcher = null
      facade.dispose()
    },
  }
}
