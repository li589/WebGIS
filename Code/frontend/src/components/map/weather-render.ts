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
}

function getPaletteDefinition(palette: string): WeatherPaletteDefinition {
  return WEATHER_PALETTES[palette] ?? WEATHER_PALETTES['wind-blue']
}

export function isRealtimeWeatherLayerId(layerId?: string | null) {
  return layerId === 'wind-field' || layerId === 'temperature' || layerId === 'precipitation'
}

export function buildWeatherLegendStops(hint: WeatherLayerRenderHint): WeatherLegendStop[] {
  const palette = getPaletteDefinition(hint.palette)
  const ticks = hint.legend_ticks.length > 0 ? hint.legend_ticks : [0, 1, 2, 3]
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
    minTick, 3.5,
    maxTick, 9.5,
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
    minTick, 0.54,
    maxTick, 1.12,
  ] as unknown as ExpressionSpecification
}

export function getWeatherLineColor(hint: WeatherLayerRenderHint) {
  return getPaletteDefinition(hint.palette).lineColor
}

export function getWeatherFillOpacity(hint: WeatherLayerRenderHint, layerOpacity: number) {
  return Math.max(0.08, Math.min(0.9, hint.opacity * layerOpacity))
}

export function getWeatherLineOpacity(hint: WeatherLayerRenderHint, layerOpacity: number) {
  return Math.max(0.08, Math.min(0.42, hint.opacity * layerOpacity * 0.46))
}
