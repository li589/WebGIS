import type { WeatherOverlayRenderContext, WeatherOverlayState } from './weather-overlay-registry'
import {
  syncWeatherCogOverlay as syncWeatherCogOverlayRenderer,
  syncWeatherGridFillOverlay as syncWeatherGridFillOverlayRenderer,
  syncWeatherHeatmapOverlay as syncWeatherHeatmapOverlayRenderer,
  syncWeatherPointOverlay as syncWeatherPointOverlayRenderer,
} from './weather-overlay-renderers'
import type { WindParticleControllerContract } from './wind-particle-controller-contract'
import type { ScalarFieldWebGLController } from './scalar-field-webgl-controller'
import type { WindDisplayMode } from './wind-display-mode'

type MapInstance = import('maplibre-gl').Map

interface CreateWeatherOverlayServicesOptions {
  map: MapInstance
  windParticleController: WindParticleControllerContract | null
  scalarFieldController: ScalarFieldWebGLController | null
  getSyncWeatherToken: () => number
  getEnabledParticleFlowCatalogId: () => string | null
  getWindDisplayMode?: () => WindDisplayMode
}

export interface WeatherOverlayServices {
  syncWeatherCogOverlay: WeatherOverlayRenderContext['syncWeatherCogOverlay']
  syncWeatherGridFillOverlay: WeatherOverlayRenderContext['syncWeatherGridFillOverlay']
  syncWeatherHeatmapOverlay: WeatherOverlayRenderContext['syncWeatherHeatmapOverlay']
  syncWeatherPointOverlay: WeatherOverlayRenderContext['syncWeatherPointOverlay']
  syncWindParticleFlow: WeatherOverlayRenderContext['syncWindParticleFlow']
  syncScalarFieldWebGL: WeatherOverlayRenderContext['syncScalarFieldWebGL']
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
        getWindDisplayMode: options.getWindDisplayMode,
      })
    },
    syncScalarFieldWebGL(overlayState: WeatherOverlayState, overlayToken: number) {
      if (!options.scalarFieldController) return false
      // 风场动画（粒子/流线）激活时标量回退 MapLibre fill；关闭态仅色底不占用 WebGL
      const windMode = options.getWindDisplayMode?.() ?? 'particle'
      if (options.getEnabledParticleFlowCatalogId() && windMode !== 'off') {
        options.scalarFieldController.removeCatalogArtifacts(overlayState.catalogId)
        return false
      }
      return options.scalarFieldController.sync(overlayState, {
        overlayToken,
        getSyncWeatherToken: options.getSyncWeatherToken,
      })
    },
  }
}
