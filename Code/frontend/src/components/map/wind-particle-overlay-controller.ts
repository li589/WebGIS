import { WindBarbLayer } from './wind-barb-layer'
import { WindContourLayer } from './wind-contour-layer'
import { WindParticleCanvas } from './wind-particle-canvas'
import { removeWeatherMapArtifacts } from './weather-overlay-maplibre'
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

  constructor(map: MapInstance) {
    this.map = map
  }

  get activeCatalogId() {
    return this.currentParticleFlowCatalogId
  }

  set activeCatalogId(catalogId: string | null) {
    this.currentParticleFlowCatalogId = catalogId
  }

  reset(options?: { invalidatePendingFetch?: boolean }) {
    debugLog('WindParticleController', 'reset', 'invalidatePendingFetch', options?.invalidatePendingFetch)
    if (options?.invalidatePendingFetch !== false) {
      this.windParticleFetchToken++
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
    removeWeatherMapArtifacts(this.map, catalogId)

    if (
      options.overlayToken !== options.getSyncWeatherToken()
      || this.currentParticleFlowCatalogId !== catalogId
    ) {
      return
    }

    const urlChanged = this.lastWindGeojsonUrl !== overlayState.geojsonUrl
    const inlineGeojson = overlayState.geojsonData as WindGeoJSON | null
    let geojson: WindGeoJSON | null = inlineGeojson ?? (urlChanged ? null : this.currentWindGeojson)
    const fetchToken = ++this.windParticleFetchToken

    if (!inlineGeojson && urlChanged && overlayState.geojsonUrl) {
      try {
        const resp = await fetch(overlayState.geojsonUrl)
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
        console.error('[WindParticleController] sync: fetch error', err)
        return
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

    if (!this.windContourLayer) {
      this.windContourLayer = new WindContourLayer(this.map, geojson)
    } else {
      this.windContourLayer.updateGeoJSON(geojson)
    }

    if (!this.windParticleCanvas) {
      this.windParticleCanvas = new WindParticleCanvas(this.map, geojson)
      this.windParticleCanvas.start()
    } else {
      this.windParticleCanvas.updateGeoJSON(geojson)
    }

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
