import type { LonFrame } from './weather-grid-lattice'

/** 视口帧外扩（度）：日界线瓦片格心略越出 bbox 时仍纳入建格，避免 IDL 窄缝空洞 */
const LON_FRAME_PAD_DEG = 3

/** 从 overlay 视口 bounds 构造建格用经度帧 */
export function lonFrameFromViewportBounds(
  bounds: { west: number; east: number; south?: number; north?: number } | null | undefined,
  centerLng?: number,
): LonFrame | null {
  if (!bounds) return null
  if (!(bounds.east > bounds.west)) return null
  return {
    west: bounds.west - LON_FRAME_PAD_DEG,
    east: bounds.east + LON_FRAME_PAD_DEG,
    centerLng:
      centerLng !== undefined && Number.isFinite(centerLng)
        ? centerLng
        : (bounds.west + bounds.east) / 2,
  }
}
