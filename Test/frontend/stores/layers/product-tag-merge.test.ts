import { describe, expect, it } from 'vitest'

import {
  LEGACY_RESTORE_TAGS,
  PRODUCT_TAG_MERGE_RULES,
  mergeProductTag,
} from '@/stores/layers/layer-naming'
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

  it('SM/VOD 后缀变体归并', () => {
    expect(mergeProductTag('SM')).toBe('SM')
    expect(mergeProductTag('VOD')).toBe('VOD')
    expect(mergeProductTag('Smap_SM')).toBe('SM')
    expect(mergeProductTag('FY-VOD')).toBe('VOD')
  })

  it('未知 tag 透传（不误归并）', () => {
    expect(mergeProductTag('RESULT')).toBe('RESULT')
    expect(mergeProductTag('NDVI')).toBe('NDVI')
    expect(mergeProductTag('SMAP_L3')).toBe('SMAP_L3')
  })

  it('normalizeProductTag 行为等价（前缀剥除 + 归并 + 大写化）', () => {
    expect(normalizeProductTag('Algorithm Map Layer: OMEGA_BLOCK')).toBe('OMEGA')
    expect(normalizeProductTag('  omega_pixel ')).toBe('OMEGA')
    expect(normalizeProductTag('Algorithm Output: landcover_025.tif')).toBe('LANDCOVER_025.TIF')
    expect(normalizeProductTag(null)).toBe('')
    expect(normalizeProductTag('')).toBe('')
  })

  it('规则表与 LEGACY 三件套一致（退役期 2026-10-23 见 layer-naming 注释）', () => {
    const canonicals = PRODUCT_TAG_MERGE_RULES.map((r) => r.canonical)
    expect([...LEGACY_RESTORE_TAGS].sort()).toEqual([...new Set(canonicals)].sort())
  })
})
