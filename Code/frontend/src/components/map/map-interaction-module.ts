import { buildMapViewportSnapshot } from './map-viewport-sync'

type MapInstance = import('maplibre-gl').Map
type InteractionMode = import('../../stores/ui').InteractionMode

/** 平移中途同步节流：避免每帧 JSON.stringify + 重置防抖，仍能提前拉瓦片 */
const MOVE_VIEWPORT_SYNC_MIN_MS = 100

interface MapViewportStoreLike {
  setMapViewport: (
    center: { lng: number; lat: number },
    bbox: { west: number; south: number; east: number; north: number; crs: 'EPSG:4326' } | null,
    zoom?: number,
    options?: { immediate?: boolean },
  ) => void
}

export interface MapInteractionModule {
  bindEvents: () => void
  syncViewportToStore: (options?: { immediate?: boolean }) => void
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
  handler: (...args: unknown[]) => void
}

export function createMapInteractionModule(
  options: CreateMapInteractionModuleOptions,
): MapInteractionModule {
  const registeredHandlers: RegisteredEventHandler[] = []
  let eventsBound = false
  let lastMoveViewportSyncAt = 0

  function syncViewportToStore(syncOptions?: { immediate?: boolean }) {
    const snapshot = buildMapViewportSnapshot(options.map)
    options.layersStore.setMapViewport(snapshot.center, snapshot.bbox, snapshot.zoom, syncOptions)
  }

  function syncViewportOnMoveThrottled() {
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now()
    if (now - lastMoveViewportSyncAt < MOVE_VIEWPORT_SYNC_MIN_MS) return
    lastMoveViewportSyncAt = now
    syncViewportToStore()
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
    handler: (...args: unknown[]) => void,
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
      // 平移中途节流同步：由 weather-viewport 防抖合并，避免每帧打满调度
      syncViewportOnMoveThrottled()
    })
    on('moveend', () => {
      options.setIsMapInteracting(false)
      options.scheduleHotspotSync()
      lastMoveViewportSyncAt = 0
      syncViewportToStore({ immediate: true })
    })
    on('zoomstart', () => {
      options.setIsMapInteracting(true)
    })
    on('zoom', () => {
      options.scheduleHotspotSync()
      // 连续缩放中途开始调度，避免仅等 zoomend 再加防抖
      syncViewportToStore()
    })
    on('zoomend', () => {
      options.setIsMapInteracting(false)
      options.scheduleHotspotSync()
      syncViewportToStore({ immediate: true })
    })
    on('resize', () => {
      options.scheduleHotspotSync()
    })
    on('render', () => {
      options.scheduleHotspotSync()
    })
    on('click', (event: unknown) => {
      const e = event as {
        lngLat: { lng: number; lat: number }
        originalEvent?: MouseEvent
      }
      const mode = options.getInteractionMode()
      const shiftOneShot = mode === 'move' && Boolean(e.originalEvent?.shiftKey)
      if (mode !== 'select' && !shiftOneShot) return
      options.emitMapPointSelect({
        lng: e.lngLat.lng,
        lat: e.lngLat.lat,
      })
    })
  }

  function dispose() {
    for (const { event, handler } of registeredHandlers.splice(0)) {
      options.map.off(event, handler)
    }
    eventsBound = false
    lastMoveViewportSyncAt = 0
  }

  return {
    bindEvents,
    syncViewportToStore,
    applyInteractionMode,
    dispose,
  }
}
