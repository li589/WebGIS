/**
 * Non-weather layer sync for MapCanvas: overlay-image rasters + imported vectors
 * + active-layer stack order. Weather overlays stay in the weather module bundle path.
 */
import { watch, type WatchStopHandle } from 'vue'

import { createOverlayImageModule } from './overlay-image-module'
import { createImportedLayerModule } from './imported-layer-module'
import { applyActiveLayerStackOrder } from './layer-stack-sync'
import type { ActiveLayer } from '../../stores/layers/types'

type MapInstance = import('maplibre-gl').Map

interface CreateMapCanvasNonWeatherLayerSyncModuleOptions {
  map: MapInstance
  getMapReady: () => boolean
  getActiveLayers: () => ActiveLayer[]
  getActiveVisibleCatalogIds: () => string[]
}

export interface MapCanvasNonWeatherLayerSyncModule {
  overlayImageModule: ReturnType<typeof createOverlayImageModule>
  importedLayerModule: ReturnType<typeof createImportedLayerModule>
  syncOverlayLayers: () => Promise<void>
  syncImportedLayers: (opts?: { fitNew?: boolean }) => void
  applyLayerStackOrder: () => void
  setupWatchers: () => void
  init: () => Promise<void>
  dispose: () => void
}

export function createMapCanvasNonWeatherLayerSyncModule(
  options: CreateMapCanvasNonWeatherLayerSyncModuleOptions,
): MapCanvasNonWeatherLayerSyncModule {
  const overlayImageModule = createOverlayImageModule({
    map: options.map,
    getMapReady: options.getMapReady,
    getActiveVisibleLayerIds: options.getActiveVisibleCatalogIds,
  })

  const importedLayerModule = createImportedLayerModule({
    map: options.map,
    getMapReady: options.getMapReady,
  })

  const stopHandles: WatchStopHandle[] = []

  function applyLayerStackOrder() {
    if (!options.getMapReady()) return
    applyActiveLayerStackOrder(options.map, options.getActiveLayers(), {
      getImportedVectorLayerIds: (instanceId) => importedLayerModule.getLayerIds(instanceId),
      getOverlayRasterLayerId: (overlayLayerId) =>
        overlayImageModule.getRasterLayerId(overlayLayerId),
    })
  }

  async function syncOverlayLayers() {
    const known = new Set(overlayImageModule.knownOverlayIds.value)
    const opacityByLayerId: Record<string, number> = {}
    const activeList: string[] = []
    const visibleList: string[] = []

    for (const layer of options.getActiveLayers()) {
      if (layer.importedRaster) {
        const overlayId = layer.importedRaster.overlayLayerId
        overlayImageModule.rememberOverlayId(overlayId)
        known.add(overlayId)
        activeList.push(overlayId)
        opacityByLayerId[overlayId] = layer.opacity
        if (layer.visible) visibleList.push(overlayId)
        continue
      }
      if (layer.importedVector || layer.isAdminBoundary) continue
      if (known.has(layer.catalogId)) {
        activeList.push(layer.catalogId)
        opacityByLayerId[layer.catalogId] = layer.opacity
        if (layer.visible) visibleList.push(layer.catalogId)
      }
    }

    await overlayImageModule.syncOverlays(activeList, visibleList, opacityByLayerId)
    applyLayerStackOrder()
  }

  function syncImportedLayers(opts: { fitNew?: boolean } = {}) {
    const imported = options.getActiveLayers().filter((l) => l.importedVector)
    const loadedIds = new Set(importedLayerModule.getLoadedIds())
    const newlyAdded: string[] = []
    for (const layer of imported) {
      const payload = layer.importedVector!
      if (payload.geojson && !loadedIds.has(layer.instanceId)) {
        importedLayerModule.addVectorLayer(
          layer.instanceId,
          payload.geojson,
          layer.name ?? payload.fileName ?? '导入图层',
        )
        if (importedLayerModule.getLoadedIds().includes(layer.instanceId)) {
          newlyAdded.push(layer.instanceId)
        }
      }
      loadedIds.delete(layer.instanceId)
    }
    for (const layer of imported) {
      importedLayerModule.setLayerVisibility(layer.instanceId, layer.visible)
      importedLayerModule.setLayerOpacity(layer.instanceId, layer.opacity)
    }
    for (const staleId of loadedIds) {
      importedLayerModule.removeLayer(staleId)
    }
    if (opts.fitNew && newlyAdded.length > 0) {
      importedLayerModule.fitLayers(newlyAdded)
    }
    applyLayerStackOrder()
  }

  function setupWatchers() {
    stopHandles.push(
      watch(
        () =>
          options
            .getActiveLayers()
            .filter((l) => l.importedRaster || (!l.importedVector && !l.isAdminBoundary))
            .map(
              (l) =>
                `${l.instanceId}:${l.catalogId}:${l.visible}:${l.opacity}:${l.importedRaster ? 'r' : 'c'}`,
            )
            .join(','),
        () => {
          void syncOverlayLayers()
        },
      ),
    )
    stopHandles.push(
      watch(
        () =>
          options
            .getActiveLayers()
            .map((l) => `${l.instanceId}:${l.order}`)
            .join(','),
        () => {
          applyLayerStackOrder()
        },
      ),
    )
    stopHandles.push(
      watch(
        () =>
          options
            .getActiveLayers()
            .filter((l) => l.importedVector)
            .map(
              (l) => `${l.instanceId}:${l.visible}:${l.opacity}:${l.importedVector!.featureCount}`,
            )
            .join(','),
        () => {
          syncImportedLayers({ fitNew: true })
        },
        { immediate: true },
      ),
    )
  }

  async function init() {
    await overlayImageModule.init()
    await syncOverlayLayers()
  }

  function dispose() {
    for (const stop of stopHandles) stop()
    stopHandles.length = 0
    overlayImageModule.dispose()
    importedLayerModule.dispose()
  }

  return {
    overlayImageModule,
    importedLayerModule,
    syncOverlayLayers,
    syncImportedLayers,
    applyLayerStackOrder,
    setupWatchers,
    init,
    dispose,
  }
}
