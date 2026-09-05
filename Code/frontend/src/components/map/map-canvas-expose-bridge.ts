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
  /** 切换导入/科学 TS overlay 当前时刻 */
  setOverlayTime?: (layerId: string, time: string) => void | Promise<void>
  flyTo?: (options: { center: [number, number]; zoom?: number; duration?: number }) => void
  fitBounds?: (
    bounds: [number, number, number, number],
    options?: { padding?: number; maxZoom?: number; duration?: number },
  ) => void
}

interface CreateMapCanvasExposeBridgeOptions {
  getMapStageElement: () => HTMLElement | null
  getMap: () => MapInstance | null
  selectHotspot?: (pinId: string) => void
  setWindAnimationPaused?: (paused: boolean) => void
  fitToLayerExtent?: (instanceId: string) => boolean
  setOverlayTime?: (layerId: string, time: string) => void | Promise<void>
  flyTo?: (options: { center: [number, number]; zoom?: number; duration?: number }) => void
  fitBounds?: (
    bounds: [number, number, number, number],
    options?: { padding?: number; maxZoom?: number; duration?: number },
  ) => void
  dependencies?: {
    warn?: (message?: unknown, ...optionalParams: unknown[]) => void
  }
}

/**
 * Wait for a MapLibre paint frame, then read the canvas in the same turn.
 * MapLibre 5 has no public `Map.render()` — only `triggerRepaint()` + `render` event.
 * With preserveDrawingBuffer=false, toDataURL must run synchronously in the render
 * callback (or immediately after the event fires on the same tick).
 */
function captureBasemapDataUrl(map: MapInstance): Promise<string | null> {
  return new Promise((resolve) => {
    let settled = false
    const finish = (dataUrl: string | null) => {
      if (settled) return
      settled = true
      resolve(dataUrl)
    }
    const readCanvas = (): string | null => {
      try {
        return map.getCanvas().toDataURL('image/png')
      } catch {
        return null
      }
    }
    map.once('render', () => {
      finish(readCanvas())
    })
    map.triggerRepaint()
    // Fallback if render event is skipped (idle / already painted).
    globalThis.setTimeout(() => finish(readCanvas()), 120)
  })
}

function loadImage(src: string, timeoutMs = 5000): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const timer = globalThis.setTimeout(() => {
      reject(new Error('Basemap snapshot image load timed out'))
    }, timeoutMs)
    img.onload = () => {
      globalThis.clearTimeout(timer)
      resolve(img)
    }
    img.onerror = () => {
      globalThis.clearTimeout(timer)
      reject(new Error('Failed to load basemap snapshot'))
    }
    img.src = src
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

    const run = async (): Promise<string | null> => {
      const basemapDataUrl = await captureBasemapDataUrl(map)
      if (!basemapDataUrl) {
        warnImpl('[MapCanvas] map canvas is tainted or empty; cannot export basemap')
        return null
      }

      if (!stage) return basemapDataUrl

      const mapCanvas = map.getCanvas()
      const out = document.createElement('canvas')
      out.width = mapCanvas.width
      out.height = mapCanvas.height
      const ctx = out.getContext('2d')
      if (!ctx) return basemapDataUrl

      const basemapImage = await loadImage(basemapDataUrl)
      ctx.drawImage(basemapImage, 0, 0)
      const scaleX = mapCanvas.width / Math.max(1, mapCanvas.clientWidth || mapCanvas.width)
      const scaleY = mapCanvas.height / Math.max(1, mapCanvas.clientHeight || mapCanvas.height)
      captureOverlayCanvases(stage, ctx, scaleX, scaleY)
      return out.toDataURL('image/png')
    }

    try {
      return await Promise.race([
        run(),
        new Promise<null>((resolve) => {
          globalThis.setTimeout(() => {
            warnImpl('[MapCanvas] captureMapCanvas timed out')
            resolve(null)
          }, 4000)
        }),
      ])
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
    setOverlayTime: options.setOverlayTime,
    flyTo: options.flyTo,
    fitBounds: options.fitBounds,
  }
}
