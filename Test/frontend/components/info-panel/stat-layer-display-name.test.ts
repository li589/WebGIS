import { describe, expect, it } from 'vitest'
import {
  looksLikeLayerId,
  resolveStatLayerDisplayName,
} from '@/components/info-panel/stat-layer-display-name'

describe('stat-layer-display-name', () => {
  it('detects common layer-id shapes', () => {
    expect(looksLikeLayerId('imported-abc')).toBe(true)
    expect(looksLikeLayerId('wf-run-1')).toBe(true)
    expect(looksLikeLayerId('ref-fy-tb-202512-mwri')).toBe(true)
    expect(looksLikeLayerId('method-smap-omega')).toBe(true)
    expect(looksLikeLayerId('Soil_Moisture')).toBe(true)
    expect(looksLikeLayerId('土壤水分')).toBe(false)
    expect(looksLikeLayerId('SMAP L3 Dec 2025')).toBe(false)
  })

  it('prefers activity-layer mapping over backend name', () => {
    const map = new Map([['imported-1', '风云亮温']])
    expect(
      resolveStatLayerDisplayName({
        layerId: 'imported-1',
        layerName: 'imported-1',
        displayNameByOverlayId: map,
      }),
    ).toBe('风云亮温')
  })

  it('does not fall back to id-like backend names', () => {
    expect(
      resolveStatLayerDisplayName({
        layerId: 'imported-xyz',
        layerName: 'imported-xyz',
        displayNameByOverlayId: new Map(),
      }),
    ).toBe('未命名图层')
  })

  it('keeps human backend names when unmapped', () => {
    expect(
      resolveStatLayerDisplayName({
        layerId: 'some-id',
        layerName: 'SMAP 土壤水分',
        displayNameByOverlayId: new Map(),
      }),
    ).toBe('SMAP 土壤水分')
  })
})
