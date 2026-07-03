import type { LayerCatalogItem, LayerCategory, LayerSource } from './types'

// ─── Categories ─────────────────────────────────────────────────────────────────

export const LAYER_CATEGORIES: LayerCategory[] = [
  {
    id: 'meteorology',
    name: '气象场',
    icon: '◈',
    accentColor: '#67d4ff',
    chipTone: 'rgba(103, 212, 255, 0.18)',
  },
  {
    id: 'disaster',
    name: '灾害监测',
    icon: '◉',
    accentColor: '#72ffcf',
    chipTone: 'rgba(114, 255, 207, 0.16)',
  },
  {
    id: 'thermal',
    name: '热环境',
    icon: '◐',
    accentColor: '#ffb65c',
    chipTone: 'rgba(255, 182, 92, 0.16)',
  },
  {
    id: 'remote-sensing',
    name: '遥感产品',
    icon: '◎',
    accentColor: '#bb89ff',
    chipTone: 'rgba(187, 137, 255, 0.16)',
  },
  {
    id: 'simulation',
    name: '模拟结果',
    icon: '◍',
    accentColor: '#ff6f91',
    chipTone: 'rgba(255, 111, 145, 0.16)',
  },
  {
    id: 'boundary',
    name: '边界数据',
    icon: '◻',
    accentColor: '#88d8ff',
    chipTone: 'rgba(136, 216, 255, 0.16)',
  },
]

// ─── Default sources ────────────────────────────────────────────────────────────

const SOURCE_ECMWF: LayerSource = {
  id: 'ecmwf-wind',
  name: 'ECMWF + 本地处理',
  description: 'ECMWF 全球预报场经本地降尺度处理',
  urlTemplate: 'https://example.com/wind/{z}/{x}/{y}.png',
  needsAuth: false,
  needsBackendTransform: false,
  coordSys: 'EPSG:3857',
  updateFrequency: '每 10 分钟刷新',
}

const SOURCE_SATELLITE: LayerSource = {
  id: 'sat-precip',
  name: '卫星融合降水',
  description: '卫星反演 + 地面站融合降水产品',
  urlTemplate: 'https://example.com/precip/{z}/{x}/{y}.png',
  needsAuth: false,
  needsBackendTransform: false,
  coordSys: 'EPSG:3857',
  updateFrequency: '每小时滚动',
}

const SOURCE_LST: LayerSource = {
  id: 'lst-modis',
  name: '遥感反演 + 站点订正',
  description: 'MODIS 地表温度反演经地面站点统计订正',
  urlTemplate: 'https://example.com/lst/{z}/{x}/{y}.png',
  needsAuth: false,
  needsBackendTransform: false,
  coordSys: 'EPSG:3857',
  updateFrequency: '每 30 分钟聚合',
}

const SOURCE_LANDSAT: LayerSource = {
  id: 'landsat-sentinel',
  name: 'Landsat / Sentinel',
  description: 'Landsat 8/9 与 Sentinel-2 联合反演结果',
  urlTemplate: 'https://example.com/rs/{z}/{x}/{y}.png',
  needsAuth: false,
  needsBackendTransform: false,
  coordSys: 'EPSG:3857',
  updateFrequency: '按日更新',
}

const SOURCE_LAB: LayerSource = {
  id: 'lab-model',
  name: '模型任务结果',
  description: '课题组模型生产结果 (由后端 workflow 任务生成)',
  urlTemplate: '',
  needsAuth: false,
  needsBackendTransform: false,
  coordSys: 'EPSG:3857',
  updateFrequency: '按任务刷新',
}

const SOURCE_GD_BOUNDARY: LayerSource = {
  id: 'guangdong-admin',
  name: '广东省市级边界',
  description: '广东省行政区划矢量边界 (GeoJSON)',
  urlTemplate: '',
  needsAuth: false,
  needsBackendTransform: false,
  coordSys: 'EPSG:3857',
  updateFrequency: '静态数据',
}

// ─── Layer catalog (图层库) ─────────────────────────────────────────────────────

export const LAYER_LIBRARY: LayerCatalogItem[] = [
  {
    catalogId: 'wind-field',
    name: '风场',
    category: 'meteorology',
    metricLabel: '核心指标',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每 10 分钟刷新',
    sourceLabel: 'ECMWF + 本地处理',
    accentColor: '#67d4ff',
    accentGlow: 'rgba(103, 212, 255, 0.34)',
    chipTone: 'rgba(103, 212, 255, 0.18)',
    sources: [SOURCE_ECMWF],
  },
  {
    catalogId: 'precipitation',
    name: '降水',
    category: 'disaster',
    metricLabel: '峰值降水',
    metricUnit: 'mm/h',
    metricPrecision: 0,
    updateLabel: '每小时滚动',
    sourceLabel: '卫星融合降水',
    accentColor: '#72ffcf',
    accentGlow: 'rgba(114, 255, 207, 0.3)',
    chipTone: 'rgba(114, 255, 207, 0.16)',
    sources: [SOURCE_SATELLITE],
  },
  {
    catalogId: 'temperature',
    name: '温度',
    category: 'thermal',
    metricLabel: '区域均温',
    metricUnit: '°C',
    metricPrecision: 1,
    updateLabel: '每 30 分钟聚合',
    sourceLabel: '遥感反演 + 站点订正',
    accentColor: '#ffb65c',
    accentGlow: 'rgba(255, 182, 92, 0.3)',
    chipTone: 'rgba(255, 182, 92, 0.16)',
    sources: [SOURCE_LST],
  },
  {
    catalogId: 'remote-sensing',
    name: '遥感反演',
    category: 'remote-sensing',
    metricLabel: '反演指数',
    metricUnit: '',
    metricPrecision: 2,
    updateLabel: '按日更新',
    sourceLabel: 'Landsat / Sentinel',
    accentColor: '#bb89ff',
    accentGlow: 'rgba(187, 137, 255, 0.3)',
    chipTone: 'rgba(187, 137, 255, 0.16)',
    sources: [SOURCE_LANDSAT],
  },
  {
    catalogId: 'lab-output',
    name: '课题组模型输出',
    category: 'simulation',
    metricLabel: '综合评分',
    metricUnit: '/ 100',
    metricPrecision: 0,
    updateLabel: '按任务刷新',
    sourceLabel: '模型任务结果',
    accentColor: '#ff6f91',
    accentGlow: 'rgba(255, 111, 145, 0.3)',
    chipTone: 'rgba(255, 111, 145, 0.16)',
    sources: [SOURCE_LAB],
  },
  {
    catalogId: 'smap-soil',
    name: 'SMAP 土壤水',
    category: 'thermal',
    metricLabel: '土壤体积含水量',
    metricUnit: 'm³/m³',
    metricPrecision: 3,
    updateLabel: '按日更新',
    sourceLabel: 'NASA SMAP',
    accentColor: '#a8e6a3',
    accentGlow: 'rgba(168, 230, 163, 0.3)',
    chipTone: 'rgba(168, 230, 163, 0.16)',
    sources: [],
  },
  {
    catalogId: 'admin-boundary',
    name: '行政区边界',
    category: 'boundary',
    metricLabel: '边界层级',
    metricUnit: '',
    metricPrecision: 0,
    updateLabel: '静态数据',
    sourceLabel: '广东省市级边界',
    accentColor: '#88d8ff',
    accentGlow: 'rgba(136, 216, 255, 0.3)',
    chipTone: 'rgba(136, 216, 255, 0.16)',
    sources: [SOURCE_GD_BOUNDARY],
    isAdminBoundary: true,
  },
]

/** 按 category 分组的图层库 */
export const LAYER_LIBRARY_BY_CATEGORY = (() => {
  const map = new Map<string, LayerCatalogItem[]>()
  for (const item of LAYER_LIBRARY) {
    if (!map.has(item.category)) {
      map.set(item.category, [])
    }
    map.get(item.category)!.push(item)
  }
  return map
})()
