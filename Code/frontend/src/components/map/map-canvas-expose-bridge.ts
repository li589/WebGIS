type MapInstance = import('maplibre-gl').Map

export interface MapCanvasExposeBridge {
  getMapStageElement: () => HTMLElement | null
  captureMapCanvas: () => string | null
  selectHotspot?: (pinId: string) => void
}

interface CreateMapCanvasExposeBridgeOptions {
  getMapStageElement: () => HTMLElement | null
  getMap: () => MapInstance | null
  selectHotspot?: (pinId: string) => void
  dependencies?: {
    warn?: (message?: unknown, ...optionalParams: unknown[]) => void
  }
}

export function createMapCanvasExposeBridge(
  options: CreateMapCanvasExposeBridgeOptions,
): MapCanvasExposeBridge {
  const warnImpl = options.dependencies?.warn ?? console.warn

  function captureOverlayCanvases(
    stage: HTMLElement,
    targetCtx: CanvasRenderingContext2D,
    scaleX: number,
    scaleY: number,
  ) {
    const selectors = [
      '.wind-particle-webgl-canvas',
      '.scalar-field-webgl-canvas',
      '.wind-particle-canvas',
      '.wind-contour-canvas',
      '.wind-barb-canvas',
      '.scalar-contour-canvas',
    ]
    for (const sel of selectors) {
      stage.querySelectorAll(sel).forEach((node) => {
        const canvas = node as HTMLCanvasElement
        if (!canvas.width || !canvas.height) return
        try {
          const rect = canvas.getBoundingClientRect()
          const stageRect = stage.getBoundingClientRect()
          targetCtx.drawImage(
            canvas,
            (rect.left - stageRect.left) * scaleX,
            (rect.top - stageRect.top) * scaleY,
            rect.width * scaleX,
            rect.height * scaleY,
          )
        } catch (error) {
          warnImpl('[MapCanvas] overlay canvas capture skipped:', sel, error)
        }
      })
    }
  }

  function captureMapCanvas(): string | null {
    const map = options.getMap()
    const stage = options.getMapStageElement()
    if (!map) return null

    try {
      ;(map as MapInstance & { render: () => void }).render()
      const mapCanvas = map.getCanvas()
      if (!stage) return mapCanvas.toDataURL('image/png')

      const out = document.createElement('canvas')
      out.width = mapCanvas.width
      out.height = mapCanvas.height
      const ctx = out.getContext('2d')
      if (!ctx) return mapCanvas.toDataURL('image/png')
      ctx.drawImage(mapCanvas, 0, 0)
      const scaleX = mapCanvas.width / Math.max(1, mapCanvas.clientWidth || mapCanvas.width)
      const scaleY = mapCanvas.height / Math.max(1, mapCanvas.clientHeight || mapCanvas.height)
      captureOverlayCanvases(stage, ctx, scaleX, scaleY)
      return out.toDataURL('image/png')
    } catch (error) {
      warnImpl('[MapCanvas] captureMapCanvas failed:', error)
      return null
    }
  }

  return {
    getMapStageElement: options.getMapStageElement,
    captureMapCanvas,
    selectHotspot: options.selectHotspot,
  }
}
