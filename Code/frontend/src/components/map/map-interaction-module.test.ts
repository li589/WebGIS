import { describe, expect, it, vi } from 'vitest'

import { createMapInteractionModule } from './map-interaction-module'

describe('map-interaction-module', () => {
  it('binds map events and forwards interaction side effects', () => {
    const handlers = new Map<string, (...args: any[]) => void>()
    const dragPanDisable = vi.fn()
    const dragPanEnable = vi.fn()
    const setMapViewport = vi.fn()
    const setIsMapInteracting = vi.fn()
    const scheduleHotspotSync = vi.fn()
    const emitMapPointSelect = vi.fn()
    let interactionMode: 'select' | 'move' = 'select'

    const canvasStyle = { cursor: '' }
    const map = {
      getCenter: () => ({ lng: 190, lat: 22 }),
      getBounds: () => ({
        getSouth: () => -91,
        getNorth: () => 91,
        getWest: () => -200,
        getEast: () => 200,
      }),
      getZoom: () => 6.2,
      getCanvas: () => ({ style: canvasStyle }),
      dragPan: {
        disable: dragPanDisable,
        enable: dragPanEnable,
      },
      on: vi.fn((event: string, handler: (...args: any[]) => void) => {
        handlers.set(event, handler)
      }),
      off: vi.fn((event: string) => {
        handlers.delete(event)
      }),
    } as any

    const module = createMapInteractionModule({
      map,
      layersStore: { setMapViewport },
      getInteractionMode: () => interactionMode,
      setIsMapInteracting,
      scheduleHotspotSync,
      emitMapPointSelect,
    })

    module.bindEvents()
    module.applyInteractionMode()
    expect(canvasStyle.cursor).toBe('default')

    handlers.get('movestart')?.()
    handlers.get('move')?.()
    handlers.get('moveend')?.()
    handlers.get('zoomstart')?.()
    handlers.get('zoom')?.()
    handlers.get('zoomend')?.()
    handlers.get('resize')?.()
    handlers.get('render')?.()
    handlers.get('click')?.({ lngLat: { lng: 113.2, lat: 23.1 } })

    interactionMode = 'move'
    module.applyInteractionMode()
    expect(canvasStyle.cursor).toBe('')
    handlers.get('click')?.({ lngLat: { lng: 120, lat: 30 } })

    expect(dragPanDisable).toHaveBeenCalledTimes(1)
    expect(dragPanEnable).toHaveBeenCalledTimes(1)
    expect(setIsMapInteracting).toHaveBeenNthCalledWith(1, true)
    expect(setIsMapInteracting).toHaveBeenNthCalledWith(2, false)
    expect(setIsMapInteracting).toHaveBeenNthCalledWith(3, true)
    expect(setIsMapInteracting).toHaveBeenNthCalledWith(4, false)
    expect(scheduleHotspotSync).toHaveBeenCalledTimes(6)
    expect(setMapViewport).toHaveBeenCalledTimes(2)
    expect(setMapViewport).toHaveBeenCalledWith(
      { lng: -170, lat: 22 },
      { west: -180, south: -90, east: 180, north: 90, crs: 'EPSG:4326' },
      6.2,
    )
    expect(emitMapPointSelect).toHaveBeenCalledTimes(1)
    expect(emitMapPointSelect).toHaveBeenCalledWith({ lng: 113.2, lat: 23.1 })

    handlers.get('click')?.({
      lngLat: { lng: 121, lat: 31 },
      originalEvent: { shiftKey: true },
    })
    expect(emitMapPointSelect).toHaveBeenCalledTimes(2)
    expect(emitMapPointSelect).toHaveBeenLastCalledWith({ lng: 121, lat: 31 })

    module.dispose()
    expect(map.off).toHaveBeenCalledTimes(9)
  })

  it('does not bind events twice', () => {
    const map = {
      getCenter: () => ({ lng: 0, lat: 0 }),
      getBounds: () => ({
        getSouth: () => 0,
        getNorth: () => 0,
        getWest: () => 0,
        getEast: () => 0,
      }),
      getZoom: () => 1,
      dragPan: {
        disable: vi.fn(),
        enable: vi.fn(),
      },
      on: vi.fn(),
      off: vi.fn(),
    } as any

    const module = createMapInteractionModule({
      map,
      layersStore: { setMapViewport: vi.fn() },
      getInteractionMode: () => 'move',
      setIsMapInteracting: vi.fn(),
      scheduleHotspotSync: vi.fn(),
      emitMapPointSelect: vi.fn(),
    })

    module.bindEvents()
    module.bindEvents()

    expect(map.on).toHaveBeenCalledTimes(9)
  })
})
