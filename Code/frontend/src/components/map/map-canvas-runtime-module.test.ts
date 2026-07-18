import { describe, expect, it, vi } from 'vitest'

import { createMapCanvasRuntimeModule } from './map-canvas-runtime-module'

describe('map-canvas-runtime-module', () => {
  it('composes runtime watchers and tears them down', () => {
    const stopBasemap = vi.fn()
    const stopInteraction = vi.fn()
    const stopAdminBoundary = vi.fn()
    const stopMeasure = vi.fn()
    let triggerTileSourceChange: ((sourceId: 'esri-street') => void) | null = null
    let triggerInteractionModeChange: (() => void) | null = null
    let triggerAdminBoundaryOverlayChange: (() => void) | null = null
    const onTileSourceChange = vi.fn()
    const onInteractionModeChange = vi.fn()
    const onAdminBoundaryOverlayChange = vi.fn()
    const onMeasureStateChange = vi.fn()

    const module = createMapCanvasRuntimeModule({
      getTileSourceId: () => 'esri-street',
      getMapReady: () => true,
      getInteractionMode: () => 'move',
      getHasAdminBoundary: () => false,
      getAdminBoundaryOpacity: () => 1,
      getMeasureSyncKey: () => 'measure-key',
      onTileSourceChange,
      onInteractionModeChange,
      onAdminBoundaryOverlayChange,
      onMeasureStateChange,
      dependencies: {
        watchBasemapSource: vi.fn((options) => {
          triggerTileSourceChange = options.onTileSourceChange
          return stopBasemap
        }),
        watchInteractionMode: vi.fn((options) => {
          triggerInteractionModeChange = options.onInteractionModeChange
          return stopInteraction
        }),
        watchAdminBoundaryOverlay: vi.fn((options) => {
          triggerAdminBoundaryOverlayChange = options.onAdminBoundaryOverlayChange
          return stopAdminBoundary
        }),
        watchMeasureState: vi.fn(() => stopMeasure),
      },
    })

    module.setupWatchers()

    expect(triggerTileSourceChange).not.toBeNull()
    expect(triggerInteractionModeChange).not.toBeNull()
    expect(triggerAdminBoundaryOverlayChange).not.toBeNull()

    triggerTileSourceChange!('esri-street')
    triggerInteractionModeChange!()
    triggerAdminBoundaryOverlayChange!()

    expect(onTileSourceChange).toHaveBeenCalledWith('esri-street')
    expect(onInteractionModeChange).toHaveBeenCalledTimes(1)
    expect(onAdminBoundaryOverlayChange).toHaveBeenCalledTimes(1)

    module.dispose()

    expect(stopBasemap).toHaveBeenCalledTimes(1)
    expect(stopInteraction).toHaveBeenCalledTimes(1)
    expect(stopAdminBoundary).toHaveBeenCalledTimes(1)
    expect(stopMeasure).toHaveBeenCalledTimes(1)
  })

  it('does not setup runtime watchers twice', () => {
    const watchBasemapSource = vi.fn(() => vi.fn())
    const watchInteractionMode = vi.fn(() => vi.fn())
    const watchAdminBoundaryOverlay = vi.fn(() => vi.fn())
    const watchMeasureState = vi.fn(() => vi.fn())

    const module = createMapCanvasRuntimeModule({
      getTileSourceId: () => 'esri-street',
      getMapReady: () => true,
      getInteractionMode: () => 'move',
      getHasAdminBoundary: () => false,
      getAdminBoundaryOpacity: () => 1,
      getMeasureSyncKey: () => 'measure-key',
      onTileSourceChange: vi.fn(),
      onInteractionModeChange: vi.fn(),
      onAdminBoundaryOverlayChange: vi.fn(),
      onMeasureStateChange: vi.fn(),
      dependencies: {
        watchBasemapSource,
        watchInteractionMode,
        watchAdminBoundaryOverlay,
        watchMeasureState,
      },
    })

    module.setupWatchers()
    module.setupWatchers()

    expect(watchBasemapSource).toHaveBeenCalledTimes(1)
    expect(watchInteractionMode).toHaveBeenCalledTimes(1)
    expect(watchAdminBoundaryOverlay).toHaveBeenCalledTimes(1)
    expect(watchMeasureState).toHaveBeenCalledTimes(1)
  })
})
