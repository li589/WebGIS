import { describe, expect, it, vi } from 'vitest'

import {
  clipCoordsForGlobe,
  isLngLatOnGlobeVisibleSide,
  isGlobeProjection,
  lngLatToGlobeSphere,
  splitCoordsOnAntimeridian,
} from '@/components/map/canvas-utils'

function makeMap(projection: 'globe' | 'mercator', center = { lng: 0, lat: 0 }) {
  return {
    getProjection: () => ({ type: projection }),
    getCenter: () => center,
  } as any
}

describe('globe canvas geometry helpers', () => {
  it('maps lon/lat to a unit sphere', () => {
    const [x, y, z] = lngLatToGlobeSphere(0, 0)
    expect(x).toBeCloseTo(0)
    expect(y).toBeCloseTo(0)
    expect(z).toBeCloseTo(1)
    expect(Math.hypot(x, y, z)).toBeCloseTo(1)
  })

  it('splits an antimeridian crossing into independent segments', () => {
    expect(splitCoordsOnAntimeridian([[170, 10], [-170, 10], [-160, 12]])).toEqual([
      [[170, 10]],
      [[-170, 10], [-160, 12]],
    ])
  })

  it('keeps front hemisphere and rejects antipodal points', () => {
    const map = makeMap('globe')
    expect(isGlobeProjection(map)).toBe(true)
    expect(isLngLatOnGlobeVisibleSide(map, 0, 0)).toBe(true)
    expect(isLngLatOnGlobeVisibleSide(map, 180, 0)).toBe(false)
    expect(clipCoordsForGlobe(map, [[0, 0], [180, 0], [10, 0]])).toEqual([[[0, 0], [10, 0]]])
  })

  it('is a no-op for mercator projection', () => {
    const map = makeMap('mercator')
    expect(isGlobeProjection(map)).toBe(false)
    const coords = [[170, 10], [-170, 10]] as Array<[number, number]>
    expect(clipCoordsForGlobe(map, coords)).toEqual([coords])
  })

  it('fails closed when projection APIs throw', () => {
    const map = {
      getProjection: vi.fn(() => {
        throw new Error('map disposed')
      }),
      getCenter: vi.fn(() => ({ lng: 0, lat: 0 })),
    } as any
    expect(isGlobeProjection(map)).toBe(false)
  })
})
