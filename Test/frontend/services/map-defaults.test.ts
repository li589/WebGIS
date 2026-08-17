import { afterEach, describe, expect, it } from 'vitest'

import {
  getMapDefaults,
  hydrateMapDefaults,
  MAP_DEFAULT_FALLBACK,
} from '@/services/map-defaults'
import { BRAND, ORG_LABEL } from '@/ui-copy/brand'

describe('map-defaults', () => {
  afterEach(() => {
    hydrateMapDefaults({
      longitude: MAP_DEFAULT_FALLBACK.longitude,
      latitude: MAP_DEFAULT_FALLBACK.latitude,
      zoom: MAP_DEFAULT_FALLBACK.zoom,
      tileSource: MAP_DEFAULT_FALLBACK.tileSource,
      aoiPresets: [],
    })
  })

  it('hydrates longitude/latitude/zoom/tileSource from config', () => {
    hydrateMapDefaults({
      longitude: 116.4,
      latitude: 39.9,
      zoom: 6,
      tileSource: 'osm-standard',
    })
    const d = getMapDefaults()
    expect(d.longitude).toBe(116.4)
    expect(d.latitude).toBe(39.9)
    expect(d.zoom).toBe(6)
    expect(d.tileSource).toBe('osm-standard')
  })

  it('merges org AOI presets', () => {
    hydrateMapDefaults({
      aoiPresets: [{ label: '校园', west: 1, south: 2, east: 3, north: 4 }],
    })
    expect(getMapDefaults().aoiPresets).toEqual([
      { label: '校园', west: 1, south: 2, east: 3, north: 4 },
    ])
  })
})

describe('brand whitelabel defaults', () => {
  it('keeps stock brand and org label without VITE overrides', () => {
    expect(BRAND.shortName).toBeTruthy()
    // 2026-08 验收更名：CGDA（含「地理」）→ SGFS「星地融合土壤水分监测与干旱预警系统」
    expect(BRAND.fullName).toBe('星地融合土壤水分监测与干旱预警系统')
    expect(BRAND.abbr).toBe('SGFS')
    expect(ORG_LABEL).toBe('科研')
  })
})
