import { describe, expect, it, vi } from 'vitest'

import { createMapCanvasTeardownBinder } from './map-canvas-teardown-binder'

describe('map-canvas-teardown-binder', () => {
  it('disposes modules, removes the map, and clears references', () => {
    const resources = {
      mapStagePresentationModule: { dispose: vi.fn() },
      basemapModule: { dispose: vi.fn() },
      adminBoundaryModule: {},
      selectedLayerFocusModule: { dispose: vi.fn() },
      mapInteractionModule: { dispose: vi.fn() },
      mapCanvasRuntimeModule: { dispose: vi.fn() },
      hotspotPinsModule: { dispose: vi.fn() },
      weatherOverlayModule: { dispose: vi.fn() },
      map: { remove: vi.fn() },
    }
    const clearResources = vi.fn()

    const binder = createMapCanvasTeardownBinder({
      getResources: () => resources,
      clearResources,
    })

    binder.dispose()

    expect(resources.mapStagePresentationModule.dispose).toHaveBeenCalledTimes(1)
    expect(resources.basemapModule.dispose).toHaveBeenCalledTimes(1)
    expect(resources.selectedLayerFocusModule.dispose).toHaveBeenCalledTimes(1)
    expect(resources.mapInteractionModule.dispose).toHaveBeenCalledTimes(1)
    expect(resources.mapCanvasRuntimeModule.dispose).toHaveBeenCalledTimes(1)
    expect(resources.hotspotPinsModule.dispose).toHaveBeenCalledTimes(1)
    expect(resources.weatherOverlayModule.dispose).toHaveBeenCalledTimes(1)
    expect(resources.map.remove).toHaveBeenCalledTimes(1)
    expect(clearResources).toHaveBeenCalledTimes(1)
  })

  it('disposes overlay image module when provided', () => {
    const overlayImageModule = { dispose: vi.fn() }
    const clearResources = vi.fn()
    const binder = createMapCanvasTeardownBinder({
      getResources: () => ({
        mapStagePresentationModule: null,
        basemapModule: null,
        adminBoundaryModule: null,
        selectedLayerFocusModule: null,
        mapInteractionModule: null,
        mapCanvasRuntimeModule: null,
        hotspotPinsModule: null,
        weatherOverlayModule: null,
        map: null,
      }),
      clearResources,
      getOverlayImageModule: () => overlayImageModule,
    })

    binder.dispose()

    expect(overlayImageModule.dispose).toHaveBeenCalledTimes(1)
    expect(clearResources).toHaveBeenCalledTimes(1)
  })

  it('handles already-cleared resources', () => {
    const clearResources = vi.fn()
    const binder = createMapCanvasTeardownBinder({
      getResources: () => ({
        mapStagePresentationModule: null,
        basemapModule: null,
        adminBoundaryModule: null,
        selectedLayerFocusModule: null,
        mapInteractionModule: null,
        mapCanvasRuntimeModule: null,
        hotspotPinsModule: null,
        weatherOverlayModule: null,
        map: null,
      }),
      clearResources,
    })

    binder.dispose()

    expect(clearResources).toHaveBeenCalledTimes(1)
  })
})
