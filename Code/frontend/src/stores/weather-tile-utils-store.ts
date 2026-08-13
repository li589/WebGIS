/**
 * Weather tile manager — pure helpers used by the store (P1-1 split).
 */
import {
  buildTileKey,
  tilesInBounds,
  type LngLatBounds,
  type WeatherTileCoords,
} from '../services/weather-tile-api'
import type { WindGeoJSON } from '../types/map-geo'
import { normalizeLngBounds } from '../utils/geo-bounds'
import { useSettingsStore } from './settings'
import type { CachedTileEntry, TileRequest } from './weather-tile-types'

/** 默认与后端 weather_cache_ttl_seconds 一致 */
const DEFAULT_TILE_TTL_MS = 3600_000
/** 单视口瓦片上限；超出则降 tile z，避免亚洲–太平洋宽视野瞬间打爆上游 */
const MAX_VIEWPORT_TILES = 36

export function tileCoordsToKey(
  coords: WeatherTileCoords,
  layerId: string,
  hour: number,
  model: string,
  provider = 'auto',
): string {
  return buildTileKey(layerId, coords.z, coords.x, coords.y, hour, model, provider)
}

function getWeatherTileTtlMs(): number {
  try {
    const ttlSec = useSettingsStore().weatherConfig?.cache_ttl_seconds
    if (typeof ttlSec === 'number' && Number.isFinite(ttlSec) && ttlSec > 0) {
      return Math.floor(ttlSec * 1000)
    }
  } catch {
    // Pinia 未就绪（单测早期）时回退默认
  }
  return DEFAULT_TILE_TTL_MS
}

export function isTileFresh(entry: CachedTileEntry, now = Date.now()): boolean {
  return now - entry.fetchedAt < getWeatherTileTtlMs()
}

export function touchTileEntry(entry: CachedTileEntry, now = Date.now()): WindGeoJSON {
  entry.lastAccess = now
  return entry.geojson
}

export function makeTileEntry(geojson: WindGeoJSON, now = Date.now()): CachedTileEntry {
  return { geojson, fetchedAt: now, lastAccess: now }
}

/**
 * 取消单个 pending 请求。
 *
 * 注意：不要在这里递减 activeFetchCount。
 * - 若请求尚未被 drainQueue 调度（dispatched=false），它从未占用槽位。
 * - 若请求已被调度（dispatched=true），submitTile 的 finally 会统一释放槽位。
 * 因此调用方只需 abort controller。
 */
export function cancelPendingRequest(request: TileRequest): void {
  request.controller.abort()
}

export function bboxApproxEqual(
  a: LngLatBounds | null,
  b: LngLatBounds | null,
  eps = 1e-4,
): boolean {
  if (a === b) return true
  if (!a || !b) return false
  return (
    Math.abs(a.west - b.west) < eps &&
    Math.abs(a.south - b.south) < eps &&
    Math.abs(a.east - b.east) < eps &&
    Math.abs(a.north - b.north) < eps
  )
}

export function tileKeySetEqual(a: WeatherTileCoords[], b: WeatherTileCoords[]): boolean {
  if (a.length !== b.length) return false
  const keys = new Set(a.map((t) => `${t.z}:${t.x}:${t.y}`))
  return b.every((t) => keys.has(`${t.z}:${t.x}:${t.y}`))
}

export function resolveTileZoom(bounds: LngLatBounds, zoom: number): number {
  let z = Math.max(0, Math.min(12, Math.round(zoom)))
  while (z > 1 && tilesInBounds(bounds, z, 0).length > MAX_VIEWPORT_TILES) {
    z -= 1
  }
  return z
}

export function boundsFromCenter(center: { lng: number; lat: number }, z: number): LngLatBounds {
  // 无 bbox 时根据中心点和 zoom 估算近似视口；经度走 normalizeLngBounds 以支持长路径/近全球
  const n = 2 ** z
  const span = Math.max(1, Math.floor(n / 16))
  const halfLon = span * (360 / n)
  const halfLat = span * (170 / n)
  const { west, east } = normalizeLngBounds(center.lng - halfLon, center.lng + halfLon, center.lng)
  return {
    west,
    south: Math.max(-85, center.lat - halfLat),
    east,
    north: Math.min(85, center.lat + halfLat),
  }
}
