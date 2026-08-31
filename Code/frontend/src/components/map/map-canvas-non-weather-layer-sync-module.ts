/**
 * Non-weather layer sync for MapCanvas: overlay-image rasters + imported vectors
 * + active-layer stack order. Weather overlays stay in the weather module bundle path.
 */
import { watch, type WatchStopHandle } from 'vue'

import { createOverlayImageModule } from './overlay-image-module'
import { createImportedLayerModule } from './imported-layer-module'
import { applyActiveLayerStackOrder } from './layer-stack-sync'
import type { ActiveLayer } from '../../stores/layers/types'
import { resolveLayerDisplayLabel } from '../../stores/layers/layer-naming'

type MapInstance = import('maplibre-gl').Map

interface CreateMapCanvasNonWeatherLayerSyncModuleOptions {
  map: MapInstance
  getMapReady: () => boolean
  getActiveLayers: () => ActiveLayer[]
  getActiveVisibleCatalogIds: () => string[]
  /** P1 lifecycle 双写：将地图 overlay 时间状态回传给 layers store。 */
  onOverlayTimeStatesChanged?: (
    states: Array<{
      layerId: string
      category: string
      timeList: string[]
      currentTime: string | null
    }>,
  ) => void
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
  let onLayerRenamed: ((ev: Event) => void) | null = null

  function applyLayerStackOrder() {
    if (!options.getMapReady()) return
    applyActiveLayerStackOrder(options.map, options.getActiveLayers(), {
      getImportedVectorLayerIds: (instanceId) => importedLayerModule.getLayerIds(instanceId),
      getOverlayRasterLayerId: (overlayLayerId) =>
        overlayImageModule.getRasterLayerId(overlayLayerId),
    })
  }

  function publishOverlayTimeStates() {
    options.onOverlayTimeStatesChanged?.(
      overlayImageModule.overlayTimeStates.value.map((state) => ({
        layerId: state.layerId,
        category: state.category,
        timeList: [...state.timeList],
        currentTime: state.currentTime,
      })),
    )
  }

  async function syncOverlayLayers() {
    const known = new Set(overlayImageModule.knownOverlayIds.value)
    const opacityByLayerId: Record<string, number> = {}
    const styleByLayerId: Record<string, import('./overlay-image-module').OverlayStyleParams> = {}
    const activeList: string[] = []
    const visibleList: string[] = []

    for (const layer of options.getActiveLayers()) {
      const styleParams = {
        palette: layer.paletteOverride ?? undefined,
        vmin: layer.vminOverride ?? undefined,
        vmax: layer.vmaxOverride ?? undefined,
        nodataMode: layer.nodataMode ?? undefined,
        nodataColor: layer.nodataColor ?? undefined,
        forceStyle: Boolean(
          layer.paletteOverride ||
          layer.vminOverride != null ||
          layer.vmaxOverride != null ||
          (layer.nodataMode && layer.nodataMode !== 'transparent') ||
          layer.nodataColor,
        ),
      }
      if (layer.importedRaster) {
        const overlayId = layer.importedRaster.overlayLayerId
        overlayImageModule.rememberOverlayId(overlayId)
        known.add(overlayId)
        activeList.push(overlayId)
        opacityByLayerId[overlayId] = layer.opacity
        styleByLayerId[overlayId] = styleParams
        if (layer.visible) visibleList.push(overlayId)
        continue
      }
      if (layer.importedVector || layer.isAdminBoundary) continue
      if (known.has(layer.catalogId)) {
        activeList.push(layer.catalogId)
        opacityByLayerId[layer.catalogId] = layer.opacity
        styleByLayerId[layer.catalogId] = styleParams
        if (layer.visible) visibleList.push(layer.catalogId)
      }
    }

    await overlayImageModule.syncOverlays(activeList, visibleList, opacityByLayerId, styleByLayerId)
    publishOverlayTimeStates()
    applyLayerStackOrder()
  }

  /** 仅更新 overlay 透明度，不触发 setOverlayStyle（避免配色突变） */
  function syncOverlayOpacity() {
    if (!options.getMapReady()) return
    for (const layer of options.getActiveLayers()) {
      if (layer.importedVector || layer.isAdminBoundary) continue
      const overlayId = layer.importedRaster ? layer.importedRaster.overlayLayerId : layer.catalogId
      if (layer.importedRaster || overlayImageModule.knownOverlayIds.value.includes(overlayId)) {
        overlayImageModule.setOverlayOpacity(overlayId, layer.opacity)
      }
    }
  }

  function syncImportedLayers(opts: { fitNew?: boolean } = {}) {
    const imported = options.getActiveLayers().filter((l) => l.importedVector)
    const loadedIds = new Set(importedLayerModule.getLoadedIds())
    const newlyAdded: string[] = []
    for (const layer of imported) {
      const payload = layer.importedVector!
      if (!payload.geojson) continue
      // addVectorLayer 内部区分新增（addSource+addLayer）与已加载（geojson
      // 引用变化时仅 setData），空 FeatureCollection 也会注册 source/渲染层，
      // 待后续数据加载（revision 递增）后直接显示
      const wasLoaded = loadedIds.has(layer.instanceId)
      const label = resolveLayerDisplayLabel({
        name: layer.name,
        catalogId: layer.catalogId,
        fileStem: payload.fileName,
      })
      const ok = importedLayerModule.addVectorLayer(layer.instanceId, payload.geojson, label)
      if (ok && !wasLoaded) {
        newlyAdded.push(layer.instanceId)
      }
      loadedIds.delete(layer.instanceId)
    }
    for (const layer of imported) {
      importedLayerModule.setLayerVisibility(layer.instanceId, layer.visible)
      const payload = layer.importedVector
      const label = resolveLayerDisplayLabel({
        name: layer.name,
        catalogId: layer.catalogId,
        fileStem: payload?.fileName,
      })
      importedLayerModule.updateLayerDisplayName(layer.instanceId, label)
      const style = layer.importedVector?.style
      if (style) {
        importedLayerModule.applyLayerStyle(layer.instanceId, style, layer.opacity)
      } else {
        importedLayerModule.setLayerOpacity(layer.instanceId, layer.opacity)
      }
    }
    for (const staleId of loadedIds) {
      importedLayerModule.removeLayer(staleId)
    }
    if (opts.fitNew && newlyAdded.length > 0) {
      // 相机操作失败不得中断图层栈应用（2026-08-23 事故：fitBounds 抛
      // Invalid LngLat 炸穿 onMapLoad → 底图/分析面板全部不渲染）
      try {
        importedLayerModule.fitLayers(newlyAdded)
      } catch (error) {
        console.warn('[NonWeatherLayerSync] fitLayers failed (skipped)', error)
      }
    }
    applyLayerStackOrder()
  }

  function setupWatchers() {
    if (typeof window !== 'undefined') {
      onLayerRenamed = (ev: Event) => {
        const detail = (ev as CustomEvent<{ instanceId?: string; name?: string }>).detail
        if (!detail?.instanceId || !detail.name) return
        importedLayerModule.updateLayerDisplayName(detail.instanceId, detail.name)
      }
      window.addEventListener('cgda:layer-renamed', onLayerRenamed)
    }
    // 透明度专用 watcher — 仅更新 raster-opacity paint 属性，不触发 setOverlayStyle
    stopHandles.push(
      watch(
        () =>
          options
            .getActiveLayers()
            .filter((l) => l.importedRaster || (!l.importedVector && !l.isAdminBoundary))
            .map((l) => `${l.instanceId}:${l.opacity}`)
            .join(','),
        () => {
          syncOverlayOpacity()
        },
      ),
    )
    // 样式/结构 watcher — 不含 opacity，仅在结构或样式变更时全量同步
    stopHandles.push(
      watch(
        () =>
          options
            .getActiveLayers()
            .filter((l) => l.importedRaster || (!l.importedVector && !l.isAdminBoundary))
            .map(
              (l) =>
                `${l.instanceId}:${l.catalogId}:${l.visible}:${l.importedRaster ? 'r' : 'c'}:${l.paletteOverride ?? ''}:${l.vminOverride ?? ''}:${l.vmaxOverride ?? ''}:${l.nodataMode ?? ''}:${l.nodataColor ?? ''}`,
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
          overlayImageModule.overlayTimeStates.value
            .map((s) => `${s.layerId}:${s.currentTime ?? ''}:${s.timeList.join('|')}`)
            .join(','),
        () => publishOverlayTimeStates(),
        { immediate: true },
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
          `${options.getMapReady() ? 'ready' : 'pending'}|${options
            .getActiveLayers()
            .filter((l) => l.importedVector)
            .map(
              (l) =>
                `${l.instanceId}:${l.name ?? ''}:${l.visible}:${l.opacity}:${l.importedVector!.revision ?? 0}:${l.importedVector!.featureCount}:${JSON.stringify(l.importedVector!.style ?? null)}`,
            )
            .join(',')}`,
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
    if (onLayerRenamed && typeof window !== 'undefined') {
      window.removeEventListener('cgda:layer-renamed', onLayerRenamed)
      onLayerRenamed = null
    }
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
