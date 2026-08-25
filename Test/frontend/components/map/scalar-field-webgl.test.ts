import { describe, expect, it } from 'vitest'

import { buildScalarGridFromGeoJSON, resolveScalarValueRange } from '@/components/map/scalar-field-grid'
import {
  encodeScalarGridToRGBA,
  decodeScalarByte,
  buildPaletteLUT,
} from '@/components/map/scalar-field-webgl-texture'
import {
  clampBlend,
  SCALAR_FIELD_FRAGMENT_SHADER,
} from '@/components/map/scalar-field-webgl-shaders'
import {
  buildPressureIsobarLevels,
  buildWeakScalarContourLevels,
  filterContourLevelsForZoom,
  isWeakContourLayerId,
} from '@/components/map/scalar-contour-layer'

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

  it('keeps both IDL sides in one continuous longitude frame', () => {
    const geo = pointFc([
      { lon: 170, lat: 20, value: 1 },
      { lon: 175, lat: 20, value: 2 },
      { lon: -175, lat: 20, value: 3 },
      { lon: -170, lat: 20, value: 4 },
      { lon: 170, lat: 25, value: 5 },
      { lon: 175, lat: 25, value: 6 },
      { lon: -175, lat: 25, value: 7 },
      { lon: -170, lat: 25, value: 8 },
    ])
    const grid = buildScalarGridFromGeoJSON(geo, 'temperature_2m', {
      west: 150,
      east: 210,
      centerLng: 180,
    })
    expect(grid).not.toBeNull()
    expect(grid!.west).toBe(170)
    expect(grid!.east).toBe(190)
    expect(grid!.cols).toBe(5)
  })

  it('uses a layout-aware signature instead of a value sum', () => {
    const westGrid = buildScalarGridFromGeoJSON(
      pointFc([
        { lon: -170, lat: 0, value: 1 },
        { lon: -160, lat: 0, value: 2 },
        { lon: -170, lat: 10, value: 3 },
        { lon: -160, lat: 10, value: 4 },
      ]),
      'temperature_2m',
    )!
    const eastGrid = buildScalarGridFromGeoJSON(
      pointFc([
        { lon: 170, lat: 0, value: 4 },
        { lon: 180, lat: 0, value: 3 },
        { lon: 170, lat: 10, value: 2 },
        { lon: 180, lat: 10, value: 1 },
      ]),
      'temperature_2m',
    )!
    expect(westGrid.signature).not.toBe(eastGrid.signature)
  })

  it('resolves range from legend ticks', () => {
    const range = resolveScalarValueRange([-10, 0, 40], null)
    expect(range).toEqual({ min: -10, max: 40 })
  })

  // 2026-08-25 平滑渲染修复：后端标量层 tile（temperature/humidity 等）的
  // feature 是网格单元 Polygon（PixelIsArea，带 row/col/resolution 属性），
  // 而风场 tile 是 Point——buildScalarGridFromGeoJSON 此前只认 Point，导致
  // 标量层 WebGL 连续面永远建不出网格（1350 个 feature 全部被跳过）。
  it('builds grid from Polygon cell features (backend scalar tiles)', () => {
    const cell = (west: number, south: number, res: number) => {
      const east = west + res
      const north = south + res
      return [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ]
    }
    const geo = {
      type: 'FeatureCollection' as const,
      features: [
        { lon: 110, lat: 20, value: 10 },
        { lon: 111, lat: 20, value: 12 },
        { lon: 110, lat: 21, value: 14 },
        { lon: 111, lat: 21, value: 16 },
      ].map((p) => ({
        type: 'Feature' as const,
        properties: {
          temperature_2m: p.value,
          height: '2m',
          unit: 'C',
          row: 0,
          col: 0,
          resolution: 1,
          grid_resolution: 1,
        },
        geometry: { type: 'Polygon' as const, coordinates: [cell(p.lon, p.lat, 1)] },
      })),
    }
    const grid = buildScalarGridFromGeoJSON(geo, 'temperature_2m')
    expect(grid).not.toBeNull()
    expect(grid!.rows).toBe(2)
    expect(grid!.cols).toBe(2)
    // 质心即格点：值按单元中心归位
    expect(grid!.points[1][0].value).toBe(10) // 西南
    expect(grid!.points[1][1].value).toBe(12) // 东南
    expect(grid!.points[0][0].value).toBe(14) // 西北（row0=北）
    expect(grid!.points[0][1].value).toBe(16) // 东北
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

  it('does not feather data-quad edges, so world copies meet at IDL without a transparent seam', () => {
    expect(SCALAR_FIELD_FRAGMENT_SHADER).not.toContain('* feather')
    expect(SCALAR_FIELD_FRAGMENT_SHADER).toContain('float softMask = smoothstep(0.008, 0.06, mask);')
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
