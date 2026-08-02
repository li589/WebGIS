type MapInstance = import('maplibre-gl').Map

export interface MapCanvasExposeBridge {
  getMapStageElement: () => HTMLElement | null
  /** Capture basemap WebGL + overlay canvases after a guaranteed repaint. */
  captureMapCanvas: () => Promise<string | null>
  selectHotspot?: (pinId: string) => void
  /** 全屏面板盖住地图时暂停风场 RAF */
  setWindAnimationPaused?: (paused: boolean) => void
  /** 缩放到指定图层显示范围（双击图层列表等） */
  fitToLayerExtent?: (instanceId: string) => boolean
}

interface CreateMapCanvasExposeBridgeOptions {
  getMapStageElement: () => HTMLElement | null
  getMap: () => MapInstance | null
  selectHotspot?: (pinId: string) => void
  setWindAnimationPaused?: (paused: boolean) => void
  fitToLayerExtent?: (instanceId: string) => boolean
  dependencies?: {
    warn?: (message?: unknown, ...optionalParams: unknown[]) => void
  }
}

function waitForMapRender(map: MapInstance): Promise<void> {
  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      resolve()
    }
    map.once('render', finish)
    map.triggerRepaint()
    // Fallback if render event is skipped (idle / already painted).
    window.setTimeout(finish, 120)
  })
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

  async function captureMapCanvas(): Promise<string | null> {
    const map = options.getMap()
    const stage = options.getMapStageElement()
    if (!map) return null

    try {
      await waitForMapRender(map)
      // One sync render after the event so the buffer is current for toDataURL
      // when preserveDrawingBuffer is false.
      ;(map as MapInstance & { render: () => void }).render()
      const mapCanvas = map.getCanvas()

      try {
        // Probe taint early — cross-origin tiles without CORS break export.
        mapCanvas.toDataURL('image/png')
      } catch (error) {
        warnImpl('[MapCanvas] map canvas is tainted; cannot export basemap:', error)
        return null
      }

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
    setWindAnimationPaused: options.setWindAnimationPaused,
    fitToLayerExtent: options.fitToLayerExtent,
  }
}
