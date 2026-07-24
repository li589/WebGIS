import { describe, expect, it, vi } from 'vitest'

import { createWeatherOverlayRuntimeOrchestrator } from './weather-overlay-runtime-orchestrator'

describe('weather-overlay-runtime-orchestrator', () => {
  it('orchestrates prune, reconcile, and render for resolved weather overlay states', () => {
    const targetStates = [
      {
        catalogId: 'weather.wind',
        geojsonUrl: null,
        geojsonData: null,
        cogPreviewUrl: null,
        cogBbox: null,
        renderHint: {
          paint_mode: 'particle_flow',
          palette: 'viridis',
          primary_metric: 'wind_speed_10m',
          unit_label: 'm/s',
          opacity: 1,
          legend_ticks: [],
          notes: [],
          layer_id: 'weather.wind',
        },
        opacity: 1,
      },
      {
        catalogId: 'weather.temp',
        geojsonUrl: '/tiles/temp.json',
        geojsonData: null,
        cogPreviewUrl: null,
        cogBbox: null,
        renderHint: {
          paint_mode: 'grid_fill',
          palette: 'magma',
          primary_metric: 'temperature_2m',
          unit_label: 'C',
          opacity: 1,
          legend_ticks: [],
          notes: [],
          layer_id: 'weather.temp',
        },
        opacity: 0.8,
      },
    ] as any

    const session = {
      renderedCatalogIds: new Set(['weather.old']),
      markRendered: vi.fn(),
      removeCatalogOverlay: vi.fn(),
    }

    const pruneStale = vi.fn()
    const reconcileParticleFlow = vi.fn()
    const createOverlayServices = vi.fn(() => ({
      syncWeatherCogOverlay: vi.fn(),
      syncWeatherGridFillOverlay: vi.fn(),
      syncWeatherHeatmapOverlay: vi.fn(),
      syncWeatherPointOverlay: vi.fn(),
      syncWindParticleFlow: vi.fn(),
      syncScalarFieldWebGL: vi.fn(() => false),
    }))
    const createRenderContext = vi.fn(() => ({ context: true }) as any)
    const renderBatch = vi.fn()

    const orchestrator = createWeatherOverlayRuntimeOrchestrator({
      map: {} as any,
      resolver: { resolveStates: () => targetStates },
      session: session as any,
      windParticleController: {} as any,
      getEnabledParticleFlowCatalogId: () => 'weather.wind',
      getSyncWeatherToken: () => 42,
      debugLog: vi.fn(),
      dependencies: {
        pruneStale,
        reconcileParticleFlow,
        createOverlayServices,
        createRenderContext,
        renderBatch,
      },
    })

    orchestrator.sync(7)

    expect(pruneStale).toHaveBeenCalledTimes(1)
    expect(Array.from(pruneStale.mock.calls[0][1] as Set<string>)).toEqual([
      'weather.wind',
      'weather.temp',
    ])
    expect(reconcileParticleFlow).toHaveBeenCalledWith({
      enabledParticleFlowCatalogId: 'weather.wind',
      targetCatalogIds: expect.any(Set),
      windParticleController: {},
      removeCatalogOverlay: session.removeCatalogOverlay,
    })
    expect(createOverlayServices).toHaveBeenCalledTimes(1)
    expect(createRenderContext).toHaveBeenCalledWith({
      enabledParticleFlowCatalogId: 'weather.wind',
      markRendered: session.markRendered,
      ...createOverlayServices.mock.results[0].value,
    })
    expect(renderBatch).toHaveBeenCalledWith({
      targetStates,
      overlayToken: 7,
      getSyncWeatherToken: expect.any(Function),
      renderContext: { context: true },
    })
  })
})
