<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useLayersStore } from '../stores/layers'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import { useWeatherTileManager } from '../stores/weather-tile-manager'
import type { LayerHotspot } from '../stores/layers/types'
import { createMapCanvasActionBridge } from './map/map-canvas-action-bridge'
import { createMapCanvasExposeBridge } from './map/map-canvas-expose-bridge'
import { createMapCanvasLifecycleBinder } from './map/map-canvas-lifecycle-binder'
import { createMapCanvasMapOptions } from './map/map-canvas-map-options'
import { createMapCanvasModuleBundle } from './map/map-canvas-module-bundle'
import { createOverlayImageModule } from './map/overlay-image-module'
import { createImportedLayerModule } from './map/imported-layer-module'
import { applyActiveLayerStackOrder } from './map/layer-stack-sync'
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
const logStore = useLogStore()
const weatherTileManager = useWeatherTileManager()
const { statusVersion: weatherStatusVersion } = storeToRefs(weatherTileManager)

const props = defineProps<{
  tileSourceId: TileSourceId
  currentHour: number
  hourLabel: string
}>()

const emit = defineEmits<{
  visibleHotspotsChange: [hotspots: LayerHotspot[]]
  hotspotSelect: [hotspot: LayerHotspot | null]
  mapPointSelect: [point: { lng: number; lat: number }]
  overlayTimeUpdate: [states: import('./map/overlay-image-module').OverlayTimeState[]]
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
  getOverlayImageModule: () => overlayImageModule,
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

// ─── Overlay image module (generalized raster overlay) ──────────────────────
let overlayImageModule: ReturnType<typeof createOverlayImageModule> | null = null
let importedLayerModule: ReturnType<typeof createImportedLayerModule> | null = null
const overlayTimeStates = computed(() => overlayImageModule?.overlayTimeStates.value ?? [])
const activeTimeSeriesOverlays = computed(() =>
  overlayTimeStates.value.filter((s) => s.category === 'time-series'),
)
const overlayLinkTimeEnabled = computed(() => overlayImageModule?.linkTimeEnabled.value ?? false)

// 透传 overlay 时间状态到父组件
watch(
  overlayTimeStates,
  (states) => { emit('overlayTimeUpdate', states) },
  { deep: true },
)

function overlayStepTime(layerId: string, delta: number) {
  if (!overlayImageModule) return
  const state = overlayTimeStates.value.find((s) => s.layerId === layerId)
  if (!state || !state.currentTime) return
  const idx = state.timeList.indexOf(state.currentTime)
  if (idx < 0) return
  const nextIdx = idx + delta
  if (nextIdx < 0 || nextIdx >= state.timeList.length) return
  void overlayImageModule.setOverlayTime(layerId, state.timeList[nextIdx])
}

function overlayToggleLinkTime() {
  if (!overlayImageModule) return
  overlayImageModule.setLinkTime(!overlayImageModule.linkTimeEnabled.value)
}

function overlayFormatTime(time: string | null): string {
  if (!time) return ''
  // YYYYMMDD -> YYYY-MM-DD ; YYYYMM -> YYYY-MM
  if (time.length === 8 && /^\d{8}$/.test(time)) {
    return `${time.slice(0, 4)}-${time.slice(4, 6)}-${time.slice(6, 8)}`
  }
  if (time.length === 6 && /^\d{6}$/.test(time)) {
    return `${time.slice(0, 4)}-${time.slice(4, 6)}`
  }
  return time
}

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

// 天气瓦片加载/错误/半覆盖状态：聚合所有可见天气图层
const weatherTileStatusModel = computed(() => {
  // 依赖 statusVersion 触发响应式更新
  void weatherStatusVersion.value
  const weatherLayers = layersStore.activeLayersDisplay.filter(
    (l) => l.visible && layersStore.isWeatherEngineLayer(l.catalogId),
  )
  if (weatherLayers.length === 0) {
    return { show: false, isLoading: false, error: null as string | null, partial: null as string | null }
  }

  for (const layer of weatherLayers) {
    const status = weatherTileManager.getLayerStatus(layer.catalogId)
    if (!status.active) continue
    // 视口全空时才盖错误横幅
    if (status.errorType && status.cachedInViewport === 0) {
      return {
        show: true,
        isLoading: false,
        error: status.errorMessage ?? '天气数据加载失败',
        partial: null,
      }
    }
  }
  // 全空且仍在拉取
  for (const layer of weatherLayers) {
    const status = weatherTileManager.getLayerStatus(layer.catalogId)
    if (status.active && status.pending > 0 && status.cachedInViewport === 0) {
      return { show: true, isLoading: true, error: null, partial: null }
    }
  }
  // 半覆盖：已有内容但视口仍有空洞（pending=0 时提示补洞，避免误以为加载结束）
  for (const layer of weatherLayers) {
    const status = weatherTileManager.getLayerStatus(layer.catalogId)
    if (!status.active) continue
    if (status.cachedInViewport > 0 && status.missingInViewport > 0 && status.pending === 0) {
      const progress = `${status.cachedInViewport}/${status.viewportTotal}`
      const partial = status.gapSweepActive
        ? `已加载 ${progress}，正在补全空洞…`
        : `已加载 ${progress}，部分区域待重试`
      return { show: true, isLoading: false, error: null, partial }
    }
  }
  return { show: false, isLoading: false, error: null, partial: null }
})
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
  state.resources.hotspotPinsModule = moduleBundle.hotspotPinsModule
  state.resources.mapInteractionModule = moduleBundle.mapInteractionModule
  state.resources.mapCanvasRuntimeModule = moduleBundle.mapCanvasRuntimeModule
  state.resources.selectedLayerFocusModule = moduleBundle.selectedLayerFocusModule
  state.resources.measureModule = moduleBundle.measureModule
  moduleBundle.weatherOverlayModule.setupWatchers()
  moduleBundle.mapInteractionModule.bindEvents()
  moduleBundle.mapCanvasRuntimeModule.setupWatchers()
  moduleBundle.selectedLayerFocusModule.setupWatchers()
  moduleBundle.measureModule.bindEvents()

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
      // 同样补同步导入层：mapReady 前 addVectorLayer 会 no-op
      syncImportedLayers({ fitNew: true })
      moduleBundle.mapInteractionModule.applyInteractionMode()
      // 测量模式初始状态同步（mapInteractionModule 已处理 dragPan，measureModule 处理 doubleClickZoom/boxZoom + Canvas show）
      moduleBundle.measureModule.applyMeasureMode()
      presentationModule.revealMap()
    },
    scheduleNavigationThemeSync: () => {
      presentationModule.scheduleNavigationThemeSync()
    },
  }).bind()

  // ─── Generalized raster image overlay module ───────────────────────────────
  overlayImageModule = createOverlayImageModule({
    map: mapInstance,
    getMapReady: () => mapReady.value,
    getActiveVisibleLayerIds: () =>
      layersStore.activeLayersDisplay.filter((l) => l.visible).map((l) => l.catalogId),
  })
  overlayImageModule.init().then(() => { void syncOverlayLayers() })

  async function syncOverlayLayers() {
    if (!overlayImageModule) return
    const known = new Set(overlayImageModule.knownOverlayIds.value)
    const opacityByLayerId: Record<string, number> = {}
    // activeList: 应保持加载的图层（含 hidden 的，即仍在 activeLayers 列表中）
    // visibleList: 应可见的子集（visible=true）
    // 分离两个列表，让 hidden 图层保留在地图上仅切 visibility，避免重复 fetch PNG
    const activeList: string[] = []
    const visibleList: string[] = []

    for (const layer of layersStore.activeLayers) {
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

  function applyLayerStackOrder() {
    if (!mapReady.value || !mapInstance) return
    applyActiveLayerStackOrder(mapInstance, layersStore.activeLayers, {
      getImportedVectorLayerIds: (instanceId) => importedLayerModule?.getLayerIds(instanceId) ?? [],
      getOverlayRasterLayerId: (overlayLayerId) =>
        overlayImageModule?.getRasterLayerId(overlayLayerId) ?? null,
    })
  }

  watch(
    () => layersStore.activeLayers
      // 重要：不再过滤 visible=false 的图层。hidden 图层也需要进入 watch 源，
      // 这样显隐切换才能触发 syncOverlayLayers（同步仅切 visibility，不重载 PNG）。
      .filter((l) => l.importedRaster || (!l.importedVector && !l.isAdminBoundary))
      .map((l) => `${l.instanceId}:${l.catalogId}:${l.visible}:${l.opacity}:${l.importedRaster ? 'r' : 'c'}`)
      .join(','),
    () => { void syncOverlayLayers() },
  )

  watch(
    () => layersStore.activeLayers
      .map((l) => `${l.instanceId}:${l.order}`)
      .join(','),
    () => { applyLayerStackOrder() },
  )

  // ─── Imported layer module（本地导入矢量：挂接活动图层列表） ───────────────
  importedLayerModule = createImportedLayerModule({
    map: mapInstance,
    getMapReady: () => mapReady.value,
  })

  /** 把 activeLayers 中的导入矢量同步到地图；fitNew 时对新加入图层做视野适配 */
  function syncImportedLayers(opts: { fitNew?: boolean } = {}) {
    if (!importedLayerModule) return
    const imported = layersStore.activeLayers.filter((l) => l.importedVector)
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
        // add 可能因 mapReady=false 失败；仅在实际加载成功后再记
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

  // 同步「活动图层」里的导入矢量到地图：显隐 / 透明度 / 增删
  watch(
    () => layersStore.activeLayers
      .filter((l) => l.importedVector)
      .map((l) => `${l.instanceId}:${l.visible}:${l.opacity}:${l.importedVector!.featureCount}`)
      .join(','),
    () => {
      syncImportedLayers({ fitNew: true })
    },
    { immediate: true },
  )

})

onBeforeUnmount(() => {
  teardownBinder.dispose()
  overlayImageModule = null
  importedLayerModule?.dispose()
  _clearLocationMarker()
})

// ── 自动定位 ──────────────────────────────────────────────────────────────
const isLocating = ref(false)
const locateError = ref<{ message: string; hint: string } | null>(null)
let locationMarkerCleanup: (() => void) | null = null
let locateErrorTimer: ReturnType<typeof setTimeout> | null = null

function _showLocateError(message: string, hint: string) {
  locateError.value = { message, hint }
  if (locateErrorTimer) clearTimeout(locateErrorTimer)
  locateErrorTimer = setTimeout(() => { locateError.value = null }, 6000)
}

function _clearLocationMarker() {
  if (locationMarkerCleanup) {
    locationMarkerCleanup()
    locationMarkerCleanup = null
  }
}

async function handleLocateMe() {
  if (isLocating.value) return
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
        zoom: Math.max(mapInstance.getZoom(), 10),
        duration: 1500,
      })

      // 添加临时定位标记
      _clearLocationMarker()
      const { default: maplibregl } = await import('maplibre-gl')
      const el = document.createElement('div')
      el.className = 'geolocation-marker'
      el.innerHTML = '<div class="geo-pulse"></div><div class="geo-dot"></div>'
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([longitude, latitude])
        .addTo(mapInstance)
      locationMarkerCleanup = () => marker.remove()

      // 8 秒后自动移除标记
      setTimeout(() => _clearLocationMarker(), 8000)

      isLocating.value = false
      logStore.logOperation('locate-me', `已定位到 (${longitude.toFixed(4)}, ${latitude.toFixed(4)})`)
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
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      </span>
      <span>{{ stageStatusModel.tileErrorMessage }}</span>
      <button class="tile-retry-btn" @click="actionBridge.retryTileLoad">{{ stageStatusModel.retryButtonLabel }}</button>
    </div>

    <!-- Weather tile loading indicator -->
    <div v-if="weatherTileStatusModel.show && weatherTileStatusModel.isLoading" class="weather-loading">
      <span class="weather-loading-dot"></span>
      <span>正在加载天气数据…</span>
    </div>

    <!-- Weather tile partial coverage (holes being refilled) -->
    <div v-if="weatherTileStatusModel.show && weatherTileStatusModel.partial" class="weather-load-partial">
      <span class="weather-loading-dot"></span>
      <span>{{ weatherTileStatusModel.partial }}</span>
    </div>

    <!-- Weather tile error banner -->
    <div v-if="weatherTileStatusModel.show && weatherTileStatusModel.error" class="weather-load-error">
      <span class="weather-error-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/>
          <line x1="12" y1="17" x2="12.01" y2="17"/>
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

    <!-- Overlay time control (time-series raster overlays) -->
    <div
      v-if="activeTimeSeriesOverlays.length > 0"
      class="overlay-time-bar"
    >
      <button
        v-if="activeTimeSeriesOverlays.length > 1"
        class="overlay-link-btn"
        :class="{ active: overlayLinkTimeEnabled }"
        type="button"
        :title="overlayLinkTimeEnabled ? '取消联动' : '多图层时间联动'"
        @click="overlayToggleLinkTime"
      >{{ overlayLinkTimeEnabled ? '🔗' : '⛓' }}</button>
      <div
        v-for="state in activeTimeSeriesOverlays"
        :key="'overlay-time-' + state.layerId"
        class="overlay-time-control"
      >
        <button
          class="overlay-time-btn"
          type="button"
          :disabled="state.timeList.indexOf(state.currentTime ?? '') <= 0"
          @click="overlayStepTime(state.layerId, -1)"
          aria-label="上一个时间"
        >‹</button>
        <span class="overlay-time-label">{{ overlayFormatTime(state.currentTime) }}</span>
        <button
          class="overlay-time-btn"
          type="button"
          :disabled="state.timeList.indexOf(state.currentTime ?? '') >= state.timeList.length - 1"
          @click="overlayStepTime(state.layerId, 1)"
          aria-label="下一个时间"
        >›</button>
      </div>
    </div>

    <!-- 自动定位按钮 -->
    <button
      class="locate-me-btn"
      :class="{ locating: isLocating }"
      type="button"
      title="定位到当前位置"
      :disabled="isLocating"
      @click="handleLocateMe"
    >
      <svg v-if="!isLocating" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="4"/>
        <line x1="12" y1="2" x2="12" y2="5"/>
        <line x1="12" y1="19" x2="12" y2="22"/>
        <line x1="2" y1="12" x2="5" y2="12"/>
        <line x1="19" y1="12" x2="22" y2="12"/>
      </svg>
      <span v-else class="locate-spinner"></span>
    </button>

    <!-- 定位失败提示 -->
    <Transition name="locate-error">
      <div v-if="locateError" class="locate-error-tip">
        <span class="locate-error-icon">⚠</span>
        <div class="locate-error-body">
          <p class="locate-error-msg">{{ locateError.message }}</p>
          <p class="locate-error-hint">{{ locateError.hint }}</p>
        </div>
        <button class="locate-error-close" @click="locateError = null">×</button>
      </div>
    </Transition>
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

/* 天气瓦片加载指示器 */
.weather-loading {
  position: absolute;
  top: 110px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.38rem 0.7rem;
  border-radius: 999px;
  background: rgba(8, 18, 33, 0.88);
  border: 1px solid rgba(100, 160, 255, 0.25);
  color: #a8c8ff;
  font-size: 0.64rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.24);
}

.weather-loading-dot {
  width: 0.48rem;
  height: 0.48rem;
  border-radius: 999px;
  background: #6aa0ff;
  box-shadow: 0 0 0 6px rgba(100, 160, 255, 0.12);
  animation: weather-pulse 1.2s ease-in-out infinite;
}

@keyframes weather-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

/* 天气瓦片半覆盖 / 补洞提示 */
.weather-load-partial {
  position: absolute;
  top: 110px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
  padding: 0.38rem 0.7rem;
  border-radius: 999px;
  background: rgba(18, 28, 22, 0.9);
  border: 1px solid rgba(120, 200, 160, 0.28);
  color: #b8e6c8;
  font-size: 0.64rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.24);
}

/* 天气瓦片错误横幅 */
.weather-load-error {
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
  background: rgba(33, 22, 8, 0.92);
  border: 1px solid rgba(255, 180, 60, 0.3);
  color: #ffcb80;
  font-size: 0.64rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.24);
  max-width: 80%;
}

.weather-error-icon {
  display: flex;
  align-items: center;
  color: #ffa040;
  flex-shrink: 0;
}

.hotspot-label strong,
.hotspot-label span {
  display: block;
}
.hotspot-label strong { font-size: 0.64rem; }
.hotspot-label span { margin-top: 0.15rem; color: #99afc3; font-size: 0.6rem; }

/* Overlay time-series control */
.overlay-time-bar {
  position: absolute;
  z-index: 22;
  bottom: 1rem;
  right: 1rem;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.3rem;
}

.overlay-time-control {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.32rem 0.4rem;
  border-radius: 0.7rem;
  background: rgba(8, 18, 33, 0.88);
  border: 1px solid rgba(136, 192, 255, 0.18);
  box-shadow: 0 6px 20px rgba(3, 10, 20, 0.22);
  color: #eaf3fb;
  font-size: 0.7rem;
}

.overlay-link-btn {
  width: 1.7rem;
  height: 1.7rem;
  border-radius: 0.5rem;
  border: 1px solid rgba(136, 192, 255, 0.22);
  background: rgba(8, 18, 33, 0.88);
  color: #9fb6cc;
  font-size: 0.85rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}

.overlay-link-btn.active {
  background: rgba(60, 160, 100, 0.24);
  border-color: rgba(114, 255, 207, 0.4);
  color: #9ff8cf;
}

.overlay-link-btn:hover {
  border-color: rgba(136, 192, 255, 0.4);
  color: #eaf3fb;
}

.overlay-time-btn {
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 0.4rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  background: rgba(36, 90, 170, 0.14);
  color: #dfeefd;
  font-size: 0.9rem;
  font-family: inherit;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.18s ease, color 0.18s ease;
}

.overlay-time-btn:hover:not(:disabled) {
  background: rgba(60, 120, 200, 0.28);
  color: #ffffff;
}

.overlay-time-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.overlay-time-label {
  min-width: 5.2rem;
  text-align: center;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

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
  .locate-me-btn { right: 3.55rem; bottom: 0.75rem; }
}

/* ── 自动定位按钮 ─────────────────────────────────────────────────────── */
.locate-me-btn {
  position: absolute;
  right: 3.8rem;
  bottom: 0.8rem;
  z-index: 25;
  width: 2.4rem;
  height: 2.4rem;
  border: 1px solid rgba(136, 192, 255, 0.18);
  border-radius: 0.6rem;
  background: rgba(4, 12, 23, 0.55);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  color: #9fb6cc;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: border-color 0.2s ease, color 0.2s ease, background 0.2s ease;
  pointer-events: auto;
}

.locate-me-btn:hover:not(:disabled) {
  border-color: rgba(90, 213, 255, 0.4);
  color: #5ad5ff;
  background: rgba(10, 132, 255, 0.15);
}

.locate-me-btn:active:not(:disabled) {
  transform: scale(0.95);
}

.locate-me-btn.locating {
  border-color: rgba(90, 213, 255, 0.3);
  color: #5ad5ff;
}

.locate-spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid rgba(90, 213, 255, 0.2);
  border-top-color: #5ad5ff;
  border-radius: 50%;
  animation: locate-spin 0.8s linear infinite;
}

@keyframes locate-spin {
  to { transform: rotate(360deg); }
}

/* ── 定位失败提示 ─────────────────────────────────────────────────────── */
.locate-error-tip {
  position: absolute;
  right: 3.5rem;
  bottom: 3.4rem;
  z-index: 26;
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  max-width: 18rem;
  padding: 0.55rem 0.7rem;
  border: 1px solid rgba(255, 138, 138, 0.28);
  border-radius: 0.6rem;
  background: rgba(40, 12, 18, 0.82);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  pointer-events: auto;
}

.locate-error-icon {
  color: #ff8a8a;
  font-size: 0.85rem;
  flex: none;
  margin-top: 0.05rem;
}

.locate-error-body {
  flex: 1;
  min-width: 0;
}

.locate-error-msg {
  margin: 0;
  color: #ffb0b0;
  font-size: 0.68rem;
  font-weight: 600;
  line-height: 1.3;
}

.locate-error-hint {
  margin: 0.15rem 0 0;
  color: #c8a0a0;
  font-size: 0.58rem;
  line-height: 1.4;
}

.locate-error-close {
  border: none;
  background: transparent;
  color: #8a6060;
  font-size: 0.9rem;
  line-height: 1;
  cursor: pointer;
  flex: none;
  padding: 0;
  margin-top: -0.1rem;
}

.locate-error-close:hover { color: #ff8a8a; }

.locate-error-enter-active,
.locate-error-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.locate-error-enter-from,
.locate-error-leave-to {
  opacity: 0;
  transform: translateY(0.4rem);
}

/* ── 定位标记 ─────────────────────────────────────────────────────────── */
:deep(.geolocation-marker) {
  pointer-events: none;
}

:deep(.geo-dot) {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 0.7rem;
  height: 0.7rem;
  border-radius: 50%;
  background: #5ad5ff;
  border: 2px solid #fff;
  box-shadow: 0 0 6px rgba(90, 213, 255, 0.6);
}

:deep(.geo-pulse) {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  background: rgba(90, 213, 255, 0.25);
  animation: geo-pulse-anim 2s ease-out infinite;
}

@keyframes geo-pulse-anim {
  0% { transform: translate(-50%, -50%) scale(0.5); opacity: 1; }
  100% { transform: translate(-50%, -50%) scale(2.5); opacity: 0; }
}
</style>
