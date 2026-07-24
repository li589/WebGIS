import type { WatchStopHandle } from 'vue'

import { focusMapOnHotspots } from './selected-layer-focus'
import { watchSelectedLayerFocus } from './selected-layer-focus-watcher'

type MapInstance = import('maplibre-gl').Map
type SelectedLayerGetter = () =>
  import('../../stores/layers/types').ActiveLayerDisplay | null | undefined
type DebugLogger = (module: string, ...args: unknown[]) => void

export interface SelectedLayerFocusModule {
  setupWatchers: () => void
  handleMapLoad: () => void
  dispose: () => void
}

interface CreateSelectedLayerFocusModuleOptions {
  map: MapInstance
  getSelectedLayer: SelectedLayerGetter
  scheduleHotspotSync: () => void
  debugLog: DebugLogger
  dependencies?: {
    focusMapOnHotspots?: typeof focusMapOnHotspots
    watchSelectedLayerFocus?: typeof watchSelectedLayerFocus
  }
}

export function createSelectedLayerFocusModule(
  options: CreateSelectedLayerFocusModuleOptions,
): SelectedLayerFocusModule {
  const focusMapOnHotspotsImpl = options.dependencies?.focusMapOnHotspots ?? focusMapOnHotspots
  const watchSelectedLayerFocusImpl =
    options.dependencies?.watchSelectedLayerFocus ?? watchSelectedLayerFocus

  let initialFocusDone = false
  let stopWatcher: WatchStopHandle | null = null

  function focusSelectedLayer() {
    const hotspots = options.getSelectedLayer()?.hotspots ?? []
    focusMapOnHotspotsImpl(options.map, hotspots)
  }

  function handleSelectionChange() {
    if (!initialFocusDone) {
      focusSelectedLayer()
    }
    options.scheduleHotspotSync()
  }

  function handleMapLoad() {
    focusSelectedLayer()
    initialFocusDone = true
    options.scheduleHotspotSync()
  }

  function setupWatchers() {
    if (stopWatcher) return
    stopWatcher = watchSelectedLayerFocusImpl({
      getSelectedLayer: options.getSelectedLayer,
      onSelectionChange: handleSelectionChange,
      debugLog: options.debugLog,
    })
  }

  function dispose() {
    stopWatcher?.()
    stopWatcher = null
  }

  return {
    setupWatchers,
    handleMapLoad,
    dispose,
  }
}
