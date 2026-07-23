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
  getWindDisplayMode?: () => import('./wind-display-mode').WindDisplayMode
  getSmoothRendering?: () => boolean
  getDataVersion: () => number
  getCurrentHour: () => number
  scheduleSync: (reason?: 'move' | 'zoom' | 'data' | 'hour') => void
  debugLog: DebugLogger
}

export function watchWeatherOverlayInputs(
  options: WatchWeatherOverlayInputsOptions,
): WatchStopHandle {
  return watch(
    () =>
      buildWeatherOverlayWatchInputs(
        options.getActiveLayers(),
        options.getParticleFlowCatalogId(),
        options.getDataVersion(),
        options.getCurrentHour(),
        options.getWindDisplayMode?.() ?? 'off',
        options.getSmoothRendering?.() ?? true,
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
        'windMode',
        previous?.windDisplayMode,
        '->',
        next.windDisplayMode,
        'smoothRendering',
        previous?.smoothRendering,
        '->',
        next.smoothRendering,
        'layersHashChanged',
        diff.layersHashChanged,
        'dataVersionChanged',
        diff.dataVersionChanged,
        'hourChanged',
        diff.hourChanged,
      )
      // hour 与瓦片 coalesce 对齐；dataVersion 用 data 防抖（勿当 zoom，否则每块瓦片都短抖闪）
      // windDisplayMode / smoothRendering 变化用 hour 级短防抖（100ms），减少模式切换空窗
      const reason =
        diff.hourChanged || diff.windDisplayModeChanged || diff.smoothRenderingChanged
          ? 'hour'
          : 'data'
      options.scheduleSync(reason)
    },
  )
}
