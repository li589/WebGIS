import { describe, expect, it } from 'vitest'
import {
  DEFAULT_LAYER_OVERLAY_IDS,
  isDefaultLayerOverlayId,
} from '@/stores/layers/default-layer-ids'

describe('default-layer-ids', () => {
  it('默认四组共 12 个成员，编号不重复', () => {
    expect(DEFAULT_LAYER_OVERLAY_IDS).toHaveLength(12)
    expect(new Set(DEFAULT_LAYER_OVERLAY_IDS).size).toBe(12)
  })

  it('识别默认图层成员（风云/SMAP 的平均+动态）', () => {
    // 风云平均 SM、SMAP 平均 SM、风云动态 ω、SMAP 动态 VOD
    for (const id of [
      'imported-55359b8ecd3d',
      'imported-38993117b963',
      'imported-c6c55b8a9f4e',
      'imported-5427e1020d63',
    ]) {
      expect(isDefaultLayerOverlayId(id)).toBe(true)
    }
  })

  it('非默认图层（含已退役的 SMAP 逐日目录）返回 false', () => {
    expect(isDefaultLayerOverlayId('imported-136c60293bbf')).toBe(false)
    expect(isDefaultLayerOverlayId('imported-169f6402583c')).toBe(false)
    expect(isDefaultLayerOverlayId('some-random-id')).toBe(false)
    expect(isDefaultLayerOverlayId(undefined)).toBe(false)
    expect(isDefaultLayerOverlayId(null)).toBe(false)
    expect(isDefaultLayerOverlayId('')).toBe(false)
    expect(isDefaultLayerOverlayId('  ')).toBe(false)
  })
})
