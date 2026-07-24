import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import type { ActiveLayerDisplay } from '../../stores/layers/types'
import { resolveWeatherOverlayStates } from './weather-overlay-coordinator'

type DebugLogger = (module: string, ...args: unknown[]) => void
type WeatherOverlayGeojsonData =
  import('./weather-overlay-registry').WeatherOverlayState['geojsonData']
type WeatherOverlayState = import('./weather-overlay-registry').WeatherOverlayState

interface CreateWeatherOverlayResolverOptions {
  getActiveLayers: () => ActiveLayerDisplay[]
  isWeatherEngineLayer: (catalogId: string) => boolean
  getMergedGeojsonForViewport: (catalogId: string) => WeatherOverlayGeojsonData
  getViewportBounds?: (catalogId: string) => WeatherOverlayState['viewportBounds']
  buildDefaultWeatherRenderHint: (catalogId: string) => WeatherLayerRenderHint | null
  resolveApiUrl: (url: string) => string
  debugLog: DebugLogger
}

export interface WeatherOverlayResolver {
  resolveStates: () => WeatherOverlayState[]
}

export function createWeatherOverlayResolver(
  options: CreateWeatherOverlayResolverOptions,
): WeatherOverlayResolver {
  return {
    resolveStates() {
      return resolveWeatherOverlayStates({
        activeLayers: options.getActiveLayers(),
        isWeatherEngineLayer: options.isWeatherEngineLayer,
        getMergedGeojsonForViewport: options.getMergedGeojsonForViewport,
        getViewportBounds: options.getViewportBounds,
        buildDefaultWeatherRenderHint: options.buildDefaultWeatherRenderHint,
        resolveApiUrl: options.resolveApiUrl,
        debugLog: options.debugLog,
      })
    },
  }
}
