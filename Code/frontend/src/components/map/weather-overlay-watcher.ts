import { watch, type WatchStopHandle } from 'vue'

import {
  buildWeatherOverlayWatchInputs,
  diffWeatherOverlayWatchInputs,
  type WeatherOverlayWatchInputs,
} from './weather-overlay-watch-adapter'

type ActiveLayersGetter = () => import('../../stores/layers/types').ActiveLayerDisplay[]
type DebugLogger = (module: string, ...args: unknown[]) => void

interface WatchWeatherOverlayInputsOptions {
  getActiveLayers: ActiveLayersGetter
  getParticleFlowCatalogId: () => string | null
  getDataVersion: () => number
  getCurrentHour: () => number
  scheduleSync: () => void
  debugLog: DebugLogger
}

export function watchWeatherOverlayInputs(
  options: WatchWeatherOverlayInputsOptions,
): WatchStopHandle {
  return watch(
    () => buildWeatherOverlayWatchInputs(
      options.getActiveLayers(),
      options.getParticleFlowCatalogId(),
      options.getDataVersion(),
      options.getCurrentHour(),
    ),
    (next: WeatherOverlayWatchInputs, previous?: WeatherOverlayWatchInputs) => {
      const diff = diffWeatherOverlayWatchInputs(next, previous)
      options.debugLog(
        'MapCanvas',
        'watcher fired',
        'flowId',
        previous?.particleFlowCatalogId,
        '->',
        next.particleFlowCatalogId,
        'layersHashChanged',
        diff.layersHashChanged,
        'dataVersionChanged',
        diff.dataVersionChanged,
        'hourChanged',
        diff.hourChanged,
      )
      options.scheduleSync()
    },
  )
}
