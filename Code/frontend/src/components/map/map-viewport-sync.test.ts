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

  it('preserves antimeridian-crossing viewport via +360 east extension', () => {
    // 视口实际跨越 170° → 180° → -180° → -175°（短路径，跨 ±180° 经线）
    // 旧实现错误交换为 west=-175/east=170（映射到地球反面，跨度 345°）
    // 新实现保留 west=170，east 扩展为 185（短路径语义，便于 tilesInBounds 归一化）
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
      west: 170,
      south: -10,
      east: 185,
      north: 20,
      crs: 'EPSG:4326',
    })
  })
})
