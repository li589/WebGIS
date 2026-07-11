type MapInstance = import('maplibre-gl').Map

export interface MapCanvasExposeBridge {
  getMapStageElement: () => HTMLElement | null
  captureMapCanvas: () => string | null
}

interface CreateMapCanvasExposeBridgeOptions {
  getMapStageElement: () => HTMLElement | null
  getMap: () => MapInstance | null
  dependencies?: {
    warn?: (message?: unknown, ...optionalParams: unknown[]) => void
  }
}

export function createMapCanvasExposeBridge(
  options: CreateMapCanvasExposeBridgeOptions,
): MapCanvasExposeBridge {
  const warnImpl = options.dependencies?.warn ?? console.warn

  function captureMapCanvas(): string | null {
    const map = options.getMap()
    if (!map) return null

    try {
      ;(map as MapInstance & { render: () => void }).render()
      return map.getCanvas().toDataURL('image/png')
    } catch (error) {
      warnImpl('[MapCanvas] captureMapCanvas failed:', error)
      return null
    }
  }

  return {
    getMapStageElement: options.getMapStageElement,
    captureMapCanvas,
  }
}
