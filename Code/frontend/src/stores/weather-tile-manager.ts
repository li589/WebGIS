/**
 * 天气瓦片调度管理器。
 *
 * 职责：
 * - 按图层维护瓦片缓存（fetchedAt/lastAccess + TTL SWR）、视口、世代号。
 * - 全局并发槽位（上限 4），与后端 WeatherTileService semaphore 对齐。
 * - 图层内优先级：0=视口@H → 1=邻域 depth3/父级@H → 2=子级 z+1@H → 3=视口@H±1。
 * - 移动/缩放时 generation++，丢弃过期结果并取消不在目标集合内的请求。
 * - 每个瓦片通过 GET /weather/tiles 拉取 GeoJSON（服务端缓存/生成）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { useLogStore } from './log'
import { useSettingsStore } from './settings'
import {
  buildTileKey,
  fetchWeatherTile,
  tileToLngLatBounds,
  tilesInBounds,
  type LngLatBounds,
  type WeatherTileCoords,
} from '../services/weather-tile-api'
import {
  buildMergeStats,
  filterGeojsonInsideTileBounds,
  filterGeojsonOutsideCoverage,
  formatMergeStats,
  mergeWeatherTiles,
  type MergedWeatherTile,
} from '../services/weather-tile-utils'
import type { WindGeoJSON } from '../components/map/types'
import { isPerfEnabled, perfIncBump, perfMark, perfNoteViewportFill } from '../utils/perf-probe'
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

/** 视口外扩预取圈数：同级邻居提前缓存，减少平移空洞 */
const PREFETCH_NEIGHBOR_DEPTH = 3
/** 邻小时预取优先级（仅 viewport，不扩环） */
const ADJACENT_HOUR_PRIORITY = 3
/** 预报 hour 合法范围（与后端 Query ge=0,le=47 对齐） */
const HOUR_MIN = 0
const HOUR_MAX = 47
/** 默认与后端 weather_cache_ttl_seconds 一致 */
const DEFAULT_TILE_TTL_MS = 3600_000

/** 单瓦片缓存条目：SWR 用 fetchedAt，LRU trim 用 lastAccess */
export interface CachedTileEntry {
  geojson: WindGeoJSON
  fetchedAt: number
  lastAccess: number
}
/** 单视口瓦片上限；超出则降 tile z，避免亚洲–太平洋宽视野瞬间打爆上游 */
const MAX_VIEWPORT_TILES = 36
/** dataVersion 短窗合并，避免每到一块瓦片就全量重算 */
const DATA_VERSION_COALESCE_MS = 220
/** pending 过高时暂停 z+1 child prefetch */
const CHILD_PREFETCH_PENDING_STRESS = 6
const BACKOFF_429_MS = 5000
/** 429 退避后重试的最大次数，避免无限重试 */
const MAX_429_RETRIES = 3
/** 503（断路器/服务不可用）退避时间 */
const BACKOFF_503_MS = 8000
/** 503 重试最大次数 */
const MAX_503_RETRIES = 3
/** 前端 abort 超时后的退避（后端可能仍在生成，稍后重试可命中缓存） */
const BACKOFF_TIMEOUT_MS = 4000
/** 超时重试最大次数 */
const MAX_TIMEOUT_RETRIES = 2
/** 耗尽重试后的软重拉间隔（给断路器恢复时间，避免立刻再撞 503） */
const SOFT_REQUEUE_MS = 15_000
/** 同一瓦片软重拉上限，防止断路器打开时无限「运行中」 */
const MAX_SOFT_REQUEUES = 3
/** 视口缺口补洞扫描间隔（秒级，商业观感：缩放后尽快填洞） */
const GAP_SWEEP_MS = 2_500
/** 限流/断路压力下的补洞间隔 */
const GAP_SWEEP_STRESSED_MS = 8_000
/** Zoom-out 过渡期补洞间隔（更快填洞） */
const GAP_SWEEP_ZOOM_CHANGE_MS = 1_000
/** Zoom-out 过渡期 dataVersion 合并窗口（更快触发渲染） */
const DATA_VERSION_ZOOMOUT_COALESCE_MS = 100
/** Zoom-out 过渡期时长（ms）：在此期间加速补洞/放宽缓存/缩短合并 */
const ZOOM_OUT_TRANSITION_MS = 3_000

/** 默认气象模型 bootstrap；正式值由天气引擎配置 / 后端 default_model 覆盖。 */
export const DEFAULT_WEATHER_MODEL = 'ecmwf_ifs025'

/**
 * 模型 × 图层 结构性不支持清单：变量在该模型中不存在，数据同步也补不齐
 * （如 ECMWF IFS 不提供 visibility）。与后端 WEATHER_LAYER_SPECS 语义保持一致。
 * 命中时 setViewport 直接短路：不发瓦片请求，按 data-empty 提示。
 */
const UNSUPPORTED_LAYER_MODELS: Record<string, readonly string[]> = {
  visibility: ['ecmwf_ifs025'],
}

/** 图层变量在当前模型下是否结构性不可用（与数据同步状态无关） */
export function isWeatherLayerUnsupportedByModel(layerId: string, model: string): boolean {
  const models = UNSUPPORTED_LAYER_MODELS[layerId]
  return !!models && models.includes(model)
}

interface TileKey {
  layerId: string
  z: number
  x: number
  y: number
  hour: number
}

interface TileRequest {
  key: TileKey
  layerId: string
  priority: number
  generation: number
  sequence: number
  controller: AbortController
  /** 是否已被 drainQueue 取出并进入 submitTile；用于取消时区分是否占用并发槽位。 */
  dispatched?: boolean
  /** 429 重试计数 */
  retry429Count?: number
  /** 503 重试计数 */
  retry503Count?: number
  /** 前端超时重试计数 */
  retryTimeoutCount?: number
  /** 该瓦片最早可重试的时间戳（ms）。drainQueue/pickNextRequest 会跳过未到期的瓦片，
   *  确保单个瓦片的退避不被其他 drainQueue 调用绕过。 */
  retryAfter?: number
}

interface LayerState {
  layerId: string
  generation: number
  visible: boolean
  center: { lng: number; lat: number }
  /** 预算后的瓦片 zoom（入队 / merge 用） */
  zoom: number
  /** 地图原始 zoom；用于判断「仅缩放未改瓦片集合」时仍需通知 overlay 重投影 */
  mapZoom: number
  hour: number
  model: string
  /** Weather provider preference (auto | provider_id); part of tile cache key */
  provider: string
  bbox: LngLatBounds | null
  viewportTiles: WeatherTileCoords[]
  prefetchRing: WeatherTileCoords[]
  tiles: Map<string, CachedTileEntry>
  pending: Map<string, TileRequest>
  /** 最近一次成功合并的 GeoJSON；视口换小时/缩放时暂无可匹配瓦片则沿用，避免闪空 */
  lastMergedGeojson: WindGeoJSON | null
  /** 上一帧合并的 feature 数，用于检测「平移后暂时变稀」并沿用旧帧 */
  lastMergedFeatureCount: number
  /** 最近一次错误类型（null = 无错误）。UI 通过 statusVersion 触发响应式更新。 */
  lastErrorType: WeatherTileErrorType | null
  /** 错误信息（供 UI 展示） */
  lastErrorMessage: string | null
  /**
   * 「无数据」短路标记：记录最近一次 422（主变量全 null）时的 `${model}|${provider}`。
   * 命中后该图层在当前 model/provider 下不再发任何瓦片请求（422 表示变量缺失，
   * 是图层级状态而非单瓦片问题），避免 gap sweep / soft requeue 构成无限重试。
   * model/provider 变化后 scope 自动失配、恢复请求；图层重新激活时显式清除。
   */
  dataEmptyScope: string | null
  /** 最近一次 zoom 变化的时间戳（ms）；zoom-out 过渡期内加速补洞/放宽缓存/缩短合并窗口 */
  lastZoomChangedAt: number
}

export interface LayerTileStats {
  pending: number
  cached: number
  visible: number
}

/** 天气瓦片图层的运行时状态，供 UI 显示加载/错误反馈 */
export type WeatherTileErrorType =
  'circuit-open' | 'rate-limited' | 'workflow-failed' | 'timeout' | 'data-empty' | 'unknown'

export type WeatherWorkflowMappedStatus =
  'running' | 'queued' | 'retry_pending' | 'failed' | 'cancelled' | 'succeeded'

export interface WeatherWorkflowContributionItem {
  catalogId: string
  status: WeatherWorkflowMappedStatus
  message: string
  pending: number
  missingInViewport: number
  errorType: WeatherTileErrorType | null
}

export interface WeatherWorkflowContribution {
  running: number
  queued: number
  retryPending: number
  failed: number
  cancelled: number
  succeeded: number
  items: WeatherWorkflowContributionItem[]
}

export interface WeatherTileLayerStatus {
  /** 图层是否可见且需要瓦片 */
  active: boolean
  /** 视口内已缓存的瓦片数 */
  cachedInViewport: number
  /** 视口内瓦片总数 */
  viewportTotal: number
  /** 视口内尚未缓存的瓦片数 */
  missingInViewport: number
  /** 仍在加载的瓦片数（含退避中；工具栏「运行中」≈ priority=0 pending） */
  pending: number
  /** 是否有图层级视口补洞定时器在跑 */
  gapSweepActive: boolean
  /** 最近一次错误类型（null = 无错误） */
  errorType: WeatherTileErrorType | null
  /** 错误信息（供 UI 展示） */
  errorMessage: string | null
}

let globalSequence = 0
let activeFetchCount = 0
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
  for (const timer of pendingRetryTimers) clearTimeout(timer)
  pendingRetryTimers.clear()
  softRequeueCounts.clear()
  for (const timer of gapSweepTimers.values()) clearTimeout(timer)
  gapSweepTimers.clear()
  resetWeatherTileConcurrencyForTests()
}

function parseTileCoordsFromCacheKey(cacheKey: string): WeatherTileCoords | null {
  const zMatch = /:z(\d+):/.exec(cacheKey)
  const xMatch = /:x(\d+):/.exec(cacheKey)
  const yMatch = /:y(\d+):/.exec(cacheKey)
  if (!zMatch || !xMatch || !yMatch) return null
  return {
    z: Number(zMatch[1]),
    x: Number(xMatch[1]),
    y: Number(yMatch[1]),
  }
}

/** 轴对齐 bbox 是否与视口相交（视口 east 可 >180） */
function tileBoundsOverlapViewport(tile: LngLatBounds, viewport: LngLatBounds): boolean {
  const tw = tile.west
  const te = tile.east
  const ts = tile.south
  const tn = tile.north
  if (tn < viewport.south || ts > viewport.north) return false
  // 视口可能跨日界线（east>180）：把瓦片 lon 卷入视口框再比
  let x0 = tw
  let x1 = te
  if (viewport.east > 180 || viewport.east < viewport.west) {
    while (x0 < viewport.west) {
      x0 += 360
      x1 += 360
    }
    while (x0 >= viewport.west + 360) {
      x0 -= 360
      x1 -= 360
    }
  }
  return x1 >= viewport.west && x0 <= viewport.east
}

function debugLog(module: string, ...args: unknown[]) {
  console.log(`[${performance.now().toFixed(1)}ms] [WeatherTileManager:${module}]`, ...args)
}
setWeatherTileConcurrencyDebugLog(debugLog)

function classifyTileError(err: unknown): { type: WeatherTileErrorType; message: string } {
  const raw = String((err as Error)?.message ?? err ?? '天气瓦片加载失败')
  if (raw.includes('timeout')) {
    return { type: 'timeout', message: '天气瓦片请求超时，上游可能限流，稍后自动重试' }
  }
  if (raw.includes('429')) {
    return { type: 'rate-limited', message: '天气 API 请求频率超限，请稍后重试' }
  }
  if (
    raw.includes('422') ||
    /all-null|empty payload|empty grid|model_empty|no usable data|无数据/i.test(raw)
  ) {
    return {
      type: 'data-empty',
      message: '本地模型无数据，请同步 Open-Meteo',
    }
  }
  if (
    raw.includes('503') ||
    raw.includes('502') ||
    raw.includes('504') ||
    /Bad gateway/i.test(raw)
  ) {
    return {
      type: 'circuit-open',
      message: '天气服务暂时不可达（网关/断路器），请稍后重试',
    }
  }
  // 兜底：绝不把 HTML 错误页原文推到地图横幅
  return { type: 'unknown', message: sanitizeUiErrorMessage(raw) }
}

/** UI / 日志用：去掉 HTML 并截断，避免 Cloudflare 502 整页污染界面 */
function sanitizeUiErrorMessage(message: string, maxLen = 180): string {
  if (
    /<!DOCTYPE\s+html|<html[\s>]|<head[\s>]|<body[\s>]/i.test(message) ||
    message.includes('<!DOCTYPE')
  ) {
    const statusMatch = /failed:\s*(\d{3})/.exec(message)
    const status = statusMatch?.[1] ?? '错误'
    return `天气瓦片请求失败（HTTP ${status}），服务暂时不可达`
  }
  const oneLine = message.replace(/\s+/g, ' ').trim()
  return oneLine.length > maxLen ? `${oneLine.slice(0, maxLen)}…` : oneLine
}

function tileCoordsToKey(
  coords: WeatherTileCoords,
  layerId: string,
  hour: number,
  model: string,
  provider = 'auto',
): string {
  return buildTileKey(layerId, coords.z, coords.x, coords.y, hour, model, provider)
}

function getWeatherTileTtlMs(): number {
  try {
    const ttlSec = useSettingsStore().weatherConfig?.cache_ttl_seconds
    if (typeof ttlSec === 'number' && Number.isFinite(ttlSec) && ttlSec > 0) {
      return Math.floor(ttlSec * 1000)
    }
  } catch {
    // Pinia 未就绪（单测早期）时回退默认
  }
  return DEFAULT_TILE_TTL_MS
}

function isTileFresh(entry: CachedTileEntry, now = Date.now()): boolean {
  return now - entry.fetchedAt < getWeatherTileTtlMs()
}

function touchTileEntry(entry: CachedTileEntry, now = Date.now()): WindGeoJSON {
  entry.lastAccess = now
  return entry.geojson
}

function makeTileEntry(geojson: WindGeoJSON, now = Date.now()): CachedTileEntry {
  return { geojson, fetchedAt: now, lastAccess: now }
}

/**
 * 取消单个 pending 请求。
 *
 * 注意：不要在这里递减 activeFetchCount。
 * - 若请求尚未被 drainQueue 调度（dispatched=false），它从未占用槽位。
 * - 若请求已被调度（dispatched=true），submitTile 的 finally 会统一释放槽位。
 * 因此调用方只需 abort controller。
 */
function cancelPendingRequest(request: TileRequest): void {
  request.controller.abort()
}

function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}

export const useWeatherTileManager = defineStore('weatherTileManager', () => {
  // 全局数据版本号：瓦片缓存变化时递增，供组件 watch 触发重渲染
  const dataVersion = ref(0)
  // 状态版本号：错误/加载状态变化时递增，供 UI watch 触发响应式更新
  const statusVersion = ref(0)
  // 活跃度版本号：pending 数量变化时递增，供标题栏工作流状态按钮响应式更新
  const activityVersion = ref(0)
  // 图层状态：使用普通 Map，依赖 dataVersion/statusVersion 触发响应式更新
  const layerStates = new Map<string, LayerState>()
  const MERGE_CACHE_MAX = 8
  const mergeCache = new Map<string, WindGeoJSON | null>()
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

  function buildMergeCacheKey(
    layerId: string,
    state: LayerState,
    clampedZoom: number,
    bounds: LngLatBounds,
    coverageSig: string,
  ): string {
    return `${layerId}:${state.generation}:${state.hour}:${clampedZoom}:${bounds.west.toFixed(3)},${bounds.south.toFixed(3)},${bounds.east.toFixed(3)},${bounds.north.toFixed(3)}:c=${coverageSig}`
  }

  function rememberMergeCache(key: string, value: WindGeoJSON | null): WindGeoJSON | null {
    mergeCache.set(key, value)
    if (mergeCache.size > MERGE_CACHE_MAX) {
      const firstKey = mergeCache.keys().next().value
      if (firstKey !== undefined) {
        mergeCache.delete(firstKey)
      }
    }
    return value
  }

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
        model: DEFAULT_WEATHER_MODEL,
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
    // 仅清理当前图层的合并缓存，保留其他图层的缓存
    for (const key of Array.from(mergeCache.keys())) {
      if (key.startsWith(`${layerId}:`)) mergeCache.delete(key)
    }
    debugLog('clearLayer', layerId)
  }

  function bboxApproxEqual(a: LngLatBounds | null, b: LngLatBounds | null, eps = 1e-4): boolean {
    if (a === b) return true
    if (!a || !b) return false
    return (
      Math.abs(a.west - b.west) < eps &&
      Math.abs(a.south - b.south) < eps &&
      Math.abs(a.east - b.east) < eps &&
      Math.abs(a.north - b.north) < eps
    )
  }

  function tileKeySetEqual(a: WeatherTileCoords[], b: WeatherTileCoords[]): boolean {
    if (a.length !== b.length) return false
    const keys = new Set(a.map((t) => `${t.z}:${t.x}:${t.y}`))
    return b.every((t) => keys.has(`${t.z}:${t.x}:${t.y}`))
  }

  function resolveTileZoom(bounds: LngLatBounds, zoom: number): number {
    let z = Math.max(0, Math.min(12, Math.round(zoom)))
    while (z > 1 && tilesInBounds(bounds, z, 0).length > MAX_VIEWPORT_TILES) {
      z -= 1
    }
    return z
  }

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

    const resolvedModel = model || DEFAULT_WEATHER_MODEL
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
    const viewportTiles = tilesInBounds(bounds, clampedZoom, 0)
    const prefetchRing = tilesInBounds(bounds, clampedZoom, PREFETCH_NEIGHBOR_DEPTH).filter(
      (t) => !viewportTiles.some((vt) => vt.x === t.x && vt.y === t.y && vt.z === t.z),
    )
    // 父子 z 预取：换 zoom 时垫底/过渡，减少空洞与错分辨率闪断
    const parentPrefetch = clampedZoom > 0 ? tilesInBounds(bounds, clampedZoom - 1, 0) : []
    const childPrefetch =
      clampedZoom < 12
        ? tilesInBounds(bounds, clampedZoom + 1, 0).filter((t) => {
            // 仅预取覆盖视口中心附近的子瓦片，避免 4× 爆炸
            const midLat = Math.max(-85, Math.min(85, (bounds.south + bounds.north) / 2))
            const midLon = (bounds.west + bounds.east) / 2
            const cx = Math.floor(((midLon + 180) / 360) * 2 ** (clampedZoom + 1))
            const latRad = (midLat * Math.PI) / 180
            const cy = Math.floor(
              ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) *
                2 ** (clampedZoom + 1),
            )
            return Math.abs(t.x - cx) <= 1 && Math.abs(t.y - cy) <= 1
          })
        : []
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
        for (const key of Array.from(mergeCache.keys())) {
          if (key.startsWith(`${layerId}:`)) mergeCache.delete(key)
        }
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
    // Zoom-out 检测：缩小时提升并发并记录过渡期时间戳
    if (zoomChanged) {
      state.lastZoomChangedAt = Date.now()
      if (clampedZoom < state.zoom) {
        boostConcurrencyForZoomOut()
      }
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
    for (const key of Array.from(mergeCache.keys())) {
      if (key.startsWith(`${layerId}:`)) mergeCache.delete(key)
    }
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
    for (const adjHour of [hour - 1, hour + 1]) {
      if (adjHour < HOUR_MIN || adjHour > HOUR_MAX) continue
      for (const t of viewportTiles) {
        desiredKeys.add(tileCoordsToKey(t, layerId, adjHour, resolvedModel, resolvedProvider))
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
      for (const adjHour of [hour - 1, hour + 1]) {
        if (adjHour < HOUR_MIN || adjHour > HOUR_MAX) continue
        for (const tile of viewportTiles) {
          if (enqueueIfMissing(state, tile, ADJACENT_HOUR_PRIORITY, generation, adjHour)) {
            enqueuedAny = true
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

  function boundsFromCenter(center: { lng: number; lat: number }, z: number): LngLatBounds {
    // 无 bbox 时根据中心点和 zoom 估算一个近似视口（约 4 个瓦片）
    const n = 2 ** z
    const span = Math.max(1, Math.floor(n / 16))
    return {
      west: Math.max(-180, center.lng - span * (360 / n)),
      south: Math.max(-85, center.lat - span * (170 / n)),
      east: Math.min(180, center.lng + span * (360 / n)),
      north: Math.min(85, center.lat + span * (170 / n)),
    }
  }

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
    let best: TileRequest | null = null
    for (const state of layerStates.values()) {
      if (!state.visible) continue
      // 无数据图层不再派发请求
      if (isLayerDataEmpty(state)) continue
      for (const request of state.pending.values()) {
        // 已派发的请求仍在 pending 中（等待 submitTile finally 清理），避免重复调度
        if (request.dispatched) continue
        // 跳过仍在退避期内的瓦片，确保单瓦片重试延迟不被其他 drainQueue 调用绕过
        if (request.retryAfter && now < request.retryAfter) continue
        // 压力期只拉视口瓦片（priority=0）
        if (pausePrefetch && request.priority > 0) continue
        // pending 高时仅暂停 child z+1（priority===2），邻小时 priority=3 仍可在视口填满后调度
        if (pauseChild && request.priority === 2) continue
        if (!best) {
          best = request
          continue
        }
        if (request.priority < best.priority) {
          best = request
        } else if (request.priority === best.priority && request.sequence < best.sequence) {
          best = request
        }
      }
    }
    return best
  }

  async function submitTile(request: TileRequest): Promise<void> {
    const { key, layerId } = request
    const state = layerStates.get(layerId)
    const cacheKey = tileCoordsToKey(
      { z: key.z, x: key.x, y: key.y },
      layerId,
      key.hour,
      state?.model ?? DEFAULT_WEATHER_MODEL,
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
        console.error(
          `[WeatherTileManager] submitTile failed ${layerId} z=${key.z} x=${key.x} y=${key.y}:`,
          classified.type,
          err,
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
    const state = layerStates.get(layerId)
    if (!state || !state.visible) {
      debugLog('getMergedGeojson', layerId, 'state=', !!state, 'visible=', state?.visible)
      return null
    }

    // 直接使用 setViewport 已计算并存储的 state.zoom，避免重新计算导致 z 不一致
    const clampedZoom = state.zoom
    const bounds = state.bbox ?? boundsFromCenter(state.center, clampedZoom)
    const viewportTiles = tilesInBounds(bounds, clampedZoom, 0)
    const currentMatched: MergedWeatherTile[] = []
    const parentMatched: MergedWeatherTile[] = []
    const nAtZoom = 2 ** clampedZoom

    const cachedKeys = Array.from(state.tiles.keys()).map((k) => {
      const zMatch = /:z(\d+):/.exec(k)
      const xMatch = /:x(\d+):/.exec(k)
      const yMatch = /:y(\d+):/.exec(k)
      const hMatch = /:h(\d+)/.exec(k)
      return `z${zMatch?.[1]}:x${xMatch?.[1]}:y${yMatch?.[1]}:h${hMatch?.[1]}`
    })

    const hitKeys: string[] = []
    const hitTiles: WeatherTileCoords[] = []
    for (const tile of viewportTiles) {
      const key = tileCoordsToKey(tile, layerId, state.hour, state.model, state.provider)
      const entry = state.tiles.get(key)
      if (!entry) continue
      const raw = touchTileEntry(entry)
      const tileBounds = tileToLngLatBounds(tile.z, tile.x, tile.y)
      const geojson = filterGeojsonInsideTileBounds(raw, tileBounds, {
        includeEast: tile.x >= nAtZoom - 1,
        includeSouth: tile.y >= nAtZoom - 1,
      })
      if (!geojson.features?.length) continue
      // 仅有实际特征的瓦片才计入覆盖率，防止空瓦片膨胀 coverage 导致 underlay 被跳过
      hitKeys.push(`${tile.x},${tile.y}`)
      hitTiles.push(tile)
      currentMatched.push({
        layerId,
        z: tile.z,
        x: tile.x,
        y: tile.y,
        hour: state.hour,
        geojson,
      })
    }

    const coverageSig = `${hitKeys.length}/${viewportTiles.length}:${hitKeys.join('|')}`
    const cacheKey = buildMergeCacheKey(layerId, state, clampedZoom, bounds, coverageSig)
    const cached = mergeCache.get(cacheKey)
    if (cached !== undefined) {
      return cached
    }

    const currentCoverage = viewportTiles.length > 0 ? hitKeys.length / viewportTiles.length : 0

    // 父级 underlay：本级未齐时用 z-1 填洞
    const PARENT_UNDERLAY_COVERAGE_MAX = 0.92
    /** 缩放换 z 后沿用邻近级缓存（含更高 z 旧瓦片），避免「只剩缩放前那一块」 */
    const NEARBY_Z_UNDERLAY_RADIUS = 4
    const gapFillMatched: MergedWeatherTile[] = []
    if (clampedZoom > 0 && currentCoverage < PARENT_UNDERLAY_COVERAGE_MAX) {
      const coveredBounds = hitTiles.map((tile) => tileToLngLatBounds(tile.z, tile.x, tile.y))
      const parentZ = clampedZoom - 1
      const nParent = 2 ** parentZ
      const parentTiles = tilesInBounds(bounds, parentZ, 0)
      for (const tile of parentTiles) {
        const key = tileCoordsToKey(tile, layerId, state.hour, state.model, state.provider)
        const entry = state.tiles.get(key)
        if (!entry) continue
        const raw = touchTileEntry(entry)
        const tileBounds = tileToLngLatBounds(tile.z, tile.x, tile.y)
        const clippedToParent = filterGeojsonInsideTileBounds(raw, tileBounds, {
          includeEast: tile.x >= nParent - 1,
          includeSouth: tile.y >= nParent - 1,
        })
        const geojson =
          coveredBounds.length > 0
            ? filterGeojsonOutsideCoverage(clippedToParent, coveredBounds)
            : clippedToParent
        if (!geojson.features?.length) continue
        parentMatched.push({
          layerId,
          z: tile.z,
          x: tile.x,
          y: tile.y,
          hour: state.hour,
          geojson,
        })
        coveredBounds.push(tileBounds)
      }

      // 邻近 z 缓存垫底（尤其 zoom-out 后仍保留的更高 z 瓦片）
      const nearby: Array<{ z: number; x: number; y: number; raw: WindGeoJSON; dz: number }> = []
      for (const [cacheKey, entry] of state.tiles.entries()) {
        if (!cacheKey.startsWith(`${layerId}:`)) continue
        const coords = parseTileCoordsFromCacheKey(cacheKey)
        if (!coords) continue
        const { z, x, y } = coords
        if (z === clampedZoom || z === parentZ) continue
        const dz = Math.abs(z - clampedZoom)
        if (dz < 1 || dz > NEARBY_Z_UNDERLAY_RADIUS) continue
        // 仅同 hour/model/provider：cacheKey 已含这些字段，layer 前缀匹配即可
        if (!cacheKey.includes(`:h${state.hour}`)) continue
        const tileBounds = tileToLngLatBounds(z, x, y)
        if (!tileBoundsOverlapViewport(tileBounds, bounds)) continue
        nearby.push({ z, x, y, raw: touchTileEntry(entry), dz })
      }
      nearby.sort((a, b) => a.dz - b.dz || a.z - b.z)
      for (const c of nearby) {
        const n = 2 ** c.z
        const tileBounds = tileToLngLatBounds(c.z, c.x, c.y)
        const clipped = filterGeojsonInsideTileBounds(c.raw, tileBounds, {
          includeEast: c.x >= n - 1,
          includeSouth: c.y >= n - 1,
        })
        let geojson =
          coveredBounds.length > 0 ? filterGeojsonOutsideCoverage(clipped, coveredBounds) : clipped
        geojson = filterGeojsonInsideTileBounds(geojson, bounds, {
          includeEast: true,
          includeSouth: true,
        })
        if (!geojson.features?.length) continue
        gapFillMatched.push({
          layerId,
          z: c.z,
          x: c.x,
          y: c.y,
          hour: state.hour,
          geojson,
        })
        coveredBounds.push(tileBounds)
      }
    }

    // 本级优先 → 父级 → 邻近 z 缓存
    const mergedTiles: MergedWeatherTile[] = [
      ...currentMatched,
      ...parentMatched,
      ...gapFillMatched,
    ]

    if (parentMatched.length > 0 || gapFillMatched.length > 0) {
      debugLog(
        'getMergedGeojson',
        layerId,
        'multi-z-gap-fill',
        `needZ=${clampedZoom}`,
        `current=${currentMatched.length}/${viewportTiles.length}`,
        `parent=${parentMatched.length}`,
        `nearby=${gapFillMatched.length}`,
      )
    }

    debugLog(
      'getMergedGeojson',
      layerId,
      `gen=${state.generation}`,
      `zoom=${state.zoom}->${clampedZoom}`,
      `hour=${state.hour}`,
      `bbox=${state.bbox ? `${state.bbox.west.toFixed(1)},${state.bbox.south.toFixed(1)},${state.bbox.east.toFixed(1)},${state.bbox.north.toFixed(1)}` : 'null'}`,
      `viewportTiles=${viewportTiles.map((t) => `${t.x},${t.y}`).join('|')}`,
      `cached=${state.tiles.size}:[${cachedKeys.join(',')}]`,
      `matched=${mergedTiles.length}`,
      `coverage=${currentCoverage.toFixed(2)}`,
    )

    if (!mergedTiles.length) {
      // 新瓦片未就绪：用上一帧裁到新视口，避免整屏闪空或粘住旧区域。
      // 条件放宽到「只要有旧帧就沿用」：即使所有瓦片已缓存但为空（pending=0,
      // missing=0），旧帧仍能提供流线/粒子数据，避免控制器被 reset 后永久空白。
      // 新瓦片到达后 dataVersion bump → 新 sync 自然覆盖旧帧。
      if (state.lastMergedGeojson) {
        const clipped = filterGeojsonInsideTileBounds(state.lastMergedGeojson, bounds, {
          includeEast: true,
          includeSouth: true,
        })
        const n = clipped.features?.length ?? 0
        debugLog(
          'getMergedGeojson',
          layerId,
          'stale-while-revalidate clipped',
          `pending=${state.pending.size}`,
          `missing=${countViewportMissing(state)}`,
          `kept=${n}`,
        )
        if (n > 0) return clipped
        return null
      }
      return rememberMergeCache(cacheKey, null)
    }
    const merged = mergeWeatherTiles(mergedTiles)
    const featureCount = Array.isArray(merged.features) ? merged.features.length : 0
    // 已有本级命中时优先用新合并结果（渐进填洞），勿因 feature 变少而退回旧视口数据
    if (
      currentMatched.length === 0 &&
      parentMatched.length === 0 &&
      gapFillMatched.length === 0 &&
      currentCoverage < PARENT_UNDERLAY_COVERAGE_MAX &&
      state.lastMergedGeojson &&
      state.lastMergedFeatureCount > 0 &&
      featureCount < state.lastMergedFeatureCount * 0.55 &&
      (state.pending.size > 0 || countViewportMissing(state) > 0)
    ) {
      const clipped = filterGeojsonInsideTileBounds(state.lastMergedGeojson, bounds, {
        includeEast: true,
        includeSouth: true,
      })
      debugLog(
        'getMergedGeojson',
        layerId,
        'stale-while-revalidate sparse clipped',
        `new=${featureCount}`,
        `prev=${state.lastMergedFeatureCount}`,
        `kept=${clipped.features?.length ?? 0}`,
        `pending=${state.pending.size}`,
      )
      if ((clipped.features?.length ?? 0) > 0) return clipped
    }
    // 本级有命中、邻近垫底或覆盖率足够时更新 stale 锚点
    if (
      currentMatched.length > 0 ||
      parentMatched.length > 0 ||
      gapFillMatched.length > 0 ||
      currentCoverage >= 0.5 ||
      !state.lastMergedGeojson
    ) {
      state.lastMergedGeojson = merged
      state.lastMergedFeatureCount = featureCount
    }
    return rememberMergeCache(cacheKey, merged)
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
