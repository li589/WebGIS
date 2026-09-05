import { describe, expect, it } from 'vitest'

import {
  isEnglishInversionCatalogId,
  resolveInversionCatalogId,
  sanitizeRunGroupTitle,
} from '@/stores/layers/inversion-catalog'

describe('inversion-catalog', () => {
  it('detects English fenkuai / avg / imported overlay ids', () => {
    expect(isEnglishInversionCatalogId('omega_sf_fenkuai_smap_online')).toBe(true)
    expect(isEnglishInversionCatalogId('omega-sf-fenkuai-fy_single')).toBe(true)
    expect(isEnglishInversionCatalogId('imported-omega_sf_fenkuai_smap_online-00')).toBe(true)
    expect(isEnglishInversionCatalogId('omega_avg_daily_fy')).toBe(true)
    expect(isEnglishInversionCatalogId('method-smap-omega-doy-dynamic')).toBe(false)
    expect(isEnglishInversionCatalogId('wf-run-group-sm')).toBe(false)
    expect(isEnglishInversionCatalogId('')).toBe(false)
  })

  it('maps English workflow / overlay ids to method-* catalog members', () => {
    expect(resolveInversionCatalogId('omega_sf_fenkuai_fy_online')).toBe(
      'method-fy-omega-doy-dynamic',
    )
    expect(resolveInversionCatalogId('omega_sf_fenkuai_smap_single')).toBe(
      'method-smap-omega-doy-dynamic',
    )
    expect(resolveInversionCatalogId('imported-omega_sf_fenkuai_smap_online-00')).toBe(
      'method-smap-omega-doy-dynamic',
    )
    expect(resolveInversionCatalogId('method-fy-omega-doy-dynamic')).toBe(
      'method-fy-omega-doy-dynamic',
    )
    expect(resolveInversionCatalogId('weather-wind')).toBe('weather-wind')
  })

  it('sanitizes run group titles that leak English technical ids', () => {
    expect(sanitizeRunGroupTitle('omega_sf_fenkuai_smap_online')).toBe('反演产物')
    expect(sanitizeRunGroupTitle('SMAP 动态散射约束产品')).toBe('SMAP 动态散射约束产品')
    expect(sanitizeRunGroupTitle('')).toBe('反演产物')
    expect(sanitizeRunGroupTitle(null, '自定义兜底')).toBe('自定义兜底')
  })
})
