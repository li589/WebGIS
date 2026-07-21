import { describe, expect, it } from 'vitest'

import {
  buildDefaultWeatherRenderHint,
  buildWeatherFillColorExpression,
  buildWeatherFillOpacityExpression,
  buildWeatherLegendGradient,
  buildWeatherLegendStops,
  paletteToParticleColors,
  samplePaletteColor,
} from './weather-render'
import { __testComputeParticleCountForArea } from './wind-particle-canvas'
import { geojsonPointsToGridCells } from './weather-overlay-renderers'

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
    // 点 110 吸附到格心 110.25（step=0.5）→ 格元 [110, 110.5]
    expect(ring[0][0]).toBeCloseTo(110, 5)
    expect(ring[1][0]).toBeCloseTo(110.5, 5)
  })

  it('uses fixed zoom resolution when provided', () => {
    const input = {
      type: 'FeatureCollection' as const,
      features: [
        { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [120.25, 30.25] } },
      ],
    }
    const out = geojsonPointsToGridCells(input as any, { zoom: 6 }) as typeof input
    const ring = (out.features[0].geometry as any).coordinates[0] as number[][]
    // z6 → 0.5° step，格心 120.25 → 宽 0.5
    expect(ring[1][0] - ring[0][0]).toBeCloseTo(0.5, 5)
  })
})

describe('particle density', () => {
  it('scales with area and respects caps', () => {
    expect(__testComputeParticleCountForArea(10)).toBe(400) // 100 → min 400
    expect(__testComputeParticleCountForArea(1000)).toBe(3600) // 10000 → max 3600
    expect(__testComputeParticleCountForArea(0.01)).toBe(400)
  })
})

describe('buildWeatherFillOpacityExpression', () => {
  it('uses value-dependent alpha for precipitation', () => {
    const hint = buildDefaultWeatherRenderHint('precipitation')!
    const expr = buildWeatherFillOpacityExpression(hint, 1) as unknown[]
    expect(expr[0]).toBe('interpolate')
    expect(expr).toContain(0.04)
  })

  it('keeps constant opacity for temperature', () => {
    const hint = buildDefaultWeatherRenderHint('temperature')!
    const opacity = buildWeatherFillOpacityExpression(hint, 1)
    expect(typeof opacity).toBe('number')
    expect(opacity as number).toBeGreaterThan(0.5)
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
