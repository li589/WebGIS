import { describe, expect, it } from 'vitest'

import type { WindGeoJSON } from '@/components/map/types'
import { isLonInFrame } from '@/components/map/weather-grid-lattice'
import { buildWindGridFromGeoJSON } from '@/components/map/wind-grid'

function windFc(points: Array<{ lon: number; lat: number; speed?: number }>): WindGeoJSON {
  return {
    type: 'FeatureCollection',
    features: points.map((p) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
      properties: {
        height: '10m',
        wind_speed_10m: p.speed ?? 10,
        wind_direction_10m: 90,
        resolution: 0.5,
      },
    })),
  }
}

describe('buildWindGridFromGeoJSON with LonFrame', () => {
  it('does not collapse to Americas when frame is Asia–Pacific and features are Americas-only', () => {
    // 稀疏合并只含美洲点；若盲 unwrap 会建成美洲网格 → 亚太视口只亮西半球
    const geo = windFc([
      { lon: -120, lat: 20 },
      { lon: -110, lat: 20 },
      { lon: -120, lat: 30 },
      { lon: -110, lat: 30 },
    ])
    const frame = { west: 80, east: 240, centerLng: 150 }
    const grid = buildWindGridFromGeoJSON(geo, frame)
    // 帧外点全部丢弃 → 无法建格（或若有残留也不应落在美洲）
    expect(grid).toBeNull()
  })

  it('keeps Asia points when frame is Asia–Pacific', () => {
    const geo = windFc([
      { lon: 110, lat: 20 },
      { lon: 120, lat: 20 },
      { lon: 110, lat: 30 },
      { lon: 120, lat: 30 },
      // 错半球噪声应被丢弃
      { lon: -100, lat: 25 },
    ])
    const frame = { west: 80, east: 240, centerLng: 150 }
    const grid = buildWindGridFromGeoJSON(geo, frame)
    expect(grid).not.toBeNull()
    expect(grid!.west).toBeGreaterThan(0)
    expect(grid!.east).toBeLessThan(200)
    expect(grid!.west).toBeGreaterThanOrEqual(100)
  })

  it('isLonInFrame rejects Americas lon for Asia-Pacific frame', () => {
    const frame = { west: 80, east: 240, centerLng: 160 }
    expect(isLonInFrame(-100, frame)).toBe(false)
    expect(isLonInFrame(-60, frame)).toBe(false)
    expect(isLonInFrame(120, frame)).toBe(true)
    expect(isLonInFrame(-170, frame)).toBe(true) // 190° in frame
  })

  it('keeps Asia and Americas points when LonFrame crosses IDL', () => {
    const geo = windFc([
      { lon: 170, lat: 20 },
      { lon: 175, lat: 20 },
      { lon: -170, lat: 20 },
      { lon: -175, lat: 20 },
      { lon: 170, lat: 30 },
      { lon: 175, lat: 30 },
      { lon: -170, lat: 30 },
      { lon: -175, lat: 30 },
    ])
    const frame = { west: 150, east: 210, centerLng: 180 }
    const grid = buildWindGridFromGeoJSON(geo, frame)
    expect(grid).not.toBeNull()
    // 解包后应覆盖日界线两侧（east>180）
    expect(grid!.west).toBeLessThan(180)
    expect(grid!.east).toBeGreaterThan(180)
  })

  it('isLonInFrame accepts IDL ±360 aliases near frame edge', () => {
    const frame = { west: 80, east: 240, centerLng: 160 }
    expect(isLonInFrame(179, frame)).toBe(true)
    expect(isLonInFrame(-181, frame)).toBe(true)
    expect(isLonInFrame(539, frame)).toBe(true)
  })

  it('checksum changes when grid lon bounds change with same speed sum', () => {
    const geo = windFc([
      { lon: 110, lat: 20 },
      { lon: 120, lat: 20 },
      { lon: 110, lat: 30 },
      { lon: 120, lat: 30 },
    ])
    const a = buildWindGridFromGeoJSON(geo, { west: 100, east: 130, centerLng: 115 })!
    const b = buildWindGridFromGeoJSON(geo, { west: 105, east: 135, centerLng: 120 })!
    expect(a.checksum).not.toBe(b.checksum)
  })
})
