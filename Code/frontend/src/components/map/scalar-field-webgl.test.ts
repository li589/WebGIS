import { describe, expect, it } from 'vitest'

import { buildScalarGridFromGeoJSON, resolveScalarValueRange } from './scalar-field-grid'
import {
  encodeScalarGridToRGBA,
  decodeScalarByte,
  buildPaletteLUT,
} from './scalar-field-webgl-texture'
import { clampBlend } from './scalar-field-webgl-shaders'
import {
  buildPressureIsobarLevels,
  buildWeakScalarContourLevels,
  filterContourLevelsForZoom,
  isWeakContourLayerId,
} from './scalar-contour-layer'

function pointFc(
  points: Array<{ lon: number; lat: number; value: number }>,
  metric = 'temperature_2m',
) {
  return {
    type: 'FeatureCollection' as const,
    features: points.map((p) => ({
      type: 'Feature' as const,
      properties: { [metric]: p.value },
      geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
    })),
  }
}

describe('scalar-field-grid', () => {
  it('builds a 2×2 grid from lattice points', () => {
    const geo = pointFc([
      { lon: 110, lat: 20, value: 10 },
      { lon: 110.5, lat: 20, value: 12 },
      { lon: 110, lat: 20.5, value: 14 },
      { lon: 110.5, lat: 20.5, value: 16 },
    ])
    const grid = buildScalarGridFromGeoJSON(geo, 'temperature_2m')
    expect(grid).not.toBeNull()
    expect(grid!.rows).toBe(2)
    expect(grid!.cols).toBe(2)
    expect(grid!.points[0][0].hasData).toBe(true)
  })

  it('resolves range from legend ticks', () => {
    const range = resolveScalarValueRange([-10, 0, 40], null)
    expect(range).toEqual({ min: -10, max: 40 })
  })
})

describe('scalar-field-webgl-texture', () => {
  it('encodes normalized values into R channel with mask', () => {
    const geo = pointFc([
      { lon: 0, lat: 1, value: 0 },
      { lon: 1, lat: 1, value: 10 },
      { lon: 0, lat: 0, value: 5 },
      { lon: 1, lat: 0, value: 10 },
    ])
    const grid = buildScalarGridFromGeoJSON(geo, 'temperature_2m')!
    const enc = encodeScalarGridToRGBA(grid, 0, 10)
    expect(enc.width).toBe(2)
    expect(enc.height).toBe(2)
    expect(enc.data[3]).toBe(255)
    expect(decodeScalarByte(enc.data[0])).toBeCloseTo(0, 1)
    expect(buildPaletteLUT(['#000000', '#ffffff']).length).toBe(256 * 4)
  })
})

describe('scalar-field-webgl-shaders', () => {
  it('clamps blend to [0,1]', () => {
    expect(clampBlend(-1)).toBe(0)
    expect(clampBlend(0.5)).toBe(0.5)
    expect(clampBlend(2)).toBe(1)
    expect(clampBlend(NaN)).toBe(0)
  })
})

describe('scalar-contour pressure levels', () => {
  it('builds 4hPa steps with bold decades', () => {
    const levels = buildPressureIsobarLevels([980, 1000, 1020, 1040])
    expect(levels.some((l) => l.value === 1000 && l.bold)).toBe(true)
    expect(levels.every((l) => l.value % 4 === 0)).toBe(true)
  })

  it('filters levels by zoom LOD', () => {
    const levels = buildPressureIsobarLevels([996, 1024])
    expect(filterContourLevelsForZoom(levels, 2)).toEqual([])
    expect(filterContourLevelsForZoom(levels, 4).every((l) => l.bold)).toBe(true)
    expect(filterContourLevelsForZoom(levels, 8).length).toBeGreaterThan(
      filterContourLevelsForZoom(levels, 4).length,
    )
  })

  it('builds weak temperature contours', () => {
    const levels = buildWeakScalarContourLevels([-10, 0, 10, 20, 30, 40], { targetCount: 6 })
    expect(levels.length).toBeGreaterThan(3)
    expect(isWeakContourLayerId('temperature')).toBe(true)
  })
})
