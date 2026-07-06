export interface DemoHotspot {
  id: string
  name: string
  lng: number
  lat: number
  value: string
}

interface DemoHotspotTemplate {
  id: string
  name: string
  lng: number
  lat: number
  baseValue: number
  amplitude: number
}

interface DemoTimeBand {
  startHour: number
  endHour: number
  metricBase: number
  hotspotDrift: number
  availabilityState: 'empty' | 'partial' | 'ready'
  trendLabel: string
  summary: string
  statusLabel: string
  confidenceLabel: string
}

interface DemoFieldAliases {
  metricValue: string[]
  hotspotValue: string[]
  observationTime: string[]
  statusLabel: string[]
}

interface DemoDataState {
  mode: 'demo' | 'placeholder' | 'mixed'
  label: string
  emptyLabel: string
}

export interface DemoLayerCatalogItem {
  id: string
  name: string
  category: string
  metricLabel: string
  metricUnit: string
  metricPrecision: number
  updateLabel: string
  sourceLabel: string
  accentColor: string
  accentGlow: string
  chipTone: string
  dataState: DemoDataState
  fieldAliases: DemoFieldAliases
  hotspotTemplates: DemoHotspotTemplate[]
  timeBands: DemoTimeBand[]
}

export interface DemoLayer {
  id: string
  name: string
  category: string
  summary: string
  metricLabel: string
  metricValue: string
  trendLabel: string
  statusLabel: string
  updateLabel: string
  sourceLabel: string
  confidenceLabel: string
  accentColor: string
  accentGlow: string
  chipTone: string
  dataStateLabel: string
  availabilityState: 'empty' | 'partial' | 'ready'
  availabilityLabel: string
  availabilityDescription: string
  missingFieldsLabel: string
  emptyStateLabel: string
  fieldAliasLabel: string
  observationFieldLabel: string
  observationTimeLabel: string
  hotspots: DemoHotspot[]
}

const defaultObservationFieldAliases = ['time', 'timestamp', 'forecast_time']

export const demoLayerCatalog: DemoLayerCatalogItem[] = [
  {
    id: 'wind-field',
    name: '风场（10m）',
    category: '气象场',
    metricLabel: '风速',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 10m',
    accentColor: '#67d4ff',
    accentGlow: 'rgba(103, 212, 255, 0.34)',
    chipTone: 'rgba(103, 212, 255, 0.18)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 10m',
      emptyLabel: '运行工作流后接入 10m 实时风场',
    },
    fieldAliases: {
      metricValue: ['speed', 'wind_speed', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'speed'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'gzs', name: '广州南沙', lng: 113.6, lat: 22.77, baseValue: 15.6, amplitude: 1.4 },
      { id: 'szb', name: '深圳东部', lng: 114.35, lat: 22.62, baseValue: 14.9, amplitude: 1.1 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 17.2, amplitude: 1.6 },
      { id: 'zhp', name: '中山黄圃', lng: 113.34, lat: 22.71, baseValue: 13.8, amplitude: 1.0 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 6,
        metricBase: 13.9,
        hotspotDrift: -0.5,
        availabilityState: 'partial',
        trendLabel: '夜间海陆风维持，沿海风速偏强',
        summary: '展示近地表风速、风向与局部梯度，适合演示沿海风场框架。',
        statusLabel: 'Demo 更新',
        confidenceLabel: '置信度 92%',
      },
      {
        startHour: 6,
        endHour: 12,
        metricBase: 14.8,
        hotspotDrift: 0.2,
        availabilityState: 'ready',
        trendLabel: '西南风增强 12%',
        summary: '展示近地表风速、风向与局部梯度，上午时段可观察局地增强。',
        statusLabel: 'Demo 更新',
        confidenceLabel: '置信度 93%',
      },
      {
        startHour: 12,
        endHour: 18,
        metricBase: 16.1,
        hotspotDrift: 0.9,
        availabilityState: 'ready',
        trendLabel: '午后海风推进，沿岸梯度扩大',
        summary: '展示近地表风速、风向与局部梯度，午后更适合演示高值带迁移。',
        statusLabel: 'Demo 峰值',
        confidenceLabel: '置信度 94%',
      },
      {
        startHour: 18,
        endHour: 24,
        metricBase: 14.4,
        hotspotDrift: -0.2,
        availabilityState: 'partial',
        trendLabel: '傍晚风速回落，通道逐步收敛',
        summary: '展示近地表风速、风向与局部梯度，傍晚阶段适合演示回落过程。',
        statusLabel: 'Demo 回落',
        confidenceLabel: '置信度 92%',
      },
    ],
  },
  {
    id: 'wind-field-80m',
    name: '风场（80m）',
    category: '气象场',
    metricLabel: '风速',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 80m',
    accentColor: '#7ec4ff',
    accentGlow: 'rgba(126, 196, 255, 0.34)',
    chipTone: 'rgba(126, 196, 255, 0.18)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 80m',
      emptyLabel: '运行工作流后接入 80m 实时风场',
    },
    fieldAliases: {
      metricValue: ['wind_speed_80m', 'speed', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'speed'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'gzs', name: '广州南沙', lng: 113.6, lat: 22.77, baseValue: 19.8, amplitude: 1.6 },
      { id: 'szb', name: '深圳东部', lng: 114.35, lat: 22.62, baseValue: 18.9, amplitude: 1.3 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 21.4, amplitude: 1.8 },
      { id: 'zhp', name: '中山黄圃', lng: 113.34, lat: 22.71, baseValue: 17.6, amplitude: 1.2 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 17.9, hotspotDrift: -0.6,
        availabilityState: 'partial', trendLabel: '夜间 80m 风速维持高位',
        summary: '80m 高度风场，风机轮毂高度参考层，夜间风速通常高于近地面。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 19.0, hotspotDrift: 0.3,
        availabilityState: 'ready', trendLabel: '上午西南风增强',
        summary: '80m 高度风场，上午时段可观察海风增强过程。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 93%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 20.5, hotspotDrift: 1.0,
        availabilityState: 'ready', trendLabel: '午后 80m 风速峰值',
        summary: '80m 高度风场，午后对流增强，风机发电潜力最大时段。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 94%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 18.4, hotspotDrift: -0.3,
        availabilityState: 'partial', trendLabel: '傍晚风速回落',
        summary: '80m 高度风场，傍晚阶段风速逐步收敛。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
    ],
  },
  {
    id: 'wind-field-120m',
    name: '风场（120m）',
    category: '气象场',
    metricLabel: '风速',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 120m',
    accentColor: '#95b8ff',
    accentGlow: 'rgba(149, 184, 255, 0.34)',
    chipTone: 'rgba(149, 184, 255, 0.18)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 120m',
      emptyLabel: '运行工作流后接入 120m 实时风场',
    },
    fieldAliases: {
      metricValue: ['wind_speed_120m', 'speed', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'speed'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'gzs', name: '广州南沙', lng: 113.6, lat: 22.77, baseValue: 22.4, amplitude: 1.8 },
      { id: 'szb', name: '深圳东部', lng: 114.35, lat: 22.62, baseValue: 21.3, amplitude: 1.5 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 24.1, amplitude: 2.0 },
      { id: 'zhp', name: '中山黄圃', lng: 113.34, lat: 22.71, baseValue: 19.9, amplitude: 1.3 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 20.2, hotspotDrift: -0.7,
        availabilityState: 'partial', trendLabel: '夜间 120m 风速稳定',
        summary: '120m 高度风场，大型/海上风机轮毂高度参考层。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 21.5, hotspotDrift: 0.4,
        availabilityState: 'ready', trendLabel: '上午 120m 风速增强',
        summary: '120m 高度风场，上午时段风速通常高于 80m。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 93%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 23.2, hotspotDrift: 1.1,
        availabilityState: 'ready', trendLabel: '午后 120m 风速峰值',
        summary: '120m 高度风场，午后峰值时段，海上风机发电黄金区间。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 94%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 20.8, hotspotDrift: -0.4,
        availabilityState: 'partial', trendLabel: '傍晚风速回落',
        summary: '120m 高度风场，傍晚阶段风速逐步收敛。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
    ],
  },
  {
    id: 'wind-field-180m',
    name: '风场（180m）',
    category: '气象场',
    metricLabel: '风速',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 180m',
    accentColor: '#a8a8ff',
    accentGlow: 'rgba(168, 168, 255, 0.34)',
    chipTone: 'rgba(168, 168, 255, 0.18)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 180m',
      emptyLabel: '运行工作流后接入 180m 实时风场',
    },
    fieldAliases: {
      metricValue: ['wind_speed_180m', 'speed', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'speed'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'gzs', name: '广州南沙', lng: 113.6, lat: 22.77, baseValue: 25.1, amplitude: 2.0 },
      { id: 'szb', name: '深圳东部', lng: 114.35, lat: 22.62, baseValue: 23.9, amplitude: 1.7 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 27.0, amplitude: 2.2 },
      { id: 'zhp', name: '中山黄圃', lng: 113.34, lat: 22.71, baseValue: 22.3, amplitude: 1.5 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 22.7, hotspotDrift: -0.8,
        availabilityState: 'partial', trendLabel: '夜间 180m 边界层顶风',
        summary: '180m 高度风场，大气边界层顶部参考层，风速通常最大。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 24.2, hotspotDrift: 0.5,
        availabilityState: 'ready', trendLabel: '上午 180m 风速增强',
        summary: '180m 高度风场，上午对流发展期，风速持续上升。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 93%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 26.1, hotspotDrift: 1.2,
        availabilityState: 'ready', trendLabel: '午后 180m 风速峰值',
        summary: '180m 高度风场，午后峰值时段，常达到大风阈值。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 94%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 23.4, hotspotDrift: -0.5,
        availabilityState: 'partial', trendLabel: '傍晚风速回落',
        summary: '180m 高度风场，傍晚阶段边界层衰减，风速收敛。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
    ],
  },
  {
    id: 'wind-field-850hPa',
    name: '风场（850hPa）',
    category: '气象场',
    metricLabel: '850hPa 风速',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 850hPa',
    accentColor: '#8fb8ff',
    accentGlow: 'rgba(143, 184, 255, 0.34)',
    chipTone: 'rgba(143, 184, 255, 0.18)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 850hPa',
      emptyLabel: '运行工作流后接入 850hPa 实时风场',
    },
    fieldAliases: {
      metricValue: ['wind_speed_850hPa', 'speed_850hPa', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'wind_speed_850hPa'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'gzs', name: '广州南沙', lng: 113.6, lat: 22.77, baseValue: 28.5, amplitude: 2.2 },
      { id: 'szb', name: '深圳东部', lng: 114.35, lat: 22.62, baseValue: 26.8, amplitude: 1.9 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 30.2, amplitude: 2.4 },
      { id: 'zhp', name: '中山黄圃', lng: 113.34, lat: 22.71, baseValue: 25.4, amplitude: 1.6 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 24.8, hotspotDrift: -0.8,
        availabilityState: 'partial', trendLabel: '夜间 850hPa 低空急流',
        summary: '850 hPa 气压层（约 1.5 km）风场，低空急流与对流 inflow 参考。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 26.6, hotspotDrift: 0.4,
        availabilityState: 'ready', trendLabel: '上午 850hPa 西南风增强',
        summary: '850 hPa 风场，上午时段常出现低空急流建立。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 28.9, hotspotDrift: 1.3,
        availabilityState: 'ready', trendLabel: '午后 850hPa 风速峰值',
        summary: '850 hPa 风场，午后对流活跃期，强对流触发参考层。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 93%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 25.7, hotspotDrift: -0.4,
        availabilityState: 'partial', trendLabel: '傍晚 850hPa 风速回落',
        summary: '850 hPa 风场，傍晚阶段风速收敛。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
    ],
  },
  {
    id: 'wind-field-500hPa',
    name: '风场（500hPa）',
    category: '气象场',
    metricLabel: '500hPa 风速',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 500hPa',
    accentColor: '#7ea0ff',
    accentGlow: 'rgba(126, 160, 255, 0.34)',
    chipTone: 'rgba(126, 160, 255, 0.18)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 500hPa',
      emptyLabel: '运行工作流后接入 500hPa 实时风场',
    },
    fieldAliases: {
      metricValue: ['wind_speed_500hPa', 'speed_500hPa', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'wind_speed_500hPa'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'gzs', name: '广州南沙', lng: 113.6, lat: 22.77, baseValue: 35.2, amplitude: 2.8 },
      { id: 'szb', name: '深圳东部', lng: 114.35, lat: 22.62, baseValue: 33.6, amplitude: 2.4 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 37.8, amplitude: 3.0 },
      { id: 'zhp', name: '中山黄圃', lng: 113.34, lat: 22.71, baseValue: 32.1, amplitude: 2.0 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 31.4, hotspotDrift: -1.0,
        availabilityState: 'partial', trendLabel: '夜间 500hPa 西风带',
        summary: '500 hPa 气压层（约 5.5 km）风场，中空天气尺度流场参考。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 33.5, hotspotDrift: 0.5,
        availabilityState: 'ready', trendLabel: '上午 500hPa 短波槽东移',
        summary: '500 hPa 风场，上午时段常配合短波槽移动出现风速增强。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 36.1, hotspotDrift: 1.6,
        availabilityState: 'ready', trendLabel: '午后 500hPa 急流核',
        summary: '500 hPa 风场，午后急流核通过时段，强对流引导层。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 93%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 32.8, hotspotDrift: -0.6,
        availabilityState: 'partial', trendLabel: '傍晚 500hPa 风速收敛',
        summary: '500 hPa 风场，傍晚阶段急流核东移，风速收敛。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
    ],
  },
  {
    id: 'wind-field-200hPa',
    name: '风场（200hPa）',
    category: '气象场',
    metricLabel: '200hPa 风速',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 200hPa',
    accentColor: '#6e88ff',
    accentGlow: 'rgba(110, 136, 255, 0.34)',
    chipTone: 'rgba(110, 136, 255, 0.18)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 200hPa',
      emptyLabel: '运行工作流后接入 200hPa 实时风场',
    },
    fieldAliases: {
      metricValue: ['wind_speed_200hPa', 'speed_200hPa', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'wind_speed_200hPa'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'gzs', name: '广州南沙', lng: 113.6, lat: 22.77, baseValue: 62.4, amplitude: 4.5 },
      { id: 'szb', name: '深圳东部', lng: 114.35, lat: 22.62, baseValue: 58.7, amplitude: 3.8 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 67.2, amplitude: 5.0 },
      { id: 'zhp', name: '中山黄圃', lng: 113.34, lat: 22.71, baseValue: 55.8, amplitude: 3.4 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 56.3, hotspotDrift: -1.5,
        availabilityState: 'partial', trendLabel: '夜间 200hPa 急流',
        summary: '200 hPa 气压层（约 12 km）风场，高空急流参考层。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 60.5, hotspotDrift: 0.8,
        availabilityState: 'ready', trendLabel: '上午 200hPa 急流增强',
        summary: '200 hPa 风场，上午时段高空急流入口区风速增强。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 65.8, hotspotDrift: 2.5,
        availabilityState: 'ready', trendLabel: '午后 200hPa 急流核',
        summary: '200 hPa 风场，午后急流核通过时段，常超过 60 m/s。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 93%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 58.2, hotspotDrift: -1.0,
        availabilityState: 'partial', trendLabel: '傍晚 200hPa 风速收敛',
        summary: '200 hPa 风场，傍晚急流核东移，风速收敛。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
    ],
  },
  {
    id: 'precipitation',
    name: '降水',
    category: '灾害监测',
    metricLabel: '峰值降水',
    metricUnit: 'mm/h',
    metricPrecision: 0,
    updateLabel: '每小时滚动',
    sourceLabel: '卫星融合降水',
    accentColor: '#72ffcf',
    accentGlow: 'rgba(114, 255, 207, 0.3)',
    chipTone: 'rgba(114, 255, 207, 0.16)',
    dataState: {
      mode: 'demo',
      label: 'Demo 时段样例',
      emptyLabel: '待接入实况降水产品后替换',
    },
    fieldAliases: {
      metricValue: ['precip_rate', 'rain_rate', 'value'],
      hotspotValue: ['site_rain', 'pixel_rain', 'rain_rate'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['warning_level', 'status'],
    },
    hotspotTemplates: [
      { id: 'qys', name: '清远山地', lng: 113.15, lat: 24.05, baseValue: 42, amplitude: 8 },
      { id: 'dgx', name: '东莞西部', lng: 113.71, lat: 23.02, baseValue: 55, amplitude: 10 },
      { id: 'hzz', name: '惠州中部', lng: 114.53, lat: 23.14, baseValue: 38, amplitude: 6 },
      { id: 'zjp', name: '湛江湾', lng: 110.35, lat: 21.27, baseValue: 32, amplitude: 5 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 6,
        metricBase: 28,
        hotspotDrift: -6,
        availabilityState: 'partial',
        trendLabel: '夜间对流减弱，强降水范围收缩',
        summary: '展示小时降水强度与强对流核心区，夜间以残余回波为主。',
        statusLabel: '监测中',
        confidenceLabel: '置信度 86%',
      },
      {
        startHour: 6,
        endHour: 12,
        metricBase: 41,
        hotspotDrift: -1,
        availabilityState: 'partial',
        trendLabel: '晨间回波重组，山区率先触发',
        summary: '展示小时降水强度与强对流核心区，上午利于演示对流初生。',
        statusLabel: '短临预报',
        confidenceLabel: '置信度 88%',
      },
      {
        startHour: 12,
        endHour: 18,
        metricBase: 62,
        hotspotDrift: 7,
        availabilityState: 'ready',
        trendLabel: '对流带向东移动',
        summary: '展示小时降水强度与强对流核心区，午后为 Demo 峰值时段。',
        statusLabel: '强对流活跃',
        confidenceLabel: '置信度 90%',
      },
      {
        startHour: 18,
        endHour: 24,
        metricBase: 36,
        hotspotDrift: -3,
        availabilityState: 'partial',
        trendLabel: '傍晚主雨带减弱，沿海残留回波',
        summary: '展示小时降水强度与强对流核心区，傍晚阶段适合演示衰减过程。',
        statusLabel: '回波衰减',
        confidenceLabel: '置信度 87%',
      },
    ],
  },
  {
    id: 'temperature',
    name: '温度',
    category: '热环境',
    metricLabel: '区域均温',
    metricUnit: '°C',
    metricPrecision: 1,
    updateLabel: '每 30 分钟聚合',
    sourceLabel: '遥感反演 + 站点订正',
    accentColor: '#ffb65c',
    accentGlow: 'rgba(255, 182, 92, 0.3)',
    chipTone: 'rgba(255, 182, 92, 0.16)',
    dataState: {
      mode: 'mixed',
      label: 'Demo + 占位',
      emptyLabel: '待接入真实热环境栅格后替换',
    },
    fieldAliases: {
      metricValue: ['temperature', 'lst', 'value'],
      hotspotValue: ['site_temp', 'urban_heat', 'temperature'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'product_state'],
    },
    hotspotTemplates: [
      { id: 'fos', name: '佛山禅城', lng: 113.12, lat: 23.02, baseValue: 31.4, amplitude: 2.2 },
      { id: 'gzt', name: '广州天河', lng: 113.36, lat: 23.13, baseValue: 32.3, amplitude: 2.5 },
      { id: 'szh', name: '深圳河套', lng: 114.05, lat: 22.53, baseValue: 30.9, amplitude: 1.9 },
      { id: 'fss', name: '佛山顺德', lng: 113.28, lat: 22.91, baseValue: 31.8, amplitude: 2.0 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 6,
        metricBase: 26.8,
        hotspotDrift: -2.1,
        availabilityState: 'partial',
        trendLabel: '夜间热岛减弱，城区与郊区差异缩小',
        summary: '展示地表温度与城市热岛强度，夜间可演示热岛回落阶段。',
        statusLabel: '夜间回放',
        confidenceLabel: '置信度 89%',
      },
      {
        startHour: 6,
        endHour: 12,
        metricBase: 30.2,
        hotspotDrift: -0.4,
        availabilityState: 'ready',
        trendLabel: '日照增强，热岛逐步建立',
        summary: '展示地表温度与城市热岛强度，上午阶段适合演示升温过程。',
        statusLabel: '升温中',
        confidenceLabel: '置信度 90%',
      },
      {
        startHour: 12,
        endHour: 18,
        metricBase: 31.6,
        hotspotDrift: 1.3,
        availabilityState: 'ready',
        trendLabel: '城区热岛上升 1.8 °C',
        summary: '展示地表温度与城市热岛强度，午后阶段为 Demo 主展示时段。',
        statusLabel: '高温峰值',
        confidenceLabel: '置信度 91%',
      },
      {
        startHour: 18,
        endHour: 24,
        metricBase: 29.1,
        hotspotDrift: -0.8,
        availabilityState: 'partial',
        trendLabel: '晚间降温开始，核心城区仍偏暖',
        summary: '展示地表温度与城市热岛强度，晚间阶段适合演示滞后降温。',
        statusLabel: '回落中',
        confidenceLabel: '置信度 90%',
      },
    ],
  },
  {
    id: 'temperature-80m',
    name: '温度（80m）',
    category: '热环境',
    metricLabel: '80m 温度',
    metricUnit: '°C',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 80m',
    accentColor: '#ffc97a',
    accentGlow: 'rgba(255, 201, 122, 0.3)',
    chipTone: 'rgba(255, 201, 122, 0.16)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 80m',
      emptyLabel: '运行工作流后接入 80m 实时温度',
    },
    fieldAliases: {
      metricValue: ['temperature_80m', 'temp_80m', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'temperature_80m'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'fos', name: '佛山禅城', lng: 113.12, lat: 23.02, baseValue: 28.6, amplitude: 1.4 },
      { id: 'gzt', name: '广州天河', lng: 113.36, lat: 23.13, baseValue: 29.3, amplitude: 1.5 },
      { id: 'szh', name: '深圳河套', lng: 114.05, lat: 22.53, baseValue: 28.1, amplitude: 1.2 },
      { id: 'zhp', name: '中山黄圃', lng: 113.34, lat: 22.71, baseValue: 27.9, amplitude: 1.1 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 24.8, hotspotDrift: -1.4,
        availabilityState: 'partial', trendLabel: '夜间 80m 温度低于地面',
        summary: '80m 高度温度，风机结冰预警与尾流分析参考层。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 90%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 27.6, hotspotDrift: -0.2,
        availabilityState: 'ready', trendLabel: '上午 80m 温度爬升',
        summary: '80m 高度温度，上午时段温度通常略低于 2m。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 29.0, hotspotDrift: 0.6,
        availabilityState: 'ready', trendLabel: '午后 80m 温度峰值',
        summary: '80m 高度温度，午后峰值时段，可观察热对流高度。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 27.2, hotspotDrift: -0.4,
        availabilityState: 'partial', trendLabel: '傍晚 80m 温度回落',
        summary: '80m 高度温度，傍晚阶段温度逐步回落。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 90%',
      },
    ],
  },
  {
    id: 'temperature-120m',
    name: '温度（120m）',
    category: '热环境',
    metricLabel: '120m 温度',
    metricUnit: '°C',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 120m',
    accentColor: '#ffdc8a',
    accentGlow: 'rgba(255, 220, 138, 0.3)',
    chipTone: 'rgba(255, 220, 138, 0.16)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 120m',
      emptyLabel: '运行工作流后接入 120m 实时温度',
    },
    fieldAliases: {
      metricValue: ['temperature_120m', 'temp_120m', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'temperature_120m'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'fos', name: '佛山禅城', lng: 113.12, lat: 23.02, baseValue: 27.4, amplitude: 1.3 },
      { id: 'gzt', name: '广州天河', lng: 113.36, lat: 23.13, baseValue: 28.1, amplitude: 1.4 },
      { id: 'szh', name: '深圳河套', lng: 114.05, lat: 22.53, baseValue: 26.9, amplitude: 1.1 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 26.5, amplitude: 1.0 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 23.6, hotspotDrift: -1.5,
        availabilityState: 'partial', trendLabel: '夜间 120m 温度低于 80m',
        summary: '120m 高度温度，大型风机轮毂高度热力参考。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 90%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 26.3, hotspotDrift: -0.3,
        availabilityState: 'ready', trendLabel: '上午 120m 温度爬升',
        summary: '120m 高度温度，上午时段温度通常略低于 80m。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 27.8, hotspotDrift: 0.5,
        availabilityState: 'ready', trendLabel: '午后 120m 温度峰值',
        summary: '120m 高度温度，午后峰值时段，海上风机热力剖面参考。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 26.0, hotspotDrift: -0.5,
        availabilityState: 'partial', trendLabel: '傍晚 120m 温度回落',
        summary: '120m 高度温度，傍晚阶段温度逐步回落。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 90%',
      },
    ],
  },
  {
    id: 'temperature-180m',
    name: '温度（180m）',
    category: '热环境',
    metricLabel: '180m 温度',
    metricUnit: '°C',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo · 180m',
    accentColor: '#ffe49a',
    accentGlow: 'rgba(255, 228, 154, 0.3)',
    chipTone: 'rgba(255, 228, 154, 0.16)',
    dataState: {
      mode: 'mixed',
      label: 'Open-Meteo 180m',
      emptyLabel: '运行工作流后接入 180m 实时温度',
    },
    fieldAliases: {
      metricValue: ['temperature_180m', 'temp_180m', 'value'],
      hotspotValue: ['station_value', 'grid_value', 'temperature_180m'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['status', 'quality_flag'],
    },
    hotspotTemplates: [
      { id: 'fos', name: '佛山禅城', lng: 113.12, lat: 23.02, baseValue: 26.2, amplitude: 1.2 },
      { id: 'gzt', name: '广州天河', lng: 113.36, lat: 23.13, baseValue: 26.9, amplitude: 1.3 },
      { id: 'szh', name: '深圳河套', lng: 114.05, lat: 22.53, baseValue: 25.7, amplitude: 1.0 },
      { id: 'zjz', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 25.3, amplitude: 0.9 },
    ],
    timeBands: [
      {
        startHour: 0, endHour: 6, metricBase: 22.4, hotspotDrift: -1.6,
        availabilityState: 'partial', trendLabel: '夜间 180m 温度最低',
        summary: '180m 高度温度，大气边界层顶部热力剖面。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 90%',
      },
      {
        startHour: 6, endHour: 12, metricBase: 25.1, hotspotDrift: -0.4,
        availabilityState: 'ready', trendLabel: '上午 180m 温度爬升',
        summary: '180m 高度温度，上午时段温度通常略低于 120m。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 91%',
      },
      {
        startHour: 12, endHour: 18, metricBase: 26.6, hotspotDrift: 0.4,
        availabilityState: 'ready', trendLabel: '午后 180m 温度峰值',
        summary: '180m 高度温度，午后峰值时段，边界层顶部热力参考。',
        statusLabel: 'Open-Meteo 峰值', confidenceLabel: '置信度 92%',
      },
      {
        startHour: 18, endHour: 24, metricBase: 24.8, hotspotDrift: -0.6,
        availabilityState: 'partial', trendLabel: '傍晚 180m 温度回落',
        summary: '180m 高度温度，傍晚阶段温度逐步回落。',
        statusLabel: 'Open-Meteo', confidenceLabel: '置信度 90%',
      },
    ],
  },
  {
    id: 'pressure',
    name: '气压',
    category: '大气环境',
    metricLabel: '海平面气压',
    metricUnit: 'hPa',
    metricPrecision: 1,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo / 气压分析',
    accentColor: '#c9a3ff',
    accentGlow: 'rgba(201, 163, 255, 0.3)',
    chipTone: 'rgba(201, 163, 255, 0.16)',
    dataState: {
      mode: 'demo',
      label: 'Demo 气压场',
      emptyLabel: '待接入真实气压格点后替换',
    },
    fieldAliases: {
      metricValue: ['pressure_msl', 'mslp', 'value'],
      hotspotValue: ['station_pressure', 'grid_pressure', 'pressure_msl'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['pressure_trend', 'status'],
    },
    hotspotTemplates: [
      { id: 'qyl', name: '清远低压槽', lng: 113.05, lat: 23.88, baseValue: 1008.5, amplitude: 1.5 },
      { id: 'gzh', name: '广州高压脊', lng: 113.32, lat: 23.14, baseValue: 1012.4, amplitude: 1.2 },
      { id: 'swh', name: '汕头沿海', lng: 116.68, lat: 23.35, baseValue: 1010.8, amplitude: 1.4 },
      { id: 'zjl', name: '湛江雷州', lng: 110.07, lat: 20.91, baseValue: 1009.6, amplitude: 1.1 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 6,
        metricBase: 1010.2,
        hotspotDrift: -0.8,
        availabilityState: 'partial',
        trendLabel: '夜间气压稳定，低压槽缓慢东移',
        summary: '展示海平面气压分布与低压中心轨迹，夜间气压场变化平缓。',
        statusLabel: '气压稳定',
        confidenceLabel: '置信度 91%',
      },
      {
        startHour: 6,
        endHour: 12,
        metricBase: 1011.5,
        hotspotDrift: 0.4,
        availabilityState: 'ready',
        trendLabel: '晨间高压脊推进，气压梯度增强',
        summary: '展示海平面气压分布与低压中心轨迹，上午可观察气压系统迁移。',
        statusLabel: '系统迁移',
        confidenceLabel: '置信度 93%',
      },
      {
        startHour: 12,
        endHour: 18,
        metricBase: 1012.8,
        hotspotDrift: 0.9,
        availabilityState: 'ready',
        trendLabel: '午后气压达到峰值，等压线密集',
        summary: '展示海平面气压分布与低压中心轨迹，午后为气压场 Demo 主展示时段。',
        statusLabel: '气压峰值',
        confidenceLabel: '置信度 94%',
      },
      {
        startHour: 18,
        endHour: 24,
        metricBase: 1011.0,
        hotspotDrift: -0.3,
        availabilityState: 'partial',
        trendLabel: '傍晚气压回落，低压槽重新发展',
        summary: '展示海平面气压分布与低压中心轨迹，傍晚适合演示气压衰减过程。',
        statusLabel: '气压回落',
        confidenceLabel: '置信度 92%',
      },
    ],
  },
  {
    id: 'humidity',
    name: '湿度',
    category: '大气环境',
    metricLabel: '相对湿度',
    metricUnit: '%',
    metricPrecision: 0,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo / 湿度监测',
    accentColor: '#a3d9b0',
    accentGlow: 'rgba(163, 217, 176, 0.3)',
    chipTone: 'rgba(163, 217, 176, 0.16)',
    dataState: {
      mode: 'demo',
      label: 'Demo 湿度场',
      emptyLabel: '待接入真实湿度产品后替换',
    },
    fieldAliases: {
      metricValue: ['relative_humidity_2m', 'humidity', 'value'],
      hotspotValue: ['station_humidity', 'grid_humidity', 'humidity'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['comfort_index', 'status'],
    },
    hotspotTemplates: [
      { id: 'jmh', name: '江门沿海', lng: 113.02, lat: 21.94, baseValue: 88, amplitude: 5 },
      { id: 'zqh', name: '珠江口', lng: 113.82, lat: 22.34, baseValue: 84, amplitude: 4 },
      { id: 'szh', name: '深圳河套', lng: 114.05, lat: 22.53, baseValue: 82, amplitude: 4 },
      { id: 'qyh', name: '清远山区', lng: 113.15, lat: 24.05, baseValue: 78, amplitude: 5 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 6,
        metricBase: 86,
        hotspotDrift: 3,
        availabilityState: 'partial',
        trendLabel: '夜间湿度饱和，沿海局地起雾',
        summary: '展示 2 米相对湿度分布与舒适度，夜间湿度维持高位。',
        statusLabel: '高湿预警',
        confidenceLabel: '置信度 90%',
      },
      {
        startHour: 6,
        endHour: 12,
        metricBase: 78,
        hotspotDrift: -2,
        availabilityState: 'ready',
        trendLabel: '晨间湿度回落，日照蒸发增强',
        summary: '展示 2 米相对湿度分布与舒适度，上午可观察湿度下降过程。',
        statusLabel: '湿度回落',
        confidenceLabel: '置信度 92%',
      },
      {
        startHour: 12,
        endHour: 18,
        metricBase: 72,
        hotspotDrift: -4,
        availabilityState: 'ready',
        trendLabel: '午后湿度降至最低，体感舒适',
        summary: '展示 2 米相对湿度分布与舒适度，午后为 Demo 低值时段。',
        statusLabel: '舒适时段',
        confidenceLabel: '置信度 93%',
      },
      {
        startHour: 18,
        endHour: 24,
        metricBase: 80,
        hotspotDrift: 2,
        availabilityState: 'partial',
        trendLabel: '傍晚湿度回升，沿海率先达饱和',
        summary: '展示 2 米相对湿度分布与舒适度，傍晚适合演示湿度回升。',
        statusLabel: '湿度回升',
        confidenceLabel: '置信度 91%',
      },
    ],
  },
  {
    id: 'visibility',
    name: '能见度',
    category: '大气环境',
    metricLabel: '能见度',
    metricUnit: 'm',
    metricPrecision: 0,
    updateLabel: '每小时刷新',
    sourceLabel: 'Open-Meteo / 能见度监测',
    accentColor: '#e8c87a',
    accentGlow: 'rgba(232, 200, 122, 0.3)',
    chipTone: 'rgba(232, 200, 122, 0.16)',
    dataState: {
      mode: 'demo',
      label: 'Demo 能见度',
      emptyLabel: '待接入真实能见度观测后替换',
    },
    fieldAliases: {
      metricValue: ['visibility', 'vis', 'value'],
      hotspotValue: ['station_vis', 'grid_vis', 'visibility'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['visibility_level', 'status'],
    },
    hotspotTemplates: [
      { id: 'qyv', name: '清远山区', lng: 113.15, lat: 24.05, baseValue: 3500, amplitude: 800 },
      { id: 'gzv', name: '广州城区', lng: 113.36, lat: 23.13, baseValue: 8500, amplitude: 1200 },
      { id: 'szv', name: '深圳沿海', lng: 114.05, lat: 22.53, baseValue: 12000, amplitude: 1500 },
      { id: 'stv', name: '汕头沿海', lng: 116.68, lat: 23.35, baseValue: 9500, amplitude: 1300 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 6,
        metricBase: 4200,
        hotspotDrift: -1500,
        availabilityState: 'partial',
        trendLabel: '夜间雾区扩展，能见度低于 3 km',
        summary: '展示地面能见度与低能见度风险区，夜间为 Demo 低值时段。',
        statusLabel: '低能见度',
        confidenceLabel: '置信度 88%',
      },
      {
        startHour: 6,
        endHour: 12,
        metricBase: 7800,
        hotspotDrift: 2000,
        availabilityState: 'ready',
        trendLabel: '晨间雾散，能见度快速回升',
        summary: '展示地面能见度与低能见度风险区，上午可观察雾消散过程。',
        statusLabel: '能见度回升',
        confidenceLabel: '置信度 90%',
      },
      {
        startHour: 12,
        endHour: 18,
        metricBase: 12500,
        hotspotDrift: 1500,
        availabilityState: 'ready',
        trendLabel: '午后能见度最佳，航空条件优良',
        summary: '展示地面能见度与低能见度风险区，午后为 Demo 峰值时段。',
        statusLabel: '优良能见度',
        confidenceLabel: '置信度 92%',
      },
      {
        startHour: 18,
        endHour: 24,
        metricBase: 6500,
        hotspotDrift: -2000,
        availabilityState: 'partial',
        trendLabel: '傍晚能见度下降，霾区逐步形成',
        summary: '展示地面能见度与低能见度风险区，傍晚适合演示衰减过程。',
        statusLabel: '能见度下降',
        confidenceLabel: '置信度 89%',
      },
    ],
  },
  {
    id: 'ndvi',
    name: '植被指数',
    category: '植被监测',
    metricLabel: 'NDVI',
    metricUnit: '',
    metricPrecision: 2,
    updateLabel: '按日更新',
    sourceLabel: 'Landsat / Sentinel NDVI',
    accentColor: '#7fd99a',
    accentGlow: 'rgba(127, 217, 154, 0.3)',
    chipTone: 'rgba(127, 217, 154, 0.16)',
    dataState: {
      mode: 'placeholder',
      label: 'Demo NDVI',
      emptyLabel: '待接入真实遥感 NDVI 产品后替换',
    },
    fieldAliases: {
      metricValue: ['ndvi', 'vegetation_index', 'value'],
      hotspotValue: ['pixel_ndvi', 'region_ndvi', 'ndvi'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['vegetation_state', 'status'],
    },
    hotspotTemplates: [
      { id: 'qyn', name: '清远林区', lng: 113.05, lat: 23.88, baseValue: 0.72, amplitude: 0.04 },
      { id: 'zjn', name: '湛江农区', lng: 110.35, lat: 21.27, baseValue: 0.65, amplitude: 0.05 },
      { id: 'mzn', name: '梅州山地', lng: 116.12, lat: 24.28, baseValue: 0.78, amplitude: 0.03 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 8,
        metricBase: 0.71,
        hotspotDrift: -0.01,
        availabilityState: 'empty',
        trendLabel: '夜间保留上一期 NDVI 反演结果',
        summary: '展示植被覆盖度与生长状况，当前以占位协议演示字段映射。',
        statusLabel: '待真实数据',
        confidenceLabel: '置信度 待接入',
      },
      {
        startHour: 8,
        endHour: 16,
        metricBase: 0.73,
        hotspotDrift: 0.02,
        availabilityState: 'partial',
        trendLabel: '林区 NDVI 偏高，农区梯度明显',
        summary: '展示植被覆盖度与生长状况，白天阶段用于演示 NDVI 产品接入。',
        statusLabel: '协议演示',
        confidenceLabel: '置信度 占位',
      },
      {
        startHour: 16,
        endHour: 24,
        metricBase: 0.72,
        hotspotDrift: 0,
        availabilityState: 'empty',
        trendLabel: '晚间保留最近一次有效 NDVI 结果',
        summary: '展示植被覆盖度与生长状况，当前未接入实时产品，保持 Demo 占位。',
        statusLabel: '待真实数据',
        confidenceLabel: '置信度 待接入',
      },
    ],
  },
  {
    id: 'remote-sensing',
    name: '遥感反演',
    category: '遥感产品',
    metricLabel: '反演指数',
    metricUnit: '',
    metricPrecision: 2,
    updateLabel: '按日更新',
    sourceLabel: 'Landsat / Sentinel',
    accentColor: '#bb89ff',
    accentGlow: 'rgba(187, 137, 255, 0.3)',
    chipTone: 'rgba(187, 137, 255, 0.16)',
    dataState: {
      mode: 'placeholder',
      label: '占位协议',
      emptyLabel: '待接入真实遥感反演结果',
    },
    fieldAliases: {
      metricValue: ['retrieval_index', 'index_value', 'value'],
      hotspotValue: ['pixel_index', 'region_index', 'index_value'],
      observationTime: defaultObservationFieldAliases,
      statusLabel: ['inversion_state', 'status'],
    },
    hotspotTemplates: [
      { id: 'jm', name: '江门沿海', lng: 113.02, lat: 21.94, baseValue: 0.79, amplitude: 0.04 },
      { id: 'zh', name: '珠海西岸', lng: 113.24, lat: 22.08, baseValue: 0.77, amplitude: 0.03 },
      { id: 'zs', name: '中山南部', lng: 113.36, lat: 22.35, baseValue: 0.74, amplitude: 0.03 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 8,
        metricBase: 0.74,
        hotspotDrift: -0.02,
        availabilityState: 'empty',
        trendLabel: '夜间阶段保留上一期反演结果',
        summary: '展示遥感反演结果与空间差异，当前以占位协议演示字段映射。',
        statusLabel: '待真实数据',
        confidenceLabel: '置信度 待接入',
      },
      {
        startHour: 8,
        endHour: 16,
        metricBase: 0.78,
        hotspotDrift: 0.01,
        availabilityState: 'partial',
        trendLabel: '边缘区梯度明显',
        summary: '展示遥感反演结果与空间差异，白天阶段用于演示反演产品接入框架。',
        statusLabel: '协议演示',
        confidenceLabel: '置信度 占位',
      },
      {
        startHour: 16,
        endHour: 24,
        metricBase: 0.76,
        hotspotDrift: -0.01,
        availabilityState: 'empty',
        trendLabel: '晚间保留最近一次有效反演结果',
        summary: '展示遥感反演结果与空间差异，当前未接入实时产品，保持 Demo 占位。',
        statusLabel: '待真实数据',
        confidenceLabel: '置信度 待接入',
      },
    ],
  },
  {
    id: 'lab-output',
    name: '课题组模型输出',
    category: '模拟结果',
    metricLabel: '综合评分',
    metricUnit: '/ 100',
    metricPrecision: 0,
    updateLabel: '按任务刷新',
    sourceLabel: '模型任务结果',
    accentColor: '#ff6f91',
    accentGlow: 'rgba(255, 111, 145, 0.3)',
    chipTone: 'rgba(255, 111, 145, 0.16)',
    dataState: {
      mode: 'mixed',
      label: 'Demo 任务结果',
      emptyLabel: '待接入真实任务输出文件',
    },
    fieldAliases: {
      metricValue: ['score', 'risk_score', 'value'],
      hotspotValue: ['cell_score', 'grid_score', 'risk_score'],
      observationTime: ['task_time', 'run_time', 'forecast_time'],
      statusLabel: ['task_status', 'status'],
    },
    hotspotTemplates: [
      { id: 'gza', name: '广州北部', lng: 113.31, lat: 23.39, baseValue: 81, amplitude: 3 },
      { id: 'dga', name: '东莞中部', lng: 113.85, lat: 23.0, baseValue: 79, amplitude: 3 },
      { id: 'sza', name: '深圳西部', lng: 113.86, lat: 22.56, baseValue: 77, amplitude: 2 },
    ],
    timeBands: [
      {
        startHour: 0,
        endHour: 6,
        metricBase: 76,
        hotspotDrift: -2,
        availabilityState: 'partial',
        trendLabel: '夜间风险带维持，模型结果趋稳',
        summary: '展示课题组模型结果与风险分区，夜间阶段用于演示任务留存结果。',
        statusLabel: '任务留存',
        confidenceLabel: '置信度 89%',
      },
      {
        startHour: 6,
        endHour: 12,
        metricBase: 80,
        hotspotDrift: 0,
        availabilityState: 'ready',
        trendLabel: '晨间风险带沿通道扩展',
        summary: '展示课题组模型结果与风险分区，上午阶段用于演示新任务接力。',
        statusLabel: '任务生成',
        confidenceLabel: '置信度 90%',
      },
      {
        startHour: 12,
        endHour: 18,
        metricBase: 82,
        hotspotDrift: 2,
        availabilityState: 'ready',
        trendLabel: '风险带持续扩展',
        summary: '展示课题组模型结果与风险分区，午后阶段适合作为 Demo 峰值。',
        statusLabel: '任务峰值',
        confidenceLabel: '置信度 91%',
      },
      {
        startHour: 18,
        endHour: 24,
        metricBase: 78,
        hotspotDrift: -1,
        availabilityState: 'partial',
        trendLabel: '傍晚风险区回缩，边缘区逐步减弱',
        summary: '展示课题组模型结果与风险分区，晚间阶段适合演示结果回缩。',
        statusLabel: '任务回落',
        confidenceLabel: '置信度 90%',
      },
    ],
  },
]
