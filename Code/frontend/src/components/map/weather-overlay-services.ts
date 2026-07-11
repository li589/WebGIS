import type { WeatherOverlayRenderContext, WeatherOverlayState } from './weather-overlay-registry'
import {
  syncWeatherCogOverlay as syncWeatherCogOverlayRenderer,
  syncWeatherGridFillOverlay as syncWeatherGridFillOverlayRenderer,
  syncWeatherHeatmapOverlay as syncWeatherHeatmapOverlayRenderer,
  syncWeatherPointOverlay as syncWeatherPointOverlayRenderer,
} from './weather-overlay-renderers'
import { WindParticleOverlayController } from './wind-particle-overlay-controller'

type MapInstance = import('maplibre-gl').Map

interface CreateWeatherOverlayServicesOptions {
  map: MapInstance
  windParticleController: WindParticleOverlayController | null
  getSyncWeatherToken: () => number
  getEnabledParticleFlowCatalogId: () => string | null
}

export interface WeatherOverlayServices {
  syncWeatherCogOverlay: WeatherOverlayRenderContext['syncWeatherCogOverlay']
  syncWeatherGridFillOverlay: WeatherOverlayRenderContext['syncWeatherGridFillOverlay']
  syncWeatherHeatmapOverlay: WeatherOverlayRenderContext['syncWeatherHeatmapOverlay']
  syncWeatherPointOverlay: WeatherOverlayRenderContext['syncWeatherPointOverlay']
  syncWindParticleFlow: WeatherOverlayRenderContext['syncWindParticleFlow']
}

export function createWeatherOverlayServices(
  options: CreateWeatherOverlayServicesOptions,
): WeatherOverlayServices {
  return {
    syncWeatherCogOverlay(overlayState: WeatherOverlayState) {
      syncWeatherCogOverlayRenderer(options.map, overlayState)
    },
    syncWeatherGridFillOverlay(overlayState: WeatherOverlayState) {
      syncWeatherGridFillOverlayRenderer(options.map, overlayState)
    },
    syncWeatherHeatmapOverlay(overlayState: WeatherOverlayState) {
      syncWeatherHeatmapOverlayRenderer(options.map, overlayState)
    },
    syncWeatherPointOverlay(overlayState: WeatherOverlayState) {
      syncWeatherPointOverlayRenderer(options.map, overlayState)
    },
    async syncWindParticleFlow(overlayState: WeatherOverlayState, overlayToken: number) {
      if (!options.windParticleController) return
      await options.windParticleController.sync(overlayState, {
        overlayToken,
        getSyncWeatherToken: options.getSyncWeatherToken,
        getEnabledParticleFlowCatalogId: options.getEnabledParticleFlowCatalogId,
      })
    },
  }
}
