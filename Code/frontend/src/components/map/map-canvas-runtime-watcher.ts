import { watch, type WatchStopHandle } from 'vue'

import type { TileSourceId } from '../../services/api-config'
import type { InteractionMode } from '../../stores/ui'

interface WatchBasemapSourceOptions {
  getTileSourceId: () => TileSourceId
  getMapReady: () => boolean
  onTileSourceChange: (sourceId: TileSourceId) => void
}

interface WatchInteractionModeOptions {
  getInteractionMode: () => InteractionMode
  getMapReady: () => boolean
  onInteractionModeChange: () => void
}

interface WatchAdminBoundaryOverlayOptions {
  getHasAdminBoundary: () => boolean
  getAdminBoundaryOpacity: () => number
  getMapReady: () => boolean
  onAdminBoundaryOverlayChange: () => void
}

interface WatchMeasureStateOptions {
  /** 轻量版本号：点数变化 / 结束绘制 / 清除时变化即可 */
  getMeasureSyncKey: () => string
  getMapReady: () => boolean
  onMeasureStateChange: () => void
}

export function watchBasemapSource(options: WatchBasemapSourceOptions): WatchStopHandle {
  return watch(
    () => ({
      sourceId: options.getTileSourceId(),
      mapReady: options.getMapReady(),
    }),
    ({ sourceId, mapReady }) => {
      if (!mapReady) return
      options.onTileSourceChange(sourceId)
    },
  )
}

export function watchInteractionMode(options: WatchInteractionModeOptions): WatchStopHandle {
  return watch(
    () => ({
      interactionMode: options.getInteractionMode(),
      mapReady: options.getMapReady(),
    }),
    ({ mapReady }) => {
      if (!mapReady) return
      options.onInteractionModeChange()
    },
  )
}

export function watchAdminBoundaryOverlay(
  options: WatchAdminBoundaryOverlayOptions,
): WatchStopHandle {
  return watch(
    () => ({
      hasAdminBoundary: options.getHasAdminBoundary(),
      adminBoundaryOpacity: options.getAdminBoundaryOpacity(),
      mapReady: options.getMapReady(),
    }),
    ({ mapReady }) => {
      if (!mapReady) return
      options.onAdminBoundaryOverlayChange()
    },
  )
}

export function watchMeasureState(options: WatchMeasureStateOptions): WatchStopHandle {
  return watch(
    () => ({
      key: options.getMeasureSyncKey(),
      mapReady: options.getMapReady(),
    }),
    ({ mapReady }) => {
      if (!mapReady) return
      options.onMeasureStateChange()
    },
  )
}
