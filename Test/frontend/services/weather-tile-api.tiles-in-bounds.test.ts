import { describe, expect, it } from 'vitest'

import {
  lngLatToTile,
  sortTilesCenterFirst,
  summarizeHttpErrorDetail,
  tilesInBounds,
} from '@/services/weather-tile-api'

describe('tilesInBounds', () => {
  it('keeps Asia when viewport spans Africa→Pacific (span > 180°)', () => {
    // 用户从广东缩放到亚洲/太平洋：west≈-20 east≈200（normalizeLngBounds 后）
    // 旧逻辑误走短路径只取太平洋–美洲–大西洋，亚洲中部整片不请求
    const tiles = tilesInBounds({ west: -20, east: 200, south: -40, north: 55 }, 3, 0)
    const xs = [...new Set(tiles.map((t) => t.x))].sort((a, b) => a - b)
    // z=3：亚洲约 x=4..7（lon≈22°..157°），必须覆盖
    expect(xs).toEqual(expect.arrayContaining([4, 5, 6, 7]))
    // 不应只剩美洲一侧 [0,1,2,3]
    expect(xs.length).toBeGreaterThan(4)
  })

  it('still covers short antimeridian path west=170 east=185', () => {
    const tiles = tilesInBounds({ west: 170, east: 185, south: -10, north: 20 }, 4, 0)
    expect(tiles.length).toBeGreaterThan(0)
    const n = 16
    // 170°→185° 跨日界线：x 覆盖靠近 n-1 与 0
    const xs = new Set(tiles.map((t) => t.x))
    expect(xs.has(n - 1) || xs.has(0)).toBe(true)
  })

  it('handles legacy east < west form without dropping the short arc', () => {
    const tiles = tilesInBounds({ west: 170, east: -175, south: -10, north: 20 }, 3, 0)
    expect(tiles.length).toBeGreaterThan(0)
  })

  it('returns full world when span >= 360', () => {
    const tiles = tilesInBounds({ west: -180, east: 180, south: -85, north: 85 }, 2, 0)
    const xs = new Set(tiles.map((t) => t.x))
    expect(xs.size).toBe(4) // z=2 → 4 columns
  })
})

describe('sortTilesCenterFirst', () => {
  it('orders viewport tiles by distance to map center', () => {
    const tiles = tilesInBounds({ west: 110, east: 120, south: 20, north: 30 }, 5, 0)
    const sorted = sortTilesCenterFirst(tiles, 115, 25)
    const center = lngLatToTile(115, 25, 5)
    const first = sorted[0]!
    const last = sorted[sorted.length - 1]!
    const d2 = (t: { x: number; y: number }) => (t.x - center.x) ** 2 + (t.y - center.y) ** 2
    expect(d2(first)).toBeLessThanOrEqual(d2(last))
    expect(sorted[0]).toEqual(expect.objectContaining({ z: 5 }))
    // 中心瓦片应在前列
    expect(sorted.slice(0, 4)).toEqual(
      expect.arrayContaining([expect.objectContaining({ x: center.x, y: center.y })]),
    )
  })

  it('uses toroidal x distance near the antimeridian', () => {
    const n = 16 // z=4
    const tiles = [
      { z: 4, x: 0, y: 8 },
      { z: 4, x: 1, y: 8 },
      { z: 4, x: n - 1, y: 8 },
      { z: 4, x: 8, y: 8 },
    ]
    // 中心靠近 x=0（lon≈-180）
    const sorted = sortTilesCenterFirst(tiles, -179, 0)
    expect(sorted[0]?.x).toBe(0)
    expect(sorted.map((t) => t.x).slice(0, 3)).toEqual(expect.arrayContaining([0, 1, n - 1]))
    expect(sorted[sorted.length - 1]?.x).toBe(8)
  })

  it('wraps unwrapped longitudes before converting to tile x', () => {
    const a = lngLatToTile(185, 0, 4)
    const b = lngLatToTile(-175, 0, 4)
    expect(a.x).toBe(b.x)
    expect(a.x).toBeLessThan(16)
  })
})

describe('summarizeHttpErrorDetail', () => {
  it('does not leak Cloudflare HTML into UI error text', () => {
    const html = `<!DOCTYPE html><html><head><title>cgdas.dpdns.org | 502: Bad gateway</title></head><body>Bad gateway</body></html>`
    const summary = summarizeHttpErrorDetail(502, html)
    expect(summary).toContain('502')
    expect(summary).toContain('Bad gateway')
    expect(summary).not.toContain('<!DOCTYPE')
    expect(summary).not.toContain('<body')
    expect(summary.length).toBeLessThan(120)
  })

  it('truncates long plain-text bodies', () => {
    const summary = summarizeHttpErrorDetail(500, 'x'.repeat(500))
    expect(summary.endsWith('…')).toBe(true)
    expect(summary.length).toBeLessThanOrEqual(161)
  })
})
