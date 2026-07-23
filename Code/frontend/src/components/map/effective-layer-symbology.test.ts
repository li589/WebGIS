import { describe, expect, it } from 'vitest'
import type { WeatherLayerRenderHint } from '../../services/runtime-api'
import {
  buildSampledLegendTicks,
  resolveEffectiveLayerSymbology,
} from './effective-layer-symbology'

const baseHint = (overrides: Partial<WeatherLayerRenderHint> = {}): WeatherLayerRenderHint => ({
  layer_id: 'temperature',
  paint_mode: 'grid_fill',
  palette: 'temp',
  primary_metric: 'temperature_2m',
  unit_label: '°C',
  opacity: 0.7,
  legend_ticks: [-10, 0, 10, 20, 30],
  ...overrides,
})

describe('effective-layer-symbology', () => {
  it('keeps configured legend_ticks and applies paletteOverride', () => {
    const { hint, ticksFromViewport } = resolveEffectiveLayerSymbology({
      renderHint: baseHint(),
      paletteOverride: 'viridis',
    })
    expect(ticksFromViewport).toBe(false)
    expect(hint?.palette).toBe('viridis')
    expect(hint?.legend_ticks).toEqual([-10, 0, 10, 20, 30])
  })

  it('samples viewport range when legend_ticks missing', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [113, 23] },
          properties: { temperature_2m: 10, resolution_deg: 0.25 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [113.25, 23] },
          properties: { temperature_2m: 20, resolution_deg: 0.25 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [113, 23.25] },
          properties: { temperature_2m: 12, resolution_deg: 0.25 },
        },
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [113.25, 23.25] },
          properties: { temperature_2m: 18, resolution_deg: 0.25 },
        },
      ],
    }
    const { hint, ticksFromViewport } = resolveEffectiveLayerSymbology({
      renderHint: baseHint({ legend_ticks: [] }),
      viewportGeojson: geojson,
    })
    expect(ticksFromViewport).toBe(true)
    const nums = (hint?.legend_ticks ?? []).filter((t): t is number => typeof t === 'number')
    expect(nums.length).toBeGreaterThanOrEqual(2)
    expect(Math.min(...nums)).toBeLessThanOrEqual(10)
    expect(Math.max(...nums)).toBeGreaterThanOrEqual(18)
  })

  it('buildSampledLegendTicks includes endpoints', () => {
    expect(buildSampledLegendTicks(0, 40, 5)).toEqual([0, 10, 20, 30, 40])
  })
})
