import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type MapMode = '2d' | '3d'
export type BasemapStyle = 'none' | 'street' | 'satellite' | 'dark' | 'terrain'
export type TileSourceId =
  | 'none'
  | 'esri-street'       // Esri 世界街道
  | 'esri-imagery'      // Esri 世界影像
  | 'esri-terrain'      // Esri 地形
  | 'osm-standard'       // OSM 标准
  | 'osm-hot'           // OSM 人道主义
  | 'carto-light'       // CARTO 亮色
  | 'carto-dark'        // CARTO 深色
  | 'stadia-streets'    // Stadia 街道
  | 'stadia-dark'       // Stadia 深色
  | 'stadia-satellite'   // Stadia 卫星
  | 'bing-road'         // Bing 道路
  | 'bing-aerial'       // Bing 航空
  | 'bing-dark'         // Bing 深色
  | 'gaode-street'      // 高德街道（需代理）
  | 'gaode-satellite'   // 高德卫星（需代理）
  | 'tianditu-img'      // 天地图影像（需代理）
  | 'tianditu-label'    // 天地图标注（需代理）
  | 'baidu-street'      // 百度街道（需代理）
  | 'baidu-satellite'   // 百度卫星（需代理）

export interface TileSourceConfig {
  id: TileSourceId
  label: string
  provider: string
  style: BasemapStyle
  urlTemplate: string
  attribution?: string
  tileSize?: number
  saturation: number
  brightness: number
  contrast: number
  isStandard: boolean
  needsBackendTransform: boolean
}

// 图层类型
export type LayerType = 'raster' | 'vector' | 'point' | 'polygon' | 'heatmap' | 'wind'

// 图层接口
export interface Layer {
  id: string
  name: string
  type: LayerType
  visible: boolean
  opacity: number // 0-1
  color?: string // 可选的颜色配置
  description?: string
}

// 图例项接口
export interface LegendItem {
  color: string
  label: string
  value?: number
}

// 图例配置接口
export interface LegendConfig {
  title: string
  unit: string
  type: 'continuous' | 'discrete' // 连续色带 或 离散颜色
  min: number
  max: number
  items?: LegendItem[] // 离散颜色使用
  gradient?: string[] // 连续色带使用
}

export const TILE_SOURCES: TileSourceConfig[] = [
  // 空白底图
  {
    id: 'none',
    label: '空白',
    provider: 'None',
    style: 'none',
    urlTemplate: '',
    saturation: 0,
    brightness: 0,
    contrast: 0,
    isStandard: true,
    needsBackendTransform: false,
  },

  // ===== Esri 系列 =====
  {
    id: 'esri-street',
    label: 'Esri 世界街道',
    provider: 'Esri',
    style: 'street',
    urlTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri',
    tileSize: 256,
    saturation: -0.08,
    brightness: 0.02,
    contrast: 0.08,
    isStandard: true,
    needsBackendTransform: false,
  },
  {
    id: 'esri-imagery',
    label: 'Esri 世界影像',
    provider: 'Esri',
    style: 'satellite',
    urlTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri',
    tileSize: 256,
    saturation: 0.04,
    brightness: 0.03,
    contrast: 0.1,
    isStandard: true,
    needsBackendTransform: false,
  },
  {
    id: 'esri-terrain',
    label: 'Esri 地形',
    provider: 'Esri',
    style: 'terrain',
    urlTemplate: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Esri',
    tileSize: 256,
    saturation: -0.1,
    brightness: 0.02,
    contrast: 0.12,
    isStandard: true,
    needsBackendTransform: false,
  },

  // ===== OSM 系列 =====
  {
    id: 'osm-standard',
    label: 'OSM 标准',
    provider: 'OSM',
    style: 'street',
    // 注意：OSM 标准服务器国内访问可能不稳定
    urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
    tileSize: 256,
    saturation: 0,
    brightness: 0,
    contrast: 0.02,
    isStandard: true,
    needsBackendTransform: false,
  },
  {
    id: 'osm-hot',
    label: 'OSM 人道主义',
    provider: 'OSM-FR',
    style: 'street',
    // OSM France 人道主义地图 - 国内可访问
    urlTemplate: 'https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
    tileSize: 256,
    saturation: -0.05,
    brightness: 0,
    contrast: 0.05,
    isStandard: true,
    needsBackendTransform: false,
  },

  // ===== CARTO 系列 =====
  {
    id: 'carto-light',
    label: 'CARTO 亮色',
    provider: 'CARTO',
    style: 'street',
    // CARTO Light - 备用
    urlTemplate: 'https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
    attribution: 'CARTO',
    tileSize: 256,
    saturation: -0.05,
    brightness: 0.02,
    contrast: 0.08,
    isStandard: true,
    needsBackendTransform: false,
  },
  {
    id: 'carto-dark',
    label: 'CARTO 深色',
    provider: 'CARTO',
    style: 'dark',
    // CARTO Dark - 备用深色底图
    urlTemplate: 'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
    attribution: 'CARTO',
    tileSize: 256,
    saturation: -0.2,
    brightness: -0.04,
    contrast: 0.16,
    isStandard: true,
    needsBackendTransform: false,
  },

  // ===== Stadia 系列 =====
  {
    id: 'stadia-streets',
    label: 'Stadia 街道',
    provider: 'Stadia',
    style: 'street',
    // Stadia Streets - 需 API Key（使用公共示例）
    urlTemplate: 'https://tiles.stadiamaps.com/tiles/stamen_toner/{z}/{x}/{y}.png',
    attribution: '© Stadia Maps',
    tileSize: 256,
    saturation: 0,
    brightness: 0,
    contrast: 0.05,
    isStandard: true,
    needsBackendTransform: false,
  },
  {
    id: 'stadia-dark',
    label: 'Stadia 深色',
    provider: 'Stadia',
    style: 'dark',
    // Stadia Dark
    urlTemplate: 'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}.png',
    attribution: '© Stadia Maps',
    tileSize: 256,
    saturation: -0.15,
    brightness: -0.08,
    contrast: 0.1,
    isStandard: true,
    needsBackendTransform: false,
  },
  {
    id: 'stadia-satellite',
    label: 'Stadia 卫星',
    provider: 'Stadia',
    style: 'satellite',
    // Stadia Satellite (via Stamen)
    urlTemplate: 'https://tiles.stadiamaps.com/tiles/stamen_toner_satellite/{z}/{x}/{y}.png',
    attribution: '© Stadia Maps',
    tileSize: 256,
    saturation: 0.02,
    brightness: 0.02,
    contrast: 0.08,
    isStandard: true,
    needsBackendTransform: false,
  },

  // ===== Bing 系列 =====
  {
    id: 'bing-road',
    label: 'Bing 道路',
    provider: 'Bing',
    style: 'street',
    // Bing 道路地图 - 通过后端代理
    urlTemplate: '/tiles/bing-road/{z}/{x}/{y}',
    attribution: '© Microsoft Bing',
    tileSize: 256,
    saturation: -0.02,
    brightness: 0.01,
    contrast: 0.05,
    isStandard: true,
    needsBackendTransform: true,  // Bing 使用自己的坐标系统
  },
  {
    id: 'bing-aerial',
    label: 'Bing 航空',
    provider: 'Bing',
    style: 'satellite',
    // Bing 航空影像
    urlTemplate: '/tiles/bing-aerial/{z}/{x}/{y}',
    attribution: '© Microsoft Bing',
    tileSize: 256,
    saturation: 0.02,
    brightness: 0.02,
    contrast: 0.08,
    isStandard: true,
    needsBackendTransform: true,
  },
  {
    id: 'bing-dark',
    label: 'Bing 深色',
    provider: 'Bing',
    style: 'dark',
    // Bing 深色主题
    urlTemplate: '/tiles/bing-dark/{z}/{x}/{y}',
    attribution: '© Microsoft Bing',
    tileSize: 256,
    saturation: -0.1,
    brightness: -0.05,
    contrast: 0.08,
    isStandard: true,
    needsBackendTransform: true,
  },

  // ===== 中国底图（需代理）=====
  {
    id: 'gaode-street',
    label: '高德街道',
    provider: 'AutoNavi',
    style: 'street',
    // 高德街道地图 - GCJ-02 坐标系，通过后端代理
    urlTemplate: '/tiles/gaode-street/{z}/{x}/{y}',
    attribution: '© 高德地图',
    tileSize: 256,
    saturation: 0,
    brightness: 0,
    contrast: 0.05,
    isStandard: true,
    needsBackendTransform: true,
  },
  {
    id: 'gaode-satellite',
    label: '高德卫星',
    provider: 'AutoNavi',
    style: 'satellite',
    // 高德卫星影像 - GCJ-02 坐标系
    urlTemplate: '/tiles/gaode-satellite/{z}/{x}/{y}',
    attribution: '© 高德影像',
    tileSize: 256,
    saturation: 0.02,
    brightness: 0.02,
    contrast: 0.08,
    isStandard: true,
    needsBackendTransform: true,
  },
  {
    id: 'tianditu-img',
    label: '天地图影像',
    provider: 'Tianditu',
    style: 'satellite',
    // 天地图影像 - 需 API Key
    urlTemplate: '/tiles/tianditu-img/{z}/{x}/{y}',
    attribution: '© 天地图',
    tileSize: 256,
    saturation: 0.02,
    brightness: 0.02,
    contrast: 0.08,
    isStandard: true,
    needsBackendTransform: true,
  },
  {
    id: 'tianditu-label',
    label: '天地图标注',
    provider: 'Tianditu',
    style: 'street',
    // 天地图标注（可叠加在其他影像上）
    urlTemplate: '/tiles/tianditu-label/{z}/{x}/{y}',
    attribution: '© 天地图',
    tileSize: 256,
    saturation: 0,
    brightness: 0,
    contrast: 0.02,
    isStandard: true,
    needsBackendTransform: true,
  },
  {
    id: 'baidu-street',
    label: '百度街道',
    provider: 'Baidu',
    style: 'street',
    // 百度街道地图 - BD-09 坐标系
    urlTemplate: '/tiles/baidu-street/{z}/{x}/{y}',
    attribution: '© 百度地图',
    tileSize: 256,
    saturation: 0,
    brightness: 0,
    contrast: 0.05,
    isStandard: true,
    needsBackendTransform: true,
  },
  {
    id: 'baidu-satellite',
    label: '百度卫星',
    provider: 'Baidu',
    style: 'satellite',
    // 百度卫星影像 - BD-09 坐标系
    urlTemplate: '/tiles/baidu-satellite/{z}/{x}/{y}',
    attribution: '© 百度影像',
    tileSize: 256,
    saturation: 0.02,
    brightness: 0.02,
    contrast: 0.08,
    isStandard: true,
    needsBackendTransform: true,
  },
]

export const TILE_SOURCE_MAP = new Map<TileSourceId, TileSourceConfig>(
  TILE_SOURCES.map((source) => [source.id, source]),
)

export const TILE_SOURCES_BY_STYLE = new Map<BasemapStyle, TileSourceConfig[]>()
for (const source of TILE_SOURCES) {
  const existing = TILE_SOURCES_BY_STYLE.get(source.style)
  if (existing) {
    existing.push(source)
  } else {
    TILE_SOURCES_BY_STYLE.set(source.style, [source])
  }
}

// ============================================================
// 底图辅助函数
// ============================================================

/**
 * 检查底图是否需要通过后端代理
 */
export function needsBackendProxy(sourceId: TileSourceId): boolean {
  const source = TILE_SOURCE_MAP.get(sourceId)
  return source?.needsBackendTransform ?? false
}

/**
 * 获取底图 URL（自动处理代理路径）
 * 对于需要代理的底图，返回后端代理路径
 * 对于直接访问的底图，返回原始 URL
 */
export function getTileUrl(sourceId: TileSourceId): string {
  const source = TILE_SOURCE_MAP.get(sourceId)
  if (!source) return ''

  // 如果需要代理，已经配置了 /tiles/xxx 格式
  if (source.needsBackendTransform) {
    return source.urlTemplate
  }

  return source.urlTemplate
}

/**
 * 获取所有需要代理的底图列表
 */
export function getProxyRequiredSources(): TileSourceConfig[] {
  return TILE_SOURCES.filter((s) => s.needsBackendTransform)
}

/**
 * 获取可直接访问的底图列表
 */
export function getDirectAccessSources(): TileSourceConfig[] {
  return TILE_SOURCES.filter((s) => !s.needsBackendTransform && s.id !== 'none')
}

/**
 * 根据风格获取底图列表
 */
export function getSourcesByStyle(style: BasemapStyle): TileSourceConfig[] {
  return TILE_SOURCES_BY_STYLE.get(style) ?? []
}

/**
 * 获取默认底图（直接访问）
 */
export function getDefaultTileSource(): TileSourceId {
  // 优先使用 Esri（全球覆盖，国内可访问）
  return 'esri-street'
}

/**
 * 检查底图是否可用
 */
export function isSourceAvailable(sourceId: TileSourceId): boolean {
  const source = TILE_SOURCE_MAP.get(sourceId)
  return source !== undefined && source.id !== 'none'
}

export const layerLegends: Record<string, LegendConfig> = {
  'wind-field': {
    title: '风速',
    unit: 'm/s',
    type: 'continuous',
    min: 0,
    max: 30,
    gradient: ['#3288bd', '#99d594', '#e6f598', '#ffffbf', '#fee08b', '#fc8d59', '#d53e4f'],
  },
  'precipitation': {
    title: '降水量',
    unit: 'mm',
    type: 'continuous',
    min: 0,
    max: 100,
    gradient: ['#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#08519c', '#08306b'],
  },
  'temperature': {
    title: '温度',
    unit: '°C',
    type: 'continuous',
    min: -20,
    max: 40,
    gradient: ['#313695', '#4575b4', '#74add1', '#abd9e9', '#e0f3f8', '#ffffbf', '#fee090', '#fdae61', '#f46d43', '#d73027', '#a50026'],
  },
  'remote-sensing': {
    title: '遥感指数',
    unit: 'NDVI',
    type: 'continuous',
    min: -1,
    max: 1,
    gradient: ['#d73027', '#fc8d59', '#fee08b', '#ffffbf', '#d9ef8b', '#91cf60', '#1a9850'],
  },
  'research-output': {
    title: '模型输出',
    unit: 'index',
    type: 'discrete',
    min: 0,
    max: 100,
    items: [
      { color: '#d53e4f', label: '高风险', value: 80 },
      { color: '#fc8d59', label: '中高风险', value: 60 },
      { color: '#fee08b', label: '中等风险', value: 40 },
      { color: '#99d594', label: '低风险', value: 20 },
    ],
  },
}

// 初始图层数据
const initialLayers: Layer[] = [
  {
    id: 'wind-field',
    name: '风场',
    type: 'wind',
    visible: true,
    opacity: 0.8,
    description: '风场矢量数据',
  },
  {
    id: 'precipitation',
    name: '降水',
    type: 'raster',
    visible: false,
    opacity: 0.7,
    description: '降水分布图',
  },
  {
    id: 'temperature',
    name: '温度',
    type: 'raster',
    visible: false,
    opacity: 0.6,
    description: '地表温度',
  },
  {
    id: 'remote-sensing',
    name: '遥感反演',
    type: 'raster',
    visible: false,
    opacity: 0.5,
    description: '遥感反演产品',
  },
  {
    id: 'research-output',
    name: '课题组模型输出',
    type: 'polygon',
    visible: false,
    opacity: 0.9,
    description: '课题组算法计算结果',
  },
]

export const useUiStore = defineStore('ui', () => {
  const mapMode = ref<MapMode>('2d')
  const activeDataset = ref('风场')
  const tileSourceId = ref<TileSourceId>('esri-street')
  const layers = ref<Layer[]>(initialLayers)

  // 时间轴相关 - 使用当前时间初始化
  const now = new Date()
  const currentHour = ref(now.getHours())
  const isPlaying = ref(false)
  const currentDate = ref(now)

  // 用户位置相关
  const userLocation = ref<{ lng: number; lat: number } | null>(null)

  // 侧边栏折叠状态
  const sidebarCollapsed = ref(false)

  const hourLabel = computed(() => `${String(currentHour.value).padStart(2, '0')}:00`)

  // 完整时间标签：日期 + 时间
  const fullTimeLabel = computed(() => {
    const date = currentDate.value
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const hour = String(currentHour.value).padStart(2, '0')
    return `${year}-${month}-${day} ${hour}:00`
  })

  // 获取可见图层
  const visibleLayers = computed(() => layers.value.filter((layer) => layer.visible))

  // 获取活跃图层
  const activeLayer = computed(() =>
    layers.value.find((layer) => layer.name === activeDataset.value)
  )

  // 获取当前图层的图例配置
  const currentLegend = computed(() => {
    const layer = activeLayer.value
    if (!layer) return null
    return layerLegends[layer.id] || null
  })

  function setMode(mode: MapMode) {
    mapMode.value = mode
  }

  function setDataset(dataset: string) {
    activeDataset.value = dataset
  }

  function setTileSource(sourceId: TileSourceId) {
    tileSourceId.value = sourceId
  }

  function setHour(hour: number) {
    currentHour.value = Math.max(0, Math.min(23, Math.round(hour)))
  }

  function stepHour(delta: number) {
    const nextValue = currentHour.value + delta

    if (nextValue < 0) {
      currentHour.value = 23
      // 回退一天
      const newDate = new Date(currentDate.value)
      newDate.setDate(newDate.getDate() - 1)
      currentDate.value = newDate
      return
    }

    if (nextValue > 23) {
      currentHour.value = 0
      // 前进一天
      const newDate = new Date(currentDate.value)
      newDate.setDate(newDate.getDate() + 1)
      currentDate.value = newDate
      return
    }

    currentHour.value = nextValue
  }

  // 播放控制
  function play() {
    isPlaying.value = true
  }

  function pause() {
    isPlaying.value = false
  }

  function togglePlay() {
    isPlaying.value = !isPlaying.value
  }

  function setDate(date: Date) {
    currentDate.value = date
  }

  // 用户位置相关方法
  function setUserLocation(lng: number, lat: number) {
    userLocation.value = { lng, lat }
  }

  function clearUserLocation() {
    userLocation.value = null
  }

  // 侧边栏折叠控制
  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  // 图层相关方法
  function toggleLayerVisibility(layerId: string) {
    const layer = layers.value.find((l) => l.id === layerId)
    if (layer) {
      layer.visible = !layer.visible
    }
  }

  function setLayerOpacity(layerId: string, opacity: number) {
    const layer = layers.value.find((l) => l.id === layerId)
    if (layer) {
      layer.opacity = Math.max(0, Math.min(1, opacity))
    }
  }

  function addLayer(layer: Layer) {
    const exists = layers.value.find((l) => l.id === layer.id)
    if (!exists) {
      layers.value.push(layer)
    }
  }

  function removeLayer(layerId: string) {
    const index = layers.value.findIndex((l) => l.id === layerId)
    if (index !== -1) {
      layers.value.splice(index, 1)
    }
  }

  function setLayerActive(layerId: string) {
    const layer = layers.value.find((l) => l.id === layerId)
    if (layer) {
      activeDataset.value = layer.name
    }
  }

  return {
    mapMode,
    activeDataset,
    tileSourceId,
    currentHour,
    hourLabel,
    fullTimeLabel,
    layers,
    visibleLayers,
    activeLayer,
    currentLegend,
    isPlaying,
    currentDate,
    userLocation,
    sidebarCollapsed,
    setMode,
    setDataset,
    setTileSource,
    setHour,
    stepHour,
    play,
    pause,
    togglePlay,
    setDate,
    setUserLocation,
    clearUserLocation,
    toggleSidebar,
    toggleLayerVisibility,
    setLayerOpacity,
    addLayer,
    removeLayer,
    setLayerActive,
  }
})
