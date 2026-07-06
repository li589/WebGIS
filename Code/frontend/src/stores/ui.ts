import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type MapMode = '2d' | '3d'

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
  items: LegendItem[] // 离散颜色使用
  gradient?: string[] // 连续色带使用
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
