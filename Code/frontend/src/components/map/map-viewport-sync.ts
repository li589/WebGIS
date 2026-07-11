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
      ;[west, east] = [east, west]
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
