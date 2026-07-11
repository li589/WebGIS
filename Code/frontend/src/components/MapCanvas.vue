<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'

import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import type { LayerHotspot } from '../stores/layers/types'
import { createMapCanvasActionBridge } from './map/map-canvas-action-bridge'
import { createMapCanvasExposeBridge } from './map/map-canvas-expose-bridge'
import { createMapCanvasLifecycleBinder } from './map/map-canvas-lifecycle-binder'
import { createMapCanvasMapOptions } from './map/map-canvas-map-options'
import { createMapCanvasModuleBundle } from './map/map-canvas-module-bundle'
import { createMapStagePresentationModule } from './map/map-stage-presentation-module'
import { createMapCanvasState } from './map/map-canvas-state'
import { createMapCanvasTeardownBinder } from './map/map-canvas-teardown-binder'
import {
  buildMapStageAppearanceModel,
  buildMapStageDisplayModel,
  buildFallbackActiveLayerDisplay,
  buildMapStageStatusModel,
  buildMapStageTimeVisualState,
} from './map/map-stage-view-model'
import { TILE_SOURCE_MAP, type TileSourceId } from '../services/api-config'

const layersStore = useLayersStore()
const uiStore = useUiStore()
const weatherTileManager = useWeatherTileManager()

const props = defineProps<{
  tileSourceId: TileSourceId
  currentHour: number
  hourLabel: string
}>()

const emit = defineEmits<{
  visibleHotspotsChange: [hotspots: LayerHotspot[]]
  hotspotSelect: [hotspot: LayerHotspot | null]
  mapPointSelect: [point: { lng: number; lat: number }]
}>()

const state = createMapCanvasState()
const {
  mapContainer,
  mapStageRef,
  hotspotPins,
  selectedHotspotId,
  mapReady,
  mapVisible,
  skeletonVisible,
  isMapInteracting,
  isSourceTransitioning,
  loadingLabel,
  tileLoadFailed,
  tileFailedProvider,
} = state

const teardownBinder = createMapCanvasTeardownBinder({
  getResources: () => state.resources,
  clearResources: state.clearResources,
})
const actionBridge = createMapCanvasActionBridge({
  getMapReady: () => mapReady.value,
  getHasAdminBoundary: () => hasAdminBoundary.value,
  getAdminBoundaryOpacity: () => adminBoundaryOpacity.value,
  getAdminBoundaryModule: () => state.resources.adminBoundaryModule,
  getBasemapModule: () => state.resources.basemapModule,
  getHotspotPinsModule: () => state.resources.hotspotPinsModule,
})
const exposeBridge = createMapCanvasExposeBridge({
  getMapStageElement: () => mapStageRef.value,
  getMap: () => state.resources.map,
})

defineExpose(exposeBridge)

function debugLog(module: string, ...args: unknown[]) {
  console.log(`[${performance.now().toFixed(1)}ms] [${module}]`, ...args)
}

const currentTileConfig = computed(() => TILE_SOURCE_MAP.get(props.tileSourceId) ?? TILE_SOURCE_MAP.get('esri-street')!)

// ── Derived from layersStore ──────────────────────────────────────────────────

const selectedLayer = computed(() => layersStore.selectedLayerDisplay)
const hasAdminBoundary = computed(() => layersStore.activeLayersDisplay.some((d) => d.isAdminBoundary))
const adminBoundaryOpacity = computed(() => {
  const layer = layersStore.activeLayersDisplay.find((d) => d.isAdminBoundary)
  return layer ? layer.opacity : 1
})

// Safe fallback for template (no selected layer = dark atmospheric state)
const activeLayer = computed(() => selectedLayer.value ?? buildFallbackActiveLayerDisplay())
const stageDisplayModel = computed(() => buildMapStageDisplayModel({
  basemapProvider: currentTileConfig.value.provider,
  basemapLabel: currentTileConfig.value.label,
  hourLabel: props.hourLabel,
  activeLayer: activeLayer.value,
}))
const stageStatusModel = computed(() => buildMapStageStatusModel({
  mapReady: mapReady.value,
  loadingLabel: loadingLabel.value,
  tileLoadFailed: tileLoadFailed.value,
  tileFailedProvider: tileFailedProvider.value,
}))
const stageAppearanceModel = computed(() => buildMapStageAppearanceModel({
  basemapStyle: currentTileConfig.value.style,
  activeLayer: activeLayer.value,
  timeVisualState: timeVisualState.value,
  isMapInteracting: isMapInteracting.value,
  isSourceTransitioning: isSourceTransitioning.value,
  mapVisible: mapVisible.value,
  skeletonVisible: skeletonVisible.value,
}))

// ─── Time-of-day visual vars ─────────────────────────────────────────────────

const timeVisualState = computed(() => buildMapStageTimeVisualState(props.currentHour))

// ─── Map init ────────────────────────────────────────────────────────────────

onMounted(async () => {
  if (!mapContainer.value) return

  const presentationModule = createMapStagePresentationModule({
    getMapContainer: () => mapContainer.value,
    getUsesLightNavigationTheme: () => stageAppearanceModel.value.usesLightNavigationTheme,
    setLoadingLabel: (label) => {
      loadingLabel.value = label
    },
    setMapVisible: (visible) => {
      mapVisible.value = visible
    },
    setSkeletonVisible: (visible) => {
      skeletonVisible.value = visible
    },
  })
  state.resources.mapStagePresentationModule = presentationModule
  await presentationModule.prepareMount()

  const { default: maplibregl } = await import('maplibre-gl')

  const mapInstance = new maplibregl.Map(createMapCanvasMapOptions({
    container: mapContainer.value,
  }))
  state.resources.map = mapInstance
  const moduleBundle = createMapCanvasModuleBundle({
    map: mapInstance,
    layersStore,
    weatherTileManager,
    getCurrentHour: () => props.currentHour,
    getMapReady: () => mapReady.value,
    getTileConfig: (sourceId) => TILE_SOURCE_MAP.get(sourceId),
    getCurrentTileSourceId: () => props.tileSourceId,
    setTileLoadFailed: (failed) => {
      tileLoadFailed.value = failed
    },
    setTileFailedProvider: (provider) => {
      tileFailedProvider.value = provider
    },
    setSourceTransitioning: (transitioning) => {
      isSourceTransitioning.value = transitioning
    },
    onAfterSourceSwitch: () => {
      presentationModule.scheduleNavigationThemeSync()
    },
    setLoadingLabel: (label) => {
      presentationModule.setLoadingLabel(label)
    },
    getSelectedLayer: () => selectedLayer.value,
    getSelectedHotspotId: () => selectedHotspotId.value,
    setSelectedHotspotId: (hotspotId) => {
      selectedHotspotId.value = hotspotId
    },
    emitVisibleHotspotsChange: (hotspots) => emit('visibleHotspotsChange', hotspots),
    emitHotspotSelect: (hotspot) => emit('hotspotSelect', hotspot),
    setHotspotPins: (pins) => {
      hotspotPins.value = pins
    },
    getInteractionMode: () => uiStore.interactionMode,
    setIsMapInteracting: (interacting) => {
      isMapInteracting.value = interacting
    },
    scheduleHotspotSync: actionBridge.scheduleHotspotSync,
    emitMapPointSelect: (point) => emit('mapPointSelect', point),
    getHasAdminBoundary: () => hasAdminBoundary.value,
    getAdminBoundaryOpacity: () => adminBoundaryOpacity.value,
    syncAdminOverlay: actionBridge.syncAdminOverlay,
    debugLog,
    weatherDebounceMs: 200,
  })
  state.resources.basemapModule = moduleBundle.basemapModule
  state.resources.adminBoundaryModule = moduleBundle.adminBoundaryModule
  state.resources.weatherOverlayModule = moduleBundle.weatherOverlayModule
  state.resources.hotspotPinsModule = moduleBundle.hotspotPinsModule
  state.resources.mapInteractionModule = moduleBundle.mapInteractionModule
  state.resources.mapCanvasRuntimeModule = moduleBundle.mapCanvasRuntimeModule
  state.resources.selectedLayerFocusModule = moduleBundle.selectedLayerFocusModule
  moduleBundle.weatherOverlayModule.setupWatchers()
  moduleBundle.mapInteractionModule.bindEvents()
  moduleBundle.mapCanvasRuntimeModule.setupWatchers()
  moduleBundle.selectedLayerFocusModule.setupWatchers()

  createMapCanvasLifecycleBinder({
    map: mapInstance,
    controls: {
      NavigationControl: maplibregl.NavigationControl,
      ScaleControl: maplibregl.ScaleControl,
    },
    onMapError: (event) => {
      moduleBundle.basemapModule.handleMapErrorEvent(event)
    },
    onMapLoad: async () => {
      moduleBundle.basemapModule.switchTileSource(props.tileSourceId)
      await moduleBundle.adminBoundaryModule.ensureLayers()
      mapReady.value = true
      actionBridge.syncAdminOverlay()
      moduleBundle.selectedLayerFocusModule.handleMapLoad()
      // 初始化 store 的地图视口，使首次工作流提交时能拿到正确中心点和 bbox
      moduleBundle.mapInteractionModule.syncViewportToStore()
      // 地图就绪后同步天气叠加层（之前 syncWeatherOverlay 在 mapReady=true 之前调用会被跳过）
      moduleBundle.weatherOverlayModule.runSyncNow()
      moduleBundle.mapInteractionModule.applyInteractionMode()
      presentationModule.revealMap()
    },
    scheduleNavigationThemeSync: () => {
      presentationModule.scheduleNavigationThemeSync()
    },
  }).bind()

})

onBeforeUnmount(() => {
  teardownBinder.dispose()
})
</script>

<template>
  <section
    ref="mapStageRef"
    class="map-stage"
    :class="stageAppearanceModel.stageClassNames"
    :style="stageAppearanceModel.stageStyleVars"
  >
    <div ref="mapContainer" class="map-host" :class="stageAppearanceModel.mapHostClassNames"></div>

    <!-- Skeleton -->
    <div class="map-skeleton" :class="stageAppearanceModel.skeletonClassNames" aria-hidden="true">
      <div class="skeleton-sweep"></div>
      <div class="skeleton-node skeleton-node-a"></div>
      <div class="skeleton-node skeleton-node-b"></div>
      <div class="skeleton-strip skeleton-strip-a"></div>
      <div class="skeleton-strip skeleton-strip-b"></div>
    </div>

    <!-- Atmosphere layers -->
    <div class="map-fog"></div>
    <div class="basemap-transition-mask"></div>
    <div class="time-sheen"></div>
    <div class="time-band"></div>
    <div class="weather-overlay"></div>
    <div class="grid-overlay"></div>

    <!-- Loading indicator -->
    <div v-if="stageStatusModel.showLoading" class="map-loading">
      <span class="loading-dot"></span>
      <span>{{ stageStatusModel.loadingLabel }}</span>
    </div>

    <!-- Tile error banner -->
    <div v-if="stageStatusModel.showTileError" class="tile-load-error">
      <span class="tile-error-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      </span>
      <span>{{ stageStatusModel.tileErrorMessage }}</span>
      <button class="tile-retry-btn" @click="actionBridge.retryTileLoad">{{ stageStatusModel.retryButtonLabel }}</button>
    </div>

    <!-- Map chips -->
    <div class="map-overlay">
      <span class="chip">
        {{ stageDisplayModel.basemapChipLabel }}
      </span>
      <span class="chip">{{ stageDisplayModel.hourChipLabel }}</span>
      <span class="chip secondary">{{ stageDisplayModel.layerChipLabel }}</span>
      <span class="chip" :class="stageDisplayModel.availabilityChipClass">
        {{ stageDisplayModel.availabilityChipLabel }}
      </span>
    </div>

    <!-- Layer info card -->
    <div class="map-note">
      <h2>{{ stageDisplayModel.noteTitle }}</h2>
      <p>{{ stageDisplayModel.noteSummary }}</p>
      <span class="map-note-meta">{{ stageDisplayModel.noteMeta }}</span>
      <div class="time-indicator" aria-hidden="true">
        <div class="time-indicator-fill"></div>
      </div>
    </div>

    <!-- Hotspot pins -->
    <div class="hotspot-layer" :class="stageDisplayModel.hotspotLayerClass" aria-hidden="true">
      <button
        v-for="pin in hotspotPins"
        :key="pin.id"
        class="hotspot-pin"
        :class="{ selected: pin.selected }"
        :style="{ left: pin.left, top: pin.top }"
        type="button"
        @click="actionBridge.handleHotspotPinClick(pin.id)"
      >
        <div class="hotspot-core"></div>
        <div class="hotspot-label">
          <strong>{{ pin.name }}</strong>
          <span>{{ pin.value }}</span>
        </div>
      </button>
    </div>
  </section>
</template>

<style scoped>
.map-stage {
  position: relative;
  min-height: calc(100vh - 1.5rem);
  overflow: hidden;
  border-radius: 1.4rem;
  border: 1px solid rgba(136, 192, 255, 0.16);
  background:
    radial-gradient(circle at top, rgba(66, 130, 255, 0.14), transparent 28rem),
    linear-gradient(180deg, rgba(6, 14, 26, 0.98), rgba(10, 19, 35, 0.94));
  /* 性能优化：contained paint layer */
  contain: layout style paint;
}

.map-host,
.map-fog,
.weather-overlay,
.grid-overlay,
.hotspot-layer {
  position: absolute;
  inset: 0;
}

.map-host {
  z-index: 0;
  opacity: 0.01;
  transition: opacity 0.45s ease;
}

.map-host.visible {
  opacity: 1;
}

.map-skeleton {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at 28% 36%, rgba(87, 166, 255, 0.18), transparent 16rem),
    linear-gradient(180deg, rgba(7, 16, 29, 0.98), rgba(10, 19, 35, 0.95));
  opacity: 1;
  transition: opacity 0.35s ease;
}

.map-skeleton.hidden {
  opacity: 0;
  pointer-events: none;
}

.map-skeleton.hidden .skeleton-sweep {
  animation-play-state: paused;
}

.skeleton-sweep,
.skeleton-node,
.skeleton-strip {
  position: absolute;
}

.skeleton-sweep {
  position: absolute;
  inset: 0;
  background: linear-gradient(110deg, transparent 26%, rgba(255, 255, 255, 0.08) 50%, transparent 74%);
  transform: translateX(-100%);
  animation: sweep 2.4s linear infinite;
  /* 性能优化：GPU 加速 */
  will-change: transform;
}

.skeleton-node {
  width: 0.9rem;
  height: 0.9rem;
  border-radius: 999px;
  background: rgba(138, 198, 255, 0.34);
  box-shadow: 0 0 0 10px rgba(82, 134, 255, 0.08);
}

.skeleton-node-a { top: 34%; left: 28%; }
.skeleton-node-b { top: 56%; left: 64%; }

.skeleton-strip {
  height: 0.7rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
}

.skeleton-strip-a { left: 1rem; bottom: 5rem; width: 10rem; }
.skeleton-strip-b { right: 1rem; bottom: 4.9rem; width: 7.6rem; }

.map-fog {
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(circle at 20% 18%, rgba(3, 12, 24, 0.06), transparent 18rem),
    linear-gradient(180deg, rgba(4, 11, 20, 0.01), rgba(4, 11, 20, 0.24));
}

.basemap-transition-mask {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  opacity: 0;
  background:
    radial-gradient(circle at 50% 48%, rgba(125, 192, 255, 0.08), transparent 18rem),
    linear-gradient(180deg, rgba(4, 11, 20, 0.08), rgba(4, 11, 20, 0.14));
  /* 性能优化：GPU 加速，仅 opacity 使用过渡 */
  transform: translateZ(0);
  will-change: opacity;
  transition: opacity 0.22s ease;
}

.time-sheen {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(
      circle at var(--horizon-position) 18%,
      rgba(255, 196, 120, var(--time-glow-opacity)),
      transparent 20rem
    ),
    linear-gradient(
      180deg,
      rgba(255, 181, 107, calc(var(--time-glow-opacity) * 0.35)) 0%,
      transparent 38%
    );
  /* 性能优化：GPU 加速，仅 opacity 使用过渡 */
  transform: translateZ(0);
  will-change: opacity;
  transition: opacity 0.35s ease;
}

.time-band {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background:
    radial-gradient(
      circle at var(--horizon-position) 72%,
      rgba(100, 140, 220, 0.18),
      transparent var(--stage-glow-spread)
    ),
    linear-gradient(
      180deg,
      transparent 58%,
      rgba(255, 255, 255, calc(var(--stage-band-opacity) * 0.16)) 100%
    );
  /* 性能优化：GPU 加速，仅 opacity 使用过渡 */
  transform: translateZ(0);
  will-change: opacity;
  opacity: 0.92;
  transition: opacity 0.35s ease;
}

.weather-overlay {
  z-index: 1;
  pointer-events: none;
  opacity: 0.24;
  background:
    radial-gradient(circle at 18% 30%, rgba(82, 134, 255, 0.12), transparent 18rem),
    radial-gradient(circle at 78% 24%, rgba(82, 134, 255, 0.12), transparent 20rem),
    radial-gradient(circle at 52% 72%, rgba(255, 255, 255, 0.06), transparent 16rem);
  /* 性能优化：移除 filter blur，改用背景渐变透明度，GPU 加速 */
  transform: translateZ(0);
  will-change: opacity;
}

.grid-overlay {
  z-index: 1;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px);
  background-size: 72px 72px;
  mask-image: linear-gradient(180deg, transparent, rgba(0, 0, 0, 0.6) 18%, rgba(0, 0, 0, 0.92));
  will-change: opacity;
}

.map-stage-interacting .weather-overlay,
.map-stage-interacting .time-sheen,
.map-stage-interacting .time-band,
.map-stage-interacting .grid-overlay {
  opacity: 0.08;
}

.map-stage-interacting .hotspot-layer {
  opacity: 0.4;
}

.map-stage-transitioning .basemap-transition-mask {
  opacity: 1;
}

.map-stage-transitioning .map-host {
  filter: saturate(0.92) brightness(0.92);
}

.map-stage-ready .weather-overlay { opacity: 0.28; }
.map-stage-ready .time-sheen { opacity: 1; }
.map-stage-ready .time-band { opacity: 1; }
.map-stage-partial .weather-overlay { opacity: 0.16; }
.map-stage-partial .grid-overlay { opacity: 0.32; }
.map-stage-empty .map-fog { background: radial-gradient(circle at 20% 18%, rgba(3, 12, 24, 0.12), transparent 18rem), linear-gradient(180deg, rgba(4, 11, 20, 0.08), rgba(4, 11, 20, 0.34)); }
.map-stage-empty .time-sheen { opacity: 0.38; }
.map-stage-empty .time-band { opacity: 0.46; }
.map-stage-empty .weather-overlay { opacity: 0.08; }
.map-stage-empty .grid-overlay { opacity: 0.2; }

.map-overlay {
  position: absolute;
  z-index: 21;
  top: 0;
  left: 0;
  right: auto;
  display: flex;
  gap: 0.38rem;
  flex-wrap: wrap;
  padding: 0.8rem 0.8rem 0;
  box-sizing: border-box;
  align-content: flex-start;
}

.chip {
  padding: 0.24rem 0.48rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.52);
  border: 1px solid rgba(136, 192, 255, 0.12);
  color: #eff7ff;
  font-size: 0.64rem;
}

.chip.secondary {
  color: #eaf7ff;
  border-color: rgba(90, 162, 255, 0.36);
  background: rgba(36, 90, 170, 0.16);
}

.chip-ready { color: #9ff8cf; border-color: rgba(114, 255, 207, 0.2); background: rgba(114, 255, 207, 0.08); }
.chip-partial { color: #ffd38a; border-color: rgba(255, 196, 120, 0.18); background: rgba(255, 196, 120, 0.08); }
.chip-empty { color: #d7c1ff; border-color: rgba(187, 137, 255, 0.18); background: rgba(187, 137, 255, 0.08); }

.map-note {
  position: absolute;
  z-index: 18;
  left: 1rem;
  bottom: 3.15rem;
  max-width: 13rem;
  display: grid;
  gap: 0.2rem;
  padding: 0.46rem 0.54rem;
  border-radius: 0.82rem;
  background: rgba(8, 18, 33, 0.72);
  border: 1px solid rgba(90, 162, 255, 0.12);
}

.map-note h2 { margin: 0; font-size: 0.76rem; color: #f3fbff; }
.map-note p { margin: 0; color: #96a8bb; font-size: 0.64rem; line-height: 1.32; }
.map-note-meta { color: #bfd3e6; font-size: 0.58rem; letter-spacing: 0.02em; }

.time-indicator {
  position: relative;
  height: 0.24rem;
  margin-top: 0.16rem;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.08);
}

.time-indicator-fill {
  width: var(--time-progress);
  height: 100%;
  border-radius: inherit;
  background: rgba(90, 106, 128, 0.25);
}

.hotspot-layer { z-index: 2; pointer-events: none; }
.hotspot-layer-ready .hotspot-pin { opacity: 1; }
.hotspot-layer-partial .hotspot-pin { opacity: 0.76; }
.hotspot-layer-empty .hotspot-pin { opacity: 0.38; }

.hotspot-pin {
  position: absolute;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0;
  border: none;
  background: transparent;
  appearance: none;
  pointer-events: auto;
  cursor: pointer;
  /* 性能优化：GPU 加速，仅 opacity 使用过渡 */
  will-change: opacity;
  transition: opacity 0.28s ease;
}

.hotspot-core {
  width: 0.74rem;
  height: 0.74rem;
  border-radius: 999px;
  background: var(--accent-color);
  transform: translateZ(0) scale(var(--hotspot-scale));
  box-shadow:
    0 0 0 0 rgba(255, 255, 255, 0.08),
    0 0 0 var(--hotspot-halo-size) rgba(90, 106, 128, 0.3);
  /* 性能优化：仅 GPU 属性过渡 */
  transition: transform 0.28s cubic-bezier(0.25, 0.46, 0.45, 0.94), box-shadow 0.28s ease;
}

.hotspot-label {
  margin-top: 0.4rem;
  padding: 0.32rem 0.42rem;
  border-radius: 0.8rem;
  background: rgba(4, 12, 23, 0.72);
  border: 1px solid rgba(136, 192, 255, 0.14);
  color: #e8f3fc;
  white-space: nowrap;
  box-shadow: 0 10px 18px rgba(1, 8, 16, 0.18);
  opacity: var(--hotspot-label-opacity);
  will-change: opacity;
  transition: opacity 0.28s ease;
  transform: translateZ(0);
}

.map-loading {
  position: absolute;
  inset: auto auto 1rem 1rem;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.5rem 0.72rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.88);
  border: 1px solid rgba(136, 192, 255, 0.16);
  color: #dfeefd;
  font-size: 0.74rem;
}

.loading-dot {
  width: 0.48rem;
  height: 0.48rem;
  border-radius: 999px;
  background: var(--accent-color);
  box-shadow: 0 0 0 6px rgba(90, 106, 128, 0.13);
}

.tile-load-error {
  position: absolute;
  top: 110px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.38rem 0.6rem 0.38rem 0.5rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.92);
  border: 1px solid rgba(255, 100, 100, 0.28);
  color: #ffb3b3;
  font-size: 0.64rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.24);
}

.tile-error-icon { display: flex; align-items: center; color: #ff9090; }

.tile-retry-btn {
  margin-left: 0.18rem;
  padding: 0.18rem 0.46rem;
  border-radius: 999px;
  border: 1px solid rgba(255, 140, 140, 0.3);
  background: rgba(255, 80, 80, 0.12);
  color: #ffc0c0;
  font-size: 0.6rem;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease;
}

.tile-retry-btn:hover {
  background: rgba(255, 80, 80, 0.22);
  color: #fff0f0;
}

.hotspot-label strong,
.hotspot-label span {
  display: block;
}
.hotspot-label strong { font-size: 0.64rem; }
.hotspot-label span { margin-top: 0.15rem; color: #99afc3; font-size: 0.6rem; }

:deep(.maplibregl-ctrl-bottom-right) {
  right: 0.8rem;
  bottom: 0.8rem;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.28rem;
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group) {
  display: flex;
  flex-direction: column;
  border-radius: 0.7rem;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(3, 10, 20, 0.18);
  background: rgba(8, 18, 33, 0.9);
  border: 1px solid rgba(136, 192, 255, 0.12);
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button) {
  width: 2rem;
  height: 2rem;
  background: transparent;
  border: none;
  color: #dbe8f5;
  box-shadow: none;
  border-radius: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: #f4fbff;
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button + button) {
  border-top: 1px solid rgba(136, 192, 255, 0.08);
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button .maplibregl-ctrl-icon) {
  filter: brightness(1.15) contrast(1.05);
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group),
.map-stage-light :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  background: rgba(8, 18, 33, 0.92);
  border-color: rgba(136, 192, 255, 0.12);
  box-shadow: 0 8px 24px rgba(3, 10, 20, 0.18);
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button),
.map-stage-light :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  color: #eaf3fb;
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button:hover) {
  background: rgba(255, 255, 255, 0.08);
  color: #ffffff;
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button .maplibregl-ctrl-icon) {
  filter: brightness(1.15) contrast(1.08);
}

.map-stage-light :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  color: #eaf3fb;
}

.map-stage-dark :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group),
.map-stage-dark :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  background: rgba(255, 255, 255, 0.9);
  border-color: rgba(18, 28, 44, 0.14);
  box-shadow: 0 8px 24px rgba(3, 10, 20, 0.16);
}

.map-stage-dark :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button),
.map-stage-dark :deep(.maplibregl-ctrl-bottom-left .maplibregl-ctrl-scale) {
  color: #203040;
}

.map-stage-dark :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button:hover) {
  background: rgba(24, 80, 160, 0.12);
  color: #10233a;
}

.map-stage-dark :deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-group button .maplibregl-ctrl-icon) {
  filter: brightness(0.42) contrast(1.15);
}
:deep(.maplibregl-ctrl-bottom-right .maplibregl-ctrl-scale) {
  border-radius: 0.6rem;
  border: none;
  background: rgba(8, 18, 33, 0.9);
  color: #eaf3fb;
  font-size: 0.64rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  padding: 0.32rem 0.6rem;
  box-shadow: 0 8px 24px rgba(3, 10, 20, 0.18);
  box-sizing: border-box;
}
:deep(.maplibregl-ctrl-attrib) { background: rgba(255, 255, 255, 0.8); }

@keyframes sweep { to { transform: translateX(100%); } }

@media (max-width: 820px) {
  .map-stage { min-height: calc(100vh - 1rem); }
  .map-overlay { top: 0; left: 0; padding: 0.75rem 0.75rem 0; }
  .map-note { left: 0.75rem; right: 0.75rem; bottom: 8.3rem; max-width: none; }
  :deep(.maplibregl-ctrl-bottom-left) { left: 0.75rem; bottom: 0.75rem; }
  :deep(.maplibregl-ctrl-bottom-right) { right: 0.75rem; bottom: 0.75rem; }
}
</style>
