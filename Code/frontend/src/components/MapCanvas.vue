<script setup lang="ts">
import { MapChromeNavigationControl } from './map/map-chrome-controls'
import type { Map as MapInstance } from 'maplibre-gl'

import { computed, onBeforeUnmount, onMounted, ref, shallowRef, toRef, watch } from 'vue'

import { AlertTriangle } from './ui/icons'
import DrawToolbar from './map/draw-toolbar.vue'
import GlobeStarfield from './map/GlobeStarfield.vue'
import ZonalStatsCard from './info-panel/ZonalStatsCard.vue'
import VectorAttributeTable from './info-panel/VectorAttributeTable.vue'
import { useLayersStore } from '../stores/layers'
import { useLayerWorkspace, useLayerViewport } from '../stores/layers/selectors'
import { useUiStore } from '../stores/ui'
import { useDrawStore } from '../stores/draw-store'
import { useLogStore } from '../stores/log'
import { useDrawSave } from '../composables/useDrawSave'
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
import {
  TILE_SOURCE_MAP,
  getDefaultTileSource,
  getFailoverCandidates,
  isTileSourceUsable,
  type TileSourceId,
} from '../services/api-config'
import { isGlobalMapViewport } from '../utils/map-viewport'
import {
  isMapDistributionChromeEnabled,
  subscribeMapDistributionChrome,
  getGlobeBackgroundMode,
  getGlobeDaylightMode,
  subscribeGlobeScene,
  type GlobeBackgroundMode,
  type GlobeDaylightMode,
} from '../services/settings-local'
import {
  buildNightHemisphereGeoJSON,
  classifyBasemapBrightness,
  resolveGlobeSky,
} from './map/globe-scene-utils'
import { TILE_LAYER_ID } from './map/basemap-module'
import { useThemeStore } from '../stores/theme'
import { resolveGlobeBackgroundColor } from './map/map-canvas-map-options'
import {
  dataWorkspaceHighlight,
  dataWorkspaceZoomRequest,
  showToast,
} from '../data-manager/core/workspace-store'
import { debugLog as probeDebugLog } from '../utils/perf-probe'
import { useSettingsStore } from '../stores/settings'

const layersStore = useLayersStore() // createMapCanvasModuleBundle 需完整 store 实例
const workspace = useLayerWorkspace()
const viewport = useLayerViewport()
const uiStore = useUiStore()
const settingsStore = useSettingsStore()
const drawStore = useDrawStore()
const logStore = useLogStore()
const weatherTileManager = useWeatherTileManager()
const weatherStatusVersion = toRef(weatherTileManager, 'statusVersion')
const weatherActivityVersion = toRef(weatherTileManager, 'activityVersion')

const props = defineProps<{
  tileSourceId: TileSourceId
  currentHour: number
  /** 时间轴日期（"自然"晨昏样式计算太阳赤纬所需；缺省取当前日期） */
  currentDate?: Date
  /** 地图点查选中坐标（持久标记，非定位标记） */
  inspectPoint?: { lng: number; lat: number } | null
  /** 实验性 3D：true 时地图切 globe 投影（外观设置勾选「启用3D视图」后生效） */
  globeProjection?: boolean
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
      // 相机操作失败不得炸断用户操作链（坏 bounds 数据防御）
      try {
        mod.fitLayers([instanceId])
        return true
      } catch (error) {
        console.warn('[MapCanvas] fitLayers failed', error)
        showToast('该图层坐标超出地理范围，无法定位', true, 3500)
        return false
      }
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
  buildMapStageDisplayModel({ activeLayer: activeLayer.value }),
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

// ─── 主题切换时更新 MapLibre 背景色 ──────────────────────────────────────────
const themeStore = useThemeStore()

/** 按当前投影模式更新 background layer 颜色（globe=球面深空蓝兜底/浅蓝灰；2D=surface-1）。 */
function applyBackgroundColor(): void {
  const map = state.resources.map
  if (map && mapReady.value) {
    map.setPaintProperty(
      'background',
      'background-color',
      resolveGlobeBackgroundColor(
        props.globeProjection === true,
        themeStore.mode === 'light',
      ),
    )
  }
}

watch(
  () => themeStore.mode,
  () => {
    applyBackgroundColor()
    // 昼夜遮罩层在主题切换时无需改色（fill-color 固定深色半透明）
  },
)

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

// ─── 低缩放纯色底图抑制 ──────────────────────────────────────────────────────
// 设计变更：关闭「分布淡底 / 氛围遮罩」时，底图应始终可见，不再在低 zoom 抑制。
// 原逻辑在 zoom≤3.5 + 无数据图层 + 设置关闭时隐藏底图瓦片，导致大洲/世界视口下底图消失。
// 现改为始终保留底图，氛围效果由 CSS chrome-off 类统一控制（opacity:0）。
let _isUnmounted = false

const shouldSuppressBasemap = computed(() => false)

function applyBasemapSuppression() {
  if (_isUnmounted) return
  const map = state.resources.map
  if (!map || !mapReady.value) return
  // 空白底图（tileSourceId=none）必须保持隐藏；否则切源后的延时抑制会把旧瓦片重新显示出来
  const blankBasemap = props.tileSourceId === 'none'
  const suppress = shouldSuppressBasemap.value || blankBasemap
  const tileLayer = map.getLayer('tile-base-raster')
  if (tileLayer) {
    const target = suppress ? 'none' : 'visible'
    if (map.getLayoutProperty('tile-base-raster', 'visibility') !== target) {
      map.setLayoutProperty('tile-base-raster', 'visibility', target)
    }
  }
  const overlayLayer = map.getLayer('tile-base-overlay-raster')
  if (overlayLayer && suppress) {
    if (map.getLayoutProperty('tile-base-overlay-raster', 'visibility') !== 'none') {
      map.setLayoutProperty('tile-base-overlay-raster', 'visibility', 'none')
    }
  }
}

watch(shouldSuppressBasemap, () => applyBasemapSuppression())

// 瓦片源切换（scheduleTileSourceSwitch 有 80ms 防抖）后重新应用抑制
watch(
  () => props.tileSourceId,
  () => {
    setTimeout(applyBasemapSuppression, 120)
  },
)

// ─── 实验性 3D：globe 投影切换 ──────────────────────────────────────────────
// 外观设置勾选「启用3D视图（实验测试）」且顶栏处于 3D 模式时切 globe；
// 关闭或切回 2D 时恢复 mercator。地图实例保持不变，全部图层与叠加层保留。
watch(
  [() => props.globeProjection, mapReady],
  ([on, ready]) => {
    if (!ready || _isUnmounted) return
    const map = state.resources.map
    if (!map) return
    const target = on ? 'globe' : 'mercator'
    try {
      const current = map.getProjection?.()
      if (current?.type === target) return
      map.setProjection({ type: target })
      debugLog('MapCanvas', 'setProjection', target)
    } catch (err) {
      console.warn('[MapCanvas] setProjection failed:', err)
    }
    // 投影切换后同步 background 颜色（globe=深空蓝球面兜底；2D=surface-1）
    applyBackgroundColor()
  },
  { immediate: true },
)

// ─── 3D globe 场景偏好（背景星图 / 昼夜光影档位）────────────────────────────

const globeProjectionOn = computed(() => props.globeProjection === true)
const globeBackgroundMode = ref<GlobeBackgroundMode>(getGlobeBackgroundMode())
const globeDaylightMode = ref<GlobeDaylightMode>(getGlobeDaylightMode())
let _unsubscribeGlobeScene: (() => void) | null = null
_unsubscribeGlobeScene = subscribeGlobeScene(() => {
  globeBackgroundMode.value = getGlobeBackgroundMode()
  globeDaylightMode.value = getGlobeDaylightMode()
})
onBeforeUnmount(() => {
  _unsubscribeGlobeScene?.()
  _unsubscribeGlobeScene = null
})

// map 实例在 onMounted 异步创建；watch 先登记，创建后立即 apply，
// 时间轴 / 底图源 / 光影档位变化时仅更新光照与天空。
watch(
  [
    () => props.globeProjection,
    () => props.currentHour,
    () => props.currentDate,
    () => props.tileSourceId,
    globeDaylightMode,
    mapReady,
  ],
  ([enabled, hour, , , , ready]) => {
    const map = state.resources.map
    if (map && ready) applyGlobeScene(map, enabled === true, hour)
  },
  { immediate: true },
)

// ─── Time-of-day visual vars ─────────────────────────────────────────────────

const timeVisualState = computed(() => buildMapStageTimeVisualState(props.currentHour))

/**
 * Globe 专属视觉层：原生天空大气 + raster 昼夜遮罩。
 * 只在 3D 模式打开，2D 模式恢复默认，避免常规地图承担额外样式更新。
 *
 * ⚠️ globe 模式下**不再 setLight**：light 的 azimuth 公式是"视口相对方位"，
 * 对 globe 语义错误（且 raster 瓦片本身不吃 light，只会对 vector 数据层
 * 产生方向错误的阴影）——昼夜统一由夜半球遮罩（applyNightHemisphere）
 * 与 raster-brightness 压制（applyBasemapBrightness）负责。
 *
 * 亮色底图（街道/矢量/地形）在太阳直射下会过曝发白：
 * 直接压底图 raster 图层的 brightness-max（对瓦片像素的硬约束）：
 * 亮色底图白天段 ≈ 0.80，soft 档再降至 0.72；影像/暗色底图保留 1.0。
 */
function applyGlobeScene(map: MapInstance, enabled: boolean, hour: number): void {
  try {
    applyBasemapBrightness(map, enabled)
    applyNightHemisphere(map, enabled, hour, props.currentDate)
    if (!enabled || globeDaylightMode.value === 'off') {
      // 非 globe 或「无」档：恢复默认大气（整体亮度统一，不加任何亮暗效果）
      map.setSky?.({})
      return
    }
    const basemapStyle = TILE_SOURCE_MAP.get(props.tileSourceId)?.style
    const brightness = classifyBasemapBrightness(basemapStyle)
    // sky 固定化（用户定调）：
    // - 「标准」固定白天大气（不随时间轴变化的立体地球质感）
    // - 「自然」固定夜间深空大气（地球的亮暗完全由晨昏线负责，
    //   天空不再叠加随时间变化的方向性亮色）
    const skyAnchorHour = globeDaylightMode.value === 'natural' ? 0 : 12
    const sky = resolveGlobeSky(skyAnchorHour, brightness)
    map.setSky?.({
      'sky-color': sky.skyColor,
      'horizon-color': sky.horizonColor,
      'fog-color': sky.fogColor,
      'fog-ground-blend': sky.fogGroundBlend,
      'horizon-fog-blend': sky.horizonFogBlend,
      'sky-horizon-blend': sky.skyHorizonBlend,
      'atmosphere-blend': sky.atmosphereBlend,
    })
  } catch (error) {
    // 旧样式/旧 MapLibre 版本不支持天空参数时，不影响地图主体渲染。
    debugLog('[MapCanvas] globe scene style unavailable', error)
  }
}

/**
 * 底图 raster 亮度压制（globe 模式专属）。
 * 亮色底图阳面"过曝发白"的主修：直接限制瓦片像素最大亮度。
 * - 亮色底图 + 标准：raster-brightness-max = 0.80
 * - 亮色底图 + 柔和：0.72（进一步压）
 * - 影像/暗色底图：1.0（保留原始对比）
 * - 2D / globe 关闭：恢复 1.0
 */
/**
 * 底图 raster 亮度压制（globe 模式专属）。
 * 亮色底图阳面"过曝发白"的主修：直接限制瓦片像素最大亮度。
 * - 亮色底图 + 标准/自然：raster-brightness-max = 0.80
 * - 亮色底图 + 无（off 档）：1.0（完全不加亮暗效果）
 * - 影像/暗色底图：1.0（保留原始对比）
 * - 2D / globe 关闭：恢复 1.0
 */
function applyBasemapBrightness(map: MapInstance, globeEnabled: boolean): void {
  try {
    if (!map.getLayer?.(TILE_LAYER_ID)) return
    let brightnessMax = 1.0
    if (globeEnabled && globeDaylightMode.value !== 'off') {
      const basemapStyle = TILE_SOURCE_MAP.get(props.tileSourceId)?.style
      const brightness = classifyBasemapBrightness(basemapStyle)
      if (brightness === 'light') {
        brightnessMax = 0.8
      }
    }
    const current = map.getPaintProperty?.(TILE_LAYER_ID, 'raster-brightness-max')
    if (current !== brightnessMax) {
      map.setPaintProperty(TILE_LAYER_ID, 'raster-brightness-max', brightnessMax)
    }
  } catch (error) {
    debugLog('[MapCanvas] applyBasemapBrightness unavailable', error)
  }
}

// ─── Globe raster 昼夜遮罩（"自然"晨昏样式，跟随时间轴+日期） ────────────────

/**
 * OSM 等 raster 瓦片没有 MapLibre 光照属性，必须单独绘制夜半球遮罩。
 * 真实太空观感（globe-scene-utils.buildNightHemisphereGeoJSON）：
 * - 弯曲晨昏线：按太阳赤纬精确求解纬度边界，极昼/极夜随日期自然出现
 * - 夜侧均匀暗化（单一 night-core 多边形，硬边）
 * - **line-blur 羽化过渡**：晨昏线 terminator 用原生 line-blur 宽线
 *   向两侧像素级羽化（替代多档条纹——档边界渲染下可见，用户反馈"好多线"）
 * - 仅「自然」档显示；「标准」=固定质感不画晨昏线；「无」=完全不画
 *
 * ⚠️ MapLibre 表达式规范：['zoom'] 只能作为**顶层** step/interpolate 的 input，
 * 不能嵌套在乘法里（校验失败静默拒绝 addLayer——错误只走 error 事件不 throw）。
 */
const NIGHT_HEMISPHERE_SOURCE_ID = 'globe-night-hemisphere'
const NIGHT_CORE_LAYER_ID = 'globe-night-core-fill'
const NIGHT_TRANSITION_LAYER_ID = 'globe-night-transition-fill'
const TERMINATOR_LINE_LAYER_ID = 'globe-terminator-line'
const LEGACY_NIGHT_LAYER_ID = 'globe-night-hemisphere-fill'
const TWILIGHT_GLOW_LAYER_ID = 'globe-twilight-glow-fill'

/** 夜核 fill opacity：顶层 zoom interpolate（规范合法）。 */
function nightCoreOpacityExpression(): unknown {
  return ['interpolate', ['linear'], ['zoom'], 0, 0.5, 3, 0.58]
}

/** 晨昏线 line-width：顶层 zoom interpolate。 */
function terminatorWidthExpression(): unknown {
  return ['interpolate', ['linear'], ['zoom'], 0, 26, 2, 16, 4, 9]
}

/** 晨昏线 line-blur：顶层 zoom interpolate（向两侧羽化溶解 fill 硬边）。 */
function terminatorBlurExpression(): unknown {
  return ['interpolate', ['linear'], ['zoom'], 0, 20, 2, 13, 4, 7]
}

/** addLayer 后验证 layer 真的进入 style（MapLibre 表达式校验失败不 throw）。 */
function ensureNightLayers(map: MapInstance): void {
  // 夜核 fill（单一多边形，硬边，统一暗度）
  if (!map.getLayer(NIGHT_CORE_LAYER_ID)) {
    map.addLayer({
      id: NIGHT_CORE_LAYER_ID,
      type: 'fill',
      source: NIGHT_HEMISPHERE_SOURCE_ID,
      filter: ['==', ['get', 'hemisphere'], 'night-core'],
      paint: {
        'fill-color': '#0a1626',
        'fill-opacity': nightCoreOpacityExpression() as never,
        // 同色描边：antimeridian 拆分的两个 ring 边界边在球面上是同一条线，
        // fill 边缘抗锯齿各自半透明会在日期变更线附近透出底图细线——
        // 同色 outline 覆盖接缝（MapLibre 相邻多边形接缝的标准解法）
        'fill-outline-color': '#0a1626',
      },
      layout: { visibility: 'visible' },
    } as never)
    if (!map.getLayer(NIGHT_CORE_LAYER_ID)) {
      console.warn('[MapCanvas] 夜半球 core 图层创建失败（表达式校验被拒绝）')
      return
    }
  }
  map.setLayoutProperty(NIGHT_CORE_LAYER_ID, 'visibility', 'visible')
  map.setPaintProperty(NIGHT_CORE_LAYER_ID, 'fill-opacity', nightCoreOpacityExpression() as never)
  map.setPaintProperty(NIGHT_CORE_LAYER_ID, 'fill-outline-color', '#0a1626')

  // 晨昏线 line-blur 羽化（宽线高模糊 → 平滑过渡，无条纹）
  if (!map.getLayer(TERMINATOR_LINE_LAYER_ID)) {
    map.addLayer({
      id: TERMINATOR_LINE_LAYER_ID,
      type: 'line',
      source: NIGHT_HEMISPHERE_SOURCE_ID,
      filter: ['==', ['get', 'hemisphere'], 'terminator'],
      paint: {
        'line-color': '#0a1626',
        'line-width': terminatorWidthExpression() as never,
        'line-blur': terminatorBlurExpression() as never,
        'line-opacity': 0.5,
      },
      layout: { visibility: 'visible', 'line-cap': 'round', 'line-join': 'round' },
    } as never)
    if (!map.getLayer(TERMINATOR_LINE_LAYER_ID)) {
      console.warn('[MapCanvas] 晨昏线 blur 图层创建失败（表达式校验被拒绝）')
      return
    }
  }
  map.setLayoutProperty(TERMINATOR_LINE_LAYER_ID, 'visibility', 'visible')
  map.setPaintProperty(TERMINATOR_LINE_LAYER_ID, 'line-width', terminatorWidthExpression() as never)
  map.setPaintProperty(TERMINATOR_LINE_LAYER_ID, 'line-blur', terminatorBlurExpression() as never)
}

function applyNightHemisphere(
  map: MapInstance,
  globeEnabled: boolean,
  hour: number,
  date?: Date,
): void {
  try {
    // 仅「自然」档显示昼夜遮罩；「标准」固定质感不画；「无」完全不画
    if (!globeEnabled || globeDaylightMode.value !== 'natural') {
      for (const layerId of [
        NIGHT_CORE_LAYER_ID,
        TERMINATOR_LINE_LAYER_ID,
        NIGHT_TRANSITION_LAYER_ID,
        LEGACY_NIGHT_LAYER_ID,
        TWILIGHT_GLOW_LAYER_ID,
      ]) {
        if (map.getLayer(layerId)) {
          map.setLayoutProperty(layerId, 'visibility', 'none')
        }
      }
      return
    }
    const data = buildNightHemisphereGeoJSON(hour, date)
    const source = map.getSource(NIGHT_HEMISPHERE_SOURCE_ID) as
      | import('maplibre-gl').GeoJSONSource
      | undefined
    if (source && 'setData' in source) {
      source.setData(data as never)
    } else if (!map.getSource(NIGHT_HEMISPHERE_SOURCE_ID)) {
      map.addSource(NIGHT_HEMISPHERE_SOURCE_ID, { type: 'geojson', data: data as never })
    }
    // 旧版图层残留隐藏（条纹过渡带/单 layer/twilight 历史版本）
    for (const layerId of [
      NIGHT_TRANSITION_LAYER_ID,
      LEGACY_NIGHT_LAYER_ID,
      TWILIGHT_GLOW_LAYER_ID,
    ]) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', 'none')
      }
    }
    ensureNightLayers(map)
  } catch (error) {
    debugLog('[MapCanvas] applyNightHemisphere unavailable', error)
  }
}

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
    if (_isUnmounted) return

    const { default: maplibregl } = await import('maplibre-gl')
    if (_isUnmounted) return

    const mapInstance = new maplibregl.Map(
      createMapCanvasMapOptions({
        container: mapContainer.value,
      }),
    )
    state.resources.map = mapInstance
    // 调试诊断口：浏览器控制台排查 globe/光照/图层状态用（perf-probe 惯例，只读引用）
    if (typeof window !== 'undefined') {
      ;(window as unknown as Record<string, unknown>).__cgdaMap = mapInstance
    }
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
      onProviderFailover: (nextSourceId, failedProvider) => {
        // 同步单一真源：更新 store 选中态，让底图选择器 UI 与实际渲染一致
        uiStore.setTileSource(nextSourceId)
        const nextLabel = TILE_SOURCE_MAP.get(nextSourceId)?.label ?? nextSourceId
        logStore.logOperation(
          'basemap-failover',
          `底图源「${failedProvider}」暂时不可用，已自动切换至「${nextLabel}」`,
        )
        showToast(`底图源「${failedProvider}」暂时不可用，已自动切换至「${nextLabel}」`, false)
      },
      getFailoverCandidates: (sourceId, excludeProviders) =>
        getFailoverCandidates(sourceId, excludeProviders).filter((id) => {
          const cfg = TILE_SOURCE_MAP.get(id)
          return (
            !!cfg && isTileSourceUsable(cfg, (key) => settingsStore.isBasemapApiKeyAvailable(key))
          )
        }),
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
      getDrawState: () => ({
        drawMode: drawStore.drawMode,
        features: drawStore.features,
        activeVertices: drawStore.activeVertices,
        isDrawing: drawStore.isDrawing,
        hoverPoint: drawStore.hoverPoint,
        selectedFeatureIndex: drawStore.selectedFeatureIndex,
      }),
      addDrawVertex: (v) => drawStore.addVertex(v),
      undoDrawVertex: () => drawStore.undoLastVertex(),
      setDrawHoverPoint: (p) => drawStore.setHoverPoint(p),
      addDrawFeature: (f) => drawStore.addFeature(f),
      clearDrawVertices: () => drawStore.clearActiveVertices(),
      setDrawDrawingFlag: (v) => {
        drawStore.isDrawing = v
      },
      scheduleDrawPersist: () => drawStore.scheduleDraftPersist(),
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
    state.resources.drawModule = moduleBundle.drawModule
    overlayImageModuleRef.value = moduleBundle.nonWeatherLayerSyncModule.overlayImageModule
    moduleBundle.weatherOverlayModule.setupWatchers()
    moduleBundle.nonWeatherLayerSyncModule.setupWatchers()
    void moduleBundle.nonWeatherLayerSyncModule.init()
    moduleBundle.mapInteractionModule.bindEvents()
    moduleBundle.mapCanvasRuntimeModule.setupWatchers()
    moduleBundle.selectedLayerFocusModule.setupWatchers()
    moduleBundle.measureModule.bindEvents()
    moduleBundle.drawModule.bindEvents()
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
        // 绘制模式初始状态同步
        moduleBundle.drawModule.applyDrawMode()
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
  _isUnmounted = true
  unsubscribeMapChrome()
  teardownBinder.dispose()
  overlayImageModule = null
  _clearLocationMarker()
  _clearInspectMarker()
  if (locateErrorTimer) {
    clearTimeout(locateErrorTimer)
    locateErrorTimer = null
  }
  window.removeEventListener('draw:save', handleDrawSave)
  window.removeEventListener('draw:toggle-attr-table', handleToggleAttrTable)
})

// ── 绘制保存事件处理 ────────────────────────────────────────────────────

const attrTableVisible = ref(false)
const drawSave = useDrawSave()

function handleToggleAttrTable() {
  attrTableVisible.value = !attrTableVisible.value
}

async function handleDrawSave() {
  const res = await drawSave.saveDrawLayer()
  if (res.ok) {
    logStore.logOperation(
      'draw-save',
      res.dropped ? '空图层已丢弃' : `绘制图层已保存 (${res.featureCount} 个要素)`,
    )
    return
  }
  if (res.validationErrors.length > 0) {
    logStore.logOperation('draw-save-error', `校验未通过: ${res.validationErrors[0].message}`)
    // 打开属性表展示校验错误，便于用户定位问题要素
    if (!attrTableVisible.value) {
      window.dispatchEvent(new CustomEvent('draw:toggle-attr-table'))
    }
    return
  }
  logStore.logOperation('draw-save-error', `保存失败: ${res.error ?? '未知错误'}`)
  console.error('[draw] save failed:', res.error)
}

// 进入绘制模式时自动创建草稿图层；已有未保存草稿则继续编辑（防丢失）
watch(
  () => uiStore.interactionMode,
  (mode) => {
    if (mode !== 'draw') return
    const hasActiveDraft = drawStore.draftLayerId || drawStore.features.length > 0
    if (hasActiveDraft) return
    const name = drawStore.draftLayerName || `绘制图层-${new Date().toLocaleString('zh-CN')}`
    const layer = layersStore.addDrawDraftLayer(name)
    drawStore.beginDrawSession(name)
    drawStore.setDraftLayerId(layer.instanceId)
  },
)

// 切出绘制模式：丢弃未闭合的半成品多边形，保留已完成要素（草稿）
watch(
  () => uiStore.interactionMode,
  (mode) => {
    if (mode !== 'draw') {
      drawStore.clearActiveVertices()
    }
  },
)

// 孤儿草稿安全网：草稿/编辑图层在工作区被移除时，清空绘制 store，避免悬空状态
watch(
  () => layersStore.activeLayers.map((l) => l.instanceId),
  (ids) => {
    const draftId = drawStore.draftLayerId
    const editingId = drawStore.editingLayerId
    if ((draftId && !ids.includes(draftId)) || (editingId && !ids.includes(editingId))) {
      drawStore.clearDraft()
      if (uiStore.interactionMode === 'draw') {
        uiStore.setInteractionMode('move')
      }
    }
  },
)

// L3：刷新后恢复未保存草稿 —— 重建草稿图层并回填要素
{
  const restored = drawStore.restoreDraft()
  if (restored && drawStore.features.length > 0) {
    const name = drawStore.draftLayerName || '恢复的绘制图层'
    const layer = layersStore.addDrawDraftLayer(name)
    drawStore.setDraftLayerId(layer.instanceId)
    logStore.logOperation('draw-restore', `已恢复未保存草稿 (${drawStore.features.length} 个要素)`)
  } else if (restored === false && drawStore.editingLayerId) {
    // 编辑已有图层的草稿恢复暂不自动进入，等用户切到 draw 模式
  }
}

window.addEventListener('draw:save', handleDrawSave)
window.addEventListener('draw:toggle-attr-table', handleToggleAttrTable)

// ── 自动定位 ──────────────────────────────────────────────────────────────
const isLocating = ref(false)
const locateError = ref<{ message: string; hint: string } | null>(null)
let locationMarkerCleanup: (() => void) | null = null
let locateErrorTimer: ReturnType<typeof setTimeout> | null = null

function _showLocateError(message: string, hint: string) {
  locateError.value = { message, hint }
  if (locateErrorTimer) clearTimeout(locateErrorTimer)
  locateErrorTimer = setTimeout(() => {
    locateError.value = null
  }, 6000)
}

function _clearLocationMarker() {
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
  if (_isUnmounted || !state.resources.map) return
  const el = document.createElement('div')
  el.className = 'inspect-point-marker'
  el.innerHTML = '<div class="inspect-dot"></div>'
  const marker = new maplibregl.Marker({ element: el })
    .setLngLat([point.lng, point.lat])
    .addTo(mapInstance)
  inspectMarkerCleanup = () => marker.remove()
}

// inspectPoint 是 {lng, lat} 浅对象，用字符串键浅 watch 替代 deep watch
watch(
  () => (props.inspectPoint ? `${props.inspectPoint.lng},${props.inspectPoint.lat}` : null),
  () => {
    void _syncInspectMarker(props.inspectPoint)
  },
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
      if (_isUnmounted || !state.resources.map) {
        isLocating.value = false
        return
      }
      const el = document.createElement('div')
      el.className = 'geolocation-marker'
      el.innerHTML = '<div class="geo-pulse"></div><div class="geo-dot"></div>'
      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([longitude, latitude])
        .addTo(state.resources.map)
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
    <!-- 3D globe 深空星图背景层（2D 时淡出；在地图画布之下）
         suppress-galaxy：「自然/无」档隐藏银河白带（左上亮来源），「标准」档保留 -->
    <GlobeStarfield
      :mode="globeBackgroundMode"
      :active="globeProjectionOn"
      :suppress-galaxy="globeDaylightMode !== 'standard'"
    />

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
    <!-- 3D globe 下不渲染屏幕空间时间铬层（昼夜统一由地理夜半球遮罩负责，
         避免"两条晨昏线"；v-if 比 CSS display:none 可靠，不受缓存/级联影响） -->
    <div v-if="!globeProjectionOn" class="time-sheen"></div>
    <div v-if="!globeProjectionOn" class="time-band"></div>
    <!-- weather/grid-overlay 的方向性光斑与网格是 2D 氛围层：
         「自然/无」档隐藏（亮暗只由晨昏线/统一亮度负责），「标准」档保留质感 -->
    <div
      v-if="!globeProjectionOn || globeDaylightMode === 'standard'"
      class="weather-overlay"
    ></div>
    <div v-if="!globeProjectionOn" class="grid-overlay"></div>

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

    <!-- Layer info card -->
    <div class="map-note">
      <h2>{{ stageDisplayModel.noteTitle }}</h2>
      <p>{{ stageDisplayModel.noteSummary }}</p>
      <span class="map-note-meta">{{ stageDisplayModel.noteMeta }}</span>
      <div class="time-indicator" aria-hidden="true">
        <div class="time-indicator-fill"></div>
      </div>
    </div>

    <!-- 绘制工具栏 -->
    <DrawToolbar />

    <!-- 分区统计卡片 -->
    <ZonalStatsCard />

    <!-- 矢量属性表 -->
    <VectorAttributeTable v-if="attrTableVisible" @close="attrTableVisible = false" />

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
