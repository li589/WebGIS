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
        windDisplayMode: 'particle',
        isWeatherEngineLayer: (catalogId: string) => catalogId === 'weather.wind',
      },
      weatherTileManager: {
        getMergedGeojsonForViewport: vi.fn(() => null),
        getViewportBounds: vi.fn(() => null),
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
    const args = createWeatherOverlayModule.mock.calls[0][0]
    expect(args.getEnabledParticleFlowCatalogId()).toBe('weather.wind')
  })

  it('returns particleFlowCatalogId even when windDisplayMode is off (controller handles off internally)', () => {
    const createWeatherOverlayModule = vi.fn(() => ({
      setupWatchers: vi.fn(),
      scheduleSync: vi.fn(),
      runSyncNow: vi.fn(),
      dispose: vi.fn(),
    }))

    createMapCanvasWeatherOverlayModule({
      map: {} as any,
      getMapReady: () => true,
      layersStore: {
        activeLayersDisplay: [],
        particleFlowCatalogId: 'weather.wind',
        windDisplayMode: 'off',
        smoothRendering: true,
        isWeatherEngineLayer: () => true,
      },
      weatherTileManager: {
        getMergedGeojsonForViewport: vi.fn(() => null),
        getViewportBounds: vi.fn(() => null),
        dataVersion: 1,
      },
      getCurrentHour: () => 0,
      debugLog: vi.fn(),
      dependencies: { createWeatherOverlayModule },
    } as any)

    const args = createWeatherOverlayModule.mock.calls[0][0]
    // wind "off" 模式仍返回 catalogId，由粒子控制器内部处理 off → 风速底色渲染
    expect(args.getEnabledParticleFlowCatalogId()).toBe('weather.wind')
  })
})
