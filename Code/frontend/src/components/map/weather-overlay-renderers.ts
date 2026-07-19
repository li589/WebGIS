import {
  buildWeatherArrowSizeExpression,
  buildWeatherFillColorExpression,
  buildWeatherPointColorExpression,
  buildWeatherPointRadiusExpression,
  getWeatherFillOpacity,
} from './weather-render'
import { buildWeatherOverlayIds, getWeatherOverlayBeforeLayerId, removeWeatherMapArtifacts } from './weather-overlay-maplibre'
import type { WeatherOverlayState } from './weather-overlay-registry'
import type { WindGeoJSON } from './types'

type MapInstance = import('maplibre-gl').Map
type GeoJsonSourceSpecification = import('maplibre-gl').GeoJSONSourceSpecification
type GeoJSONSource = import('maplibre-gl').GeoJSONSource
type ImageSourceSpecification = import('maplibre-gl').ImageSourceSpecification
type ImageSource = import('maplibre-gl').ImageSource

type HeatmapFeatureCollection = {
  type: 'FeatureCollection'
  features: Array<{
    type: string
    geometry?: { type: string; coordinates: unknown }
    properties?: Record<string, unknown> | null
    [key: string]: unknown
  }>
}

/** Polygon/MultiPolygon → 点质心，供 MapLibre heatmap 使用 */
export function geojsonToHeatmapPoints(
  data: HeatmapFeatureCollection | WindGeoJSON | string,
): HeatmapFeatureCollection | WindGeoJSON | string {
  if (typeof data === 'string') return data
  if (!data || data.type !== 'FeatureCollection' || !Array.isArray(data.features)) return data

  const features = data.features.map((feature) => {
    const geom = feature.geometry as { type: string; coordinates: number[][] | number[][][] | number[][][][] } | undefined
    if (!geom) return feature
    if (geom.type === 'Point') return feature
    if (geom.type === 'Polygon') {
      const ring = (geom.coordinates as number[][])[0] ?? []
      if (ring.length === 0) return feature
      let sx = 0
      let sy = 0
      for (const pt of ring) {
        sx += pt[0]
        sy += pt[1]
      }
      const n = ring.length
      return {
        ...feature,
        geometry: { type: 'Point' as const, coordinates: [sx / n, sy / n] },
      }
    }
    if (geom.type === 'MultiPolygon') {
      const ring = (geom.coordinates as number[][][])[0]?.[0] ?? []
      if (ring.length === 0) return feature
      let sx = 0
      let sy = 0
      for (const pt of ring) {
        sx += pt[0]
        sy += pt[1]
      }
      const n = ring.length
      return {
        ...feature,
        geometry: { type: 'Point' as const, coordinates: [sx / n, sy / n] },
      }
    }
    return feature
  })

  return { type: 'FeatureCollection', features }
}

function medianPositive(values: number[]): number | null {
  const sorted = values.filter((v) => Number.isFinite(v) && v > 1e-9).sort((a, b) => a - b)
  if (!sorted.length) return null
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
}

/**
 * 规则点阵 → 矩形网格单元，供 fill 连续色场使用。
 * 避免 heatmap 在放大后变成「一坨一坨晕点」。
 */
export function geojsonPointsToGridCells(
  data: HeatmapFeatureCollection | WindGeoJSON,
): HeatmapFeatureCollection | WindGeoJSON {
  if (!data || data.type !== 'FeatureCollection' || !Array.isArray(data.features)) return data

  const points: Array<{ lon: number; lat: number; feature: (typeof data.features)[number] }> = []
  let polygonCount = 0
  for (const feature of data.features) {
    const geom = feature.geometry as { type?: string; coordinates?: number[] } | undefined
    if (!geom) continue
    if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
      polygonCount += 1
      continue
    }
    if (geom.type !== 'Point' || !Array.isArray(geom.coordinates) || geom.coordinates.length < 2) continue
    const lon = Number(geom.coordinates[0])
    const lat = Number(geom.coordinates[1])
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
    points.push({ lon, lat, feature })
  }

  // 已是多边形网格：直接用于 fill
  if (polygonCount > 0 && points.length === 0) return data
  if (points.length === 0) return data

  const lonSet = Array.from(new Set(points.map((p) => Math.round(p.lon * 1e6) / 1e6))).sort((a, b) => a - b)
  const latSet = Array.from(new Set(points.map((p) => Math.round(p.lat * 1e6) / 1e6))).sort((a, b) => a - b)
  const lonGaps = lonSet.slice(1).map((v, i) => v - lonSet[i])
  const latGaps = latSet.slice(1).map((v, i) => v - latSet[i])
  const lonStep = medianPositive(lonGaps) ?? 0.25
  const latStep = medianPositive(latGaps) ?? 0.25
  const halfLon = lonStep / 2
  const halfLat = latStep / 2

  const features = points.map(({ lon, lat, feature }) => ({
    ...feature,
    geometry: {
      type: 'Polygon' as const,
      coordinates: [[
        [lon - halfLon, lat - halfLat],
        [lon + halfLon, lat - halfLat],
        [lon + halfLon, lat + halfLat],
        [lon - halfLon, lat + halfLat],
        [lon - halfLon, lat - halfLat],
      ]],
    },
  }))

  return { type: 'FeatureCollection', features }
}

/** 连续色场用 GeoJSON：多边形原样；点阵转成网格单元 */
export function prepareContinuousFieldGeojson(
  data: HeatmapFeatureCollection | WindGeoJSON | string | null | undefined,
): HeatmapFeatureCollection | WindGeoJSON | string | null {
  if (!data || typeof data === 'string') return data ?? null
  return geojsonPointsToGridCells(data)
}

export function syncWeatherCogOverlay(map: MapInstance, overlayState: WeatherOverlayState) {
  if (!overlayState.cogPreviewUrl || !overlayState.cogBbox) return

  const ids = buildWeatherOverlayIds(overlayState.catalogId)
  removeWeatherMapArtifacts(map, overlayState.catalogId, { preserveImageSource: true })

  const ticks = (overlayState.renderHint.legend_ticks ?? []).filter(
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
  const rawSource = overlayState.geojsonData ?? overlayState.geojsonUrl
  if (!rawSource) return
  const geojsonSource = typeof rawSource === 'string'
    ? rawSource
    : prepareContinuousFieldGeojson(rawSource as HeatmapFeatureCollection | WindGeoJSON)

  if (!geojsonSource) return

  const ids = buildWeatherOverlayIds(overlayState.catalogId)
  // 已有 fill 时就地更新，避免每次瓦片到达都拆层闪烁
  if (!map.getLayer(ids.fillLayerId)) {
    removeWeatherMapArtifacts(map, overlayState.catalogId, { preserveGeoJsonSource: true })
  }

  // 连续色场改用网格 fill 后，清掉旧 heatmap/bloom，避免晕点叠在色块上
  if (map.getLayer(ids.heatmapPointLayerId)) map.removeLayer(ids.heatmapPointLayerId)
  if (map.getLayer(ids.heatmapLayerId)) map.removeLayer(ids.heatmapLayerId)
  if (map.getLayer(ids.bloomLayerId)) map.removeLayer(ids.bloomLayerId)
  if (map.getSource(ids.bloomSourceId)) map.removeSource(ids.bloomSourceId)

  const existingSource = map.getSource(ids.sourceId) as GeoJSONSource | undefined
  const fillOpacity = getWeatherFillOpacity(overlayState.renderHint, overlayState.opacity)
  const fillColor = buildWeatherFillColorExpression(overlayState.renderHint)

  if (!existingSource) {
    map.addSource(ids.sourceId, {
      type: 'geojson',
      data: geojsonSource,
    } as GeoJsonSourceSpecification)
  } else {
    existingSource.setData(geojsonSource as any)
  }

  if (!map.getLayer(ids.fillLayerId)) {
    map.addLayer(
      {
        id: ids.fillLayerId,
        type: 'fill',
        source: ids.sourceId,
        paint: {
          'fill-color': fillColor,
          'fill-opacity': fillOpacity,
          'fill-antialias': true,
        },
      },
      getWeatherOverlayBeforeLayerId(map),
    )
  } else {
    map.setPaintProperty(ids.fillLayerId, 'fill-color', fillColor)
    map.setPaintProperty(ids.fillLayerId, 'fill-opacity', fillOpacity)
    map.setLayoutProperty(ids.fillLayerId, 'visibility', 'visible')
  }

  // 去掉网格描边，避免色块感；若旧会话残留 line 层则隐藏
  if (map.getLayer(ids.lineLayerId)) {
    map.setLayoutProperty(ids.lineLayerId, 'visibility', 'none')
  }
}

export function syncWeatherHeatmapOverlay(map: MapInstance, overlayState: WeatherOverlayState) {
  // 连续气象场统一走网格 fill：heatmap 放大后必然「一坨坨晕点」，观感差
  syncWeatherGridFillOverlay(map, {
    ...overlayState,
    renderHint: {
      ...overlayState.renderHint,
      paint_mode: 'grid_fill',
    },
  })
}

export function syncWeatherPointOverlay(map: MapInstance, overlayState: WeatherOverlayState) {
  const geojsonSource = overlayState.geojsonData ?? overlayState.geojsonUrl
  if (!geojsonSource) return

  const ids = buildWeatherOverlayIds(overlayState.catalogId)
  if (!map.getLayer(ids.pointLayerId)) {
    removeWeatherMapArtifacts(map, overlayState.catalogId, { preserveGeoJsonSource: true })
  }

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

/**
 * 风场粒子下方的风速色底：网格 fill（连续），不用 heatmap。
 * 与粒子 Canvas 叠用：MapLibre fill 在下，Canvas 粒子在上。
 */
export function syncWeatherSpeedUnderlay(map: MapInstance, overlayState: WeatherOverlayState) {
  const underlayOpacity = Math.min(0.58, (overlayState.opacity ?? 0.7) * 0.72)
  syncWeatherGridFillOverlay(map, {
    ...overlayState,
    opacity: underlayOpacity,
    renderHint: {
      ...overlayState.renderHint,
      paint_mode: 'grid_fill',
      opacity: Math.min(0.62, (overlayState.renderHint.opacity ?? 0.7) * 0.72),
    },
  })
}
