import { describe, expect, it } from 'vitest'

import {
  intersectCellWithTileHalfOpen,
  latticeCellBounds,
  pointInTileHalfOpen,
  snapToLatticeCenter,
  buildRegularLatticeAxis,
  detectLatticeResolution,
} from './weather-grid-lattice'
import { geojsonPointsToGridCells } from './weather-overlay-renderers'

describe('weather-grid-lattice', () => {
  it('snaps to (i+0.5)*res centers', () => {
    expect(snapToLatticeCenter(110.25, 0.5)).toBeCloseTo(110.25, 10)
    expect(snapToLatticeCenter(110.75, 0.5)).toBeCloseTo(110.75, 10)
    expect(snapToLatticeCenter(110.0, 0.5)).toBeCloseTo(110.25, 10)
  })

  it('adjacent lattice cells abut (seam eps only, no visible overlap)', () => {
    const a = latticeCellBounds(110.25, 20.25, 0.5, { seamEps: 0 })
    const b = latticeCellBounds(110.75, 20.25, 0.5, { seamEps: 0 })
    expect(a.east).toBeCloseTo(b.west, 10)
    expect(a.east - a.west).toBeCloseTo(0.5, 10)
  })

  it('half-open point predicate matches backend', () => {
    const tile = { west: 110, south: 20, east: 115, north: 25 }
    expect(pointInTileHalfOpen(110, 25, tile)).toBe(true)
    expect(pointInTileHalfOpen(115, 22, tile)).toBe(false)
    expect(pointInTileHalfOpen(112, 20, tile)).toBe(false)
  })

  it('without tile clip, neighbor lattice cells meet across tile east', () => {
    // 瓦片边 115 落在格网线上：左最后格心 114.75、右最先 115.25
    const left = latticeCellBounds(114.75, 22.25, 0.5, { seamEps: 0 })
    const right = latticeCellBounds(115.25, 22.25, 0.5, { seamEps: 0 })
    expect(left.east).toBeCloseTo(115, 10)
    expect(right.west).toBeCloseTo(115, 10)
    expect(left.east).toBeCloseTo(right.west, 10)
  })

  it('documents why clip-to-tile creates gaps when tile edge ≠ lattice edge', () => {
    // Mercator 瓦片边 115.3 不在 0.5° 格网上
    const tileEast = 115.3
    const leftCell = latticeCellBounds(114.75, 22.25, 0.5, { seamEps: 0 })
    const rightCell = latticeCellBounds(115.25, 22.25, 0.5, { seamEps: 0 })
    const clippedLeft = intersectCellWithTileHalfOpen(leftCell, {
      west: 110,
      south: 20,
      east: tileEast,
      north: 25,
    })!
    const clippedRight = intersectCellWithTileHalfOpen(rightCell, {
      west: tileEast,
      south: 20,
      east: 120,
      north: 25,
    })!
    // 裁剪后中间出现空隙 —— 故渲染路径禁止裁格元进瓦片框
    expect(clippedLeft.east).toBeLessThan(clippedRight.west)
  })

  it('fills latitude axis across equator when mid-band points are missing', () => {
    // 南北半球各有点、赤道带缺瓦：步长仍为 2.5，中间行被补齐
    const axis = buildRegularLatticeAxis([-38.75, -1.25, 1.25, 38.75], {
      resolution: 2.5,
      descending: true,
    })
    expect(axis[0]).toBeCloseTo(38.75, 5)
    expect(axis[axis.length - 1]).toBeCloseTo(-38.75, 5)
    expect(axis.length).toBeGreaterThan(4)
    // 赤道附近应有连续格心，而不是从 1.25 直接跳到 -1.25 作为相邻行
    const nearEq = axis.filter((lat) => Math.abs(lat) <= 5)
    expect(nearEq.length).toBeGreaterThanOrEqual(3)
    for (let i = 1; i < axis.length; i++) {
      expect(axis[i - 1]! - axis[i]!).toBeCloseTo(2.5, 5)
    }
  })

  it('detectLatticeResolution ignores equatorial hole when estimating step', () => {
    const res = detectLatticeResolution([-38.75, -1.25, 1.25, 38.75])
    expect(res).toBeCloseTo(2.5, 5)
  })
})

describe('geojsonPointsToGridCells spanning tiles', () => {
  it('keeps full lattice cells so cross-tile edge has no gap', () => {
    const out = geojsonPointsToGridCells({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { resolution: 0.5 },
          geometry: { type: 'Point', coordinates: [114.75, 22.25] },
        },
        {
          type: 'Feature',
          properties: { resolution: 0.5 },
          geometry: { type: 'Point', coordinates: [115.25, 22.25] },
        },
      ],
    } as any) as { features: Array<{ geometry: { coordinates: number[][][] } }> }
    expect(out.features).toHaveLength(2)
    const leftEast = Math.max(...out.features[0].geometry.coordinates[0].map((c) => c[0]))
    const rightWest = Math.min(...out.features[1].geometry.coordinates[0].map((c) => c[0]))
    // 允许 seam eps，但不允许可见空隙
    expect(leftEast).toBeGreaterThanOrEqual(rightWest - 1e-6)
  })
})
