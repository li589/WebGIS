import { describe, expect, it } from 'vitest'

import {
  buildLegendHintFromOverlayMeta,
  buildOverlayStyleQuery,
  hasRenderableSymbology,
  isMapLinkedPalette,
  resolveEffectivePalette,
  resolveStyleRenderHint,
  resolveSymbologyColors,
} from '@/components/map/layer-symbology'

describe('layer-symbology', () => {
  it('resolves palette colors from renderHint', () => {
    const colors = resolveSymbologyColors({
      renderHint: { palette: 'wind-blue' },
    })
    expect(colors.length).toBeGreaterThan(2)
    expect(colors[0]).toMatch(/^#/)
  })

  it('applies paletteOverride over overlay meta', () => {
    const colors = resolveSymbologyColors({
      paletteOverride: 'reds',
      overlayMeta: { palette: 'viridis' },
    })
    const overrideColors = resolveSymbologyColors({ renderHint: { palette: 'reds' } })
    expect(colors).toEqual(overrideColors)
  })

  it('resolveEffectivePalette prefers override', () => {
    expect(
      resolveEffectivePalette({
        paletteOverride: 'blues',
        renderHintPalette: 'wind-blue',
        overlayMetaPalette: 'viridis',
      }),
    ).toBe('blues')
  })

  it('builds overlay legend hint when palette present', () => {
    const hint = buildLegendHintFromOverlayMeta({
      palette: 'viridis',
      vmin: 0,
      vmax: 100,
      unit: 'm',
    })
    expect(hint?.palette).toBe('viridis')
    expect(hint?.legend_ticks).toEqual([0, 50, 100])
    expect(hint?.paint_mode).toBe('raster_legend')
  })

  it('resolveStyleRenderHint merges override onto renderHint', () => {
    const hint = resolveStyleRenderHint({
      paletteOverride: 'spectral',
      renderHint: {
        layer_id: 'wind-field',
        paint_mode: 'fill',
        palette: 'wind-blue',
        primary_metric: 'wind_speed_10m',
        unit_label: 'm/s',
        opacity: 0.8,
        legend_ticks: [0, 10, 20],
        notes: [],
      },
    })
    expect(hint?.palette).toBe('spectral')
  })

  it('marks overlay-only palette as not map-linked unless supports_recolor', () => {
    expect(isMapLinkedPalette({ hasRenderHint: false })).toBe(false)
    expect(isMapLinkedPalette({ hasRenderHint: true })).toBe(true)
    expect(isMapLinkedPalette({ hasRenderHint: true, isImportedRaster: true })).toBe(false)
    expect(
      isMapLinkedPalette({
        hasRenderHint: false,
        isImportedRaster: true,
        supportsRecolor: true,
      }),
    ).toBe(true)
  })

  it('buildOverlayStyleQuery encodes palette and nodata', () => {
    const qs = buildOverlayStyleQuery({
      palette: 'viridis',
      vmin: 0,
      vmax: 1,
      nodataMode: 'solid',
      nodataColor: '#ff0000',
      forceStyle: true,
    })
    expect(qs).toContain('palette=viridis')
    expect(qs).toContain('min_value=0')
    expect(qs).toContain('max_value=1')
    expect(qs).toContain('nodata_mode=solid')
    expect(qs).toContain('nodata_color')
  })

  it('hides symbology for imported / admin layers', () => {
    expect(
      hasRenderableSymbology({
        isImported: true,
        renderHint: { palette: 'wind-blue' } as any,
      }),
    ).toBe(false)
    expect(
      hasRenderableSymbology({
        renderHint: { palette: 'wind-blue' } as any,
      }),
    ).toBe(true)
  })
})
