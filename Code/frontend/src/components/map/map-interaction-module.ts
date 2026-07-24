import { buildMapViewportSnapshot } from './map-viewport-sync'

type MapInstance = import('maplibre-gl').Map
type InteractionMode = import('../../stores/ui').InteractionMode

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
  getInteractionMode: () => InteractionMode
  setIsMapInteracting: (interacting: boolean) => void
  scheduleHotspotSync: () => void
  emitMapPointSelect: (point: { lng: number; lat: number }) => void
}

interface RegisteredEventHandler {
  event:
    | 'movestart'
    | 'move'
    | 'moveend'
    | 'zoomstart'
    | 'zoom'
    | 'zoomend'
    | 'resize'
    | 'render'
    | 'click'
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
    const mode = options.getInteractionMode()
    const canvas = options.map.getCanvas?.()
    // measure 与 select 模式都需要禁用 dragPan：
    // - select：点击查询点信息，拖动会与单击冲突
    // - measure：点击打点，拖动会与单击冲突
    if (mode === 'select' || mode === 'measure') {
      options.map.dragPan.disable()
      // select 用箭头（非抓手）；measure 用十字准星
      if (canvas?.style) {
        canvas.style.cursor = mode === 'select' ? 'default' : 'crosshair'
      }
    } else {
      options.map.dragPan.enable()
      // 交还 MapLibre 默认抓手光标
      if (canvas?.style) {
        canvas.style.cursor = ''
      }
    }
  }

  function on<T extends RegisteredEventHandler['event']>(
    event: T,
    handler: (...args: any[]) => void,
  ) {
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
    on('click', (event: { lngLat: { lng: number; lat: number }; originalEvent?: MouseEvent }) => {
      const mode = options.getInteractionMode()
      const shiftOneShot = mode === 'move' && Boolean(event.originalEvent?.shiftKey)
      if (mode !== 'select' && !shiftOneShot) return
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
