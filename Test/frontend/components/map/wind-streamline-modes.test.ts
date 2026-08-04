import { describe, expect, it } from 'vitest'

import {
  buildStreamlineSeeds,
  computeStreamlineCountForArea,
  computeStreamlineCountForGrid,
  integrateStreamline,
  projectStreamlinePathStrokes,
  resolveStreamlineSeedBounds,
  streamlineLonWrapOffsets,
  wrappedPulse,
} from '@/components/map/wind-streamline-layer'
import type { WindGrid } from '@/components/map/wind-grid'
import { isWindDisplayMode, windDisplayModeChip, windDisplayModeLabel } from '@/components/map/wind-display-mode'
import { buildWeakScalarContourLevels, isWeakContourLayerId } from '@/components/map/scalar-contour-layer'
import { getPaletteColors } from '@/components/map/weather-render'

function makeUniformGrid(speed = 10, direction = 90): WindGrid {
  const rows = 4
  const cols = 4
  const points: WindGrid['points'] = []
  for (let r = 0; r < rows; r++) {
    points[r] = []
    for (let c = 0; c < cols; c++) {
      const lat = 30 - (r / (rows - 1)) * 10
      const lon = 110 + (c / (cols - 1)) * 10
      points[r][c] = { lat, lon, speed, direction }
    }
  }
  return {
    rows,
    cols,
    south: 20,
    north: 30,
    west: 110,
    east: 120,
    points,
    checksum: 1,
  }
}

describe('wind display mode helpers', () => {
  it('validates and labels tri-state modes', () => {
    expect(isWindDisplayMode('particle')).toBe(true)
    expect(isWindDisplayMode('streamline')).toBe(true)
    expect(isWindDisplayMode('off')).toBe(true)
    expect(isWindDisplayMode('barb')).toBe(false)
    expect(windDisplayModeLabel('streamline')).toBe('流量场')
    expect(windDisplayModeChip('particle')).toBe('particle_flow')
    expect(windDisplayModeChip('streamline')).toBe('streamline')
  })
})

describe('wind streamline pure functions', () => {
  it('clamps streamline count by grid area', () => {
    const grid = makeUniformGrid()
    const count = computeStreamlineCountForGrid(grid)
    expect(count).toBeGreaterThanOrEqual(80)
    expect(count).toBeLessThanOrEqual(420)
  })

  it('builds deterministic seeds with custom rng', () => {
    let i = 0
    const rng = () => {
      i += 1
      return (i % 10) / 10
    }
    const seeds = buildStreamlineSeeds(makeUniformGrid(), 9, rng)
    expect(seeds).toHaveLength(9)
    expect(seeds.every((s) => s.lat >= 20 && s.lat <= 30)).toBe(true)
    expect(seeds.every((s) => s.lon >= 110 && s.lon <= 120)).toBe(true)
  })

  it('integrates a path along wind direction', () => {
    const grid = makeUniformGrid(12, 270) // 西风 → 向东积分
    const path = integrateStreamline(grid, 25, 112, 12, 0.3)
    expect(path.length).toBeGreaterThan(2)
    expect(path[path.length - 1].lon).toBeGreaterThan(path[0].lon)
  })

  it('viewport seed bounds keep density after large zoom-out grid', () => {
    const grid = { west: 60, east: 180, south: -10, north: 55 }
    const viewport = { west: 110, east: 125, south: 20, north: 35 }
    const seed = resolveStreamlineSeedBounds(grid, viewport)
    const fullCount = computeStreamlineCountForGrid({
      ...makeUniformGrid(),
      west: grid.west,
      east: grid.east,
      south: grid.south,
      north: grid.north,
    })
    const viewCount = computeStreamlineCountForArea(
      Math.abs(seed.north - seed.south) * Math.abs(seed.east - seed.west),
    )
    // 视口面积远小于全 grid：条数应更贴近视口，且种子落在视口附近
    expect(seed.west).toBeGreaterThanOrEqual(grid.west)
    expect(seed.east).toBeLessThanOrEqual(grid.east)
    expect(seed.west).toBeLessThan(120)
    expect(seed.east).toBeGreaterThan(115)
    expect(viewCount).toBeLessThanOrEqual(fullCount)
    const seeds = buildStreamlineSeeds(seed, viewCount, () => 0.5)
    expect(seeds.every((s) => s.lon >= seed.west && s.lon <= seed.east)).toBe(true)
  })

  it('streamlineLonWrapOffsets covers adjacent world copies', () => {
    expect(streamlineLonWrapOffsets(0)).toEqual([-360, 0, 360])
    expect(streamlineLonWrapOffsets(360)).toEqual([0, 360, 720])
  })

  it('wrappedPulse is continuous across the 0/1 seam', () => {
    const width = 0.28
    const nearEnd = wrappedPulse(0.98, 0.02, width)
    const nearStart = wrappedPulse(0.02, 0.02, width)
    expect(nearEnd).toBeGreaterThan(0.2)
    expect(nearStart).toBeGreaterThan(0.9)
    const s = 0.5
    const a0 = wrappedPulse(s, 0.99, width)
    const a1 = wrappedPulse(s, 0.01, width)
    expect(Math.abs(a0 - a1)).toBeLessThan(0.15)
    expect(wrappedPulse(0.5, 0, 0.2)).toBe(0)
  })

  it('keeps in-bound seeds when densifying toward a higher target count', () => {
    const grid = makeUniformGrid(10, 270)
    const seeds = buildStreamlineSeeds(grid, 12, () => 0.5)
    const target = computeStreamlineCountForGrid(grid)
    const kept = seeds.filter(
      (s) => s.lat >= grid.south && s.lat <= grid.north && s.lon >= grid.west && s.lon <= grid.east,
    )
    expect(kept.length).toBe(seeds.length)
    if (kept.length < target) {
      const extras = buildStreamlineSeeds(grid, target - kept.length, () => 0.25)
      expect(kept.length + extras.length).toBe(target)
    }
  })

  it('projectStreamlinePathStrokes caches screen pts and arc length', () => {
    const path = [
      { lat: 25, lon: 112, speed: 8 },
      { lat: 25.2, lon: 112.4, speed: 10 },
      { lat: 25.4, lon: 112.8, speed: 12 },
    ]
    let projectCalls = 0
    const project = (lngLat: [number, number]) => {
      projectCalls += 1
      return { x: lngLat[0] * 10, y: lngLat[1] * 10 }
    }
    const wraps = streamlineLonWrapOffsets(0)
    const strokes = projectStreamlinePathStrokes(path, wraps, project, {
      dpr: 1,
      canvasWidth: 2000,
      canvasHeight: 2000,
      margin: 40,
    })
    expect(projectCalls).toBe(path.length * wraps.length)
    expect(strokes.length).toBeGreaterThan(0)
    expect(strokes[0].pts).toHaveLength(3)
    expect(strokes[0].cum).toHaveLength(3)
    expect(strokes[0].cum[0]).toBe(0)
    expect(strokes[0].totalLen).toBeGreaterThan(2)
    expect(strokes[0].cum[2]).toBe(strokes[0].totalLen)

    // 复用同一结果不应再 project（调用方缓存语义）
    const again = projectStreamlinePathStrokes(path, wraps, project, {
      dpr: 1,
      canvasWidth: 2000,
      canvasHeight: 2000,
      margin: 40,
    })
    expect(again[0].pts[0]).toEqual(strokes[0].pts[0])
  })

  it('drops fully off-screen wrap copies', () => {
    const path = [
      { lat: 10, lon: 10, speed: 5 },
      { lat: 40, lon: 50, speed: 5 },
    ]
    const project = (lngLat: [number, number]) => ({ x: lngLat[0], y: lngLat[1] })
    const strokes = projectStreamlinePathStrokes(path, [0, 9999], project, {
      dpr: 1,
      canvasWidth: 100,
      canvasHeight: 100,
      margin: 10,
    })
    expect(strokes).toHaveLength(1)
    expect(strokes[0].pts[0].x).toBe(10)
  })
})

describe('weak scalar contours', () => {
  it('builds sparse low-alpha levels from ticks', () => {
    const levels = buildWeakScalarContourLevels([-10, 0, 10, 20, 30], {
      targetCount: 5,
      alpha: 0.2,
    })
    expect(levels.length).toBeGreaterThan(2)
    expect(levels.length).toBeLessThanOrEqual(8)
    expect(levels[0].color).toContain('rgba')
  })

  it('detects temperature and precipitation layer ids', () => {
    expect(isWeakContourLayerId('temperature')).toBe(true)
    expect(isWeakContourLayerId('temperature-80m')).toBe(true)
    expect(isWeakContourLayerId('precipitation')).toBe(true)
    expect(isWeakContourLayerId('pressure')).toBe(false)
    expect(isWeakContourLayerId('wind-field')).toBe(false)
  })
})

describe('scalar palette density', () => {
  it('keeps dense Windy-like LUTs for temperature and precipitation', () => {
    expect(getPaletteColors('thermal-orange').length).toBeGreaterThanOrEqual(12)
    expect(getPaletteColors('precip-cyan').length).toBeGreaterThanOrEqual(10)
  })
})
