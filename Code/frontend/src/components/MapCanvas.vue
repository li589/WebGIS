<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useLayersStore } from '../stores/layers'
import type { DemoHotspot } from '../app/demo-data'
import {
  buildWeatherArrowSizeExpression,
  buildWeatherFillColorExpression,
  buildWeatherPointColorExpression,
  buildWeatherPointRadiusExpression,
  getWeatherFillOpacity,
  getWeatherLineColor,
  getWeatherLineOpacity,
} from './map/weather-render'
import { WindParticleCanvas } from './map/wind-particle-canvas'
import { WindBarbLayer } from './map/wind-barb-layer'
import { WindContourLayer } from './map/wind-contour-layer'
import { resolveApiUrl } from '../services/runtime-api'
import type { TileSourceId } from '../stores/ui'
import { TILE_SOURCE_MAP } from '../stores/ui'
import type { StyleSpecification } from 'maplibre-gl'

const layersStore = useLayersStore()

const props = defineProps<{
  tileSourceId: TileSourceId
  currentHour: number
  hourLabel: string
}>()

const emit = defineEmits<{
  visibleHotspotsChange: [hotspots: DemoHotspot[]]
  hotspotSelect: [hotspot: DemoHotspot | null]
  mapPointSelect: [point: { lng: number; lat: number }]
}>()

defineExpose({ getMapStageElement, captureMapCanvas })

const mapContainer = ref<HTMLElement | null>(null)
const mapStageRef = ref<HTMLElement | null>(null)
const hotspotPins = ref<
  Array<{
    id: string
    name: string
    value: string
    left: string
    top: string
    selected: boolean
  }>
>([])
const selectedHotspotId = ref<string | null>(null)
const mapReady = ref(false)
const mapVisible = ref(false)
const skeletonVisible = ref(true)
const isMapInteracting = ref(false)
const isSourceTransitioning = ref(false)
const loadingLabel = ref('正在加载地图...')
const tileLoadFailed = ref(false)
const tileLoadRetryCount = ref(0)
const MAX_TILE_RETRIES = 2

type MapInstance = import('maplibre-gl').Map
type GeoJsonSourceSpecification = import('maplibre-gl').GeoJSONSourceSpecification
type GeoJSONSource = import('maplibre-gl').GeoJSONSource
type ImageSourceSpecification = import('maplibre-gl').ImageSourceSpecification
type ImageSource = import('maplibre-gl').ImageSource
type RasterSourceSpecification = import('maplibre-gl').RasterSourceSpecification
type GuangdongBoundaryData = typeof import('../app/guangdong-boundaries')

let boundaryModule: GuangdongBoundaryData | null = null
let boundaryModulePromise: Promise<GuangdongBoundaryData | null> | null = null
let map: MapInstance | null = null
let animationFrameId: number | null = null
let sourceTransitionTimer: number | null = null

const TILE_SOURCE_ID = 'tile-base'
const TILE_LAYER_ID = 'tile-base-raster'

// ── 多图层叠加：每个 weatherengine 图层用独立 source/layer ID ──────────────
// 通过 catalogId 后缀隔离，避免多个 grid_fill 图层互相覆盖
function weatherSourceId(catalogId: string) { return `weather-src-${catalogId}` }
function weatherFillLayerId(catalogId: string) { return `weather-fill-${catalogId}` }
function weatherLineLayerId(catalogId: string) { return `weather-line-${catalogId}` }
function weatherPointLayerId(catalogId: string) { return `weather-point-${catalogId}` }
function weatherArrowLayerId(catalogId: string) { return `weather-arrow-${catalogId}` }
function weatherImageSourceId(catalogId: string) { return `weather-img-src-${catalogId}` }
function weatherRasterLayerId(catalogId: string) { return `weather-raster-${catalogId}` }

// 跟踪当前已渲染的 weather 图层 catalogId（用于增量清理）
const renderedWeatherCatalogIds = new Set<string>()

// 风场粒子流/风羽/等值线 canvas 叠加层实例（独占，同时只一个图层启用）
let windParticleCanvas: WindParticleCanvas | null = null
let windBarbLayer: WindBarbLayer | null = null
let windContourLayer: WindContourLayer | null = null
let currentWindGeojson: any = null
let lastWindGeojsonUrl: string | null = null
let currentParticleFlowCatalogId: string | null = null

const currentTileConfig = computed(() => TILE_SOURCE_MAP.get(props.tileSourceId) ?? TILE_SOURCE_MAP.get('esri-street')!)

// ── Derived from layersStore ──────────────────────────────────────────────────

const selectedLayer = computed(() => layersStore.selectedLayerDisplay)
const hasAdminBoundary = computed(() => layersStore.activeLayersDisplay.some((d) => d.isAdminBoundary))
const adminBoundaryOpacity = computed(() => {
  const layer = layersStore.activeLayersDisplay.find((d) => d.isAdminBoundary)
  return layer ? layer.opacity : 1
})

// Safe fallback for template (no selected layer = dark atmospheric state)
const activeLayer = computed(() => {
  const s = selectedLayer.value
  if (s) return s
  return {
    name: '无图层',
    availabilityState: 'empty' as const,
    availabilityLabel: '空状态',
    availabilityDescription: '从左侧图层面板添加数据图层。',
    observationTimeLabel: '—',
    missingFieldsLabel: '—',
    accentColor: '#5a6a80',
    accentGlow: 'rgba(90, 106, 128, 0.3)',
    chipTone: 'rgba(90, 106, 128, 0.16)',
    metricLabel: '—',
    metricValue: '—',
    hotspots: [],
    summary: '',
    trendLabel: '',
    statusLabel: '',
    updateLabel: '',
    sourceLabel: '',
    confidenceLabel: '',
    trend: '',
    dataState: 'demo' as const,
    isAdminBoundary: false,
    instanceId: '',
    catalogId: '',
    category: '',
    order: 0,
    visible: true,
    opacity: 1,
    reportSummary: '',
    resultUrl: '',
  }
})

// ─── Tile layer management ───────────────────────────────────────────────────

function ensureTileLayer(sourceId: TileSourceId) {
  if (!map) return

  const cfg = TILE_SOURCE_MAP.get(sourceId)
  if (!cfg) return

  if (!map.getSource(TILE_SOURCE_ID)) {
    map.addSource(TILE_SOURCE_ID, {
      type: 'raster',
      tiles: [cfg.urlTemplate],
      tileSize: cfg.tileSize ?? 256,
      attribution: cfg.attribution,
      maxzoom: 18,
      scheme: 'xyz',
    } as RasterSourceSpecification)
  }

  if (!map.getLayer(TILE_LAYER_ID)) {
    const beforeLayerId = map.getLayer('admin-fill') ? 'admin-fill' : undefined
    map.addLayer(
      {
        id: TILE_LAYER_ID,
        type: 'raster',
        source: TILE_SOURCE_ID,
        layout: { visibility: 'none' },
        paint: {
          'raster-opacity': 0.88,
          'raster-saturation': cfg.saturation,
          'raster-brightness-max': 1.0 + cfg.brightness,
          'raster-brightness-min': 0.0 + Math.max(0, cfg.brightness),
          'raster-contrast': cfg.contrast,
        },
      },
      beforeLayerId,
    )
  }
}

function switchTileSource(sourceId: TileSourceId) {
  if (!map) return

  tileLoadFailed.value = false
  tileLoadRetryCount.value = 0

  if (sourceId === 'none') {
    if (map.getLayer(TILE_LAYER_ID)) {
      map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'none')
    }
    return
  }

  const cfg = TILE_SOURCE_MAP.get(sourceId)
  if (!cfg) return

  if (map.getSource(TILE_SOURCE_ID)) {
    if (map.getLayer(TILE_LAYER_ID)) map.removeLayer(TILE_LAYER_ID)
    map.removeSource(TILE_SOURCE_ID)
  }

  ensureTileLayer(sourceId)

  if (map.getLayer(TILE_LAYER_ID)) {
    map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'visible')
    map.setPaintProperty(TILE_LAYER_ID, 'raster-opacity', 0.88)
    map.setPaintProperty(TILE_LAYER_ID, 'raster-saturation', cfg.saturation)
    map.setPaintProperty(TILE_LAYER_ID, 'raster-brightness-max', 1.0 + cfg.brightness)
    map.setPaintProperty(TILE_LAYER_ID, 'raster-brightness-min', 0.0 + Math.max(0, cfg.brightness))
    map.setPaintProperty(TILE_LAYER_ID, 'raster-contrast', cfg.contrast)
  }
}

// ─── Boundary layers ─────────────────────────────────────────────────────────

async function ensureBoundaryModule() {
  if (!boundaryModule) {
    if (!boundaryModulePromise) {
      loadingLabel.value = '正在载入行政区边界...'
      boundaryModulePromise = import('../app/guangdong-boundaries').catch((err) => {
        console.error('[MapCanvas] Failed to load boundary module:', err)
        boundaryModulePromise = null
        return null
      })
    }
    const module = await boundaryModulePromise
    if (!module) return null
    boundaryModule = module
  }
  return boundaryModule
}

async function ensureBoundaryLayers() {
  if (!map) return

  const loadedBoundaryModule = await ensureBoundaryModule()
  if (!loadedBoundaryModule) return
  // 组件可能在 await 期间卸载（onBeforeUnmount 已将 map 置 null），需重新检查
  if (!map) return

  if (!map.getSource('admin-boundaries')) {
    map.addSource('admin-boundaries', {
      type: 'geojson',
      data: loadedBoundaryModule.guangdongCityBoundaries,
    } as GeoJsonSourceSpecification)
  }

  if (!map.getSource('admin-centers')) {
    map.addSource('admin-centers', {
      type: 'geojson',
      data: loadedBoundaryModule.guangdongCityCenters,
    } as GeoJsonSourceSpecification)
  }

  if (!map.getLayer('admin-fill')) {
    map.addLayer({
      id: 'admin-fill',
      type: 'fill',
      source: 'admin-boundaries',
      paint: {
        'fill-color': '#0c2238',
        'fill-opacity': 0,
      },
    })
  }

  if (!map.getLayer('admin-line')) {
    map.addLayer({
      id: 'admin-line',
      type: 'line',
      source: 'admin-boundaries',
      paint: {
        'line-color': '#4c88ba',
        'line-width': 1,
        'line-opacity': 0,
      },
    })
  }

  if (!map.getLayer('admin-center-points')) {
    map.addLayer({
      id: 'admin-center-points',
      type: 'circle',
      source: 'admin-centers',
      paint: {
        'circle-radius': 2.2,
        'circle-color': '#d8efff',
        'circle-opacity': 0,
        'circle-stroke-width': 1,
        'circle-stroke-color': '#0a233a',
      },
    })
  }
}

function applyAdminOverlay(show: boolean, opacity: number) {
  if (!map) return
  const lineOpacity = show ? 0.82 * opacity : 0
  const fillOpacity = show ? 0.32 * opacity : 0
  const centerOpacity = show ? 0.72 * opacity : 0

  if (map.getLayer('admin-fill')) {
    map.setLayoutProperty('admin-fill', 'visibility', 'visible')
    map.setPaintProperty('admin-fill', 'fill-opacity', fillOpacity)
  }
  if (map.getLayer('admin-line')) {
    map.setLayoutProperty('admin-line', 'visibility', 'visible')
    map.setPaintProperty('admin-line', 'line-opacity', lineOpacity)
  }
  if (map.getLayer('admin-center-points')) {
    map.setLayoutProperty('admin-center-points', 'visibility', 'visible')
    map.setPaintProperty('admin-center-points', 'circle-opacity', centerOpacity)
  }
}

function syncAdminOverlay() {
  if (!mapReady.value) return
  applyAdminOverlay(hasAdminBoundary.value, adminBoundaryOpacity.value)
}

function removeWeatherOverlayForCatalog(catalogId: string) {
  if (!map) return
  const srcId = weatherSourceId(catalogId)
  const fillId = weatherFillLayerId(catalogId)
  const lineId = weatherLineLayerId(catalogId)
  const pointId = weatherPointLayerId(catalogId)
  const arrowId = weatherArrowLayerId(catalogId)
  const imgSrcId = weatherImageSourceId(catalogId)
  const rasterId = weatherRasterLayerId(catalogId)
  if (map.getLayer(rasterId)) map.removeLayer(rasterId)
  if (map.getSource(imgSrcId)) map.removeSource(imgSrcId)
  if (map.getLayer(arrowId)) map.removeLayer(arrowId)
  if (map.getLayer(pointId)) map.removeLayer(pointId)
  if (map.getLayer(lineId)) map.removeLayer(lineId)
  if (map.getLayer(fillId)) map.removeLayer(fillId)
  if (map.getSource(srcId)) map.removeSource(srcId)
  renderedWeatherCatalogIds.delete(catalogId)
}

function removeWeatherOverlay() {
  if (!map) return
  // 清理所有已渲染的 weather 图层
  for (const catalogId of Array.from(renderedWeatherCatalogIds)) {
    removeWeatherOverlayForCatalog(catalogId)
  }
  // 销毁风场粒子流/风羽/等值线 canvas 叠加层
  if (windParticleCanvas) {
    windParticleCanvas.destroy()
    windParticleCanvas = null
  }
  if (windBarbLayer) {
    windBarbLayer.destroy()
    windBarbLayer = null
  }
  if (windContourLayer) {
    windContourLayer.destroy()
    windContourLayer = null
  }
  currentWindGeojson = null
  lastWindGeojsonUrl = null
  currentParticleFlowCatalogId = null
}

interface WeatherOverlayState {
  catalogId: string
  geojsonUrl: string | null
  cogPreviewUrl: string | null
  cogBbox: { west: number; south: number; east: number; north: number } | null
  renderHint: any
  opacity: number
}

/** 解析所有可见 weatherengine 图层的 overlay 状态（多图层叠加） */
function resolveAllWeatherOverlayStates(): WeatherOverlayState[] {
  const states: WeatherOverlayState[] = []
  for (const layer of layersStore.activeLayersDisplay) {
    if (!layer.visible) continue
    if (layer.isAdminBoundary) continue
    const renderHint = layer.jobLayer?.mapLayerPayload?.renderHint
    if (!renderHint) continue
    const geojsonUrl = layer.jobLayer?.mapLayerPayload?.layerAssets?.geojsonUrl
    const cogPreviewUrl = layer.jobLayer?.mapLayerPayload?.layerAssets?.cogPreviewUrl
    const cogBbox = layer.jobLayer?.mapLayerPayload?.layerAssets?.cogBbox ?? null
    const resolvedGeojsonUrl = typeof geojsonUrl === 'string' && geojsonUrl.trim() ? resolveApiUrl(geojsonUrl) : null
    const resolvedCogPreviewUrl =
      typeof cogPreviewUrl === 'string' && cogPreviewUrl.trim() ? resolveApiUrl(cogPreviewUrl) : null
    if (renderHint.paint_mode === 'point_symbol' && !resolvedGeojsonUrl) continue
    if (renderHint.paint_mode === 'particle_flow' && !resolvedGeojsonUrl) continue
    if (renderHint.paint_mode === 'grid_fill' && !resolvedGeojsonUrl && !(resolvedCogPreviewUrl && cogBbox)) continue
    states.push({
      catalogId: layer.catalogId,
      geojsonUrl: resolvedGeojsonUrl,
      cogPreviewUrl: resolvedCogPreviewUrl,
      cogBbox,
      renderHint,
      opacity: layer.opacity,
    })
  }
  return states
}

function syncWeatherOverlay() {
  if (!mapReady.value || !map) return
  const targetStates = resolveAllWeatherOverlayStates()
  const targetCatalogIds = new Set(targetStates.map((s) => s.catalogId))

  // 清理不再需要的图层（已删除/隐藏/不可见的）
  for (const catalogId of Array.from(renderedWeatherCatalogIds)) {
    if (!targetCatalogIds.has(catalogId)) {
      removeWeatherOverlayForCatalog(catalogId)
    }
  }

  // 粒子流独占逻辑：只渲染 particleFlowCatalogId 对应的图层
  const enabledFlowId = layersStore.particleFlowCatalogId
  // 若启用的粒子流图层不在目标列表中（被移除/隐藏），则关闭粒子流
  if (enabledFlowId && !targetCatalogIds.has(enabledFlowId)) {
    if (windParticleCanvas || windBarbLayer || windContourLayer) {
      if (windParticleCanvas) { windParticleCanvas.destroy(); windParticleCanvas = null }
      if (windBarbLayer) { windBarbLayer.destroy(); windBarbLayer = null }
      if (windContourLayer) { windContourLayer.destroy(); windContourLayer = null }
      currentWindGeojson = null
      lastWindGeojsonUrl = null
    }
    currentParticleFlowCatalogId = null
  }
  // 切换粒子流图层时清理前一个 canvas
  if (enabledFlowId !== currentParticleFlowCatalogId) {
    if (windParticleCanvas) { windParticleCanvas.destroy(); windParticleCanvas = null }
    if (windBarbLayer) { windBarbLayer.destroy(); windBarbLayer = null }
    if (windContourLayer) { windContourLayer.destroy(); windContourLayer = null }
    currentWindGeojson = null
    lastWindGeojsonUrl = null
    // 上一图层标记为需清理（如果还在 rendered 集合中，会被 removeWeatherOverlayForCatalog 处理）
    if (currentParticleFlowCatalogId) {
      removeWeatherOverlayForCatalog(currentParticleFlowCatalogId)
    }
    currentParticleFlowCatalogId = enabledFlowId
  }

  // 渲染每个图层
  for (const state of targetStates) {
    const { catalogId, renderHint } = state

    // particle_flow 图层：只渲染启用的那个
    if (renderHint.paint_mode === 'particle_flow') {
      if (catalogId === enabledFlowId) {
        syncWindParticleFlow(state)
        renderedWeatherCatalogIds.add(catalogId)
      }
      continue
    }

    // grid_fill / point_symbol 图层：独立渲染
    if (renderHint.paint_mode === 'grid_fill') {
      if (state.cogPreviewUrl && state.cogBbox) {
        syncWeatherCogOverlay(state)
      } else {
        syncWeatherGridFillOverlay(state)
      }
      renderedWeatherCatalogIds.add(catalogId)
      continue
    }

    if (renderHint.paint_mode === 'point_symbol') {
      syncWeatherPointOverlay(state)
      renderedWeatherCatalogIds.add(catalogId)
      continue
    }
  }
}

function syncWeatherCogOverlay(overlayState: WeatherOverlayState) {
  if (!map || !overlayState.cogPreviewUrl || !overlayState.cogBbox) return
  const catalogId = overlayState.catalogId
  const imgSrcId = weatherImageSourceId(catalogId)
  const rasterId = weatherRasterLayerId(catalogId)
  // 切换渲染模式时清理同 catalog 的其他 maplibre 图层
  const fillId = weatherFillLayerId(catalogId)
  const lineId = weatherLineLayerId(catalogId)
  const pointId = weatherPointLayerId(catalogId)
  const arrowId = weatherArrowLayerId(catalogId)
  const srcId = weatherSourceId(catalogId)
  if (map.getLayer(arrowId)) map.removeLayer(arrowId)
  if (map.getLayer(pointId)) map.removeLayer(pointId)
  if (map.getLayer(lineId)) map.removeLayer(lineId)
  if (map.getLayer(fillId)) map.removeLayer(fillId)
  if (map.getSource(srcId)) map.removeSource(srcId)

  const ticks = overlayState.renderHint.legend_ticks.filter((tick): tick is number => typeof tick === 'number')
  const minValue = ticks[0] ?? 0
  const maxValue = ticks[ticks.length - 1] ?? (minValue + 1)
  const previewUrl = `${overlayState.cogPreviewUrl}?palette=${encodeURIComponent(overlayState.renderHint.palette)}&min_value=${minValue}&max_value=${maxValue}&width=768&height=768`
  const coordinates = [
    [overlayState.cogBbox.west, overlayState.cogBbox.north],
    [overlayState.cogBbox.east, overlayState.cogBbox.north],
    [overlayState.cogBbox.east, overlayState.cogBbox.south],
    [overlayState.cogBbox.west, overlayState.cogBbox.south],
  ] as [[number, number], [number, number], [number, number], [number, number]]

  const existingImageSource = map.getSource(imgSrcId) as ImageSource | undefined
  const rasterOpacity = getWeatherFillOpacity(overlayState.renderHint, overlayState.opacity)

  if (!existingImageSource) {
    map.addSource(imgSrcId, {
      type: 'image',
      url: previewUrl,
      coordinates,
    } as ImageSourceSpecification)

    map.addLayer(
      {
        id: rasterId,
        type: 'raster',
        source: imgSrcId,
        paint: {
          'raster-opacity': rasterOpacity,
          'raster-fade-duration': 0,
        },
      },
      map.getLayer('admin-fill') ? 'admin-fill' : undefined,
    )
    return
  }

  existingImageSource.updateImage({
    url: previewUrl,
    coordinates,
  })
  if (map.getLayer(rasterId)) {
    map.setPaintProperty(rasterId, 'raster-opacity', rasterOpacity)
    map.setLayoutProperty(rasterId, 'visibility', 'visible')
  }
}

/** grid_fill 模式：geojson fill + line 渲染（每图层独立 source/layer） */
function syncWeatherGridFillOverlay(overlayState: WeatherOverlayState) {
  if (!map || !overlayState.geojsonUrl) return
  const catalogId = overlayState.catalogId
  const srcId = weatherSourceId(catalogId)
  const fillId = weatherFillLayerId(catalogId)
  const lineId = weatherLineLayerId(catalogId)
  // 切换渲染模式时清理同 catalog 的其他图层
  const pointId = weatherPointLayerId(catalogId)
  const arrowId = weatherArrowLayerId(catalogId)
  const imgSrcId = weatherImageSourceId(catalogId)
  const rasterId = weatherRasterLayerId(catalogId)
  if (map.getLayer(rasterId)) map.removeLayer(rasterId)
  if (map.getSource(imgSrcId)) map.removeSource(imgSrcId)
  if (map.getLayer(arrowId)) map.removeLayer(arrowId)
  if (map.getLayer(pointId)) map.removeLayer(pointId)

  const existingSource = map.getSource(srcId) as GeoJSONSource | undefined
  const fillOpacity = getWeatherFillOpacity(overlayState.renderHint, overlayState.opacity)
  const lineOpacity = getWeatherLineOpacity(overlayState.renderHint, overlayState.opacity)
  const fillColor = buildWeatherFillColorExpression(overlayState.renderHint)
  const lineColor = getWeatherLineColor(overlayState.renderHint)
  if (!existingSource) {
    map.addSource(srcId, {
      type: 'geojson',
      data: overlayState.geojsonUrl,
    } as GeoJsonSourceSpecification)

    map.addLayer(
      {
        id: fillId,
        type: 'fill',
        source: srcId,
        paint: {
          'fill-color': fillColor,
          'fill-opacity': fillOpacity,
        },
      },
      map.getLayer('admin-fill') ? 'admin-fill' : undefined,
    )

    map.addLayer(
      {
        id: lineId,
        type: 'line',
        source: srcId,
        paint: {
          'line-color': lineColor,
          'line-width': 0.45,
          'line-opacity': lineOpacity,
        },
      },
      map.getLayer('admin-fill') ? 'admin-fill' : undefined,
    )
    return
  }

  existingSource.setData(overlayState.geojsonUrl)
  if (map.getLayer(fillId)) {
    map.setPaintProperty(fillId, 'fill-color', fillColor)
    map.setPaintProperty(fillId, 'fill-opacity', fillOpacity)
    map.setLayoutProperty(fillId, 'visibility', 'visible')
  }
  if (map.getLayer(lineId)) {
    map.setPaintProperty(lineId, 'line-color', lineColor)
    map.setPaintProperty(lineId, 'line-opacity', lineOpacity)
    map.setLayoutProperty(lineId, 'visibility', 'visible')
  }
}

function syncWeatherPointOverlay(overlayState: WeatherOverlayState) {
  if (!map || !overlayState.geojsonUrl) return
  const catalogId = overlayState.catalogId
  const srcId = weatherSourceId(catalogId)
  const pointId = weatherPointLayerId(catalogId)
  const arrowId = weatherArrowLayerId(catalogId)
  // 切换渲染模式时清理同 catalog 的其他图层
  const fillId = weatherFillLayerId(catalogId)
  const lineId = weatherLineLayerId(catalogId)
  const imgSrcId = weatherImageSourceId(catalogId)
  const rasterId = weatherRasterLayerId(catalogId)
  if (map.getLayer(rasterId)) map.removeLayer(rasterId)
  if (map.getSource(imgSrcId)) map.removeSource(imgSrcId)
  if (map.getLayer(lineId)) map.removeLayer(lineId)
  if (map.getLayer(fillId)) map.removeLayer(fillId)

  const existingSource = map.getSource(srcId) as GeoJSONSource | undefined
  const pointColor = buildWeatherPointColorExpression(overlayState.renderHint)
  const pointRadius = buildWeatherPointRadiusExpression(overlayState.renderHint)
  const arrowSize = buildWeatherArrowSizeExpression(overlayState.renderHint)
  const pointOpacity = getWeatherFillOpacity(overlayState.renderHint, overlayState.opacity)

  if (!existingSource) {
    map.addSource(srcId, {
      type: 'geojson',
      data: overlayState.geojsonUrl,
    } as GeoJsonSourceSpecification)

    map.addLayer({
      id: pointId,
      type: 'circle',
      source: srcId,
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
      id: arrowId,
      type: 'symbol',
      source: srcId,
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

  existingSource.setData(overlayState.geojsonUrl)
  if (map.getLayer(pointId)) {
    map.setPaintProperty(pointId, 'circle-radius', pointRadius)
    map.setPaintProperty(pointId, 'circle-color', pointColor)
    map.setPaintProperty(pointId, 'circle-opacity', Math.max(0.18, pointOpacity * 0.52))
    map.setPaintProperty(pointId, 'circle-stroke-opacity', Math.max(0.18, pointOpacity * 0.7))
  }
  if (map.getLayer(arrowId)) {
    map.setLayoutProperty(arrowId, 'text-size', ['*', 15, arrowSize])
    map.setPaintProperty(arrowId, 'text-opacity', pointOpacity)
  }
}

// ─── Wind particle flow overlay ──────────────────────────────────────────────

/**
 * 同步风场粒子流叠加层：等值线（底层） + 粒子流（中层） + 风羽符号（顶层）。
 * 类似 Windy.com 的炫酷风场渲染效果。fetch GeoJSON → 创建/更新三层 canvas。
 */
async function syncWindParticleFlow(overlayState: WeatherOverlayState) {
  if (!map) return

  // 粒子流模式不创建 maplibre source/layer（用 canvas 叠加）
  // 仅清理同 catalog 可能存在的其他 maplibre 图层
  const catalogId = overlayState.catalogId
  const fillId = weatherFillLayerId(catalogId)
  const lineId = weatherLineLayerId(catalogId)
  const pointId = weatherPointLayerId(catalogId)
  const arrowId = weatherArrowLayerId(catalogId)
  const imgSrcId = weatherImageSourceId(catalogId)
  const rasterId = weatherRasterLayerId(catalogId)
  const srcId = weatherSourceId(catalogId)
  if (map.getLayer(rasterId)) map.removeLayer(rasterId)
  if (map.getSource(imgSrcId)) map.removeSource(imgSrcId)
  if (map.getLayer(arrowId)) map.removeLayer(arrowId)
  if (map.getLayer(pointId)) map.removeLayer(pointId)
  if (map.getLayer(lineId)) map.removeLayer(lineId)
  if (map.getLayer(fillId)) map.removeLayer(fillId)
  if (map.getSource(srcId)) map.removeSource(srcId)

  // fetch GeoJSON 数据（仅当 URL 变化时重新 fetch）
  const urlChanged = lastWindGeojsonUrl !== overlayState.geojsonUrl
  let geojson: any = urlChanged ? null : currentWindGeojson
  if (urlChanged && overlayState.geojsonUrl) {
    try {
      const resp = await fetch(overlayState.geojsonUrl)
      if (resp.ok) {
        geojson = await resp.json()
        currentWindGeojson = geojson
        lastWindGeojsonUrl = overlayState.geojsonUrl
      } else {
        console.warn('[MapCanvas] Failed to fetch wind geojson:', resp.status)
        return
      }
    } catch (err) {
      console.error('[MapCanvas] Error fetching wind geojson:', err)
      return
    }
  }

  // 组件可能在 await 期间卸载（onBeforeUnmount 已将 map 置 null），需重新检查
  if (!map) return
  if (!geojson) return

  // 创建或更新三层 canvas 叠加
  if (!windContourLayer) {
    windContourLayer = new WindContourLayer(map, geojson)
  } else {
    windContourLayer.updateGeoJSON(geojson)
  }

  if (!windParticleCanvas) {
    windParticleCanvas = new WindParticleCanvas(map, geojson)
    windParticleCanvas.start()
  } else {
    windParticleCanvas.updateGeoJSON(geojson)
  }

  if (!windBarbLayer) {
    windBarbLayer = new WindBarbLayer(map, geojson)
  } else {
    windBarbLayer.updateGeoJSON(geojson)
  }
}

// ─── Tile error handling ─────────────────────────────────────────────────────

function handleTileError() {
  tileLoadRetryCount.value++
  if (tileLoadRetryCount.value > MAX_TILE_RETRIES) {
    tileLoadFailed.value = true
  }
}

function retryTileLoad() {
  tileLoadFailed.value = false
  tileLoadRetryCount.value = 0
  if (map && map.getSource(TILE_SOURCE_ID)) {
    switchTileSource(props.tileSourceId)
    if (map.getLayer(TILE_LAYER_ID) && props.tileSourceId !== 'none') {
      map.setLayoutProperty(TILE_LAYER_ID, 'visibility', 'visible')
    }
  }
}

// ─── Source transition ───────────────────────────────────────────────────────

function triggerSourceTransition() {
  if (typeof window === 'undefined') return
  isSourceTransitioning.value = true
  if (sourceTransitionTimer !== null) window.clearTimeout(sourceTransitionTimer)
  sourceTransitionTimer = window.setTimeout(() => {
    isSourceTransitioning.value = false
    sourceTransitionTimer = null
  }, 260)
}

// ─── Hotspot sync ────────────────────────────────────────────────────────────

function getVisibleHotspots() {
  const hotspots = selectedLayer.value?.hotspots ?? []
  const currentMap = map
  if (!currentMap) return hotspots

  const zoom = currentMap.getZoom()
  if (zoom < 5.4) return hotspots.slice(0, 1)
  if (zoom < 6.2) return hotspots.slice(0, 2)
  if (zoom < 7) return hotspots.slice(0, 3)
  return hotspots
}

function syncHotspotPins() {
  const currentMap = map
  if (!currentMap) return

  const visibleHotspots = getVisibleHotspots()
  emit('visibleHotspotsChange', visibleHotspots)

  if (selectedHotspotId.value && !visibleHotspots.some((hotspot) => hotspot.id === selectedHotspotId.value)) {
    selectedHotspotId.value = null
    emit('hotspotSelect', null)
  }

  // 投影所有热点到屏幕坐标
  const rawPins = visibleHotspots.map((hotspot) => {
    const point = currentMap.project([hotspot.lng, hotspot.lat])
    return {
      id: hotspot.id,
      name: hotspot.name,
      value: hotspot.value,
      x: point.x,
      y: point.y,
      selected: hotspot.id === selectedHotspotId.value,
    }
  })

  // 碰撞检测/避让：标注约 120px 宽 x 36px 高
  // 最小间距 70px：防止标注框直接重叠，同时允许轻微靠近
  const MIN_DIST = 70
  const OFFSET_STEP = 36 // 偏移步长（约一个标注高度）
  const placed: typeof rawPins = []

  // 选中的 pin 优先放置（不被偏移），然后按 y 坐标排序
  const sorted = [...rawPins].sort((a, b) => {
    if (a.selected !== b.selected) return a.selected ? -1 : 1
    return a.y - b.y
  })

  for (const pin of sorted) {
    let px = pin.x
    let py = pin.y
    let placedOk = false

    // 尝试原位 → 向下 → 向上 → 向右 → 向左
    const candidates = [
      [0, 0],
      [0, OFFSET_STEP],
      [0, -OFFSET_STEP],
      [OFFSET_STEP * 2, 0],
      [-OFFSET_STEP * 2, 0],
      [0, OFFSET_STEP * 2],
      [0, -OFFSET_STEP * 2],
    ]

    for (const [dx, dy] of candidates) {
      const cx = pin.x + dx
      const cy = pin.y + dy
      const overlaps = placed.some((p) => {
        const ddx = cx - p.x
        const ddy = cy - p.y
        return Math.sqrt(ddx * ddx + ddy * ddy) < MIN_DIST
      })
      if (!overlaps) {
        px = cx
        py = cy
        placedOk = true
        break
      }
    }

    // 即使所有候选位置都重叠，仍然保留 pin（不消失），使用最后一个候选位置
    placed.push({ ...pin, x: px, y: py })
  }

  hotspotPins.value = placed.map((pin) => ({
    id: pin.id,
    name: pin.name,
    value: pin.value,
    left: `${pin.x}px`,
    top: `${pin.y}px`,
    selected: pin.selected,
  }))
}

function scheduleHotspotSync() {
  if (!map || animationFrameId !== null) return
  animationFrameId = requestAnimationFrame(() => {
    animationFrameId = null
    syncHotspotPins()
  })
}

/** 把当前地图中心点 + 可见 bbox 同步到 layersStore，供工作流提交时使用 */
function syncMapViewportToStore() {
  if (!map) return
  const center = map.getCenter()
  // wrap 经度到 [-180, 180]，避免 renderWorldCopies 模式下中心点经度越界
  let lng = center.lng
  while (lng > 180) lng -= 360
  while (lng < -180) lng += 360
  const bounds = map.getBounds()
  // 南北极裁剪：bounds 可能超出 [-90, 90]，夹紧到合法范围
  const south = Math.max(-90, Math.min(90, bounds.getSouth()))
  const north = Math.max(-90, Math.min(90, bounds.getNorth()))
  // 经度裁剪到 [-180, 180]；renderWorldCopies 模式下 getWest/getEast 可能返回越界值
  let west = bounds.getWest()
  let east = bounds.getEast()
  // 若范围跨越整个地球（东西差 >= 360），夹紧到全球范围
  if (east - west >= 360) {
    west = -180
    east = 180
  } else {
    // wrap 到 [-180, 180]
    while (west > 180) west -= 360
    while (west < -180) west += 360
    while (east > 180) east -= 360
    while (east < -180) east += 360
    // 若 east < west（跨日界线），交换以保证 east > west
    if (east < west) {
      ;[west, east] = [east, west]
    }
  }
  layersStore.setMapViewport({ lng, lat: center.lat }, { west, south, east, north, crs: 'EPSG:4326' })
}

function focusActiveLayer() {
  if (!map) return
  const hotspots = selectedLayer.value?.hotspots ?? []
  if (hotspots.length === 0) return

  if (hotspots.length === 1) {
    const hotspot = hotspots[0]
    map.easeTo({
      center: [hotspot.lng, hotspot.lat],
      zoom: 6.6,
      duration: 650,
      essential: true,
    })
    return
  }

  const lngs = hotspots.map((hotspot) => hotspot.lng)
  const lats = hotspots.map((hotspot) => hotspot.lat)
  const bounds: [[number, number], [number, number]] = [
    [Math.min(...lngs), Math.min(...lats)],
    [Math.max(...lngs), Math.max(...lats)],
  ]

  map.fitBounds(bounds, {
    padding: { top: 120, right: 220, bottom: 120, left: 220 },
    maxZoom: 6.8,
    duration: 700,
    essential: true,
  })
}

function toggleHotspotSelection(pinId: string) {
  const nextId = selectedHotspotId.value === pinId ? null : pinId
  selectedHotspotId.value = nextId
  emit('hotspotSelect', activeLayer.value.hotspots.find((hotspot) => hotspot.id === nextId) ?? null)
}

function syncNavigationControlTheme() {
  const navButtons = mapContainer.value?.querySelectorAll('.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button')
  if (!navButtons?.length) return

  const buttonBackground =
    currentTileConfig.value.style === 'satellite' || currentTileConfig.value.style === 'terrain'
      ? 'rgba(255,255,255,0.86)'
      : 'rgba(8,18,33,0.85)'

  navButtons.forEach((button) => {
    ;(button as HTMLElement).style.backgroundColor = buttonBackground
  })
}

/** 供父组件截图使用：返回地图舞台 DOM 元素 */
function getMapStageElement(): HTMLElement | null {
  return mapStageRef.value
}

/**
 * 截图专用：在 preserveDrawingBuffer=false 下同步读取地图画面。
 * 调用 map.render() 强制刷新 WebGL 帧，紧接着同步 toDataURL() 读取 framebuffer。
 */
function captureMapCanvas(): string | null {
  if (!map) return null
  try {
    map.render()
    const canvas = map.getCanvas()
    return canvas.toDataURL('image/png')
  } catch (error) {
    console.warn('[MapCanvas] captureMapCanvas failed:', error)
    return null
  }
}

// ─── Time-of-day visual vars ─────────────────────────────────────────────────

const timeProgressPercent = computed(() => `${(props.currentHour / 23) * 100}%`)
const timeGlowOpacity = computed(() => {
  const normalized = props.currentHour / 23
  const peak = 1 - Math.abs(normalized - 0.55) / 0.55
  return (0.08 + Math.max(0, peak) * 0.18).toFixed(3)
})
const horizonPosition = computed(() => `${12 + (props.currentHour / 23) * 76}%`)
const stageBandOpacity = computed(() => {
  const normalized = props.currentHour / 23
  const peak = 1 - Math.abs(normalized - 0.58) / 0.58
  return (0.06 + Math.max(0, peak) * 0.16).toFixed(3)
})

function timeBandValue<T extends string>(hour: number, entries: Array<{ threshold: number; value: T }>): T {
  for (const { threshold, value } of entries) {
    if (hour < threshold) return value
  }
  return entries[entries.length - 1].value
}

const stageGlowSpread = computed(() =>
  timeBandValue(props.currentHour, [
    { threshold: 6, value: '16rem' },
    { threshold: 11, value: '20rem' },
    { threshold: 17, value: '24rem' },
    { threshold: 20, value: '21rem' },
    { threshold: 24, value: '17rem' },
  ]),
)
const hotspotScale = computed(() =>
  timeBandValue(props.currentHour, [
    { threshold: 6, value: '0.88' },
    { threshold: 11, value: '0.96' },
    { threshold: 17, value: '1.08' },
    { threshold: 20, value: '0.98' },
    { threshold: 24, value: '0.9' },
  ]),
)
const hotspotHaloSize = computed(() =>
  timeBandValue(props.currentHour, [
    { threshold: 6, value: '8px' },
    { threshold: 11, value: '10px' },
    { threshold: 17, value: '12px' },
    { threshold: 20, value: '10px' },
    { threshold: 24, value: '8px' },
  ]),
)
const hotspotLabelOpacity = computed(() =>
  timeBandValue(props.currentHour, [
    { threshold: 6, value: '0.82' },
    { threshold: 11, value: '0.9' },
    { threshold: 17, value: '1' },
    { threshold: 20, value: '0.92' },
    { threshold: 24, value: '0.84' },
  ]),
)

// ─── Map init ────────────────────────────────────────────────────────────────

function waitForFirstPaint() {
  return new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
}

onMounted(async () => {
  if (!mapContainer.value) return

  loadingLabel.value = '正在准备地图...'
  await waitForFirstPaint()
  loadingLabel.value = '正在加载地图引擎...'

  const { default: maplibregl } = await import('maplibre-gl')

  const mapOptions: ConstructorParameters<typeof maplibregl.Map>[0] = {
    container: mapContainer.value,
    style: {
      version: 8,
      sources: {},
      layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#07111e' } }],
    } as StyleSpecification,
    center: [113.2644, 23.1291],
    zoom: 4.8,
    pitch: 0,
    bearing: 0,
    attributionControl: false,
    // 允许全球浏览：世界在东西方向重复渲染，用户可拖动到任意经度
    renderWorldCopies: true,
    cancelPendingTileRequestsWhileZooming: false,
    refreshExpiredTiles: false,
    canvasContextAttributes: {
      // preserveDrawingBuffer=false（默认）：不回读 framebuffer，大幅提升与 Canvas 2D 叠加层的合成性能
      // 截图改用 captureMapCanvas() 在 render() 后同步读取
      preserveDrawingBuffer: false,
    },
  }

  map = new maplibregl.Map(mapOptions)

  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right')
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
  window.setTimeout(syncNavigationControlTheme, 0)

  map.on('error', (e) => {
    if (((e as any).sourceId !== TILE_SOURCE_ID && (e as any).sourceId !== undefined)) return
    const status = e.error?.status
    if (status === undefined || status === 0 || status === 403 || status === 404) {
      handleTileError()
    }
  })

  map.on('load', async () => {
    ensureTileLayer(props.tileSourceId)
    await ensureBoundaryModule()
    await ensureBoundaryLayers()
    if (map!.getLayer(TILE_LAYER_ID)) {
      map!.setLayoutProperty(TILE_LAYER_ID, 'visibility', props.tileSourceId === 'none' ? 'none' : 'visible')
    }
    syncAdminOverlay()
    syncWeatherOverlay()
    focusActiveLayer()
    scheduleHotspotSync()
    // 初始化 store 的地图视口，使首次工作流提交时能拿到正确中心点和 bbox
    syncMapViewportToStore()
    mapReady.value = true
    requestAnimationFrame(() => {
      mapVisible.value = true
      window.setTimeout(() => {
        skeletonVisible.value = false
      }, 260)
    })
  })

  map.on('movestart', () => { isMapInteracting.value = true })
  map.on('move', scheduleHotspotSync)
  map.on('moveend', () => {
    isMapInteracting.value = false
    scheduleHotspotSync()
    syncMapViewportToStore()
  })
  map.on('zoomstart', () => { isMapInteracting.value = true })
  map.on('zoom', scheduleHotspotSync)
  map.on('zoomend', () => {
    isMapInteracting.value = false
    scheduleHotspotSync()
    syncMapViewportToStore()
  })
  map.on('resize', scheduleHotspotSync)
  map.on('render', scheduleHotspotSync)
  map.on('click', (event) => {
    emit('mapPointSelect', {
      lng: event.lngLat.lng,
      lat: event.lngLat.lat,
    })
  })
})

// ─── Watchers ────────────────────────────────────────────────────────────────

watch(
  () => props.tileSourceId,
  (sourceId) => {
    if (!mapReady.value) return
    triggerSourceTransition()
    switchTileSource(sourceId)
    window.setTimeout(syncNavigationControlTheme, 0)
  },
)

// Watch layersStore for admin boundary changes
watch(
  () => [hasAdminBoundary.value, adminBoundaryOpacity.value],
  () => syncAdminOverlay(),
)

watch(
  () => [
    // 监听所有可见图层的 overlay 状态变化（多图层叠加）
    JSON.stringify(
      layersStore.activeLayersDisplay.map((l) => ({
        id: l.instanceId,
        catalogId: l.catalogId,
        visible: l.visible,
        opacity: l.opacity,
        isAdmin: l.isAdminBoundary,
        jobUpdatedAt: l.jobLayer?.updatedAt,
        paintMode: l.jobLayer?.mapLayerPayload?.renderHint?.paint_mode,
        geojsonUrl: l.jobLayer?.mapLayerPayload?.layerAssets?.geojsonUrl,
        cogPreviewUrl: l.jobLayer?.mapLayerPayload?.layerAssets?.cogPreviewUrl,
      })),
    ),
    // 粒子流启用状态
    layersStore.particleFlowCatalogId,
  ],
  () => syncWeatherOverlay(),
)

// Watch selected layer for hotspot changes
watch(
  () => [selectedLayer.value?.instanceId, selectedLayer.value?.hotspots],
  () => {
    focusActiveLayer()
    scheduleHotspotSync()
  },
)

onBeforeUnmount(() => {
  if (animationFrameId !== null) cancelAnimationFrame(animationFrameId)
  if (sourceTransitionTimer !== null && typeof window !== 'undefined') window.clearTimeout(sourceTransitionTimer)
  removeWeatherOverlay()
  map?.remove()
  map = null
})
</script>

<template>
  <section
    ref="mapStageRef"
    class="map-stage"
    :class="{
      'map-stage-interacting': isMapInteracting,
      'map-stage-transitioning': isSourceTransitioning,
      'map-stage-light': currentTileConfig.style === 'satellite' || currentTileConfig.style === 'terrain',
      'map-stage-dark': currentTileConfig.style === 'dark',
      [`map-stage-${activeLayer.availabilityState}`]: true,
    }"
    :style="{
      '--accent-color': activeLayer.accentColor,
      '--accent-glow': activeLayer.accentGlow,
      '--chip-tone': activeLayer.chipTone,
      '--time-progress': timeProgressPercent,
      '--time-glow-opacity': timeGlowOpacity,
      '--horizon-position': horizonPosition,
      '--stage-band-opacity': stageBandOpacity,
      '--stage-glow-spread': stageGlowSpread,
      '--hotspot-scale': hotspotScale,
      '--hotspot-halo-size': hotspotHaloSize,
      '--hotspot-label-opacity': hotspotLabelOpacity,
    }"
  >
    <div ref="mapContainer" class="map-host" :class="{ visible: mapVisible }"></div>

    <!-- Skeleton -->
    <div class="map-skeleton" :class="{ hidden: !skeletonVisible }" aria-hidden="true">
      <div class="skeleton-sweep"></div>
      <div class="skeleton-node skeleton-node-a"></div>
      <div class="skeleton-node skeleton-node-b"></div>
      <div class="skeleton-strip skeleton-strip-a"></div>
      <div class="skeleton-strip skeleton-strip-b"></div>
    </div>

    <!-- Atmosphere layers -->
    <div class="map-fog"></div>
    <div class="basemap-transition-mask"></div>
    <div class="time-sheen"></div>
    <div class="time-band"></div>
    <div class="weather-overlay"></div>
    <div class="grid-overlay"></div>

    <!-- Loading indicator -->
    <div v-if="!mapReady" class="map-loading">
      <span class="loading-dot"></span>
      <span>{{ loadingLabel }}</span>
    </div>

    <!-- Tile error banner -->
    <div v-if="tileLoadFailed" class="tile-load-error">
      <span class="tile-error-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      </span>
      <span>瓦片加载失败</span>
      <button class="tile-retry-btn" @click="retryTileLoad">重试</button>
    </div>

    <!-- Map chips -->
    <div class="map-overlay">
      <span class="chip">
        {{ currentTileConfig.provider }} · {{ currentTileConfig.label }}
      </span>
      <span class="chip">{{ hourLabel }}</span>
      <span class="chip secondary">{{ activeLayer.name }}</span>
      <span class="chip" :class="`chip-${activeLayer.availabilityState}`">
        {{ activeLayer.availabilityLabel }}
      </span>
    </div>

    <!-- Layer info card -->
    <div class="map-note">
      <h2>{{ activeLayer.name }}</h2>
      <p>{{ activeLayer.trendLabel }}</p>
      <span class="map-note-meta">{{ activeLayer.observationTimeLabel }} · {{ activeLayer.availabilityLabel }}</span>
      <div class="time-indicator" aria-hidden="true">
        <div class="time-indicator-fill"></div>
      </div>
    </div>

    <!-- Hotspot pins -->
    <div class="hotspot-layer" :class="`hotspot-layer-${activeLayer.availabilityState}`" aria-hidden="true">
      <button
        v-for="pin in hotspotPins"
        :key="pin.id"
        class="hotspot-pin"
        :class="{ selected: pin.selected }"
        :style="{ left: pin.left, top: pin.top }"
        type="button"
        @click="toggleHotspotSelection(pin.id)"
      >
        <div class="hotspot-core"></div>
        <div class="hotspot-label">
          <strong>{{ pin.name }}</strong>
          <span>{{ pin.value }}</span>
        </div>
      </button>
    </div>
  </section>
</template>

<style scoped>
.map-stage {
  position: relative;
  min-height: calc(100vh - 1.5rem);
  overflow: hidden;
  border-radius: 1.4rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  background:
    radial-gradient(circle at top, rgba(66, 130, 255, 0.14), transparent 28rem),
    linear-gradient(180deg, rgba(6, 14, 26, 0.98), rgba(10, 19, 35, 0.94));
  /* 性能优化：contained paint layer */
  contain: layout style paint;
}

.map-host,
.map-fog,
.weather-overlay,
.grid-overlay,
.hotspot-layer {
  position: absolute;
  inset: 0;
}

.map-host {
  z-index: 0;
  opacity: 0.01;
  transition: opacity 0.45s ease;
}

.map-host.visible {
  opacity: 1;
}

.map-skeleton {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at 28% 36%, rgba(87, 166, 255, 0.18), transparent 16rem),
    linear-gradient(180deg, rgba(7, 16, 29, 0.98), rgba(10, 19, 35, 0.95));
  opacity: 1;
  transition: opacity 0.35s ease;
}

.map-skeleton.hidden {
  opacity: 0;
  pointer-events: none;
}

.map-skeleton.hidden .skeleton-sweep {
  animation-play-state: paused;
}

.skeleton-sweep,
.skeleton-node,
.skeleton-strip {
  position: absolute;
}

.skeleton-sweep {
  position: absolute;
  inset: 0;
  background: linear-gradient(110deg, transparent 26%, rgba(255, 255, 255, 0.08) 50%, transparent 74%);
  transform: translateX(-100%);
  animation: sweep 2.4s linear infinite;
  /* 性能优化：GPU 加速 */
  will-change: transform;
}

.skeleton-node {
  width: 0.9rem;
  height: 0.9rem;
  border-radius: 999px;
  background: rgba(138, 198, 255, 0.34);
  box-shadow: 0 0 0 10px rgba(82, 134, 255, 0.08);
}

.skeleton-node-a { top: 34%; left: 28%; }
.skeleton-node-b { top: 56%; left: 64%; }

.skeleton-strip {
  height: 0.7rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
}

.skeleton-strip-a { left: 1rem; bottom: 5rem; width: 10rem; }
.skeleton-strip-b { right: 1rem; bottom: 4.9rem; width: 7.6rem; }

.map-fog {
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(circle at 20% 18%, rgba(3, 12, 24, 0.06), transparent 18rem),
    linear-gradient(180deg, rgba(4, 11, 20, 0.01), rgba(4, 11, 20, 0.24));
}

.basemap-transition-mask {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  opacity: 0;
  background:
    radial-gradient(circle at 50% 48%, rgba(125, 192, 255, 0.08), transparent 18rem),
    linear-gradient(180deg, rgba(4, 11, 20, 0.08), rgba(4, 11, 20, 0.14));
  /* 性能优化：GPU 加速，仅 opacity 使用过渡 */
  transform: translateZ(0);
  will-change: opacity;
  transition: opacity 0.22s ease;
}

.time-sheen {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(
      circle at var(--horizon-position) 18%,
      rgba(255, 196, 120, var(--time-glow-opacity)),
      transparent 20rem
    ),
    linear-gradient(
      180deg,
      rgba(255, 181, 107, calc(var(--time-glow-opacity) * 0.35)) 0%,
      transparent 38%
    );
  /* 性能优化：GPU 加速，仅 opacity 使用过渡 */
  transform: translateZ(0);
  will-change: opacity;
  transition: opacity 0.35s ease;
}

.time-band {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(
      circle at var(--horizon-position) 72%,
      rgba(100, 140, 220, 0.18),
      transparent var(--stage-glow-spread)
    ),
    linear-gradient(
      180deg,
      transparent 58%,
      rgba(255, 255, 255, calc(var(--stage-band-opacity) * 0.16)) 100%
    );
  /* 性能优化：GPU 加速，仅 opacity 使用过渡 */
  transform: translateZ(0);
  will-change: opacity;
  opacity: 0.92;
  transition: opacity 0.35s ease;
}

.weather-overlay {
  z-index: 1;
  pointer-events: none;
  opacity: 0.24;
  background:
    radial-gradient(circle at 18% 30%, rgba(82, 134, 255, 0.12), transparent 18rem),
    radial-gradient(circle at 78% 24%, rgba(82, 134, 255, 0.12), transparent 20rem),
    radial-gradient(circle at 52% 72%, rgba(255, 255, 255, 0.06), transparent 16rem);
  /* 性能优化：移除 filter blur，改用背景渐变透明度，GPU 加速 */
  transform: translateZ(0);
  will-change: opacity;
}

.grid-overlay {
  z-index: 1;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 72px 72px;
  mask-image: linear-gradient(180deg, transparent, rgba(0, 0, 0, 0.6) 18%, rgba(0, 0, 0, 0.92));
  will-change: opacity;
}

.map-stage-interacting .weather-overlay,
.map-stage-interacting .time-sheen,
.map-stage-interacting .time-band,
.map-stage-interacting .grid-overlay {
  opacity: 0.08;
}

.map-stage-interacting .hotspot-layer {
  opacity: 0.4;
}

.map-stage-transitioning .basemap-transition-mask {
  opacity: 1;
}

.map-stage-transitioning .map-host {
  filter: saturate(0.92) brightness(0.92);
}

.map-stage-ready .weather-overlay { opacity: 0.28; }
.map-stage-ready .time-sheen { opacity: 1; }
.map-stage-ready .time-band { opacity: 1; }
.map-stage-partial .weather-overlay { opacity: 0.16; }
.map-stage-partial .grid-overlay { opacity: 0.32; }
.map-stage-empty .map-fog { background: radial-gradient(circle at 20% 18%, rgba(3, 12, 24, 0.12), transparent 18rem), linear-gradient(180deg, rgba(4, 11, 20, 0.08), rgba(4, 11, 20, 0.34)); }
.map-stage-empty .time-sheen { opacity: 0.38; }
.map-stage-empty .time-band { opacity: 0.46; }
.map-stage-empty .weather-overlay { opacity: 0.08; }
.map-stage-empty .grid-overlay { opacity: 0.2; }

.map-overlay {
  position: absolute;
  z-index: 21;
  top: 0;
  left: 0;
  right: auto;
  display: flex;
  gap: 0.38rem;
  flex-wrap: wrap;
  padding: 0.8rem 0.8rem 0;
  box-sizing: border-box;
  align-content: flex-start;
}

.chip {
  padding: 0.24rem 0.48rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.52);
  border: 1px solid rgba(136, 192, 255, 0.12);
  color: #eff7ff;
  font-size: 0.64rem;
}

.chip.secondary {
  color: #eaf7ff;
  border-color: rgba(90, 162, 255, 0.36);
  background: rgba(36, 90, 170, 0.16);
}

.chip-ready { color: #9ff8cf; border-color: rgba(114, 255, 207, 0.2); background: rgba(114, 255, 207, 0.08); }
.chip-partial { color: #ffd38a; border-color: rgba(255, 196, 120, 0.18); background: rgba(255, 196, 120, 0.08); }
.chip-empty { color: #d7c1ff; border-color: rgba(187, 137, 255, 0.18); background: rgba(187, 137, 255, 0.08); }

.map-note {
  position: absolute;
  z-index: 18;
  left: 1rem;
  bottom: 3.15rem;
  max-width: 13rem;
  display: grid;
  gap: 0.2rem;
  padding: 0.46rem 0.54rem;
  border-radius: 0.82rem;
  background: rgba(8, 18, 33, 0.72);
  border: 1px solid rgba(90, 162, 255, 0.12);
}

.map-note h2 { margin: 0; font-size: 0.76rem; color: #f3fbff; }
.map-note p { margin: 0; color: #96a8bb; font-size: 0.64rem; line-height: 1.32; }
.map-note-meta { color: #bfd3e6; font-size: 0.58rem; letter-spacing: 0.02em; }

.time-indicator {
  position: relative;
  height: 0.24rem;
  margin-top: 0.16rem;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.08);
}

.time-indicator-fill {
  width: var(--time-progress);
  height: 100%;
  border-radius: inherit;
  background: rgba(90, 106, 128, 0.25);
}

.hotspot-layer { z-index: 2; pointer-events: none; }
.hotspot-layer-ready .hotspot-pin { opacity: 1; }
.hotspot-layer-partial .hotspot-pin { opacity: 0.76; }
.hotspot-layer-empty .hotspot-pin { opacity: 0.38; }

.hotspot-pin {
  position: absolute;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0;
  border: none;
  background: transparent;
  appearance: none;
  pointer-events: auto;
  cursor: pointer;
  /* 性能优化：GPU 加速，仅 opacity 使用过渡 */
  will-change: opacity;
  transition: opacity 0.28s ease;
}

.hotspot-core {
  width: 0.74rem;
  height: 0.74rem;
  border-radius: 999px;
  background: var(--accent-color);
  transform: translateZ(0) scale(var(--hotspot-scale));
  box-shadow:
    0 0 0 0 rgba(255, 255, 255, 0.08),
    0 0 0 var(--hotspot-halo-size) rgba(90, 106, 128, 0.3);
  /* 性能优化：仅 GPU 属性过渡 */
  transition: transform 0.28s cubic-bezier(0.25, 0.46, 0.45, 0.94), box-shadow 0.28s ease;
}

.hotspot-label {
  margin-top: 0.4rem;
  padding: 0.32rem 0.42rem;
  border-radius: 0.8rem;
  background: rgba(4, 12, 23, 0.72);
  border: 1px solid rgba(136, 192, 255, 0.14);
  color: #e8f3fc;
  white-space: nowrap;
  box-shadow: 0 10px 18px rgba(1, 8, 16, 0.18);
  opacity: var(--hotspot-label-opacity);
  will-change: opacity;
  transition: opacity 0.28s ease;
  transform: translateZ(0);
}

.map-loading {
  position: absolute;
  inset: auto auto 1rem 1rem;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.5rem 0.72rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.88);
  border: 1px solid rgba(136, 192, 255, 0.16);
  color: #dfeefd;
  font-size: 0.74rem;
}

.loading-dot {
  width: 0.48rem;
  height: 0.48rem;
  border-radius: 999px;
  background: var(--accent-color);
  box-shadow: 0 0 0 6px rgba(90, 106, 128, 0.13);
}

.tile-load-error {
  position: absolute;
  top: 110px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.38rem 0.6rem 0.38rem 0.5rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.92);
  border: 1px solid rgba(255, 100, 100, 0.28);
  color: #ffb3b3;
  font-size: 0.64rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.24);
}

.tile-error-icon { display: flex; align-items: center; color: #ff9090; }

.tile-retry-btn {
  margin-left: 0.18rem;
  padding: 0.18rem 0.46rem;
  border-radius: 999px;
  border: 1px solid rgba(255, 140, 140, 0.3);
  background: rgba(255, 80, 80, 0.12);
  color: #ffc0c0;
  font-size: 0.6rem;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease;
}

.tile-retry-btn:hover {
  background: rgba(255, 80, 80, 0.22);
  color: #fff0f0;
}

.hotspot-label strong,
.hotspot-label span {
  display: block;
}
.hotspot-label strong { font-size: 0.64rem; }
.hotspot-label span { margin-top: 0.15rem; color: #99afc3; font-size: 0.6rem; }

:deep(.maplibregl-ctrl-bottom-right) {
  right: 0.8rem;
  bottom: 0.8rem;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.28rem;
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group) {
  display: flex;
  flex-direction: column;
  border-radius: 0.7rem;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(3, 10, 20, 0.18);
  background: rgba(8, 18, 33, 0.9);
  border: 1px solid rgba(136, 192, 255, 0.12);
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button) {
  width: 2rem;
  height: 2rem;
  background: transparent;
  border: none;
  color: #dbe8f5;
  box-shadow: none;
  border-radius: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: #f4fbff;
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button + button) {
  border-top: 1px solid rgba(136, 192, 255, 0.08);
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button .maplibregl-ctrl-icon) {
  filter: brightness(1.15) contrast(1.05);
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group),
.map-stage-light :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  background: rgba(8, 18, 33, 0.92);
  border-color: rgba(136, 192, 255, 0.12);
  box-shadow: 0 8px 24px rgba(3, 10, 20, 0.18);
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button),
.map-stage-light :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  color: #eaf3fb;
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button .maplibregl-ctrl-icon) {
  filter: brightness(1.15) contrast(1.08);
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  color: #eaf3fb;
}

.map-stage-dark :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group),
.map-stage-dark :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(18, 28, 44, 0.14);
  box-shadow: 0 8px 24px rgba(3, 10, 20, 0.16);
}

.map-stage-dark :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button),
.map-stage-dark :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  color: #203040;
}

.map-stage-dark :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button:hover) {
  background: rgba(24, 80, 160, 0.12);
  color: #10233a;
}

.map-stage-dark :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button .maplibregl-ctrl-icon) {
  filter: brightness(0.42) contrast(1.15);
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-scale) {
  border-radius: 0.6rem;
  border: none;
  background: rgba(8, 18, 33, 0.9);
  color: #eaf3fb;
  font-size: 0.64rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 0.32rem 0.6rem;
  box-shadow: 0 8px 24px rgba(3, 10, 20, 0.18);
  box-sizing: border-box;
}
:deep(.maplibregl-ctrl-attrib) { background: rgba(255, 255, 255, 0.8); }

@keyframes sweep { to { transform: translateX(100%); } }

@media (max-width: 820px) {
  .map-stage { min-height: calc(100vh - 1rem); }
  .map-overlay { top: 0; left: 0; padding: 0.75rem 0.75rem 0; }
  .map-note { left: 0.75rem; right: 0.75rem; bottom: 8.3rem; max-width: none; }
  :deep(.maplibregl-ctrl-bottom-left) { left: 0.75rem; bottom: 0.75rem; }
  :deep(.maplibregl-ctrl-bottom-right) { right: 0.75rem; bottom: 0.75rem; }
}
</style>
