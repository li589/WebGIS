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

/**
 * 反演产物「变量角色 → 计量单位」（2026-10-15）。
 *
 * ## 为什么会有这个表（后端把变量标签当成了单位）
 * 产物物化 / 懒加载两处都把 **label** 塞进了 overlay 的 unit 字段：
 *   - `app/data_io/services/raster_timeseries.py`：`register_overlay(..., unit=label)`
 *   - `app/services/overlay_registry.py`：`unit = str(meta.get("unit") or meta.get("label") or "")`
 * ⇒ `/overlay-bounds` 返回的 `meta.unit` 实际是 `SM / VOD / OMEGA` 这类**角色码**，
 * 前端若原样展示，色带右端就出现「0.5 SM」这种字样（用户 2026-10-15 报障）。
 *
 * ## 展示口径（用户口径）
 * - **SM**（土壤体积含水量）＝ `m³/m³`，要显示；
 * - **VOD**（植被光学厚度）、**ω**（等效散射反照率）为无量纲量 ⇒ **不显示单位**；
 * - 角色码本身（SM / VOD / OMEGA）永远不当单位展示。
 *
 * 后端若日后改为真实单位，`meta.unit` 不是角色码时会原样透传（见各调用方优先级）。
 */
export const PRODUCT_ROLE_CODES = ['SM', 'VOD', 'OMEGA'] as const

/** 角色 → 单位。**无量纲量（VOD / ω）不入表** ⇒ 查不到即「不显示单位」。 */
const ROLE_UNITS: Record<string, string> = {
  SM: 'm³/m³',
}

/** 该字符串是否就是变量角色码（用来识别「标签被当成单位」的后端返回值） */
export function isProductRoleCode(value: string | null | undefined): boolean {
  const key = String(value ?? '')
    .trim()
    .toUpperCase()
  return (PRODUCT_ROLE_CODES as readonly string[]).includes(key)
}

/** 按变量角色取单位；未知 / 无量纲角色返回空串（约定为空串即不显示单位） */
export function unitForRole(role: string | null | undefined): string {
  const key = String(role ?? '')
    .trim()
    .toUpperCase()
  return ROLE_UNITS[key] ?? ''
}

/** paletteOverride ?? renderHint ?? overlayMeta */
export function resolveEffectivePalette(options: {
  paletteOverride?: string | null
  renderHintPalette?: string | null
  overlayMetaPalette?: string | null
}): string | null {
  return options.paletteOverride ?? options.renderHintPalette ?? options.overlayMetaPalette ?? null
}

/**
 * 地图绘制是否会跟前端 palette / 值域走。
 * - 天气 / 带 renderHint 的作业（含反演 COG）：是
 * - 有源 overlay / 导入 GeoTIFF（supports_recolor）：是
 * - 仅烘焙 PNG 无源且无 renderHint：否
 */
export function isMapLinkedPalette(options: {
  hasRenderHint: boolean
  isImportedRaster?: boolean
  supportsRecolor?: boolean
}): boolean {
  if (options.supportsRecolor) return true
  if (options.hasRenderHint) return true
  return false
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
    // 2026-10-15：后端把变量标签写进了 unit（meta.unit = SM / VOD / OMEGA）⇒
    // 角色码按口径换成真实单位（SM= m³/m³；无量纲 ⇒ 空串，不显示）
    unit_label: isProductRoleCode(meta.unit) ? unitForRole(meta.unit) : (meta.unit ?? ''),
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
    typeof overlayMeta?.vmin === 'number' ? overlayMeta.vmin : ticks.length ? ticks[0] : 0
  const baseMax =
    typeof overlayMeta?.vmax === 'number'
      ? overlayMeta.vmax
      : ticks.length > 1
        ? ticks[ticks.length - 1]
        : ticks.length === 1
          ? ticks[0]
          : 1
  const lo =
    typeof vminOverride === 'number' && Number.isFinite(vminOverride) ? vminOverride : baseMin
  const hi =
    typeof vmaxOverride === 'number' && Number.isFinite(vmaxOverride) ? vmaxOverride : baseMax
  if (
    (typeof vminOverride === 'number' && Number.isFinite(vminOverride)) ||
    (typeof vmaxOverride === 'number' && Number.isFinite(vmaxOverride))
  ) {
    const a = Math.min(lo, hi)
    const b = Math.max(lo, hi)
    const mid = (a + b) / 2
    const span = b - a
    const round = (v: number) => (span >= 10 ? Math.round(v * 10) / 10 : Math.round(v * 100) / 100)
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
