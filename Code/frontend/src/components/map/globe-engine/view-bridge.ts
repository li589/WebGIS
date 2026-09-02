/**
 * 3D 引擎互切视口桥（仅 session 内存；回 2D 不强制改 mercator）。
 */

export interface GlobeViewSnapshot {
  lng: number
  lat: number
  /** Cesium 相机高度（米） */
  heightMeters: number
  /** MapLibre zoom（可选；由 height 互推） */
  zoom?: number
  bearing?: number
  pitch?: number
}

let snapshot: GlobeViewSnapshot | null = null

export function setGlobeViewSnapshot(next: GlobeViewSnapshot | null): void {
  snapshot = next
}

export function getGlobeViewSnapshot(): GlobeViewSnapshot | null {
  return snapshot
}

/** 读取并清空（挂载侧一次性消费，避免反复跳转） */
export function consumeGlobeViewSnapshot(): GlobeViewSnapshot | null {
  const cur = snapshot
  snapshot = null
  return cur
}

/** MapLibre zoom → 近似椭球高度（米） */
export function zoomToHeightMeters(zoom: number, latDeg: number): number {
  const latRad = (latDeg * Math.PI) / 180
  const metersPerPixel = (156543.03392 * Math.cos(latRad)) / Math.pow(2, zoom)
  // 视口约 960px 高时的相机高度粗估
  return Math.max(500, metersPerPixel * 960)
}

/** 高度 → 近似 MapLibre zoom */
export function heightMetersToZoom(heightMeters: number, latDeg: number): number {
  const latRad = (latDeg * Math.PI) / 180
  const cos = Math.max(0.01, Math.cos(latRad))
  const metersPerPixel = heightMeters / 960
  const zoom = Math.log2((156543.03392 * cos) / Math.max(0.1, metersPerPixel))
  return Math.max(0, Math.min(22, zoom))
}
