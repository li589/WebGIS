/**
 * Weather viewport + wind display slice extracted from the layers god store.
 * Public API remains re-exported via useLayersStore(); this module owns the refs
 * and debounce timers so index.ts stays focused on catalog/job lifecycle.
 */
import { ref } from 'vue'

import type { WindDisplayMode } from '../../components/map/wind-display-mode'
import type { BoundingBox } from '../../services/runtime-api'

const VIEWPORT_DEBOUNCE_MS = 500
const WEATHER_VIEWPORT_DEBOUNCE_MS = 200
/** 防抖上限：即使持续缩放，最多等 600ms 后必须触发 setViewport */
const WEATHER_VIEWPORT_MAX_WAIT_MS = 600
/** Zoom-out 快速防抖：缩小视口时更快触发瓦片调度，减少新区域空白等待 */
const WEATHER_VIEWPORT_ZOOMOUT_DEBOUNCE_MS = 80
const WEATHER_VIEWPORT_ZOOMOUT_MAX_WAIT_MS = 250
/** 判定为 zoom-out 的最小 zoom 减小量 */
const ZOOM_OUT_THRESHOLD = 0.3

export interface WeatherViewportActiveLayer {
  catalogId: string
  visible: boolean
  jobLayer?: unknown
}

export interface WeatherViewportSliceDeps {
  getActiveLayers: () => WeatherViewportActiveLayer[]
  isWeatherEngineLayer: (catalogId: string) => boolean
  supportsViewportDrivenRefresh: (catalogId: string) => boolean
  getCurrentHour: () => number
  weatherProviderArg: (catalogId: string) => string
  setWeatherTileViewport: (
    catalogId: string,
    center: { lng: number; lat: number },
    zoom: number,
    hour: number,
    model: undefined,
    bbox: BoundingBox | null,
    provider: string,
  ) => void
  /** Called after workflow viewport debounce with a fresh epoch */
  onWorkflowViewportRefresh: (epoch: number) => void
  debugLog: (module: string, ...args: unknown[]) => void
}

export function createWeatherViewportSlice(deps: WeatherViewportSliceDeps) {
  // 粒子流 / 动画流线性能开销大且视觉冲突，同一时间只允许一个图层启用
  // particleFlowCatalogId：当前风场三态所属图层（含 mode=off 时仍保留，便于再切换）
  // 实际是否渲染：windDisplayMode !== 'off' 时由 overlay 的 getEnabled… 过滤
  // windDisplayMode：particle | streamline | off
  const particleFlowCatalogId = ref<string | null>(null)
  const windDisplayMode = ref<WindDisplayMode>('off')

  const viewportDebounceTimer = ref<number | null>(null)
  /** 视口驱动 workflow 刷新世代：防抖触发时递增；过期提交/轮询写回丢弃 */
  let viewportRefreshEpoch = 0

  // 天气瓦片 setViewport 防抖：用户连续移动时避免每次都取消在途瓦片
  const weatherViewportDebounceTimer = ref<number | null>(null)
  let weatherViewportMaxWaitTimer: ReturnType<typeof setTimeout> | null = null

  const currentMapCenter = ref<{ lng: number; lat: number }>({ lng: 113.2644, lat: 23.1291 })
  const currentMapBBox = ref<BoundingBox | null>(null)
  const currentMapZoom = ref(4.8)

  /** 平滑渲染开关：启用后天气标量场使用 WebGL 双线性插值（平滑过渡），关闭则为网格色块。
   *  默认启用：WebGL 可用时自动平滑，不可用时透明回退网格。 */
  const smoothRendering = ref(true)
  function setSmoothRendering(v: boolean) {
    smoothRendering.value = v
  }

  function isViewportRefreshStale(expectedEpoch: number | undefined): boolean {
    return expectedEpoch !== undefined && expectedEpoch !== viewportRefreshEpoch
  }

  function getViewportRefreshEpoch(): number {
    return viewportRefreshEpoch
  }

  /** 设置风场显示三态。off 仍保留 particleFlowCatalogId，便于 UI 再切回。
   *  模式切换后立即刷新视口瓦片数据，确保 Canvas 控制器拿到当前视口的 merged geojson，
   *  避免使用旧视口数据导致流场/等值线定位偏移。 */
  function setWindDisplayMode(catalogId: string, mode: WindDisplayMode) {
    const modeChanged = windDisplayMode.value !== mode
    particleFlowCatalogId.value = catalogId
    windDisplayMode.value = mode
    if (modeChanged && mode !== 'off') {
      flushWeatherTileViewports()
    }
  }

  /** 切换粒子流：兼容薄封装（on→particle，off→off） */
  function toggleParticleFlow(catalogId: string) {
    if (particleFlowCatalogId.value === catalogId && windDisplayMode.value !== 'off') {
      setWindDisplayMode(catalogId, 'off')
    } else {
      setWindDisplayMode(catalogId, 'particle')
    }
  }

  /** 直接设置粒子流启用图层（设为 null 关闭）；开启时默认 particle */
  function setParticleFlow(catalogId: string | null) {
    if (!catalogId) {
      particleFlowCatalogId.value = null
      windDisplayMode.value = 'off'
      return
    }
    setWindDisplayMode(catalogId, 'particle')
  }

  /** 图层移除/隐藏时清空该层风场归属 */
  function clearWindForCatalog(catalogId: string) {
    if (particleFlowCatalogId.value === catalogId) {
      particleFlowCatalogId.value = null
      windDisplayMode.value = 'off'
    }
  }

  /** 若尚无风场归属且该层支持粒子流，则默认开启 particle */
  function enableParticleIfUnset(catalogId: string) {
    if (!particleFlowCatalogId.value) {
      particleFlowCatalogId.value = catalogId
      windDisplayMode.value = 'particle'
    }
  }

  function cancelWeatherViewportDebounce() {
    if (weatherViewportDebounceTimer.value !== null) {
      window.clearTimeout(weatherViewportDebounceTimer.value)
      weatherViewportDebounceTimer.value = null
    }
    if (weatherViewportMaxWaitTimer !== null) {
      clearTimeout(weatherViewportMaxWaitTimer)
      weatherViewportMaxWaitTimer = null
    }
  }

  /** 立即把当前视口推给所有可见天气图层（小时变化等离散操作） */
  function flushWeatherTileViewports(hour?: number) {
    cancelWeatherViewportDebounce()
    const h = hour ?? deps.getCurrentHour()
    for (const layer of deps.getActiveLayers()) {
      if (layer.visible && deps.isWeatherEngineLayer(layer.catalogId)) {
        deps.setWeatherTileViewport(
          layer.catalogId,
          currentMapCenter.value,
          currentMapZoom.value,
          h,
          undefined,
          currentMapBBox.value,
          deps.weatherProviderArg(layer.catalogId),
        )
      }
    }
  }

  /** 处理视口变化：防抖后刷新活跃的地图型工作流（天气图层由 tile manager 处理） */
  function handleViewportChange() {
    const activeMapLayerIds = deps
      .getActiveLayers()
      .filter(
        (layer) =>
          layer.visible &&
          deps.supportsViewportDrivenRefresh(layer.catalogId) &&
          !deps.isWeatherEngineLayer(layer.catalogId) &&
          layer.jobLayer,
      )
      .map((layer) => layer.catalogId)
    deps.debugLog(
      'handleViewportChange',
      'debounce',
      VIEWPORT_DEBOUNCE_MS,
      'ms',
      'activeLayers',
      activeMapLayerIds,
      'bbox',
      currentMapBBox.value,
    )
    if (viewportDebounceTimer.value !== null) {
      window.clearTimeout(viewportDebounceTimer.value)
      viewportDebounceTimer.value = null
    }

    viewportDebounceTimer.value = window.setTimeout(() => {
      viewportDebounceTimer.value = null
      viewportRefreshEpoch += 1
      const epoch = viewportRefreshEpoch
      deps.onWorkflowViewportRefresh(epoch)
    }, VIEWPORT_DEBOUNCE_MS)
  }

  /** 更新当前地图视口（中心点 + 可见 bbox + zoom），由 MapCanvas 在 moveend/zoomend 时调用 */
  function setMapViewport(
    center: { lng: number; lat: number },
    bbox: BoundingBox | null,
    zoom?: number,
  ) {
    const bboxChanged = JSON.stringify(currentMapBBox.value) !== JSON.stringify(bbox)
    const prevZoom = currentMapZoom.value
    currentMapCenter.value = center
    currentMapBBox.value = bbox
    if (typeof zoom === 'number' && Number.isFinite(zoom)) {
      currentMapZoom.value = zoom
    }

    const hasVisibleWeatherLayer = deps
      .getActiveLayers()
      .some((layer) => layer.visible && deps.isWeatherEngineLayer(layer.catalogId))
    if (hasVisibleWeatherLayer) {
      // Zoom-out 快速路径：缩小时用更短防抖，让新区域瓦片更快开始加载
      const isZoomOut = typeof zoom === 'number' && prevZoom - zoom >= ZOOM_OUT_THRESHOLD
      const debounceMs = isZoomOut
        ? WEATHER_VIEWPORT_ZOOMOUT_DEBOUNCE_MS
        : WEATHER_VIEWPORT_DEBOUNCE_MS
      const maxWaitMs = isZoomOut
        ? WEATHER_VIEWPORT_ZOOMOUT_MAX_WAIT_MS
        : WEATHER_VIEWPORT_MAX_WAIT_MS

      // 防抖 + maxWait：持续缩放时最多等 maxWaitMs 后必须触发 setViewport，
      // 避免高频缩放导致防抖定时器不断重置、setViewport 永远不触发
      if (weatherViewportDebounceTimer.value !== null) {
        window.clearTimeout(weatherViewportDebounceTimer.value)
      }
      const snapCenter = center
      const snapZoom = currentMapZoom.value
      const snapHour = deps.getCurrentHour()
      const snapBbox = bbox

      const fireViewport = () => {
        weatherViewportDebounceTimer.value = null
        weatherViewportMaxWaitTimer = null
        for (const layer of deps.getActiveLayers()) {
          if (layer.visible && deps.isWeatherEngineLayer(layer.catalogId)) {
            deps.setWeatherTileViewport(
              layer.catalogId,
              snapCenter,
              snapZoom,
              snapHour,
              undefined,
              snapBbox,
              deps.weatherProviderArg(layer.catalogId),
            )
          }
        }
      }

      weatherViewportDebounceTimer.value = window.setTimeout(fireViewport, debounceMs)
      // maxWait 保证：首次设防抖时同时起 maxWait 定时器，
      // 后续重置防抖不重置 maxWait，确保最多 maxWaitMs 后强制触发
      if (weatherViewportMaxWaitTimer === null) {
        weatherViewportMaxWaitTimer = setTimeout(() => {
          if (weatherViewportDebounceTimer.value !== null) {
            window.clearTimeout(weatherViewportDebounceTimer.value)
            fireViewport()
          }
        }, maxWaitMs)
      }
    }

    if (
      bboxChanged &&
      deps
        .getActiveLayers()
        .some(
          (layer) =>
            deps.supportsViewportDrivenRefresh(layer.catalogId) &&
            layer.jobLayer &&
            !deps.isWeatherEngineLayer(layer.catalogId),
        )
    ) {
      handleViewportChange()
    }
  }

  return {
    particleFlowCatalogId,
    windDisplayMode,
    currentMapCenter,
    currentMapBBox,
    currentMapZoom,
    smoothRendering,
    setWindDisplayMode,
    toggleParticleFlow,
    setParticleFlow,
    clearWindForCatalog,
    enableParticleIfUnset,
    setSmoothRendering,
    isViewportRefreshStale,
    getViewportRefreshEpoch,
    handleViewportChange,
    setMapViewport,
    flushWeatherTileViewports,
    cancelWeatherViewportDebounce,
  }
}

export type WeatherViewportSlice = ReturnType<typeof createWeatherViewportSlice>
