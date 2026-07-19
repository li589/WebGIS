import { describe, expect, it } from 'vitest'

import {
  buildDefaultWeatherRenderHint,
  buildWeatherFillColorExpression,
  buildWeatherLegendGradient,
  buildWeatherLegendStops,
  paletteToParticleColors,
  samplePaletteColor,
} from './weather-render'
import { __testComputeParticleCountForArea } from './wind-particle-canvas'
import { geojsonPointsToGridCells, geojsonToHeatmapPoints } from './weather-overlay-renderers'

describe('weather-render continuous palette', () => {
  it('buildWeatherFillColorExpression uses interpolate not step', () => {
    const hint = buildDefaultWeatherRenderHint('temperature')!
    const expr = buildWeatherFillColorExpression(hint) as unknown[]
    expect(expr[0]).toBe('interpolate')
    expect(expr[1]).toEqual(['linear'])
    expect(expr).toContain(-10)
    expect(expr).toContain(40)
  })

  it('legend stops sample palette by value ratio', () => {
    const hint = buildDefaultWeatherRenderHint('temperature')!
    const stops = buildWeatherLegendStops(hint)
    expect(stops.length).toBeGreaterThan(2)
    expect(stops[0].color).toBe(samplePaletteColor(hint.palette, 0))
    expect(stops[stops.length - 1].color).toBe(samplePaletteColor(hint.palette, 1))
  })

  it('buildWeatherLegendGradient uses legend stop colors (aligned with fill)', () => {
    const hint = buildDefaultWeatherRenderHint('precipitation')!
    const gradient = buildWeatherLegendGradient(hint)
    expect(gradient.startsWith('linear-gradient(90deg,')).toBe(true)
    const stops = buildWeatherLegendStops(hint)
    expect(gradient).toContain(stops[0].color)
    expect(gradient).toContain(stops[stops.length - 1].color)
  })

  it('prefers local canonical palette over catalog alias', () => {
    const hint = buildDefaultWeatherRenderHint('wind-field', {
      capabilities: {
        paint_mode: 'particle_flow',
        primary_metric: 'wind_speed_10m',
        legend_ticks: [0, 5, 10, 15, 20, 25, 30],
      },
      style: {
        palette: 'blue-cyan',
        unit_label: 'm/s',
        opacity: 0.85,
      },
    } as any)!
    expect(hint.palette).toBe('wind-blue')
    expect(hint.legend_ticks).toEqual([0, 5, 10, 15, 20, 25, 30])
    expect(hint.unit_label).toBe('m/s')
  })

  it('temperature default paint_mode is grid_fill for continuous field', () => {
    const hint = buildDefaultWeatherRenderHint('temperature')!
    expect(hint.paint_mode).toBe('grid_fill')
  })
})

describe('geojsonToHeatmapPoints', () => {
  it('converts polygon cells to point centroids', () => {
    const input = {
      type: 'FeatureCollection' as const,
      features: [
        {
          type: 'Feature',
          properties: { precipitation: 3 },
          geometry: {
            type: 'Polygon',
            coordinates: [[
              [110, 20],
              [112, 20],
              [112, 22],
              [110, 22],
              [110, 20],
            ]],
          },
        },
      ],
    }
    const out = geojsonToHeatmapPoints(input) as typeof input
    expect(out.features[0].geometry.type).toBe('Point')
    const [lng, lat] = out.features[0].geometry.coordinates as number[]
    expect(lng).toBeCloseTo(110.8, 5)
    expect(lat).toBeCloseTo(20.8, 5)
  })
})

describe('geojsonPointsToGridCells', () => {
  it('turns a regular point lattice into abutting polygons', () => {
    const input = {
      type: 'FeatureCollection' as const,
      features: [
        { type: 'Feature', properties: { wind_speed_10m: 4 }, geometry: { type: 'Point', coordinates: [110, 20] } },
        { type: 'Feature', properties: { wind_speed_10m: 5 }, geometry: { type: 'Point', coordinates: [110.5, 20] } },
        { type: 'Feature', properties: { wind_speed_10m: 6 }, geometry: { type: 'Point', coordinates: [110, 20.5] } },
        { type: 'Feature', properties: { wind_speed_10m: 7 }, geometry: { type: 'Point', coordinates: [110.5, 20.5] } },
      ],
    }
    const out = geojsonPointsToGridCells(input as any) as typeof input
    expect(out.features).toHaveLength(4)
    expect(out.features[0].geometry.type).toBe('Polygon')
    const ring = (out.features[0].geometry as any).coordinates[0] as number[][]
    // half-step 0.25 → cell width/height 0.5, abutting neighbors
    expect(ring[0][0]).toBeCloseTo(109.75, 5)
    expect(ring[1][0]).toBeCloseTo(110.25, 5)
  })
})

describe('particle density', () => {
  it('scales with area and respects caps', () => {
    expect(__testComputeParticleCountForArea(10)).toBe(Math.max(320, Math.min(2200, 60)))
    expect(__testComputeParticleCountForArea(1000)).toBe(2200)
    expect(__testComputeParticleCountForArea(0.01)).toBe(320)
  })
})

describe('paletteToParticleColors', () => {
  it('resolves aliases and keeps strokes bright enough for dark basemaps', () => {
    const colors = paletteToParticleColors('blue-cyan')
    expect(colors.length).toBe(12)
    for (const hex of colors) {
      const n = parseInt(hex.slice(1), 16)
      const r = (n >> 16) & 255
      const g = (n >> 8) & 255
      const b = n & 255
      expect(Math.max(r, g, b)).toBeGreaterThanOrEqual(160)
    }
  })
})
