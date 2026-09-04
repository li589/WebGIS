import { describe, expect, it } from 'vitest'

import { PRODUCT_TAG_MERGE_RULES, mergeProductTag } from '@/stores/layers/layer-naming'
import { normalizeProductTag } from '@/stores/layers/result-adapter'

describe('productTag 归并规则表（P2-A 表化回归锁，2026-08-24）', () => {
  it('OMEGA 变体全归并（含 BLOCK/PIXEL/连接符变体）', () => {
    expect(mergeProductTag('OMEGA')).toBe('OMEGA')
    expect(mergeProductTag('OMEGA_BLOCK')).toBe('OMEGA')
    expect(mergeProductTag('OMEGA_BLOCK_20251201')).toBe('OMEGA')
    expect(mergeProductTag('OMEGA_PIXEL')).toBe('OMEGA')
    expect(mergeProductTag('FY_DUAL_OMEGA')).toBe('OMEGA')
    expect(mergeProductTag('SMAP-OMEGA')).toBe('OMEGA')
  })

  it('SM/VOD 精确 tag 透传（LEGACY 退役 2026-08-24：变体后缀归并已删）', () => {
    // 现行种子产物 tag 为精确值 SM/VOD/OMEGA（extra.outputs），透传即可
    expect(mergeProductTag('SM')).toBe('SM')
    expect(mergeProductTag('VOD')).toBe('VOD')
    // 旧 run 变体后缀（XX_SM/XX-VOD）不再归并——退役决策见 layer-naming 注释
    expect(mergeProductTag('Smap_SM')).toBe('Smap_SM')
    expect(mergeProductTag('FY-VOD')).toBe('FY-VOD')
  })

  it('NDVI 变体全归并（含 植被指数 / DAILY_NDVI 变体）', () => {
    expect(mergeProductTag('NDVI')).toBe('NDVI')
    expect(mergeProductTag('植被指数 NDVI')).toBe('NDVI')
    expect(mergeProductTag('植被指数')).toBe('NDVI')
    expect(mergeProductTag('DAILY_NDVI')).toBe('NDVI')
    expect(mergeProductTag('NDVI_16DAY_RASTER')).toBe('NDVI')
    expect(normalizeProductTag('Algorithm Map Layer: 植被指数 NDVI')).toBe('NDVI')
  })

  it('未知 tag 透传（不误归并）', () => {
    expect(mergeProductTag('RESULT')).toBe('RESULT')
    expect(mergeProductTag('SMAP_L3')).toBe('SMAP_L3')
  })

  it('normalizeProductTag 行为等价（前缀剥除 + 归并 + 大写化）', () => {
    expect(normalizeProductTag('Algorithm Map Layer: OMEGA_BLOCK')).toBe('OMEGA')
    expect(normalizeProductTag('  omega_pixel ')).toBe('OMEGA')
    expect(normalizeProductTag('Algorithm Output: landcover_025.tif')).toBe('LANDCOVER_025.TIF')
    expect(normalizeProductTag(null)).toBe('')
    expect(normalizeProductTag('')).toBe('')
  })

  it('规则表仅含现行归并（OMEGA 与 NDVI），无 LEGACY 残留', () => {
    expect(PRODUCT_TAG_MERGE_RULES.map((r) => r.canonical)).toEqual(['OMEGA', 'NDVI'])
  })
})
