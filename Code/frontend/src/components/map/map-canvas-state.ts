import { ref, type Ref } from 'vue'

import { createAdminBoundaryModule } from './admin-boundary-module'
import { createBasemapModule } from './basemap-module'
import { createHotspotPinsModule } from './hotspot-pins-module'
import { createMapInteractionModule } from './map-interaction-module'
import { createMapCanvasRuntimeModule } from './map-canvas-runtime-module'
import { createMapStagePresentationModule } from './map-stage-presentation-module'
import { createMeasureModule } from './measure-module'
import { createSelectedLayerFocusModule } from './selected-layer-focus-module'
import type { WeatherOverlayModule } from './weather-overlay-module'

type MapInstance = import('maplibre-gl').Map

export interface MapCanvasState {
  mapContainer: Ref<HTMLElement | null>
  mapStageRef: Ref<HTMLElement | null>
  hotspotPins: Ref<Array<{
    id: string
    name: string
    value: string
    left: string
    top: string
    selected: boolean
  }>>
  selectedHotspotId: Ref<string | null>
  mapReady: Ref<boolean>
  mapVisible: Ref<boolean>
  skeletonVisible: Ref<boolean>
  isMapInteracting: Ref<boolean>
  isSourceTransitioning: Ref<boolean>
  loadingLabel: Ref<string>
  tileLoadFailed: Ref<boolean>
  tileFailedProvider: Ref<string | null>
  resources: {
    map: MapInstance | null
    adminBoundaryModule: ReturnType<typeof createAdminBoundaryModule> | null
    basemapModule: ReturnType<typeof createBasemapModule> | null
    mapStagePresentationModule: ReturnType<typeof createMapStagePresentationModule> | null
    weatherOverlayModule: WeatherOverlayModule | null
    hotspotPinsModule: ReturnType<typeof createHotspotPinsModule> | null
    mapInteractionModule: ReturnType<typeof createMapInteractionModule> | null
    mapCanvasRuntimeModule: ReturnType<typeof createMapCanvasRuntimeModule> | null
    selectedLayerFocusModule: ReturnType<typeof createSelectedLayerFocusModule> | null
    measureModule: ReturnType<typeof createMeasureModule> | null
  }
  clearResources: () => void
}

export function createMapCanvasState(): MapCanvasState {
  const state: MapCanvasState = {
    mapContainer: ref<HTMLElement | null>(null),
    mapStageRef: ref<HTMLElement | null>(null),
    hotspotPins: ref([]),
    selectedHotspotId: ref<string | null>(null),
    mapReady: ref(false),
    mapVisible: ref(false),
    skeletonVisible: ref(true),
    isMapInteracting: ref(false),
    isSourceTransitioning: ref(false),
    loadingLabel: ref('正在加载地图...'),
    tileLoadFailed: ref(false),
    tileFailedProvider: ref<string | null>(null),
    resources: {
      map: null,
      adminBoundaryModule: null,
      basemapModule: null,
      mapStagePresentationModule: null,
      weatherOverlayModule: null,
      hotspotPinsModule: null,
      mapInteractionModule: null,
      mapCanvasRuntimeModule: null,
      selectedLayerFocusModule: null,
      measureModule: null,
    },
    clearResources: () => {
      state.resources.map = null
      state.resources.adminBoundaryModule = null
      state.resources.basemapModule = null
      state.resources.mapStagePresentationModule = null
      state.resources.weatherOverlayModule = null
      state.resources.hotspotPinsModule = null
      state.resources.mapInteractionModule = null
      state.resources.mapCanvasRuntimeModule = null
      state.resources.selectedLayerFocusModule = null
      state.resources.measureModule = null
    },
  }

  return state
}
