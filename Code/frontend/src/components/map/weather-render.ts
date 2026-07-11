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
}

const WEATHER_PALETTES: Record<string, WeatherPaletteDefinition> = {
  'thermal-orange': {
    colors: ['#315dff', '#36c5ff', '#7ce7b0', '#ffd166', '#ff7b54', '#ff4d4d'],
    lineColor: 'rgba(255,255,255,0.18)',
  },
  'precip-cyan': {
    colors: ['#16324f', '#1c6dd0', '#1ec8ff', '#70f0ff', '#b7fff5', '#f5ffff'],
    lineColor: 'rgba(150, 236, 255, 0.22)',
  },
  'wind-blue': {
    colors: ['#10314b', '#1d6fa5', '#4bb9ff', '#84ddff', '#c4f3ff'],
    lineColor: 'rgba(170, 228, 255, 0.22)',
  },
  'magenta-yellow': {
    colors: ['#1a102a', '#5b1f7a', '#b832e0', '#ff5e9a', '#ffb347', '#fff2a6'],
    lineColor: 'rgba(255, 214, 153, 0.24)',
  },
}

function getPaletteDefinition(palette: string): WeatherPaletteDefinition {
  return WEATHER_PALETTES[palette] ?? WEATHER_PALETTES['wind-blue']
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

export function isRealtimeWeatherLayerId(layerId?: string | null) {
  if (!layerId) return false
  // 风场全高度变体（wind-field / wind-field-80m / wind-field-120m / wind-field-180m / wind-field-850hPa 等）
  if (layerId.startsWith('wind-field')) return true
  // 温度全高度变体（temperature / temperature-80m / temperature-120m / temperature-180m）
  if (layerId.startsWith('temperature')) return true
  // 其他 weatherengine 实时图层
  return ['precipitation', 'pressure', 'humidity', 'visibility'].includes(layerId)
}

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
  const ticks = hint.legend_ticks.length > 0 ? hint.legend_ticks : DEFAULT_LEGEND_TICKS
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
  const ticks = hint.legend_ticks.filter((tick): tick is number => typeof tick === 'number')
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
  const ticks = hint.legend_ticks.filter((tick): tick is number => typeof tick === 'number')
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
  const ticks = hint.legend_ticks.filter((tick): tick is number => typeof tick === 'number')
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
