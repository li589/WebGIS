interface DisposableResource {
  dispose: () => void
}

interface RemovableMapInstance {
  remove: () => void
}

interface MapCanvasTeardownResources {
  mapStagePresentationModule: DisposableResource | null
  basemapModule: DisposableResource | null
  adminBoundaryModule: unknown | null
  selectedLayerFocusModule: DisposableResource | null
  mapInteractionModule: DisposableResource | null
  mapCanvasRuntimeModule: DisposableResource | null
  hotspotPinsModule: DisposableResource | null
  weatherOverlayModule: DisposableResource | null
  map: RemovableMapInstance | null
}

export interface MapCanvasTeardownBinder {
  dispose: () => void
}

interface CreateMapCanvasTeardownBinderOptions {
  getResources: () => MapCanvasTeardownResources
  clearResources: () => void
  getOverlayImageModule?: () => DisposableResource | null
}

export function createMapCanvasTeardownBinder(
  options: CreateMapCanvasTeardownBinderOptions,
): MapCanvasTeardownBinder {
  function dispose() {
    const resources = options.getResources()

    resources.mapStagePresentationModule?.dispose()
    resources.basemapModule?.dispose()
    resources.selectedLayerFocusModule?.dispose()
    resources.mapInteractionModule?.dispose()
    resources.mapCanvasRuntimeModule?.dispose()
    resources.hotspotPinsModule?.dispose()
    resources.weatherOverlayModule?.dispose()
    options.getOverlayImageModule?.()?.dispose()
    resources.map?.remove()

    options.clearResources()
  }

  return {
    dispose,
  }
}
