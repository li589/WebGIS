import { describe, expect, it, vi } from 'vitest'

import { createSelectedLayerFocusModule } from './selected-layer-focus-module'

describe('selected-layer-focus-module', () => {
  it('focuses before initial load through watcher and only schedules after initial load', () => {
    const focusMapOnHotspots = vi.fn()
    const scheduleHotspotSync = vi.fn()
    const stopWatcher = vi.fn()
    let onSelectionChange: (() => void) | null = null

    const module = createSelectedLayerFocusModule({
      map: {} as any,
      getSelectedLayer: () => ({
        instanceId: 'layer-1',
        hotspots: [{ id: 'a', name: 'A', lng: 113, lat: 23, value: '1' }],
      } as any),
      scheduleHotspotSync,
      debugLog: vi.fn(),
      dependencies: {
        focusMapOnHotspots,
        watchSelectedLayerFocus: vi.fn((options) => {
          onSelectionChange = options.onSelectionChange
          return stopWatcher
        }),
      },
    })

    module.setupWatchers()
    expect(onSelectionChange).not.toBeNull()

    onSelectionChange!()
    expect(focusMapOnHotspots).toHaveBeenCalledTimes(1)
    expect(scheduleHotspotSync).toHaveBeenCalledTimes(1)

    module.handleMapLoad()
    expect(focusMapOnHotspots).toHaveBeenCalledTimes(2)
    expect(scheduleHotspotSync).toHaveBeenCalledTimes(2)

    onSelectionChange!()
    expect(focusMapOnHotspots).toHaveBeenCalledTimes(2)
    expect(scheduleHotspotSync).toHaveBeenCalledTimes(3)

    module.dispose()
    expect(stopWatcher).toHaveBeenCalledTimes(1)
  })

  it('does not setup watchers twice', () => {
    const watchSelectedLayerFocus = vi.fn(() => vi.fn())

    const module = createSelectedLayerFocusModule({
      map: {} as any,
      getSelectedLayer: () => null,
      scheduleHotspotSync: vi.fn(),
      debugLog: vi.fn(),
      dependencies: {
        focusMapOnHotspots: vi.fn(),
        watchSelectedLayerFocus,
      },
    })

    module.setupWatchers()
    module.setupWatchers()

    expect(watchSelectedLayerFocus).toHaveBeenCalledTimes(1)
  })
})
