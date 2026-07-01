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
    name: '风场',
    category: '气象场',
    metricLabel: '核心指标',
    metricUnit: 'm/s',
    metricPrecision: 1,
    updateLabel: '每 10 分钟刷新',
    sourceLabel: 'ECMWF + 本地处理',
    accentColor: '#67d4ff',
    accentGlow: 'rgba(103, 212, 255, 0.34)',
    chipTone: 'rgba(103, 212, 255, 0.18)',
    dataState: {
      mode: 'mixed',
      label: 'Demo 驱动',
      emptyLabel: '待接入真实风场格点后替换',
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
