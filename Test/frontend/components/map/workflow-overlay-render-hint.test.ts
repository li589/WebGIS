import { describe, expect, it } from 'vitest'

import type { ActiveLayerDisplay } from '@/stores/layers/types'

/**
 * Mirrors weather-overlay-coordinator buildWorkflowOverlayState renderHint selection.
 */
function pickWorkflowRenderHint(layer: Pick<ActiveLayerDisplay, 'renderHint' | 'jobLayer'>) {
  return layer.renderHint ?? layer.jobLayer?.mapLayerPayload?.renderHint ?? null
}

describe('workflow overlay renderHint bridge', () => {
  it('prefers display renderHint with paletteOverride over raw job payload', () => {
    const layer = {
      renderHint: {
        layer_id: 'method-smap-omega-doy-dynamic',
        paint_mode: 'grid_fill',
        palette: 'cividis',
        primary_metric: 'value',
        unit_label: '',
        opacity: 0.8,
        legend_ticks: [0, 1],
        notes: [],
      },
      jobLayer: {
        mapLayerPayload: {
          renderHint: {
            layer_id: 'method-smap-omega-doy-dynamic',
            paint_mode: 'grid_fill',
            palette: 'viridis',
            primary_metric: 'value',
            unit_label: '',
            opacity: 0.8,
            legend_ticks: [0, 1],
            notes: [],
          },
        },
      },
    } as unknown as ActiveLayerDisplay

    expect(pickWorkflowRenderHint(layer)?.palette).toBe('cividis')
  })

  it('falls back to job payload when display hint missing', () => {
    const layer = {
      renderHint: undefined,
      jobLayer: {
        mapLayerPayload: {
          renderHint: {
            layer_id: 'x',
            paint_mode: 'grid_fill',
            palette: 'ylgnbu',
            primary_metric: 'value',
            unit_label: '',
            opacity: 0.7,
            legend_ticks: [0, 1],
            notes: [],
          },
        },
      },
    } as unknown as ActiveLayerDisplay

    expect(pickWorkflowRenderHint(layer)?.palette).toBe('ylgnbu')
  })
})
