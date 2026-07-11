import { describe, expect, it, vi } from 'vitest'

import { createHotspotPinsModule } from './hotspot-pins-module'

describe('hotspot-pins-module', () => {
  it('syncs visible hotspots, clears hidden selection, and writes display pins', () => {
    let selectedHotspotId: string | null = 'b'
    const setHotspotPins = vi.fn()
    const emitVisibleHotspotsChange = vi.fn()
    const emitHotspotSelect = vi.fn()

    const module = createHotspotPinsModule({
      map: {
        getZoom: () => 5.1,
        project: ([lng, lat]: [number, number]) => ({ x: lng * 10, y: lat * 10 }),
      } as any,
      getHotspots: () => [
        { id: 'a', name: 'A', lng: 1, lat: 2, value: '1' },
        { id: 'b', name: 'B', lng: 3, lat: 4, value: '2' },
      ],
      getSelectedHotspotId: () => selectedHotspotId,
      setSelectedHotspotId: (hotspotId) => {
        selectedHotspotId = hotspotId
      },
      emitVisibleHotspotsChange,
      emitHotspotSelect,
      setHotspotPins,
    })

    module.runSyncNow()

    expect(emitVisibleHotspotsChange).toHaveBeenCalledWith([
      { id: 'a', name: 'A', lng: 1, lat: 2, value: '1' },
    ])
    expect(selectedHotspotId).toBeNull()
    expect(emitHotspotSelect).toHaveBeenCalledWith(null)
    expect(setHotspotPins).toHaveBeenCalledWith([
      { id: 'a', name: 'A', value: '1', left: '10px', top: '20px', selected: false },
    ])
  })

  it('debounces scheduling with requestAnimationFrame and cancels on dispose', () => {
    let scheduledCallback: FrameRequestCallback | null = null
    const requestAnimationFrameMock = vi.fn((callback: FrameRequestCallback) => {
      scheduledCallback = callback
      return 9
    })
    const cancelAnimationFrameMock = vi.fn()
    const setHotspotPins = vi.fn()

    const module = createHotspotPinsModule({
      map: {
        getZoom: () => 7.2,
        project: ([lng, lat]: [number, number]) => ({ x: lng, y: lat }),
      } as any,
      getHotspots: () => [{ id: 'a', name: 'A', lng: 1, lat: 2, value: '1' }],
      getSelectedHotspotId: () => null,
      setSelectedHotspotId: vi.fn(),
      emitVisibleHotspotsChange: vi.fn(),
      emitHotspotSelect: vi.fn(),
      setHotspotPins,
      dependencies: {
        requestAnimationFrame: requestAnimationFrameMock,
        cancelAnimationFrame: cancelAnimationFrameMock,
      },
    })

    module.scheduleSync()
    module.scheduleSync()

    expect(requestAnimationFrameMock).toHaveBeenCalledTimes(1)
    expect(scheduledCallback).not.toBeNull()
    scheduledCallback!(16)
    expect(setHotspotPins).toHaveBeenCalledTimes(1)

    module.scheduleSync()
    module.dispose()
    expect(cancelAnimationFrameMock).toHaveBeenCalledWith(9)
  })

  it('toggles hotspot selection and emits the selected hotspot', () => {
    let selectedHotspotId: string | null = null
    const emitHotspotSelect = vi.fn()
    const setHotspotPins = vi.fn()

    const module = createHotspotPinsModule({
      map: {
        getZoom: () => 7.2,
        project: ([lng, lat]: [number, number]) => ({ x: lng * 10, y: lat * 10 }),
      } as any,
      getHotspots: () => [
        { id: 'a', name: 'A', lng: 1, lat: 2, value: '1' },
        { id: 'b', name: 'B', lng: 3, lat: 4, value: '2' },
      ],
      getSelectedHotspotId: () => selectedHotspotId,
      setSelectedHotspotId: (hotspotId) => {
        selectedHotspotId = hotspotId
      },
      emitVisibleHotspotsChange: vi.fn(),
      emitHotspotSelect,
      setHotspotPins,
    })

    module.toggleSelection('b')
    expect(selectedHotspotId).toBe('b')
    expect(emitHotspotSelect).toHaveBeenLastCalledWith({
      id: 'b',
      name: 'B',
      lng: 3,
      lat: 4,
      value: '2',
    })
    expect(setHotspotPins).toHaveBeenCalledWith([
      { id: 'b', name: 'B', value: '2', left: '30px', top: '40px', selected: true },
      { id: 'a', name: 'A', value: '1', left: '-62px', top: '20px', selected: false },
    ])

    module.toggleSelection('b')
    expect(selectedHotspotId).toBeNull()
    expect(emitHotspotSelect).toHaveBeenLastCalledWith(null)
  })
})
