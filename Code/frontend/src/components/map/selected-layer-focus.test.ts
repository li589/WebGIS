import { describe, expect, it, vi } from 'vitest'

import { focusMapOnHotspots } from './selected-layer-focus'

describe('selected-layer-focus', () => {
  it('uses easeTo for a single hotspot', () => {
    const map = {
      easeTo: vi.fn(),
      fitBounds: vi.fn(),
    } as any

    focusMapOnHotspots(map, [
      { id: 'a', name: 'A', lng: 113.2, lat: 23.1, value: '1' },
    ])

    expect(map.easeTo).toHaveBeenCalledWith({
      center: [113.2, 23.1],
      zoom: 6.6,
      duration: 650,
      essential: true,
    })
    expect(map.fitBounds).not.toHaveBeenCalled()
  })

  it('uses fitBounds for multiple hotspots', () => {
    const map = {
      easeTo: vi.fn(),
      fitBounds: vi.fn(),
    } as any

    focusMapOnHotspots(map, [
      { id: 'a', name: 'A', lng: 110, lat: 20, value: '1' },
      { id: 'b', name: 'B', lng: 120, lat: 30, value: '2' },
    ])

    expect(map.fitBounds).toHaveBeenCalledWith(
      [[110, 20], [120, 30]],
      {
        padding: { top: 120, right: 220, bottom: 120, left: 220 },
        maxZoom: 6.8,
        duration: 700,
        essential: true,
      },
    )
    expect(map.easeTo).not.toHaveBeenCalled()
  })
})
