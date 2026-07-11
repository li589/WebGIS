import { effectScope, nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { createWeatherOverlayFacade } from './weather-overlay-facade'
import { watchWeatherOverlayInputs } from './weather-overlay-watcher'

function createLayer(overrides: Record<string, unknown> = {}) {
  return {
    instanceId: 'layer-1',
    catalogId: 'weather.wind',
    name: 'Wind',
    category: 'weather',
    summary: '',
    metricLabel: '',
    metricValue: '',
    trendLabel: '',
    statusLabel: '',
    updateLabel: '',
    sourceLabel: '',
    confidenceLabel: '',
    accentColor: '',
    accentGlow: '',
    chipTone: '',
    availabilityState: 'ready',
    availabilityLabel: '',
    availabilityDescription: '',
    observationTimeLabel: '',
    missingFieldsLabel: '',
    hotspots: [],
    isAdminBoundary: false,
    visible: true,
    opacity: 1,
    order: 0,
    dataState: 'real',
    ...overrides,
  } as any
}

describe('weather overlay watcher + facade integration', () => {
  it('drives runtime sync when watcher inputs change', async () => {
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

    const activeLayers = ref([createLayer()])
    const particleFlowCatalogId = ref<string | null>('weather.wind')
    const dataVersion = ref(1)
    const currentHour = ref(12)

    const facade = createWeatherOverlayFacade({
      map: {} as any,
      getMapReady: () => true,
      resolver: { resolveStates: () => [] },
      getEnabledParticleFlowCatalogId: () => particleFlowCatalogId.value,
      debugLog: vi.fn(),
      dependencies: {
        createWindParticleController: vi.fn(() => ({}) as any),
        createSession: vi.fn(() => session as any),
        createScheduler: vi.fn(() => scheduler as any),
        createRuntimeOrchestrator: vi.fn(() => runtimeOrchestrator as any),
      },
    })

    const scope = effectScope()
    scope.run(() => {
      watchWeatherOverlayInputs({
        getActiveLayers: () => activeLayers.value,
        getParticleFlowCatalogId: () => particleFlowCatalogId.value,
        getDataVersion: () => dataVersion.value,
        getCurrentHour: () => currentHour.value,
        scheduleSync: facade.scheduleSync,
        debugLog: vi.fn(),
      })
    })

    await nextTick()
    scheduler.schedule.mockClear()

    dataVersion.value = 2
    await nextTick()

    expect(scheduler.schedule).toHaveBeenCalledTimes(1)
    expect(scheduledCallback).not.toBeNull()

    scheduledCallback!()

    expect(scheduler.beginSync).toHaveBeenCalledTimes(1)
    expect(runtimeOrchestrator.sync).toHaveBeenCalledWith(5)

    scope.stop()
  })
})
