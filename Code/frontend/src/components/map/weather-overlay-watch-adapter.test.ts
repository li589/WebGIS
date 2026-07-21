import { describe, expect, it } from 'vitest'

import {
  buildWeatherOverlayWatchInputs,
  diffWeatherOverlayWatchInputs,
} from './weather-overlay-watch-adapter'

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

describe('weather-overlay-watch-adapter', () => {
  it('builds stable watch inputs for weather overlay dependencies', () => {
    const inputs = buildWeatherOverlayWatchInputs(
      [createLayer()],
      'weather.wind',
      7,
      12,
    )

    expect(inputs.particleFlowCatalogId).toBe('weather.wind')
    expect(inputs.dataVersion).toBe(7)
    expect(inputs.currentHour).toBe(12)
    expect(inputs.layersHash).toContain('"catalogId":"weather.wind"')
  })

  it('detects which weather watch inputs changed', () => {
    const previous = buildWeatherOverlayWatchInputs([createLayer()], 'weather.wind', 7, 12)
    const next = buildWeatherOverlayWatchInputs(
      [createLayer({ opacity: 0.6 })],
      'weather.temp',
      8,
      13,
    )

    expect(diffWeatherOverlayWatchInputs(next, previous)).toEqual({
      flowIdChanged: true,
      windDisplayModeChanged: false,
      layersHashChanged: true,
      dataVersionChanged: true,
      hourChanged: true,
    })
  })

  it('detects wind display mode changes', () => {
    const previous = buildWeatherOverlayWatchInputs([createLayer()], 'weather.wind', 7, 12, 'particle')
    const next = buildWeatherOverlayWatchInputs([createLayer()], 'weather.wind', 7, 12, 'streamline')
    expect(diffWeatherOverlayWatchInputs(next, previous).windDisplayModeChanged).toBe(true)
    expect(next.windDisplayMode).toBe('streamline')
  })
})
