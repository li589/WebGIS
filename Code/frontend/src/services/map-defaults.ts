/**
 * Shared map / AOI defaults. Cold-start uses Guangzhou-aligned constants;
 * hydrate from GET /config/general (+ weather lat/lng) after settings load.
 */

export const MAP_DEFAULT_FALLBACK = {
  longitude: 113.2644,
  latitude: 23.1291,
  zoom: 4.8,
  tileSource: 'gaode-street',
} as const

export interface MapAoiPreset {
  label: string
  west: number
  south: number
  east: number
  north: number
}

export interface MapDefaults {
  longitude: number
  latitude: number
  zoom: number
  tileSource: string
  aoiPresets: MapAoiPreset[]
}

let hydrated: MapDefaults = {
  longitude: MAP_DEFAULT_FALLBACK.longitude,
  latitude: MAP_DEFAULT_FALLBACK.latitude,
  zoom: MAP_DEFAULT_FALLBACK.zoom,
  tileSource: MAP_DEFAULT_FALLBACK.tileSource,
  aoiPresets: [],
}

export function getMapDefaults(): MapDefaults {
  return hydrated
}

export function hydrateMapDefaults(partial: {
  longitude?: number | null
  latitude?: number | null
  zoom?: number | null
  tileSource?: string | null
  aoiPresets?: MapAoiPreset[] | null
}): MapDefaults {
  const next: MapDefaults = { ...hydrated }
  if (typeof partial.longitude === 'number' && Number.isFinite(partial.longitude)) {
    next.longitude = partial.longitude
  }
  if (typeof partial.latitude === 'number' && Number.isFinite(partial.latitude)) {
    next.latitude = partial.latitude
  }
  if (typeof partial.zoom === 'number' && Number.isFinite(partial.zoom)) {
    next.zoom = partial.zoom
  }
  if (typeof partial.tileSource === 'string' && partial.tileSource.trim()) {
    next.tileSource = partial.tileSource.trim()
  }
  if (Array.isArray(partial.aoiPresets)) {
    next.aoiPresets = partial.aoiPresets.filter(
      (p) =>
        p &&
        typeof p.label === 'string' &&
        Number.isFinite(p.west) &&
        Number.isFinite(p.south) &&
        Number.isFinite(p.east) &&
        Number.isFinite(p.north),
    )
  }
  hydrated = next
  return hydrated
}
