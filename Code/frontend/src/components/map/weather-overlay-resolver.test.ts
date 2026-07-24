import { describe, expect, it, vi } from 'vitest'

import { createWeatherOverlayResolver } from './weather-overlay-resolver'

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

describe('weather-overlay-resolver', () => {
  it('resolves weather engine layer states from injected dependencies', () => {
    const geojson = { type: 'FeatureCollection', features: [] }
    const resolver = createWeatherOverlayResolver({
      getActiveLayers: () => [
        createLayer({
          catalogId: 'weather.wind',
          renderHint: {
            layer_id: 'weather.wind',
            paint_mode: 'particle_flow',
            palette: 'viridis',
            primary_metric: 'wind_speed_10m',
            unit_label: 'm/s',
            opacity: 1,
            legend_ticks: [],
            notes: [],
          },
        }),
      ],
      isWeatherEngineLayer: (catalogId) => catalogId === 'weather.wind',
      getMergedGeojsonForViewport: vi.fn(() => geojson as any),
      buildDefaultWeatherRenderHint: vi.fn(() => null),
      resolveApiUrl: vi.fn((url: string) => url),
      debugLog: vi.fn(),
    })

    expect(resolver.resolveStates()).toEqual([
      {
        catalogId: 'weather.wind',
        geojsonUrl: null,
        geojsonData: geojson,
        cogPreviewUrl: null,
        cogBbox: null,
        viewportBounds: null,
        renderHint: {
          layer_id: 'weather.wind',
          paint_mode: 'particle_flow',
          palette: 'viridis',
          primary_metric: 'wind_speed_10m',
          unit_label: 'm/s',
          opacity: 1,
          legend_ticks: [],
          notes: [],
        },
        opacity: 1,
      },
    ])
  })

  it('grid_fill：无数据时先推灰底占位态，有数据后快照在瞬态空窗被沿用', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: null, properties: {} }],
    }
    const viewport = { west: -10, south: -10, east: 10, north: 10 }
    const renderHint = {
      layer_id: 'temperature',
      paint_mode: 'grid_fill',
      palette: 'turbo',
      primary_metric: 'temperature_2m',
      unit_label: '°C',
      opacity: 1,
      legend_ticks: [],
      notes: [],
    }
    let merged: unknown = null
    const resolver = createWeatherOverlayResolver({
      getActiveLayers: () => [createLayer({ catalogId: 'temperature', renderHint })],
      isWeatherEngineLayer: () => true,
      getMergedGeojsonForViewport: vi.fn((): any => merged),
      getViewportBounds: vi.fn(() => viewport),
      buildDefaultWeatherRenderHint: vi.fn(() => null),
      resolveApiUrl: vi.fn((url: string) => url),
      debugLog: vi.fn(),
    })

    // 首次加载无数据：推出灰底占位态（geojsonData=null + viewportBounds）
    const placeholderStates = resolver.resolveStates()
    expect(placeholderStates).toHaveLength(1)
    expect(placeholderStates[0]).toMatchObject({
      catalogId: 'temperature',
      geojsonData: null,
      viewportBounds: viewport,
    })

    // 数据到达：正常推数据态并记录快照
    merged = geojson
    const dataStates = resolver.resolveStates()
    expect(dataStates).toHaveLength(1)
    expect(dataStates[0]?.geojsonData).toBe(geojson)

    // 瞬态空窗（平移/退避）：沿用上一快照（地理锚定），避免 prune 销毁重建闪烁
    merged = null
    const staleStates = resolver.resolveStates()
    expect(staleStates).toHaveLength(1)
    expect(staleStates[0]?.geojsonData).toBe(geojson)
    expect(staleStates[0]?.viewportBounds).toEqual(viewport)
  })
})
