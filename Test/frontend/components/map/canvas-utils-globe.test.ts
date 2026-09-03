import { describe, expect, it, vi } from 'vitest'

import {
  clipCoordsForGlobe,
  getGlobeViewPole,
  isLngLatOccludedByGlobe,
  isLngLatOnGlobeVisibleSide,
  isGlobeProjection,
  lngLatToGlobeSphere,
  splitCoordsOnAntimeridian,
} from '@/components/map/canvas-utils'

function makeMap(
  projection: 'globe' | 'mercator',
  center = { lng: 0, lat: 0 },
  pitch = 0,
  bearing = 0,
) {
  return {
    getProjection: () => ({ type: projection }),
    getCenter: () => center,
    getPitch: () => pitch,
    getBearing: () => bearing,
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
    expect(isLngLatOccludedByGlobe(map, 180, 0)).toBe(true)
    expect(clipCoordsForGlobe(map, [[0, 0], [180, 0], [10, 0]])).toEqual([[[0, 0], [10, 0]]])
  })

  it('culls back side under pitched camera toward the horizon', () => {
    // pitch 60°：视向极点向北倾，南半球更易被判为背面
    const map = makeMap('globe', { lng: 0, lat: 0 }, 60, 0)
    const pole = getGlobeViewPole(map)
    expect(pole[1]).toBeGreaterThan(0.4)
    expect(isLngLatOccludedByGlobe(map, 0, -70)).toBe(true)
    expect(isLngLatOnGlobeVisibleSide(map, 0, 40)).toBe(true)
  })

  it('is a no-op for mercator projection', () => {
    const map = makeMap('mercator')
    expect(isGlobeProjection(map)).toBe(false)
    expect(isLngLatOccludedByGlobe(map, 180, 0)).toBe(false)
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
