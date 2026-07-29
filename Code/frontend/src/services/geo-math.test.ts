import { describe, expect, it } from 'vitest'
import {
  lngSpanFromList,
  normalizeLngLatBBox,
  overlaySafeWgs84Bounds,
  wrapLongitude,
} from './geo-math'

describe('geo-math', () => {
  it('wrapLongitude edges', () => {
    expect(wrapLongitude(180)).toBe(180)
    expect(wrapLongitude(-180)).toBe(-180)
    expect(wrapLongitude(190)).toBeCloseTo(-170, 10)
  })

  it('lngSpanFromList unwraps dateline', () => {
    const span = lngSpanFromList([170, -170, 175])
    expect(span).not.toBeNull()
    expect(span![0]).toBeLessThan(span![1])
    expect(span![1]).toBeGreaterThan(180)
  })

  it('overlaySafeWgs84Bounds normalizes near-global', () => {
    expect(overlaySafeWgs84Bounds(-180, -85, 180, 85)).toEqual([-180, -85, 180, 85])
  })

  it('normalizeLngLatBBox unwraps pacific strip', () => {
    const b = normalizeLngLatBBox(170, -10, -170, 10)
    expect(b[0]).toBeLessThan(b[2])
    expect(b[2]).toBe(190)
  })
})
