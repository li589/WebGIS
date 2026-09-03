/**
 * 图层符号 / 图例解析：侧栏与 InfoPanel 共用。
 */
import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import {
  buildWeatherLegendGradient,
  buildWeatherLegendStops,
  getPaletteColors,
  paletteIdsEqual,
  resolveCanonicalPaletteId,
  resolveCanonicalPaletteIdStrict,
  WEATHER_PALETTE_OPTIONS,
} from './weather-render'

export {
  WEATHER_PALETTE_OPTIONS,
  buildWeatherLegendGradient,
  buildWeatherLegendStops,
  getPaletteColors,
  paletteIdsEqual,
  resolveCanonicalPaletteId,
  resolveCanonicalPaletteIdStrict,
}

// D1 修复后：类型真源在 src/types/overlay-symbology.ts，此处 re-export 保持兼容
export type { OverlaySymbologyMeta } from '../../types/overlay-symbology'
import type { OverlaySymbologyMeta } from '../../types/overlay-symbology'

/** paletteOverride ?? renderHint ?? overlayMeta */
export function resolveEffectivePalette(options: {
  paletteOverride?: string | null
  renderHintPalette?: string | null
  overlayMetaPalette?: string | null
}): string | null {
  return options.paletteOverride ?? options.renderHintPalette ?? options.overlayMetaPalette ?? null
}

/**
 * 地图绘制是否会跟前端 palette 走。
 * - 天气 / 带 renderHint 的矢量作业：是（MapLibre paint）
 * - 有源 overlay / 导入 GeoTIFF（supports_recolor）：是（服务端参数化 PNG）
 * - 仅烘焙 PNG 无源：否
 */
export function isMapLinkedPalette(options: {
  hasRenderHint: boolean
  isImportedRaster?: boolean
  supportsRecolor?: boolean
}): boolean {
  if (options.supportsRecolor) return true
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
    notes: ['有源图层可改配色；地图与图例同步重着色'],
  }
}

/** 合并 override 后的样式 hint（图例 / 配色 UI） */
export function resolveStyleRenderHint(options: {
  paletteOverride?: string | null
  /** 用户覆盖值域：写入 legend_ticks 两端，驱动图例与地图同源 */
  vminOverride?: number | null
  vmaxOverride?: number | null
  renderHint?: WeatherLayerRenderHint | null
  overlayMeta?: OverlaySymbologyMeta | null
}): WeatherLayerRenderHint | null {
  const { renderHint, overlayMeta, paletteOverride, vminOverride, vmaxOverride } = options
  let hint: WeatherLayerRenderHint | null = null
  if (renderHint) {
    const palette = resolveEffectivePalette({
      paletteOverride,
      renderHintPalette: renderHint.palette,
    })
    hint = palette && palette !== renderHint.palette ? { ...renderHint, palette } : renderHint
  } else if (overlayMeta?.palette) {
    const base = buildLegendHintFromOverlayMeta(overlayMeta)
    if (!base) return null
    const palette = resolveEffectivePalette({
      paletteOverride,
      overlayMetaPalette: overlayMeta.palette,
    })
    hint = palette && palette !== base.palette ? { ...base, palette } : base
  }
  if (!hint) return null

  const ticks = (hint.legend_ticks ?? []).filter(
    (t): t is number => typeof t === 'number' && Number.isFinite(t),
  )
  const baseMin =
    typeof overlayMeta?.vmin === 'number'
      ? overlayMeta.vmin
      : ticks.length
        ? ticks[0]
        : 0
  const baseMax =
    typeof overlayMeta?.vmax === 'number'
      ? overlayMeta.vmax
      : ticks.length > 1
        ? ticks[ticks.length - 1]
        : ticks.length === 1
          ? ticks[0]
          : 1
  const lo = typeof vminOverride === 'number' && Number.isFinite(vminOverride) ? vminOverride : baseMin
  const hi = typeof vmaxOverride === 'number' && Number.isFinite(vmaxOverride) ? vmaxOverride : baseMax
  if (
    (typeof vminOverride === 'number' && Number.isFinite(vminOverride)) ||
    (typeof vmaxOverride === 'number' && Number.isFinite(vmaxOverride))
  ) {
    const a = Math.min(lo, hi)
    const b = Math.max(lo, hi)
    const mid = (a + b) / 2
    const span = b - a
    const round = (v: number) =>
      span >= 10 ? Math.round(v * 10) / 10 : Math.round(v * 100) / 100
    return { ...hint, legend_ticks: [round(a), round(mid), round(b)] }
  }
  return hint
}

export function hasRenderableSymbology(options: {
  renderHint?: WeatherLayerRenderHint | null
  overlayMeta?: OverlaySymbologyMeta | null
  isAdminBoundary?: boolean
  isImported?: boolean
  isImportedRaster?: boolean
}): boolean {
  if (options.isAdminBoundary || options.isImported) return false
  // 导入栅格若可重着色也展示图例/配色
  if (options.isImportedRaster && !options.overlayMeta?.supports_recolor) return false
  if (options.renderHint) return true
  return Boolean(options.overlayMeta?.palette)
}

/** 拼 overlay-preview / overlay-tiles 样式 query（无覆盖时仍可传默认 palette 触发动态着色） */
export function buildOverlayStyleQuery(params: {
  time?: string | null
  palette?: string | null
  vmin?: number | null
  vmax?: number | null
  nodataMode?: string | null
  nodataColor?: string | null
  /** 仅当用户改过样式或明确要求动态着色时附加 */
  forceStyle?: boolean
}): string {
  const q = new URLSearchParams()
  if (params.time) q.set('time', params.time)
  const force =
    params.forceStyle ||
    Boolean(params.palette) ||
    params.vmin != null ||
    params.vmax != null ||
    (params.nodataMode && params.nodataMode !== 'transparent') ||
    Boolean(params.nodataColor)
  if (force) {
    if (params.palette) q.set('palette', params.palette)
    if (params.vmin != null && Number.isFinite(params.vmin)) q.set('min_value', String(params.vmin))
    if (params.vmax != null && Number.isFinite(params.vmax)) q.set('max_value', String(params.vmax))
    if (params.nodataMode) q.set('nodata_mode', params.nodataMode)
    if (params.nodataColor) q.set('nodata_color', params.nodataColor)
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}
