import type { ActiveLayerDisplay } from '../../stores/layers/types'

export interface WeatherOverlayWatchInputs {
  layersHash: string
  particleFlowCatalogId: string | null
  dataVersion: number
  currentHour: number
}

export function buildWeatherOverlayWatchInputs(
  activeLayers: ActiveLayerDisplay[],
  particleFlowCatalogId: string | null,
  dataVersion: number,
  currentHour: number,
): WeatherOverlayWatchInputs {
  return {
    layersHash: JSON.stringify(
      activeLayers.map((layer) => ({
        id: layer.instanceId,
        catalogId: layer.catalogId,
        visible: layer.visible,
        opacity: layer.opacity,
        isAdmin: layer.isAdminBoundary,
        jobUpdatedAt: layer.jobLayer?.updatedAt,
        paintMode: layer.jobLayer?.mapLayerPayload?.renderHint?.paint_mode,
        geojsonUrl: layer.jobLayer?.mapLayerPayload?.layerAssets?.geojsonUrl,
        cogPreviewUrl: layer.jobLayer?.mapLayerPayload?.layerAssets?.cogPreviewUrl,
      })),
    ),
    particleFlowCatalogId,
    dataVersion,
    currentHour,
  }
}

export interface WeatherOverlayWatchDiff {
  flowIdChanged: boolean
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
    layersHashChanged: next.layersHash !== previous?.layersHash,
    dataVersionChanged: next.dataVersion !== previous?.dataVersion,
    hourChanged: next.currentHour !== previous?.currentHour,
  }
}
