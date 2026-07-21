import type { WatchStopHandle } from 'vue'

import type { TileSourceId } from '../../services/api-config'
import type { InteractionMode } from '../../stores/ui'
import {
  watchAdminBoundaryOverlay,
  watchBasemapSource,
  watchInteractionMode,
  watchMeasureState,
} from './map-canvas-runtime-watcher'

export interface MapCanvasRuntimeModule {
  setupWatchers: () => void
  dispose: () => void
}

interface CreateMapCanvasRuntimeModuleOptions {
  getTileSourceId: () => TileSourceId
  getMapReady: () => boolean
  getInteractionMode: () => InteractionMode
  getHasAdminBoundary: () => boolean
  getAdminBoundaryOpacity: () => number
  getMeasureSyncKey: () => string
  onTileSourceChange: (sourceId: TileSourceId) => void
  onInteractionModeChange: () => void
  onAdminBoundaryOverlayChange: () => void
  onMeasureStateChange: () => void
  dependencies?: {
    watchBasemapSource?: typeof watchBasemapSource
    watchInteractionMode?: typeof watchInteractionMode
    watchAdminBoundaryOverlay?: typeof watchAdminBoundaryOverlay
    watchMeasureState?: typeof watchMeasureState
  }
}

export function createMapCanvasRuntimeModule(
  options: CreateMapCanvasRuntimeModuleOptions,
): MapCanvasRuntimeModule {
  const watchBasemapSourceImpl = options.dependencies?.watchBasemapSource ?? watchBasemapSource
  const watchInteractionModeImpl = options.dependencies?.watchInteractionMode ?? watchInteractionMode
  const watchAdminBoundaryOverlayImpl =
    options.dependencies?.watchAdminBoundaryOverlay ?? watchAdminBoundaryOverlay
  const watchMeasureStateImpl = options.dependencies?.watchMeasureState ?? watchMeasureState

  const stopHandles: WatchStopHandle[] = []

  function setupWatchers() {
    if (stopHandles.length > 0) return

    stopHandles.push(
      watchBasemapSourceImpl({
        getTileSourceId: options.getTileSourceId,
        getMapReady: options.getMapReady,
        onTileSourceChange: options.onTileSourceChange,
      }),
    )

    stopHandles.push(
      watchInteractionModeImpl({
        getInteractionMode: options.getInteractionMode,
        getMapReady: options.getMapReady,
        onInteractionModeChange: options.onInteractionModeChange,
      }),
    )

    stopHandles.push(
      watchAdminBoundaryOverlayImpl({
        getHasAdminBoundary: options.getHasAdminBoundary,
        getAdminBoundaryOpacity: options.getAdminBoundaryOpacity,
        getMapReady: options.getMapReady,
        onAdminBoundaryOverlayChange: options.onAdminBoundaryOverlayChange,
      }),
    )

    stopHandles.push(
      watchMeasureStateImpl({
        getMeasureSyncKey: options.getMeasureSyncKey,
        getMapReady: options.getMapReady,
        onMeasureStateChange: options.onMeasureStateChange,
      }),
    )
  }

  function dispose() {
    while (stopHandles.length > 0) {
      stopHandles.pop()?.()
    }
  }

  return {
    setupWatchers,
    dispose,
  }
}
