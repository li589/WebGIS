import { describe, expect, it } from 'vitest'

import { getDefaultTileSource, getSourcesByStyle, TILE_SOURCES } from '@/services/api-config'
import {
  BASEMAP_COPY,
  BRAND,
  LEGACY_BRAND,
  WIND_COPY,
  basemapStyleLabel,
} from '@/ui-copy/index'

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

  it('keeps Esri terrain only under terrain, not street', () => {
    const streetIds = getSourcesByStyle('street').map((s) => s.id)
    expect(streetIds).not.toContain('esri-terrain')
    expect(streetIds.filter((id) => id.startsWith('esri-'))).toEqual(['esri-street'])
    expect(getSourcesByStyle('terrain').map((s) => s.id)).toEqual([
      'esri-terrain',
      'esri-hillshade',
      'opentopo-terrain',
      'tianditu-ter',
    ])
  })

  it('exposes twenty sources including blank', () => {
    expect(TILE_SOURCES.some((s) => s.id === 'none')).toBe(true)
    expect(TILE_SOURCES.length).toBe(20)
  })
})

describe('ui-copy glossary', () => {
  it('keeps brand and wind labels stable for acceptance', () => {
    // 验收品牌：SGFS / Satellite-Ground Fusion Soil Data Platform
    expect(BRAND.shortName).toBe('星地融合土壤数据平台')
    expect(BRAND.fullName).toBe(
      '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
    )
    expect(BRAND.displayNameEn).toBe('Satellite-Ground Fusion Soil Data Platform')
    expect(BRAND.eyebrow).toBe('SGFS')
    expect(WIND_COPY.particle).toBe('粒子流')
    expect(WIND_COPY.streamline).toBe('流量场')
    expect(WIND_COPY.off).toBe('网格')
    expect(basemapStyleLabel('none')).toBe(BASEMAP_COPY.styleNone)
  })

  it('keeps legacy CGDA brand available for rollback', () => {
    expect(LEGACY_BRAND.shortName).toBe('综合地理态势')
    expect(LEGACY_BRAND.fullName).toBe('综合地理态势分析系统')
    expect(LEGACY_BRAND.legacyAbbr).toBe('CGDA / CGDAS')
  })
})
