/**
 * Weather tile manager — viewport merge + merge cache (P1-1 split).
 */
import {
  lngLatToTile,
  TILE_KEY_PREFIX,
  tileToLngLatBounds,
  tilesInBounds,
  type LngLatBounds,
  type WeatherTileCoords,
} from '../services/weather-tile-api'
import {
  filterGeojsonInsideTileBounds,
  filterGeojsonOutsideCoverage,
  mergeWeatherTiles,
  tileBoundsOverlapViewport,
  type MergedWeatherTile,
} from '../services/weather-tile-utils'
import type { WindGeoJSON } from '../types/map-geo'
import { parseTileCoordsFromCacheKey, type DebugLogFn } from './weather-tile-errors'
import type { LayerState } from './weather-tile-types'
import { boundsFromCenter, tileCoordsToKey, touchTileEntry } from './weather-tile-utils-store'

export type MergeCache = Map<string, WindGeoJSON | null>

const MERGE_CACHE_MAX = 8

export function clearMergeCacheForLayer(mergeCache: MergeCache, layerId: string): void {
  for (const key of Array.from(mergeCache.keys())) {
    if (key.startsWith(`${layerId}:`)) mergeCache.delete(key)
  }
}

function buildMergeCacheKey(
  layerId: string,
  state: LayerState,
  clampedZoom: number,
  bounds: LngLatBounds,
  coverageSig: string,
): string {
  return `${layerId}:${state.generation}:${state.hour}:${clampedZoom}:${bounds.west.toFixed(3)},${bounds.south.toFixed(3)},${bounds.east.toFixed(3)},${bounds.north.toFixed(3)}:c=${coverageSig}`
}

function rememberMergeCache(
  mergeCache: MergeCache,
  key: string,
  value: WindGeoJSON | null,
): WindGeoJSON | null {
  mergeCache.set(key, value)
  if (mergeCache.size > MERGE_CACHE_MAX) {
    const firstKey = mergeCache.keys().next().value
    if (firstKey !== undefined) {
      mergeCache.delete(firstKey)
    }
  }
  return value
}

export function getMergedGeojsonForViewport(
  layerId: string,
  state: LayerState | undefined,
  deps: {
    mergeCache: MergeCache
    debugLog: DebugLogFn
    countViewportMissing: (state: LayerState) => number
  },
): WindGeoJSON | null {
  const { mergeCache, debugLog, countViewportMissing } = deps
  if (!state || !state.visible) {
    debugLog('getMergedGeojson', layerId, 'state=', !!state, 'visible=', state?.visible)
    return null
  }

  const clampedZoom = state.zoom
  const bounds = state.bbox ?? boundsFromCenter(state.center, clampedZoom)
  const viewportTiles = tilesInBounds(bounds, clampedZoom, 0)
  const currentMatched: MergedWeatherTile[] = []
  const parentMatched: MergedWeatherTile[] = []
  const nAtZoom = 2 ** clampedZoom

  const cachedKeys = Array.from(state.tiles.keys()).map((k) => {
    const zMatch = /:z(\d+):/.exec(k)
    const xMatch = /:x(\d+):/.exec(k)
    const yMatch = /:y(\d+):/.exec(k)
    const hMatch = /:h(\d+)/.exec(k)
    return `z${zMatch?.[1]}:x${xMatch?.[1]}:y${yMatch?.[1]}:h${hMatch?.[1]}`
  })

  const hitKeys: string[] = []
  const hitTiles: WeatherTileCoords[] = []
  for (const tile of viewportTiles) {
    const key = tileCoordsToKey(tile, layerId, state.hour, state.model, state.provider)
    const entry = state.tiles.get(key)
    if (!entry) continue
    const raw = touchTileEntry(entry)
    const tileBounds = tileToLngLatBounds(tile.z, tile.x, tile.y)
    const geojson = filterGeojsonInsideTileBounds(raw, tileBounds, {
      includeEast: tile.x >= nAtZoom - 1,
      includeSouth: tile.y >= nAtZoom - 1,
    })
    if (!geojson.features?.length) continue
    // 仅有实际特征的瓦片才计入覆盖率，防止空瓦片膨胀 coverage 导致 underlay 被跳过
    hitKeys.push(`${tile.x},${tile.y}`)
    hitTiles.push(tile)
    currentMatched.push({
      layerId,
      z: tile.z,
      x: tile.x,
      y: tile.y,
      hour: state.hour,
      geojson,
    })
  }

  const coverageSig = `${hitKeys.length}/${viewportTiles.length}:${hitKeys.join('|')}`
  const cacheKey = buildMergeCacheKey(layerId, state, clampedZoom, bounds, coverageSig)
  const cached = mergeCache.get(cacheKey)
  if (cached !== undefined) {
    return cached
  }

  const currentCoverage = viewportTiles.length > 0 ? hitKeys.length / viewportTiles.length : 0

  // 父级 underlay：本级未齐时用 z-1 填洞
  const PARENT_UNDERLAY_COVERAGE_MAX = 0.92
  /** 缩放换 z 后沿用邻近级缓存（含更高 z 旧瓦片），避免「只剩缩放前那一块」 */
  const NEARBY_Z_UNDERLAY_RADIUS = 4
  const gapFillMatched: MergedWeatherTile[] = []
  if (clampedZoom > 0 && currentCoverage < PARENT_UNDERLAY_COVERAGE_MAX) {
    const coveredBounds = hitTiles.map((tile) => tileToLngLatBounds(tile.z, tile.x, tile.y))
    const parentZ = clampedZoom - 1
    const nParent = 2 ** parentZ
    const parentTiles = tilesInBounds(bounds, parentZ, 0)
    for (const tile of parentTiles) {
      const key = tileCoordsToKey(tile, layerId, state.hour, state.model, state.provider)
      const entry = state.tiles.get(key)
      if (!entry) continue
      const raw = touchTileEntry(entry)
      const tileBounds = tileToLngLatBounds(tile.z, tile.x, tile.y)
      const clippedToParent = filterGeojsonInsideTileBounds(raw, tileBounds, {
        includeEast: tile.x >= nParent - 1,
        includeSouth: tile.y >= nParent - 1,
      })
      const geojson =
        coveredBounds.length > 0
          ? filterGeojsonOutsideCoverage(clippedToParent, coveredBounds)
          : clippedToParent
      if (!geojson.features?.length) continue
      parentMatched.push({
        layerId,
        z: tile.z,
        x: tile.x,
        y: tile.y,
        hour: state.hour,
        geojson,
      })
      coveredBounds.push(tileBounds)
    }

    // 邻近 z 缓存垫底（尤其 zoom-out 后仍保留的更高 z 瓦片）
    // key 形如 `weather:tile:{layerId}:z...`，归属判断必须带完整前缀，
    // 仅 `startsWith(layerId:)` 恒为 false 会让整个垫底分支失效
    const nearby: Array<{ z: number; x: number; y: number; raw: WindGeoJSON; dz: number }> = []
    for (const [cacheKey, entry] of state.tiles.entries()) {
      if (!cacheKey.startsWith(`${TILE_KEY_PREFIX}${layerId}:`)) continue
      const coords = parseTileCoordsFromCacheKey(cacheKey)
      if (!coords) continue
      const { z, x, y } = coords
      if (z === clampedZoom || z === parentZ) continue
      const dz = Math.abs(z - clampedZoom)
      if (dz < 1 || dz > NEARBY_Z_UNDERLAY_RADIUS) continue
      // 仅同 hour/model/provider：cacheKey 已含这些字段，layer 前缀匹配即可
      if (!cacheKey.includes(`:h${state.hour}`)) continue
      const tileBounds = tileToLngLatBounds(z, x, y)
      if (!tileBoundsOverlapViewport(tileBounds, bounds)) continue
      nearby.push({ z, x, y, raw: touchTileEntry(entry), dz })
    }
    nearby.sort((a, b) => a.dz - b.dz || a.z - b.z)
    for (const c of nearby) {
      const n = 2 ** c.z
      const tileBounds = tileToLngLatBounds(c.z, c.x, c.y)
      const clipped = filterGeojsonInsideTileBounds(c.raw, tileBounds, {
        includeEast: c.x >= n - 1,
        includeSouth: c.y >= n - 1,
      })
      let geojson =
        coveredBounds.length > 0 ? filterGeojsonOutsideCoverage(clipped, coveredBounds) : clipped
      geojson = filterGeojsonInsideTileBounds(geojson, bounds, {
        includeEast: true,
        includeSouth: true,
      })
      if (!geojson.features?.length) continue
      gapFillMatched.push({
        layerId,
        z: c.z,
        x: c.x,
        y: c.y,
        hour: state.hour,
        geojson,
      })
      coveredBounds.push(tileBounds)
    }

    // 上一帧垫底：边缘本级瓦片先到、父/邻级未齐时，避免「中心空洞、周围有数」
    if (
      state.lastMergedGeojson?.features?.length &&
      (state.pending.size > 0 || hitKeys.length < viewportTiles.length)
    ) {
      let swr = filterGeojsonOutsideCoverage(state.lastMergedGeojson, coveredBounds)
      swr = filterGeojsonInsideTileBounds(swr, bounds, {
        includeEast: true,
        includeSouth: true,
      })
      if (swr.features?.length) {
        gapFillMatched.push({
          layerId,
          z: clampedZoom,
          x: -1,
          y: -1,
          hour: state.hour,
          geojson: swr,
        })
      }
    }
  }

  // 本级优先 → 父级 → 邻近 z / 上一帧垫底
  const mergedTiles: MergedWeatherTile[] = [...currentMatched, ...parentMatched, ...gapFillMatched]

  if (parentMatched.length > 0 || gapFillMatched.length > 0) {
    debugLog(
      'getMergedGeojson',
      layerId,
      'multi-z-gap-fill',
      `needZ=${clampedZoom}`,
      `current=${currentMatched.length}/${viewportTiles.length}`,
      `parent=${parentMatched.length}`,
      `nearby=${gapFillMatched.length}`,
    )
  }

  debugLog(
    'getMergedGeojson',
    layerId,
    `gen=${state.generation}`,
    `zoom=${state.zoom}->${clampedZoom}`,
    `hour=${state.hour}`,
    `bbox=${state.bbox ? `${state.bbox.west.toFixed(1)},${state.bbox.south.toFixed(1)},${state.bbox.east.toFixed(1)},${state.bbox.north.toFixed(1)}` : 'null'}`,
    `viewportTiles=${viewportTiles.map((t) => `${t.x},${t.y}`).join('|')}`,
    `cached=${state.tiles.size}:[${cachedKeys.join(',')}]`,
    `matched=${mergedTiles.length}`,
    `coverage=${currentCoverage.toFixed(2)}`,
  )

  if (!mergedTiles.length) {
    // 新瓦片未就绪：用上一帧裁到新视口，避免整屏闪空或粘住旧区域。
    // 条件放宽到「只要有旧帧就沿用」：即使所有瓦片已缓存但为空（pending=0,
    // missing=0），旧帧仍能提供流线/粒子数据，避免控制器被 reset 后永久空白。
    // 新瓦片到达后 dataVersion bump → 新 sync 自然覆盖旧帧。
    if (state.lastMergedGeojson) {
      const clipped = filterGeojsonInsideTileBounds(state.lastMergedGeojson, bounds, {
        includeEast: true,
        includeSouth: true,
      })
      const n = clipped.features?.length ?? 0
      debugLog(
        'getMergedGeojson',
        layerId,
        'stale-while-revalidate clipped',
        `pending=${state.pending.size}`,
        `missing=${countViewportMissing(state)}`,
        `kept=${n}`,
      )
      if (n > 0) return clipped
      return null
    }
    return rememberMergeCache(mergeCache, cacheKey, null)
  }
  const merged = mergeWeatherTiles(mergedTiles)
  const featureCount = Array.isArray(merged.features) ? merged.features.length : 0
  // 覆盖未齐且新合并明显变稀：仍返回含 underlay/上一帧垫底的合并结果，
  // 但勿把「边缘已到、中心仍空」的稀缺帧写成 lastMerged 锚点。
  const sparseWhileLoading =
    currentCoverage < PARENT_UNDERLAY_COVERAGE_MAX &&
    state.lastMergedGeojson &&
    state.lastMergedFeatureCount > 0 &&
    featureCount < state.lastMergedFeatureCount * 0.7 &&
    (state.pending.size > 0 || countViewportMissing(state) > 0)
  if (sparseWhileLoading) {
    debugLog(
      'getMergedGeojson',
      layerId,
      'stale-while-revalidate sparse keep-anchor',
      `new=${featureCount}`,
      `prev=${state.lastMergedFeatureCount}`,
      `pending=${state.pending.size}`,
      `coverage=${currentCoverage.toFixed(2)}`,
    )
    return rememberMergeCache(mergeCache, cacheKey, merged)
  }
  // 本级有命中、邻近垫底或覆盖率足够时更新 stale 锚点
  // 宽跨度：适中覆盖或已有本级命中即可更新锚点（过严 0.85 会导致半屏 SWR 不稳）
  const lonSpan = bounds.east - bounds.west
  const wideSpan = lonSpan > 180
  const centerTile = lngLatToTile(state.center.lng, state.center.lat, clampedZoom)
  const centerCached = state.tiles.has(
    tileCoordsToKey(centerTile, layerId, state.hour, state.model, state.provider),
  )
  const coverageGate = wideSpan
    ? currentCoverage >= 0.65 && (centerCached || currentCoverage >= 0.85)
    : currentCoverage >= 0.5
  if (
    currentMatched.length > 0 ||
    parentMatched.length > 0 ||
    gapFillMatched.length > 0 ||
    coverageGate ||
    !state.lastMergedGeojson
  ) {
    if (
      !wideSpan ||
      coverageGate ||
      currentMatched.length > 0 ||
      parentMatched.length > 0 ||
      !state.lastMergedGeojson
    ) {
      state.lastMergedGeojson = merged
      state.lastMergedFeatureCount = featureCount
    }
  }
  return rememberMergeCache(mergeCache, cacheKey, merged)
}
