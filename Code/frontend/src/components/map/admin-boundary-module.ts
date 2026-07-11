type MapInstance = import('maplibre-gl').Map
type GeoJsonSourceSpecification = import('maplibre-gl').GeoJSONSourceSpecification
type BoundaryModuleData = typeof import('../../app/guangdong-boundaries')

export interface AdminBoundaryModule {
  ensureLayers: () => Promise<void>
  syncOverlay: (show: boolean, opacity: number) => void
}

interface CreateAdminBoundaryModuleOptions {
  map: MapInstance
  setLoadingLabel: (label: string) => void
  dependencies?: {
    loadBoundaryModule?: () => Promise<BoundaryModuleData | null>
  }
}

export function createAdminBoundaryModule(
  options: CreateAdminBoundaryModuleOptions,
): AdminBoundaryModule {
  const loadBoundaryModuleImpl = options.dependencies?.loadBoundaryModule
    ?? (() => import('../../app/guangdong-boundaries').catch((error) => {
      console.error('[MapCanvas] Failed to load boundary module:', error)
      return null
    }))

  let boundaryModule: BoundaryModuleData | null = null
  let boundaryModulePromise: Promise<BoundaryModuleData | null> | null = null

  async function ensureBoundaryModule() {
    if (!boundaryModule) {
      if (!boundaryModulePromise) {
        options.setLoadingLabel('正在载入行政区边界...')
        boundaryModulePromise = loadBoundaryModuleImpl()
      }
      boundaryModule = await boundaryModulePromise
      if (!boundaryModule) {
        boundaryModulePromise = null
      }
    }
    return boundaryModule
  }

  async function ensureLayers() {
    const loadedBoundaryModule = await ensureBoundaryModule()
    if (!loadedBoundaryModule) return

    if (!options.map.getSource('admin-boundaries')) {
      options.map.addSource('admin-boundaries', {
        type: 'geojson',
        data: loadedBoundaryModule.guangdongCityBoundaries,
      } as GeoJsonSourceSpecification)
    }

    if (!options.map.getSource('admin-centers')) {
      options.map.addSource('admin-centers', {
        type: 'geojson',
        data: loadedBoundaryModule.guangdongCityCenters,
      } as GeoJsonSourceSpecification)
    }

    if (!options.map.getLayer('admin-fill')) {
      options.map.addLayer({
        id: 'admin-fill',
        type: 'fill',
        source: 'admin-boundaries',
        paint: {
          'fill-color': '#0c2238',
          'fill-opacity': 0,
        },
      })
    }

    if (!options.map.getLayer('admin-line')) {
      options.map.addLayer({
        id: 'admin-line',
        type: 'line',
        source: 'admin-boundaries',
        paint: {
          'line-color': '#4c88ba',
          'line-width': 1,
          'line-opacity': 0,
        },
      })
    }

    if (!options.map.getLayer('admin-center-points')) {
      options.map.addLayer({
        id: 'admin-center-points',
        type: 'circle',
        source: 'admin-centers',
        paint: {
          'circle-radius': 2.2,
          'circle-color': '#d8efff',
          'circle-opacity': 0,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#0a233a',
        },
      })
    }
  }

  function syncOverlay(show: boolean, opacity: number) {
    const lineOpacity = show ? 0.82 * opacity : 0
    const fillOpacity = show ? 0.32 * opacity : 0
    const centerOpacity = show ? 0.72 * opacity : 0

    if (options.map.getLayer('admin-fill')) {
      options.map.setLayoutProperty('admin-fill', 'visibility', 'visible')
      options.map.setPaintProperty('admin-fill', 'fill-opacity', fillOpacity)
    }
    if (options.map.getLayer('admin-line')) {
      options.map.setLayoutProperty('admin-line', 'visibility', 'visible')
      options.map.setPaintProperty('admin-line', 'line-opacity', lineOpacity)
    }
    if (options.map.getLayer('admin-center-points')) {
      options.map.setLayoutProperty('admin-center-points', 'visibility', 'visible')
      options.map.setPaintProperty('admin-center-points', 'circle-opacity', centerOpacity)
    }
  }

  return {
    ensureLayers,
    syncOverlay,
  }
}
