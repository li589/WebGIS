import { describe, expect, it, vi } from 'vitest'

import { createMapCanvasWeatherOverlayModule } from './map-canvas-weather-overlay-module'

describe('map-canvas-weather-overlay-module', () => {
  it('adapts MapCanvas stores into weather overlay module inputs', () => {
    const createWeatherOverlayModule = vi.fn(() => ({
      setupWatchers: vi.fn(),
      scheduleSync: vi.fn(),
      runSyncNow: vi.fn(),
      dispose: vi.fn(),
    }))

    const module = createMapCanvasWeatherOverlayModule({
      map: {} as any,
      getMapReady: () => true,
      layersStore: {
        activeLayersDisplay: [],
        particleFlowCatalogId: 'weather.wind',
        isWeatherEngineLayer: (catalogId: string) => catalogId === 'weather.wind',
      },
      weatherTileManager: {
        getMergedGeojsonForViewport: vi.fn(() => null),
        dataVersion: 3,
      },
      getCurrentHour: () => 12,
      debugLog: vi.fn(),
      dependencies: {
        createWeatherOverlayModule,
      },
    } as any)

    expect(createWeatherOverlayModule).toHaveBeenCalledTimes(1)
    expect(module).toBe(createWeatherOverlayModule.mock.results[0].value)
  })
})
