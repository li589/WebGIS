/**
 * 有效图层符号学：InfoPanel / LayerSidebar / 地图色带同源。
 * - 色板：paletteOverride > renderHint / overlayMeta
 * - 量程：配置 legend_ticks（≥2 数值）优先；否则从视口合并 GeoJSON 采样
 * - 说明：可跟 live windDisplayMode
 */
import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import type { WindGeoJSON } from './types'
import type { WindDisplayMode } from './wind-display-mode'
import { type OverlaySymbologyMeta, resolveStyleRenderHint } from './layer-symbology'
import { buildScalarGridFromGeoJSON, resolveScalarValueRange } from './scalar-field-grid'

const SAMPLED_TICK_COUNT = 5

export interface EffectiveLayerSymbologyInput {
  paletteOverride?: string | null
  renderHint?: WeatherLayerRenderHint | null
  overlayMeta?: OverlaySymbologyMeta | null
  /** 当前视口合并数据；仅在配置 ticks 不足时用于采样量程 */
  viewportGeojson?: WindGeoJSON | { type: string; features?: unknown[] } | null
  windDisplayMode?: WindDisplayMode | null
}

export interface EffectiveLayerSymbology {
  hint: WeatherLayerRenderHint | null
  /** 图例说明文案（可跟 live 风场模式） */
  explainer: string
  /** ticks 是否来自视口采样（相对目录配置） */
  ticksFromViewport: boolean
}

function numericLegendTicks(ticks: Array<number | string> | null | undefined): number[] {
  return (ticks ?? []).filter((t): t is number => typeof t === 'number' && Number.isFinite(t))
}

/** 在 [min, max] 上生成等距刻度（含端点） */
export function buildSampledLegendTicks(
  min: number,
  max: number,
  count = SAMPLED_TICK_COUNT,
): number[] {
  const n = Math.max(2, Math.floor(count))
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1]
  if (min === max) return [min - 1, min, min + 1]
  const lo = Math.min(min, max)
  const hi = Math.max(min, max)
  const ticks: number[] = []
  for (let i = 0; i < n; i++) {
    const t = lo + ((hi - lo) * i) / (n - 1)
    // 保留合理精度，避免 1.333333333
    const rounded = Math.abs(hi - lo) >= 10 ? Math.round(t * 10) / 10 : Math.round(t * 100) / 100
    ticks.push(rounded)
  }
  return ticks
}

export function buildLegendExplainer(options: {
  hint: WeatherLayerRenderHint | null
  windDisplayMode?: WindDisplayMode | null
  canToggleParticleFlow?: boolean
}): string {
  const { hint, windDisplayMode, canToggleParticleFlow } = options
  if (windDisplayMode === 'particle' || windDisplayMode === 'streamline') {
    return '色带对应风速网格底色；粒子/流线表示流向（颜色随风速提亮）。'
  }
  if (windDisplayMode === 'off' && canToggleParticleFlow) {
    return '色带对应风速网格底色；风场粒子/流线当前已关闭。'
  }
  const mode = hint?.paint_mode
  if (mode === 'particle_flow' || canToggleParticleFlow) {
    return '色带对应风速网格底色；粒子线表示流向（颜色随风速提亮）。'
  }
  if (mode === 'grid_fill' || mode === 'heatmap') {
    return '色带对应网格单元量级；相邻单元接壤形成连续色场。'
  }
  return ''
}

/**
 * 解析分析框 / 侧栏共用的有效 renderHint。
 */
export function resolveEffectiveLayerSymbology(
  input: EffectiveLayerSymbologyInput,
): EffectiveLayerSymbology {
  const base = resolveStyleRenderHint({
    paletteOverride: input.paletteOverride,
    renderHint: input.renderHint,
    overlayMeta: input.overlayMeta,
  })
  if (!base) {
    return { hint: null, explainer: '', ticksFromViewport: false }
  }

  const configured = numericLegendTicks(base.legend_ticks)
  let hint = base
  let ticksFromViewport = false

  if (configured.length < 2 && input.viewportGeojson) {
    const metric = base.primary_metric || 'value'
    const grid = buildScalarGridFromGeoJSON(input.viewportGeojson, metric)
    const range = resolveScalarValueRange(base.legend_ticks, grid)
    // 仅当网格或采样给出有效跨度时替换 ticks
    if (grid || configured.length === 0) {
      hint = {
        ...base,
        legend_ticks: buildSampledLegendTicks(range.min, range.max),
      }
      ticksFromViewport = true
    }
  }

  return {
    hint,
    explainer: buildLegendExplainer({
      hint,
      windDisplayMode: input.windDisplayMode,
      canToggleParticleFlow:
        hint.paint_mode === 'particle_flow' ||
        hint.paint_mode === 'barb' ||
        Boolean(input.windDisplayMode),
    }),
    ticksFromViewport,
  }
}
