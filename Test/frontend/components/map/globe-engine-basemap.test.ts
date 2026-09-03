import { describe, expect, it } from 'vitest'

import {
  normalizeCesiumTileUrl,
  resolveCesiumBasemap,
} from '@/components/map/globe-engine/cesium/basemap-adapter'

describe('cesium basemap-adapter', () => {
  it('none yields empty imagery', () => {
    const spec = resolveCesiumBasemap('none')
    expect(spec.urlTemplate).toBeNull()
    expect(spec.overlayUrlTemplate).toBeNull()
  })

  it('known source exposes urlTemplate from TILE_SOURCE_MAP', () => {
    const spec = resolveCesiumBasemap('gaode-street')
    expect(spec.urlTemplate).toBeTruthy()
    expect(spec.urlTemplate).toContain('{z}')
    expect(spec.urlTemplate).toContain('{x}')
    expect(spec.urlTemplate).toContain('{y}')
  })

  it('strips subdomain placeholders Cesium cannot expand', () => {
    expect(normalizeCesiumTileUrl('https://{s}.tile.example/{z}/{x}/{y}.png')).toBe(
      'https://tile.example/{z}/{x}/{y}.png',
    )
    expect(normalizeCesiumTileUrl('/unified-tiles/osm/{z}/{x}/{y}')).toBe(
      '/unified-tiles/osm/{z}/{x}/{y}',
    )
  })
})

describe('cesium lighting hour', () => {
  it('julianDateFromLocalHour is stable for whole hours', async () => {
    const { julianDateFromLocalHour } = await import(
      '@/components/map/globe-engine/cesium/lighting'
    )
    // Avoid loading full cesium in unit test: stub minimal JulianDate.fromDate
    const Cesium = {
      JulianDate: {
        fromDate: (d: Date) => ({ stub: true, hours: d.getHours(), minutes: d.getMinutes() }),
      },
    } as unknown as typeof import('cesium')
    const jd = julianDateFromLocalHour(Cesium, 14.5, new Date('2026-06-21T00:00:00'))
    expect(jd).toMatchObject({ hours: 14, minutes: 30 })
  })
})
