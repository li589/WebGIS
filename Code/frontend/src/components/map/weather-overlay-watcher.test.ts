import { effectScope, nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

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

describe('weather-overlay-watcher', () => {
  it('schedules sync when weather watcher inputs change', async () => {
    const scope = effectScope()
    const scheduleSync = vi.fn()
    const debugLog = vi.fn()
    const activeLayers = ref([createLayer()])
    const particleFlowCatalogId = ref<string | null>('weather.wind')
    const dataVersion = ref(1)
    const currentHour = ref(12)

    scope.run(() => {
      watchWeatherOverlayInputs({
        getActiveLayers: () => activeLayers.value,
        getParticleFlowCatalogId: () => particleFlowCatalogId.value,
        getDataVersion: () => dataVersion.value,
        getCurrentHour: () => currentHour.value,
        scheduleSync,
        debugLog,
      })
    })

    await nextTick()
    scheduleSync.mockClear()

    dataVersion.value = 2
    await nextTick()

    expect(scheduleSync).toHaveBeenCalledTimes(1)
    expect(debugLog).toHaveBeenCalled()

    scope.stop()
  })
})
