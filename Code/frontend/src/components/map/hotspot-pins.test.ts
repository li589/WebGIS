import { describe, expect, it } from 'vitest'

import type { LayerHotspot } from '../../stores/layers/types'
import {
  buildDisplayHotspotPins,
  buildProjectedHotspotPins,
  getVisibleHotspotsForZoom,
  placeHotspotPins,
} from './hotspot-pins'

const HOTSPOTS: LayerHotspot[] = [
  { id: 'a', name: 'A', lng: 1, lat: 1, value: '1' },
  { id: 'b', name: 'B', lng: 2, lat: 2, value: '2' },
  { id: 'c', name: 'C', lng: 3, lat: 3, value: '3' },
  { id: 'd', name: 'D', lng: 4, lat: 4, value: '4' },
]

describe('hotspot-pins', () => {
  it('limits visible hotspots by zoom bands', () => {
    expect(getVisibleHotspotsForZoom(HOTSPOTS, 5.3).map((item) => item.id)).toEqual(['a'])
    expect(getVisibleHotspotsForZoom(HOTSPOTS, 6.1).map((item) => item.id)).toEqual(['a', 'b'])
    expect(getVisibleHotspotsForZoom(HOTSPOTS, 6.8).map((item) => item.id)).toEqual(['a', 'b', 'c'])
    expect(getVisibleHotspotsForZoom(HOTSPOTS, 7.1).map((item) => item.id)).toEqual([
      'a',
      'b',
      'c',
      'd',
    ])
  })

  it('projects pins and preserves selected priority during placement', () => {
    const rawPins = buildProjectedHotspotPins(
      HOTSPOTS.slice(0, 2),
      {
        project: ([lng, lat]) => ({ x: lng * 10, y: lat * 10 }),
      },
      'b',
    )

    const placedPins = placeHotspotPins(rawPins, { minDistance: 30, offsetStep: 10 })

    expect(placedPins[0]?.id).toBe('b')
    expect(placedPins[0]?.x).toBe(20)
    expect(placedPins[0]?.y).toBe(20)
    expect(placedPins[1]?.id).toBe('a')
    expect(placedPins[1]?.x).not.toBe(10)
    expect(buildDisplayHotspotPins(placedPins)[0]).toMatchObject({
      id: 'b',
      left: '20px',
      top: '20px',
      selected: true,
    })
  })
})
