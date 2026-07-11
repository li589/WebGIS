import { describe, expect, it, vi } from 'vitest'

import { createWeatherOverlayFacade } from './weather-overlay-facade'

describe('weather-overlay-facade', () => {
  it('routes scheduled sync through the scheduler and runtime orchestrator', () => {
    let scheduledCallback: (() => void) | null = null
    const scheduler = {
      getCurrentToken: vi.fn(() => 4),
      beginSync: vi.fn(() => 5),
      schedule: vi.fn((callback: () => void) => {
        scheduledCallback = callback
      }),
      runNow: vi.fn(),
      dispose: vi.fn(),
    }
    const session = {
      renderedCatalogIds: [],
      markRendered: vi.fn(),
      removeCatalogOverlay: vi.fn(),
      removeAllOverlays: vi.fn(),
    }
    const runtimeOrchestrator = {
      sync: vi.fn(),
    }

    const facade = createWeatherOverlayFacade({
      map: {} as any,
      getMapReady: () => true,
      resolver: { resolveStates: () => [] },
      getEnabledParticleFlowCatalogId: () => null,
      debugLog: vi.fn(),
      dependencies: {
        createWindParticleController: vi.fn(() => ({}) as any),
        createSession: vi.fn(() => session as any),
        createScheduler: vi.fn(() => scheduler as any),
        createRuntimeOrchestrator: vi.fn(() => runtimeOrchestrator as any),
      },
    })

    facade.scheduleSync()
    expect(scheduler.schedule).toHaveBeenCalledTimes(1)

    expect(scheduledCallback).not.toBeNull()
    scheduledCallback!()

    expect(scheduler.beginSync).toHaveBeenCalledTimes(1)
    expect(runtimeOrchestrator.sync).toHaveBeenCalledWith(5)
  })

  it('skips runtime sync when map is not ready and disposes owned resources', () => {
    let runNowCallback: (() => void) | null = null
    const scheduler = {
      getCurrentToken: vi.fn(() => 1),
      beginSync: vi.fn(() => 2),
      schedule: vi.fn(),
      runNow: vi.fn((callback: () => void) => {
        runNowCallback = callback
      }),
      dispose: vi.fn(),
    }
    const session = {
      renderedCatalogIds: [],
      markRendered: vi.fn(),
      removeCatalogOverlay: vi.fn(),
      removeAllOverlays: vi.fn(),
    }
    const runtimeOrchestrator = {
      sync: vi.fn(),
    }

    const facade = createWeatherOverlayFacade({
      map: {} as any,
      getMapReady: () => false,
      resolver: { resolveStates: () => [] },
      getEnabledParticleFlowCatalogId: () => null,
      debugLog: vi.fn(),
      dependencies: {
        createWindParticleController: vi.fn(() => ({}) as any),
        createSession: vi.fn(() => session as any),
        createScheduler: vi.fn(() => scheduler as any),
        createRuntimeOrchestrator: vi.fn(() => runtimeOrchestrator as any),
      },
    })

    facade.runSyncNow()
    expect(runNowCallback).not.toBeNull()
    runNowCallback!()
    facade.dispose()

    expect(runtimeOrchestrator.sync).not.toHaveBeenCalled()
    expect(scheduler.dispose).toHaveBeenCalledTimes(1)
    expect(session.removeAllOverlays).toHaveBeenCalledTimes(1)
  })
})
