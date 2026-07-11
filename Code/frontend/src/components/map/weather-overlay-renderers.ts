import {
  buildWeatherArrowSizeExpression,
  buildWeatherFillColorExpression,
  buildWeatherHeatmapColorExpression,
  buildWeatherHeatmapWeightExpression,
  buildWeatherPointColorExpression,
  buildWeatherPointRadiusExpression,
  getWeatherFillOpacity,
  getWeatherLineColor,
  getWeatherLineOpacity,
} from './weather-render'
import { buildWeatherOverlayIds, getWeatherOverlayBeforeLayerId, removeWeatherMapArtifacts } from './weather-overlay-maplibre'
import type { WeatherOverlayState } from './weather-overlay-registry'

type MapInstance = import('maplibre-gl').Map
type GeoJsonSourceSpecification = import('maplibre-gl').GeoJSONSourceSpecification
type GeoJSONSource = import('maplibre-gl').GeoJSONSource
type ImageSourceSpecification = import('maplibre-gl').ImageSourceSpecification
type ImageSource = import('maplibre-gl').ImageSource

export function syncWeatherCogOverlay(map: MapInstance, overlayState: WeatherOverlayState) {
  if (!overlayState.cogPreviewUrl || !overlayState.cogBbox) return

  const ids = buildWeatherOverlayIds(overlayState.catalogId)
  removeWeatherMapArtifacts(map, overlayState.catalogId, { preserveImageSource: true })

  const ticks = overlayState.renderHint.legend_ticks.filter(
    (tick: number | string): tick is number => typeof tick === 'number',
  )
  const minValue = ticks[0] ?? 0
  const maxValue = ticks[ticks.length - 1] ?? (minValue + 1)
  const previewUrl = `${overlayState.cogPreviewUrl}?palette=${encodeURIComponent(overlayState.renderHint.palette)}&min_value=${minValue}&max_value=${maxValue}&width=768&height=768`
  const coordinates = [
    [overlayState.cogBbox.west, overlayState.cogBbox.north],
    [overlayState.cogBbox.east, overlayState.cogBbox.north],
    [overlayState.cogBbox.east, overlayState.cogBbox.south],
    [overlayState.cogBbox.west, overlayState.cogBbox.south],
  ] as [[number, number], [number, number], [number, number], [number, number]]

  const existingImageSource = map.getSource(ids.imageSourceId) as ImageSource | undefined
  const rasterOpacity = getWeatherFillOpacity(overlayState.renderHint, overlayState.opacity)

  if (!existingImageSource) {
    map.addSource(ids.imageSourceId, {
      type: 'image',
      url: previewUrl,
      coordinates,
    } as ImageSourceSpecification)

    map.addLayer(
      {
        id: ids.rasterLayerId,
        type: 'raster',
        source: ids.imageSourceId,
        paint: {
          'raster-opacity': rasterOpacity,
          'raster-fade-duration': 0,
        },
      },
      getWeatherOverlayBeforeLayerId(map),
    )
    return
  }

  existingImageSource.updateImage({
    url: previewUrl,
    coordinates,
  })
  if (map.getLayer(ids.rasterLayerId)) {
    map.setPaintProperty(ids.rasterLayerId, 'raster-opacity', rasterOpacity)
    map.setLayoutProperty(ids.rasterLayerId, 'visibility', 'visible')
  }
}

export function syncWeatherGridFillOverlay(map: MapInstance, overlayState: WeatherOverlayState) {
  const geojsonSource = overlayState.geojsonData ?? overlayState.geojsonUrl
  if (!geojsonSource) return

  const ids = buildWeatherOverlayIds(overlayState.catalogId)
  removeWeatherMapArtifacts(map, overlayState.catalogId, { preserveGeoJsonSource: true })

  const existingSource = map.getSource(ids.sourceId) as GeoJSONSource | undefined
  const fillOpacity = getWeatherFillOpacity(overlayState.renderHint, overlayState.opacity)
  const lineOpacity = getWeatherLineOpacity(overlayState.renderHint, overlayState.opacity)
  const fillColor = buildWeatherFillColorExpression(overlayState.renderHint)
  const lineColor = getWeatherLineColor(overlayState.renderHint)

  if (!existingSource) {
    map.addSource(ids.sourceId, {
      type: 'geojson',
      data: geojsonSource,
    } as GeoJsonSourceSpecification)

    map.addLayer(
      {
        id: ids.fillLayerId,
        type: 'fill',
        source: ids.sourceId,
        paint: {
          'fill-color': fillColor,
          'fill-opacity': fillOpacity,
        },
      },
      getWeatherOverlayBeforeLayerId(map),
    )

    map.addLayer(
      {
        id: ids.lineLayerId,
        type: 'line',
        source: ids.sourceId,
        paint: {
          'line-color': lineColor,
          'line-width': 0.45,
          'line-opacity': lineOpacity,
        },
      },
      getWeatherOverlayBeforeLayerId(map),
    )
    return
  }

  existingSource.setData(geojsonSource as any)
  if (map.getLayer(ids.fillLayerId)) {
    map.setPaintProperty(ids.fillLayerId, 'fill-color', fillColor)
    map.setPaintProperty(ids.fillLayerId, 'fill-opacity', fillOpacity)
    map.setLayoutProperty(ids.fillLayerId, 'visibility', 'visible')
  }
  if (map.getLayer(ids.lineLayerId)) {
    map.setPaintProperty(ids.lineLayerId, 'line-color', lineColor)
    map.setPaintProperty(ids.lineLayerId, 'line-opacity', lineOpacity)
    map.setLayoutProperty(ids.lineLayerId, 'visibility', 'visible')
  }
}

export function syncWeatherHeatmapOverlay(map: MapInstance, overlayState: WeatherOverlayState) {
  const geojsonSource = overlayState.geojsonData ?? overlayState.geojsonUrl
  if (!geojsonSource) return

  const ids = buildWeatherOverlayIds(overlayState.catalogId)
  removeWeatherMapArtifacts(map, overlayState.catalogId, { preserveGeoJsonSource: true })

  const existingSource = map.getSource(ids.sourceId) as GeoJSONSource | undefined
  const heatmapOpacity = Math.max(0.12, getWeatherFillOpacity(overlayState.renderHint, overlayState.opacity))
  const pointOpacity = Math.max(0.2, overlayState.opacity * 0.86)
  const pointRadius = buildWeatherPointRadiusExpression(overlayState.renderHint)
  const pointColor = buildWeatherPointColorExpression(overlayState.renderHint)
  const heatmapColor = buildWeatherHeatmapColorExpression(overlayState.renderHint)
  const heatmapWeight = buildWeatherHeatmapWeightExpression(overlayState.renderHint)

  if (!existingSource) {
    map.addSource(ids.sourceId, {
      type: 'geojson',
      data: geojsonSource,
    } as GeoJsonSourceSpecification)
  } else {
    existingSource.setData(geojsonSource as any)
  }

  if (!map.getLayer(ids.heatmapLayerId)) {
    map.addLayer(
      {
        id: ids.heatmapLayerId,
        type: 'heatmap',
        source: ids.sourceId,
        maxzoom: 9,
        paint: {
          'heatmap-weight': heatmapWeight,
          'heatmap-intensity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            0, 0.28,
            2.5, 0.42,
            5, 0.68,
            7, 0.9,
            9, 1.02,
          ],
          'heatmap-radius': [
            'interpolate',
            ['linear'],
            ['zoom'],
            0, 18,
            2.5, 26,
            5, 34,
            7, 42,
            9, 52,
          ],
          'heatmap-opacity': heatmapOpacity,
          'heatmap-color': heatmapColor,
        },
      },
      getWeatherOverlayBeforeLayerId(map),
    )
  } else {
    map.setPaintProperty(ids.heatmapLayerId, 'heatmap-weight', heatmapWeight)
    map.setPaintProperty(ids.heatmapLayerId, 'heatmap-intensity', [
      'interpolate',
      ['linear'],
      ['zoom'],
      0, 0.28,
      2.5, 0.42,
      5, 0.68,
      7, 0.9,
      9, 1.02,
    ])
    map.setPaintProperty(ids.heatmapLayerId, 'heatmap-radius', [
      'interpolate',
      ['linear'],
      ['zoom'],
      0, 18,
      2.5, 26,
      5, 34,
      7, 42,
      9, 52,
    ])
    map.setPaintProperty(ids.heatmapLayerId, 'heatmap-opacity', heatmapOpacity)
    map.setPaintProperty(ids.heatmapLayerId, 'heatmap-color', heatmapColor)
    map.setLayoutProperty(ids.heatmapLayerId, 'visibility', 'visible')
  }

  if (!map.getLayer(ids.heatmapPointLayerId)) {
    map.addLayer(
      {
        id: ids.heatmapPointLayerId,
        type: 'circle',
        source: ids.sourceId,
        minzoom: 4.75,
        paint: {
          'circle-radius': pointRadius,
          'circle-color': pointColor,
          'circle-opacity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            4.75, 0,
            6.5, Math.max(0.14, pointOpacity * 0.42),
            8.2, Math.max(0.18, pointOpacity * 0.72),
            10, pointOpacity,
          ],
          'circle-stroke-color': 'rgba(255, 244, 214, 0.88)',
          'circle-stroke-width': 0.6,
          'circle-stroke-opacity': [
            'interpolate',
            ['linear'],
            ['zoom'],
            4.75, 0,
            7, 0.18,
            8.2, 0.34,
            10, 0.52,
          ],
        },
      },
      getWeatherOverlayBeforeLayerId(map),
    )
  } else {
    map.setPaintProperty(ids.heatmapPointLayerId, 'circle-radius', pointRadius)
    map.setPaintProperty(ids.heatmapPointLayerId, 'circle-color', pointColor)
    map.setPaintProperty(ids.heatmapPointLayerId, 'circle-opacity', [
      'interpolate',
      ['linear'],
      ['zoom'],
      4.75, 0,
      6.5, Math.max(0.14, pointOpacity * 0.42),
      8.2, Math.max(0.18, pointOpacity * 0.72),
      10, pointOpacity,
    ])
    map.setPaintProperty(ids.heatmapPointLayerId, 'circle-stroke-opacity', [
      'interpolate',
      ['linear'],
      ['zoom'],
      4.75, 0,
      7, 0.18,
      8.2, 0.34,
      10, 0.52,
    ])
    map.setLayoutProperty(ids.heatmapPointLayerId, 'visibility', 'visible')
  }
}

export function syncWeatherPointOverlay(map: MapInstance, overlayState: WeatherOverlayState) {
  const geojsonSource = overlayState.geojsonData ?? overlayState.geojsonUrl
  if (!geojsonSource) return

  const ids = buildWeatherOverlayIds(overlayState.catalogId)
  removeWeatherMapArtifacts(map, overlayState.catalogId, { preserveGeoJsonSource: true })

  const existingSource = map.getSource(ids.sourceId) as GeoJSONSource | undefined
  const pointColor = buildWeatherPointColorExpression(overlayState.renderHint)
  const pointRadius = buildWeatherPointRadiusExpression(overlayState.renderHint)
  const arrowSize = buildWeatherArrowSizeExpression(overlayState.renderHint)
  const pointOpacity = getWeatherFillOpacity(overlayState.renderHint, overlayState.opacity)

  if (!existingSource) {
    map.addSource(ids.sourceId, {
      type: 'geojson',
      data: geojsonSource,
    } as GeoJsonSourceSpecification)

    map.addLayer({
      id: ids.pointLayerId,
      type: 'circle',
      source: ids.sourceId,
      paint: {
        'circle-radius': pointRadius,
        'circle-color': pointColor,
        'circle-opacity': Math.max(0.18, pointOpacity * 0.52),
        'circle-stroke-color': 'rgba(230, 248, 255, 0.82)',
        'circle-stroke-width': 0.7,
        'circle-stroke-opacity': Math.max(0.18, pointOpacity * 0.7),
      },
    })

    map.addLayer({
      id: ids.arrowLayerId,
      type: 'symbol',
      source: ids.sourceId,
      layout: {
        'text-field': '➤',
        'text-size': ['*', 15, arrowSize],
        'text-allow-overlap': true,
        'text-ignore-placement': true,
        'text-rotate': ['coalesce', ['to-number', ['get', 'wind_direction_10m']], 0],
        'text-rotation-alignment': 'map',
      },
      paint: {
        'text-color': '#e8fbff',
        'text-opacity': pointOpacity,
        'text-halo-color': 'rgba(5, 16, 30, 0.86)',
        'text-halo-width': 1.1,
      },
    })
    return
  }

  existingSource.setData(geojsonSource as any)
  if (map.getLayer(ids.pointLayerId)) {
    map.setPaintProperty(ids.pointLayerId, 'circle-radius', pointRadius)
    map.setPaintProperty(ids.pointLayerId, 'circle-color', pointColor)
    map.setPaintProperty(ids.pointLayerId, 'circle-opacity', Math.max(0.18, pointOpacity * 0.52))
    map.setPaintProperty(ids.pointLayerId, 'circle-stroke-opacity', Math.max(0.18, pointOpacity * 0.7))
  }
  if (map.getLayer(ids.arrowLayerId)) {
    map.setLayoutProperty(ids.arrowLayerId, 'text-size', ['*', 15, arrowSize])
    map.setPaintProperty(ids.arrowLayerId, 'text-opacity', pointOpacity)
  }
}
