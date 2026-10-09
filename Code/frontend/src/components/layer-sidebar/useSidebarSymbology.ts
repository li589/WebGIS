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
  /**
   * 反演 / 导入栅格的真实 overlay layer id。
   *
   * 这类图层的 `catalogId` 会被工作区改写成前端随机 id（见
   * `stores/layers/active-layers.ts` 的 `isEnglishInversionCatalogId` 分支），
   * 而地图侧写进 overlay symbology store 的键是**这个真实 id**
   * （`components/map/overlay-image-module.ts` 的 `putMeta(layerId, ...)`）。
   * 侧栏若继续用 `catalogId` 查缓存会永远 miss ⇒ 图例整行不渲染。
   */
  importedRasterOverlayLayerId?: string
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
  /**
   * 查 overlay 符号化缓存用的键。
   *
   * 2026-10-09 修复：原先一律用 `layer.catalogId`。反演 / 导入栅格图层的
   * catalogId 会被工作区改写成前端随机 id，而 store 里的 meta 是以真实
   * overlay layer id 为键写入的 ⇒ 左侧 TOC 永远取不到 palette/vmin/vmax，
   * 图例整行不渲染（右侧分析面板用 `importedRasterOverlayLayerId` ⇒ 正常）。
   * 现与 `components/info-panel/useLayerSymbology.ts` 的 `overlayStyleMeta` 对齐。
   */
  function resolveOverlayMetaId(layer: ActiveLayerDisplayLike): string {
    return layer.importedRasterOverlayLayerId || layer.catalogId
  }

  /** 判断图层是否支持颜色图例显示（参考 ArcGIS：仅有符号化数据的图层显示色带） */
  function hasColorSymbology(layer: ActiveLayerDisplayLike): boolean {
    if (layer.isAdminBoundary) return false
    if (layer.renderHint) return true
    // 依赖 store.version，保证 meta 拉取后色带刷新
    void overlaySymbologyStore.version
    const metaId = resolveOverlayMetaId(layer)
    const meta = overlaySymbologyStore.getMeta(metaId)
    if (meta?.palette) return true
    // 缓存未命中时补拉一次（与右侧分析面板同源）。
    // 动态 overlay 未必在 /overlays 注册表内 ⇒ 跳过注册检查，直接问 bounds。
    if (layer.importedRasterOverlayLayerId && !overlaySymbologyStore.shouldSkipFetch(metaId)) {
      void overlaySymbologyStore.ensureMeta(metaId, { skipRegistryCheck: true })
    }
    return false
  }

  function getSymbologyUnit(layer: ActiveLayerDisplayLike): string {
    if (layer.renderHint?.unit_label) return layer.renderHint.unit_label
    void overlaySymbologyStore.version
    const meta = overlaySymbologyStore.getMeta(resolveOverlayMetaId(layer))
    if (meta?.unit) return meta.unit
    return ''
  }

  function getSymbologyVmin(layer: ActiveLayerDisplayLike): string {
    void overlaySymbologyStore.version
    const { hint } = resolveEffectiveLayerSymbology({
      paletteOverride: layer.paletteOverride,
      vminOverride: layer.vminOverride,
      vmaxOverride: layer.vmaxOverride,
      renderHint: (layer.renderHint ?? null) as WeatherLayerRenderHint | null,
      overlayMeta: overlaySymbologyStore.getMeta(resolveOverlayMetaId(layer)),
    })
    const ticks = hint?.legend_ticks
    if (ticks && ticks.length > 0) return String(ticks[0])
    return ''
  }

  function getSymbologyVmax(layer: ActiveLayerDisplayLike): string {
    void overlaySymbologyStore.version
    const { hint } = resolveEffectiveLayerSymbology({
      paletteOverride: layer.paletteOverride,
      vminOverride: layer.vminOverride,
      vmaxOverride: layer.vmaxOverride,
      renderHint: (layer.renderHint ?? null) as WeatherLayerRenderHint | null,
      overlayMeta: overlaySymbologyStore.getMeta(resolveOverlayMetaId(layer)),
    })
    const ticks = hint?.legend_ticks
    if (ticks && ticks.length > 1) return String(ticks[ticks.length - 1])
    if (ticks && ticks.length === 1) return String(ticks[0])
    return ''
  }

  function getColorRampStyle(layer: ActiveLayerDisplayLike): Record<string, string> {
    void overlaySymbologyStore.version
    const overlayMeta = overlaySymbologyStore.getMeta(resolveOverlayMetaId(layer))
    // 与 InfoPanel 同源：resolveEffectiveLayerSymbology + buildWeatherLegendGradient
    const { hint } = resolveEffectiveLayerSymbology({
      paletteOverride: layer.paletteOverride,
      vminOverride: layer.vminOverride,
      vmaxOverride: layer.vmaxOverride,
      renderHint: (layer.renderHint ?? null) as WeatherLayerRenderHint | null,
      overlayMeta,
    })
    if (hint) {
      return { background: buildWeatherLegendGradient(hint) }
    }
    const colors = resolveSymbologyColors({
      paletteOverride: layer.paletteOverride,
      renderHint: layer.renderHint,
      overlayMeta,
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
