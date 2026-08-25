import type { WeatherOverlayRenderContext, WeatherOverlayState } from './weather-overlay-registry'
import {
  syncWeatherCogOverlay as syncWeatherCogOverlayRenderer,
  syncWeatherGridFillOverlay as syncWeatherGridFillOverlayRenderer,
  syncWeatherPointOverlay as syncWeatherPointOverlayRenderer,
} from './weather-overlay-renderers'
import { buildWeatherOverlayIds } from './weather-overlay-maplibre'
import type { WindParticleControllerContract } from './wind-particle-controller-contract'
import type { ScalarFieldWebGLController } from './scalar-field-webgl-controller'
import type { WindDisplayMode } from './wind-display-mode'
import { shouldYieldScalarWebGLToWind } from './weather-overlay-compositing'

type MapInstance = import('maplibre-gl').Map

interface CreateWeatherOverlayServicesOptions {
  map: MapInstance
  windParticleController: WindParticleControllerContract | null
  scalarFieldController: ScalarFieldWebGLController | null
  getSyncWeatherToken: () => number
  getEnabledParticleFlowCatalogId: () => string | null
  getWindDisplayMode?: () => WindDisplayMode
  getSmoothRendering?: () => boolean
}

export interface WeatherOverlayServices {
  syncWeatherCogOverlay: WeatherOverlayRenderContext['syncWeatherCogOverlay']
  syncWeatherGridFillOverlay: WeatherOverlayRenderContext['syncWeatherGridFillOverlay']
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
      // 防双层叠加（2026-08-25 用户反馈：降水量移动时色块颜色深度变化）：
      // 每次视口刷新 grid fill renderer 会无条件把 fill 设为 visible——若
      // 标量 WebGL 平滑面已隐藏 fill，这个窗口期 fill+WebGL 双层半透明
      // 叠加 → 色深闪烁。平滑模式下 fill 已隐藏时保持隐藏；WebGL 让位/
      // 失败路径（removeCatalogArtifacts）会删除 fill，下一轮 grid sync
      // 重建并正常显示（回退链不受影响）。
      const ids = buildWeatherOverlayIds(overlayState.catalogId)
      const fillLayer = options.map.getLayer(ids.fillLayerId) as
        | { layout?: { visibility?: string } }
        | undefined
      const fillWasHiddenByWebGL = fillLayer?.layout?.visibility === 'none'
      syncWeatherGridFillOverlayRenderer(options.map, overlayState)
      const smoothActive = options.getSmoothRendering?.() ?? true
      if (smoothActive && fillWasHiddenByWebGL) {
        const restored = options.map.getLayer(ids.fillLayerId)
        if (restored) {
          options.map.setLayoutProperty(ids.fillLayerId, 'visibility', 'none')
        }
      }
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
        getSmoothRendering: options.getSmoothRendering,
        syncSmoothScalarUnderlay: (state) => {
          if (!options.scalarFieldController) return false
          if (!(options.getSmoothRendering?.() ?? true)) return false
          return options.scalarFieldController.sync(state, {
            overlayToken,
            getSyncWeatherToken: options.getSyncWeatherToken,
          })
        },
        clearSmoothScalarUnderlay: (catalogId) => {
          options.scalarFieldController?.removeCatalogArtifacts(catalogId)
        },
      })
    },
    syncScalarFieldWebGL(overlayState: WeatherOverlayState, overlayToken: number) {
      if (!options.scalarFieldController) return false
      // 用户关闭平滑渲染：拆掉 WebGL 连续面，回退 MapLibre 网格色块
      if (!(options.getSmoothRendering?.() ?? true)) {
        options.scalarFieldController.removeCatalogArtifacts(overlayState.catalogId)
        return false
      }
      const windMode = options.getWindDisplayMode?.() ?? 'particle'
      if (
        shouldYieldScalarWebGLToWind({
          enabledParticleFlowCatalogId: options.getEnabledParticleFlowCatalogId(),
          windDisplayMode: windMode,
          smoothRendering: options.getSmoothRendering?.() ?? true,
        })
      ) {
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
