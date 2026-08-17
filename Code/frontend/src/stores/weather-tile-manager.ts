/**
 * 天气瓦片调度管理器。
 *
 * 职责：
 * - 按图层维护瓦片缓存（fetchedAt/lastAccess + TTL SWR）、视口、世代号。
 * - 全局并发槽位（上限 6），与后端 WeatherTileService semaphore 对齐。
 * - 图层内优先级：0=视口@H → 1=邻域 depth3/父级@H → 2=子级 z+1@H → 3=视口@H±1。
 * - 视口瓦片按距地图中心从近到远入队，减少缩放后「边缘先亮、中心空洞」。
 * - 多层（可见≥2）：同优先级跨图层 round-robin；邻域 depth=1；跳过邻小时预取。
 * - 移动/缩放时 generation++，丢弃过期结果并取消不在目标集合内的请求。
 * - 每个瓦片通过 GET /weather/tiles 拉取 GeoJSON（服务端缓存/生成）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { useLogStore } from './log'
import {
  fetchWeatherTile,
  sortTilesCenterFirst,
  tileToLngLatBounds,
  tilesInBounds,
  type LngLatBounds,
  type WeatherTileCoords,
} from '../services/weather-tile-api'
import {
  buildMergeStats,
  centerInLngBounds,
  formatMergeStats,
  tileBoundsOverlapViewport,
  type MergedWeatherTile,
} from '../services/weather-tile-utils'
import type { WindGeoJSON } from '../types/map-geo'
import {
  debugLog as probeDebugLog,
  isPerfEnabled,
  perfIncBump,
  perfMark,
  perfNoteViewportFill,
} from '../utils/perf-probe'
import {
  boostConcurrencyForZoomOut,
  checkWeatherTileMemoryPressure,
  getWeatherTileMaxConcurrent,
  recordWeatherTileFailure,
  recordWeatherTileSuccess,
  resetWeatherTileConcurrencyForTests,
  setWeatherTileConcurrencyDebugLog,
} from './weather-tile-concurrency'
import { trimWeatherLayerTileCache } from './weather-tile-cache-trim'
// P1-1: 从 God Store 拆分的模块
import {
  ADJACENT_HOUR_PRIORITY,
  BACKOFF_429_MS,
  BACKOFF_503_MS,
  BACKOFF_TIMEOUT_MS,
  CHILD_PREFETCH_PENDING_STRESS,
  DATA_VERSION_COALESCE_MS,
  DATA_VERSION_ZOOMOUT_COALESCE_MS,
  GAP_SWEEP_MS,
  GAP_SWEEP_STRESSED_MS,
  GAP_SWEEP_ZOOM_CHANGE_MS,
  HOUR_MAX,
  HOUR_MIN,
  MAX_429_RETRIES,
  MAX_503_RETRIES,
  MAX_SOFT_REQUEUES,
  MAX_TIMEOUT_RETRIES,
  MULTI_LAYER_PREFETCH_THRESHOLD,
  PREFETCH_NEIGHBOR_DEPTH,
  PREFETCH_NEIGHBOR_DEPTH_MULTI_LAYER,
  SOFT_REQUEUE_MS,
  ZOOM_OUT_TRANSITION_MS,
  isWeatherLayerUnsupportedByModel,
  resolveConfiguredWeatherModel,
  type LayerState,
  type LayerTileStats,
  type TileKey,
  type TileRequest,
  type WeatherTileErrorType,
  type WeatherTileLayerStatus,
  type WeatherWorkflowContribution,
  type WeatherWorkflowContributionItem,
  type WeatherWorkflowMappedStatus,
} from './weather-tile-types'
import {
  classifyTileError,
  isAbortError,
  parseTileCoordsFromCacheKey,
  type DebugLogFn,
} from './weather-tile-errors'
import {
  bboxApproxEqual,
  boundsFromCenter,
  cancelPendingRequest,
  isTileFresh,
  makeTileEntry,
  resolveTileZoom,
  tileCoordsToKey,
  tileKeySetEqual,
} from './weather-tile-utils-store'
import {
  clearMergeCacheForLayer,
  getMergedGeojsonForViewport as getMergedGeojsonForViewportImpl,
  type MergeCache,
} from './weather-tile-merge'

// P1-1: 常量 / 类型 / 纯函数已拆至 weather-tile-types.ts、weather-tile-errors.ts、weather-tile-utils-store.ts
// 此处仅保留 re-export 以维持向后兼容（外部 import 路径不变）
export { DEFAULT_WEATHER_MODEL, isWeatherLayerUnsupportedByModel } from './weather-tile-types'
export type {
  CachedTileEntry,
  LayerTileStats,
  WeatherTileErrorType,
  WeatherTileLayerStatus,
  WeatherWorkflowContribution,
  WeatherWorkflowContributionItem,
  WeatherWorkflowMappedStatus,
} from './weather-tile-types'

let globalSequence = 0
let activeFetchCount = 0
/** 同优先级跨图层轮询游标，避免先入队图层饿死后图层 */
let layerRoundRobinCursor = 0
/** 跟踪 429/503 重试定时器，在 clearLayer 时统一清理避免访问已销毁的图层状态 */
const pendingRetryTimers = new Set<ReturnType<typeof setTimeout>>()
/** 软重拉次数（cacheKey → count），超出后停止自动重拉，避免工作流指示器卡死 */
const softRequeueCounts = new Map<string, number>()
/** 图层级视口补洞定时器（layerId → timer） */
const gapSweepTimers = new Map<string, ReturnType<typeof setTimeout>>()

/** 单测：重置模块级并发/定时器状态（多文件并行时避免串扰） */
export function __testResetWeatherTileManagerModuleState(): void {
  globalSequence = 0
  activeFetchCount = 0
  layerRoundRobinCursor = 0
  for (const timer of pendingRetryTimers) clearTimeout(timer)
  pendingRetryTimers.clear()
  softRequeueCounts.clear()
  for (const timer of gapSweepTimers.values()) clearTimeout(timer)
  gapSweepTimers.clear()
  resetWeatherTileConcurrencyForTests()
}

// P1-1: debugLog 保留在此处（依赖 probeDebugLog + performance.now）
const debugLog: DebugLogFn = (module: string, ...args: unknown[]) => {
  probeDebugLog(`[${performance.now().toFixed(1)}ms] [WeatherTileManager:${module}]`, ...args)
}
setWeatherTileConcurrencyDebugLog(debugLog)

export const useWeatherTileManager = defineStore('weatherTileManager', () => {
  // 全局数据版本号：瓦片缓存变化时递增，供组件 watch 触发重渲染
  const dataVersion = ref(0)
  // 状态版本号：错误/加载状态变化时递增，供 UI watch 触发响应式更新
  const statusVersion = ref(0)
  // 活跃度版本号：pending 数量变化时递增，供标题栏工作流状态按钮响应式更新
  const activityVersion = ref(0)
  // 图层状态：使用普通 Map，依赖 dataVersion/statusVersion 触发响应式更新
  const layerStates = new Map<string, LayerState>()
  // P1-1: mergeCache 类型从 weather-tile-merge 导入
  const mergeCache: MergeCache = new Map<string, WindGeoJSON | null>()
  let dataVersionBumpTimer: ReturnType<typeof setTimeout> | null = null
  /** 视口从有洞到铺满的计时起点（perf） */
  const viewportFillStartedAt = new Map<string, number>()

  function anyLayerUnderWeatherPressure(): boolean {
    for (const state of layerStates.values()) {
      if (!state.visible) continue
      if (
        state.lastErrorType === 'circuit-open' ||
        state.lastErrorType === 'rate-limited' ||
        state.lastErrorType === 'timeout'
      ) {
        return true
      }
    }
    return false
  }

  /** 参与抢槽的可见天气层数（排除 data-empty） */
  function countCompetingWeatherLayers(): number {
    let n = 0
    for (const state of layerStates.values()) {
      if (!state.visible) continue
      if (isLayerDataEmpty(state)) continue
      n += 1
    }
    return n
  }

  function isMultiLayerPrefetchMode(): boolean {
    return countCompetingWeatherLayers() >= MULTI_LAYER_PREFETCH_THRESHOLD
  }

  function viewportCachedCount(state: LayerState): number {
    let cached = 0
    for (const tile of state.viewportTiles) {
      const key = tileCoordsToKey(tile, state.layerId, state.hour, state.model, state.provider)
      if (state.tiles.has(key)) cached += 1
    }
    return cached
  }

  /** 当前 model/provider 是否已被 422 标记为「图层无数据」 */
  function isLayerDataEmpty(state: LayerState): boolean {
    return (
      state.dataEmptyScope !== null && state.dataEmptyScope === `${state.model}|${state.provider}`
    )
  }

  function countViewportMissing(state: LayerState): number {
    // 无数据图层不再统计缺口：gap sweep / 状态指示随之停止，而非永远「加载中」
    if (isLayerDataEmpty(state)) return 0
    let missing = 0
    for (const tile of state.viewportTiles) {
      const key = tileCoordsToKey(tile, state.layerId, state.hour, state.model, state.provider)
      if (!state.tiles.has(key)) missing += 1
    }
    return missing
  }

  function clearGapSweep(layerId: string): void {
    const timer = gapSweepTimers.get(layerId)
    if (timer !== undefined) {
      clearTimeout(timer)
      gapSweepTimers.delete(layerId)
      statusVersion.value += 1
    }
  }

  function gapSweepDelayMs(): number {
    if (anyLayerUnderWeatherPressure()) return GAP_SWEEP_STRESSED_MS
    if (anyLayerInZoomOutTransition()) return GAP_SWEEP_ZOOM_CHANGE_MS
    return GAP_SWEEP_MS
  }

  /** 任意图层在 zoom-out 过渡期内（最近 3s 发生过 zoom 变化） */
  function anyLayerInZoomOutTransition(): boolean {
    const now = Date.now()
    for (const state of layerStates.values()) {
      if (!state.visible) continue
      if (state.lastZoomChangedAt > 0 && now - state.lastZoomChangedAt < ZOOM_OUT_TRANSITION_MS)
        return true
    }
    return false
  }

  /**
   * 限流/断路期间 pickNextRequest 会跳过 priority>0，未派发的预取会永久占着 pending。
   * 压力期主动丢掉未派发预取，避免「假运行」和补洞逻辑被卡住。
   */
  function dropUndispatchedPrefetchWhenStressed(): void {
    if (!anyLayerUnderWeatherPressure()) return
    let dropped = 0
    for (const state of layerStates.values()) {
      if (!state.visible) continue
      for (const [key, request] of [...state.pending.entries()]) {
        if (request.priority > 0 && request.dispatched !== true) {
          cancelPendingRequest(request)
          state.pending.delete(key)
          dropped += 1
        }
      }
    }
    if (dropped > 0) {
      debugLog('dropPrefetch', `dropped=${dropped}`)
      activityVersion.value += 1
    }
  }

  /** 视口仍有缺口时确保低频补洞扫描；soft 封顶后的安全网 */
  function ensureGapSweep(layerId: string): void {
    dropUndispatchedPrefetchWhenStressed()
    const state = layerStates.get(layerId)
    if (!state || !state.visible) {
      clearGapSweep(layerId)
      return
    }
    if (countViewportMissing(state) === 0) {
      clearGapSweep(layerId)
      return
    }
    if (gapSweepTimers.has(layerId)) return
    const delay = gapSweepDelayMs()
    debugLog(
      'gapSweep schedule',
      layerId,
      `delay=${delay}ms`,
      `missing=${countViewportMissing(state)}`,
    )
    const timer = setTimeout(() => {
      gapSweepTimers.delete(layerId)
      runGapSweep(layerId)
    }, delay)
    gapSweepTimers.set(layerId, timer)
    statusVersion.value += 1
  }

  function runGapSweep(layerId: string): void {
    dropUndispatchedPrefetchWhenStressed()
    const state = layerStates.get(layerId)
    if (!state || !state.visible) {
      clearGapSweep(layerId)
      return
    }

    const generation = state.generation
    let enqueuedAny = false
    let missingAfter = 0
    for (const tile of state.viewportTiles) {
      const cacheKey = tileCoordsToKey(tile, layerId, state.hour, state.model, state.provider)
      const cached = state.tiles.get(cacheKey)
      if (cached && isTileFresh(cached)) continue
      if (!cached) missingAfter += 1
      if (state.pending.has(cacheKey)) continue
      // 重置 soft 计数，允许再走一轮快路径重试；stale 走 priority≥1 SWR
      softRequeueCounts.delete(cacheKey)
      const priority = cached ? 1 : 0
      if (enqueueIfMissing(state, tile, priority, generation)) enqueuedAny = true
    }

    if (enqueuedAny) {
      activityVersion.value += 1
      drainQueue()
    }

    missingAfter = countViewportMissing(state)
    debugLog('gapSweep run', layerId, `enqueued=${enqueuedAny}`, `missing=${missingAfter}`)

    if (missingAfter === 0) {
      if (
        state.lastErrorType === 'timeout' ||
        state.lastErrorType === 'circuit-open' ||
        state.lastErrorType === 'rate-limited'
      ) {
        clearLayerError(layerId)
      }
      clearGapSweep(layerId)
      return
    }

    // 仍有缺口：继续下一轮（ensure 会新建定时器）
    ensureGapSweep(layerId)
  }

  function scheduleDataVersionBump(): void {
    // 合并短窗内连续到达的瓦片：只 bump 一次；mergeCache 按 coverageSig 自然失效，勿全清
    if (dataVersionBumpTimer !== null) return
    // Zoom-out 过渡期用更短窗口，让首批瓦片更快触发渲染更新
    const coalesceMs = anyLayerInZoomOutTransition()
      ? DATA_VERSION_ZOOMOUT_COALESCE_MS
      : DATA_VERSION_COALESCE_MS
    dataVersionBumpTimer = setTimeout(() => {
      dataVersionBumpTimer = null
      dataVersion.value += 1
      perfIncBump()
      if (isPerfEnabled()) {
        let tileCount = 0
        for (const state of layerStates.values()) tileCount += state.tiles.size
        perfMark('tile.cacheSize', { tiles: tileCount, mergeCache: mergeCache.size })
      }
    }, coalesceMs)
  }

  function noteViewportFillProgress(layerId: string, state: LayerState): void {
    const missing = countViewportMissing(state)
    if (missing > 0) {
      if (!viewportFillStartedAt.has(layerId)) {
        viewportFillStartedAt.set(layerId, performance.now())
      }
      return
    }
    const started = viewportFillStartedAt.get(layerId)
    if (started !== undefined) {
      perfNoteViewportFill(performance.now() - started)
      viewportFillStartedAt.delete(layerId)
    }
  }

  function countGlobalPending(): number {
    let n = 0
    for (const state of layerStates.values()) n += state.pending.size
    return n
  }

  function shouldPauseChildPrefetch(): boolean {
    return anyLayerUnderWeatherPressure() || countGlobalPending() >= CHILD_PREFETCH_PENDING_STRESS
  }

  // P1-1: buildMergeCacheKey / rememberMergeCache 已拆至 weather-tile-merge.ts

  function getOrCreateState(layerId: string): LayerState {
    let state = layerStates.get(layerId)
    if (!state) {
      state = {
        layerId,
        generation: 0,
        visible: false,
        center: { lng: 0, lat: 0 },
        zoom: 0,
        mapZoom: 0,
        hour: 0,
        model: resolveConfiguredWeatherModel(),
        provider: 'auto',
        bbox: null,
        viewportTiles: [],
        prefetchRing: [],
        tiles: new Map(),
        pending: new Map(),
        lastMergedGeojson: null,
        lastMergedFeatureCount: 0,
        lastErrorType: null,
        lastErrorMessage: null,
        dataEmptyScope: null,
        lastZoomChangedAt: 0,
      }
      layerStates.set(layerId, state)
    }
    return state
  }

  /** 设置图层错误状态并触发 UI 更新 */
  function setLayerError(layerId: string, errorType: WeatherTileErrorType, message: string): void {
    const state = layerStates.get(layerId)
    if (!state) return
    // 避免重复记录相同错误
    const isNewError = state.lastErrorType !== errorType || state.lastErrorMessage !== message
    state.lastErrorType = errorType
    state.lastErrorMessage = message
    statusVersion.value += 1
    if (isNewError) {
      const logStore = useLogStore()
      logStore.logWorkflow('weather-tile-error', `[${layerId}] ${message}`)
    }
  }

  /** 清除图层错误状态并触发 UI 更新 */
  function clearLayerError(layerId: string): void {
    const state = layerStates.get(layerId)
    if (!state || !state.lastErrorType) return
    state.lastErrorType = null
    state.lastErrorMessage = null
    statusVersion.value += 1
  }

  function setLayerActive(layerId: string, active: boolean): void {
    const state = getOrCreateState(layerId)
    if (state.visible === active) return
    state.visible = active
    if (!active) {
      // 抬升世代，使隐藏前已发出的在途请求写回失效
      state.generation += 1
      // 隐藏时取消所有在途请求；槽位由 submitTile finally 统一释放
      for (const request of state.pending.values()) {
        cancelPendingRequest(request)
      }
      state.pending.clear()
      // 重新激活即视为手动重试：清除「无数据」短路（用户可能已补齐同步）
      state.dataEmptyScope = null
      clearGapSweep(layerId)
      activityVersion.value += 1
    }
    debugLog('setLayerActive', layerId, active, 'generation', state.generation)
  }

  function clearLayer(layerId: string): void {
    const state = layerStates.get(layerId)
    if (!state) return
    state.generation += 1
    state.visible = false
    for (const request of state.pending.values()) {
      cancelPendingRequest(request)
    }
    state.pending.clear()
    clearGapSweep(layerId)
    // 不清空全局 pendingRetryTimers：已删除图层的定时器回调会通过
    // layerStates.get(layerId) / generation 检查自动跳过，不会访问已删除状态。
    // 清空全部会取消其他活跃图层的 429/timeout 重试，导致视口空洞。
    activityVersion.value += 1
    layerStates.delete(layerId)
    // 清理当前图层的合并缓存与软重拉计数，保留其他图层的缓存
    clearMergeCacheForLayer(mergeCache, layerId)
    // 同 id 重建图层时不得继承旧填充起点，否则 viewport-fill 指标失真
    viewportFillStartedAt.delete(layerId)
    for (const key of Array.from(softRequeueCounts.keys())) {
      if (key.startsWith(`${layerId}:`)) softRequeueCounts.delete(key)
    }
    debugLog('clearLayer', layerId)
  }

  // P1-1: bboxApproxEqual / tileKeySetEqual / resolveTileZoom 已拆至 weather-tile-utils-store.ts

  function setViewport(
    layerId: string,
    center: { lng: number; lat: number },
    zoom: number,
    hour: number,
    model?: string,
    bbox?: { west: number; south: number; east: number; north: number } | null,
    provider?: string,
  ): void {
    const state = getOrCreateState(layerId)
    if (!state.visible) return

    const resolvedModel = resolveConfiguredWeatherModel(model)
    // Explicit provider string required to change source; omit/undefined keeps current
    // (avoids accidental reset to auto when a caller forgets the 7th arg).
    const resolvedProvider =
      provider === undefined ? state.provider || 'auto' : provider.trim() || 'auto'

    // 模型 × 图层 结构性不支持（如 visibility × ecmwf_ifs025）：短路不发请求，
    // 复用 data-empty 链路给出提示；换用支持的模型后 scope 失配自动恢复。
    if (isWeatherLayerUnsupportedByModel(layerId, resolvedModel)) {
      state.model = resolvedModel
      state.provider = resolvedProvider
      state.hour = hour
      state.dataEmptyScope = `${resolvedModel}|${resolvedProvider}`
      setLayerError(
        layerId,
        'data-empty',
        `当前模型（${resolvedModel}）不提供该图层变量，请切换其他气象模型`,
      )
      clearGapSweep(layerId)
      return
    }
    const nextBbox = bbox
      ? {
          west: bbox.west,
          south: bbox.south,
          east: bbox.east,
          north: bbox.north,
        }
      : null
    const bounds = nextBbox ?? boundsFromCenter(center, Math.max(0, Math.min(12, Math.round(zoom))))
    const clampedZoom = resolveTileZoom(bounds, zoom)
    const viewportTiles = sortTilesCenterFirst(
      tilesInBounds(bounds, clampedZoom, 0),
      center.lng,
      center.lat,
    )
    const multiLayer = isMultiLayerPrefetchMode()
    const neighborDepth = multiLayer ? PREFETCH_NEIGHBOR_DEPTH_MULTI_LAYER : PREFETCH_NEIGHBOR_DEPTH
    const prefetchRing = tilesInBounds(bounds, clampedZoom, neighborDepth).filter(
      (t) => !viewportTiles.some((vt) => vt.x === t.x && vt.y === t.y && vt.z === t.z),
    )
    // 父子 z 预取：换 zoom 时垫底/过渡，减少空洞与错分辨率闪断
    const parentPrefetch = clampedZoom > 0 ? tilesInBounds(bounds, clampedZoom - 1, 0) : []
    const childPrefetch =
      clampedZoom < 12
        ? tilesInBounds(bounds, clampedZoom + 1, 0).filter((t) => {
            // 仅预取覆盖视口中心附近的子瓦片，避免 4× 爆炸（宽跨度用相机中心，勿用 (west+east)/2）
            const midLat = Math.max(-85, Math.min(85, (bounds.south + bounds.north) / 2))
            const midLon = center.lng
            const cx = Math.floor(((midLon + 180) / 360) * 2 ** (clampedZoom + 1))
            const latRad = (midLat * Math.PI) / 180
            const cy = Math.floor(
              ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) *
                2 ** (clampedZoom + 1),
            )
            return Math.abs(t.x - cx) <= 1 && Math.abs(t.y - cy) <= 1
          })
        : []
    // 中心跳出旧视口经度弧：清空 lastMerged，避免错半球锚点污染
    const prevBbox = state.bbox
    if (prevBbox && !centerInLngBounds(center.lng, prevBbox)) {
      state.lastMergedGeojson = null
      state.lastMergedFeatureCount = 0
    }
    // 瓦片集合未变：不抬世代、不重入队；但仍须同步 bbox/center，并通知 overlay 重投影。
    // 旧逻辑在此直接 return 且不更新 bbox → 平移/缩放后 merge 仍按旧视口裁剪，
    // 表现为半屏空白、风场错位叠影，且工作流指示器不刷新。
    if (
      state.hour === hour &&
      state.model === resolvedModel &&
      state.provider === resolvedProvider &&
      Math.round(state.zoom) === clampedZoom &&
      tileKeySetEqual(state.viewportTiles, viewportTiles) &&
      tileKeySetEqual(state.prefetchRing, prefetchRing)
    ) {
      const bboxChanged = !bboxApproxEqual(state.bbox, nextBbox)
      const mapZoomChanged = Math.abs(state.mapZoom - zoom) > 0.05
      state.center = center
      state.bbox = nextBbox
      state.mapZoom = zoom
      if (bboxChanged || mapZoomChanged) {
        debugLog(
          'setViewport view-only',
          layerId,
          `tileZ=${clampedZoom}`,
          `mapZ=${zoom.toFixed(2)}`,
          bboxChanged ? 'bbox' : 'zoom',
        )
        clearMergeCacheForLayer(mergeCache, layerId)
        scheduleDataVersionBump()
      } else {
        debugLog('setViewport skip-noop', layerId, `z=${clampedZoom}`, `hour=${hour}`)
      }
      if (countViewportMissing(state) > 0) ensureGapSweep(layerId)
      return
    }

    const modelChanged = state.model !== resolvedModel
    const providerChanged = state.provider !== resolvedProvider
    const zoomChanged = Math.round(state.zoom) !== clampedZoom
    // 换 tile z（放大/缩小）时临时拉满并发，加速中心与缺口填充
    if (zoomChanged) {
      state.lastZoomChangedAt = Date.now()
      boostConcurrencyForZoomOut()
    }
    state.generation += 1
    const generation = state.generation
    state.center = center
    // 存预算后的 tile z，使 getMerged / gapSweep 与入队一致
    state.zoom = clampedZoom
    state.mapZoom = zoom
    state.hour = hour
    state.model = resolvedModel
    state.provider = resolvedProvider
    state.bbox = nextBbox
    state.viewportTiles = viewportTiles
    state.prefetchRing = prefetchRing

    // 视口已变：清 merge 缓存
    clearMergeCacheForLayer(mergeCache, layerId)
    // 换 tile zoom：勿清空 lastMerged——缩放瞬间本级瓦片往往为 0，
    // 清空会导致整屏闪空；改由多级缓存垫底 + 渐进合并过渡。
    // 立刻通知 overlay 按新视口重取 merge
    scheduleDataVersionBump()

    // 缩放或换源后重置软重拉计数，避免空洞瓦片永久 softRequeue skipped (cap)
    if (zoomChanged || modelChanged || providerChanged) {
      for (const key of Array.from(softRequeueCounts.keys())) {
        if (key.startsWith(`${layerId}:`)) softRequeueCounts.delete(key)
      }
    }

    // Model/provider are part of the cache key; drop prior tiles on change
    if (modelChanged || providerChanged) {
      state.tiles.clear()
      state.lastMergedGeojson = null
      state.lastMergedFeatureCount = 0
      // softRequeueCounts 已在上方 zoomChanged/modelChanged/providerChanged 分支中
      // 按 layerId 前缀清理，此处不再全量清空以免影响其他图层
      for (const request of state.pending.values()) {
        cancelPendingRequest(request)
      }
      state.pending.clear()
    }

    const desiredPrefetch = [
      ...prefetchRing,
      ...parentPrefetch,
      ...(shouldPauseChildPrefetch() ? [] : childPrefetch),
    ]
    const desiredKeys = new Set<string>(
      [...viewportTiles, ...desiredPrefetch].map((t) =>
        tileCoordsToKey(t, layerId, hour, resolvedModel, resolvedProvider),
      ),
    )
    // 邻小时视口预取 keys 也纳入 desired，避免平移后旧邻小时请求占坑
    // 多层模式跳过：释放槽位给各层当前小时视口
    if (!multiLayer) {
      for (const adjHour of [hour - 1, hour + 1]) {
        if (adjHour < HOUR_MIN || adjHour > HOUR_MAX) continue
        for (const t of viewportTiles) {
          desiredKeys.add(tileCoordsToKey(t, layerId, adjHour, resolvedModel, resolvedProvider))
        }
      }
    }

    // 仅驱逐与当前视口不相交的缓存（错半球）；保留叠瓦任意 z 作 underlay，避免缩放时 IDL/半屏空洞
    if (!modelChanged && !providerChanged && nextBbox) {
      for (const key of Array.from(state.tiles.keys())) {
        const coords = parseTileCoordsFromCacheKey(key)
        if (!coords) {
          state.tiles.delete(key)
          continue
        }
        const tb = tileToLngLatBounds(coords.z, coords.x, coords.y)
        if (!tileBoundsOverlapViewport(tb, bounds)) state.tiles.delete(key)
      }
    }

    // 瓦片仍在目标集合内：抬世代，并清退避，避免「等待重试」卡死新视口缺口
    for (const [key, request] of state.pending.entries()) {
      if (!desiredKeys.has(key)) {
        cancelPendingRequest(request)
        state.pending.delete(key)
      } else {
        request.generation = generation
        request.retryAfter = undefined
        // 视口变更后允许重新退避计数，避免旧半球 429 耗尽拖死新缺口
        request.retry429Count = 0
        request.retry503Count = 0
        request.retryTimeoutCount = 0
      }
    }

    // 对视口缺失瓦片以高优先级入队
    // 批量入队后统一递增 activityVersion 一次，避免每瓦片触发响应式更新
    let enqueuedAny = false
    for (const tile of viewportTiles) {
      if (enqueueIfMissing(state, tile, 0, generation)) enqueuedAny = true
    }

    // 限流/断路期间跳过预取，优先填满视口，避免把 API 槽位打满导致持续超时
    // 优先级：视口=0 → 邻域/父级=1 → child z+1=2 → 邻小时视口=3
    // 多层时：压缩邻域 + 跳过邻小时，避免预取饿死其他层视口
    if (!anyLayerUnderWeatherPressure()) {
      for (const tile of prefetchRing) {
        if (enqueueIfMissing(state, tile, 1, generation)) enqueuedAny = true
      }
      for (const tile of parentPrefetch) {
        if (enqueueIfMissing(state, tile, 1, generation)) enqueuedAny = true
      }
      if (!shouldPauseChildPrefetch()) {
        for (const tile of childPrefetch) {
          if (enqueueIfMissing(state, tile, 2, generation)) enqueuedAny = true
        }
      }
      if (!multiLayer) {
        for (const adjHour of [hour - 1, hour + 1]) {
          if (adjHour < HOUR_MIN || adjHour > HOUR_MAX) continue
          for (const tile of viewportTiles) {
            if (enqueueIfMissing(state, tile, ADJACENT_HOUR_PRIORITY, generation, adjHour)) {
              enqueuedAny = true
            }
          }
        }
      }
    }

    if (enqueuedAny) {
      activityVersion.value += 1
    }

    noteViewportFillProgress(layerId, state)

    debugLog(
      'setViewport',
      layerId,
      `gen=${generation}`,
      `z=${clampedZoom}`,
      `hour=${hour}`,
      `bbox=${state.bbox ? `${state.bbox.west.toFixed(1)},${state.bbox.south.toFixed(1)},${state.bbox.east.toFixed(1)},${state.bbox.north.toFixed(1)}` : 'null'}`,
      `viewport=${viewportTiles.length}:[${viewportTiles.map((t) => `${t.x},${t.y}`).join('|')}]`,
      `prefetch=${prefetchRing.length}`,
      `pending=${state.pending.size}`,
      `cached=${state.tiles.size}`,
    )

    drainQueue()
    if (countViewportMissing(state) > 0) {
      ensureGapSweep(layerId)
    } else {
      clearGapSweep(layerId)
    }
  }

  // P1-1: boundsFromCenter 已拆至 weather-tile-utils-store.ts

  /**
   * 为缺失或过期瓦片入队。
   * - fresh 缓存：跳过
   * - stale 缓存：SWR，以 priority≥1 后台重拉（避免指示器一直「运行中」）
   * - hourOverride：邻小时预取
   * 返回 true 表示新建了请求。
   */
  function enqueueIfMissing(
    state: LayerState,
    tile: WeatherTileCoords,
    priority: number,
    generation: number,
    hourOverride?: number,
  ): boolean {
    // 无数据图层短路：一个 422 即说明当前 model/provider 缺该变量，不再入队
    if (isLayerDataEmpty(state)) return false
    const hour = hourOverride ?? state.hour
    const key = tileCoordsToKey(tile, state.layerId, hour, state.model, state.provider)
    const existing = state.tiles.get(key)
    if (existing) {
      existing.lastAccess = Date.now()
      if (isTileFresh(existing)) return false
      // SWR：过期条目仍可渲染，后台以低优先级刷新
      priority = Math.max(priority, 1)
    }
    if (state.pending.has(key)) return false
    const controller = new AbortController()
    const request: TileRequest = {
      key: { layerId: state.layerId, z: tile.z, x: tile.x, y: tile.y, hour },
      layerId: state.layerId,
      priority,
      generation,
      sequence: ++globalSequence,
      controller,
      dispatched: false,
    }
    state.pending.set(key, request)
    return true
  }

  function drainQueue(): void {
    checkWeatherTileMemoryPressure()
    while (activeFetchCount < getWeatherTileMaxConcurrent()) {
      const next = pickNextRequest()
      if (!next) break
      activeFetchCount += 1
      next.dispatched = true
      void submitTile(next)
    }
  }

  function pickNextRequest(): TileRequest | null {
    const now = Date.now()
    const pausePrefetch = anyLayerUnderWeatherPressure()
    const pauseChild = shouldPauseChildPrefetch()
    const visibleStates: LayerState[] = []
    for (const state of layerStates.values()) {
      if (!state.visible) continue
      if (isLayerDataEmpty(state)) continue
      visibleStates.push(state)
    }
    if (visibleStates.length === 0) return null

    type LayerCandidate = { request: TileRequest; layerIndex: number }
    const perLayerBest: LayerCandidate[] = []
    for (let i = 0; i < visibleStates.length; i++) {
      const state = visibleStates[i]!
      let bestForLayer: TileRequest | null = null
      for (const request of state.pending.values()) {
        // 已派发的请求仍在 pending 中（等待 submitTile finally 清理），避免重复调度
        if (request.dispatched) continue
        // 跳过仍在退避期内的瓦片，确保单瓦片重试延迟不被其他 drainQueue 调用绕过
        if (request.retryAfter && now < request.retryAfter) continue
        // 压力期只拉视口瓦片（priority=0）
        if (pausePrefetch && request.priority > 0) continue
        // pending 高时仅暂停 child z+1（priority===2），邻小时 priority=3 仍可在视口填满后调度
        if (pauseChild && request.priority === 2) continue
        if (
          !bestForLayer ||
          request.priority < bestForLayer.priority ||
          (request.priority === bestForLayer.priority && request.sequence < bestForLayer.sequence)
        ) {
          bestForLayer = request
        }
      }
      if (bestForLayer) perLayerBest.push({ request: bestForLayer, layerIndex: i })
    }
    if (perLayerBest.length === 0) return null

    const minPriority = Math.min(...perLayerBest.map((c) => c.request.priority))
    const atMin = perLayerBest.filter((c) => c.request.priority === minPriority)
    // 同优先级跨图层轮询：从 cursor 起找下一层，避免 FIFO 饿死后入队图层
    const start = layerRoundRobinCursor % visibleStates.length
    for (let offset = 0; offset < visibleStates.length; offset++) {
      const idx = (start + offset) % visibleStates.length
      const hit = atMin.find((c) => c.layerIndex === idx)
      if (hit) {
        layerRoundRobinCursor = idx + 1
        return hit.request
      }
    }
    return atMin[0]!.request
  }

  async function submitTile(request: TileRequest): Promise<void> {
    const { key, layerId } = request
    const state = layerStates.get(layerId)
    const cacheKey = tileCoordsToKey(
      { z: key.z, x: key.x, y: key.y },
      layerId,
      key.hour,
      resolveConfiguredWeatherModel(state?.model),
      state?.provider ?? 'auto',
    )

    try {
      // 调度前已过期：直接返回，pending 删除和槽位释放由 finally 统一处理，避免双重扣减
      // 注意：动态读取 request.generation，因为 setViewport 可能已更新它
      if (!state || state.generation !== request.generation) {
        debugLog(
          'submitTile discard stale before submit',
          layerId,
          `z=${key.z} x=${key.x} y=${key.y}`,
        )
        return
      }

      debugLog(
        'submitTile start',
        layerId,
        `z=${key.z} x=${key.x} y=${key.y}`,
        `gen=${request.generation}`,
        `priority=${request.priority}`,
      )
      const fetchStartedAt = performance.now()
      const geojson = await fetchWeatherTile(layerId, key.z, key.x, key.y, {
        hour: key.hour,
        model: state.model,
        provider: state.provider,
        signal: request.controller.signal,
      })
      perfMark('tile.fetchMs', {
        layerId,
        z: key.z,
        x: key.x,
        y: key.y,
        ms: Math.round(performance.now() - fetchStartedAt),
        priority: request.priority,
      })

      // 拉取完成后若图层已隐藏、已清理或世代已更新，丢弃结果
      const finalState = layerStates.get(layerId)
      if (!finalState || !finalState.visible || finalState.generation !== request.generation) {
        debugLog(
          'submitTile discard stale after fetch',
          layerId,
          `z=${key.z} x=${key.x} y=${key.y}`,
          `visible=${finalState?.visible ?? false}`,
          `gen=${request.generation}/${finalState?.generation ?? 'gone'}`,
        )
        return
      }

      finalState.tiles.set(cacheKey, makeTileEntry(geojson))
      softRequeueCounts.delete(cacheKey)
      trimLayerCache(finalState)
      clearLayerError(layerId)
      noteViewportFillProgress(layerId, finalState)
      if (countViewportMissing(finalState) === 0) {
        clearGapSweep(layerId)
        // 视口瓦片全部到达：立即 bump dataVersion 触发渲染，
        // 不等 220ms coalesce 窗口，减少缩放后到首次渲染的延迟
        if (dataVersionBumpTimer !== null) {
          clearTimeout(dataVersionBumpTimer)
          dataVersionBumpTimer = null
        }
        dataVersion.value += 1
        perfIncBump()
      } else {
        scheduleDataVersionBump()
      }

      if (isPerfEnabled()) {
        const cachedTiles: MergedWeatherTile[] = Array.from(finalState.tiles.entries()).map(
          ([k, entry]) => {
            const zMatch = /:z(\d+):/.exec(k)
            const xMatch = /:x(\d+):/.exec(k)
            const yMatch = /:y(\d+):/.exec(k)
            return {
              layerId,
              z: Number(zMatch?.[1] ?? key.z),
              x: Number(xMatch?.[1] ?? key.x),
              y: Number(yMatch?.[1] ?? key.y),
              hour: key.hour,
              geojson: entry.geojson,
            }
          },
        )
        const stats = buildMergeStats(cachedTiles)
        debugLog(
          'submitTile done',
          layerId,
          `z=${key.z} x=${key.x} y=${key.y}`,
          formatMergeStats(layerId, stats),
        )
      }

      expandNeighbors(finalState, key, request.generation)
      recordWeatherTileSuccess()
    } catch (err) {
      if (isAbortError(err)) {
        debugLog('submitTile aborted', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
      } else if ((err as Error)?.message?.includes('timeout')) {
        // 前端 abort 超时：后端可能仍在生成；退避重试，耗尽后再软重拉
        const retryCount = (request.retryTimeoutCount ?? 0) + 1
        request.retryTimeoutCount = retryCount
        if (retryCount <= MAX_TIMEOUT_RETRIES) {
          if (retryCount === 1) recordWeatherTileFailure()
          const backoff = BACKOFF_TIMEOUT_MS * Math.pow(2, retryCount - 1)
          debugLog(
            'submitTile timeout retry',
            layerId,
            `z=${key.z} x=${key.x} y=${key.y}`,
            `retry=${retryCount}/${MAX_TIMEOUT_RETRIES}`,
            `backoff=${backoff}ms`,
          )
          activeFetchCount = Math.max(0, activeFetchCount - 1)
          request.dispatched = false
          request.retryAfter = Date.now() + backoff
          const retryTimer = setTimeout(() => {
            pendingRetryTimers.delete(retryTimer)
            drainQueue()
          }, backoff + 100)
          pendingRetryTimers.add(retryTimer)
          return
        }
        recordWeatherTileFailure()
        debugLog(
          'submitTile timeout exhausted',
          layerId,
          `z=${key.z} x=${key.x} y=${key.y}`,
          `retries=${retryCount}`,
        )
        // 视口已有内容时不贴死错误横幅，避免「一直超时」误报
        const liveAfterTimeout = layerStates.get(layerId)
        if (!liveAfterTimeout || viewportCachedCount(liveAfterTimeout) === 0) {
          setLayerError(layerId, 'timeout', '天气瓦片请求超时，上游可能限流，稍后自动重试')
        }
        dropUndispatchedPrefetchWhenStressed()
        scheduleSoftRequeue(layerId, key, request.generation)
        ensureGapSweep(layerId)
      } else if (String(err).includes('429') || (err as Error).message?.includes('429')) {
        const retryCount = (request.retry429Count ?? 0) + 1
        request.retry429Count = retryCount
        if (retryCount <= MAX_429_RETRIES) {
          recordWeatherTileFailure()
          // 指数退避：base * 2^(retry-1)，避免多瓦片同时重试再次触发 429
          const backoff = BACKOFF_429_MS * Math.pow(2, retryCount - 1)
          debugLog(
            'submitTile 429 retry',
            layerId,
            `z=${key.z} x=${key.x} y=${key.y}`,
            `retry=${retryCount}/${MAX_429_RETRIES}`,
            `backoff=${backoff}ms`,
          )
          activeFetchCount = Math.max(0, activeFetchCount - 1)
          request.dispatched = false
          request.retryAfter = Date.now() + backoff
          const retryTimer = setTimeout(() => {
            pendingRetryTimers.delete(retryTimer)
            drainQueue()
          }, backoff + 100)
          pendingRetryTimers.add(retryTimer)
          return
        }
        debugLog(
          'submitTile 429 exhausted',
          layerId,
          `z=${key.z} x=${key.x} y=${key.y}`,
          `retries=${retryCount}`,
        )
        setLayerError(layerId, 'rate-limited', '天气 API 请求频率超限，请稍后重试')
        scheduleSoftRequeue(layerId, key, request.generation)
        ensureGapSweep(layerId)
      } else if (
        String(err).includes('503') ||
        String(err).includes('502') ||
        String(err).includes('504') ||
        (err as Error).message?.includes('503') ||
        (err as Error).message?.includes('502') ||
        (err as Error).message?.includes('504')
      ) {
        const retryCount = (request.retry503Count ?? 0) + 1
        request.retry503Count = retryCount
        if (retryCount <= MAX_503_RETRIES) {
          recordWeatherTileFailure()
          const backoff = BACKOFF_503_MS * Math.pow(2, retryCount - 1)
          debugLog(
            'submitTile gateway retry',
            layerId,
            `z=${key.z} x=${key.x} y=${key.y}`,
            `retry=${retryCount}/${MAX_503_RETRIES}`,
            `backoff=${backoff}ms`,
          )
          activeFetchCount = Math.max(0, activeFetchCount - 1)
          request.dispatched = false
          request.retryAfter = Date.now() + backoff
          const retryTimer = setTimeout(() => {
            pendingRetryTimers.delete(retryTimer)
            drainQueue()
          }, backoff + 100)
          pendingRetryTimers.add(retryTimer)
          return
        }
        debugLog(
          'submitTile gateway exhausted',
          layerId,
          `z=${key.z} x=${key.x} y=${key.y}`,
          `retries=${retryCount}`,
        )
        const liveAfter503 = layerStates.get(layerId)
        if (!liveAfter503 || viewportCachedCount(liveAfter503) === 0) {
          setLayerError(layerId, 'circuit-open', '天气服务暂时不可达（网关/断路器），请稍后重试')
        }
        scheduleSoftRequeue(layerId, key, request.generation)
        ensureGapSweep(layerId)
      } else {
        recordWeatherTileFailure()
        const classified = classifyTileError(err)
        useLogStore().logOperation(
          'weather-tile-error',
          '天气瓦片请求失败',
          `layer=${layerId} z=${key.z} x=${key.x} y=${key.y} type=${classified.type} err=${String(err)}`,
          'error',
        )
        setLayerError(layerId, classified.type, classified.message)
        if (classified.type === 'data-empty') {
          // 422 = 当前 model/provider 缺该变量（图层级）：标记短路并清掉同图层
          // 其余 pending，避免每个瓦片都白打一次上游。重新激活图层可重试。
          const liveState = layerStates.get(layerId)
          if (liveState) {
            liveState.dataEmptyScope = `${liveState.model}|${liveState.provider}`
            for (const pendingReq of liveState.pending.values()) {
              cancelPendingRequest(pendingReq)
            }
            liveState.pending.clear()
            activityVersion.value += 1
          }
          clearGapSweep(layerId)
        } else {
          scheduleSoftRequeue(layerId, key, request.generation)
        }
        ensureGapSweep(layerId)
      }
    } finally {
      // 429/503/timeout 重试时不清理 pending（dispatched=false 表示已重新入队等待重试）
      if (request.dispatched !== false) {
        const currentState = layerStates.get(layerId)
        currentState?.pending.delete(cacheKey)
        activeFetchCount = Math.max(0, activeFetchCount - 1)
        activityVersion.value += 1
        drainQueue()
      }
    }
  }

  /** 限流/断路耗尽后，过一会再把仍缺的瓦片拉回队列（避免永久空洞） */
  function scheduleSoftRequeue(layerId: string, key: TileKey, generation: number) {
    const state = layerStates.get(layerId)
    const countKey = state
      ? tileCoordsToKey(
          { z: key.z, x: key.x, y: key.y },
          layerId,
          key.hour,
          state.model,
          state.provider,
        )
      : `${layerId}:z${key.z}:x${key.x}:y${key.y}:h${key.hour}`
    const prev = softRequeueCounts.get(countKey) ?? 0
    if (prev >= MAX_SOFT_REQUEUES) {
      debugLog(
        'softRequeue skipped (cap)',
        layerId,
        `z=${key.z} x=${key.x} y=${key.y}`,
        `h=${key.hour}`,
        `count=${prev}`,
      )
      return
    }
    softRequeueCounts.set(countKey, prev + 1)
    const retryTimer = setTimeout(() => {
      pendingRetryTimers.delete(retryTimer)
      const current = layerStates.get(layerId)
      if (!current || !current.visible || current.generation !== generation) return
      const tile = { z: key.z, x: key.x, y: key.y }
      const cacheKey = tileCoordsToKey(tile, layerId, key.hour, current.model, current.provider)
      if (current.tiles.has(cacheKey) || current.pending.has(cacheKey)) return
      debugLog(
        'softRequeue',
        layerId,
        `z=${key.z} x=${key.x} y=${key.y}`,
        `h=${key.hour}`,
        `attempt=${prev + 1}`,
      )
      // 邻小时失败重试保持低优先级，避免挤占标题栏「运行中」计数
      const priority = key.hour === current.hour ? 0 : ADJACENT_HOUR_PRIORITY
      if (enqueueIfMissing(current, tile, priority, generation, key.hour)) {
        activityVersion.value += 1
        drainQueue()
      }
    }, SOFT_REQUEUE_MS)
    pendingRetryTimers.add(retryTimer)
  }

  function expandNeighbors(state: LayerState, key: TileKey, generation: number): void {
    const n = 2 ** key.z
    const deltas = [
      [-1, -1],
      [0, -1],
      [1, -1],
      [-1, 0],
      [1, 0],
      [-1, 1],
      [0, 1],
      [1, 1],
    ]

    // 只预取当前视口外扩 1 圈内的邻居，避免无限外扩和移动后旧预取浪费
    const allowedKeys = new Set<string>(
      [...state.viewportTiles, ...state.prefetchRing].map((t) =>
        tileCoordsToKey(t, state.layerId, state.hour, state.model, state.provider),
      ),
    )

    let enqueuedAny = false
    for (const [dx, dy] of deltas) {
      const nx = (((key.x + dx) % n) + n) % n
      const ny = key.y + dy
      if (ny < 0 || ny >= n) continue
      const neighborKey = tileCoordsToKey(
        { z: key.z, x: nx, y: ny },
        state.layerId,
        state.hour,
        state.model,
        state.provider,
      )
      if (!allowedKeys.has(neighborKey)) continue
      if (enqueueIfMissing(state, { z: key.z, x: nx, y: ny }, 1, generation)) {
        enqueuedAny = true
      }
    }
    if (enqueuedAny) {
      activityVersion.value += 1
    }
    if (state.pending.size > 0) {
      drainQueue()
    }
  }

  function trimLayerCache(state: LayerState): void {
    // Zoom-out 过渡期保留更多跨级瓦片（z±2），作为 underlay 填洞
    const inTransition =
      state.lastZoomChangedAt > 0 && Date.now() - state.lastZoomChangedAt < ZOOM_OUT_TRANSITION_MS
    trimWeatherLayerTileCache(state, tileCoordsToKey, undefined, inTransition ? 2 : 1)
  }

  function getMergedGeojsonForViewport(layerId: string): WindGeoJSON | null {
    // P1-1: 合并逻辑已拆至 weather-tile-merge.ts
    return getMergedGeojsonForViewportImpl(layerId, layerStates.get(layerId), {
      mergeCache,
      debugLog,
      countViewportMissing,
    })
  }

  function getDataVersion(): number {
    return dataVersion.value
  }

  /** 当前请求视口 bounds（瓦片合并的目标范围）；供 overlay 渲染灰底占位 */
  function getViewportBounds(layerId: string): LngLatBounds | null {
    const state = layerStates.get(layerId)
    if (!state || !state.visible) return null
    if (state.bbox) return state.bbox
    const clampedZoom = Math.max(0, Math.min(12, Math.round(state.zoom)))
    return boundsFromCenter(state.center, clampedZoom)
  }

  function getStats(layerId: string): LayerTileStats {
    const state = layerStates.get(layerId)
    if (!state) return { pending: 0, cached: 0, visible: 0 }
    const clampedZoom = Math.max(0, Math.min(12, Math.round(state.zoom)))
    const visibleCount = state.bbox ? tilesInBounds(state.bbox, clampedZoom, 0).length : 0
    return {
      pending: state.pending.size,
      cached: state.tiles.size,
      visible: visibleCount,
    }
  }

  /** 获取图层当前的加载/错误状态，供 UI 展示反馈 */
  function getLayerStatus(layerId: string): WeatherTileLayerStatus {
    const state = layerStates.get(layerId)
    if (!state || !state.visible) {
      return {
        active: false,
        cachedInViewport: 0,
        viewportTotal: 0,
        missingInViewport: 0,
        pending: 0,
        gapSweepActive: false,
        errorType: null,
        errorMessage: null,
      }
    }
    const viewportTotal = state.viewportTiles.length
    let cachedInViewport = 0
    for (const tile of state.viewportTiles) {
      const tileKey = tileCoordsToKey(tile, layerId, state.hour, state.model, state.provider)
      if (state.tiles.has(tileKey)) cachedInViewport += 1
    }
    // 与 countViewportMissing / gap-sweep 对齐：data-empty 层不再报视口缺口
    const missingInViewport = countViewportMissing(state)
    return {
      active: true,
      cachedInViewport,
      viewportTotal,
      missingInViewport,
      pending: state.pending.size,
      gapSweepActive: gapSweepTimers.has(layerId),
      errorType: state.lastErrorType,
      errorMessage: state.lastErrorMessage,
    }
  }

  /**
   * 标题栏「运行中」只计视口高优先级且已在队列/在途的瓦片（priority=0）。
   * 仅 gap-sweep 等待（pending=0）时不计，避免假「运行中」。
   */
  function getGlobalActiveTileCount(): number {
    let count = 0
    for (const state of layerStates.values()) {
      if (!state.visible) continue
      for (const request of state.pending.values()) {
        if (request.priority === 0) count += 1
      }
    }
    return count
  }

  /**
   * 将瓦片层状态映射为与 job 同构的六态贡献（不写入 JobLayerItem）。
   * 无数据仅认本层 errorType === 'data-empty'（不因全局 modelEmpty 连坐其它层）。
   * sync 进行中：本层 data-empty → retry_pending，否则 → failed。
   */
  function deriveWeatherWorkflowContribution(options?: {
    syncInProgress?: boolean
  }): WeatherWorkflowContribution {
    const syncInProgress = !!options?.syncInProgress
    const now = Date.now()
    const items: WeatherWorkflowContributionItem[] = []
    const counts = {
      running: 0,
      queued: 0,
      retryPending: 0,
      failed: 0,
      cancelled: 0,
      succeeded: 0,
    }

    for (const state of layerStates.values()) {
      if (!state.visible) continue
      const statusInfo = getLayerStatus(state.layerId)
      let running = 0
      let queued = 0
      let retrying = 0
      for (const request of state.pending.values()) {
        if (request.priority !== 0) continue
        if (typeof request.retryAfter === 'number' && request.retryAfter > now) {
          retrying += 1
        } else if (request.dispatched) {
          running += 1
        } else {
          // 未派发且无退避：等待并发槽位，属于「排队」而非「重试」
          queued += 1
        }
      }

      let mapped: WeatherWorkflowMappedStatus | null = null
      let message = ''

      const emptySignal = statusInfo.errorType === 'data-empty'

      if (running > 0) {
        mapped = 'running'
        message = `加载瓦片 ${statusInfo.cachedInViewport}/${statusInfo.viewportTotal}`
      } else if (queued > 0) {
        // 有瓦片在队列中等待并发槽位，显示为「运行中」（用户视角正在加载）
        mapped = 'running'
        message = `加载瓦片 ${statusInfo.cachedInViewport}/${statusInfo.viewportTotal}，排队 ${queued}`
      } else if (retrying > 0 || (statusInfo.gapSweepActive && statusInfo.missingInViewport > 0)) {
        mapped = 'retry_pending'
        message = statusInfo.gapSweepActive ? '视口补洞等待重试' : '瓦片退避等待重试'
      } else if (emptySignal) {
        if (syncInProgress) {
          mapped = 'retry_pending'
          message = '本地模型无数据，同步进行中…'
        } else {
          mapped = 'failed'
          message = statusInfo.errorMessage || '本地模型无数据，请同步 Open-Meteo'
        }
      } else if (
        statusInfo.errorType &&
        statusInfo.missingInViewport > 0 &&
        !statusInfo.gapSweepActive
      ) {
        mapped = 'failed'
        message = statusInfo.errorMessage || '天气瓦片加载失败'
      } else if (statusInfo.viewportTotal > 0 && statusInfo.missingInViewport === 0) {
        // 视口瓦片已全部缓存 → 计入「已完成」，与工具栏/状态面板六态对齐
        mapped = 'succeeded'
        message = `已完成瓦片 ${statusInfo.cachedInViewport}/${statusInfo.viewportTotal}`
      } else if (statusInfo.pending > 0 && statusInfo.missingInViewport > 0) {
        // 仍有缺口且有在途请求（含预取）：显示为运行中，避免状态栏缺失该图层
        mapped = 'running'
        message = `加载瓦片 ${statusInfo.cachedInViewport}/${statusInfo.viewportTotal}`
      }

      if (!mapped) continue
      items.push({
        catalogId: state.layerId,
        status: mapped,
        message,
        pending: statusInfo.pending,
        missingInViewport: statusInfo.missingInViewport,
        cachedInViewport: statusInfo.cachedInViewport,
        viewportTotal: statusInfo.viewportTotal,
        errorType: statusInfo.errorType,
      })
      if (mapped === 'running') counts.running += 1
      else if (mapped === 'retry_pending') counts.retryPending += 1
      else if (mapped === 'failed') counts.failed += 1
      else if (mapped === 'succeeded') counts.succeeded += 1
    }

    return { ...counts, items }
  }

  /** 清 soft-requeue 计数并强制补洞重试 */
  function retryLayerTiles(layerId: string): void {
    const state = layerStates.get(layerId)
    if (!state) return
    for (const key of softRequeueCounts.keys()) {
      if (key.startsWith(`${layerId}:`)) softRequeueCounts.delete(key)
    }
    clearLayerError(layerId)
    // 手动重试须解除 422 短路，否则 enqueueIfMissing 仍会跳过
    state.dataEmptyScope = null
    state.generation += 1
    // 清空视口快照，避免 setViewport 因集合未变 noop 而不重新入队
    state.viewportTiles = []
    state.prefetchRing = []
    // 重新以当前视口调度
    setViewport(
      layerId,
      state.center,
      state.zoom,
      state.hour,
      state.model,
      state.bbox ?? undefined,
      state.provider,
    )
    ensureGapSweep(layerId)
    statusVersion.value += 1
    activityVersion.value += 1
  }

  /**
   * 清空全部图层瓦片/合并缓存（保留可见状态与视口）。
   * 用于设置页改 TTL、清理数据缓存后与后端真相对齐。
   */
  function invalidateAllTileCaches(): void {
    for (const state of layerStates.values()) {
      for (const request of state.pending.values()) {
        cancelPendingRequest(request)
      }
      state.pending.clear()
      state.tiles.clear()
      state.lastMergedGeojson = null
      state.lastMergedFeatureCount = 0
      state.generation += 1
      // 清空视口快照，避免随后 setViewport 走 noop 早退而不重新入队
      state.viewportTiles = []
      state.prefetchRing = []
    }
    mergeCache.clear()
    softRequeueCounts.clear()
    for (const layerId of Array.from(gapSweepTimers.keys())) {
      clearGapSweep(layerId)
    }
    dataVersion.value += 1
    statusVersion.value += 1
    activityVersion.value += 1
    // 对仍可见图层按当前视口重新调度
    for (const [layerId, state] of layerStates.entries()) {
      if (!state.visible) continue
      setViewport(
        layerId,
        state.center,
        state.mapZoom || state.zoom,
        state.hour,
        state.model,
        state.bbox ?? undefined,
        state.provider,
      )
    }
    debugLog('invalidateAllTileCaches')
  }

  /** 获取当前自适应并发信息，供 UI 监控显示 */
  function getConcurrencyInfo(): { active: number; max: number } {
    return { active: activeFetchCount, max: getWeatherTileMaxConcurrent() }
  }

  return {
    dataVersion,
    statusVersion,
    activityVersion,
    setLayerActive,
    clearLayer,
    setViewport,
    getMergedGeojsonForViewport,
    getViewportBounds,
    getDataVersion,
    getStats,
    getLayerStatus,
    getGlobalActiveTileCount,
    deriveWeatherWorkflowContribution,
    retryLayerTiles,
    invalidateAllTileCaches,
    getConcurrencyInfo,
    /** 单测：立刻跑一轮视口补洞（绕过 GAP_SWEEP_MS 等待） */
    __testRunGapSweepNow: runGapSweep,
  }
})
