import { createAdminBoundaryModule } from './admin-boundary-module'
import { createBasemapModule } from './basemap-module'
import { createHotspotPinsModule } from './hotspot-pins-module'
import { createMapInteractionModule } from './map-interaction-module'
import { createMapCanvasRuntimeModule } from './map-canvas-runtime-module'
import { createMapCanvasWeatherOverlayModule } from './map-canvas-weather-overlay-module'
import { createMeasureModule } from './measure-module'
import { createSelectedLayerFocusModule } from './selected-layer-focus-module'
import type { WeatherOverlayModule } from './weather-overlay-module'
import type { TileSourceConfig } from '../../services/api-config'

type MapInstance = import('maplibre-gl').Map
type TileSourceId = import('../../services/api-config').TileSourceId
type LayerHotspot = import('../../stores/layers/types').LayerHotspot
type ActiveLayerDisplay = import('../../stores/layers/types').ActiveLayerDisplay
type InteractionMode = import('../../stores/ui').InteractionMode
type MeasureState = import('../../stores/ui').MeasureState
type MeasurePoint = import('../../stores/ui').MeasurePoint
type DebugLogger = (module: string, ...args: unknown[]) => void

interface LayersStoreLike {
  activeLayersDisplay: ActiveLayerDisplay[]
  particleFlowCatalogId: string | null
  windDisplayMode: import('./wind-display-mode').WindDisplayMode
  isWeatherEngineLayer: (catalogId: string) => boolean
  setMapViewport: (
    center: { lng: number; lat: number },
    bbox: { west: number; south: number; east: number; north: number; crs: 'EPSG:4326' } | null,
    zoom?: number,
  ) => void
}

interface WeatherTileManagerLike {
  getMergedGeojsonForViewport: (catalogId: string) => import('./weather-overlay-registry').WeatherOverlayState['geojsonData']
  dataVersion: number
}

export interface MapCanvasModuleBundle {
  basemapModule: ReturnType<typeof createBasemapModule>
  adminBoundaryModule: ReturnType<typeof createAdminBoundaryModule>
  weatherOverlayModule: WeatherOverlayModule
  hotspotPinsModule: ReturnType<typeof createHotspotPinsModule>
  mapInteractionModule: ReturnType<typeof createMapInteractionModule>
  mapCanvasRuntimeModule: ReturnType<typeof createMapCanvasRuntimeModule>
  selectedLayerFocusModule: ReturnType<typeof createSelectedLayerFocusModule>
  measureModule: ReturnType<typeof createMeasureModule>
}

interface CreateMapCanvasModuleBundleOptions {
  map: MapInstance
  layersStore: LayersStoreLike
  weatherTileManager: WeatherTileManagerLike
  getCurrentHour: () => number
  getMapReady: () => boolean
  getTileConfig: (sourceId: TileSourceId) => TileSourceConfig | undefined
  getCurrentTileSourceId: () => TileSourceId
  setTileLoadFailed: (failed: boolean) => void
  setTileFailedProvider: (provider: string | null) => void
  setSourceTransitioning: (transitioning: boolean) => void
  onAfterSourceSwitch: () => void
  setLoadingLabel: (label: string) => void
  getSelectedLayer: () => ActiveLayerDisplay | null | undefined
  getSelectedHotspotId: () => string | null
  setSelectedHotspotId: (hotspotId: string | null) => void
  emitVisibleHotspotsChange: (hotspots: LayerHotspot[]) => void
  emitHotspotSelect: (hotspot: LayerHotspot | null) => void
  setHotspotPins: (pins: Array<{ id: string; name: string; value: string; left: string; top: string; selected: boolean }>) => void
  getInteractionMode: () => InteractionMode
  setIsMapInteracting: (interacting: boolean) => void
  scheduleHotspotSync: () => void
  emitMapPointSelect: (point: { lng: number; lat: number }) => void
  getHasAdminBoundary: () => boolean
  getAdminBoundaryOpacity: () => number
  syncAdminOverlay: () => void
  debugLog: DebugLogger
  weatherDebounceMs?: number
  // ── 测量模式相关 ──
  getMeasureState: () => MeasureState
  addMeasurePoint: (p: MeasurePoint) => void
  undoLastMeasurePoint: () => void
  completeMeasure: () => void
  setHoverPoint: (p: MeasurePoint | null) => void
  clearMeasure: () => void
  dependencies?: {
    createBasemapModule?: typeof createBasemapModule
    createAdminBoundaryModule?: typeof createAdminBoundaryModule
    createMapCanvasWeatherOverlayModule?: typeof createMapCanvasWeatherOverlayModule
    createHotspotPinsModule?: typeof createHotspotPinsModule
    createMapInteractionModule?: typeof createMapInteractionModule
    createMapCanvasRuntimeModule?: typeof createMapCanvasRuntimeModule
    createSelectedLayerFocusModule?: typeof createSelectedLayerFocusModule
    createMeasureModule?: typeof createMeasureModule
  }
}

export function createMapCanvasModuleBundle(
  options: CreateMapCanvasModuleBundleOptions,
): MapCanvasModuleBundle {
  const createBasemapModuleImpl = options.dependencies?.createBasemapModule ?? createBasemapModule
  const createAdminBoundaryModuleImpl =
    options.dependencies?.createAdminBoundaryModule ?? createAdminBoundaryModule
  const createMapCanvasWeatherOverlayModuleImpl =
    options.dependencies?.createMapCanvasWeatherOverlayModule ?? createMapCanvasWeatherOverlayModule
  const createHotspotPinsModuleImpl =
    options.dependencies?.createHotspotPinsModule ?? createHotspotPinsModule
  const createMapInteractionModuleImpl =
    options.dependencies?.createMapInteractionModule ?? createMapInteractionModule
  const createMapCanvasRuntimeModuleImpl =
    options.dependencies?.createMapCanvasRuntimeModule ?? createMapCanvasRuntimeModule
  const createSelectedLayerFocusModuleImpl =
    options.dependencies?.createSelectedLayerFocusModule ?? createSelectedLayerFocusModule
  const createMeasureModuleImpl =
    options.dependencies?.createMeasureModule ?? createMeasureModule

  const basemapModule = createBasemapModuleImpl({
    map: options.map,
    getTileConfig: options.getTileConfig,
    getCurrentTileSourceId: options.getCurrentTileSourceId,
    setTileLoadFailed: options.setTileLoadFailed,
    setTileFailedProvider: options.setTileFailedProvider,
    setSourceTransitioning: options.setSourceTransitioning,
    onAfterSourceSwitch: options.onAfterSourceSwitch,
  })

  const adminBoundaryModule = createAdminBoundaryModuleImpl({
    map: options.map,
    setLoadingLabel: options.setLoadingLabel,
  })

  const weatherOverlayModule = createMapCanvasWeatherOverlayModuleImpl({
    map: options.map,
    getMapReady: options.getMapReady,
    layersStore: options.layersStore,
    weatherTileManager: options.weatherTileManager,
    getCurrentHour: options.getCurrentHour,
    debugLog: options.debugLog,
    debounceMs: options.weatherDebounceMs,
  })

  const hotspotPinsModule = createHotspotPinsModuleImpl({
    map: options.map,
    getHotspots: () => options.getSelectedLayer()?.hotspots ?? [],
    getSelectedHotspotId: options.getSelectedHotspotId,
    setSelectedHotspotId: options.setSelectedHotspotId,
    emitVisibleHotspotsChange: options.emitVisibleHotspotsChange,
    emitHotspotSelect: options.emitHotspotSelect,
    setHotspotPins: options.setHotspotPins,
  })

  const mapInteractionModule = createMapInteractionModuleImpl({
    map: options.map,
    layersStore: options.layersStore,
    getInteractionMode: options.getInteractionMode,
    setIsMapInteracting: options.setIsMapInteracting,
    scheduleHotspotSync: options.scheduleHotspotSync,
    emitMapPointSelect: options.emitMapPointSelect,
  })

  // measureModule 在 mapCanvasRuntimeModule 之前创建，
  // 以便 onInteractionModeChange 回调能引用它（避免 TDZ）
  const measureModule = createMeasureModuleImpl({
    map: options.map,
    getInteractionMode: options.getInteractionMode,
    getMeasureState: options.getMeasureState,
    addMeasurePoint: options.addMeasurePoint,
    undoLastMeasurePoint: options.undoLastMeasurePoint,
    completeMeasure: options.completeMeasure,
    setHoverPoint: options.setHoverPoint,
    clearMeasure: options.clearMeasure,
  })

  const mapCanvasRuntimeModule = createMapCanvasRuntimeModuleImpl({
    getTileSourceId: options.getCurrentTileSourceId,
    getMapReady: options.getMapReady,
    getInteractionMode: options.getInteractionMode,
    getHasAdminBoundary: options.getHasAdminBoundary,
    getAdminBoundaryOpacity: options.getAdminBoundaryOpacity,
    getMeasureSyncKey: () => {
      const s = options.getMeasureState()
      return `${s.points.length}:${s.isDrawing ? 1 : 0}`
    },
    onTileSourceChange: (sourceId) => {
      basemapModule.scheduleTileSourceSwitch(sourceId)
    },
    onInteractionModeChange: () => {
      mapInteractionModule.applyInteractionMode()
      measureModule.applyMeasureMode()
    },
    onAdminBoundaryOverlayChange: options.syncAdminOverlay,
    onMeasureStateChange: () => {
      measureModule.syncFromStore()
    },
  })

  const selectedLayerFocusModule = createSelectedLayerFocusModuleImpl({
    map: options.map,
    getSelectedLayer: options.getSelectedLayer,
    scheduleHotspotSync: options.scheduleHotspotSync,
    debugLog: options.debugLog,
  })

  return {
    basemapModule,
    adminBoundaryModule,
    weatherOverlayModule,
    hotspotPinsModule,
    mapInteractionModule,
    mapCanvasRuntimeModule,
    selectedLayerFocusModule,
    measureModule,
  }
}
