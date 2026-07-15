/**
 * 天气瓦片调度管理器。
 *
 * 职责：
 * - 按图层维护瓦片缓存、视口、世代号。
 * - 全局并发槽位（默认 4），与后端 WeatherTileService semaphore 对齐。
 * - 图层内优先级队列：视口瓦片 priority=0，BFS 外扩预取 priority=1。
 * - 移动/缩放时 generation++，丢弃过期结果并取消不在新视口内的请求。
 * - 每个瓦片通过 GET /unified-tiles 拉取 GeoJSON（服务端缓存/生成）。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { BoundingBox } from '../services/runtime-api'
import { useLogStore } from './log'
import {
  buildTileKey,
  fetchWeatherTile,
  tilesInBounds,
  type LngLatBounds,
  type WeatherTileCoords,
} from '../services/weather-tile-api'
import {
  buildMergeStats,
  formatMergeStats,
  mergeWeatherTiles,
  type MergedWeatherTile,
} from '../services/weather-tile-utils'
import type { WindGeoJSON } from '../components/map/types'

// ── 自适应并发控制 ──────────────────────────────────────────────────────────
// 并发数不再固定，而是基于 CPU 核心数初始化，再根据成功率（AIMD）和内存压力动态调节：
//   - 成功时缓慢线性增加（Additive Increase）
//   - 429/503 限流时立即乘性减少（Multiplicative Decrease）
//   - JS 堆内存使用率超阈值时主动降低
const MIN_CONCURRENT_TILES = 2
const MAX_CONCURRENT_TILES_CAP = 8
/** 每 N 次连续成功后尝试增加 1 个并发槽位 */
const SUCCESS_THRESHOLD_FOR_INCREASE = 8
/** JS 堆内存使用率阈值（超过则降低并发） */
const MEMORY_PRESSURE_RATIO = 0.8

function computeInitialConcurrency(): number {
  const cores = navigator.hardwareConcurrency ?? 4
  return Math.min(6, Math.max(MIN_CONCURRENT_TILES, Math.floor(cores / 2)))
}

let currentMaxConcurrent = computeInitialConcurrency()
let consecutiveSuccesses = 0

function recordTileSuccess(): void {
  consecutiveSuccesses += 1
  if (consecutiveSuccesses >= SUCCESS_THRESHOLD_FOR_INCREASE && currentMaxConcurrent < MAX_CONCURRENT_TILES_CAP) {
    currentMaxConcurrent += 1
    consecutiveSuccesses = 0
    debugLog('concurrency', 'increase →', currentMaxConcurrent)
  }
}

function recordTileFailure(): void {
  const newLimit = Math.max(MIN_CONCURRENT_TILES, Math.floor(currentMaxConcurrent / 2))
  if (newLimit < currentMaxConcurrent) {
    currentMaxConcurrent = newLimit
    debugLog('concurrency', 'decrease →', currentMaxConcurrent)
  }
  consecutiveSuccesses = 0
}

/** 检查 JS 堆内存压力，超阈值时降低并发 */
function checkMemoryPressure(): void {
  const perfMemory = (performance as Performance & { memory?: { usedJSHeapSize: number; jsHeapSizeLimit: number } }).memory
  if (!perfMemory) return
  const usedRatio = perfMemory.usedJSHeapSize / perfMemory.jsHeapSizeLimit
  if (usedRatio > MEMORY_PRESSURE_RATIO && currentMaxConcurrent > MIN_CONCURRENT_TILES) {
    const newLimit = Math.max(MIN_CONCURRENT_TILES, Math.floor(currentMaxConcurrent / 2))
    if (newLimit < currentMaxConcurrent) {
      currentMaxConcurrent = newLimit
      debugLog('concurrency', 'memory-pressure →', currentMaxConcurrent, `heap=${usedRatio.toFixed(2)}`)
    }
    consecutiveSuccesses = 0
  }
}

const MAX_LAYER_CACHE_TILES = 128
const PREFETCH_NEIGHBOR_DEPTH = 1
const BACKOFF_429_MS = 5000
/** 429 退避后重试的最大次数，避免无限重试 */
const MAX_429_RETRIES = 3
/** 503（断路器/服务不可用）退避时间 */
const BACKOFF_503_MS = 8000
/** 503 重试最大次数 */
const MAX_503_RETRIES = 3

/** 默认气象模型；后端也使用 best_match，这里仅作为显式占位。 */
const DEFAULT_WEATHER_MODEL = 'best_match'

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
  /** 该瓦片最早可重试的时间戳（ms）。drainQueue/pickNextRequest 会跳过未到期的瓦片，
   *  确保单个瓦片的退避不被其他 drainQueue 调用绕过。 */
  retryAfter?: number
}

interface LayerState {
  layerId: string
  generation: number
  visible: boolean
  center: { lng: number; lat: number }
  zoom: number
  hour: number
  model: string
  bbox: LngLatBounds | null
  viewportTiles: WeatherTileCoords[]
  prefetchRing: WeatherTileCoords[]
  tiles: Map<string, WindGeoJSON>
  pending: Map<string, TileRequest>
  /** 最近一次错误类型（null = 无错误）。UI 通过 statusVersion 触发响应式更新。 */
  lastErrorType: WeatherTileErrorType | null
  /** 错误信息（供 UI 展示） */
  lastErrorMessage: string | null
}

export interface LayerTileStats {
  pending: number
  cached: number
  visible: number
}

/** 天气瓦片图层的运行时状态，供 UI 显示加载/错误反馈 */
export type WeatherTileErrorType =
  | 'circuit-open'
  | 'rate-limited'
  | 'workflow-failed'
  | 'timeout'
  | 'unknown'

export interface WeatherTileLayerStatus {
  /** 图层是否可见且需要瓦片 */
  active: boolean
  /** 视口内已缓存的瓦片数 */
  cachedInViewport: number
  /** 视口内瓦片总数 */
  viewportTotal: number
  /** 仍在加载的瓦片数 */
  pending: number
  /** 最近一次错误类型（null = 无错误） */
  errorType: WeatherTileErrorType | null
  /** 错误信息（供 UI 展示） */
  errorMessage: string | null
}

let globalSequence = 0
let activeFetchCount = 0

function debugLog(module: string, ...args: unknown[]) {
  console.log(`[${performance.now().toFixed(1)}ms] [WeatherTileManager:${module}]`, ...args)
}

function tileCoordsToKey(coords: WeatherTileCoords, layerId: string, hour: number): string {
  return buildTileKey(layerId, coords.z, coords.x, coords.y, hour)
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

  function getOrCreateState(layerId: string): LayerState {
    let state = layerStates.get(layerId)
    if (!state) {
      state = {
        layerId,
        generation: 0,
        visible: false,
        center: { lng: 0, lat: 0 },
        zoom: 0,
        hour: 0,
        model: DEFAULT_WEATHER_MODEL,
        bbox: null,
        viewportTiles: [],
        prefetchRing: [],
        tiles: new Map(),
        pending: new Map(),
        lastErrorType: null,
        lastErrorMessage: null,
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
    activityVersion.value += 1
    layerStates.delete(layerId)
    debugLog('clearLayer', layerId)
  }

  function tileKeySetEqual(a: WeatherTileCoords[], b: WeatherTileCoords[]): boolean {
    if (a.length !== b.length) return false
    const keys = new Set(a.map((t) => `${t.z}:${t.x}:${t.y}`))
    return b.every((t) => keys.has(`${t.z}:${t.x}:${t.y}`))
  }

  function setViewport(
    layerId: string,
    center: { lng: number; lat: number },
    zoom: number,
    hour: number,
    model?: string,
    bbox?: BoundingBox | null,
  ): void {
    const state = getOrCreateState(layerId)
    if (!state.visible) return

    const resolvedModel = model || DEFAULT_WEATHER_MODEL
    const clampedZoom = Math.max(0, Math.min(12, Math.round(zoom)))
    const nextBbox = bbox
      ? {
          west: bbox.west,
          south: bbox.south,
          east: bbox.east,
          north: bbox.north,
        }
      : null
    const bounds = nextBbox ?? boundsFromCenter(center, clampedZoom)
    const viewportTiles = tilesInBounds(bounds, clampedZoom, 0)
    const prefetchRing = tilesInBounds(bounds, clampedZoom, PREFETCH_NEIGHBOR_DEPTH).filter(
      (t) => !viewportTiles.some((vt) => vt.x === t.x && vt.y === t.y && vt.z === t.z),
    )

    // 视口/小时/模型未变时跳过，避免重复 moveend 抬世代、冲刷并发槽
    if (
      state.hour === hour
      && state.model === resolvedModel
      && Math.round(state.zoom) === clampedZoom
      && tileKeySetEqual(state.viewportTiles, viewportTiles)
      && tileKeySetEqual(state.prefetchRing, prefetchRing)
    ) {
      debugLog('setViewport skip-noop', layerId, `z=${clampedZoom}`, `hour=${hour}`)
      return
    }

    state.generation += 1
    const generation = state.generation
    state.center = center
    state.zoom = zoom
    state.hour = hour
    state.model = resolvedModel
    state.bbox = nextBbox
    state.viewportTiles = viewportTiles
    state.prefetchRing = prefetchRing

    const desiredKeys = new Set<string>(
      [...viewportTiles, ...prefetchRing].map((t) => tileCoordsToKey(t, layerId, hour)),
    )

    // 取消不在目标集合内的 pending 请求；槽位由 submitTile finally 统一释放
    for (const [key, request] of state.pending.entries()) {
      if (!desiredKeys.has(key)) {
        cancelPendingRequest(request)
        state.pending.delete(key)
      } else {
        // 瓦片仍在视口内：无论是否已派发，都更新世代为当前值。
        // 对于在途瓦片（dispatched=true），submitTile 会动态读取
        // request.generation 进行世代检查，更新后它们的结果不会被误判为过期而丢弃。
        request.generation = generation
      }
    }

    // 对视口缺失瓦片以高优先级入队
    for (const tile of viewportTiles) {
      enqueueIfMissing(state, tile, 0, generation)
    }

    // 外扩候选以低优先级入队
    for (const tile of prefetchRing) {
      enqueueIfMissing(state, tile, 1, generation)
    }

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

  function enqueueIfMissing(
    state: LayerState,
    tile: WeatherTileCoords,
    priority: number,
    generation: number,
  ): void {
    const key = tileCoordsToKey(tile, state.layerId, state.hour)
    if (state.tiles.has(key) || state.pending.has(key)) return
    const controller = new AbortController()
    const request: TileRequest = {
      key: { layerId: state.layerId, z: tile.z, x: tile.x, y: tile.y, hour: state.hour },
      layerId: state.layerId,
      priority,
      generation,
      sequence: ++globalSequence,
      controller,
      dispatched: false,
    }
    state.pending.set(key, request)
    activityVersion.value += 1
  }

  function drainQueue(): void {
    checkMemoryPressure()
    while (activeFetchCount < currentMaxConcurrent) {
      const next = pickNextRequest()
      if (!next) break
      activeFetchCount += 1
      next.dispatched = true
      void submitTile(next)
    }
  }

  function pickNextRequest(): TileRequest | null {
    const now = Date.now()
    let best: TileRequest | null = null
    for (const state of layerStates.values()) {
      if (!state.visible) continue
      for (const request of state.pending.values()) {
        // 已派发的请求仍在 pending 中（等待 submitTile finally 清理），避免重复调度
        if (request.dispatched) continue
        // 跳过仍在退避期内的瓦片，确保单瓦片重试延迟不被其他 drainQueue 调用绕过
        if (request.retryAfter && now < request.retryAfter) continue
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
    )

    try {
      // 调度前已过期：直接返回，pending 删除和槽位释放由 finally 统一处理，避免双重扣减
      // 注意：动态读取 request.generation，因为 setViewport 可能已更新它
      if (!state || state.generation !== request.generation) {
        debugLog('submitTile discard stale before submit', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
        return
      }

      debugLog('submitTile start', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `gen=${request.generation}`, `priority=${request.priority}`)
      const geojson = await fetchWeatherTile(
        layerId,
        key.z,
        key.x,
        key.y,
        {
          hour: key.hour,
          model: state.model,
          signal: request.controller.signal,
        },
      )

      // 拉取完成后若图层已隐藏、已清理或世代已更新，丢弃结果
      const finalState = layerStates.get(layerId)
      if (
        !finalState
        || !finalState.visible
        || finalState.generation !== request.generation
      ) {
        debugLog('submitTile discard stale after fetch', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `visible=${finalState?.visible ?? false}`, `gen=${request.generation}/${finalState?.generation ?? 'gone'}`)
        return
      }

      finalState.tiles.set(cacheKey, geojson)
      trimLayerCache(finalState)
      dataVersion.value += 1
      clearLayerError(layerId)

      const cachedTiles: MergedWeatherTile[] = Array.from(finalState.tiles.entries()).map(([k, tileGeojson]) => {
        const zMatch = /:z(\d+):/.exec(k)
        const xMatch = /:x(\d+):/.exec(k)
        const yMatch = /:y(\d+):/.exec(k)
        return {
          layerId,
          z: Number(zMatch?.[1] ?? key.z),
          x: Number(xMatch?.[1] ?? key.x),
          y: Number(yMatch?.[1] ?? key.y),
          hour: key.hour,
          geojson: tileGeojson,
        }
      })
      const stats = buildMergeStats(cachedTiles)
      debugLog('submitTile done', layerId, `z=${key.z} x=${key.x} y=${key.y}`, formatMergeStats(layerId, stats))

      expandNeighbors(finalState, key, request.generation)
      recordTileSuccess()
    } catch (err) {
      if (isAbortError(err)) {
        debugLog('submitTile aborted', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
      } else if ((err as Error)?.message?.includes('timeout')) {
        // 请求超时：降低自适应并发，不重试（超时通常意味着后端过载）
        recordTileFailure()
        debugLog('submitTile timeout', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
        setLayerError(layerId, 'timeout', '天气瓦片请求超时，后端可能过载，请稍后重试')
      } else if (String(err).includes('429') || (err as Error).message?.includes('429')) {
        const retryCount = (request.retry429Count ?? 0) + 1
        request.retry429Count = retryCount
        if (retryCount <= MAX_429_RETRIES) {
          recordTileFailure()
          // 指数退避：base * 2^(retry-1)，避免多瓦片同时重试再次触发 429
          const backoff = BACKOFF_429_MS * Math.pow(2, retryCount - 1)
          debugLog('submitTile 429 retry', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `retry=${retryCount}/${MAX_429_RETRIES}`, `backoff=${backoff}ms`)
          activeFetchCount = Math.max(0, activeFetchCount - 1)
          request.dispatched = false
          request.retryAfter = Date.now() + backoff
          setTimeout(() => drainQueue(), backoff + 100)
          return
        }
        debugLog('submitTile 429 exhausted', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `retries=${retryCount}`)
        setLayerError(layerId, 'rate-limited', '天气 API 请求频率超限，请稍后重试')
      } else if (String(err).includes('503') || (err as Error).message?.includes('503')) {
        const retryCount = (request.retry503Count ?? 0) + 1
        request.retry503Count = retryCount
        if (retryCount <= MAX_503_RETRIES) {
          recordTileFailure()
          const backoff = BACKOFF_503_MS * Math.pow(2, retryCount - 1)
          debugLog('submitTile 503 retry', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `retry=${retryCount}/${MAX_503_RETRIES}`, `backoff=${backoff}ms`)
          activeFetchCount = Math.max(0, activeFetchCount - 1)
          request.dispatched = false
          request.retryAfter = Date.now() + backoff
          setTimeout(() => drainQueue(), backoff + 100)
          return
        }
        debugLog('submitTile 503 exhausted', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `retries=${retryCount}`)
        setLayerError(layerId, 'circuit-open', '天气服务暂时不可用（断路器保护中），请稍后重试')
      } else {
        console.error(`[WeatherTileManager] submitTile failed ${layerId} z=${key.z} x=${key.x} y=${key.y}:`, err)
        setLayerError(layerId, 'unknown', (err as Error)?.message ?? '天气瓦片加载失败')
      }
    } finally {
      // 429/503 重试时不清理 pending（dispatched=false 表示已重新入队等待重试）
      if (request.dispatched !== false) {
        const currentState = layerStates.get(layerId)
        currentState?.pending.delete(cacheKey)
        activeFetchCount = Math.max(0, activeFetchCount - 1)
        activityVersion.value += 1
        drainQueue()
      }
    }
  }

  function expandNeighbors(state: LayerState, key: TileKey, generation: number): void {
    const n = 2 ** key.z
    const deltas = [
      [-1, -1], [0, -1], [1, -1],
      [-1, 0],           [1, 0],
      [-1, 1],  [0, 1],  [1, 1],
    ]

    // 只预取当前视口外扩 1 圈内的邻居，避免无限外扩和移动后旧预取浪费
    const allowedKeys = new Set<string>(
      [...state.viewportTiles, ...state.prefetchRing].map((t) => tileCoordsToKey(t, state.layerId, state.hour)),
    )

    for (const [dx, dy] of deltas) {
      const nx = ((key.x + dx) % n + n) % n
      const ny = key.y + dy
      if (ny < 0 || ny >= n) continue
      const neighborKey = tileCoordsToKey({ z: key.z, x: nx, y: ny }, state.layerId, state.hour)
      if (!allowedKeys.has(neighborKey)) continue
      enqueueIfMissing(
        state,
        { z: key.z, x: nx, y: ny },
        1,
        generation,
      )
    }
    if (state.pending.size > 0) {
      drainQueue()
    }
  }

  function trimLayerCache(state: LayerState): void {
    while (state.tiles.size > MAX_LAYER_CACHE_TILES) {
      const firstKey = state.tiles.keys().next().value
      if (firstKey === undefined) break
      state.tiles.delete(firstKey)
    }
  }

  function getMergedGeojsonForViewport(layerId: string): WindGeoJSON | null {
    const state = layerStates.get(layerId)
    if (!state || !state.visible) {
      debugLog('getMergedGeojson', layerId, 'state=', !!state, 'visible=', state?.visible)
      return null
    }

    const clampedZoom = Math.max(0, Math.min(12, Math.round(state.zoom)))
    // bbox 可能为 null（addLayer 时未传 bbox），用 center+zoom 兜底计算
    const bounds = state.bbox ?? boundsFromCenter(state.center, clampedZoom)
    const viewportTiles = tilesInBounds(bounds, clampedZoom, 0)
    const mergedTiles: MergedWeatherTile[] = []

    const cachedKeys = Array.from(state.tiles.keys()).map((k) => {
      const zMatch = /:z(\d+):/.exec(k)
      const xMatch = /:x(\d+):/.exec(k)
      const yMatch = /:y(\d+):/.exec(k)
      const hMatch = /:h(\d+)$/.exec(k)
      return `z${zMatch?.[1]}:x${xMatch?.[1]}:y${yMatch?.[1]}:h${hMatch?.[1]}`
    })

    for (const tile of viewportTiles) {
      const key = tileCoordsToKey(tile, layerId, state.hour)
      const geojson = state.tiles.get(key)
      if (geojson) {
        mergedTiles.push({
          layerId,
          z: tile.z,
          x: tile.x,
          y: tile.y,
          hour: state.hour,
          geojson,
        })
      }
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
    )

    if (!mergedTiles.length) return null
    return mergeWeatherTiles(mergedTiles)
  }

  function getDataVersion(): number {
    return dataVersion.value
  }

  function getStats(layerId: string): LayerTileStats {
    const state = layerStates.get(layerId)
    if (!state) return { pending: 0, cached: 0, visible: 0 }
    const clampedZoom = Math.max(0, Math.min(12, Math.round(state.zoom)))
    const visibleCount = state.bbox
      ? tilesInBounds(state.bbox, clampedZoom, 0).length
      : 0
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
        pending: 0,
        errorType: null,
        errorMessage: null,
      }
    }
    const viewportTotal = state.viewportTiles.length
    let cachedInViewport = 0
    for (const tile of state.viewportTiles) {
      const tileKey = tileCoordsToKey(tile, layerId, state.hour)
      if (state.tiles.has(tileKey)) cachedInViewport += 1
    }
    return {
      active: true,
      cachedInViewport,
      viewportTotal,
      pending: state.pending.size,
      errorType: state.lastErrorType,
      errorMessage: state.lastErrorMessage,
    }
  }

  /** 获取所有天气图层当前活跃（pending）的瓦片总数，供标题栏工作流状态汇总使用 */
  function getGlobalActiveTileCount(): number {
    let count = 0
    for (const state of layerStates.values()) {
      if (state.visible) {
        count += state.pending.size
      }
    }
    return count
  }

  /** 获取当前自适应并发信息，供 UI 监控显示 */
  function getConcurrencyInfo(): { active: number; max: number } {
    return { active: activeFetchCount, max: currentMaxConcurrent }
  }

  return {
    dataVersion,
    statusVersion,
    activityVersion,
    setLayerActive,
    clearLayer,
    setViewport,
    getMergedGeojsonForViewport,
    getDataVersion,
    getStats,
    getLayerStatus,
    getGlobalActiveTileCount,
    getConcurrencyInfo,
  }
})
