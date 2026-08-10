import { describe, expect, it } from 'vitest'
import {
  collectLayerDisplayNameKeys,
  isDefaultProductDisplayName,
  isRuntimeCatalogId,
  MAX_LAYER_DISPLAY_NAME_LENGTH,
  normalizeDisplayName,
} from '@/stores/layers/layer-naming'

describe('layer-naming', () => {
  it('detects runtime catalog ids', () => {
    expect(isRuntimeCatalogId('wf-run-g1-sm')).toBe(true)
    expect(isRuntimeCatalogId('wf-out-123-abc')).toBe(true)
    expect(isRuntimeCatalogId('imported-deadbeef')).toBe(true)
    expect(isRuntimeCatalogId('wind-field')).toBe(false)
    expect(isRuntimeCatalogId('ndvi')).toBe(false)
  })

  it('normalizes display names', () => {
    expect(normalizeDisplayName('  SM  ')).toBe('SM')
    expect(normalizeDisplayName('a   b')).toBe('a b')
    expect(normalizeDisplayName('   ')).toBeNull()
    expect(normalizeDisplayName('x'.repeat(MAX_LAYER_DISPLAY_NAME_LENGTH + 5))?.length).toBe(
      MAX_LAYER_DISPLAY_NAME_LENGTH,
    )
  })

  it('recognizes default and legacy product labels', () => {
    expect(isDefaultProductDisplayName('SM', 'SM', 'SM')).toBe(true)
    expect(isDefaultProductDisplayName('SM（土壤湿度）', 'SM', 'SM')).toBe(true)
    expect(isDefaultProductDisplayName('SM（部分）', 'SM', 'SM')).toBe(true)
    expect(isDefaultProductDisplayName('ω', 'OMEGA', 'ω')).toBe(true)
    expect(isDefaultProductDisplayName('我的反演层', 'SM', 'SM')).toBe(false)
  })

  it('collects display-name persistence keys', () => {
    expect(
      collectLayerDisplayNameKeys({
        instanceId: 'inst-1',
        catalogId: 'wind-field',
        importedRaster: { overlayLayerId: 'ov-1' },
      }).sort(),
    ).toEqual(['inst-1', 'ov-1', 'wind-field'].sort())
  })
})
