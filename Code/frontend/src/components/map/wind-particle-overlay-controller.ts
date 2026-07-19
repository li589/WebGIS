import { WindBarbLayer } from './wind-barb-layer'
import { WindContourLayer } from './wind-contour-layer'
import { WindParticleCanvas } from './wind-particle-canvas'
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
  private windBarbLayer: WindBarbLayer | null = null
  private windContourLayer: WindContourLayer | null = null
  private currentWindGeojson: WindGeoJSON | null = null
  private lastWindGeojsonUrl: string | null = null
  private currentParticleFlowCatalogId: string | null = null
  private windParticleFetchToken = 0
  private windParticleFetchAbort: AbortController | null = null

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

  reset(options?: { invalidatePendingFetch?: boolean }) {
    debugLog('WindParticleController', 'reset', 'invalidatePendingFetch', options?.invalidatePendingFetch)
    if (options?.invalidatePendingFetch !== false) {
      this.windParticleFetchToken++
      this.abortPendingGeojsonFetch()
    }
    if (this.windParticleCanvas) {
      this.windParticleCanvas.destroy()
      this.windParticleCanvas = null
    }
    if (this.windBarbLayer) {
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }
    if (this.windContourLayer) {
      this.windContourLayer.destroy()
      this.windContourLayer = null
    }
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

  async sync(
    overlayState: WeatherOverlayState,
    options: {
      overlayToken: number
      getSyncWeatherToken: () => number
      getEnabledParticleFlowCatalogId: () => string | null
    },
  ) {
    debugLog(
      'WindParticleController',
      'sync start',
      'catalogId',
      overlayState.catalogId,
      'geojsonUrl',
      overlayState.geojsonUrl,
      'hasInlineGeojson',
      !!overlayState.geojsonData,
    )

    const catalogId = overlayState.catalogId

    if (
      options.overlayToken !== options.getSyncWeatherToken()
      || this.currentParticleFlowCatalogId !== catalogId
    ) {
      return
    }

    const urlChanged = this.lastWindGeojsonUrl !== overlayState.geojsonUrl
    const inlineGeojson = overlayState.geojsonData as WindGeoJSON | null
    let geojson: WindGeoJSON | null = inlineGeojson ?? (urlChanged ? null : this.currentWindGeojson)
    this.abortPendingGeojsonFetch()
    const fetchToken = ++this.windParticleFetchToken
    const fetchAbort = new AbortController()
    this.windParticleFetchAbort = fetchAbort

    if (!inlineGeojson && urlChanged && overlayState.geojsonUrl) {
      try {
        const resp = await fetch(overlayState.geojsonUrl, { signal: fetchAbort.signal })
        if (!resp.ok) {
          console.warn('[WindParticleController] sync: fetch failed status=%d', resp.status)
          return
        }
        const fetchedGeojson = (await resp.json()) as WindGeoJSON
        if (
          options.overlayToken !== options.getSyncWeatherToken()
          || fetchToken !== this.windParticleFetchToken
          || this.currentParticleFlowCatalogId !== catalogId
          || options.getEnabledParticleFlowCatalogId() !== catalogId
        ) {
          return
        }
        geojson = fetchedGeojson
        this.currentWindGeojson = fetchedGeojson
        this.lastWindGeojsonUrl = overlayState.geojsonUrl
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          debugLog('WindParticleController', 'sync fetch aborted')
          return
        }
        console.error('[WindParticleController] sync: fetch error', err)
        return
      } finally {
        if (this.windParticleFetchAbort === fetchAbort) {
          this.windParticleFetchAbort = null
        }
      }
    }

    if (inlineGeojson) {
      this.currentWindGeojson = inlineGeojson
      this.lastWindGeojsonUrl = overlayState.geojsonUrl
    }

    if (
      options.overlayToken !== options.getSyncWeatherToken()
      || fetchToken !== this.windParticleFetchToken
      || this.currentParticleFlowCatalogId !== catalogId
      || options.getEnabledParticleFlowCatalogId() !== catalogId
    ) {
      return
    }

    if (!geojson) {
      debugLog('WindParticleController', 'sync no geojson, skip')
      return
    }

    const enableBarbLayer = overlayState.renderHint.paint_mode === 'barb'
    debugLog(
      'WindParticleController',
      'sync data ready',
      'urlChanged',
      urlChanged,
      'inlineGeojson',
      !!inlineGeojson,
      'currentWindGeojson',
      !!this.currentWindGeojson,
      'contour',
      !!this.windContourLayer,
      'particle',
      !!this.windParticleCanvas,
      'barb',
      !!this.windBarbLayer,
      'enableBarb',
      enableBarbLayer,
    )

    if (
      !urlChanged
      && !inlineGeojson
      && this.windParticleCanvas
      && this.windContourLayer
      && (!enableBarbLayer || this.windBarbLayer)
    ) {
      debugLog('WindParticleController', 'sync skip redundant update')
      // 仍刷新风速色底（避免其它路径清掉 MapLibre 层后粒子仍在却无底色）
      syncWeatherSpeedUnderlay(this.map, {
        ...overlayState,
        geojsonData: geojson,
        opacity: overlayState.opacity,
      })
      return
    }

    debugLog(
      'WindParticleController',
      'sync updating layers',
      'createContour',
      !this.windContourLayer,
      'createParticle',
      !this.windParticleCanvas,
      'createBarb',
      !this.windBarbLayer,
      'enableBarb',
      enableBarbLayer,
      'features',
      geojson.features?.length,
    )

    // 仅首次建层时清掉 fill/point 等冲突层；更新时就地 setData，避免色底闪空
    if (!this.windParticleCanvas || !this.windContourLayer) {
      removeWeatherMapArtifacts(this.map, catalogId)
    }

    if (!this.windContourLayer) {
      this.windContourLayer = new WindContourLayer(this.map, geojson)
    } else {
      this.windContourLayer.updateGeoJSON(geojson)
    }
    // 等值线仅作极淡结构参考；主色场交给 heatmap，避免与粒子抢视觉
    this.windContourLayer.setOpacity(0.06)

    if (!this.windParticleCanvas) {
      this.windParticleCanvas = new WindParticleCanvas(this.map, geojson)
      this.windParticleCanvas.start()
    } else {
      this.windParticleCanvas.updateGeoJSON(geojson)
    }

    // 粒子用提亮后的 palette 色（深色底图可见）；风速色场仍由 heatmap 承担
    const paletteId = resolveCanonicalPaletteId(overlayState.renderHint?.palette) || 'wind-blue'
    const particleColors = paletteToParticleColors(paletteId)
    if (particleColors.length >= 2) {
      this.windParticleCanvas.setColors(particleColors)
    }

    // 风速色底（MapLibre heatmap），粒子 Canvas 叠在其上
    syncWeatherSpeedUnderlay(this.map, {
      ...overlayState,
      geojsonData: geojson,
      opacity: overlayState.opacity,
    })

    if (enableBarbLayer) {
      if (!this.windBarbLayer) {
        this.windBarbLayer = new WindBarbLayer(this.map, geojson)
      } else {
        this.windBarbLayer.updateGeoJSON(geojson)
      }
    } else if (this.windBarbLayer) {
      debugLog('WindParticleController', 'destroy unused barb layer')
      this.windBarbLayer.destroy()
      this.windBarbLayer = null
    }

    debugLog('WindParticleController', 'sync layers updated', 'barbPresent', !!this.windBarbLayer)
  }

  destroy() {
    this.reset()
    this.currentParticleFlowCatalogId = null
  }
}
