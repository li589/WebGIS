import { describe, expect, it } from 'vitest'

import { buildMapViewportSnapshot } from './map-viewport-sync'

describe('map-viewport-sync', () => {
  it('normalizes center and bounds into EPSG:4326 snapshot', () => {
    const snapshot = buildMapViewportSnapshot({
      getCenter: () => ({ lng: 190, lat: 23 }),
      getBounds: () => ({
        getSouth: () => -95,
        getNorth: () => 96,
        getWest: () => 181,
        getEast: () => 540,
      }),
      getZoom: () => 5.8,
    })

    expect(snapshot).toEqual({
      center: { lng: -170, lat: 23 },
      bbox: {
        west: -179,
        south: -90,
        east: 180,
        north: 90,
        crs: 'EPSG:4326',
      },
      zoom: 5.8,
    })
  })

  it('reorders wrapped dateline bounds when east becomes smaller than west', () => {
    const snapshot = buildMapViewportSnapshot({
      getCenter: () => ({ lng: -181, lat: 10 }),
      getBounds: () => ({
        getSouth: () => -10,
        getNorth: () => 20,
        getWest: () => 170,
        getEast: () => -175,
      }),
      getZoom: () => 4.5,
    })

    expect(snapshot.center.lng).toBe(179)
    expect(snapshot.bbox).toEqual({
      west: -175,
      south: -10,
      east: 170,
      north: 20,
      crs: 'EPSG:4326',
    })
  })
})
