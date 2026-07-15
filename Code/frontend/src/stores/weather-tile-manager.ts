/**
 * 天气瓦片调度管理器。
 *
 * 职责：
 * - 按图层维护瓦片缓存、视口、世代号。
 * - 全局并发槽位（默认 3），跨图层共享，为其他 workflow 留 1 槽位。
 * - 图层内优先级队列：视口瓦片 priority=0，BFS 外扩预取 priority=1。
 * - 移动/缩放时 generation++，丢弃过期结果并取消不在新视口内的请求。
 * - 每个瓦片通过 /workflow-runs 提交 weather_tile_render 节点任务并轮询结果。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

import type { BoundingBox } from '../services/runtime-api'
import { cancelWorkflowRun, getWorkflowRun } from '../services/runtime-api'
import type { WorkflowRunStatusResponse } from '../services/runtime-api'
import {
  buildTileKey,
  submitWeatherTileWorkflow,
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

const MAX_CONCURRENT_TILE_FETCH = 2
const MAX_LAYER_CACHE_TILES = 128
const PREFETCH_NEIGHBOR_DEPTH = 1
const POLL_INTERVAL_MS = 700
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
  runId?: string
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
 * 因此调用方只需 abort controller 并在必要时取消后端 run。
 */
function cancelPendingRequest(request: TileRequest): void {
  request.controller.abort()
  if (request.runId) {
    void cancelWorkflowRun(request.runId).catch(() => {})
  }
}

function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}

function isTerminalStatus(status: string): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

function extractGeojsonFromRun(run: WorkflowRunStatusResponse): WindGeoJSON | null {
  // 瓦片 workflow 返回两个 json result_ref：
  // 1. weather-result-*   （工作流元数据，inline_data 不含顶层 geojson）
  // 2. weather-tile-geojson-* （实际瓦片 GeoJSON，inline_data.geojson）
  // 优先匹配 weather-tile-geojson-*，其次回退到任意 json 结果
  debugLog('extractGeojson', 'result_refs count=', run.result_refs.length, 'ids=', run.result_refs.map((r) => r.result_id))
  const tileResult = run.result_refs.find(
    (item) => item.result_kind === 'json' && item.result_id?.startsWith('weather-tile-geojson-'),
  )
  debugLog('extractGeojson', 'tileResult found=', !!tileResult, 'tileResultId=', tileResult?.result_id)
  const jsonResult = tileResult ?? run.result_refs.find((item) => item.result_kind === 'json')
  const inlineData = jsonResult?.inline_data
  debugLog('extractGeojson', 'jsonResult id=', jsonResult?.result_id, 'kind=', jsonResult?.result_kind, 'hasInline=', !!inlineData, 'inlineKeys=', inlineData ? Object.keys(inlineData as Record<string, unknown>) : 'null')
  if (!inlineData || typeof inlineData !== 'object') return null
  const geojson = (inlineData as Record<string, unknown>).geojson
  debugLog('extractGeojson', 'geojson type=', geojson ? (geojson as WindGeoJSON).type : 'null')
  if (geojson && typeof geojson === 'object' && (geojson as WindGeoJSON).type === 'FeatureCollection') {
    return geojson as WindGeoJSON
  }
  return null
}

export const useWeatherTileManager = defineStore('weatherTileManager', () => {
  // 全局数据版本号：瓦片缓存变化时递增，供组件 watch 触发重渲染
  const dataVersion = ref(0)
  // 状态版本号：错误/加载状态变化时递增，供 UI watch 触发重渲染
  const statusVersion = ref(0)
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
    state.lastErrorType = errorType
    state.lastErrorMessage = message
    statusVersion.value += 1
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
      // 隐藏时取消所有在途请求；槽位由 submitTile finally 统一释放
      for (const request of state.pending.values()) {
        cancelPendingRequest(request)
      }
      state.pending.clear()
    }
    debugLog('setLayerActive', layerId, active, 'generation', state.generation)
  }

  function clearLayer(layerId: string): void {
    const state = layerStates.get(layerId)
    if (!state) return
    for (const request of state.pending.values()) {
      cancelPendingRequest(request)
    }
    layerStates.delete(layerId)
    debugLog('clearLayer', layerId)
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

    state.generation += 1
    const generation = state.generation
    state.center = center
    state.zoom = zoom
    state.hour = hour
    state.model = model || DEFAULT_WEATHER_MODEL
    state.bbox = bbox
      ? {
          west: bbox.west,
          south: bbox.south,
          east: bbox.east,
          north: bbox.north,
        }
      : null

    const clampedZoom = Math.max(0, Math.min(12, Math.round(zoom)))
    const bounds = state.bbox ?? boundsFromCenter(center, clampedZoom)
    const viewportTiles = tilesInBounds(bounds, clampedZoom, 0)
    const prefetchRing = tilesInBounds(bounds, clampedZoom, PREFETCH_NEIGHBOR_DEPTH).filter(
      (t) => !viewportTiles.some((vt) => vt.x === t.x && vt.y === t.y),
    )
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
        // 对于在途瓦片（dispatched=true），submitTile/pollTile 会动态读取
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
  }

  function drainQueue(): void {
    while (activeFetchCount < MAX_CONCURRENT_TILE_FETCH) {
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
      const { runId } = await submitWeatherTileWorkflow(
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
      request.runId = runId

      // 提交完成后若世代已更新且未被 setViewport 重新对齐，立即取消并丢弃
      if (state.generation !== request.generation) {
        debugLog('submitTile discard stale after submit', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
        void cancelWorkflowRun(runId).catch(() => {})
        return
      }

      await pollTile(request, runId)
    } catch (err) {
      if (isAbortError(err)) {
        debugLog('submitTile aborted', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
      } else if (String(err).includes('429') || (err as Error).message?.includes('429')) {
        const retryCount = (request.retry429Count ?? 0) + 1
        request.retry429Count = retryCount
        if (retryCount <= MAX_429_RETRIES) {
          debugLog('submitTile 429 retry', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `retry=${retryCount}/${MAX_429_RETRIES}`)
          request.runId = undefined
          // 释放槽位，但保留 pending 条目供后续重试
          activeFetchCount = Math.max(0, activeFetchCount - 1)
          // 重置 dispatched 标志，让 drainQueue 在退避过后重新调度
          request.dispatched = false
          // 设置单瓦片退避时间，pickNextRequest 会跳过未到期的瓦片
          request.retryAfter = Date.now() + BACKOFF_429_MS
          // 安排退避后重新 drain
          setTimeout(() => drainQueue(), BACKOFF_429_MS + 100)
          return
        }
        debugLog('submitTile 429 exhausted', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `retries=${retryCount}`)
        setLayerError(layerId, 'rate-limited', '天气 API 请求频率超限，请稍后重试')
        request.runId = undefined
      } else if (String(err).includes('503') || (err as Error).message?.includes('503')) {
        const retryCount = (request.retry503Count ?? 0) + 1
        request.retry503Count = retryCount
        if (retryCount <= MAX_503_RETRIES) {
          debugLog('submitTile 503 retry', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `retry=${retryCount}/${MAX_503_RETRIES}`)
          request.runId = undefined
          activeFetchCount = Math.max(0, activeFetchCount - 1)
          request.dispatched = false
          request.retryAfter = Date.now() + BACKOFF_503_MS
          setTimeout(() => drainQueue(), BACKOFF_503_MS + 100)
          return
        }
        debugLog('submitTile 503 exhausted', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `retries=${retryCount}`)
        setLayerError(layerId, 'circuit-open', '天气服务暂时不可用（断路器保护中），请稍后重试')
        request.runId = undefined
      } else {
        console.error(`[WeatherTileManager] submitTile failed ${layerId} z=${key.z} x=${key.x} y=${key.y}:`, err)
        setLayerError(layerId, 'unknown', (err as Error)?.message ?? '天气瓦片加载失败')
      }
    } finally {
      // 429/503 重试时不清理 pending（dispatched=false 表示已重新入队等待重试）
      if (request.dispatched !== false) {
        const currentState = layerStates.get(layerId)
        // 若世代已过期且瓦片不再被需要，清理 pending；若仍需要则由 setViewport 的重新入队逻辑处理
        if (currentState && currentState.generation !== request.generation) {
          // 世代不匹配但瓦片可能已被 setViewport 重新对齐 generation。
          // 此时 request.generation 已被更新为 currentState.generation，不会进入此分支。
          // 进入此分支说明瓦片确实过期了（不在新视口内），安全清理。
        }
        currentState?.pending.delete(cacheKey)
        activeFetchCount = Math.max(0, activeFetchCount - 1)
        drainQueue()
      }
    }
  }

  async function pollTile(request: TileRequest, runId: string): Promise<void> {
    const { key, layerId } = request
    const state = layerStates.get(layerId)
    if (!state || state.generation !== request.generation) {
      void cancelWorkflowRun(runId).catch(() => {})
      return
    }

    try {
      let run = await getWorkflowRun(runId)
      while (!isTerminalStatus(run.status)) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))

        // 轮询过程中检查世代是否过期（动态读取 request.generation）
        const currentState = layerStates.get(layerId)
        if (!currentState || currentState.generation !== request.generation) {
          debugLog('pollTile generation expired', layerId, `z=${key.z} x=${key.x} y=${key.y}`, `currentGen=${currentState?.generation}`, `reqGen=${request.generation}`)
          void cancelWorkflowRun(runId).catch(() => {})
          return
        }

        if (request.controller.signal.aborted) {
          debugLog('pollTile aborted', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
          void cancelWorkflowRun(runId).catch(() => {})
          return
        }

        run = await getWorkflowRun(runId)
      }

      // 最终检查世代
      const finalState = layerStates.get(layerId)
      if (!finalState || finalState.generation !== request.generation) {
        debugLog('pollTile discard stale result', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
        return
      }

      if (run.status === 'failed') {
        console.warn(`[WeatherTileManager] tile workflow failed ${layerId} z=${key.z} x=${key.x} y=${key.y}:`, run.message)
        const msg = run.message || ''
        if (msg.includes('budget exhausted')) {
          setLayerError(layerId, 'circuit-open', '今日天气 API 调用额度已用尽，明天 UTC 0:00（北京时间 8:00）自动恢复')
        } else if (msg.includes('503') || msg.includes('Circuit breaker')) {
          setLayerError(layerId, 'circuit-open', '天气服务暂时不可用（断路器保护中），请稍后重试')
        } else if (msg.includes('429')) {
          setLayerError(layerId, 'rate-limited', '天气 API 请求频率超限，请稍后重试')
        } else {
          setLayerError(layerId, 'workflow-failed', msg || '天气瓦片工作流执行失败')
        }
        return
      }

      const geojson = extractGeojsonFromRun(run)
      if (!geojson) {
        console.warn(`[WeatherTileManager] no geojson in tile workflow result ${layerId} z=${key.z} x=${key.x} y=${key.y}`)
        return
      }

      const cacheKey = tileCoordsToKey(
        { z: key.z, x: key.x, y: key.y },
        layerId,
        key.hour,
      )
      finalState.tiles.set(cacheKey, geojson)
      trimLayerCache(finalState)
      dataVersion.value += 1
      // 瓦片成功缓存后清除之前的错误状态
      clearLayerError(layerId)

      const cachedTiles: MergedWeatherTile[] = Array.from(finalState.tiles.entries()).map(([k, geojson]) => {
        const zMatch = /:z(\d+):/.exec(k)
        const xMatch = /:x(\d+):/.exec(k)
        const yMatch = /:y(\d+):/.exec(k)
        return {
          layerId,
          z: Number(zMatch?.[1] ?? key.z),
          x: Number(xMatch?.[1] ?? key.x),
          y: Number(yMatch?.[1] ?? key.y),
          hour: key.hour,
          geojson,
        }
      })
      const stats = buildMergeStats(cachedTiles)
      debugLog('pollTile done', layerId, `z=${key.z} x=${key.x} y=${key.y}`, formatMergeStats(layerId, stats))

      // BFS 外扩：当前瓦片 8 邻居以低优先级入队（限制在当前视口外扩 1 圈内）
      expandNeighbors(finalState, key, request.generation)
    } catch (err) {
      if (isAbortError(err)) {
        debugLog('pollTile aborted', layerId, `z=${key.z} x=${key.x} y=${key.y}`)
      } else {
        console.error(`[WeatherTileManager] pollTile failed ${layerId} z=${key.z} x=${key.x} y=${key.y}:`, err)
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

  return {
    dataVersion,
    statusVersion,
    setLayerActive,
    clearLayer,
    setViewport,
    getMergedGeojsonForViewport,
    getDataVersion,
    getStats,
    getLayerStatus,
  }
})
