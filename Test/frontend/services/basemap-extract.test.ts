import { describe, expect, it, vi } from 'vitest'
import {
  bboxAreaSqDeg,
  buildOverpassQuery,
  extractAdminAreaAt,
  overpassWaysToGeoJson,
  pointInPolygonGeometry,
} from '@/services/basemap-extract'

vi.mock('@/app/admin-boundaries', () => ({
  loadWorldAdmin1Boundaries: vi.fn(async () => ({
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { name: 'Samangan', adcode: 'AF-SAM', iso_a2: 'AF' },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [67.0, 35.0],
              [68.5, 35.0],
              [68.5, 36.5],
              [67.0, 36.5],
              [67.0, 35.0],
            ],
          ],
        },
      },
    ],
  })),
  loadWorldAdmin0Boundaries: vi.fn(async () => ({
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: { name: 'Afghanistan', adcode: 'AFG', iso_a2: 'AF' },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [60.0, 29.0],
              [75.0, 29.0],
              [75.0, 39.0],
              [60.0, 39.0],
              [60.0, 29.0],
            ],
          ],
        },
      },
    ],
  })),
}))

const SQUARE_POLYGON: GeoJSON.Polygon = {
  type: 'Polygon',
  coordinates: [
    [
      [113.0, 23.0],
      [114.0, 23.0],
      [114.0, 24.0],
      [113.0, 24.0],
      [113.0, 23.0],
    ],
  ],
}

const POLYGON_WITH_HOLE: GeoJSON.Polygon = {
  type: 'Polygon',
  coordinates: [
    SQUARE_POLYGON.coordinates[0],
    [
      [113.4, 23.4],
      [113.6, 23.4],
      [113.6, 23.6],
      [113.4, 23.6],
      [113.4, 23.4],
    ],
  ],
}

describe('extractAdminAreaAt', () => {
  it('returns finest admin polygon containing the point', async () => {
    const area = await extractAdminAreaAt(67.649, 35.729)
    expect(area).not.toBeNull()
    expect(area?.name).toBe('Samangan')
    expect(area?.adminLevel).toBe('state')
    expect(area?.adcode).toBe('AF-SAM')
  })
})

describe('pointInPolygonGeometry', () => {
  it('inside / outside / boundary tolerance', () => {
    expect(pointInPolygonGeometry(113.5, 23.5, SQUARE_POLYGON)).toBe(true)
    expect(pointInPolygonGeometry(112.0, 23.5, SQUARE_POLYGON)).toBe(false)
    expect(pointInPolygonGeometry(110.0, 20.0, SQUARE_POLYGON)).toBe(false)
  })

  it('hole excluded', () => {
    expect(pointInPolygonGeometry(113.5, 23.5, POLYGON_WITH_HOLE)).toBe(false)
    expect(pointInPolygonGeometry(113.2, 23.2, POLYGON_WITH_HOLE)).toBe(true)
  })

  it('multipolygon hits any part', () => {
    const mp: GeoJSON.MultiPolygon = {
      type: 'MultiPolygon',
      coordinates: [
        SQUARE_POLYGON.coordinates,
        [
          [
            [100.0, 30.0],
            [101.0, 30.0],
            [101.0, 31.0],
            [100.0, 31.0],
            [100.0, 30.0],
          ],
        ],
      ],
    }
    expect(pointInPolygonGeometry(100.5, 30.5, mp)).toBe(true)
    expect(pointInPolygonGeometry(113.5, 23.5, mp)).toBe(true)
    expect(pointInPolygonGeometry(90.0, 10.0, mp)).toBe(false)
  })

  it('non-polygon geometry always false', () => {
    const line: GeoJSON.LineString = {
      type: 'LineString',
      coordinates: [
        [113.0, 23.0],
        [114.0, 24.0],
      ],
    }
    expect(pointInPolygonGeometry(113.5, 23.5, line as unknown as GeoJSON.Geometry)).toBe(false)
  })
})

describe('buildOverpassQuery', () => {
  it('major filter uses limited pattern and bbox order south,west,north,east', () => {
    const q = buildOverpassQuery({ west: 113, south: 23, east: 114, north: 24 }, 'major')
    expect(q).toContain('way["highway"~"^(motorway|trunk|primary)$"](23,113,24,114)')
    expect(q).toContain('[out:json][timeout:')
    expect(q).toContain('out geom qt;')
  })

  it('all filter includes secondary/tertiary/residential', () => {
    const q = buildOverpassQuery({ west: 113, south: 23, east: 114, north: 24 }, 'all')
    expect(q).toContain('secondary')
    expect(q).toContain('residential')
  })
})

describe('bboxAreaSqDeg', () => {
  it('computes absolute area', () => {
    expect(bboxAreaSqDeg({ west: 113, south: 23, east: 114, north: 24 })).toBeCloseTo(1.0, 10)
  })
})

describe('overpassWaysToGeoJson', () => {
  it('converts ways with tags and skips degenerate entries', () => {
    const { geojson, truncated } = overpassWaysToGeoJson([
      {
        type: 'way',
        id: 1,
        tags: { highway: 'primary', name: 'G107' },
        geometry: [
          { lat: 23.0, lon: 113.0 },
          { lat: 23.1, lon: 113.1 },
        ],
      },
      { type: 'node', id: 2 },
      { type: 'way', id: 3, geometry: [{ lat: 23.0, lon: 113.0 }] },
    ])
    expect(truncated).toBe(false)
    expect(geojson.features).toHaveLength(1)
    const feature = geojson.features[0]!
    expect(feature.geometry.type).toBe('LineString')
    expect(feature.properties?.name).toBe('G107')
    expect((feature.geometry as GeoJSON.LineString).coordinates).toEqual([
      [113.0, 23.0],
      [113.1, 23.1],
    ])
  })

  it('truncates at limit', () => {
    const ways = Array.from({ length: 5 }, (_, i) => ({
      type: 'way',
      id: i,
      geometry: [
        { lat: 23, lon: 113 },
        { lat: 23.1, lon: 113.1 },
      ],
    }))
    const { geojson, truncated } = overpassWaysToGeoJson(ways, 3)
    expect(geojson.features).toHaveLength(3)
    expect(truncated).toBe(true)
  })
})
