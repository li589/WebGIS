import type { ExpressionSpecification } from 'maplibre-gl'

import type { RuntimeLayerDescriptor, WeatherLayerRenderHint } from '../../services/runtime-api'

export interface WeatherLegendStop {
  value: number | string
  label: string
  color: string
}

interface WeatherPaletteDefinition {
  colors: string[]
  lineColor: string
  /** UI 显示名 */
  label: string
  /** 配色类型：sequential(递进) / diverging(发散) / qualitative(定性) */
  type: 'sequential' | 'diverging' | 'qualitative'
}

const WEATHER_PALETTES: Record<string, WeatherPaletteDefinition> = {
  'thermal-orange': {
    colors: ['#315dff', '#36c5ff', '#7ce7b0', '#ffd166', '#ff7b54', '#ff4d4d'],
    lineColor: 'rgba(255,255,255,0.18)',
    label: '热力橙红',
    type: 'sequential',
  },
  'precip-cyan': {
    colors: ['#16324f', '#1c6dd0', '#1ec8ff', '#70f0ff', '#b7fff5', '#f5ffff'],
    lineColor: 'rgba(150, 236, 255, 0.22)',
    label: '降水青蓝',
    type: 'sequential',
  },
  'wind-blue': {
    colors: ['#10314b', '#1d6fa5', '#4bb9ff', '#84ddff', '#c4f3ff'],
    lineColor: 'rgba(170, 228, 255, 0.22)',
    label: '风场蓝',
    type: 'sequential',
  },
  'magenta-yellow': {
    colors: ['#1a102a', '#5b1f7a', '#b832e0', '#ff5e9a', '#ffb347', '#fff2a6'],
    lineColor: 'rgba(255, 214, 153, 0.24)',
    label: '品红黄',
    type: 'diverging',
  },
  'viridis': {
    colors: ['#440154', '#414487', '#2a788e', '#22a884', '#7ad151', '#fde725'],
    lineColor: 'rgba(200, 220, 100, 0.20)',
    label: 'Viridis 科学',
    type: 'sequential',
  },
  'spectral': {
    colors: ['#9e0142', '#d53e4f', '#f46d43', '#fdae61', '#fee08b', '#e6f598', '#abdda4', '#66c2a5', '#3288bd'],
    lineColor: 'rgba(255, 255, 255, 0.18)',
    label: '光谱彩虹',
    type: 'diverging',
  },
  'blues': {
    colors: ['#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#084594'],
    lineColor: 'rgba(150, 200, 255, 0.22)',
    label: '渐变蓝',
    type: 'sequential',
  },
  'reds': {
    colors: ['#fff5f0', '#fee0d2', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#99000d'],
    lineColor: 'rgba(255, 180, 150, 0.22)',
    label: '渐变红',
    type: 'sequential',
  },
  'greens': {
    colors: ['#f7fcf5', '#e5f5e0', '#c7e9c0', '#a1d99b', '#74c476', '#41ab5d', '#238b45', '#005a32'],
    lineColor: 'rgba(150, 230, 150, 0.22)',
    label: '渐变绿',
    type: 'sequential',
  },
  'yellow-red': {
    colors: ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c', '#fc4e2a', '#e31a1c', '#b10026'],
    lineColor: 'rgba(255, 200, 100, 0.22)',
    label: '黄红外推',
    type: 'sequential',
  },
  'blue-green': {
    colors: ['#08306b', '#2171b5', '#6baed6', '#66c2a4', '#41ab5d', '#238b45'],
    lineColor: 'rgba(150, 220, 180, 0.22)',
    label: '蓝绿渐变',
    type: 'sequential',
  },
  'red-blue': {
    colors: ['#b2182b', '#ef8a62', '#fddbc7', '#f7f7f7', '#d1e5f0', '#67a9cf', '#2166ac'],
    lineColor: 'rgba(255, 255, 255, 0.20)',
    label: '红蓝发散',
    type: 'diverging',
  },
  'purple-orange': {
    colors: ['#2d1b3d', '#542466', '#8c2d80', '#c63e6c', '#f08050', '#ffb347', '#ffe066'],
    lineColor: 'rgba(255, 200, 120, 0.24)',
    label: '紫橙渐变',
    type: 'diverging',
  },
  'dark-rainbow': {
    colors: ['#1a0033', '#003380', '#0066cc', '#00cc66', '#cccc00', '#cc6600', '#cc0000'],
    lineColor: 'rgba(255, 255, 255, 0.20)',
    label: '暗色彩虹',
    type: 'sequential',
  },
}

/** 配色方案选项列表（供 UI 选择器使用） */
export interface WeatherPaletteOption {
  id: string
  label: string
  type: 'sequential' | 'diverging' | 'qualitative'
  colors: string[]
}

export const WEATHER_PALETTE_OPTIONS: WeatherPaletteOption[] = Object.entries(WEATHER_PALETTES).map(
  ([id, def]) => ({ id, label: def.label, type: def.type, colors: def.colors }),
)

/** 将配色方案转换为粒子流色阶（12 色插值） */
export function paletteToParticleColors(paletteId: string): string[] {
  const def = WEATHER_PALETTES[paletteId]
  if (!def) return []
  const src = def.colors
  const target = 12
  if (src.length >= target) return src.slice(0, target)
  // 线性插值扩展到 12 色
  const result: string[] = []
  for (let i = 0; i < target; i++) {
    const ratio = i / (target - 1)
    const srcIdx = ratio * (src.length - 1)
    const lo = Math.floor(srcIdx)
    const hi = Math.min(lo + 1, src.length - 1)
    const frac = srcIdx - lo
    result.push(lerpHexColor(src[lo], src[hi], frac))
  }
  return result
}

function lerpHexColor(a: string, b: string, t: number): string {
  const pa = parseHex(a)
  const pb = parseHex(b)
  if (!pa || !pb) return a
  const r = Math.round(pa[0] + (pb[0] - pa[0]) * t)
  const g = Math.round(pa[1] + (pb[1] - pa[1]) * t)
  const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t)
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${bl.toString(16).padStart(2, '0')}`
}

function parseHex(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return null
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function getPaletteDefinition(palette: string): WeatherPaletteDefinition {
  return WEATHER_PALETTES[palette] ?? WEATHER_PALETTES['wind-blue']
}

/** 供侧栏 / InfoPanel 读取色带颜色 */
export function getPaletteColors(paletteId: string): string[] {
  return getPaletteDefinition(paletteId).colors
}

// ── 渲染参数常量 ─────────────────────────────────────────

/** 天气图层填充不透明度范围（柔和低调：上限压低，不抢底图视觉焦点） */
const FILL_OPACITY_MIN = 0.06
const FILL_OPACITY_MAX = 0.7

/** 天气图层线条不透明度范围及相对填充的折扣系数 */
const LINE_OPACITY_MIN = 0.06
const LINE_OPACITY_MAX = 0.32
const LINE_OPACITY_RATIO = 0.46

/** 天气点半径映射范围（像素） */
const POINT_RADIUS_MIN = 3.0
const POINT_RADIUS_MAX = 7.0

/** 风向箭头大小映射范围 */
const ARROW_SIZE_MIN = 0.45
const ARROW_SIZE_MAX = 0.9

/** 默认图例刻度（后端未提供时使用） */
const DEFAULT_LEGEND_TICKS = [0, 1, 2, 3]

const WEATHER_RENDER_HINTS: Record<string, WeatherLayerRenderHint> = {
  'wind-field': {
    layer_id: 'wind-field',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_10m',
    unit_label: 'm/s',
    opacity: 0.82,
    legend_ticks: [0, 5, 10, 15, 20],
    notes: ['10 m 风场粒子流'],
  },
  'wind-field-80m': {
    layer_id: 'wind-field-80m',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_80m',
    unit_label: 'm/s',
    opacity: 0.82,
    legend_ticks: [0, 5, 10, 15, 20],
    notes: ['80 m 风场粒子流'],
  },
  'wind-field-120m': {
    layer_id: 'wind-field-120m',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_120m',
    unit_label: 'm/s',
    opacity: 0.82,
    legend_ticks: [0, 5, 10, 15, 20, 25],
    notes: ['120 m 风场粒子流'],
  },
  'wind-field-180m': {
    layer_id: 'wind-field-180m',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_180m',
    unit_label: 'm/s',
    opacity: 0.82,
    legend_ticks: [0, 7, 14, 21, 28, 35],
    notes: ['180 m 风场粒子流'],
  },
  'wind-field-850hPa': {
    layer_id: 'wind-field-850hPa',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_850hPa',
    unit_label: 'm/s',
    opacity: 0.78,
    legend_ticks: [0, 10, 20, 30, 40, 50],
    notes: ['850 hPa 风场粒子流'],
  },
  'wind-field-500hPa': {
    layer_id: 'wind-field-500hPa',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_500hPa',
    unit_label: 'm/s',
    opacity: 0.78,
    legend_ticks: [0, 15, 30, 45, 60, 75],
    notes: ['500 hPa 风场粒子流'],
  },
  'wind-field-200hPa': {
    layer_id: 'wind-field-200hPa',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_200hPa',
    unit_label: 'm/s',
    opacity: 0.78,
    legend_ticks: [0, 20, 40, 60, 80, 100],
    notes: ['200 hPa 风场粒子流'],
  },
  'temperature': {
    layer_id: 'temperature',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'temperature_2m',
    unit_label: '°C',
    opacity: 0.7,
    legend_ticks: [-10, 0, 10, 20, 30, 40],
    notes: ['2 m 气温填充'],
  },
  'temperature-80m': {
    layer_id: 'temperature-80m',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'temperature_80m',
    unit_label: '°C',
    opacity: 0.7,
    legend_ticks: [-10, 0, 10, 20, 30, 40],
    notes: ['80 m 气温填充'],
  },
  'temperature-120m': {
    layer_id: 'temperature-120m',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'temperature_120m',
    unit_label: '°C',
    opacity: 0.7,
    legend_ticks: [-10, 0, 10, 20, 30, 40],
    notes: ['120 m 气温填充'],
  },
  'temperature-180m': {
    layer_id: 'temperature-180m',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'temperature_180m',
    unit_label: '°C',
    opacity: 0.7,
    legend_ticks: [-10, 0, 10, 20, 30, 40],
    notes: ['180 m 气温填充'],
  },
  'precipitation': {
    layer_id: 'precipitation',
    paint_mode: 'grid_fill',
    palette: 'precip-cyan',
    primary_metric: 'precipitation',
    unit_label: 'mm',
    opacity: 0.72,
    legend_ticks: [0, 1, 5, 10, 20, 50],
    notes: ['降水量填充'],
  },
  'pressure': {
    layer_id: 'pressure',
    paint_mode: 'grid_fill',
    palette: 'magenta-yellow',
    primary_metric: 'pressure_msl',
    unit_label: 'hPa',
    opacity: 0.68,
    legend_ticks: [960, 980, 1000, 1020, 1040],
    notes: ['海平面气压填充'],
  },
  'humidity': {
    layer_id: 'humidity',
    paint_mode: 'grid_fill',
    palette: 'precip-cyan',
    primary_metric: 'relative_humidity_2m',
    unit_label: '%',
    opacity: 0.68,
    legend_ticks: [0, 20, 40, 60, 80, 100],
    notes: ['相对湿度填充'],
  },
  'visibility': {
    layer_id: 'visibility',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'visibility',
    unit_label: 'm',
    opacity: 0.68,
    legend_ticks: [0, 5000, 10000, 20000, 30000],
    notes: ['能见度填充'],
  },
}

/** 根据 catalogId 构建默认天气渲染提示（tile manager 路径下无 jobLayer 时使用）。 */
export function buildDefaultWeatherRenderHint(
  layerId?: string | null,
  descriptor?: RuntimeLayerDescriptor | null,
): WeatherLayerRenderHint | null {
  if (!layerId) return null
  const capabilityHint = descriptor?.capabilities
  const styleHint = descriptor?.style
  if (
    capabilityHint?.paint_mode
    && capabilityHint.primary_metric
    && styleHint?.palette
    && styleHint.unit_label
  ) {
    return {
      layer_id: layerId,
      paint_mode: capabilityHint.paint_mode,
      palette: styleHint.palette,
      primary_metric: capabilityHint.primary_metric,
      unit_label: styleHint.unit_label,
      opacity: typeof styleHint.opacity === 'number' ? styleHint.opacity : 1,
      legend_ticks: capabilityHint.legend_ticks ?? [],
      notes: capabilityHint.notes ?? [],
    }
  }
  return WEATHER_RENDER_HINTS[layerId] ?? null
}

export function buildWeatherLegendStops(hint: WeatherLayerRenderHint): WeatherLegendStop[] {
  const palette = getPaletteDefinition(hint.palette)
  const legendTicks = hint.legend_ticks ?? []
  const ticks = legendTicks.length > 0 ? legendTicks : DEFAULT_LEGEND_TICKS
  return ticks.map((tick, index) => ({
    value: tick,
    label: typeof tick === 'number' ? `${tick} ${hint.unit_label}`.trim() : String(tick),
    color: palette.colors[Math.min(index, palette.colors.length - 1)],
  }))
}

export function buildWeatherFillColorExpression(hint: WeatherLayerRenderHint): ExpressionSpecification {
  const legendStops = buildWeatherLegendStops(hint)
  const metricKey = hint.primary_metric
  const baseColor = legendStops[0]?.color ?? '#4bb9ff'
  const expression: Array<string | number | ExpressionSpecification> = [
    'step',
    ['coalesce', ['to-number', ['get', metricKey]], 0] as unknown as ExpressionSpecification,
    baseColor,
  ]

  for (let index = 1; index < legendStops.length; index += 1) {
    const stop = legendStops[index]
    if (typeof stop.value !== 'number') continue
    expression.push(stop.value, stop.color)
  }
  return expression as ExpressionSpecification
}

export function buildWeatherPointColorExpression(hint: WeatherLayerRenderHint): ExpressionSpecification {
  return buildWeatherFillColorExpression(hint)
}

export function buildWeatherPointRadiusExpression(hint: WeatherLayerRenderHint): ExpressionSpecification {
  const ticks = (hint.legend_ticks ?? []).filter((tick): tick is number => typeof tick === 'number')
  const minTick = ticks[0] ?? 0
  const maxTick = ticks[ticks.length - 1] ?? 20
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', hint.primary_metric]], 0],
    minTick, POINT_RADIUS_MIN,
    maxTick, POINT_RADIUS_MAX,
  ] as unknown as ExpressionSpecification
}

export function buildWeatherHeatmapColorExpression(hint: WeatherLayerRenderHint): ExpressionSpecification {
  const palette = getPaletteDefinition(hint.palette).colors
  const lastIndex = Math.max(1, palette.length - 1)
  const expression: Array<string | number> = [
    'interpolate',
    ['linear'] as unknown as number,
    ['heatmap-density'] as unknown as number,
    0,
    'rgba(0, 0, 0, 0)',
  ]
  for (let index = 0; index < palette.length; index += 1) {
    const stop = Number(((index + 1) / (lastIndex + 1)).toFixed(3))
    expression.push(stop, palette[index])
  }
  return expression as unknown as ExpressionSpecification
}

export function buildWeatherHeatmapWeightExpression(hint: WeatherLayerRenderHint): ExpressionSpecification {
  const ticks = (hint.legend_ticks ?? []).filter((tick): tick is number => typeof tick === 'number')
  const minTick = ticks[0] ?? 0
  const maxTick = ticks[ticks.length - 1] ?? 100
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', hint.primary_metric]], 0],
    minTick, 0,
    maxTick, 1,
  ] as unknown as ExpressionSpecification
}

export function buildWeatherArrowSizeExpression(hint: WeatherLayerRenderHint): ExpressionSpecification {
  const ticks = (hint.legend_ticks ?? []).filter((tick): tick is number => typeof tick === 'number')
  const minTick = ticks[0] ?? 0
  const maxTick = ticks[ticks.length - 1] ?? 20
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', hint.primary_metric]], 0],
    minTick, ARROW_SIZE_MIN,
    maxTick, ARROW_SIZE_MAX,
  ] as unknown as ExpressionSpecification
}

export function getWeatherLineColor(hint: WeatherLayerRenderHint) {
  return getPaletteDefinition(hint.palette).lineColor
}

export function getWeatherFillOpacity(hint: WeatherLayerRenderHint, layerOpacity: number) {
  return Math.max(FILL_OPACITY_MIN, Math.min(FILL_OPACITY_MAX, hint.opacity * layerOpacity))
}

export function getWeatherLineOpacity(hint: WeatherLayerRenderHint, layerOpacity: number) {
  return Math.max(LINE_OPACITY_MIN, Math.min(LINE_OPACITY_MAX, hint.opacity * layerOpacity * LINE_OPACITY_RATIO))
}
