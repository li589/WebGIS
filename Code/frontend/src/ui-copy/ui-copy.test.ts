import { describe, expect, it } from 'vitest'

import { getDefaultTileSource, getSourcesByStyle, TILE_SOURCES } from '../services/api-config'
import { BASEMAP_COPY, BRAND, WIND_COPY, basemapStyleLabel } from './index'

describe('acceptance basemap defaults', () => {
  it('defaults to gaode-street', () => {
    expect(getDefaultTileSource()).toBe('gaode-street')
  })

  it('orders street/satellite with Gaode then Bing first', () => {
    expect(
      getSourcesByStyle('street')
        .map((s) => s.id)
        .slice(0, 2),
    ).toEqual(['gaode-street', 'bing-road'])
    expect(
      getSourcesByStyle('satellite')
        .map((s) => s.id)
        .slice(0, 2),
    ).toEqual(['gaode-satellite', 'bing-aerial'])
  })

  it('exposes eighteen sources including blank', () => {
    expect(TILE_SOURCES.some((s) => s.id === 'none')).toBe(true)
    expect(TILE_SOURCES.length).toBe(18)
  })
})

describe('ui-copy glossary', () => {
  it('keeps brand and wind labels stable for acceptance', () => {
    expect(BRAND.shortName).toBe('综合地理态势')
    expect(BRAND.fullName).toBe('综合地理态势分析系统')
    expect(BRAND.eyebrow).toBe('CGDA')
    expect(WIND_COPY.particle).toBe('粒子流')
    expect(WIND_COPY.streamline).toBe('流量场')
    expect(WIND_COPY.off).toBe('关闭')
    expect(basemapStyleLabel('none')).toBe(BASEMAP_COPY.styleNone)
  })
})
