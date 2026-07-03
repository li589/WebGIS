import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { resolveDemoLayer } from '../app/demo-adapter'
import { demoLayerCatalog, type DemoLayer } from '../app/demo-data'

// ─── Tile source types ──────────────────────────────────────────────────────

/** 底图风格分类（决定 UI 中的分组与图标） */
export type BasemapStyle = 'none' | 'satellite' | 'street' | 'dark' | 'terrain' | 'topo'

/** 坐标系类型 */
export type CoordinateSystem = 'EPSG:3857' | 'GCJ-02' | 'BD-09'

/** 瓦片源标识符 */
export type TileSourceId =
  // No basemap (pure overlay)
  | 'none'
  // ESRI
  | 'esri-satellite' | 'esri-street' | 'esri-dark' | 'esri-navigation'
  // Google
  | 'google-satellite' | 'google-terrain'
  // Bing
  | 'bing-road' | 'bing-aerial' | 'bing-dark'
  // OSM
  | 'osm-standard' | 'osm-cycle' | 'osm-transport'
  // Non-standard (requires backend coordinate transform)
  | 'tianditu-img' | 'tianditu-vec' | 'baidu-standard' | 'gaode-standard'

export interface TileSourceConfig {
  id: TileSourceId
  /** 显示名称 */
  label: string
  /** 风格分类 */
  style: BasemapStyle
  /** 瓦片源提供商 */
  provider: string
  /** 坐标系（标准 EPSG:3857 可直接叠加数据；GCJ-02/BD-09 需后端转换） */
  coordSys: CoordinateSystem
  /** Mapbox/Maptiler 风格 URL 模板，{x}/{y}/{z} 占位符 */
  urlTemplate: string
  tileSize?: number
  attribution: string
  /** 色彩调整：饱和度 */
  saturation: number
  /** 色彩调整：亮度 */
  brightness: number
  /** 色彩调整：对比度 */
  contrast: number
  /** 是否需要后端坐标转换才能叠加数据 */
  needsBackendTransform: boolean
  /** 是否为标准瓦片源（前端可直接使用） */
  isStandard: boolean
}

// ─── All tile sources ────────────────────────────────────────────────────────

export const TILE_SOURCES: TileSourceConfig[] = [
  // ── No basemap (pure overlay mode) ─────────────────────────────────────────
  {
    id: 'none',
    label: '无底图',
    style: 'none',
    provider: '—',
    coordSys: 'EPSG:3857',
    urlTemplate: '',
    attribution: '',
    saturation: 0,
    brightness: 0,
    contrast: 0,
    needsBackendTransform: false,
    isStandard: true,
  },

  // ── ESRI ──────────────────────────────────────────────────────────────────
  {
    id: 'esri-satellite',
    label: 'ESRI 影像',
    style: 'satellite',
    provider: 'ESRI',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    tileSize: 256,
    attribution: '&copy; Esri, USGS, NGA, NASA, CGIAR, N Robinson, NCEAS, NLS, OS, NMA, Geodatastyrelsen, GSA, GADM, GIS User Community',
    saturation: 0,
    brightness: 0,
    contrast: 0,
    needsBackendTransform: false,
    isStandard: true,
  },
  {
    id: 'esri-street',
    label: 'ESRI 街道',
    style: 'street',
    provider: 'ESRI',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
    tileSize: 256,
    attribution: '&copy; Esri, DeLorme, USGS, Intermap, iPC, NRCAN, GeoBase, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China (Hong Kong), and the GIS User Community',
    saturation: -0.05,
    brightness: 0,
    contrast: 0.05,
    needsBackendTransform: false,
    isStandard: true,
  },
  {
    id: 'esri-dark',
    label: 'ESRI 深色',
    style: 'dark',
    provider: 'ESRI',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    tileSize: 256,
    attribution: '&copy; Esri, HERE, Garmin, FAO, NOAA, USGS, Intermap, iPC, NRCAN, GeoBase, Kadaster NL, Ordnance Survey',
    saturation: -0.15,
    brightness: 0.08,
    contrast: 0.1,
    needsBackendTransform: false,
    isStandard: true,
  },
  {
    id: 'esri-navigation',
    label: 'ESRI 航海',
    style: 'street',
    provider: 'ESRI',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Navigation_Charts/MapServer/tile/{z}/{y}/{x}',
    tileSize: 256,
    attribution: '&copy; Esri, NOAA, NGS, other contributors',
    saturation: 0.05,
    brightness: -0.02,
    contrast: 0.08,
    needsBackendTransform: false,
    isStandard: true,
  },

  // ── Google ─────────────────────────────────────────────────────────────────
  {
    id: 'google-satellite',
    label: 'Google 影像',
    style: 'satellite',
    provider: 'Google',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://khms.google.com/kh/v=950?x={x}&y={y}&z={z}',
    tileSize: 256,
    attribution: '&copy; Google',
    saturation: 0.05,
    brightness: 0,
    contrast: 0,
    needsBackendTransform: false,
    isStandard: true,
  },
  {
    id: 'google-terrain',
    label: 'Google 地形',
    style: 'terrain',
    provider: 'Google',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',
    tileSize: 256,
    attribution: '&copy; Google',
    saturation: -0.1,
    brightness: 0.04,
    contrast: 0.08,
    needsBackendTransform: false,
    isStandard: true,
  },

  // ── Bing（使用 Maptiler 公开镜像，标准 XYZ 瓦片） ─────────────────────────
  {
    id: 'bing-road',
    label: 'Bing 街道',
    style: 'street',
    provider: 'Bing',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://cdn.maptiler.com/maps/bing/style=road&key=<YOUR_MAPTILER_KEY>/{z}/{x}/{y}.png',
    tileSize: 256,
    attribution: '&copy; Microsoft, TomTom, GeoSmart',
    saturation: 0,
    brightness: 0,
    contrast: 0.05,
    needsBackendTransform: false,
    isStandard: true,
  },
  {
    id: 'bing-aerial',
    label: 'Bing 影像',
    style: 'satellite',
    provider: 'Bing',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://cdn.maptiler.com/maps/bing/style=aerial&key=<YOUR_MAPTILER_KEY>/{z}/{x}/{y}.jpg',
    tileSize: 256,
    attribution: '&copy; Microsoft, USDA Farm Service Agency',
    saturation: 0.05,
    brightness: 0,
    contrast: 0,
    needsBackendTransform: false,
    isStandard: true,
  },
  {
    id: 'bing-dark',
    label: 'Bing 深色',
    style: 'dark',
    provider: 'Bing',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://cdn.maptiler.com/maps/bing/style=dark&key=<YOUR_MAPTILER_KEY>/{z}/{x}/{y}.png',
    tileSize: 256,
    attribution: '&copy; Microsoft',
    saturation: -0.2,
    brightness: 0.1,
    contrast: 0.12,
    needsBackendTransform: false,
    isStandard: true,
  },

  // ── OSM ────────────────────────────────────────────────────────────────────
  {
    id: 'osm-standard',
    label: 'OSM 标准',
    style: 'street',
    provider: 'OSM',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    tileSize: 256,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    saturation: -0.08,
    brightness: 0,
    contrast: 0.08,
    needsBackendTransform: false,
    isStandard: true,
  },
  {
    id: 'osm-cycle',
    label: 'OSM 骑行',
    style: 'street',
    provider: 'OSM',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    tileSize: 256,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    saturation: -0.1,
    brightness: 0.02,
    contrast: 0.06,
    needsBackendTransform: false,
    isStandard: true,
  },
  {
    id: 'osm-transport',
    label: 'OSM 交通',
    style: 'street',
    provider: 'OSM',
    coordSys: 'EPSG:3857',
    urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    tileSize: 256,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    saturation: 0,
    brightness: -0.02,
    contrast: 0.1,
    needsBackendTransform: false,
    isStandard: true,
  },

  // ── Non-standard (requires backend coordinate transform) ────────────────────
  {
    id: 'tianditu-img',
    label: '天地图 影像',
    style: 'satellite',
    provider: '天地图',
    coordSys: 'GCJ-02',
    urlTemplate: 'https://t0.tianditu.gov.cn/img_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=img&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=YOUR_TIANDITU_TK_HERE',
    tileSize: 256,
    attribution: '&copy; <a href="https://www.tianditu.gov.cn">天地图</a>',
    saturation: 0,
    brightness: 0,
    contrast: 0.05,
    needsBackendTransform: true,
    isStandard: false,
  },
  {
    id: 'tianditu-vec',
    label: '天地图 矢量',
    style: 'street',
    provider: '天地图',
    coordSys: 'GCJ-02',
    urlTemplate: 'https://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=YOUR_TIANDITU_TK_HERE',
    tileSize: 256,
    attribution: '&copy; <a href="https://www.tianditu.gov.cn">天地图</a>',
    saturation: 0,
    brightness: 0,
    contrast: 0.05,
    needsBackendTransform: true,
    isStandard: false,
  },
  {
    id: 'baidu-standard',
    label: '百度 街道',
    style: 'street',
    provider: '百度',
    coordSys: 'BD-09',
    urlTemplate: 'https://maponline3.bdimg.com/styemap/{z}/{x}/{y}.png',
    tileSize: 256,
    attribution: '&copy; <a href="https://map.baidu.com">百度地图</a>',
    saturation: 0.05,
    brightness: 0.02,
    contrast: 0.05,
    needsBackendTransform: true,
    isStandard: false,
  },
  {
    id: 'gaode-standard',
    label: '高德 街道',
    style: 'street',
    provider: '高德',
    coordSys: 'GCJ-02',
    urlTemplate: 'https://webst0.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
    tileSize: 256,
    attribution: '&copy; <a href="https://www.amap.com">高德地图</a>',
    saturation: -0.05,
    brightness: 0,
    contrast: 0.08,
    needsBackendTransform: true,
    isStandard: false,
  },
]

/** 按风格分类的瓦片源映射（仅包含标准瓦片源） */
export const TILE_SOURCES_BY_STYLE = (() => {
  const map = new Map<BasemapStyle, TileSourceConfig[]>()
  for (const source of TILE_SOURCES) {
    if (!map.has(source.style)) {
      map.set(source.style, [])
    }
    map.get(source.style)!.push(source)
  }
  return map
})()

/** 瓦片源 ID → 配置映射 */
export const TILE_SOURCE_MAP = new Map<TileSourceId, TileSourceConfig>(
  TILE_SOURCES.map((s) => [s.id, s]),
)

// ─── LocalStorage helpers ────────────────────────────────────────────────────

function readStoredValue(key: string, fallback: string): string
function readStoredValue(key: string, fallback: boolean): boolean
function readStoredValue(key: string, fallback: string | boolean): string | boolean {
  if (typeof window === 'undefined') {
    return fallback
  }

  const value = window.localStorage.getItem(key)
  return value !== null ? (typeof fallback === 'boolean' ? value === 'true' : value) : fallback
}

function writeStoredValue(key: string, value: string | boolean) {
  if (typeof window === 'undefined') {
    return
  }

  window.localStorage.setItem(key, String(value))
}

function normalizeHour(value: number) {
  const wrappedHour = ((value % 24) + 24) % 24
  return Math.round(wrappedHour * 100) / 100
}

function formatHourLabel(hour: number) {
  const wholeHours = Math.floor(hour)
  const minutes = Math.round((hour - wholeHours) * 60)
  return `${String(wholeHours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
}

// ─── Store ───────────────────────────────────────────────────────────────────

/** 默认底图源：ESRI 街道图 */
const DEFAULT_TILE_SOURCE: TileSourceId = 'esri-street'

export const useUiStore = defineStore('ui', () => {
  const tileSourceId = ref<TileSourceId>(readStoredValue('ui:tile-source', DEFAULT_TILE_SOURCE) as TileSourceId)
  /** 行政区边界叠加层开关 */
  const showAdminOverlay = ref<boolean>(readStoredValue('ui:admin-overlay', 'true') === 'true')
  /** 行政区叠加层不透明度（0-1） */
  const adminOverlayOpacity = ref<number>(0.32)
  const activeLayerId = ref(readStoredValue('ui:active-layer-id', demoLayerCatalog[0].id))
  const currentHour = ref(normalizeHour(Number(readStoredValue('ui:hour', '12'))))

  const hourLabel = computed(() => formatHourLabel(currentHour.value))
  const activeLayer = computed<DemoLayer>(() => resolveDemoLayer(activeLayerId.value, currentHour.value))
  const currentTileSource = computed(() => TILE_SOURCE_MAP.get(tileSourceId.value) ?? TILE_SOURCE_MAP.get(DEFAULT_TILE_SOURCE)!)

  function setTileSource(sourceId: TileSourceId) {
    tileSourceId.value = sourceId
    writeStoredValue('ui:tile-source', sourceId)
  }

  function setAdminOverlay(visible: boolean) {
    showAdminOverlay.value = visible
    writeStoredValue('ui:admin-overlay', String(visible))
  }

  function setAdminOverlayOpacity(opacity: number) {
    adminOverlayOpacity.value = Math.max(0, Math.min(1, opacity))
  }

  function setLayer(layerId: string) {
    activeLayerId.value = layerId
    writeStoredValue('ui:active-layer-id', layerId)
  }

  function setHour(nextHour: number) {
    const wrappedHour = normalizeHour(nextHour)
    currentHour.value = wrappedHour
    writeStoredValue('ui:hour', String(wrappedHour))
  }

  function stepHour(delta: number) {
    setHour(currentHour.value + delta)
  }

  return {
    tileSourceId,
    currentTileSource,
    showAdminOverlay,
    adminOverlayOpacity,
    activeLayerId,
    activeLayer,
    currentHour,
    hourLabel,
    setTileSource,
    setAdminOverlay,
    setAdminOverlayOpacity,
    setLayer,
    setHour,
    stepHour,
  }
})
