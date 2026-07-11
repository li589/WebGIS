/**
 * 天气瓦片 GeoJSON 合并工具。
 *
 * 纯函数，无状态。负责把多个标准瓦片 GeoJSON 合并成一份 FeatureCollection，
 * 用于风场粒子流/等值线/风羽等 Canvas 叠加层统一渲染。
 */
import type { WindGeoJSON, WindGeoJSONFeature } from '../components/map/types'

export interface MergedWeatherTile {
  layerId: string
  z: number
  x: number
  y: number
  hour: number
  geojson: WindGeoJSON
}

export interface MergeStats {
  tileCount: number
  totalFeatures: number
  uniqueFeatures: number
  duplicates: number
}

interface LngLatBounds {
  west: number
  south: number
  east: number
  north: number
}

const DEFAULT_QUANTIZE_FACTOR = 1000

function quantize(value: number, factor: number): number {
  return Math.round(value * factor)
}

function extractPointCoord(feature: WindGeoJSONFeature): [number, number] | null {
  if (feature.geometry?.type !== 'Point') return null
  const coords = feature.geometry.coordinates
  if (!Array.isArray(coords) || coords.length < 2) return null
  const lon = Number(coords[0])
  const lat = Number(coords[1])
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null
  return [lon, lat]
}

function buildDedupKey(
  feature: WindGeoJSONFeature,
  quantizeFactor: number,
): string | null {
  const coord = extractPointCoord(feature)
  if (!coord) return null
  const [lon, lat] = coord
  const height = String(feature.properties?.height ?? '_')
  return `${quantize(lon, quantizeFactor)}:${quantize(lat, quantizeFactor)}:${height}`
}

/**
 * 合并多个瓦片 GeoJSON 为单一 FeatureCollection。
 *
 * 对 Point 特征按“量化经纬度 + height”去重；保留第一次出现的特征。
 * 非 Point 特征直接追加，不参与去重。
 */
export function mergeWeatherTiles(
  tiles: MergedWeatherTile[],
  options?: { quantizeFactor?: number },
): WindGeoJSON {
  const quantizeFactor = options?.quantizeFactor ?? DEFAULT_QUANTIZE_FACTOR
  const seen = new Set<string>()
  const features: WindGeoJSONFeature[] = []

  for (const tile of tiles) {
    if (!tile?.geojson?.features?.length) continue
    for (const feature of tile.geojson.features) {
      const dedupKey = buildDedupKey(feature, quantizeFactor)
      if (dedupKey !== null) {
        if (seen.has(dedupKey)) continue
        seen.add(dedupKey)
      }
      features.push(feature)
    }
  }

  return {
    type: 'FeatureCollection',
    features,
  }
}

/** 计算瓦片集合的合并 bbox（用于 canvas layout）。 */
export function computeTilesBounds(tiles: MergedWeatherTile[]): LngLatBounds | null {
  if (!tiles.length) return null

  let west = Number.POSITIVE_INFINITY
  let south = Number.POSITIVE_INFINITY
  let east = Number.NEGATIVE_INFINITY
  let north = Number.NEGATIVE_INFINITY
  let hasCoord = false

  for (const tile of tiles) {
    if (!tile?.geojson?.features?.length) continue
    for (const feature of tile.geojson.features) {
      const coord = extractPointCoord(feature)
      if (!coord) continue
      const [lon, lat] = coord
      west = Math.min(west, lon)
      south = Math.min(south, lat)
      east = Math.max(east, lon)
      north = Math.max(north, lat)
      hasCoord = true
    }
  }

  if (!hasCoord) return null
  return { west, south, east, north }
}

/** 生成用于调试的合并统计。 */
export function buildMergeStats(tiles: MergedWeatherTile[]): MergeStats {
  const merged = mergeWeatherTiles(tiles)
  let totalFeatures = 0
  for (const tile of tiles) {
    totalFeatures += tile?.geojson?.features?.length ?? 0
  }
  return {
    tileCount: tiles.length,
    totalFeatures,
    uniqueFeatures: merged.features.length,
    duplicates: Math.max(0, totalFeatures - merged.features.length),
  }
}

/**
 * 为瓦片集合生成稳定的调试摘要字符串。
 * 不暴露给业务，仅用于 Console 日志。
 */
export function formatMergeStats(layerId: string, stats: MergeStats): string {
  return `[${layerId}] tiles=${stats.tileCount} total=${stats.totalFeatures} unique=${stats.uniqueFeatures} dup=${stats.duplicates}`
}
