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
import { useWeatherEngineStore } from '@/stores/weather-engine'

const bbox = { west: 110, south: 20, east: 115, north: 25, crs: 'EPSG:4326' }
const center = { lng: 112.5, lat: 22.5 }
const emptyFc = { type: 'FeatureCollection', features: [] }

describe('weather-tile-manager model from weather-engine', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    __testResetWeatherTileManagerModuleState()
    fetchWeatherTile.mockReset()
    fetchWeatherTile.mockResolvedValue(emptyFc)
  })

  it('uses weather-engine defaultModel when setViewport omits model', async () => {
    const engine = useWeatherEngineStore()
    expect(engine.defaultModel).toBe('gfs_global')

    const manager = useWeatherTileManager()
    manager.setLayerActive('temperature', true)
    manager.setViewport('temperature', center, 5, 0, undefined, bbox)

    for (let i = 0; i < 40; i += 1) {
      await Promise.resolve()
    }

    expect(fetchWeatherTile.mock.calls.length).toBeGreaterThan(0)
    const models = fetchWeatherTile.mock.calls.map((args) => {
      const opts = args[4] as { model?: string } | undefined
      return opts?.model
    })
    expect(models.every((m) => m === 'gfs_global')).toBe(true)
  })
})