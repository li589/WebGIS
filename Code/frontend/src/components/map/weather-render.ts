import type { ExpressionSpecification } from 'maplibre-gl'

import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import { DEFAULT_LEGEND_TICKS } from '../../data/weather-render-hints'

// D1 修复后：数据表与构建函数真源在 src/data/weather-render-hints.ts
export { buildDefaultWeatherRenderHint } from '../../data/weather-render-hints'

export interface WeatherLegendStop {
  value: number | string
  label: string
  color: string
}

import {
  GENERATED_PALETTE_ALIASES,
  GENERATED_WEATHER_PALETTES,
} from '../../data/weather-palettes-generated'

interface WeatherPaletteDefinition {
  colors: string[]
  lineColor: string
  /** UI 显示名 */
  label: string
  /** 配色类型：sequential(递进) / diverging(发散) / qualitative(定性) */
  type: 'sequential' | 'diverging' | 'qualitative'
  /** 是否进选择器（生成物字段；后端独有色带 false） */
  exposed?: boolean
}

/** 配色方案选项列表（供 UI 选择器使用） */
export interface WeatherPaletteOption {
  id: string
  label: string
  type: 'sequential' | 'diverging' | 'qualitative'
  colors: string[]
}

// P2-E 单源：色带/别名来自 weather-palettes.generated.ts（真源 catalog_seeds/palettes.json）
const WEATHER_PALETTES: Record<string, WeatherPaletteDefinition> = GENERATED_WEATHER_PALETTES
const PALETTE_ALIASES: Record<string, string> = GENERATED_PALETTE_ALIASES

/** 选项仅含 exposed 条目（后端独有色带不进选择器，避免 UI 突变） */
export const WEATHER_PALETTE_OPTIONS: WeatherPaletteOption[] = Object.entries(WEATHER_PALETTES)
  .filter(([, def]) => def.exposed)
  .map(([id, def]) => ({ id, label: def.label, type: def.type, colors: def.colors }))

/** 将配色方案转换为粒子流色阶（12 色；提亮后适合深色底图描线） */
export function paletteToParticleColors(paletteId: string): string[] {
  const resolved = resolvePaletteId(paletteId)
  const def = WEATHER_PALETTES[resolved]
  if (!def) return []
  const src = def.colors
  const target = 12
  const expanded: string[] = []
  if (src.length >= target) {
    for (let i = 0; i < target; i++) expanded.push(src[i])
  } else {
    for (let i = 0; i < target; i++) {
      const ratio = i / (target - 1)
      const srcIdx = ratio * (src.length - 1)
      const lo = Math.floor(srcIdx)
      const hi = Math.min(lo + 1, src.length - 1)
      const frac = srcIdx - lo
      expanded.push(lerpHexColor(src[lo], src[hi], frac))
    }
  }
  // heatmap 色带偏暗；粒子是 1px 线，必须抬亮度否则在卫星/深色底图上等于「没显示」
  return expanded.map((c, i) => lightenForParticleStroke(c, 0.52 + (i / (target - 1)) * 0.18))
}

/** 向白混合并抬最低亮度，保证粒子描边在深色底图上可见且仍保留色相 */
function lightenForParticleStroke(hex: string, amount: number): string {
  const rgb = parseHex(hex)
  if (!rgb) return '#e8f4ff'
  const [r0, g0, b0] = rgb
  const r = Math.round(r0 + (255 - r0) * amount)
  const g = Math.round(g0 + (255 - g0) * amount)
  const b = Math.round(b0 + (255 - b0) * amount)
  // 最低亮度约 160，避免仍偏暗
  const lift = Math.max(0, 160 - Math.max(r, g, b))
  const rr = Math.min(255, r + lift)
  const gg = Math.min(255, g + lift)
  const bb = Math.min(255, b + lift)
  return `#${rr.toString(16).padStart(2, '0')}${gg.toString(16).padStart(2, '0')}${bb.toString(16).padStart(2, '0')}`
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

/** 后端目录/历史命名 → 前端色带 ID（避免未知 ID 回落暗色 wind-blue 导致“看不见”） */

function resolvePaletteId(palette: string): string {
  const key = PALETTE_ALIASES[palette] ?? palette
  if (WEATHER_PALETTES[key]) return key
  // 未知色带用高对比热力色，避免暗底图上看起来像“没图层”
  return 'thermal-orange'
}

/** 规范化色带 ID（别名 → 前端 canonical），供选择器高亮对齐 */
export function resolveCanonicalPaletteId(palette: string | null | undefined): string {
  if (!palette) return ''
  return resolvePaletteId(palette)
}

/**
 * 严格版 canonical 解析：未知色带原样返回，**不做 thermal-orange 兜底**。
 *
 * 2026-08-24 三联报障 C：后端色带全集（brg/cividis/plasma/hot/terrain/
 * ylgnbu/ylorrd 等）大于前端可选集；旧 resolvePaletteId 把未知后端色带
 * 兜底成 thermal-orange，导致「当前/默认配色」误判为热力橙红——用户显式
 * 选热力橙红时被 paletteIdsEqual 判为"等于默认"而存 null（吞掉覆盖），
 * 后端继续按原色带（如 viridis）渲染 = 「热力橙红和 Viridis 显示一样」。
 * 渲染路径（粒子/图例）仍用 resolvePaletteId 兜底保证可见性；默认/相等
 * 判定一律走本严格版。
 */
export function resolveCanonicalPaletteIdStrict(palette: string | null | undefined): string {
  if (!palette) return ''
  const key = PALETTE_ALIASES[palette] ?? palette
  return WEATHER_PALETTES[key] ? key : palette
}

/** 判断两个色带 ID 是否同一条（含别名；未知 ID 按原文比较，不兜底） */
export function paletteIdsEqual(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  if (!a || !b) return false
  return resolveCanonicalPaletteIdStrict(a) === resolveCanonicalPaletteIdStrict(b)
}

function getPaletteDefinition(palette: string): WeatherPaletteDefinition {
  return WEATHER_PALETTES[resolvePaletteId(palette)]
}

/** 供侧栏 / InfoPanel 读取色带颜色 */
export function getPaletteColors(paletteId: string): string[] {
  return getPaletteDefinition(paletteId).colors
}

// ── 渲染参数常量 ─────────────────────────────────────────

/** 天气图层填充不透明度范围（连续色场可略提高，仍保留底图可读） */
const FILL_OPACITY_MIN = 0.08
const FILL_OPACITY_MAX = 0.9

/** 网格描边尽量弱，避免色块感 */
const LINE_OPACITY_MIN = 0.02
const LINE_OPACITY_MAX = 0.12
const LINE_OPACITY_RATIO = 0.18

/** 天气点半径映射范围（像素） */
const POINT_RADIUS_MIN = 3.0
const POINT_RADIUS_MAX = 7.0

/** 风向箭头大小映射范围 */
const ARROW_SIZE_MIN = 0.45
const ARROW_SIZE_MAX = 0.9

/** 按 0~1 比例从色带采样（连续图例 / 填色共用） */
export function samplePaletteColor(paletteId: string, ratio: number): string {
  const colors = getPaletteDefinition(paletteId).colors
  if (colors.length === 0) return '#4bb9ff'
  if (colors.length === 1) return colors[0]
  const t = Math.max(0, Math.min(1, ratio))
  const srcIdx = t * (colors.length - 1)
  const lo = Math.floor(srcIdx)
  const hi = Math.min(lo + 1, colors.length - 1)
  return lerpHexColor(colors[lo], colors[hi], srcIdx - lo)
}

export function buildWeatherLegendStops(hint: WeatherLayerRenderHint): WeatherLegendStop[] {
  const legendTicks = hint.legend_ticks ?? []
  const ticks = legendTicks.length > 0 ? legendTicks : DEFAULT_LEGEND_TICKS
  const numericTicks = ticks.filter((tick): tick is number => typeof tick === 'number')
  const minTick = numericTicks[0] ?? 0
  const maxTick = numericTicks[numericTicks.length - 1] ?? 1
  const span = maxTick - minTick || 1
  return ticks.map((tick, index) => {
    const ratio =
      typeof tick === 'number' ? (tick - minTick) / span : index / Math.max(1, ticks.length - 1)
    return {
      value: tick,
      label: typeof tick === 'number' ? `${tick} ${hint.unit_label}`.trim() : String(tick),
      color: samplePaletteColor(hint.palette, ratio),
    }
  })
}

/** CSS linear-gradient：与填色 / 图例刻度同一套 samplePaletteColor，避免色条与地图色阶错位 */
export function buildWeatherLegendGradient(hint: WeatherLayerRenderHint): string {
  const stops = buildWeatherLegendStops(hint)
  const colors = stops.map((stop) => stop.color).filter(Boolean)
  if (colors.length === 0) {
    const fallback = getPaletteDefinition(hint.palette).colors
    if (fallback.length === 0) return 'linear-gradient(90deg, #4bb9ff, #ff7b54)'
    return `linear-gradient(90deg, ${fallback.join(', ')})`
  }
  if (colors.length === 1) {
    return `linear-gradient(90deg, ${colors[0]}, ${colors[0]})`
  }
  return `linear-gradient(90deg, ${colors.join(', ')})`
}

export function buildWeatherFillColorExpression(
  hint: WeatherLayerRenderHint,
): ExpressionSpecification {
  const legendStops = buildWeatherLegendStops(hint)
  const metricKey = hint.primary_metric
  const expression: Array<string | number | ExpressionSpecification> = [
    'interpolate',
    ['linear'] as unknown as ExpressionSpecification,
    ['coalesce', ['to-number', ['get', metricKey]], 0] as unknown as ExpressionSpecification,
  ]

  let pushed = 0
  for (const stop of legendStops) {
    if (typeof stop.value !== 'number') continue
    expression.push(stop.value, stop.color)
    pushed += 1
  }
  if (pushed === 0) {
    expression.push(0, legendStops[0]?.color ?? '#4bb9ff')
  }
  return expression as ExpressionSpecification
}

export function buildWeatherPointColorExpression(
  hint: WeatherLayerRenderHint,
): ExpressionSpecification {
  return buildWeatherFillColorExpression(hint)
}

export function buildWeatherPointRadiusExpression(
  hint: WeatherLayerRenderHint,
): ExpressionSpecification {
  const ticks = (hint.legend_ticks ?? []).filter((tick): tick is number => typeof tick === 'number')
  const minTick = ticks[0] ?? 0
  const maxTick = ticks[ticks.length - 1] ?? 20
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', hint.primary_metric]], 0],
    minTick,
    POINT_RADIUS_MIN,
    maxTick,
    POINT_RADIUS_MAX,
  ] as unknown as ExpressionSpecification
}

export function buildWeatherHeatmapColorExpression(
  hint: WeatherLayerRenderHint,
): ExpressionSpecification {
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

export function buildWeatherHeatmapWeightExpression(
  hint: WeatherLayerRenderHint,
): ExpressionSpecification {
  const ticks = (hint.legend_ticks ?? []).filter((tick): tick is number => typeof tick === 'number')
  const minTick = ticks[0] ?? 0
  const maxTick = ticks[ticks.length - 1] ?? 100
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', hint.primary_metric]], 0],
    minTick,
    0,
    maxTick,
    1,
  ] as unknown as ExpressionSpecification
}

export function buildWeatherArrowSizeExpression(
  hint: WeatherLayerRenderHint,
): ExpressionSpecification {
  const ticks = (hint.legend_ticks ?? []).filter((tick): tick is number => typeof tick === 'number')
  const minTick = ticks[0] ?? 0
  const maxTick = ticks[ticks.length - 1] ?? 20
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', hint.primary_metric]], 0],
    minTick,
    ARROW_SIZE_MIN,
    maxTick,
    ARROW_SIZE_MAX,
  ] as unknown as ExpressionSpecification
}

export function getWeatherLineColor(hint: WeatherLayerRenderHint) {
  return getPaletteDefinition(hint.palette).lineColor
}

export function getWeatherFillOpacity(hint: WeatherLayerRenderHint, layerOpacity: number) {
  const hintOpacity =
    typeof hint.opacity === 'number' && Number.isFinite(hint.opacity) ? hint.opacity : 0.7
  const layerOp =
    typeof layerOpacity === 'number' && Number.isFinite(layerOpacity) ? layerOpacity : 1
  const raw = hintOpacity * layerOp
  if (!Number.isFinite(raw)) return 0.55
  return Math.max(FILL_OPACITY_MIN, Math.min(FILL_OPACITY_MAX, raw))
}

/**
 * fill-opacity：降水近零值透明，突出有雨区；其它图层用恒定不透明度。
 */
export function buildWeatherFillOpacityExpression(
  hint: WeatherLayerRenderHint,
  layerOpacity: number,
): number | ExpressionSpecification {
  const base = getWeatherFillOpacity(hint, layerOpacity)
  const metric = hint.primary_metric || ''
  const isPrecip =
    hint.layer_id === 'precipitation' || metric.includes('precip') || metric.includes('rain')
  if (!isPrecip) return base

  const ticks = (hint.legend_ticks ?? []).filter((t): t is number => typeof t === 'number')
  const lightRain = ticks.length >= 2 ? ticks[1] : 1
  const midRain = ticks.length >= 3 ? ticks[2] : Math.max(lightRain * 5, 5)
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', hint.primary_metric]], 0],
    0,
    0.04,
    lightRain * 0.25,
    0.18,
    lightRain,
    Math.max(0.35, base * 0.55),
    midRain,
    base,
  ] as unknown as ExpressionSpecification
}

export function getWeatherLineOpacity(hint: WeatherLayerRenderHint, layerOpacity: number) {
  return Math.max(
    LINE_OPACITY_MIN,
    Math.min(LINE_OPACITY_MAX, hint.opacity * layerOpacity * LINE_OPACITY_RATIO),
  )
}
