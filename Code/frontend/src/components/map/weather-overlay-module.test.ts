import { describe, expect, it, vi } from 'vitest'

import { createWeatherOverlayModule } from './weather-overlay-module'

describe('weather-overlay-module', () => {
  it('composes resolver, facade, and watcher wiring', () => {
    const resolver = { resolveStates: vi.fn(() => []) }
    const facade = {
      scheduleSync: vi.fn(),
      runSyncNow: vi.fn(),
      dispose: vi.fn(),
    }
    const stopWatcher = vi.fn()
    const watchInputs = vi.fn((options: { scheduleSync: () => void }) => {
      options.scheduleSync()
      return stopWatcher
    })

    const module = createWeatherOverlayModule({
      map: {} as any,
      getMapReady: () => true,
      getActiveLayers: () => [],
      isWeatherEngineLayer: () => false,
      getMergedGeojsonForViewport: () => null,
      buildDefaultWeatherRenderHint: () => null,
      resolveApiUrl: (url: string) => url,
      getEnabledParticleFlowCatalogId: () => null,
      getDataVersion: () => 1,
      getCurrentHour: () => 12,
      debugLog: vi.fn(),
      dependencies: {
        createResolver: vi.fn(() => resolver as any),
        createFacade: vi.fn(() => facade),
        watchInputs,
      },
    })

    module.setupWatchers()
    module.runSyncNow()
    module.dispose()

    expect(watchInputs).toHaveBeenCalledTimes(1)
    expect(facade.scheduleSync).toHaveBeenCalledTimes(1)
    expect(facade.runSyncNow).toHaveBeenCalledTimes(1)
    expect(stopWatcher).toHaveBeenCalledTimes(1)
    expect(facade.dispose).toHaveBeenCalledTimes(1)
  })
})
