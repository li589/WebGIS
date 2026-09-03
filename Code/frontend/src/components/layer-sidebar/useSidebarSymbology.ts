import { useOverlaySymbologyStore } from '../../stores/overlay-symbology'
import type { WeatherLayerRenderHint } from '../../stores/layers/types'
import { resolveEffectiveLayerSymbology } from '../map/effective-layer-symbology'
import { buildWeatherLegendGradient, resolveSymbologyColors } from '../map/layer-symbology'

// 类型别名：对齐 WeatherLayerRenderHint 实际 schema（legend_ticks 而非 vmin/vmax）
export type ActiveLayerDisplayLike = {
  instanceId: string
  catalogId: string
  metricLabel: string
  accentColor: string
  opacity: number
  isAdminBoundary?: boolean
  isImported?: boolean
  isImportedRaster?: boolean
  paletteOverride?: string | null
  vminOverride?: number | null
  vmaxOverride?: number | null
  renderHint?: {
    palette: string
    unit_label?: string
    /** 天气图层的图例刻度，首末项作为 vmin/vmax 展示 */
    legend_ticks?: (number | string)[]
  } | null
}

/**
 * Extracts symbology helper functions from LayerSidebar.vue.
 *
 * Provides color symbology detection, unit/vmin/vmax extraction from render
 * hints, and gradient style computation for legend color ramps. Delegates to
 * the overlay symbology store for non-weather layers.
 *
 * @param overlaySymbologyStore - The overlay symbology store instance
 */
export function useSidebarSymbology(
  overlaySymbologyStore: ReturnType<typeof useOverlaySymbologyStore>,
) {
  /** 判断图层是否支持颜色图例显示（参考 ArcGIS：仅有符号化数据的图层显示色带） */
  function hasColorSymbology(layer: ActiveLayerDisplayLike): boolean {
    if (layer.isAdminBoundary) return false
    if (layer.renderHint) return true
    // 依赖 store.version，保证 meta 拉取后色带刷新
    void overlaySymbologyStore.version
    const meta = overlaySymbologyStore.getMeta(layer.catalogId)
    return !!meta?.palette
  }

  function getSymbologyUnit(layer: ActiveLayerDisplayLike): string {
    if (layer.renderHint?.unit_label) return layer.renderHint.unit_label
    void overlaySymbologyStore.version
    const meta = overlaySymbologyStore.getMeta(layer.catalogId)
    if (meta?.unit) return meta.unit
    return ''
  }

  function getSymbologyVmin(layer: ActiveLayerDisplayLike): string {
    const { hint } = resolveEffectiveLayerSymbology({
      paletteOverride: layer.paletteOverride,
      vminOverride: layer.vminOverride,
      vmaxOverride: layer.vmaxOverride,
      renderHint: (layer.renderHint ?? null) as WeatherLayerRenderHint | null,
      overlayMeta: overlaySymbologyStore.getMeta(layer.catalogId),
    })
    const ticks = hint?.legend_ticks
    if (ticks && ticks.length > 0) return String(ticks[0])
    return ''
  }

  function getSymbologyVmax(layer: ActiveLayerDisplayLike): string {
    const { hint } = resolveEffectiveLayerSymbology({
      paletteOverride: layer.paletteOverride,
      vminOverride: layer.vminOverride,
      vmaxOverride: layer.vmaxOverride,
      renderHint: (layer.renderHint ?? null) as WeatherLayerRenderHint | null,
      overlayMeta: overlaySymbologyStore.getMeta(layer.catalogId),
    })
    const ticks = hint?.legend_ticks
    if (ticks && ticks.length > 1) return String(ticks[ticks.length - 1])
    if (ticks && ticks.length === 1) return String(ticks[0])
    return ''
  }

  function getColorRampStyle(layer: ActiveLayerDisplayLike): Record<string, string> {
    void overlaySymbologyStore.version
    // 与 InfoPanel 同源：resolveEffectiveLayerSymbology + buildWeatherLegendGradient
    const { hint } = resolveEffectiveLayerSymbology({
      paletteOverride: layer.paletteOverride,
      vminOverride: layer.vminOverride,
      vmaxOverride: layer.vmaxOverride,
      renderHint: (layer.renderHint ?? null) as WeatherLayerRenderHint | null,
      overlayMeta: overlaySymbologyStore.getMeta(layer.catalogId),
    })
    if (hint) {
      return { background: buildWeatherLegendGradient(hint) }
    }
    const colors = resolveSymbologyColors({
      paletteOverride: layer.paletteOverride,
      renderHint: layer.renderHint,
      overlayMeta: overlaySymbologyStore.getMeta(layer.catalogId),
      fallbackAccent: layer.accentColor,
    })
    return {
      background: `linear-gradient(90deg, ${colors.join(', ')})`,
    }
  }

  return {
    hasColorSymbology,
    getSymbologyUnit,
    getSymbologyVmin,
    getSymbologyVmax,
    getColorRampStyle,
  }
}
