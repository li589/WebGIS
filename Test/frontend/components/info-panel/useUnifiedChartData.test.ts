import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ActiveLayerDisplay } from '@/stores/layers/types'
import type { OverlayPointValue } from '@/services/runtime-api'
import type { OverlayTimeState } from '@/components/map/overlay-image-module'

const activeLayersDisplayRef = ref<ActiveLayerDisplay[]>([])

vi.mock('@/stores/layers/selectors', () => ({
  useLayerWorkspace: () => ({
    activeLayersDisplay: computed(() => activeLayersDisplayRef.value),
  }),
}))

import { useUnifiedChartData } from '@/components/info-panel/useUnifiedChartData'

function makeLayer(overrides: Partial<ActiveLayerDisplay>): ActiveLayerDisplay {
  return {
    instanceId: 'inst-1',
    catalogId: 'layer-a',
    name: '图层 A',
    category: '模型输出',
    summary: '',
    metricLabel: '',
    metricValue: '',
    trendLabel: '',
    statusLabel: '',
    updateLabel: '',
    sourceLabel: '',
    confidenceLabel: '',
    accentColor: '#3b82f6',
    accentGlow: '',
    chipTone: '',
    availabilityState: 'ready',
    availabilityLabel: '',
    availabilityDescription: '',
    observationTimeLabel: '',
    missingFieldsLabel: '',
    hotspots: [],
    isAdminBoundary: false,
    isImported: false,
    isImportedRaster: false,
    visible: true,
    opacity: 1,
    order: 0,
    dataState: 'catalog',
    ...overrides,
  }
}

function makeState(layerId: string, overrides: Partial<OverlayTimeState> = {}): OverlayTimeState {
  return {
    layerId,
    category: 'static',
    timeList: [],
    currentTime: null,
    palette: 'viridis',
    unit: '',
    vmin: null,
    vmax: null,
    opacity: 1,
    bounds: null,
    ...overrides,
  }
}

function makeValue(layerId: string, value: number | null): OverlayPointValue {
  return { layer_id: layerId, value, unit: 'K', time: '', lng: 0, lat: 0 }
}

function setup(options?: {
  states?: OverlayTimeState[]
  values?: OverlayPointValue[]
  point?: { lng: number; lat: number } | null
}) {
  return useUnifiedChartData(
    computed(() => null),
    computed(() => options?.values ?? []),
    computed(() => ({})),
    computed(() => options?.states ?? []),
    computed(() => (options?.point === undefined ? { lng: 113.2, lat: 23.4 } : options.point)),
  )
}

beforeEach(() => {
  activeLayersDisplayRef.value = []
})

describe('useUnifiedChartData · raster join 放宽（目录 overlay 纳入）', () => {
  it('includes catalog overlay layers registered via overlayTimeStates', () => {
    activeLayersDisplayRef.value = [makeLayer({ catalogId: 'drought-index', name: '干旱指数' })]
    const c = setup({ states: [makeState('drought-index', { unit: 'K' })] })

    expect(c.rasterLayerInfos.value.map((i) => i.layerId)).toEqual(['drought-index'])
  })

  it('includes catalog overlay layers once a point value has been fetched', () => {
    activeLayersDisplayRef.value = [makeLayer({ catalogId: 'smap-sm', name: 'SMAP' })]
    const c = setup({ values: [makeValue('smap-sm', 0.31)] })

    expect(c.rasterLayerInfos.value.map((i) => i.layerId)).toEqual(['smap-sm'])
    expect(c.hasUnifiedData.value).toBe(true)

    const rasterValue = c.unifiedPointValues.value.find((v) => v.layerId === 'smap-sm')
    expect(rasterValue?.value).toBeCloseTo(0.31)
    expect(rasterValue?.valueText).toContain('0.310')
  })

  it('keeps imported raster layers and dedupes against catalog ids', () => {
    activeLayersDisplayRef.value = [
      makeLayer({ catalogId: 'imp', importedRasterOverlayLayerId: 'imp' }),
      makeLayer({ catalogId: 'imp' }),
    ]
    const c = setup({ values: [makeValue('imp', 1)] })

    expect(c.rasterLayerInfos.value.map((i) => i.layerId)).toEqual(['imp'])
  })

  it('excludes unregistered catalog layers (non-raster) from the raster group', () => {
    activeLayersDisplayRef.value = [
      makeLayer({ catalogId: 'plain-vector' }),
      makeLayer({ catalogId: 'weather-layer', renderHint: undefined }),
    ]
    const c = setup({ states: [], values: [] })

    expect(c.rasterLayerInfos.value).toEqual([])
  })

  it('marks time-series capability from overlayTimeStates', () => {
    activeLayersDisplayRef.value = [makeLayer({ catalogId: 'ndvi-ts' })]
    const c = setup({
      states: [makeState('ndvi-ts', { category: 'time-series', timeList: ['2024-01-01'] })],
    })

    expect(c.rasterLayerInfos.value[0]?.hasTimeSeries).toBe(true)
  })

  it('returns no unified data without a selected point', () => {
    activeLayersDisplayRef.value = [makeLayer({ catalogId: 'smap-sm' })]
    const c = setup({ values: [makeValue('smap-sm', 0.31)], point: null })

    expect(c.unifiedPointValues.value).toEqual([])
    expect(c.hasUnifiedData.value).toBe(false)
  })
})
