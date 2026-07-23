import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

import {
  useWeatherTileManager,
  __testResetWeatherTileManagerModuleState,
} from './weather-tile-manager'

const bbox = { west: 110, south: 20, east: 115, north: 25, crs: 'EPSG:4326' }
const center = { lng: 112.5, lat: 22.5 }

describe('weather-tile-manager race guards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    __testResetWeatherTileManagerModuleState()
    fetchWeatherTile.mockReset()
  })

  it('discards tile writes after layer is hidden', async () => {
    let resolveFetch!: (value: { type: string; features: unknown[] }) => void
    fetchWeatherTile.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve
        }),
    )

    const manager = useWeatherTileManager()
    manager.setLayerActive('wind-field', true)
    manager.setViewport('wind-field', center, 5, 0, undefined, bbox)
    expect(manager.getLayerStatus('wind-field').pending).toBeGreaterThan(0)

    const versionBeforeHide = manager.dataVersion
    manager.setLayerActive('wind-field', false)

    resolveFetch({ type: 'FeatureCollection', features: [] })
    await Promise.resolve()
    await Promise.resolve()

    expect(manager.dataVersion).toBe(versionBeforeHide)
    expect(manager.getMergedGeojsonForViewport('wind-field')).toBeNull()
  })

  it('skips identical setViewport without raising pending churn', async () => {
    fetchWeatherTile.mockResolvedValue({ type: 'FeatureCollection', features: [] })

    const manager = useWeatherTileManager()
    manager.setLayerActive('wind-field', true)
    manager.setViewport('wind-field', center, 5, 0, undefined, bbox)
    const pendingAfterFirst = manager.getLayerStatus('wind-field').pending

    manager.setViewport('wind-field', center, 5, 0, undefined, bbox)
    expect(manager.getLayerStatus('wind-field').pending).toBe(pendingAfterFirst)
  })
})

describe('weather-tile-manager gap sweep', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    __testResetWeatherTileManagerModuleState()
    fetchWeatherTile.mockReset()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('reports missingInViewport and keeps gapSweepActive while holes remain', async () => {
    let successLeft = 2
    fetchWeatherTile.mockImplementation(async (_layerId, _z, _x, _y, opts) => {
      // 仅当前 hour 的前 2 个视口请求成功，避免邻域/邻小时预取抢掉成功配额
      const hour = (opts as { hour?: number } | undefined)?.hour ?? 0
      if (hour !== 0) {
        throw new Error('Weather tile request timeout after 75s: prefetch')
      }
      if (successLeft > 0) {
        successLeft -= 1
        return { type: 'FeatureCollection', features: [] }
      }
      throw new Error('Weather tile request timeout after 75s: /weather/tiles/x')
    })

    const manager = useWeatherTileManager()
    manager.setLayerActive('temperature', true)
    manager.setViewport('temperature', center, 5, 0, undefined, bbox)

    for (let i = 0; i < 20; i += 1) {
      await vi.advanceTimersByTimeAsync(5_000)
      await Promise.resolve()
    }

    const status = manager.getLayerStatus('temperature')
    expect(status.active).toBe(true)
    expect(status.viewportTotal).toBeGreaterThan(0)
    expect(status.cachedInViewport).toBeGreaterThan(0)
    expect(status.missingInViewport).toBeGreaterThan(0)
    expect(status.gapSweepActive).toBe(true)

    // 补洞扫描可安全重入（不抛错）；有空洞时应继续挂着定时器
    manager.__testRunGapSweepNow('temperature')
    expect(manager.getLayerStatus('temperature').gapSweepActive).toBe(true)
    expect(manager.getLayerStatus('temperature').missingInViewport).toBeGreaterThan(0)
  })

  it('clears gap sweep when layer is hidden', async () => {
    fetchWeatherTile.mockRejectedValue(new Error('Weather tile request timeout after 75s: x'))

    const manager = useWeatherTileManager()
    manager.setLayerActive('temperature', true)
    manager.setViewport('temperature', center, 5, 0, undefined, bbox)

    for (let i = 0; i < 30; i += 1) {
      await vi.advanceTimersByTimeAsync(5_000)
      await Promise.resolve()
    }
    expect(manager.getLayerStatus('temperature').gapSweepActive).toBe(true)

    manager.setLayerActive('temperature', false)
    expect(manager.getLayerStatus('temperature').gapSweepActive).toBe(false)
    expect(manager.getLayerStatus('temperature').active).toBe(false)
  })
})
