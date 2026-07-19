import { describe, expect, it } from 'vitest'

import {
  bearing,
  computeSegments,
  formatBearing,
  formatDistance,
  haversineDistance,
} from './measure-geo'

describe('measure-geo', () => {
  it('computes haversine distance for a short east-west segment near equator', () => {
    // ~111.2 km per degree longitude at equator
    const d = haversineDistance({ lng: 0, lat: 0 }, { lng: 1, lat: 0 })
    expect(d).toBeGreaterThan(110_000)
    expect(d).toBeLessThan(112_000)
  })

  it('returns east bearing for due-east travel', () => {
    const b = bearing({ lng: 113, lat: 23 }, { lng: 114, lat: 23 })
    expect(b).toBeGreaterThan(85)
    expect(b).toBeLessThan(95)
  })

  it('formats distance and bearing', () => {
    expect(formatDistance(850)).toBe('850 m')
    expect(formatDistance(1234)).toBe('1.23 km')
    expect(formatDistance(12_300)).toBe('12.3 km')
    expect(formatBearing(45.26)).toBe('45.3°')
    expect(formatDistance(Number.NaN)).toBe('--')
  })

  it('accumulates segment distances', () => {
    const { segments, total } = computeSegments([
      { lng: 0, lat: 0 },
      { lng: 1, lat: 0 },
      { lng: 1, lat: 1 },
    ])
    expect(segments).toHaveLength(2)
    expect(total).toBeGreaterThan(segments[0].distance)
    expect(total).toBeCloseTo(segments[0].distance + segments[1].distance, 5)
  })
})
