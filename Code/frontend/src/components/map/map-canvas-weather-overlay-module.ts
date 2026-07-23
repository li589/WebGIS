import { resolveApiUrl } from '../../services/runtime-api'
import { buildDefaultWeatherRenderHint } from './weather-render'
import { createWeatherOverlayModule, type WeatherOverlayModule } from './weather-overlay-module'

type MapInstance = import('maplibre-gl').Map
type DebugLogger = (module: string, ...args: unknown[]) => void
type ActiveLayerDisplay = import('../../stores/layers/types').ActiveLayerDisplay
type WeatherOverlayGeojsonData =
  import('./weather-overlay-registry').WeatherOverlayState['geojsonData']

interface MapCanvasLayersStoreLike {
  activeLayersDisplay: ActiveLayerDisplay[]
  particleFlowCatalogId: string | null
  windDisplayMode: import('./wind-display-mode').WindDisplayMode
  smoothRendering: boolean
  isWeatherEngineLayer: (catalogId: string) => boolean
}

interface MapCanvasWeatherTileManagerLike {
  getMergedGeojsonForViewport: (catalogId: string) => WeatherOverlayGeojsonData
  getViewportBounds: (
    catalogId: string,
  ) => import('./weather-overlay-registry').WeatherOverlayState['viewportBounds']
  dataVersion: number
}

interface CreateMapCanvasWeatherOverlayModuleOptions {
  map: MapInstance
  getMapReady: () => boolean
  layersStore: MapCanvasLayersStoreLike
  weatherTileManager: MapCanvasWeatherTileManagerLike
  getCurrentHour: () => number
  debugLog: DebugLogger
  debounceMs?: number
  dependencies?: {
    createWeatherOverlayModule?: typeof createWeatherOverlayModule
  }
}

export function createMapCanvasWeatherOverlayModule(
  options: CreateMapCanvasWeatherOverlayModuleOptions,
): WeatherOverlayModule {
  const createWeatherOverlayModuleImpl =
    options.dependencies?.createWeatherOverlayModule ?? createWeatherOverlayModule

  return createWeatherOverlayModuleImpl({
    map: options.map,
    getMapReady: options.getMapReady,
    getActiveLayers: () => options.layersStore.activeLayersDisplay,
    isWeatherEngineLayer: options.layersStore.isWeatherEngineLayer,
    getMergedGeojsonForViewport: options.weatherTileManager.getMergedGeojsonForViewport,
    getViewportBounds: options.weatherTileManager.getViewportBounds,
    buildDefaultWeatherRenderHint,
    resolveApiUrl,
    getEnabledParticleFlowCatalogId: () => options.layersStore.particleFlowCatalogId,
    getWindDisplayMode: () => options.layersStore.windDisplayMode,
    getSmoothRendering: () => options.layersStore.smoothRendering,
    getDataVersion: () => options.weatherTileManager.dataVersion,
    getCurrentHour: options.getCurrentHour,
    debugLog: options.debugLog,
    debounceMs: options.debounceMs,
  })
}
