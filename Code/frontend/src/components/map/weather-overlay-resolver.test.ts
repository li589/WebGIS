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
})
