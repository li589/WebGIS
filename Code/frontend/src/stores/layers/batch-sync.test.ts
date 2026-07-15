import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const setLayerActive = vi.fn()
const clearLayer = vi.fn()
const setViewport = vi.fn()

vi.mock('../weather-tile-manager', () => ({
  useWeatherTileManager: () => ({
    setLayerActive,
    clearLayer,
    setViewport,
    getLayerStatus: () => ({
      active: false,
      cachedInViewport: 0,
      viewportTotal: 0,
      pending: 0,
      errorType: null,
      errorMessage: null,
    }),
    getMergedGeojsonForViewport: () => null,
    getDataVersion: () => 0,
    dataVersion: { value: 0 },
    statusVersion: { value: 0 },
    activityVersion: { value: 0 },
  }),
}))

vi.mock('../../services/runtime-api', () => ({
  fetchLayerCatalog: vi.fn(async () => ({ items: [] })),
  submitWorkflow: vi.fn(),
  getWorkflowRun: vi.fn(),
  getWorkflowEvents: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  retryWorkflowRun: vi.fn(),
  getWeatherPoint: vi.fn(),
}))

vi.mock('../../services/layer-capabilities', () => ({
  isWeatherLayerDescriptor: () => true,
  supportsMapLayerCapability: () => false,
  supportsParticleFlowCapability: () => false,
  supportsViewportDrivenRefreshCapability: () => false,
}))

vi.mock('../../components/map/weather-render', () => ({
  buildDefaultWeatherRenderHint: () => null,
}))

vi.mock('./result-adapter', () => ({
  buildJobLayer: vi.fn(),
}))

import { useLayersStore } from './index'

describe('layers store batch sync with weather tile manager', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setLayerActive.mockReset()
    clearLayer.mockReset()
    setViewport.mockReset()
  })

  it('setAllLayerVisibility syncs tile manager active state', () => {
    const store = useLayersStore()
    store.activeLayers.push({
      instanceId: 'inst-1',
      catalogId: 'wind-field',
      name: 'Wind',
      visible: true,
      opacity: 1,
      isAdminBoundary: false,
    } as any)

    store.setAllLayerVisibility(false)
    expect(setLayerActive).toHaveBeenCalledWith('wind-field', false)

    store.setAllLayerVisibility(true)
    expect(setLayerActive).toHaveBeenCalledWith('wind-field', true)
    expect(setViewport).toHaveBeenCalled()
  })

  it('removeAllLayers clears weather tile manager state', () => {
    const store = useLayersStore()
    store.activeLayers.push({
      instanceId: 'inst-1',
      catalogId: 'wind-field',
      name: 'Wind',
      visible: true,
      opacity: 1,
      isAdminBoundary: false,
    } as any)

    store.removeAllLayers(true)
    expect(clearLayer).toHaveBeenCalledWith('wind-field')
    expect(store.activeLayers).toHaveLength(0)
  })

  it('coalesces rapid toggles within one animation frame', async () => {
    const callbacks: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      callbacks.push(cb)
      return callbacks.length
    })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    const store = useLayersStore()
    store.activeLayers.push({
      instanceId: 'inst-1',
      catalogId: 'wind-field',
      visible: true,
      opacity: 1,
      isAdminBoundary: false,
    } as any)

    store.toggleLayerVisibility('inst-1')
    store.toggleLayerVisibility('inst-1')
    store.toggleLayerVisibility('inst-1')
    expect(store.activeLayers[0].visible).toBe(false)
    expect(setLayerActive).not.toHaveBeenCalled()
    expect(callbacks).toHaveLength(1)

    callbacks[0](0)

    expect(setLayerActive).toHaveBeenCalledTimes(1)
    expect(setLayerActive).toHaveBeenCalledWith('wind-field', false)

    vi.unstubAllGlobals()
  })
})
