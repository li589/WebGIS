import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const fetchWeatherTile = vi.fn()

vi.mock('../services/weather-tile-api', async () => {
  const actual = await vi.importActual<typeof import('../services/weather-tile-api')>(
    '../services/weather-tile-api',
  )
  return {
    ...actual,
    fetchWeatherTile: (...args: unknown[]) => fetchWeatherTile(...args),
  }
})

vi.mock('./log', () => ({
  useLogStore: () => ({
    logWorkflow: vi.fn(),
    logOperation: vi.fn(),
  }),
}))

vi.mock('./settings', () => ({
  useSettingsStore: () => ({
    weatherConfig: { cache_ttl_seconds: 3600 },
  }),
}))

import {
  useWeatherTileManager,
  __testResetWeatherTileManagerModuleState,
} from './weather-tile-manager'
import { tilesInBounds } from '../services/weather-tile-api'

const bbox = { west: 110, south: 20, east: 115, north: 25, crs: 'EPSG:4326' }
const center = { lng: 112.5, lat: 22.5 }
const emptyFc = { type: 'FeatureCollection', features: [] }

describe('weather-tile-manager cache + prefetch', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    __testResetWeatherTileManagerModuleState()
    fetchWeatherTile.mockReset()
    fetchWeatherTile.mockResolvedValue(emptyFc)
  })

  it('enqueues adjacent-hour viewport tiles (hour±1) at low priority', async () => {
    const manager = useWeatherTileManager()
    manager.setLayerActive('wind-field', true)
    manager.setViewport('wind-field', center, 5, 5, undefined, bbox)

    // 多轮 microtask + 让 priority 0/1 抽干后再调度 priority 3
    for (let i = 0; i < 80; i += 1) {
      await Promise.resolve()
    }

    const hours = new Set(
      fetchWeatherTile.mock.calls.map((args) => {
        const opts = args[4] as { hour?: number } | undefined
        return opts?.hour ?? 0
      }),
    )
    expect(hours.has(5)).toBe(true)
    expect(hours.has(4)).toBe(true)
    expect(hours.has(6)).toBe(true)
  })

  it('prefetch ring is wider than viewport (depth 3)', () => {
    const manager = useWeatherTileManager()
    manager.setLayerActive('temperature', true)
    manager.setViewport('temperature', center, 5, 0, undefined, bbox)

    const viewport = tilesInBounds(
      { west: bbox.west, south: bbox.south, east: bbox.east, north: bbox.north },
      5,
      0,
    )
    const ring3 = tilesInBounds(
      { west: bbox.west, south: bbox.south, east: bbox.east, north: bbox.north },
      5,
      3,
    )
    const status = manager.getLayerStatus('temperature')
    // pending+cached covers viewport + ring (+ parent/child/adj hours)
    expect(status.pending + status.cachedInViewport).toBeGreaterThan(viewport.length)
    expect(ring3.length).toBeGreaterThan(viewport.length)
  })

  it('invalidateAllTileCaches clears cache and requeues visible layers', async () => {
    const manager = useWeatherTileManager()
    manager.setLayerActive('wind-field', true)
    manager.setViewport('wind-field', center, 5, 0, undefined, bbox)

    for (let i = 0; i < 30; i += 1) {
      await Promise.resolve()
    }
    const callsBefore = fetchWeatherTile.mock.calls.length
    expect(callsBefore).toBeGreaterThan(0)

    manager.invalidateAllTileCaches()
    for (let i = 0; i < 30; i += 1) {
      await Promise.resolve()
    }
    expect(fetchWeatherTile.mock.calls.length).toBeGreaterThan(callsBefore)
  })

  it('skips re-fetch for fresh tiles on identical viewport', async () => {
    const manager = useWeatherTileManager()
    manager.setLayerActive('wind-field', true)
    manager.setViewport('wind-field', center, 5, 0, undefined, bbox)
    for (let i = 0; i < 40; i += 1) {
      await Promise.resolve()
    }
    const callsAfterFill = fetchWeatherTile.mock.calls.length

    manager.setViewport('wind-field', center, 5, 0, undefined, bbox)
    for (let i = 0; i < 10; i += 1) {
      await Promise.resolve()
    }
    // noop path: no new network for same fresh tiles
    expect(fetchWeatherTile.mock.calls.length).toBe(callsAfterFill)
  })

  it('isolates data-empty: sibling with tiles stays succeeded', async () => {
    fetchWeatherTile.mockImplementation(async (layerId: string) => {
      if (layerId === 'cloud_cover') {
        throw new Error('Weather tile HTTP 422: variable missing')
      }
      return emptyFc
    })

    const manager = useWeatherTileManager()
    manager.setLayerActive('cloud_cover', true)
    manager.setLayerActive('temperature', true)
    manager.setViewport('cloud_cover', center, 5, 0, undefined, bbox)
    manager.setViewport('temperature', center, 5, 0, undefined, bbox)

    for (let i = 0; i < 80; i += 1) {
      await Promise.resolve()
    }

    expect(manager.getLayerStatus('cloud_cover').errorType).toBe('data-empty')
    expect(manager.getLayerStatus('temperature').errorType).not.toBe('data-empty')
    expect(manager.getLayerStatus('temperature').cachedInViewport).toBeGreaterThan(0)

    const contrib = manager.deriveWeatherWorkflowContribution({ syncInProgress: false })
    const cloud = contrib.items.find((i) => i.catalogId === 'cloud_cover')
    const temp = contrib.items.find((i) => i.catalogId === 'temperature')
    expect(cloud?.status).toBe('failed')
    expect(temp?.status).toBe('succeeded')
  })

  it('retryLayerTiles clears dataEmptyScope so requests can resume', async () => {
    fetchWeatherTile.mockRejectedValue(new Error('HTTP 422 empty variable'))
    const manager = useWeatherTileManager()
    // 使用默认模型支持的图层，避免 UNSUPPORTED_LAYER_MODELS 短路
    manager.setLayerActive('temperature', true)
    manager.setViewport('temperature', center, 5, 0, undefined, bbox)
    for (let i = 0; i < 60; i += 1) {
      await Promise.resolve()
    }
    expect(manager.getLayerStatus('temperature').errorType).toBe('data-empty')
    const callsAfterEmpty = fetchWeatherTile.mock.calls.length
    expect(callsAfterEmpty).toBeGreaterThan(0)

    fetchWeatherTile.mockResolvedValue(emptyFc)
    manager.retryLayerTiles('temperature')
    for (let i = 0; i < 60; i += 1) {
      await Promise.resolve()
    }
    expect(fetchWeatherTile.mock.calls.length).toBeGreaterThan(callsAfterEmpty)
  })
})
