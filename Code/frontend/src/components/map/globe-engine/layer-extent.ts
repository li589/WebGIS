/**
 * 图层包围盒解析（MapLibre / Cesium 共用）。
 */
import { validateOverlayBounds } from '../overlay-image-module'

export type LngLatBoundsTuple = [number, number, number, number]

export interface LayerExtentSource {
  instanceId: string
  importedVectorBounds?: LngLatBoundsTuple | null
  importedRasterBounds?: LngLatBoundsTuple | null
  importedBounds?: LngLatBoundsTuple | null
  overlayLayerId?: string | null
  catalogId?: string | null
}

export interface OverlayTimeBoundsHint {
  layerId: string
  bounds?: LngLatBoundsTuple | null
}

/**
 * 从图层元数据 + 可选 overlay 时间状态解析可飞行包围盒。
 * 返回 null 表示无可用范围（调用方自行 toast / 回退）。
 */
export function resolveLayerExtentBounds(
  layer: LayerExtentSource,
  overlayHints: ReadonlyArray<OverlayTimeBoundsHint> = [],
): LngLatBoundsTuple | null {
  let bounds: LngLatBoundsTuple | null | undefined =
    layer.importedVectorBounds ??
    layer.importedRasterBounds ??
    layer.importedBounds ??
    null

  if (!bounds) {
    const overlayId = layer.overlayLayerId ?? layer.catalogId ?? null
    if (overlayId) {
      const st = overlayHints.find((s) => s.layerId === overlayId)
      bounds = st?.bounds ?? null
    }
  }

  if (!bounds) return null
  const check = validateOverlayBounds(bounds)
  if (!check.ok) return null

  const [w, s, e, n] = check.bounds
  const pad = 0.0001
  let west = w
  let south = s
  let east = e
  let north = n
  if (east - west < pad) {
    west -= pad
    east += pad
  }
  if (north - south < pad) {
    south -= pad
    north += pad
  }
  return [west, south, east, north]
}

/** 包围盒中心与近似相机高度（米），供 flyTo 回退。 */
export function boundsCenterAndHeight(bounds: LngLatBoundsTuple): {
  lng: number
  lat: number
  heightMeters: number
} {
  const [w, s, e, n] = bounds
  const lng = (w + e) / 2
  const lat = (s + n) / 2
  const span = Math.max(Math.abs(e - w), Math.abs(n - s), 0.05)
  // 经验：跨度 1° ≈ 800km 高度量级
  const heightMeters = Math.min(12_000_000, Math.max(80_000, span * 800_000))
  return { lng, lat, heightMeters }
}
