import { describe, expect, it, vi } from 'vitest'

import { shouldUseSmoothWindOffUnderlay } from './wind-off-underlay'
import { createWeatherOverlayServices } from './weather-overlay-services'
import type { WeatherOverlayState } from './weather-overlay-registry'

function makeState(catalogId = 'temperature'): WeatherOverlayState {
  return {
    catalogId,
    geojsonUrl: null,
    geojsonData: { type: 'FeatureCollection', features: [] },
    cogPreviewUrl: null,
    cogBbox: null,
    renderHint: {
      layer_id: catalogId,
      paint_mode: 'grid_fill',
      primary_metric: 'temperature_2m',
      unit_label: '°C',
      palette: 'thermal-orange',
      opacity: 0.7,
      legend_ticks: [-10, 0, 10, 20],
    },
    opacity: 0.7,
  }
}

describe('wind off underlay mode', () => {
  it('uses smooth scalar only when smooth on and sync available', () => {
    expect(shouldUseSmoothWindOffUnderlay(true, true)).toBe(true)
    expect(shouldUseSmoothWindOffUnderlay(true, false)).toBe(false)
    expect(shouldUseSmoothWindOffUnderlay(false, true)).toBe(false)
  })
})

describe('syncScalarFieldWebGL smooth toggle', () => {
  it('removes WebGL artifacts when smoothRendering is off', () => {
    const removeCatalogArtifacts = vi.fn()
    const sync = vi.fn(() => true)
    const services = createWeatherOverlayServices({
      map: {} as any,
      windParticleController: null,
      scalarFieldController: { removeCatalogArtifacts, sync } as any,
      getSyncWeatherToken: () => 1,
      getEnabledParticleFlowCatalogId: () => null,
      getWindDisplayMode: () => 'off',
      getSmoothRendering: () => false,
    })

    const used = services.syncScalarFieldWebGL(makeState(), 1)
    expect(used).toBe(false)
    expect(removeCatalogArtifacts).toHaveBeenCalledWith('temperature')
    expect(sync).not.toHaveBeenCalled()
  })

  it('keeps WebGL path when smoothRendering is on', () => {
    const removeCatalogArtifacts = vi.fn()
    const sync = vi.fn(() => true)
    const services = createWeatherOverlayServices({
      map: {} as any,
      windParticleController: null,
      scalarFieldController: { removeCatalogArtifacts, sync } as any,
      getSyncWeatherToken: () => 1,
      getEnabledParticleFlowCatalogId: () => null,
      getWindDisplayMode: () => 'off',
      getSmoothRendering: () => true,
    })

    const used = services.syncScalarFieldWebGL(makeState(), 1)
    expect(used).toBe(true)
    expect(sync).toHaveBeenCalled()
    expect(removeCatalogArtifacts).not.toHaveBeenCalled()
  })
})
