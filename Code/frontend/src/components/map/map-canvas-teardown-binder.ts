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
  nonWeatherLayerSyncModule: DisposableResource | null
  // D-2：draw/measure 持有 ResizeObserver/RAF/事件与叠加 canvas，
  // 此前 teardown 不调 dispose → 卸载泄漏（3D 视图切换重建即触发一次）
  drawModule: DisposableResource | null
  measureModule: DisposableResource | null
  map: RemovableMapInstance | null
}

export interface MapCanvasTeardownBinder {
  dispose: () => void
}

interface CreateMapCanvasTeardownBinderOptions {
  getResources: () => MapCanvasTeardownResources
  clearResources: () => void
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
    resources.nonWeatherLayerSyncModule?.dispose()
    // D-2：叠加 canvas 模块的清理须在 map.remove() 之前（释放 RAF/观察器与 DOM）
    resources.drawModule?.dispose()
    resources.measureModule?.dispose()
    resources.map?.remove()

    options.clearResources()
  }

  return {
    dispose,
  }
}
