/**
 * Weather overlay session: sole teardown entry for per-catalog and bulk cleanup.
 * Controllers only remove artifacts when called from here (or reconcile via coordinator).
 * Do not add MapCanvas-level wind/scalar clears outside this session.
 */
import type { WindParticleControllerContract } from './wind-particle-controller-contract'
import type { ScalarFieldWebGLController } from './scalar-field-webgl-controller'
import { clearLastGoodGridFillState } from './weather-overlay-coordinator'

type MapInstance = import('maplibre-gl').Map

interface CreateWeatherOverlaySessionOptions {
  map: MapInstance
  windParticleController: WindParticleControllerContract | null
  scalarFieldController?: ScalarFieldWebGLController | null
}

export interface WeatherOverlaySession {
  readonly renderedCatalogIds: Iterable<string>
  markRendered: (catalogId: string) => void
  removeCatalogOverlay: (catalogId: string) => void
  removeAllOverlays: () => void
}

export function createWeatherOverlaySession(
  options: CreateWeatherOverlaySessionOptions,
): WeatherOverlaySession {
  const renderedCatalogIds = new Set<string>()

  function removeCatalogOverlay(catalogId: string) {
    options.windParticleController?.removeCatalogArtifacts(catalogId)
    options.scalarFieldController?.removeCatalogArtifacts(catalogId)
    clearLastGoodGridFillState(catalogId)
    renderedCatalogIds.delete(catalogId)
  }

  function removeAllOverlays() {
    for (const catalogId of Array.from(renderedCatalogIds)) {
      removeCatalogOverlay(catalogId)
    }
    options.windParticleController?.destroy()
    options.scalarFieldController?.destroy()
  }

  return {
    get renderedCatalogIds() {
      return renderedCatalogIds
    },
    markRendered(catalogId: string) {
      renderedCatalogIds.add(catalogId)
    },
    removeCatalogOverlay,
    removeAllOverlays,
  }
}
