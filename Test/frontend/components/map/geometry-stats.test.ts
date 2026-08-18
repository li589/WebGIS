import { describe, expect, it } from 'vitest'

import {
  formatArea,
  formatLength,
  geodesicAreaM2,
  geodesicPerimeterM,
  summarizeFeatureCollection,
} from '@/components/map/geometry-stats'

/** WGS84 等面积半径，与实现保持一致的期望值基准 */
const R = 6371007.181

/** 球面上 [λ1,λ2]×[φ1,φ2] 矩形的理论面积（边为大圆弧近似下的球面梯形公式） */
function rectAreaM2(lngSpanDeg: number, lat1: number, lat2: number): number {
  return R * R * toRad(lngSpanDeg) * (Math.sin(toRad(lat2)) - Math.sin(toRad(lat1)))
}

function toRad(deg: number): number {
  return (deg * Math.PI) / 180
}

function rectRing(west: number, south: number, east: number, north: number): GeoJSON.Position[] {
  return [
    [west, south],
    [east, south],
    [east, north],
    [west, north],
    [west, south],
  ]
}

describe('geodesicAreaM2 / geodesicPerimeterM', () => {
  it('赤道 1°×1° 方形面积 ≈ 球面梯形理论值（误差 <0.1%）', () => {
    const geom: GeoJSON.Polygon = {
      type: 'Polygon',
      coordinates: [rectRing(-0.5, -0.5, 0.5, 0.5)],
    }
    const got = geodesicAreaM2(geom)
    const want = rectAreaM2(1, -0.5, 0.5)
    expect(Math.abs(got - want) / want).toBeLessThan(0.001)
  })

  it('中纬度 2°×2° 方形面积与理论值一致（误差 <0.1%）', () => {
    const geom: GeoJSON.Polygon = {
      type: 'Polygon',
      coordinates: [rectRing(116, 39, 118, 41)],
    }
    const got = geodesicAreaM2(geom)
    const want = rectAreaM2(2, 39, 41)
    expect(Math.abs(got - want) / want).toBeLessThan(0.001)
  })

  it('带洞多边形：面积 = 外环 − 洞；周长含洞', () => {
    const geom: GeoJSON.Polygon = {
      type: 'Polygon',
      coordinates: [
        rectRing(0, 0, 2, 2),
        rectRing(0.5, 0.5, 1.5, 1.5), // 洞 1°×1°
      ],
    }
    const want = rectAreaM2(2, 0, 2) - rectAreaM2(1, 0.5, 1.5)
    const got = geodesicAreaM2(geom)
    expect(Math.abs(got - want) / want).toBeLessThan(0.001)
    // 外环 4 条 2° 边 + 洞 4 条 1° 边 ≈ (4·2° + 4·1°) × 111.2 km ≈ 1334 km
    const p = geodesicPerimeterM(geom)
    expect(p).toBeGreaterThan(1_300_000)
    expect(p).toBeLessThan(1_400_000)
  })

  it('赤道 1°×1° 方形周长 ≈ 4 × 111.2 km（误差 <0.2%）', () => {
    const geom: GeoJSON.Polygon = {
      type: 'Polygon',
      coordinates: [rectRing(-0.5, -0.5, 0.5, 0.5)],
    }
    const want = 4 * R * toRad(1)
    const got = geodesicPerimeterM(geom)
    expect(Math.abs(got - want) / want).toBeLessThan(0.002)
  })

  it('跨反经线多边形面积正确（不因 Δλ 回绕放大）', () => {
    const geom: GeoJSON.Polygon = {
      type: 'Polygon',
      coordinates: [rectRing(179.5, -0.5, -179.5, 0.5)],
    }
    const want = rectAreaM2(1, -0.5, 0.5)
    const got = geodesicAreaM2(geom)
    expect(Math.abs(got - want) / want).toBeLessThan(0.001)
  })

  it('MultiPolygon 累加；点/线面积 0；线周长即长度', () => {
    const mp: GeoJSON.MultiPolygon = {
      type: 'MultiPolygon',
      coordinates: [
        [rectRing(0, 0, 1, 1)],
        [rectRing(2, 0, 3, 1)],
      ],
    }
    const want = 2 * rectAreaM2(1, 0, 1)
    expect(Math.abs(geodesicAreaM2(mp) - want) / want).toBeLessThan(0.001)

    const line: GeoJSON.LineString = {
      type: 'LineString',
      coordinates: [
        [0, 0],
        [1, 0],
      ],
    }
    expect(geodesicAreaM2(line)).toBe(0)
    expect(geodesicPerimeterM(line)).toBeGreaterThan(111000)
    expect(geodesicPerimeterM(line)).toBeLessThan(111400)

    const point: GeoJSON.Point = { type: 'Point', coordinates: [0, 0] }
    expect(geodesicAreaM2(point)).toBe(0)
    expect(geodesicPerimeterM(point)).toBe(0)
  })
})

describe('summarizeFeatureCollection', () => {
  it('汇总多个面要素并计数', () => {
    const fc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: null,
          geometry: { type: 'Polygon', coordinates: [rectRing(0, 0, 1, 1)] },
        },
        {
          type: 'Feature',
          properties: null,
          geometry: { type: 'LineString', coordinates: [[0, 0], [1, 0]] },
        },
      ],
    }
    const s = summarizeFeatureCollection(fc)
    expect(s.polygonCount).toBe(1)
    expect(s.lineCount).toBe(1)
    expect(s.areaM2).toBeGreaterThan(0)
    expect(s.perimeterM).toBeGreaterThan(400000)
  })
})

describe('formatArea / formatLength', () => {
  it('自适应单位与精度', () => {
    expect(formatArea(850)).toBe('850 m²')
    expect(formatArea(12_350_000)).toBe('12.35 km²')
    expect(formatArea(1.234e9)).toBe('1234.0 km²')
    expect(formatLength(850)).toBe('850 m')
    expect(formatLength(1234)).toBe('1.23 km')
    expect(formatLength(12_345)).toBe('12.3 km')
    expect(formatArea(-1)).toBe('--')
    expect(formatLength(NaN)).toBe('--')
  })
})
