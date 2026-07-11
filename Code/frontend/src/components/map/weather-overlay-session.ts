import { WindParticleOverlayController } from './wind-particle-overlay-controller'

type MapInstance = import('maplibre-gl').Map

interface CreateWeatherOverlaySessionOptions {
  map: MapInstance
  windParticleController: WindParticleOverlayController | null
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
    renderedCatalogIds.delete(catalogId)
  }

  function removeAllOverlays() {
    for (const catalogId of Array.from(renderedCatalogIds)) {
      removeCatalogOverlay(catalogId)
    }
    options.windParticleController?.destroy()
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
