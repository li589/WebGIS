import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

function mockBrowserStorage() {
  const store = new Map<string, string>()
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      store.set(k, v)
    },
    removeItem: (k: string) => {
      store.delete(k)
    },
    clear: () => store.clear(),
  }
  vi.stubGlobal('localStorage', storage)
  vi.stubGlobal('window', {
    localStorage: storage,
    clearTimeout: () => undefined,
    setTimeout: () => 0,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => true,
  })
}

vi.mock('@/stores/weather-tile-manager', () => ({
  useWeatherTileManager: () => ({
    setLayerActive: vi.fn(),
    clearLayer: vi.fn(),
    setViewport: vi.fn(),
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

vi.mock('@/services/runtime-api', () => ({
  fetchLayerCatalog: vi.fn(async () => ({ items: [] })),
  submitWorkflow: vi.fn(),
  getWorkflowRun: vi.fn(),
  getWorkflowEvents: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  retryWorkflowRun: vi.fn(),
  getWeatherPoint: vi.fn(),
}))

vi.mock('@/services/layer-capabilities', () => ({
  isWeatherLayerDescriptor: () => true,
  supportsMapLayerCapability: () => false,
  supportsParticleFlowCapability: () => false,
  supportsViewportDrivenRefreshCapability: () => false,
}))

import { getPersistedLayerDisplayName } from '@/stores/layers/layer-display-names'
import { useLayersStore } from '@/stores/layers/index'

describe('setLayerDisplayName', () => {
  beforeEach(() => {
    mockBrowserStorage()
    setActivePinia(createPinia())
  })

  it('writes instance-scoped display name and clears catalogId key', () => {
    const store = useLayersStore()
    store.activeLayers.push({
      instanceId: 'inst-rename-1',
      catalogId: 'wind-field',
      name: '风场（10m）',
      visible: true,
      opacity: 1,
      isAdminBoundary: false,
      order: 1,
      dataState: 'ready',
    } as never)

    store.setLayerDisplayName('inst-rename-1', '  自定义风场  ')

    const layer = store.activeLayers[0]!
    expect(layer.name).toBe('自定义风场')
    expect(layer.catalogId).toBe('wind-field')
    expect(getPersistedLayerDisplayName('inst-rename-1')).toBe('自定义风场')
    expect(getPersistedLayerDisplayName('wind-field')).toBeNull()
  })

  it('clears persisted names when layer is removed', () => {
    const store = useLayersStore()
    store.activeLayers.push({
      instanceId: 'inst-rename-2',
      catalogId: 'temperature',
      name: '温度',
      visible: true,
      opacity: 1,
      isAdminBoundary: false,
      order: 1,
      dataState: 'ready',
    } as never)

    store.setLayerDisplayName('inst-rename-2', '我的温度')
    expect(getPersistedLayerDisplayName('inst-rename-2')).toBe('我的温度')

    store.removeLayer('inst-rename-2')
    expect(getPersistedLayerDisplayName('inst-rename-2')).toBeNull()
    expect(store.activeLayers).toHaveLength(0)
  })

  it('rejects blank rename', () => {
    const store = useLayersStore()
    store.activeLayers.push({
      instanceId: 'inst-rename-3',
      catalogId: 'precipitation',
      name: '降水',
      visible: true,
      opacity: 1,
      isAdminBoundary: false,
      order: 1,
      dataState: 'ready',
    } as never)

    store.setLayerDisplayName('inst-rename-3', '   ')
    expect(store.activeLayers[0]!.name).toBe('降水')
  })
})
