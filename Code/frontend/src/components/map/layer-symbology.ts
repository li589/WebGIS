/**
 * 图层符号 / 图例解析：侧栏与 InfoPanel 共用。
 */
import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import {
  buildWeatherLegendStops,
  getPaletteColors,
  WEATHER_PALETTE_OPTIONS,
} from './weather-render'

export { WEATHER_PALETTE_OPTIONS, buildWeatherLegendStops, getPaletteColors }

export interface OverlaySymbologyMeta {
  palette?: string
  vmin?: number | null
  vmax?: number | null
  unit?: string
  opacity?: number
}

/** paletteOverride ?? renderHint ?? overlayMeta */
export function resolveEffectivePalette(options: {
  paletteOverride?: string | null
  renderHintPalette?: string | null
  overlayMetaPalette?: string | null
}): string | null {
  return options.paletteOverride
    ?? options.renderHintPalette
    ?? options.overlayMetaPalette
    ?? null
}

/**
 * 地图绘制是否会跟前端 palette 走。
 * - 天气 / 带 renderHint 的矢量作业：是（MapLibre paint）
 * - 仅 overlay 预渲染 PNG / 导入栅格：否
 */
export function isMapLinkedPalette(options: {
  hasRenderHint: boolean
  isImportedRaster?: boolean
}): boolean {
  if (options.isImportedRaster) return false
  return options.hasRenderHint
}

/** 从 renderHint / overlay meta / override 得到色带颜色序列 */
export function resolveSymbologyColors(options: {
  paletteOverride?: string | null
  renderHint?: Pick<WeatherLayerRenderHint, 'palette'> | null
  overlayMeta?: OverlaySymbologyMeta | null
  fallbackAccent?: string
}): string[] {
  const palette = resolveEffectivePalette({
    paletteOverride: options.paletteOverride,
    renderHintPalette: options.renderHint?.palette,
    overlayMetaPalette: options.overlayMeta?.palette,
  })
  if (palette) return getPaletteColors(palette)
  const accent = options.fallbackAccent ?? '#5ad5ff'
  return ['#1a2030', accent, '#e0f0ff']
}

/** 构造用于图例 stops 的最小 renderHint（overlay meta 场景） */
export function buildLegendHintFromOverlayMeta(
  meta: OverlaySymbologyMeta,
  primaryMetric = 'value',
): WeatherLayerRenderHint | null {
  if (!meta.palette) return null
  const vmin = typeof meta.vmin === 'number' ? meta.vmin : 0
  const vmax = typeof meta.vmax === 'number' ? meta.vmax : 1
  const mid = (vmin + vmax) / 2
  return {
    layer_id: 'overlay',
    paint_mode: 'raster_legend',
    palette: meta.palette,
    primary_metric: primaryMetric,
    unit_label: meta.unit ?? '',
    opacity: typeof meta.opacity === 'number' ? meta.opacity : 0.7,
    legend_ticks: [vmin, mid, vmax],
    notes: ['预渲染栅格图例；改配色不会重涂已生成的 PNG'],
  }
}

/** 合并 override 后的样式 hint（图例 / 配色 UI） */
export function resolveStyleRenderHint(options: {
  paletteOverride?: string | null
  renderHint?: WeatherLayerRenderHint | null
  overlayMeta?: OverlaySymbologyMeta | null
}): WeatherLayerRenderHint | null {
  const { renderHint, overlayMeta, paletteOverride } = options
  if (renderHint) {
    const palette = resolveEffectivePalette({
      paletteOverride,
      renderHintPalette: renderHint.palette,
    })
    return palette && palette !== renderHint.palette
      ? { ...renderHint, palette }
      : renderHint
  }
  if (!overlayMeta?.palette) return null
  const base = buildLegendHintFromOverlayMeta(overlayMeta)
  if (!base) return null
  const palette = resolveEffectivePalette({
    paletteOverride,
    overlayMetaPalette: overlayMeta.palette,
  })
  return palette && palette !== base.palette ? { ...base, palette } : base
}

export function hasRenderableSymbology(options: {
  renderHint?: WeatherLayerRenderHint | null
  overlayMeta?: OverlaySymbologyMeta | null
  isAdminBoundary?: boolean
  isImported?: boolean
  isImportedRaster?: boolean
}): boolean {
  if (options.isAdminBoundary || options.isImported || options.isImportedRaster) return false
  if (options.renderHint) return true
  return Boolean(options.overlayMeta?.palette)
}
