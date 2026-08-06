import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const fetchWeatherTile = vi.fn()

vi.mock('@/services/weather-tile-api', async () => {
  const actual = await vi.importActual<typeof import('@/services/weather-tile-api')>(
    '@/services/weather-tile-api',
  )
  return {
    ...actual,
    fetchWeatherTile: (...args: unknown[]) => fetchWeatherTile(...args),
  }
})

vi.mock('@/stores/log', () => ({
  useLogStore: () => ({
    logWorkflow: vi.fn(),
    logOperation: vi.fn(),
  }),
}))

vi.mock('@/stores/settings', () => ({
  useSettingsStore: () => ({
    weatherConfig: {
      default_model: 'gfs_global',
      sync_domains: ['gfs_global'],
      cache_ttl_seconds: 3600,
    },
  }),
}))

import {
  useWeatherTileManager,
  __testResetWeatherTileManagerModuleState,
} from '@/stores/weather-tile-manager'

const bbox = { west: 110, south: 20, east: 115, north: 25, crs: 'EPSG:4326' }
const center = { lng: 112.5, lat: 22.5 }

describe('weather-tile-manager multi-layer scheduling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    __testResetWeatherTileManagerModuleState()
    fetchWeatherTile.mockReset()
  })

  it('round-robins viewport fetches across visible layers', async () => {
    const resolvers: Array<() => void> = []
    fetchWeatherTile.mockImplementation(
      () =>
        new Promise<{ type: string; features: unknown[] }>((resolve) => {
          resolvers.push(() => resolve({ type: 'FeatureCollection', features: [] }))
        }),
    )

    const manager = useWeatherTileManager()
    manager.setLayerActive('temperature', true)
    manager.setLayerActive('humidity', true)
    // First viewport fills the concurrency cap with one layer; second enqueues behind it
    manager.setViewport('temperature', center, 5, 0, undefined, bbox)
    manager.setViewport('humidity', center, 5, 0, undefined, bbox)
    expect(fetchWeatherTile.mock.calls.length).toBeGreaterThan(0)

    // Free slots so drainQueue re-picks; round-robin should include humidity promptly
    for (const resolve of [...resolvers]) resolve()
    resolvers.length = 0
    for (let i = 0; i < 20; i += 1) {
      await Promise.resolve()
    }

    const afterRelease = fetchWeatherTile.mock.calls.map((c) => c[0] as string)
    expect(afterRelease).toContain('temperature')
    expect(afterRelease).toContain('humidity')
    // Among the first few post-release dispatches, humidity should appear (not starved)
    const humidityIndex = afterRelease.indexOf('humidity')
    expect(humidityIndex).toBeGreaterThanOrEqual(0)
    expect(humidityIndex).toBeLessThan(12)
  })

  it('skips adjacent-hour prefetch when multiple weather layers are active', async () => {
    fetchWeatherTile.mockResolvedValue({ type: 'FeatureCollection', features: [] })

    const manager = useWeatherTileManager()
    manager.setLayerActive('temperature', true)
    manager.setLayerActive('humidity', true)
    manager.setViewport('temperature', center, 5, 12, undefined, bbox)
    manager.setViewport('humidity', center, 5, 12, undefined, bbox)

    for (let i = 0; i < 80; i += 1) {
      await Promise.resolve()
    }

    const hours = fetchWeatherTile.mock.calls.map((args) => {
      const opts = args[4] as { hour?: number } | undefined
      return opts?.hour ?? 0
    })
    expect(hours.every((h) => h === 12)).toBe(true)
  })
})
