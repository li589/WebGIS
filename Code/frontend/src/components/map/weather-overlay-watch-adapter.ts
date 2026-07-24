import type { ActiveLayerDisplay } from '../../stores/layers/types'
import type { WindDisplayMode } from './wind-display-mode'

export interface WeatherOverlayWatchInputs {
  layersHash: string
  particleFlowCatalogId: string | null
  windDisplayMode: WindDisplayMode
  dataVersion: number
  currentHour: number
  /** 平滑渲染开关：变化须触发 sync，否则 WebGL/MapLibre 切换会卡住 */
  smoothRendering: boolean
}

export function buildWeatherOverlayWatchInputs(
  activeLayers: ActiveLayerDisplay[],
  particleFlowCatalogId: string | null,
  dataVersion: number,
  currentHour: number,
  windDisplayMode: WindDisplayMode = 'off',
  smoothRendering: boolean = true,
): WeatherOverlayWatchInputs {
  return {
    layersHash: JSON.stringify(
      activeLayers.map((layer) => ({
        id: layer.instanceId,
        catalogId: layer.catalogId,
        visible: layer.visible,
        opacity: layer.opacity,
        isAdmin: layer.isAdminBoundary,
      })),
    ),
    particleFlowCatalogId,
    windDisplayMode,
    dataVersion,
    currentHour,
    smoothRendering,
  }
}

export interface WeatherOverlayWatchDiff {
  flowIdChanged: boolean
  windDisplayModeChanged: boolean
  layersHashChanged: boolean
  dataVersionChanged: boolean
  hourChanged: boolean
  smoothRenderingChanged: boolean
}

export function diffWeatherOverlayWatchInputs(
  next: WeatherOverlayWatchInputs,
  previous?: WeatherOverlayWatchInputs,
): WeatherOverlayWatchDiff {
  return {
    flowIdChanged: next.particleFlowCatalogId !== previous?.particleFlowCatalogId,
    windDisplayModeChanged: next.windDisplayMode !== previous?.windDisplayMode,
    layersHashChanged: next.layersHash !== previous?.layersHash,
    dataVersionChanged: next.dataVersion !== previous?.dataVersion,
    hourChanged: next.currentHour !== previous?.currentHour,
    smoothRenderingChanged: next.smoothRendering !== previous?.smoothRendering,
  }
}
