import { WindBarbLayer } from './wind-barb-layer'
import { WindContourLayer } from './wind-contour-layer'
import { WindParticleCanvas } from './wind-particle-canvas'
import { WindStreamlineLayer } from './wind-streamline-layer'
import type { WindDisplayMode } from './wind-display-mode'
import { removeWeatherMapArtifacts } from './weather-overlay-maplibre'
import { syncWeatherSpeedUnderlay } from './weather-overlay-renderers'
import { paletteToParticleColors, resolveCanonicalPaletteId } from './weather-render'
import type { WeatherOverlayState } from './weather-overlay-registry'
import type { WindGeoJSON } from './types'

type MapInstance = import('maplibre-gl').Map

function debugLog(module: string, ...args: unknown[]) {
  console.log(`[${performance.now().toFixed(1)}ms] [${module}]`, ...args)
}

export class WindParticleOverlayController {
  private map: MapInstance
  private windParticleCanvas: WindParticleCanvas | null = null
  private windStreamlineLayer: WindStreamlineLayer | null = null
  private windBarbLayer: WindBarbLayer | null = null
  private windContourLayer: WindContourLayer | null = null
  private currentWindGeojson: WindGeoJSON | null = null
  private lastWindGeojsonUrl: string | null = null
  private currentParticleFlowCatalogId: string | null = null
  private windParticleFetchToken = 0
  private windParticleFetchAbort: AbortController | null = null
  private lastDisplayMode: WindDisplayMode = 'particle'

  constructor(map: MapInstance) {
    this.map = map
  }

  get activeCatalogId() {
    return this.currentParticleFlowCatalogId
  }

  set activeCatalogId(catalogId: string | null) {
    this.currentParticleFlowCatalogId = catalogId
  }

  private abortPendingGeojsonFetch() {
    if (this.windParticleFetchAbort) {
      this.windParticleFetchAbort.abort()
      this.windParticleFetchAbort = null
    }
  }

  private destroyParticleCanvas() {
    if (this.windParticleCanvas) {
      this.windParticleCanvas.destroy()
      this.windParticleCanvas = null
    }
  }

  private destroyStreamlineLayer() {
    if (this.windStreamlineLayer) {
      this.windStreamlineLayer.destroy()
      this.windStreamlineLayer = null
    }
  }

  private destroyAuxLayers() {
    if (this.windBarbLayer) {
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }
    if (this.windContourLayer) {
      this.windContourLayer.destroy()
      this.windContourLayer = null
    }
  }

  reset(options?: { invalidatePendingFetch?: boolean }) {
    debugLog('WindParticleController', 'reset', 'invalidatePendingFetch', options?.invalidatePendingFetch)
    if (options?.invalidatePendingFetch !== false) {
      this.windParticleFetchToken++
      this.abortPendingGeojsonFetch()
    }
    this.destroyParticleCanvas()
    this.destroyStreamlineLayer()
    this.destroyAuxLayers()
    this.currentWindGeojson = null
    this.lastWindGeojsonUrl = null
  }

  removeCatalogArtifacts(catalogId: string) {
    removeWeatherMapArtifacts(this.map, catalogId)
    if (this.currentParticleFlowCatalogId === catalogId) {
      this.reset()
      this.currentParticleFlowCatalogId = null
      return true
    }
    return false
  }

  private stillCurrent(
    options: {
      overlayToken: number
      getSyncWeatherToken: () => number
      getEnabledParticleFlowCatalogId: () => string | null
    },
    catalogId: string,
    fetchToken?: number,
  ) {
    if (options.overlayToken !== options.getSyncWeatherToken()) return false
    if (this.currentParticleFlowCatalogId !== catalogId) return false
    if (options.getEnabledParticleFlowCatalogId() !== catalogId) return false
    if (fetchToken !== undefined && fetchToken !== this.windParticleFetchToken) return false
    return true
  }

  /** 比较两次 inline geojson 是否需要重绘（避免引用相同但内容已变时漏更） */
  private geojsonNeedsUpdate(next: WindGeoJSON | null): boolean {
    const prev = this.currentWindGeojson
    if (!next) return !!prev
    if (!prev) return true
    if (prev === next) return false
    const prevN = Array.isArray(prev.features) ? prev.features.length : 0
    const nextN = Array.isArray(next.features) ? next.features.length : 0
    return prevN !== nextN || prev !== next
  }

  async sync(
    overlayState: WeatherOverlayState,
    options: {
      overlayToken: number
      getSyncWeatherToken: () => number
      getEnabledParticleFlowCatalogId: () => string | null
      getWindDisplayMode?: () => WindDisplayMode
    },
  ) {
    const catalogId = overlayState.catalogId
    const displayMode: WindDisplayMode = options.getWindDisplayMode?.() ?? 'particle'

    if (!this.stillCurrent(options, catalogId)) return

    const inlineGeojson = (overlayState.geojsonData && typeof overlayState.geojsonData === 'object'
      && 'features' in overlayState.geojsonData)
      ? overlayState.geojsonData as WindGeoJSON
      : null

    // 视口切换后 merge 可能短暂为 null：清掉旧画面，等待新瓦片，避免旧区域「粘住」
    if (!inlineGeojson && !overlayState.geojsonUrl) {
      if (this.currentWindGeojson || this.windParticleCanvas || this.windStreamlineLayer) {
        this.destroyParticleCanvas()
        this.destroyStreamlineLayer()
        this.destroyAuxLayers()
        this.currentWindGeojson = null
        this.lastWindGeojsonUrl = null
        removeWeatherMapArtifacts(this.map, catalogId)
      }
      return
    }

    let geojson = this.currentWindGeojson
    let dataChanged = false

    if (inlineGeojson) {
      dataChanged = this.geojsonNeedsUpdate(inlineGeojson)
      geojson = inlineGeojson
      this.currentWindGeojson = inlineGeojson
      this.lastWindGeojsonUrl = overlayState.geojsonUrl
    } else if (overlayState.geojsonUrl && overlayState.geojsonUrl !== this.lastWindGeojsonUrl) {
      dataChanged = true
      this.lastWindGeojsonUrl = overlayState.geojsonUrl
      const fetchToken = ++this.windParticleFetchToken
      this.abortPendingGeojsonFetch()
      const abort = new AbortController()
      this.windParticleFetchAbort = abort
      try {
        const resp = await fetch(overlayState.geojsonUrl, { signal: abort.signal })
        if (!resp.ok) throw new Error(`wind geojson ${resp.status}`)
        geojson = await resp.json() as WindGeoJSON
      } catch (err) {
        if ((err as Error)?.name === 'AbortError') return
        debugLog('WindParticleController', 'fetch failed', err)
        return
      } finally {
        if (this.windParticleFetchAbort === abort) this.windParticleFetchAbort = null
      }
      if (!this.stillCurrent(options, catalogId, fetchToken)) return
      this.currentWindGeojson = geojson
    }

    if (!this.stillCurrent(options, catalogId)) return
    if (!geojson) return

    const modeChanged = displayMode !== this.lastDisplayMode
    this.lastDisplayMode = displayMode

    // ── 关闭：仅风速色底，无粒子/流线/等值线 ────────────────────────────
    if (displayMode === 'off') {
      this.destroyParticleCanvas()
      this.destroyStreamlineLayer()
      this.destroyAuxLayers()
      syncWeatherSpeedUnderlay(this.map, {
        ...overlayState,
        geojsonData: geojson,
        opacity: Math.min(1, Math.max(0.55, overlayState.opacity * 1.05)),
      })
      return
    }

    const enableBarbLayer = overlayState.renderHint.paint_mode === 'barb'
    const useStreamline = displayMode === 'streamline'
    const useParticle = displayMode === 'particle'

    if (useStreamline) this.destroyParticleCanvas()
    if (useParticle) this.destroyStreamlineLayer()

    const hasVisualLayer = useParticle ? !!this.windParticleCanvas : !!this.windStreamlineLayer

    // 粒子/流量场：不叠风速底色；数据未变且层已就绪时可跳过
    if (
      !dataChanged
      && !modeChanged
      && hasVisualLayer
      && this.windContourLayer
      && (!enableBarbLayer || this.windBarbLayer)
    ) {
      return
    }

    if (!hasVisualLayer || !this.windContourLayer || modeChanged) {
      removeWeatherMapArtifacts(this.map, catalogId)
    }

    if (!this.windContourLayer) {
      this.windContourLayer = new WindContourLayer(this.map, geojson)
    } else {
      this.windContourLayer.updateGeoJSON(geojson)
    }
    this.windContourLayer.setOpacity(useStreamline ? 0.1 : 0.06)

    if (useParticle) {
      if (!this.windParticleCanvas) {
        this.windParticleCanvas = new WindParticleCanvas(this.map, geojson)
        this.windParticleCanvas.start()
      } else {
        this.windParticleCanvas.updateGeoJSON(geojson)
      }
      const paletteId = resolveCanonicalPaletteId(overlayState.renderHint?.palette) || 'wind-blue'
      const particleColors = paletteToParticleColors(paletteId)
      if (particleColors.length >= 2) {
        this.windParticleCanvas.setColors(particleColors)
      }
    } else if (useStreamline) {
      if (!this.windStreamlineLayer) {
        this.windStreamlineLayer = new WindStreamlineLayer(this.map, geojson)
        this.windStreamlineLayer.start()
      } else {
        this.windStreamlineLayer.updateGeoJSON(geojson)
      }
    }

    if (enableBarbLayer && useParticle) {
      if (!this.windBarbLayer) {
        this.windBarbLayer = new WindBarbLayer(this.map, geojson)
      } else {
        this.windBarbLayer.updateGeoJSON(geojson)
      }
    } else if (this.windBarbLayer) {
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }
  }

  destroy() {
    this.reset()
    this.currentParticleFlowCatalogId = null
  }
}
