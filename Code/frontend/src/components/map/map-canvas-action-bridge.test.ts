import { describe, expect, it, vi } from 'vitest'

import { createMapCanvasActionBridge } from './map-canvas-action-bridge'

describe('map-canvas-action-bridge', () => {
  it('bridges admin overlay, retry, hotspot sync, and hotspot click actions', () => {
    const syncOverlay = vi.fn()
    const retryTileLoad = vi.fn()
    const scheduleSync = vi.fn()
    const toggleSelection = vi.fn()

    const bridge = createMapCanvasActionBridge({
      getMapReady: () => true,
      getHasAdminBoundary: () => true,
      getAdminBoundaryOpacity: () => 0.6,
      getAdminBoundaryModule: () => ({ syncOverlay }),
      getBasemapModule: () => ({ retryTileLoad }),
      getHotspotPinsModule: () => ({ scheduleSync, toggleSelection }),
    })

    bridge.syncAdminOverlay()
    bridge.retryTileLoad()
    bridge.scheduleHotspotSync()
    bridge.handleHotspotPinClick('pin-1')

    expect(syncOverlay).toHaveBeenCalledWith(true, 0.6)
    expect(retryTileLoad).toHaveBeenCalledTimes(1)
    expect(scheduleSync).toHaveBeenCalledTimes(1)
    expect(toggleSelection).toHaveBeenCalledWith('pin-1')
  })

  it('skips admin overlay sync until the map is ready', () => {
    const syncOverlay = vi.fn()

    const bridge = createMapCanvasActionBridge({
      getMapReady: () => false,
      getHasAdminBoundary: () => true,
      getAdminBoundaryOpacity: () => 0.6,
      getAdminBoundaryModule: () => ({ syncOverlay }),
      getBasemapModule: () => null,
      getHotspotPinsModule: () => null,
    })

    bridge.syncAdminOverlay()

    expect(syncOverlay).not.toHaveBeenCalled()
  })
})
