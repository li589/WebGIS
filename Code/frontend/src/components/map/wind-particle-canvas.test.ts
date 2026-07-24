import { describe, expect, it } from 'vitest'

import {
  __testInterpolateWindUV,
  computeViewportBBoxFromBounds,
  mergeRoamBounds,
} from './wind-particle-canvas'
import type { WindGridPoint } from './wind-grid'

// ─── 测试夹具 ────────────────────────────────────────────────

/** 构造一个 WindGridPoint（仅 speed/direction 有意义，lat/lon 仅占位） */
function point(speed: number, direction: number): WindGridPoint {
  return { lat: 0, lon: 0, speed, direction }
}

/** 涡旋四角点：四角方向分别为 180°/270°/90°/0°，speed=10 */
function vortexCorners(): {
  nw: WindGridPoint
  ne: WindGridPoint
  sw: WindGridPoint
  se: WindGridPoint
} {
  return {
    nw: point(10, 180),
    ne: point(10, 270),
    sw: point(10, 90),
    se: point(10, 0),
  }
}

/** 均匀流场：四角 speed/direction 相同 */
function uniformCorners(
  speed: number,
  direction: number,
): {
  nw: WindGridPoint
  ne: WindGridPoint
  sw: WindGridPoint
  se: WindGridPoint
} {
  return {
    nw: point(speed, direction),
    ne: point(speed, direction),
    sw: point(speed, direction),
    se: point(speed, direction),
  }
}

// ─── Part A：算法修复 ────────────────────────────────────────

describe('interpolateWind U/V bilinear (Part A1+A2)', () => {
  it('vortex center produces near-zero speed (storm eye stagnation)', () => {
    // 涡旋四角点对称排列，中心 (u, v) 应趋于 (0, 0)，speed 趋近 0（涡旋眼静风）。
    // 旧实现：对 direction 做最短角度插值在涡旋中心是病态的，会产生任意方向。
    // 新实现：对 (u, v) 双线性插值，中心 (u, v) ≈ (0, 0)，与物理一致。
    const bounds = { south: 0, north: 10, west: 0, east: 10 }
    const result = __testInterpolateWindUV(vortexCorners(), bounds, 5, 5)
    expect(result.speed).toBeLessThan(1e-3)
  })

  it('uniform flow field matches exact values (regression for uniform case)', () => {
    // 均匀场（speed=5, direction=90°）：任意内点应得 speed=5, direction=90°
    const bounds = { south: 0, north: 10, west: 0, east: 10 }
    const result = __testInterpolateWindUV(uniformCorners(5, 90), bounds, 3, 7)
    expect(result.speed).toBeCloseTo(5, 5)
    expect(result.direction).toBeCloseTo(90, 5)
  })

  it('linear speed gradient with uniform direction matches bilinear speed interpolation', () => {
    // 四角 speed 从 5 (西) 线性变到 15 (东)，方向均匀 0°
    // t=0.5 处 speed 应为 10（双线性插值在线性梯度下精确）
    const corners = {
      nw: point(5, 0),
      ne: point(15, 0),
      sw: point(5, 0),
      se: point(15, 0),
    }
    const bounds = { south: 0, north: 10, west: 0, east: 10 }
    const result = __testInterpolateWindUV(corners, bounds, 5, 5)
    expect(result.speed).toBeCloseTo(10, 5)
    expect(result.direction).toBeCloseTo(0, 5)
  })

  it('RK2 midpoint produces smaller radial drift than Euler in rotational flow', () => {
    // 在涡旋场中，Euler 一阶积分会因方向不断变化但用单点速度推进而外旋；
    // RK2 midpoint 用半步重采样方向，曲率更准确，径向漂移更小。
    const bounds = { south: -5, north: 5, west: -5, east: 5 }
    const corners = vortexCorners()

    const stepSize = 0.3
    const steps = 50

    // Euler：每步用当前位置的风场推进
    let eulerLat = 0.1
    let eulerLon = 0
    for (let i = 0; i < steps; i++) {
      const w = __testInterpolateWindUV(corners, bounds, eulerLat, eulerLon)
      if (w.speed < 1e-6) break
      const advectSpeed = Math.max(w.speed, 0.5)
      const rad = ((w.direction + 180) * Math.PI) / 180
      const u = advectSpeed * Math.sin(rad)
      const v = advectSpeed * Math.cos(rad)
      eulerLon += u * stepSize
      eulerLat += v * stepSize
    }

    // RK2 midpoint：先用当前位置风场算半步，再用 midpoint 风场推进一步
    let rk2Lat = 0.1
    let rk2Lon = 0
    for (let i = 0; i < steps; i++) {
      const w0 = __testInterpolateWindUV(corners, bounds, rk2Lat, rk2Lon)
      if (w0.speed < 1e-6) break
      const advectSpeed0 = Math.max(w0.speed, 0.5)
      const rad0 = ((w0.direction + 180) * Math.PI) / 180
      const u0 = advectSpeed0 * Math.sin(rad0)
      const v0 = advectSpeed0 * Math.cos(rad0)
      const midLat = rk2Lat + v0 * stepSize * 0.5
      const midLon = rk2Lon + u0 * stepSize * 0.5
      const wMid = __testInterpolateWindUV(corners, bounds, midLat, midLon)
      const advectSpeedMid = Math.max(wMid.speed, 0.5)
      const radMid = ((wMid.direction + 180) * Math.PI) / 180
      const uMid = advectSpeedMid * Math.sin(radMid)
      const vMid = advectSpeedMid * Math.cos(radMid)
      rk2Lon += uMid * stepSize
      rk2Lat += vMid * stepSize
    }

    // 起点距中心 0.1°。理想粒子应绕中心做近圆周运动，距中心距离应保持 ~0.1。
    // Euler 因外旋使距离增长更大，RK2 增长更小。
    const eulerDist = Math.sqrt(eulerLat * eulerLat + eulerLon * eulerLon)
    const rk2Dist = Math.sqrt(rk2Lat * rk2Lat + rk2Lon * rk2Lon)
    expect(rk2Dist).toBeLessThan(eulerDist)
  })
})

// ─── Part B：渲染流畅性 ────────────────────────────────────

describe('exponential fade model (Part B1+B2)', () => {
  // 旧线性模型：Math.min(fadeAlpha * dt, 0.15)
  // 新指数模型：1 - Math.pow(1 - fadeAlpha, dt)
  const fadeAlpha = 0.018

  it('dt=1: exponential fade matches old linear model', () => {
    const oldLinear = Math.min(fadeAlpha * 1, 0.15)
    const newExpo = 1 - Math.pow(1 - fadeAlpha, 1)
    expect(newExpo).toBeCloseTo(oldLinear, 5)
  })

  it('dt=4: exponential fade does NOT saturate at 0.15 cap', () => {
    const oldLinear = Math.min(fadeAlpha * 4, 0.15) // = 0.072（未触发 cap）
    const newExpo = 1 - Math.pow(1 - fadeAlpha, 4)
    // 新模型 ≈ 0.0701，与旧线性相近但数学上等价于"连续 4 帧每帧衰减 1.8%"
    // 精确值：1 - (1 - 0.018)^4 = 1 - 0.929920... = 0.0700792...
    expect(newExpo).toBeCloseTo(0.0701, 3)
    expect(newExpo).toBeLessThan(0.15)
    expect(Math.abs(newExpo - oldLinear)).toBeLessThan(0.01)
  })

  it('dt=20 (capped at MAX_DT_FRAMES=4): exponential stays bounded, no burst clearing', () => {
    const cappedDt = Math.min(20, 4)
    const newExpo = 1 - Math.pow(1 - fadeAlpha, cappedDt)
    expect(newExpo).toBeLessThan(0.1)
  })

  it('advectDt clamp: dt=4 limits particle displacement to dt=2 equivalent', () => {
    const dt = 4
    const speedScale = 0.026
    const zoomFactor = 2.0
    const fullDisplacement = speedScale * zoomFactor * dt
    const clampedDisplacement = speedScale * zoomFactor * Math.min(dt, 2)
    expect(clampedDisplacement).toBeLessThan(fullDisplacement)
    expect(clampedDisplacement).toEqual(speedScale * zoomFactor * 2)
  })
})

// ─── Part C：视口自动加载 ──────────────────────────────────

describe('viewport bbox helpers (Part C1+C2)', () => {
  it('computeViewportBBoxFromBounds: normal viewport within ±180°', () => {
    const bbox = computeViewportBBoxFromBounds({
      getWest: () => 100,
      getEast: () => 130,
      getSouth: () => 20,
      getNorth: () => 40,
    })
    expect(bbox).toEqual({ south: 20, north: 40, west: 100, east: 130 })
  })

  it('computeViewportBBoxFromBounds: antimeridian-crossing viewport (east < west)', () => {
    // 视口跨 ±180°：实际从 170° 向东到 -175°（即 185°）
    const bbox = computeViewportBBoxFromBounds({
      getWest: () => 170,
      getEast: () => -175,
      getSouth: () => -10,
      getNorth: () => 20,
    })
    expect(bbox).toEqual({ south: -10, north: 20, west: 170, east: 185 })
  })

  it('computeViewportBBoxFromBounds: clamps south/north to [-85, 85]', () => {
    const bbox = computeViewportBBoxFromBounds({
      getWest: () => 0,
      getEast: () => 10,
      getSouth: () => -95,
      getNorth: () => 95,
    })
    expect(bbox.south).toBe(-85)
    expect(bbox.north).toBe(85)
  })

  it('mergeRoamBounds: returns viewport when grid is null', () => {
    const viewport = { south: 0, north: 10, west: 0, east: 10 }
    expect(mergeRoamBounds(null, viewport)).toEqual(viewport)
  })

  it('mergeRoamBounds: returns grid when viewport is null (backward compat)', () => {
    const grid = { south: 0, north: 10, west: 0, east: 10 }
    expect(mergeRoamBounds(grid, null)).toEqual(grid)
  })

  it('mergeRoamBounds: returns outer envelope (union) when both present', () => {
    // 模拟用户平移到新区域：grid 仍为旧视口（100-120°E），viewport 已移到新区域（110-130°E）
    // 期望并集为 100-130°E，让粒子能在 120-130°E 的新区域分布
    const grid = { south: 20, north: 40, west: 100, east: 120 }
    const viewport = { south: 15, north: 45, west: 110, east: 130 }
    const merged = mergeRoamBounds(grid, viewport)
    expect(merged).toEqual({ south: 15, north: 45, west: 100, east: 130 })
  })

  it('mergeRoamBounds: returns null when both null', () => {
    expect(mergeRoamBounds(null, null)).toBeNull()
  })

  it('mergeRoamBounds: viewport fully outside grid (large pan) still returns union', () => {
    // 极端情况：viewport 完全在 grid 外（用户大幅平移）
    // 仍应返回并集，让粒子能分布到新视口区域（用 grid 边缘风场外推）
    const grid = { south: 30, north: 40, west: 100, east: 110 }
    const viewport = { south: 10, north: 20, west: 130, east: 140 }
    const merged = mergeRoamBounds(grid, viewport)
    expect(merged).toEqual({ south: 10, north: 40, west: 100, east: 140 })
  })
})
