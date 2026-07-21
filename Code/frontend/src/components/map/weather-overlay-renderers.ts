import {
  boundsToPolygonRing,
  latticeCellBounds,
  latticeIndex,
} from './weather-grid-lattice'
import {
  buildWeatherArrowSizeExpression,
  buildWeatherFillColorExpression,
  buildWeatherFillOpacityExpression,
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

/** FeatureCollection 宽松类型（grid_fill / 连续色场） */
type FieldFeatureCollection = {
  type: 'FeatureCollection'
  features: Array<{
    type: string
    geometry?: { type: string; coordinates: unknown }
    properties?: Record<string, unknown> | null
    [key: string]: unknown
  }>
}

function medianPositive(values: number[]): number | null {
  const sorted = values.filter((v) => Number.isFinite(v) && v > 1e-9).sort((a, b) => a - b)
  if (!sorted.length) return null
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
}

/**
 * 与后端 `zoom_to_resolution` 对齐的固定格点步长（度）。
 * 用于 fill 单元尺寸，避免跨瓦片中位 gap 失真导致细缝。
 */
export function weatherZoomToResolution(z: number): number {
  const zoom = Math.max(0, Math.min(12, Math.round(z)))
  if (zoom <= 1) return 10.0
  if (zoom <= 2) return 5.0
  if (zoom <= 3) return 2.5
  if (zoom <= 5) return 1.0
  if (zoom <= 7) return 0.5
  return 0.25
}

/** 从 feature props / 中位 gap / zoom 推断格点步长 */
function resolveGridStepDegrees(
  points: Array<{ lon: number; lat: number; feature: { properties?: Record<string, unknown> | null } }>,
  axis: 'lon' | 'lat',
  options?: { zoom?: number; stepDegrees?: number },
): number {
  if (typeof options?.stepDegrees === 'number' && options.stepDegrees > 0) {
    return options.stepDegrees
  }
  for (const p of points) {
    const props = p.feature.properties
    if (!props) continue
    const fromProp =
      Number(props.resolution)
      || Number(props.grid_resolution)
      || Number(props.step)
      || Number(props.cell_size)
    if (Number.isFinite(fromProp) && fromProp > 0) return fromProp
  }
  if (typeof options?.zoom === 'number' && Number.isFinite(options.zoom)) {
    return weatherZoomToResolution(options.zoom)
  }
  const coords = points.map((p) => (axis === 'lon' ? p.lon : p.lat))
  const unique = Array.from(new Set(coords.map((v) => Math.round(v * 1e6) / 1e6))).sort((a, b) => a - b)
  const gaps = unique.slice(1).map((v, i) => v - unique[i])
  return medianPositive(gaps) ?? 0.25
}

/**
 * 规则点阵 → 矩形网格单元，供 fill 连续色场使用。
 * 格心吸附全球 (i+0.5)*res；瓦片半开只决定谁发出该格心，格元不裁进瓦片框，
 * 以免格网边与 Mercator 瓦片边错位时留下横/纵空隙。
 */
export function geojsonPointsToGridCells(
  data: FieldFeatureCollection | WindGeoJSON,
  options?: { zoom?: number; stepDegrees?: number },
): FieldFeatureCollection | WindGeoJSON {
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

  const lonStep = resolveGridStepDegrees(points, 'lon', options)
  const latStep = resolveGridStepDegrees(points, 'lat', options)
  const fallbackStep = lonStep > 0 ? lonStep : latStep

  const seenCells = new Set<string>()
  const features: Array<(typeof data.features)[number]> = []

  for (const { lon, lat, feature } of points) {
    const props = feature.properties ?? {}
    const fromProp =
      Number(props.resolution) ||
      Number(props.grid_resolution) ||
      Number(props.step) ||
      Number(props.cell_size)
    // 每点用自身分辨率建格元，避免跨赤道父子 z 混用时被首点粗分辨率拉大留下空带
    const step =
      Number.isFinite(fromProp) && fromProp > 0 ? fromProp : fallbackStep
    const ix = latticeIndex(lon, step)
    const iy = latticeIndex(lat, step)
    const key = `${step}:${ix}:${iy}`
    if (seenCells.has(key)) continue
    seenCells.add(key)

    const cell = latticeCellBounds(lon, lat, step)
    const nextProps = { ...props }
    delete (nextProps as Record<string, unknown>)._tile_bounds

    features.push({
      ...feature,
      properties: nextProps,
      geometry: {
        type: 'Polygon' as const,
        coordinates: [boundsToPolygonRing(cell)],
      },
    })
  }

  return { type: 'FeatureCollection', features }
}

/** 连续色场用 GeoJSON：多边形原样；点阵转成网格单元 */
export function prepareContinuousFieldGeojson(
  data: FieldFeatureCollection | WindGeoJSON | string | null | undefined,
  options?: { zoom?: number; stepDegrees?: number },
): FieldFeatureCollection | WindGeoJSON | string | null {
  if (!data || typeof data === 'string') return data ?? null
  return geojsonPointsToGridCells(data, options)
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
  const zoom = typeof map.getZoom === 'function' ? map.getZoom() : undefined
  const geojsonSource = typeof rawSource === 'string'
    ? rawSource
    : prepareContinuousFieldGeojson(rawSource as FieldFeatureCollection | WindGeoJSON, { zoom })

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
  const fillOpacity = buildWeatherFillOpacityExpression(overlayState.renderHint, overlayState.opacity)
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

/** @deprecated 名称保留兼容；实现已统一为 grid_fill（见 syncWeatherGridFillOverlay）。 */
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
        'text-rotate': [
          'coalesce',
          ['to-number', ['get', 'wind_direction_10m']],
          ['to-number', ['get', 'wind_direction_80m']],
          ['to-number', ['get', 'wind_direction_120m']],
          ['to-number', ['get', 'wind_direction_180m']],
          ['to-number', ['get', 'wind_direction_850hPa']],
          ['to-number', ['get', 'wind_direction_500hPa']],
          ['to-number', ['get', 'wind_direction_200hPa']],
          0,
        ],
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
