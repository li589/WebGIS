/**
 * Weather tile reconcile / provider preference slice.
 * Public API remains re-exported via useLayersStore().
 */
import { useWeatherTileManager } from '../weather-tile-manager'
import { useWeatherSourcePrefsStore } from '../weather-source-prefs'
import type { BoundingBox } from '../../services/runtime-api'
import type { ActiveLayer } from './types'

export interface WeatherReconcileSliceDeps {
  getActiveLayers: () => ActiveLayer[]
  isLocalImport: (layer: ActiveLayer) => boolean
  isWeatherEngineLayer: (catalogId: string) => boolean
  supportsParticleFlow: (catalogId: string) => boolean
  enableParticleIfUnset: (catalogId: string) => void
  getMapCenter: () => { lng: number; lat: number }
  getMapZoom: () => number
  getMapBBox: () => BoundingBox | null
  getCurrentHour: () => number
  getLastPointWeatherQuery: () => { lng: number; lat: number; catalogId: string } | null
  fetchPointWeather: (lng: number, lat: number, catalogId: string) => void | Promise<void>
  clearPointWeather: () => void
  hasPointWeather: () => boolean
}

export function createWeatherReconcileSlice(deps: WeatherReconcileSliceDeps) {
  const weatherTileManager = useWeatherTileManager()
  const weatherSourcePrefs = useWeatherSourcePrefsStore()

  /** Resolve tile manager provider arg (always explicit: auto | provider_id). */
  function weatherProviderArg(catalogId: string): string {
    return weatherSourcePrefs.getProvider(catalogId) || 'auto'
  }

  /** Query param for APIs; undefined when auto so backend uses registry priority. */
  function weatherProviderQuery(catalogId: string): string | undefined {
    return weatherSourcePrefs.getProviderQuery(catalogId)
  }

  function reconcileActiveWeatherLayers() {
    const cc = deps.getMapCenter()
    const cz = deps.getMapZoom()
    const ch = deps.getCurrentHour()
    const cb = deps.getMapBBox()

    for (const layer of deps.getActiveLayers()) {
      if (layer.isAdminBoundary || deps.isLocalImport(layer)) continue
      if (layer.visible && deps.isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.setLayerActive(layer.catalogId, true)
        weatherTileManager.setViewport(
          layer.catalogId,
          cc,
          cz,
          ch,
          undefined,
          cb,
          weatherProviderArg(layer.catalogId),
        )
        if (deps.supportsParticleFlow(layer.catalogId)) {
          deps.enableParticleIfUnset(layer.catalogId)
        }
      } else if (!deps.isWeatherEngineLayer(layer.catalogId)) {
        weatherTileManager.clearLayer(layer.catalogId)
      }
    }
  }

  /** After user changes per-layer weather provider preference, refresh tiles + point query. */
  function applyWeatherProviderPreference(catalogId: string, providerId: string) {
    weatherSourcePrefs.setProvider(catalogId, providerId === 'auto' ? 'auto' : providerId)
    const layer = deps
      .getActiveLayers()
      .find((item) => item.catalogId === catalogId && item.visible)
    if (layer && deps.isWeatherEngineLayer(catalogId)) {
      weatherTileManager.setViewport(
        catalogId,
        deps.getMapCenter(),
        deps.getMapZoom(),
        deps.getCurrentHour(),
        undefined,
        deps.getMapBBox(),
        weatherProviderArg(catalogId),
      )
    }
    const last = deps.getLastPointWeatherQuery()
    if (last && last.catalogId === catalogId) {
      void deps.fetchPointWeather(last.lng, last.lat, catalogId)
    } else if (deps.hasPointWeather()) {
      // Provider changed but no remembered click — clear stale point card.
      deps.clearPointWeather()
    }
  }

  function activateWeatherTileViewport(catalogId: string) {
    weatherTileManager.setLayerActive(catalogId, true)
    weatherTileManager.setViewport(
      catalogId,
      deps.getMapCenter(),
      deps.getMapZoom(),
      deps.getCurrentHour(),
      undefined,
      deps.getMapBBox(),
      weatherProviderArg(catalogId),
    )
  }

  return {
    weatherProviderArg,
    weatherProviderQuery,
    reconcileActiveWeatherLayers,
    applyWeatherProviderPreference,
    activateWeatherTileViewport,
  }
}

export type WeatherReconcileSlice = ReturnType<typeof createWeatherReconcileSlice>
