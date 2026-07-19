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

export function buildMapViewportSnapshot(map: MapViewportReader): MapViewportSnapshot {
  const center = map.getCenter()
  const bounds = map.getBounds()

  const south = Math.max(-90, Math.min(90, bounds.getSouth()))
  const north = Math.max(-90, Math.min(90, bounds.getNorth()))

  let west = bounds.getWest()
  let east = bounds.getEast()
  if (east - west >= 360) {
    west = -180
    east = 180
  } else {
    west = wrapLongitude(west)
    east = wrapLongitude(east)
    if (east < west) {
      // 视口跨 ±180° 经线（如 west=170, east=-175）。
      // 旧实现简单交换 west/east 会把视口映射到地球反面（-175→170，跨度 345°）。
      // 改为把 east 扩展到 (180, 360) 区间（170→185），保留"从 west 向东穿越 180°到 east"
      // 的短路径语义。下游 tilesInBounds 通过 ((x % n) + n) % n 归一化处理跨子午线瓦片索引。
      east += 360
    }
  }

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
