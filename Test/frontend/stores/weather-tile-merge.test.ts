/**
 * W3.4e：weather-tile-merge（视口合并 + 合并缓存）测试。
 *
 * 使用真实 tile 工具函数构造 LayerState：
 * 覆盖不可见短路、本级命中合并、合并缓存命中/淘汰/按层清理、
 * 父级 z-1 underlay 填洞、无瓦片时上一帧 stale-while-revalidate 裁剪、
 * 完全无数据时缓存 null 防重复计算。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  clearMergeCacheForLayer,
  getMergedGeojsonForViewport,
  type MergeCache,
} from '@/stores/weather-tile-merge'
import type { LayerState } from '@/stores/weather-tile-types'
import type { WindGeoJSON } from '@/types/map-geo'
import { makeTileEntry } from '@/stores/weather-tile-utils-store'
import { tileCoordsToKey } from '@/stores/weather-tile-utils-store'
import { tilesInBounds, tileToLngLatBounds, type LngLatBounds } from '@/services/weather-tile-api'

beforeEach(() => {
  setActivePinia(createPinia())
})

const BOUNDS: LngLatBounds = { west: 100, south: 30, east: 110, north: 40 }
const CENTER = { lng: 105, lat: 35 }
// z=4 时该视口仅 1 瓦片（覆盖率恒 1，underlay 分支不触发）；用 z=6（9 瓦片）
const Z = 6

function pointFeature(lng: number, lat: number, id: string): WindGeoJSON['features'][number] {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [lng, lat] },
    properties: { id, spd: 5, dir: 90 },
  } as never
}

function tileGeojsonCenter(z: number, x: number, y: number, id: string): WindGeoJSON {
  const b = tileToLngLatBounds(z, x, y)
  return {
    type: 'FeatureCollection',
    features: [pointFeature((b.west + b.east) / 2, (b.south + b.north) / 2, id)],
  } as WindGeoJSON
}

function makeState(overrides: Partial<LayerState> = {}): LayerState {
  return {
    layerId: 'wind',
    generation: 1,
    visible: true,
    center: CENTER,
    zoom: Z,
    mapZoom: Z,
    hour: 12,
    model: 'ecmwf_ifs025',
    provider: 'auto',
    bbox: BOUNDS,
    viewportTiles: [],
    prefetchRing: [],
    tiles: new Map(),
    pending: new Map(),
    lastMergedGeojson: null,
    lastMergedFeatureCount: 0,
    lastErrorType: null,
    lastErrorMessage: null,
    ...overrides,
  } as LayerState
}

function seedTiles(state: LayerState, coords: Array<{ z: number; x: number; y: number }>) {
  for (const c of coords) {
    const key = tileCoordsToKey(c, state.layerId, state.hour, state.model, state.provider)
    state.tiles.set(key, makeTileEntry(tileGeojsonCenter(c.z, c.x, c.y, `${c.z}/${c.x}/${c.y}`)))
  }
}

function deps(mergeCache: MergeCache) {
  return {
    mergeCache,
    debugLog: vi.fn(),
    countViewportMissing: () => 0,
  }
}

describe('getMergedGeojsonForViewport：基础路径', () => {
  it('state 缺失或不可见返回 null', () => {
    const cache: MergeCache = new Map()
    expect(getMergedGeojsonForViewport('wind', undefined, deps(cache))).toBeNull()
    const hidden = makeState({ visible: false })
    expect(getMergedGeojsonForViewport('wind', hidden, deps(cache))).toBeNull()
  })

  it('本级视口瓦片全部命中时合并并缓存', () => {
    const cache: MergeCache = new Map()
    const state = makeState()
    const viewportTiles = tilesInBounds(BOUNDS, Z, 0)
    seedTiles(state, viewportTiles)

    const merged = getMergedGeojsonForViewport('wind', state, deps(cache))!
    expect(merged.features.length).toBe(viewportTiles.length)
    expect(cache.size).toBe(1)

    // 二次调用走缓存：返回同一实例
    const again = getMergedGeojsonForViewport('wind', state, deps(cache))!
    expect(again).toBe(merged)
  })

  it('空瓦片（无特征）不计入合并与覆盖', () => {
    const cache: MergeCache = new Map()
    const state = makeState()
    const viewportTiles = tilesInBounds(BOUNDS, Z, 0)
    for (const c of viewportTiles) {
      const key = tileCoordsToKey(c, state.layerId, state.hour, state.model, state.provider)
      state.tiles.set(key, makeTileEntry({ type: 'FeatureCollection', features: [] } as WindGeoJSON))
    }
    const merged = getMergedGeojsonForViewport('wind', state, deps(cache))
    expect(merged).toBeNull()
  })
})

describe('父级 underlay 与邻近 z 填洞', () => {
  it('本级未齐时用 z-1 父级瓦片填洞', () => {
    const cache: MergeCache = new Map()
    const state = makeState()
    const viewportTiles = tilesInBounds(BOUNDS, Z, 0)
    expect(viewportTiles.length).toBe(9)
    const kept = viewportTiles.slice(0, 3)
    seedTiles(state, kept)
    seedTiles(state, tilesInBounds(BOUNDS, Z - 1, 0))

    const d = deps(cache)
    const merged = getMergedGeojsonForViewport('wind', state, d)!
    expect(merged.features.length).toBeGreaterThan(kept.length)
    expect(d.debugLog).toHaveBeenCalledWith(
      'getMergedGeojson',
      'wind',
      'multi-z-gap-fill',
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
    )
  })

  it('邻近更高 z 缓存垫底（zoom-out 场景）', () => {
    const cache: MergeCache = new Map()
    const state = makeState()
    const viewportTiles = tilesInBounds(BOUNDS, Z, 0)
    seedTiles(state, viewportTiles.slice(0, 3))
    // 在未覆盖的视口瓦片内种 z+2 子瓦片（dz=2 在半径 4 内），模拟 zoom-out 前的更高 z 缓存；
    // 若种在已覆盖瓦片范围内会被 filterGeojsonOutsideCoverage 正确去重，无法验证垫底路径
    const gapTile = viewportTiles[viewportTiles.length - 1]
    const childCoords = [0, 1].map((i) => ({
      z: Z + 2,
      x: gapTile.x * 4 + i,
      y: gapTile.y * 4,
    }))
    seedTiles(state, childCoords)

    const merged = getMergedGeojsonForViewport('wind', state, deps(cache))!
    expect(merged.features.length).toBeGreaterThan(3)
    const ids = merged.features.map((f) => (f.properties as { id: string }).id)
    for (const c of childCoords) expect(ids).toContain(`${c.z}/${c.x}/${c.y}`)
  })

  it('上一帧 lastMergedGeojson 在瓦片未齐时垫底', () => {
    const cache: MergeCache = new Map()
    const last: WindGeoJSON = {
      type: 'FeatureCollection',
      features: [pointFeature(105, 33, 'prev-in-gap'), pointFeature(150, 33, 'prev-out')],
    } as WindGeoJSON
    const state = makeState({ lastMergedGeojson: last, lastMergedFeatureCount: 2 })
    const viewportTiles = tilesInBounds(BOUNDS, Z, 0)
    // 仅覆盖 x=49 一列（west 侧），105° 落在未覆盖列 → 垫底生效
    seedTiles(state, viewportTiles.filter((t) => t.x === 49))

    const merged = getMergedGeojsonForViewport('wind', state, deps(cache))!
    const ids = merged.features.map((f) => (f.properties as { id: string }).id)
    expect(ids).toContain('prev-in-gap')
    expect(ids).not.toContain('prev-out')
    expect(merged.features.length).toBeGreaterThan(3)
  })
})

describe('stale-while-revalidate 与稀疏锚点', () => {
  it('无瓦片但有上一帧：上一帧垫底路径保留视口内特征并更新锚点', () => {
    const cache: MergeCache = new Map()
    const last: WindGeoJSON = {
      type: 'FeatureCollection',
      features: [pointFeature(101, 31, 'in'), pointFeature(150, 31, 'out')],
    } as WindGeoJSON
    const state = makeState({ lastMergedGeojson: last })
    const d = deps(cache)
    const merged = getMergedGeojsonForViewport('wind', state, d)!
    expect(merged.features.map((f) => (f.properties as { id: string }).id)).toEqual(['in'])
    expect(state.lastMergedGeojson).toBe(merged)
    expect(d.debugLog).toHaveBeenCalledWith(
      'getMergedGeojson',
      'wind',
      'multi-z-gap-fill',
      expect.anything(),
      expect.anything(),
      expect.anything(),
      expect.anything(),
    )
  })

  it('无瓦片且无上一帧：缓存 null 并返回 null', () => {
    const cache: MergeCache = new Map()
    const state = makeState()
    expect(getMergedGeojsonForViewport('wind', state, deps(cache))).toBeNull()
    expect([...cache.values()]).toEqual([null])
  })

  it('上一帧裁剪后无特征时返回 null（不缓存）', () => {
    const cache: MergeCache = new Map()
    const last: WindGeoJSON = {
      type: 'FeatureCollection',
      features: [pointFeature(150, 31, 'far-away')],
    } as WindGeoJSON
    const state = makeState({ lastMergedGeojson: last })
    expect(getMergedGeojsonForViewport('wind', state, deps(cache))).toBeNull()
    expect(cache.size).toBe(0)
  })
})

describe('合并缓存管理', () => {
  it('缓存超过 8 条淘汰最旧', () => {
    const cache: MergeCache = new Map()
    const state = makeState()
    const viewportTiles = tilesInBounds(BOUNDS, Z, 0)
    seedTiles(state, viewportTiles)
    for (let hour = 0; hour < 10; hour++) {
      const s = makeState({ hour })
      seedTiles(s, viewportTiles)
      getMergedGeojsonForViewport('wind', s, deps(cache))
    }
    expect(cache.size).toBeLessThanOrEqual(8)
    expect(state.tiles.size).toBe(viewportTiles.length)
  })

  it('clearMergeCacheForLayer 只清对应图层前缀', () => {
    const cache: MergeCache = new Map()
    cache.set('wind:a', null)
    cache.set('wind:b', null)
    cache.set('temp:c', null)
    clearMergeCacheForLayer(cache, 'wind')
    expect([...cache.keys()]).toEqual(['temp:c'])
  })
})
