import { describe, expect, it } from 'vitest'

import type { WindGeoJSON } from '../components/map/types'
import {
  filterGeojsonInsideTileBounds,
  filterGeojsonOutsideCoverage,
  mergeWeatherTiles,
} from './weather-tile-utils'

function pointFc(coords: Array<[number, number]>): WindGeoJSON {
  return {
    type: 'FeatureCollection',
    features: coords.map(([lon, lat], i) => ({
      type: 'Feature',
      properties: { i },
      geometry: { type: 'Point', coordinates: [lon, lat] },
    })),
  }
}

describe('filterGeojsonOutsideCoverage', () => {
  it('keeps only points outside covered tile bboxes', () => {
    const geo = pointFc([
      [110.1, 20.1],
      [112.5, 22.5],
      [118, 24],
    ])
    const out = filterGeojsonOutsideCoverage(geo, [
      { west: 110, south: 20, east: 115, north: 25 },
    ])
    expect(out.features).toHaveLength(1)
    expect((out.features[0].geometry as { coordinates: number[] }).coordinates).toEqual([118, 24])
  })

  it('does not treat tile south edge as covered (equator seam)', () => {
    // 北半球瓦片 south=0 半开不含 lat=0；覆盖检测也必须半开，否则赤道点被父级裁掉
    const geo = pointFc([
      [120, 0],
      [120, -1.25],
      [120, 1.25],
    ])
    const out = filterGeojsonOutsideCoverage(geo, [
      { west: 112.5, south: 0, east: 135, north: 40.98 },
    ])
    const lats = out.features.map(
      (f) => (f.geometry as { coordinates: number[] }).coordinates[1],
    )
    expect(lats).toEqual(expect.arrayContaining([0, -1.25]))
    expect(lats).not.toContain(1.25)
  })
})

describe('filterGeojsonInsideTileBounds', () => {
  it('uses half-open bounds so shared edges belong to one tile', () => {
    const geo = pointFc([
      [110, 20.5], // west edge — keep
      [115, 20.5], // east edge — drop unless includeEast
      [112, 25], // north edge — keep
      [112, 20], // south edge — drop unless includeSouth
    ])
    const bounds = { west: 110, south: 20, east: 115, north: 25 }
    const clipped = filterGeojsonInsideTileBounds(geo, bounds)
    const coords = clipped.features.map(
      (f) => (f.geometry as { coordinates: number[] }).coordinates,
    )
    expect(coords).toEqual([
      [110, 20.5],
      [112, 25],
    ])

    const withEdges = filterGeojsonInsideTileBounds(geo, bounds, {
      includeEast: true,
      includeSouth: true,
    })
    expect(withEdges.features).toHaveLength(4)
  })

  it('keeps Pacific points when viewport east is extended past 180', () => {
    const geo = pointFc([
      [100, 20],
      [-170, 10],
      [20, 0],
    ])
    const clipped = filterGeojsonInsideTileBounds(
      geo,
      { west: 90, south: -40, east: 200, north: 55 },
      { includeEast: true, includeSouth: true },
    )
    const lons = clipped.features.map(
      (f) => (f.geometry as { coordinates: number[] }).coordinates[0],
    )
    expect(lons).toEqual(expect.arrayContaining([100, -170]))
    expect(lons).not.toContain(20)
  })
})

describe('mergeWeatherTiles parent vs child resolutions', () => {
  it('keeps both resolutions when not clipped (documents why gap-fill must clip)', () => {
    const merged = mergeWeatherTiles([
      {
        layerId: 't',
        z: 6,
        x: 0,
        y: 0,
        hour: 0,
        geojson: pointFc([[110.0, 20.0], [110.25, 20.0]]),
      },
      {
        layerId: 't',
        z: 5,
        x: 0,
        y: 0,
        hour: 0,
        geojson: pointFc([[110.0, 20.0], [110.5, 20.0]]),
      },
    ])
    // same 110,20 deduped; 110.25 and 110.5 both survive → would double-paint without gap clip
    expect(merged.features).toHaveLength(3)
  })
})
