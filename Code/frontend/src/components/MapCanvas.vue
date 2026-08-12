<script setup lang="ts">
import { MapChromeNavigationControl } from './map/map-chrome-controls'

import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { AlertTriangle } from './ui/icons'
import { useLayersStore } from '../stores/layers'
import { useLayerWorkspace, useLayerViewport } from '../stores/layers/selectors'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import type { LayerHotspot } from '../stores/layers/types'
import { createMapCanvasActionBridge } from './map/map-canvas-action-bridge'
import { createMapCanvasExposeBridge } from './map/map-canvas-expose-bridge'
import { createMapCanvasLifecycleBinder } from './map/map-canvas-lifecycle-binder'
import { createMapCanvasMapOptions } from './map/map-canvas-map-options'
import { createMapCanvasModuleBundle } from './map/map-canvas-module-bundle'
import type { MapCanvasNonWeatherLayerSyncModule } from './map/map-canvas-non-weather-layer-sync-module'
import { createMapStagePresentationModule } from './map/map-stage-presentation-module'
import { createMapCanvasState } from './map/map-canvas-state'
import { createMapCanvasTeardownBinder } from './map/map-canvas-teardown-binder'
import type { OverlayTimeState } from './map/overlay-image-module'
import { validateOverlayBounds } from './map/overlay-image-module'
import {
  buildMapStageAppearanceModel,
  buildMapStageDisplayModel,
  buildFallbackActiveLayerDisplay,
  buildMapStageStatusModel,
  buildMapStageTimeVisualState,
} from './map/map-stage-view-model'
import { aggregateWeatherTileBanner } from './map/weather-tile-banner'
import { TILE_SOURCE_MAP, getDefaultTileSource, type TileSourceId } from '../services/api-config'
import { isGlobalMapViewport } from '../utils/map-viewport'
import {
  isMapDistributionChromeEnabled,
  subscribeMapDistributionChrome,
} from '../services/settings-local'
import {
  dataWorkspaceHighlight,
  dataWorkspaceZoomRequest,
  showToast,
} from '../data-manager/core/workspace-store'
import { debugLog as probeDebugLog } from '../utils/perf-probe'

const layersStore = useLayersStore() // createMapCanvasModuleBundle 需完整 store 实例
const workspace = useLayerWorkspace()
const viewport = useLayerViewport()
const uiStore = useUiStore()
const logStore = useLogStore()
const weatherTileManager = useWeatherTileManager()
const { statusVersion: weatherStatusVersion, activityVersion: weatherActivityVersion } =
  storeToRefs(weatherTileManager)

const props = defineProps<{
  tileSourceId: TileSourceId
  currentHour: number
  hourLabel: string
  /** 地图点查选中坐标（持久标记，非定位标记） */
  inspectPoint?: { lng: number; lat: number } | null
}>()

const emit = defineEmits<{
  visibleHotspotsChange: [hotspots: LayerHotspot[]]
  hotspotSelect: [hotspot: LayerHotspot | null]
  mapPointSelect: [point: { lng: number; lat: number }]
  overlayTimeUpdate: [states: OverlayTimeState[]]
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
  selectHotspot: (pinId: string) => actionBridge.handleHotspotPinClick(pinId),
  setWindAnimationPaused: (paused: boolean) => {
    state.resources.weatherOverlayModule?.setAnimationPaused(paused)
  },
  fitToLayerExtent: (instanceId: string) => fitToLayerExtent(instanceId),
  setOverlayTime: (layerId: string, time: string) => {
    void overlayImageModule?.setOverlayTime(layerId, time)
  },
})

defineExpose(exposeBridge)

function fitToLayerExtent(instanceId: string): boolean {
  const map = state.resources.map
  if (!map) return false

  const layer = workspace.activeLayers.value.find((l) => l.instanceId === instanceId)
  const display = workspace.activeLayersDisplay.value.find((l) => l.instanceId === instanceId)
  if (!layer && !display) {
    showToast('未找到图层，无法缩放', true)
    return false
  }

  let bounds: [number, number, number, number] | null | undefined =
    layer?.importedVector?.bounds ??
    layer?.importedRaster?.bounds ??
    display?.importedBounds ??
    display?.importedRasterBounds

  if (!bounds) {
    const overlayId = layer?.importedRaster?.overlayLayerId ?? display?.catalogId
    if (overlayId && overlayImageModule) {
      const st = overlayImageModule.overlayTimeStates.value.find((s) => s.layerId === overlayId)
      bounds = st?.bounds ?? null
    }
  }

  if (!bounds && layer?.importedVector) {
    const mod = state.resources.nonWeatherLayerSyncModule?.importedLayerModule
    if (mod) {
      mod.fitLayers([instanceId])
      return true
    }
  }

  if (!bounds) {
    showToast('该图层暂无可用显示范围', true, 3500)
    return false
  }

  const check = validateOverlayBounds(bounds)
  if (!check.ok) {
    showToast(`无法缩放到图层：${check.reason}`, true, 5000)
    return false
  }
  const [w, s, e, n] = check.bounds
  const pad = 0.0001
  let west = w
  let south = s
  let east = e
  let north = n
  if (east - west < pad) {
    west -= pad
    east += pad
  }
  if (north - south < pad) {
    south -= pad
    north += pad
  }
  map.fitBounds(
    [
      [west, south],
      [east, north],
    ],
    { padding: 48, maxZoom: 14, duration: 600 },
  )
  return true
}

// ─── Overlay image module (via non-weather sync module) ──────────────────────
let overlayImageModule: MapCanvasNonWeatherLayerSyncModule['overlayImageModule'] | null = null
// 响应式句柄：overlayImageModule 是异步挂载后才赋值的普通变量，直接放进 computed
// 会因 `?.` 短路而丢失依赖追踪（永远为空数组）。用 shallowRef 保证赋值后 watcher 触发。
const overlayImageModuleRef = shallowRef<
  MapCanvasNonWeatherLayerSyncModule['overlayImageModule'] | null
>(null)
const overlayTimeStates = computed(() => overlayImageModuleRef.value?.overlayTimeStates.value ?? [])

// 透传 overlay 时间状态到父组件
watch(
  overlayTimeStates,
  (states) => {
    emit('overlayTimeUpdate', states)
  },
  { deep: true },
)

function debugLog(module: string, ...args: unknown[]) {
  probeDebugLog(`[${performance.now().toFixed(1)}ms] [${module}]`, ...args)
}

const currentTileConfig = computed(
  () => TILE_SOURCE_MAP.get(props.tileSourceId) ?? TILE_SOURCE_MAP.get(getDefaultTileSource())!,
)

// ── Derived from layersStore ──────────────────────────────────────────────────

const selectedLayer = computed(() => workspace.selectedLayerDisplay.value)
const hasAdminBoundary = computed(() =>
  workspace.activeLayersDisplay.value.some((d) => d.isAdminBoundary),
)
const adminBoundaryOpacity = computed(() => {
  const layer = workspace.activeLayersDisplay.value.find((d) => d.isAdminBoundary)
  return layer ? layer.opacity : 1
})

// Safe fallback for template (no selected layer = dark atmospheric state)
const activeLayer = computed(() => selectedLayer.value ?? buildFallbackActiveLayerDisplay())
const stageDisplayModel = computed(() =>
  buildMapStageDisplayModel({
    basemapProvider: currentTileConfig.value.provider,
    basemapLabel: currentTileConfig.value.label,
    hourLabel: props.hourLabel,
    activeLayer: activeLayer.value,
  }),
)
const stageStatusModel = computed(() =>
  buildMapStageStatusModel({
    mapReady: mapReady.value,
    loadingLabel: loadingLabel.value,
    tileLoadFailed: tileLoadFailed.value,
    tileFailedProvider: tileFailedProvider.value,
  }),
)

// 天气瓦片加载/错误/半覆盖状态：按层隔离聚合（单层无数据不盖住健康层）
const weatherTileStatusModel = computed(() => {
  // statusVersion：错误/补洞；activityVersion：瓦片入队/完成（缩放中途加载进度）
  void weatherStatusVersion.value
  void weatherActivityVersion.value
  const weatherLayers = workspace.activeLayersDisplay.value.filter(
    (l) => l.visible && workspace.isWeatherEngineLayer(l.catalogId),
  )
  return aggregateWeatherTileBanner(
    weatherLayers.map((layer) => {
      const status = weatherTileManager.getLayerStatus(layer.catalogId)
      return {
        label: layer.name || layer.metricLabel || layer.catalogId,
        active: status.active,
        cachedInViewport: status.cachedInViewport,
        missingInViewport: status.missingInViewport,
        pending: status.pending,
        gapSweepActive: status.gapSweepActive,
        errorType: status.errorType,
        errorMessage: status.errorMessage,
      }
    }),
  )
})
const mapDistributionChromeEnabled = ref(isMapDistributionChromeEnabled())
const unsubscribeMapChrome = subscribeMapDistributionChrome(() => {
  mapDistributionChromeEnabled.value = isMapDistributionChromeEnabled()
})

const stageAppearanceModel = computed(() =>
  buildMapStageAppearanceModel({
    basemapStyle: currentTileConfig.value.style,
    activeLayer: activeLayer.value,
    timeVisualState: timeVisualState.value,
    isMapInteracting: isMapInteracting.value,
    isSourceTransitioning: isSourceTransitioning.value,
    mapVisible: mapVisible.value,
    skeletonVisible: skeletonVisible.value,
    isGlobalViewport: isGlobalMapViewport(viewport.currentMapBBox.value),
    hasVisibleDataLayers: workspace.activeLayers.value.some(
      (layer) => layer.visible && !layer.isAdminBoundary,
    ),
    distributionChromeEnabled: mapDistributionChromeEnabled.value,
  }),
)

// ─── Time-of-day visual vars ─────────────────────────────────────────────────

const timeVisualState = computed(() => buildMapStageTimeVisualState(props.currentHour))

// ─── Map init ────────────────────────────────────────────────────────────────

onMounted(async () => {
  if (!mapContainer.value) return

  try {
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

    const mapInstance = new maplibregl.Map(
      createMapCanvasMapOptions({
        container: mapContainer.value,
      }),
    )
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
      weatherDebounceMs: 350,
      getMeasureState: () => uiStore.measureState,
      addMeasurePoint: (p) => uiStore.addMeasurePoint(p),
      undoLastMeasurePoint: () => uiStore.undoLastMeasurePoint(),
      completeMeasure: () => uiStore.completeMeasure(),
      setHoverPoint: (p) => uiStore.setHoverPoint(p),
      clearMeasure: () => uiStore.clearMeasure(),
    })
    state.resources.basemapModule = moduleBundle.basemapModule
    state.resources.adminBoundaryModule = moduleBundle.adminBoundaryModule
    state.resources.weatherOverlayModule = moduleBundle.weatherOverlayModule
    state.resources.nonWeatherLayerSyncModule = moduleBundle.nonWeatherLayerSyncModule
    state.resources.hotspotPinsModule = moduleBundle.hotspotPinsModule
    state.resources.mapInteractionModule = moduleBundle.mapInteractionModule
    state.resources.mapCanvasRuntimeModule = moduleBundle.mapCanvasRuntimeModule
    state.resources.selectedLayerFocusModule = moduleBundle.selectedLayerFocusModule
    state.resources.measureModule = moduleBundle.measureModule
    overlayImageModule = moduleBundle.nonWeatherLayerSyncModule.overlayImageModule
    overlayImageModuleRef.value = moduleBundle.nonWeatherLayerSyncModule.overlayImageModule
    moduleBundle.weatherOverlayModule.setupWatchers()
    moduleBundle.nonWeatherLayerSyncModule.setupWatchers()
    void moduleBundle.nonWeatherLayerSyncModule.init()
    moduleBundle.mapInteractionModule.bindEvents()
    moduleBundle.mapCanvasRuntimeModule.setupWatchers()
    moduleBundle.selectedLayerFocusModule.setupWatchers()
    moduleBundle.measureModule.bindEvents()
    watch(
      dataWorkspaceHighlight,
      (hl) => {
        const mod = moduleBundle.nonWeatherLayerSyncModule.importedLayerModule
        if (!hl) {
          for (const id of mod.getLoadedIds()) mod.setFeatureHighlight(id, null)
          return
        }
        for (const id of mod.getLoadedIds()) {
          if (id !== hl.instanceId) mod.setFeatureHighlight(id, null)
        }
        mod.setFeatureHighlight(hl.instanceId, hl.feature)
      },
      { deep: false },
    )

    watch(
      dataWorkspaceZoomRequest,
      (req) => {
        if (!req || !mapInstance) return
        const [west, south, east, north] = req.bbox
        mapInstance.fitBounds(
          [
            [west, south],
            [east, north],
          ],
          { padding: 80, maxZoom: 14, duration: 600 },
        )
      },
      { deep: false },
    )

    createMapCanvasLifecycleBinder({
      map: mapInstance,
      controls: {
        NavigationControl: MapChromeNavigationControl,
      },
      onLocate: handleLocateMe,
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
        // 同样补同步导入层：mapReady 前 addVectorLayer 会 no-op
        moduleBundle.nonWeatherLayerSyncModule.syncImportedLayers({ fitNew: true })
        void moduleBundle.nonWeatherLayerSyncModule.syncOverlayLayers()
        moduleBundle.mapInteractionModule.applyInteractionMode()
        // 测量模式初始状态同步（mapInteractionModule 已处理 dragPan，measureModule 处理 doubleClickZoom/boxZoom + Canvas show）
        moduleBundle.measureModule.applyMeasureMode()
        presentationModule.revealMap()
      },
      scheduleNavigationThemeSync: () => {
        presentationModule.scheduleNavigationThemeSync()
      },
    }).bind()
  } catch (err) {
    console.error('[MapCanvas] initialization failed:', err)
    logStore.logOperation('map-init-error', `地图初始化失败: ${err}`)
    skeletonVisible.value = false
  }
})

onBeforeUnmount(() => {
  unsubscribeMapChrome()
  teardownBinder.dispose()
  overlayImageModule = null
  _clearLocationMarker()
  _clearInspectMarker()
  if (locateErrorTimer) {
    clearTimeout(locateErrorTimer)
    locateErrorTimer = null
  }
})

// ── 自动定位 ──────────────────────────────────────────────────────────────
const isLocating = ref(false)
const locateError = ref<{ message: string; hint: string } | null>(null)
let locationMarkerCleanup: (() => void) | null = null
let locateErrorTimer: ReturnType<typeof setTimeout> | null = null
let locationMarkerTimer: ReturnType<typeof setTimeout> | null = null

function _showLocateError(message: string, hint: string) {
  locateError.value = { message, hint }
  if (locateErrorTimer) clearTimeout(locateErrorTimer)
  locateErrorTimer = setTimeout(() => {
    locateError.value = null
  }, 6000)
}

function _clearLocationMarker() {
  if (locationMarkerTimer) {
    clearTimeout(locationMarkerTimer)
    locationMarkerTimer = null
  }
  if (locationMarkerCleanup) {
    locationMarkerCleanup()
    locationMarkerCleanup = null
  }
}

let inspectMarkerCleanup: (() => void) | null = null

function _clearInspectMarker() {
  if (inspectMarkerCleanup) {
    inspectMarkerCleanup()
    inspectMarkerCleanup = null
  }
}

async function _syncInspectMarker(point: { lng: number; lat: number } | null | undefined) {
  const mapInstance = state.resources.map
  if (!mapInstance || !point) {
    _clearInspectMarker()
    return
  }
  _clearInspectMarker()
  const { default: maplibregl } = await import('maplibre-gl')
  if (!state.resources.map) return
  const el = document.createElement('div')
  el.className = 'inspect-point-marker'
  el.innerHTML = '<div class="inspect-dot"></div>'
  const marker = new maplibregl.Marker({ element: el })
    .setLngLat([point.lng, point.lat])
    .addTo(mapInstance)
  inspectMarkerCleanup = () => marker.remove()
}

watch(
  () => props.inspectPoint,
  (point) => {
    void _syncInspectMarker(point)
  },
  { deep: true },
)

async function handleLocateMe() {
  if (isLocating.value) return

  // 若当前地图上已有定位标记，二次点击则清除定位标
  if (locationMarkerCleanup !== null) {
    _clearLocationMarker()
    logStore.logOperation('locate-me', '已清除地图定位标记')
    return
  }

  locateError.value = null
  if (!navigator.geolocation) {
    _showLocateError('浏览器不支持地理定位', '请使用 Chrome、Edge 或 Firefox 等现代浏览器')
    logStore.logOperation('locate-me', '定位失败：浏览器不支持地理定位')
    return
  }
  isLocating.value = true
  logStore.logOperation('locate-me', '正在获取当前位置…')

  navigator.geolocation.getCurrentPosition(
    async (position) => {
      const { longitude, latitude } = position.coords
      const mapInstance = state.resources.map
      if (!mapInstance) {
        isLocating.value = false
        return
      }

      // 飞行到用户位置
      mapInstance.flyTo({
        center: [longitude, latitude],
        zoom: Math.max(mapInstance.getZoom(), 12),
        duration: 1500,
      })

      // 添加定位标记 (持续保留在地图上，直至再次点击消除)
      _clearLocationMarker()
      const { default: maplibregl } = await import('maplibre-gl')
      const el = document.createElement('div')
      el.className = 'geolocation-marker'
      el.innerHTML = '<div class="geo-pulse"></div><div class="geo-dot"></div>'
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([longitude, latitude])
        .addTo(mapInstance)
      locationMarkerCleanup = () => marker.remove()

      isLocating.value = false
      logStore.logOperation(
        'locate-me',
        `已定位到 (${longitude.toFixed(4)}, ${latitude.toFixed(4)})`,
      )
    },
    (err) => {
      isLocating.value = false
      let message: string
      let hint: string
      switch (err.code) {
        case 1:
          message = '定位权限被拒绝'
          hint = '请点击地址栏左侧的锁形图标，将位置权限改为"允许"后刷新页面'
          break
        case 2:
          message = '位置不可用'
          hint = '请检查网络连接，或确认系统定位服务（GPS/Wi-Fi）已开启'
          break
        case 3:
          message = '定位超时'
          hint = '请移动到开阔地带或检查网络后重试'
          break
        default:
          message = `定位失败: ${err.message}`
          hint = '请稍后重试，或检查浏览器定位设置'
      }
      _showLocateError(message, hint)
      logStore.logOperation('locate-me', `${message}（${hint}）`)
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
  )
}
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
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
      </span>
      <span>{{ stageStatusModel.tileErrorMessage }}</span>
      <button class="tile-retry-btn" @click="actionBridge.retryTileLoad">
        {{ stageStatusModel.retryButtonLabel }}
      </button>
    </div>

    <!-- Weather tile loading indicator -->
    <div
      v-if="weatherTileStatusModel.show && weatherTileStatusModel.isLoading"
      class="weather-loading"
    >
      <span class="weather-loading-dot"></span>
      <span>正在加载天气数据…</span>
    </div>

    <!-- Weather tile partial coverage (holes being refilled) -->
    <div
      v-if="weatherTileStatusModel.show && weatherTileStatusModel.partial"
      class="weather-load-partial"
    >
      <span class="weather-loading-dot"></span>
      <span>{{ weatherTileStatusModel.partial }}</span>
    </div>

    <!-- Weather tile error banner -->
    <div
      v-if="weatherTileStatusModel.show && weatherTileStatusModel.error"
      class="weather-load-error"
    >
      <span class="weather-error-icon">
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path
            d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
          />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      </span>
      <span>{{ weatherTileStatusModel.error }}</span>
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

    <!-- 定位失败提示 -->
    <Transition name="locate-error">
      <div v-if="locateError" class="locate-error-tip">
        <span class="locate-error-icon"><AlertTriangle :size="14" aria-hidden="true" /></span>
        <div class="locate-error-body">
          <p class="locate-error-msg">{{ locateError.message }}</p>
          <p class="locate-error-hint">{{ locateError.hint }}</p>
        </div>
        <button
          class="locate-error-close"
          aria-label="关闭定位错误提示"
          @click="locateError = null"
        >
          ×
        </button>
      </div>
    </Transition>
  </section>
</template>

<style scoped src="./MapCanvas.styles.css" />
