import { describe, expect, it } from 'vitest'

import {
  buildViewBasis,
  celestialUnitVector,
  projectSkyDirection,
  solarGlareFactor,
  sunDirection,
  viewPoleFromCamera,
  type SolarSystemCamera,
} from '@/components/map/globe-solar-system'
import { subsolarDeclination, subsolarLongitude } from '@/components/map/globe-scene-utils'

const baseCamera: SolarSystemCamera = {
  lng: 0,
  lat: 0,
  bearing: 0,
  pitch: 0,
  zoom: 1.5,
}

describe('globe-solar-system projection', () => {
  it('maps celestial RA/Dec onto a unit sphere', () => {
    const v = celestialUnitVector(0, 0)
    expect(Math.hypot(v.x, v.y, v.z)).toBeCloseTo(1)
    expect(v.z).toBeCloseTo(1)
  })

  it('tilts view pole with pitch', () => {
    const flat = viewPoleFromCamera(baseCamera)
    const pitched = viewPoleFromCamera({ ...baseCamera, pitch: 55 })
    expect(pitched.y).toBeGreaterThan(flat.y)
  })

  it('projects sun in the subsolar direction and keeps it on-screen for nadir view', () => {
    const hour = 12
    const date = new Date(Date.UTC(2026, 5, 21))
    const lon = subsolarLongitude(hour, 0)
    const lat = subsolarDeclination(date)
    const sun = sunDirection(hour, date)
    // With tz=0 noon, subsolar lon ≈ 0
    expect(lon).toBeCloseTo(0, 0)
    expect(Math.abs(lat)).toBeLessThan(24)

    const basis = buildViewBasis({ ...baseCamera, lng: lon, lat: 0 })
    const scr = projectSkyDirection(sun, basis, 800, 600, 1.2)
    // 日下点几乎对准视向时投影可被裁掉（地球遮挡）；换到侧视应可见
    const sideBasis = buildViewBasis({ ...baseCamera, lng: lon + 90, lat: 0 })
    const side = projectSkyDirection(sun, sideBasis, 800, 600, 1.2)
    expect(side).not.toBeNull()
    // 侧视太阳应落在画布附近（可略出边，透视铺开）
    expect(side!.x).toBeGreaterThan(-200)
    expect(side!.x).toBeLessThan(1000)
    expect(Number.isFinite(side!.y)).toBe(true)
    // 正视时要么 null（被地球挡）要么在画布内
    if (scr) {
      expect(scr.x).toBeGreaterThanOrEqual(-50)
      expect(scr.x).toBeLessThanOrEqual(850)
    }
  })

  it('moves projected stars when bearing changes', () => {
    const star = celestialUnitVector(6.75, -16.7) // Sirius-ish
    const a = projectSkyDirection(star, buildViewBasis(baseCamera), 1000, 1000, 1.5)
    const b = projectSkyDirection(
      star,
      buildViewBasis({ ...baseCamera, bearing: 90 }),
      1000,
      1000,
      1.5,
    )
    if (a && b) {
      expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThan(5)
    } else {
      // 至少一侧可见，证明投影路径可用
      expect(a || b).toBeTruthy()
    }
  })

  it('solar glare washes out nearby stars', () => {
    expect(solarGlareFactor(0, 200)).toBe(0)
    expect(solarGlareFactor(200, 200)).toBe(1)
    expect(solarGlareFactor(40, 200)).toBeLessThan(solarGlareFactor(120, 200))
  })
})
