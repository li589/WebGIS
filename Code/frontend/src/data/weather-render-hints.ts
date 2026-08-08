/**
 * 天气图层默认渲染提示数据表与构建函数。
 *
 * 从 components/map/weather-render.ts 提取（D1 依赖倒置修复）：
 * 本模块为纯数据 + 纯函数，stores/ 可直接依赖；
 * components/map/weather-render.ts re-export 保持既有组件导入兼容。
 */
import type { RuntimeLayerDescriptor, WeatherLayerRenderHint } from '../services/runtime-api'

export const DEFAULT_LEGEND_TICKS = [0, 1, 2, 3]

export const WEATHER_RENDER_HINTS: Record<string, WeatherLayerRenderHint> = {
  'wind-field': {
    layer_id: 'wind-field',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_10m',
    unit_label: 'm/s',
    opacity: 0.7,
    legend_ticks: [0, 5, 10, 15, 20, 25, 30],
    notes: ['10 m 风场粒子流'],
  },
  'wind-field-80m': {
    layer_id: 'wind-field-80m',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_80m',
    unit_label: 'm/s',
    opacity: 0.7,
    legend_ticks: [0, 5, 10, 15, 20],
    notes: ['80 m 风场粒子流'],
  },
  'wind-field-120m': {
    layer_id: 'wind-field-120m',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_120m',
    unit_label: 'm/s',
    opacity: 0.7,
    legend_ticks: [0, 5, 10, 15, 20, 25],
    notes: ['120 m 风场粒子流'],
  },
  'wind-field-180m': {
    layer_id: 'wind-field-180m',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_180m',
    unit_label: 'm/s',
    opacity: 0.7,
    legend_ticks: [0, 7, 14, 21, 28, 35],
    notes: ['180 m 风场粒子流'],
  },
  'wind-field-850hPa': {
    layer_id: 'wind-field-850hPa',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_850hPa',
    unit_label: 'm/s',
    opacity: 0.7,
    legend_ticks: [0, 10, 20, 30, 40, 50],
    notes: ['850 hPa 风场粒子流'],
  },
  'wind-field-500hPa': {
    layer_id: 'wind-field-500hPa',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_500hPa',
    unit_label: 'm/s',
    opacity: 0.74,
    legend_ticks: [0, 15, 30, 45, 60, 75],
    notes: ['500 hPa 风场粒子流'],
  },
  'wind-field-200hPa': {
    layer_id: 'wind-field-200hPa',
    paint_mode: 'particle_flow',
    palette: 'wind-blue',
    primary_metric: 'wind_speed_200hPa',
    unit_label: 'm/s',
    opacity: 0.7,
    legend_ticks: [0, 20, 40, 60, 80, 100],
    notes: ['200 hPa 风场粒子流'],
  },
  temperature: {
    layer_id: 'temperature',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'temperature_2m',
    unit_label: '°C',
    opacity: 0.82,
    legend_ticks: [-10, 0, 10, 20, 30, 40],
    notes: ['2 m 气温连续色场（网格填充）'],
  },
  'temperature-80m': {
    layer_id: 'temperature-80m',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'temperature_80m',
    unit_label: '°C',
    opacity: 0.82,
    legend_ticks: [-10, 0, 10, 20, 30, 40],
    notes: ['80 m 气温连续色场（网格填充）'],
  },
  'temperature-120m': {
    layer_id: 'temperature-120m',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'temperature_120m',
    unit_label: '°C',
    opacity: 0.82,
    legend_ticks: [-10, 0, 10, 20, 30, 40],
    notes: ['120 m 气温连续色场（网格填充）'],
  },
  'temperature-180m': {
    layer_id: 'temperature-180m',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'temperature_180m',
    unit_label: '°C',
    opacity: 0.82,
    legend_ticks: [-10, 0, 10, 20, 30, 40],
    notes: ['180 m 气温连续色场（网格填充）'],
  },
  precipitation: {
    layer_id: 'precipitation',
    paint_mode: 'grid_fill',
    palette: 'precip-cyan',
    primary_metric: 'precipitation',
    unit_label: 'mm',
    opacity: 0.86,
    legend_ticks: [0, 1, 5, 10, 25, 50],
    notes: ['降水量连续色场（网格填充）'],
  },
  pressure: {
    layer_id: 'pressure',
    paint_mode: 'grid_fill',
    palette: 'magenta-yellow',
    primary_metric: 'pressure_msl',
    unit_label: 'hPa',
    opacity: 0.75,
    legend_ticks: [980, 1000, 1010, 1020, 1040],
    notes: ['海平面气压连续色场'],
  },
  humidity: {
    layer_id: 'humidity',
    paint_mode: 'grid_fill',
    palette: 'greens',
    primary_metric: 'relative_humidity_2m',
    unit_label: '%',
    opacity: 0.75,
    legend_ticks: [0, 20, 40, 60, 80, 100],
    notes: ['相对湿度连续色场'],
  },
  visibility: {
    layer_id: 'visibility',
    paint_mode: 'grid_fill',
    palette: 'yellow-red',
    primary_metric: 'visibility',
    unit_label: 'm',
    opacity: 0.75,
    legend_ticks: [0, 1000, 5000, 10000, 20000, 30000],
    notes: ['能见度连续色场'],
  },
  'cloud-cover': {
    layer_id: 'cloud-cover',
    paint_mode: 'grid_fill',
    palette: 'greens',
    primary_metric: 'cloud_cover',
    unit_label: '%',
    opacity: 0.8,
    legend_ticks: [0, 20, 40, 60, 80, 100],
    notes: ['总云量连续色场'],
  },
  dewpoint: {
    layer_id: 'dewpoint',
    paint_mode: 'grid_fill',
    palette: 'thermal-orange',
    primary_metric: 'dew_point_2m',
    unit_label: 'C',
    opacity: 0.78,
    legend_ticks: [-10, 0, 10, 15, 20, 25],
    notes: ['露点温度连续色场（网格填充）'],
  },
}

/** 根据 catalogId 构建默认天气渲染提示（tile manager 路径下无 jobLayer 时使用）。 */
export function buildDefaultWeatherRenderHint(
  layerId?: string | null,
  descriptor?: RuntimeLayerDescriptor | null,
): WeatherLayerRenderHint | null {
  if (!layerId) return null
  const local = WEATHER_RENDER_HINTS[layerId] ?? null
  const capabilityHint = descriptor?.capabilities
  const styleHint = descriptor?.style
  if (
    capabilityHint?.paint_mode &&
    capabilityHint.primary_metric &&
    styleHint?.palette &&
    styleHint.unit_label
  ) {
    const legendFromCap = capabilityHint.legend_ticks ?? []
    return {
      layer_id: layerId,
      paint_mode: capabilityHint.paint_mode,
      // 本地 canonical palette 优先；目录别名（blue-cyan 等）仅作回落，经 alias 解析
      palette: local?.palette || styleHint.palette || 'thermal-orange',
      primary_metric: capabilityHint.primary_metric,
      // 单位同样优先本地（°C / mm），避免目录 degC / mm/h 与图例文案不一致
      unit_label: local?.unit_label || styleHint.unit_label,
      opacity:
        typeof local?.opacity === 'number'
          ? local.opacity
          : typeof styleHint.opacity === 'number'
            ? styleHint.opacity
            : 0.7,
      // 刻度优先后端能力（与 WEATHER_LAYER_SPECS 同源）；空则回落本地
      legend_ticks:
        legendFromCap.length > 0 ? legendFromCap : (local?.legend_ticks ?? DEFAULT_LEGEND_TICKS),
      notes: capabilityHint.notes?.length ? capabilityHint.notes : (local?.notes ?? []),
    }
  }
  return local
}
