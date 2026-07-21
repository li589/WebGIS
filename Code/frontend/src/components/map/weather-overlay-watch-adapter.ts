import type { ActiveLayerDisplay } from '../../stores/layers/types'
import type { WindDisplayMode } from './wind-display-mode'

export interface WeatherOverlayWatchInputs {
  layersHash: string
  particleFlowCatalogId: string | null
  windDisplayMode: WindDisplayMode
  dataVersion: number
  currentHour: number
}

export function buildWeatherOverlayWatchInputs(
  activeLayers: ActiveLayerDisplay[],
  particleFlowCatalogId: string | null,
  dataVersion: number,
  currentHour: number,
  windDisplayMode: WindDisplayMode = 'off',
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
  }
}

export interface WeatherOverlayWatchDiff {
  flowIdChanged: boolean
  windDisplayModeChanged: boolean
  layersHashChanged: boolean
  dataVersionChanged: boolean
  hourChanged: boolean
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
  }
}
