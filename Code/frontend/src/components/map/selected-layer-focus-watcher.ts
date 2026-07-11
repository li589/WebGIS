import { watch, type WatchStopHandle } from 'vue'

import {
  buildSelectedLayerFocusWatchInputs,
  diffSelectedLayerFocusWatchInputs,
  type SelectedLayerFocusWatchInputs,
} from './selected-layer-focus-watch-adapter'

type SelectedLayerGetter = () => import('../../stores/layers/types').ActiveLayerDisplay | null | undefined
type DebugLogger = (module: string, ...args: unknown[]) => void

interface WatchSelectedLayerFocusOptions {
  getSelectedLayer: SelectedLayerGetter
  onSelectionChange: () => void
  debugLog: DebugLogger
}

export function watchSelectedLayerFocus(
  options: WatchSelectedLayerFocusOptions,
): WatchStopHandle {
  return watch(
    () => buildSelectedLayerFocusWatchInputs(options.getSelectedLayer()),
    (next: SelectedLayerFocusWatchInputs, previous?: SelectedLayerFocusWatchInputs) => {
      const diff = diffSelectedLayerFocusWatchInputs(next, previous)
      options.debugLog(
        'MapCanvas',
        'selected layer watcher fired',
        'instanceChanged',
        diff.instanceChanged,
        'hotspotsChanged',
        diff.hotspotsChanged,
      )
      options.onSelectionChange()
    },
  )
}
