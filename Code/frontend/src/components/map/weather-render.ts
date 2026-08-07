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

interface WeatherPaletteDefinition {
  colors: string[]
  lineColor: string
  /** UI 显示名 */
  label: string
  /** 配色类型：sequential(递进) / diverging(发散) / qualitative(定性) */
  type: 'sequential' | 'diverging' | 'qualitative'
}

const WEATHER_PALETTES: Record<string, WeatherPaletteDefinition> = {
  /** 更多停点 → MapLibre interpolate / 图例更平滑（对照 Windy LUT） */
  'thermal-orange': {
    colors: [
      '#0b1a6e',
      '#1b3cff',
      '#2a5fff',
      '#2f8cff',
      '#36c5ff',
      '#4ad4d0',
      '#5ad9c4',
      '#7ce7b0',
      '#a8e87a',
      '#c8e86a',
      '#ffe066',
      '#ffd166',
      '#ff9f4a',
      '#ff7b54',
      '#ff4d4d',
      '#e83070',
      '#c01888',
    ],
    lineColor: 'rgba(255,255,255,0.08)',
    label: '热力橙红',
    type: 'sequential',
  },
  'precip-cyan': {
    colors: [
      '#061018',
      '#0b1c30',
      '#123048',
      '#16324f',
      '#1a4a7a',
      '#1c6dd0',
      '#1ea0ef',
      '#1ec8ff',
      '#48e0ff',
      '#70f0ff',
      '#9af8f0',
      '#b7fff5',
      '#d8fffb',
      '#e8ffff',
      '#ffffff',
    ],
    lineColor: 'rgba(150, 236, 255, 0.12)',
    label: '降水青蓝',
    type: 'sequential',
  },
  /** 对齐 Windy.com 风速色阶：蓝→青→绿→黄→橙→红→紫 */
  'wind-blue': {
    colors: [
      '#6271b8',
      '#3d6ea3',
      '#4a94aa',
      '#4a9294',
      '#4d8e7c',
      '#6b9148',
      '#a89438',
      '#d07a3a',
      '#c94e4e',
      '#a83d7a',
      '#7a3d9e',
      '#5c4d6e',
    ],
    lineColor: 'rgba(170, 228, 255, 0.12)',
    label: '风场蓝',
    type: 'sequential',
  },
  'magenta-yellow': {
    colors: ['#1a102a', '#5b1f7a', '#b832e0', '#ff5e9a', '#ffb347', '#fff2a6'],
    lineColor: 'rgba(255, 214, 153, 0.24)',
    label: '品红黄',
    type: 'diverging',
  },
  viridis: {
    colors: ['#440154', '#414487', '#2a788e', '#22a884', '#7ad151', '#fde725'],
    lineColor: 'rgba(200, 220, 100, 0.20)',
    label: 'Viridis 科学',
    type: 'sequential',
  },
  spectral: {
    colors: [
      '#9e0142',
      '#d53e4f',
      '#f46d43',
      '#fdae61',
      '#fee08b',
      '#e6f598',
      '#abdda4',
      '#66c2a5',
      '#3288bd',
    ],
    lineColor: 'rgba(255, 255, 255, 0.18)',
    label: '光谱彩虹',
    type: 'diverging',
  },
  blues: {
    colors: [
      '#f7fbff',
      '#deebf7',
      '#c6dbef',
      '#9ecae1',
      '#6baed6',
      '#4292c6',
      '#2171b5',
      '#084594',
    ],
    lineColor: 'rgba(150, 200, 255, 0.22)',
    label: '渐变蓝',
    type: 'sequential',
  },
  reds: {
    colors: [
      '#fff5f0',
      '#fee0d2',
      '#fcbba1',
      '#fc9272',
      '#fb6a4a',
      '#ef3b2c',
      '#cb181d',
      '#99000d',
    ],
    lineColor: 'rgba(255, 180, 150, 0.22)',
    label: '渐变红',
    type: 'sequential',
  },
  greens: {
    // 低端加深，深色底图上低湿度/云量仍可见（避免近白糊底）
    colors: [
      '#0d2818',
      '#1a4d2e',
      '#2d6a4f',
      '#40916c',
      '#52b788',
      '#74c69d',
      '#95d5b2',
      '#b7e4c7',
    ],
    lineColor: 'rgba(150, 230, 150, 0.22)',
    label: '渐变绿',
    type: 'sequential',
  },
  'yellow-red': {
    colors: [
      '#ffffcc',
      '#ffeda0',
      '#fed976',
      '#feb24c',
      '#fd8d3c',
      '#fc4e2a',
      '#e31a1c',
      '#b10026',
    ],
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
const PALETTE_ALIASES: Record<string, string> = {
  'orange-red': 'thermal-orange',
  'blue-cyan': 'wind-blue',
  'teal-blue': 'precip-cyan',
  'purple-seq': 'magenta-yellow',
  'green-seq': 'greens',
  'amber-gray': 'yellow-red',
  'pressure-purple': 'magenta-yellow',
  'humidity-green': 'greens',
  'visibility-amber': 'yellow-red',
}

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

/** 判断两个色带 ID 是否同一条（含别名） */
export function paletteIdsEqual(
  a: string | null | undefined,
  b: string | null | undefined,
): boolean {
  if (!a || !b) return false
  return resolvePaletteId(a) === resolvePaletteId(b)
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
