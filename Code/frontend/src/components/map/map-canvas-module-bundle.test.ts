import { describe, expect, it, vi } from 'vitest'

import { createMapCanvasModuleBundle } from './map-canvas-module-bundle'

describe('map-canvas-module-bundle', () => {
  it('composes map canvas modules and wires runtime callbacks through created modules', () => {
    const basemapModule = {
      scheduleTileSourceSwitch: vi.fn(),
    }
    const adminBoundaryModule = {}
    const weatherOverlayModule = {}
    const hotspotPinsModule = {}
    const mapInteractionModule = {
      applyInteractionMode: vi.fn(),
    }
    const runtimeOptions: {
      onTileSourceChange?: (sourceId: 'esri-street') => void
      onInteractionModeChange?: () => void
      onAdminBoundaryOverlayChange?: () => void
    } = {}
    const selectedLayerFocusModule = {}
    const syncAdminOverlay = vi.fn()

    const bundle = createMapCanvasModuleBundle({
      map: {} as any,
      layersStore: {
        activeLayersDisplay: [],
        particleFlowCatalogId: null,
        isWeatherEngineLayer: () => false,
        setMapViewport: vi.fn(),
      },
      weatherTileManager: {
        getMergedGeojsonForViewport: () => null,
        dataVersion: 1,
      },
      getCurrentHour: () => 12,
      getMapReady: () => true,
      getTileConfig: () => undefined,
      getCurrentTileSourceId: () => 'esri-street',
      setTileLoadFailed: vi.fn(),
      setTileFailedProvider: vi.fn(),
      setSourceTransitioning: vi.fn(),
      onAfterSourceSwitch: vi.fn(),
      setLoadingLabel: vi.fn(),
      getSelectedLayer: () => null,
      getSelectedHotspotId: () => null,
      setSelectedHotspotId: vi.fn(),
      emitVisibleHotspotsChange: vi.fn(),
      emitHotspotSelect: vi.fn(),
      setHotspotPins: vi.fn(),
      getInteractionMode: () => 'move',
      setIsMapInteracting: vi.fn(),
      scheduleHotspotSync: vi.fn(),
      emitMapPointSelect: vi.fn(),
      getHasAdminBoundary: () => false,
      getAdminBoundaryOpacity: () => 1,
      syncAdminOverlay,
      debugLog: vi.fn(),
      weatherDebounceMs: 200,
      dependencies: {
        createBasemapModule: vi.fn(() => basemapModule as any),
        createAdminBoundaryModule: vi.fn(() => adminBoundaryModule as any),
        createMapCanvasWeatherOverlayModule: vi.fn(() => weatherOverlayModule as any),
        createHotspotPinsModule: vi.fn(() => hotspotPinsModule as any),
        createMapInteractionModule: vi.fn(() => mapInteractionModule as any),
        createMapCanvasRuntimeModule: vi.fn((options) => {
          runtimeOptions.onTileSourceChange = options.onTileSourceChange
          runtimeOptions.onInteractionModeChange = options.onInteractionModeChange
          runtimeOptions.onAdminBoundaryOverlayChange = options.onAdminBoundaryOverlayChange
          return {} as any
        }),
        createSelectedLayerFocusModule: vi.fn(() => selectedLayerFocusModule as any),
      },
    })

    runtimeOptions.onTileSourceChange?.('esri-street')
    runtimeOptions.onInteractionModeChange?.()
    runtimeOptions.onAdminBoundaryOverlayChange?.()

    expect(bundle.basemapModule).toBe(basemapModule)
    expect(bundle.adminBoundaryModule).toBe(adminBoundaryModule)
    expect(bundle.weatherOverlayModule).toBe(weatherOverlayModule)
    expect(bundle.hotspotPinsModule).toBe(hotspotPinsModule)
    expect(bundle.mapInteractionModule).toBe(mapInteractionModule)
    expect(bundle.selectedLayerFocusModule).toBe(selectedLayerFocusModule)
    expect(basemapModule.scheduleTileSourceSwitch).toHaveBeenCalledWith('esri-street')
    expect(mapInteractionModule.applyInteractionMode).toHaveBeenCalledTimes(1)
    expect(syncAdminOverlay).toHaveBeenCalledTimes(1)
  })
})
