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

import { useWeatherTileManager } from './weather-tile-manager'

const bbox = { west: 110, south: 20, east: 115, north: 25, crs: 'EPSG:4326' }
const center = { lng: 112.5, lat: 22.5 }

describe('weather-tile-manager race guards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
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
