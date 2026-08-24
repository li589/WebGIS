import { describe, expect, it } from 'vitest'
import {
  collectLayerDisplayNameKeys,
  isDefaultProductDisplayName,
  isRuntimeCatalogId,
  MAX_LAYER_DISPLAY_NAME_LENGTH,
  normalizeDisplayName,
  resolveExportBasename,
  resolveLayerDisplayLabel,
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

  it('recognizes default product labels（LEGACY 旧长标签已退役 2026-08-24）', () => {
    expect(isDefaultProductDisplayName('SM', 'SM', 'SM')).toBe(true)
    // 旧长标签「SM（土壤湿度）」不再视为默认名——LEGACY 表已删，
    // 退役后旧持久化名视为用户自定义名，不再被渐进失败路径覆盖
    expect(isDefaultProductDisplayName('SM（土壤湿度）', 'SM', 'SM')).toBe(false)
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

  it('resolves display label fallback chain', () => {
    expect(
      resolveLayerDisplayLabel({
        catalogDisplayName: '植被指数 NDVI',
        datasetKey: 'ndvi_viirs_9km',
        catalogId: 'ndvi',
      }),
    ).toBe('植被指数 NDVI')
    expect(
      resolveLayerDisplayLabel({
        datasetKey: 'ndvi_viirs_9km',
        catalogId: 'ndvi',
      }),
    ).toBe('ndvi_viirs_9km')
    expect(resolveLayerDisplayLabel({ catalogId: 'imported-abc' })).toBe('imported-abc')
    expect(resolveLayerDisplayLabel({})).toBe('未命名图层')
  })

  it('resolves export basename preferring machine ids', () => {
    expect(
      resolveExportBasename({
        layerId: 'ref-smap-sm-202512-l3',
        displayName: 'SMAP L3 土壤水分',
      }),
    ).toBe('ref-smap-sm-202512-l3')
    expect(
      resolveExportBasename({
        catalogId: 'imported-deadbeef',
        displayName: '我的矢量',
      }),
    ).toBe('imported-deadbeef')
  })
})
