import type { LayerHotspot } from '../../stores/layers/types'

export interface MapCanvasActionBridge {
  syncAdminOverlay: () => void
  retryTileLoad: () => void
  scheduleHotspotSync: () => void
  handleHotspotPinClick: (pinId: string) => void
}

interface CreateMapCanvasActionBridgeOptions {
  getMapReady: () => boolean
  getHasAdminBoundary: () => boolean
  getAdminBoundaryOpacity: () => number
  getAdminBoundaryModule: () => { syncOverlay: (show: boolean, opacity: number) => void } | null
  getBasemapModule: () => { retryTileLoad: () => void } | null
  getHotspotPinsModule: () => {
    scheduleSync: () => void
    toggleSelection: (pinId: string) => void
  } | null
  getActiveHotspots?: () => LayerHotspot[]
}

export function createMapCanvasActionBridge(
  options: CreateMapCanvasActionBridgeOptions,
): MapCanvasActionBridge {
  function syncAdminOverlay() {
    if (!options.getMapReady()) return
    options
      .getAdminBoundaryModule()
      ?.syncOverlay(options.getHasAdminBoundary(), options.getAdminBoundaryOpacity())
  }

  function retryTileLoad() {
    options.getBasemapModule()?.retryTileLoad()
  }

  function scheduleHotspotSync() {
    options.getHotspotPinsModule()?.scheduleSync()
  }

  function handleHotspotPinClick(pinId: string) {
    options.getHotspotPinsModule()?.toggleSelection(pinId)
  }

  return {
    syncAdminOverlay,
    retryTileLoad,
    scheduleHotspotSync,
    handleHotspotPinClick,
  }
}
