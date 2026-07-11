type MapInstance = import('maplibre-gl').Map

export interface WeatherOverlayIds {
  sourceId: string
  fillLayerId: string
  lineLayerId: string
  pointLayerId: string
  arrowLayerId: string
  heatmapLayerId: string
  heatmapPointLayerId: string
  imageSourceId: string
  rasterLayerId: string
}

export function buildWeatherOverlayIds(catalogId: string): WeatherOverlayIds {
  return {
    sourceId: `weather-src-${catalogId}`,
    fillLayerId: `weather-fill-${catalogId}`,
    lineLayerId: `weather-line-${catalogId}`,
    pointLayerId: `weather-point-${catalogId}`,
    arrowLayerId: `weather-arrow-${catalogId}`,
    heatmapLayerId: `weather-heatmap-${catalogId}`,
    heatmapPointLayerId: `weather-heatmap-point-${catalogId}`,
    imageSourceId: `weather-img-src-${catalogId}`,
    rasterLayerId: `weather-raster-${catalogId}`,
  }
}

export function getWeatherOverlayBeforeLayerId(map: MapInstance) {
  return map.getLayer('admin-fill') ? 'admin-fill' : undefined
}

export function removeWeatherMapArtifacts(
  map: MapInstance,
  catalogId: string,
  options?: {
    preserveGeoJsonSource?: boolean
    preserveImageSource?: boolean
  },
) {
  const ids = buildWeatherOverlayIds(catalogId)

  if (map.getLayer(ids.rasterLayerId)) map.removeLayer(ids.rasterLayerId)
  if (!options?.preserveImageSource && map.getSource(ids.imageSourceId)) {
    map.removeSource(ids.imageSourceId)
  }
  if (map.getLayer(ids.heatmapPointLayerId)) map.removeLayer(ids.heatmapPointLayerId)
  if (map.getLayer(ids.heatmapLayerId)) map.removeLayer(ids.heatmapLayerId)
  if (map.getLayer(ids.arrowLayerId)) map.removeLayer(ids.arrowLayerId)
  if (map.getLayer(ids.pointLayerId)) map.removeLayer(ids.pointLayerId)
  if (map.getLayer(ids.lineLayerId)) map.removeLayer(ids.lineLayerId)
  if (map.getLayer(ids.fillLayerId)) map.removeLayer(ids.fillLayerId)
  if (!options?.preserveGeoJsonSource && map.getSource(ids.sourceId)) {
    map.removeSource(ids.sourceId)
  }
}
