import { useOverlaySymbologyStore } from '../../stores/overlay-symbology'
import type { WeatherLayerRenderHint } from '../../stores/layers/types'
import { resolveEffectiveLayerSymbology } from '../map/effective-layer-symbology'
import {
  buildWeatherLegendGradient,
  isProductRoleCode,
  resolveSymbologyColors,
  unitForRole,
} from '../map/layer-symbology'

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
  /**
   * 产物角色（SM / VOD / OMEGA，见 run-layers 的 runGroupProductTag）。
   * 2026-10-15：用于判定色带单位（SM = m³/m³；VOD / ω 无量纲 ⇒ 不显示单位）。
   */
  runGroupProductTag?: string | null
}

// 变量角色 → 物理单位的表与口径在 `components/map/layer-symbology.ts`
// （`unitForRole` / `isProductRoleCode`）：SM（体积含水量）＝ m³/m³；
// VOD（植被光学厚度）/ ω（等效散射反照率）为无量纲量 ⇒ 不显示单位。

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

  /**
   * 色带单位。
   *
   * 2026-10-15 用户口径：单位写在 colorbar 右端刻度后面（如「0.5 m³/m³」），
   * **SM 要写单位，无量纲量（VOD / ω）完全不要写**——此前色带右端出现
   * 「0.5 SM」「1.5 VOD」这种字样，根因是后端把变量标签写进了 overlay 的
   * unit 字段（见 layer-symbology 的 PRODUCT_ROLE_CODES 注释）。
   *
   * 优先级：
   *   1. 产物角色已知（SM / VOD / OMEGA）⇒ 以角色为准：SM = m³/m³，其余为空；
   *   2. `renderHint.unit_label`（天气 / 静态叠加层自带单位）；
   *   3. overlay `meta.unit`（同样先排掉「角色码冒充单位」）。
   * 空串 = 不渲染单位。
   */
  function getSymbologyUnit(layer: ActiveLayerDisplayLike): string {
    const role = String(layer.runGroupProductTag ?? '')
      .trim()
      .toUpperCase()
    if (isProductRoleCode(role)) return unitForRole(role)
    const hintUnit = layer.renderHint?.unit_label
    if (hintUnit && !isProductRoleCode(hintUnit)) return hintUnit
    void overlaySymbologyStore.version
    const metaUnit = overlaySymbologyStore.getMeta(resolveOverlayMetaId(layer))?.unit
    if (isProductRoleCode(metaUnit)) return unitForRole(metaUnit)
    return metaUnit ?? ''
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

  /** 刻度数字去尾零：0.6 → "0.6"，1.5 → "1.5"，0 → "0"，0.30000000000000004 → "0.3" */
  function formatTickValue(value: number): string {
    if (!Number.isFinite(value)) return ''
    const rounded = Math.round(value * 1000) / 1000
    return String(rounded)
  }

  /**
   * 图例刻度（2026-11-05 用户口径，第二版）。
   *
   * 用户补充原话：「超过 0.6 的有效值使用端点深蓝，图例右端标为『≥0.6』」
   * 「图例增加 0.2、0.4 刻度，左右『低—高』说明」。
   *
   * ⇒ 刻度四档：`0 / 0.2 / 0.4 / ≥0.6`，量程起点 0 **必须写**。
   *    （第一版我误把 0 删掉，只剩 0.2/0.4/0.6，用户指出这等于宣称
   *      "量程从 0.2 开始"，与色带实际 0 起点自相矛盾——删不得。）
   * ⇒ 右端用 `≥` 而不是 `>`：渲染端把 ≥vmax 的值 clip 到端点色，
   *    `≥0.6` 与「超过 0.6 用端点深蓝」一致，且数学上含 0.6 本身。
   *
   * 内部分档数固定为 3 段（2 个内部刻度）：0–0.6 正好落在 0.2 / 0.4；
   * 其它变量（如 VOD 0–1.5）会得到 0.5 / 1.0，同样是三等分的自然刻度。
   */
  function getLegendTicks(layer: ActiveLayerDisplayLike): {
    ticks: string[]
    maxLabel: string
  } {
    void overlaySymbologyStore.version
    const { hint } = resolveEffectiveLayerSymbology({
      paletteOverride: layer.paletteOverride,
      vminOverride: layer.vminOverride,
      vmaxOverride: layer.vmaxOverride,
      renderHint: (layer.renderHint ?? null) as WeatherLayerRenderHint | null,
      overlayMeta: overlaySymbologyStore.getMeta(resolveOverlayMetaId(layer)),
    })
    const raw = hint?.legend_ticks
    if (!raw || raw.length < 2) {
      // 拿不到声明刻度就退回旧的「首 / 末」两段，至少不空着
      const lo = getSymbologyVmin(layer)
      const hi = getSymbologyVmax(layer)
      return { ticks: lo ? [lo] : [], maxLabel: hi }
    }
    const lo = Number(raw[0])
    const hi = Number(raw[raw.length - 1])
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) {
      return { ticks: [String(raw[0])], maxLabel: String(raw[raw.length - 1] ?? '') }
    }
    const step = (hi - lo) / 3
    return {
      // 0 / 0.2 / 0.4 三档内部刻度（起点必须保留，否则与色带 0 起点矛盾）
      ticks: [lo, lo + step, lo + 2 * step].map(formatTickValue),
      maxLabel: `≥${formatTickValue(hi)}`,
    }
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
    getLegendTicks,
    getColorRampStyle,
  }
}
