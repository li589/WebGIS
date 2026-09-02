/**
 * Cesium overlay XYZ 瓦片规格：对接 /overlay-tiles（PNG）。
 * /weather/tiles 返回 GeoJSON，本阶段跳过（风场等仍走 MapLibre）。
 */
import { buildOverlayStyleQuery } from '../../layer-symbology'
import type { ActiveLayerDisplay } from '../../../../stores/layers/types'

export interface CesiumOverlayTileSpec {
  id: string
  urlTemplate: string
  opacity: number
  maximumLevel: number
}

export interface CollectOverlayTileOptions {
  /** 是否天气引擎层（GeoJSON 管线）→ 跳过 */
  isWeatherEngineLayer?: (catalogId: string) => boolean
  /** 时间轴 time key（写入 overlay query） */
  timeKey?: string | null
}

/**
 * 从可见图层收集可挂到 Cesium ImageryLayer 的 overlay-tiles URL。
 */
export function collectCesiumOverlayTileSpecs(
  layers: ReadonlyArray<ActiveLayerDisplay>,
  options: CollectOverlayTileOptions = {},
): CesiumOverlayTileSpec[] {
  const out: CesiumOverlayTileSpec[] = []
  const seen = new Set<string>()

  for (const layer of layers) {
    if (!layer.visible) continue
    if (layer.isAdminBoundary) continue
    if (options.isWeatherEngineLayer?.(layer.catalogId)) continue

    const overlayId =
      layer.importedRasterOverlayLayerId ||
      (layer.isImportedRaster ? layer.catalogId : null) ||
      // 非天气、已物化的 overlay 资产：catalogId 常即 overlay_layer_id
      (layer.dataState === 'real' && !layer.isImported && !layer.renderHint
        ? layer.catalogId
        : null)

    if (!overlayId || seen.has(overlayId)) continue
    seen.add(overlayId)

    const qs = buildOverlayStyleQuery({
      time: options.timeKey ?? layer.importedRasterEffectiveTime ?? null,
      palette: layer.paletteOverride ?? null,
      vmin: layer.vminOverride ?? null,
      vmax: layer.vmaxOverride ?? null,
      nodataMode: layer.nodataMode ?? null,
      nodataColor: layer.nodataColor ?? null,
      forceStyle: Boolean(
        layer.paletteOverride || layer.vminOverride != null || layer.vmaxOverride != null,
      ),
    })

    const base = `/overlay-tiles/${encodeURIComponent(overlayId)}/{z}/{x}/{y}.png`
    out.push({
      id: overlayId,
      urlTemplate: `${base}${qs}`,
      opacity: Math.max(0, Math.min(1, layer.opacity ?? 1)),
      maximumLevel: 18,
    })
  }

  return out
}
