import { buildMapViewportSnapshot } from './map-viewport-sync'

type MapInstance = import('maplibre-gl').Map

interface MapViewportStoreLike {
  setMapViewport: (
    center: { lng: number; lat: number },
    bbox: { west: number; south: number; east: number; north: number; crs: 'EPSG:4326' } | null,
    zoom?: number,
  ) => void
}

export interface MapInteractionModule {
  bindEvents: () => void
  syncViewportToStore: () => void
  applyInteractionMode: () => void
  dispose: () => void
}

interface CreateMapInteractionModuleOptions {
  map: MapInstance
  layersStore: MapViewportStoreLike
  getInteractionMode: () => 'select' | 'move'
  setIsMapInteracting: (interacting: boolean) => void
  scheduleHotspotSync: () => void
  emitMapPointSelect: (point: { lng: number; lat: number }) => void
}

interface RegisteredEventHandler {
  event: 'movestart' | 'move' | 'moveend' | 'zoomstart' | 'zoom' | 'zoomend' | 'resize' | 'render' | 'click'
  handler: (...args: any[]) => void
}

export function createMapInteractionModule(
  options: CreateMapInteractionModuleOptions,
): MapInteractionModule {
  const registeredHandlers: RegisteredEventHandler[] = []
  let eventsBound = false

  function syncViewportToStore() {
    const snapshot = buildMapViewportSnapshot(options.map)
    options.layersStore.setMapViewport(snapshot.center, snapshot.bbox, snapshot.zoom)
  }

  function applyInteractionMode() {
    if (options.getInteractionMode() === 'select') {
      options.map.dragPan.disable()
    } else {
      options.map.dragPan.enable()
    }
  }

  function on<T extends RegisteredEventHandler['event']>(event: T, handler: (...args: any[]) => void) {
    options.map.on(event, handler)
    registeredHandlers.push({ event, handler })
  }

  function bindEvents() {
    if (eventsBound) return
    eventsBound = true

    on('movestart', () => {
      options.setIsMapInteracting(true)
    })
    on('move', () => {
      options.scheduleHotspotSync()
    })
    on('moveend', () => {
      options.setIsMapInteracting(false)
      options.scheduleHotspotSync()
      syncViewportToStore()
    })
    on('zoomstart', () => {
      options.setIsMapInteracting(true)
    })
    on('zoom', () => {
      options.scheduleHotspotSync()
    })
    on('zoomend', () => {
      options.setIsMapInteracting(false)
      options.scheduleHotspotSync()
      syncViewportToStore()
    })
    on('resize', () => {
      options.scheduleHotspotSync()
    })
    on('render', () => {
      options.scheduleHotspotSync()
    })
    on('click', (event: { lngLat: { lng: number; lat: number } }) => {
      if (options.getInteractionMode() !== 'select') return
      options.emitMapPointSelect({
        lng: event.lngLat.lng,
        lat: event.lngLat.lat,
      })
    })
  }

  function dispose() {
    for (const { event, handler } of registeredHandlers.splice(0)) {
      options.map.off(event, handler)
    }
    eventsBound = false
  }

  return {
    bindEvents,
    syncViewportToStore,
    applyInteractionMode,
    dispose,
  }
}
