import type { ExpressionSpecification } from 'maplibre-gl'

import type { WeatherLayerRenderHint } from '../../services/runtime-api'

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
