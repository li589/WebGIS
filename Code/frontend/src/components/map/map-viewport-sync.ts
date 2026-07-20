export interface MapViewportBounds {
  getSouth: () => number
  getNorth: () => number
  getWest: () => number
  getEast: () => number
}

export interface MapViewportReader {
  getCenter: () => { lng: number; lat: number }
  getBounds: () => MapViewportBounds
  getZoom: () => number
}

export interface MapViewportSnapshot {
  center: { lng: number; lat: number }
  bbox: { west: number; south: number; east: number; north: number; crs: 'EPSG:4326' }
  zoom: number
}

function wrapLongitude(lng: number): number {
  let wrapped = lng
  while (wrapped > 180) wrapped -= 360
  while (wrapped < -180) wrapped += 360
  return wrapped
}

/**
 * 归一化经度边界并处理反子午线穿越。
 *
 * 将 west/east 归一化到 [-180, 180]；若 east < west（跨 ±180° 经线），
 * 将 east 扩展到 (180, 360) 区间，保留"从 west 向东穿越 180° 到 east"的短路径语义。
 * 下游 tilesInBounds 通过 ((x % n) + n) % n 归一化处理跨子午线瓦片索引。
 *
 * 跨度 >= 360°（全屏视口）时直接返回世界范围 [-180, 180]。
 *
 * 共享给 map-viewport-sync.ts 与 wind-particle-canvas.ts，避免两处独立维护
 * 相同的反子午线归一化逻辑。
 */
export function normalizeLngBounds(west: number, east: number): { west: number; east: number } {
  if (east - west >= 360) {
    return { west: -180, east: 180 }
  }
  let w = west
  let e = east
  while (w > 180) w -= 360
  while (w < -180) w += 360
  while (e > 180) e -= 360
  while (e < -180) e += 360
  if (e < w) {
    e += 360
  }
  return { west: w, east: e }
}

export function buildMapViewportSnapshot(map: MapViewportReader): MapViewportSnapshot {
  const center = map.getCenter()
  const bounds = map.getBounds()

  // 保留完整地理坐标范围 [-90, 90]：bbox 除用于瓦片加载外，也可能用于点查询等
  // 非渲染用途；瓦片请求中越界 y 坐标由 tilesInBounds 内部 y < 0 || y >= n 过滤
  const south = Math.max(-90, Math.min(90, bounds.getSouth()))
  const north = Math.max(-90, Math.min(90, bounds.getNorth()))

  const { west, east } = normalizeLngBounds(bounds.getWest(), bounds.getEast())

  return {
    center: {
      lng: wrapLongitude(center.lng),
      lat: center.lat,
    },
    bbox: {
      west,
      south,
      east,
      north,
      crs: 'EPSG:4326',
    },
    zoom: map.getZoom(),
  }
}
