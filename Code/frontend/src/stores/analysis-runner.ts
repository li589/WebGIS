/**
 * Analysis runner: submit InfoPanel GIS tools with exclusivity + per-layer queue.
 *
 * Rules (phase-1):
 * - Same layer+tool → backend cancel-then-accept (exclusivity key)
 * - Same layer, different tools → max 2 concurrent; extras local-queue
 * - Global capacity 429 → exponential backoff retry (capped)
 */
import { defineStore } from 'pinia'
import { computed, onScopeDispose, ref } from 'vue'
import {
  fetchAnalysisTools,
  submitAnalysisRun,
  type AnalysisRunRequestBody,
  type AnalysisToolDescriptor,
  type AnalysisToolListResponse,
} from '../services/analysis-api'
import { ApiRequestError } from '../services/http-errors'
import { cancelWorkflowRun } from '../services/runtime-api'
import { useWorkflowRun } from './layers/selectors'
import type { ActiveLayerDisplay } from './layers/types'

export type AnalysisRunPhase =
  'idle' | 'queued' | 'submitting' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface AnalysisActiveRun {
  toolId: string
  layerId: string
  instanceId: string
  runId: string
  phase: AnalysisRunPhase
  message: string
  replacedPrior?: boolean
}

export interface AnalysisQueueItem {
  id: string
  toolId: string
  layerId: string
  instanceId: string
  body: AnalysisRunRequestBody
  enqueuedAt: number
}

const MAX_PARALLEL_TOOLS_PER_LAYER = 2
const MAX_CAPACITY_RETRIES = 5

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function cancelableSleep(ms: number): { promise: Promise<void>; cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined
  let rejectFn!: () => void
  const promise = new Promise<void>((resolve, reject) => {
    rejectFn = reject
    timer = setTimeout(resolve, ms)
  })
  return {
    promise,
    cancel: () => {
      if (timer) clearTimeout(timer)
      rejectFn()
    },
  }
}

function isCapacityError(err: unknown): boolean {
  if (err instanceof ApiRequestError && err.status === 429) return true
  const msg = err instanceof Error ? err.message : String(err)
  return /\b429\b/.test(msg) || /capacity|max_active|too many/i.test(msg)
}

export const useAnalysisRunnerStore = defineStore('analysis-runner', () => {
  const toolsCache = ref<AnalysisToolListResponse | null>(null)
  const toolsLoading = ref(false)
  const toolsError = ref<string | null>(null)

  const activeByKey = ref<Record<string, AnalysisActiveRun>>({})
  const localQueue = ref<AnalysisQueueItem[]>([])
  const lastHint = ref<string | null>(null)
  /** Bumped on cancel to abort in-flight capacity backoff / submit. */
  const submitGeneration = ref<Record<string, number>>({})
  /** Active watchRun cancellers — keyed by runKey. */
  const watcherCancellers = new Map<string, () => void>()

  const activeRuns = computed(() => Object.values(activeByKey.value))

  function runKey(layerId: string, toolId: string) {
    return `${layerId}::${toolId}`
  }

  function bumpGeneration(key: string) {
    submitGeneration.value = {
      ...submitGeneration.value,
      [key]: (submitGeneration.value[key] ?? 0) + 1,
    }
    return submitGeneration.value[key]
  }

  function currentGeneration(key: string) {
    return submitGeneration.value[key] ?? 0
  }

  onScopeDispose(() => {
    for (const cancel of watcherCancellers.values()) cancel()
    watcherCancellers.clear()
  })

  /** In-flight submits/runs only — used by drain so local `queued` can start. */
  function countRunningForLayer(layerId: string) {
    return activeRuns.value.filter(
      (r) => r.layerId === layerId && (r.phase === 'submitting' || r.phase === 'running'),
    ).length
  }

  /** Slots that block starting another tool (in-flight + local queue + capacity backoff). */
  function countOccupiedSlotsForLayer(layerId: string) {
    const inFlight = countRunningForLayer(layerId)
    const localQueued = localQueue.value.filter((q) => q.layerId === layerId).length
    const capacityBackoff = activeRuns.value.filter(
      (r) =>
        r.layerId === layerId &&
        r.phase === 'queued' &&
        !localQueue.value.some((q) => q.layerId === r.layerId && q.toolId === r.toolId),
    ).length
    return inFlight + localQueued + capacityBackoff
  }

  async function loadToolsForDisplay(display: ActiveLayerDisplay, opts?: { isWeather?: boolean }) {
    toolsLoading.value = true
    toolsError.value = null
    try {
      const overlayId = display.importedRasterOverlayLayerId || undefined
      const res = await fetchAnalysisTools({
        layer_id: display.catalogId,
        overlay_layer_id: overlayId,
        has_raster: Boolean(display.isImportedRaster || overlayId),
        has_vector: Boolean(display.isImported),
        is_weather: Boolean(opts?.isWeather),
        is_point_only: false,
      })
      toolsCache.value = res
      return res
    } catch (err) {
      toolsError.value = err instanceof Error ? err.message : String(err)
      toolsCache.value = null
      throw err
    } finally {
      toolsLoading.value = false
    }
  }

  function toolStatus(toolId: string, layerId: string): AnalysisActiveRun | null {
    return activeByKey.value[runKey(layerId, toolId)] ?? null
  }

  async function cancelRun(layerId: string, toolId: string) {
    const key = runKey(layerId, toolId)
    bumpGeneration(key)
    watcherCancellers.get(key)?.()
    watcherCancellers.delete(key)
    const cur = activeByKey.value[key]
    if (cur?.runId) {
      try {
        await cancelWorkflowRun(cur.runId)
      } catch {
        // ignore — may already be terminal
      }
    }
    if (cur) {
      activeByKey.value = {
        ...activeByKey.value,
        [key]: { ...cur, phase: 'cancelled', message: '已取消' },
      }
    }
    localQueue.value = localQueue.value.filter(
      (q) => !(q.layerId === layerId && q.toolId === toolId),
    )
    void drainQueue(layerId)
  }

  async function submitTool(args: {
    tool: AnalysisToolDescriptor
    display: ActiveLayerDisplay
    params: Record<string, unknown>
    mapPoint?: { lng: number; lat: number } | null
    bbox?: { west: number; south: number; east: number; north: number } | null
    zonesOverlayLayerId?: string | null
    showOnMap?: boolean
  }) {
    const layerId = args.display.catalogId
    const toolId = args.tool.tool_id
    const body: AnalysisRunRequestBody = {
      tool_id: toolId,
      layer_id: layerId,
      overlay_layer_id: args.display.importedRasterOverlayLayerId || null,
      zones_overlay_layer_id: args.zonesOverlayLayerId || null,
      map_point: args.mapPoint || null,
      bbox: args.bbox || null,
      params: args.params,
      show_on_map: args.showOnMap ?? true,
    }

    const key = runKey(layerId, toolId)
    const prior = activeByKey.value[key]

    // Already occupying a slot as queued: update local-queue payload only.
    // Capacity-backoff also uses phase `queued` but is not in localQueue — do not
    // start a second executeSubmit (would double-fire when backoff finishes).
    if (prior?.phase === 'queued') {
      const idx = localQueue.value.findIndex((q) => q.layerId === layerId && q.toolId === toolId)
      if (idx >= 0) {
        const copy = [...localQueue.value]
        copy[idx] = { ...copy[idx], body, instanceId: args.display.instanceId }
        localQueue.value = copy
        lastHint.value = '已更新排队中的同工具参数'
        return
      }
      lastHint.value = '正在等待业务池重试…'
      return
    }

    if (prior && (prior.phase === 'running' || prior.phase === 'submitting')) {
      lastHint.value = '已取代先前同工具分析'
    }

    if (countOccupiedSlotsForLayer(layerId) >= MAX_PARALLEL_TOOLS_PER_LAYER && !prior) {
      const item: AnalysisQueueItem = {
        id: `${Date.now()}-${toolId}`,
        toolId,
        layerId,
        instanceId: args.display.instanceId,
        body,
        enqueuedAt: Date.now(),
      }
      localQueue.value = [...localQueue.value, item]
      activeByKey.value = {
        ...activeByKey.value,
        [key]: {
          toolId,
          layerId,
          instanceId: args.display.instanceId,
          runId: '',
          phase: 'queued',
          message: '同图层并行已满，已加入本地队列',
        },
      }
      lastHint.value = '同图层最多并行 2 个不同工具，已排队'
      return
    }

    await executeSubmit(key, args.display, body, Boolean(prior))
  }

  async function executeSubmit(
    key: string,
    display: ActiveLayerDisplay,
    body: AnalysisRunRequestBody,
    replacedPrior: boolean,
  ) {
    const gen = bumpGeneration(key)
    activeByKey.value = {
      ...activeByKey.value,
      [key]: {
        toolId: body.tool_id,
        layerId: body.layer_id,
        instanceId: display.instanceId,
        runId: '',
        phase: 'submitting',
        message: replacedPrior ? '已取代先前分析，正在提交…' : '正在提交…',
        replacedPrior,
      },
    }

    let attempt = 0
    while (attempt <= MAX_CAPACITY_RETRIES) {
      if (currentGeneration(key) !== gen) return
      try {
        const accepted = await submitAnalysisRun(body)
        if (currentGeneration(key) !== gen) {
          try {
            await cancelWorkflowRun(accepted.run_id)
          } catch {
            /* ignore */
          }
          return
        }
        activeByKey.value = {
          ...activeByKey.value,
          [key]: {
            toolId: body.tool_id,
            layerId: body.layer_id,
            instanceId: display.instanceId,
            runId: accepted.run_id,
            phase: 'running',
            message: accepted.message || '分析运行中…',
            replacedPrior,
          },
        }
        const { registerExternalWorkflowRun } = useWorkflowRun()
        await registerExternalWorkflowRun(accepted.run_id, body.layer_id)
        void watchRun(key, accepted.run_id)
        return
      } catch (err) {
        if (currentGeneration(key) !== gen) return
        if (isCapacityError(err) && attempt < MAX_CAPACITY_RETRIES) {
          attempt += 1
          const wait = Math.min(8000, 500 * 2 ** attempt)
          activeByKey.value = {
            ...activeByKey.value,
            [key]: {
              ...activeByKey.value[key],
              phase: 'queued',
              message: `业务池繁忙，${Math.round(wait / 1000)}s 后重试（${attempt}/${MAX_CAPACITY_RETRIES}）`,
            },
          }
          await sleep(wait)
          continue
        }
        activeByKey.value = {
          ...activeByKey.value,
          [key]: {
            toolId: body.tool_id,
            layerId: body.layer_id,
            instanceId: display.instanceId,
            runId: '',
            phase: 'failed',
            message: err instanceof Error ? err.message : String(err),
          },
        }
        void drainQueue(body.layer_id)
        return
      }
    }
    if (currentGeneration(key) === gen) {
      activeByKey.value = {
        ...activeByKey.value,
        [key]: {
          toolId: body.tool_id,
          layerId: body.layer_id,
          instanceId: display.instanceId,
          runId: '',
          phase: 'failed',
          message: '业务池持续繁忙，请稍后重试',
        },
      }
      void drainQueue(body.layer_id)
    }
  }

  async function watchRun(key: string, runId: string) {
    const { jobLayers } = useWorkflowRun()
    const started = Date.now()
    while (Date.now() - started < 30 * 60_000) {
      const sleeper = cancelableSleep(1500)
      watcherCancellers.set(key, sleeper.cancel)
      try {
        await sleeper.promise
      } catch {
        return
      } finally {
        watcherCancellers.delete(key)
      }
      const job = jobLayers.value.find((j) => j.jobId === runId)
      const cur = activeByKey.value[key]
      if (!cur || cur.runId !== runId) return
      if (cur.phase === 'cancelled') return
      if (!job) continue
      const status = String(job.status || '').toLowerCase()
      if (status === 'succeeded') {
        activeByKey.value = {
          ...activeByKey.value,
          [key]: { ...cur, phase: 'succeeded', message: job.message || '分析完成' },
        }
        void drainQueue(cur.layerId)
        return
      }
      if (status === 'failed') {
        activeByKey.value = {
          ...activeByKey.value,
          [key]: { ...cur, phase: 'failed', message: job.message || '分析失败' },
        }
        void drainQueue(cur.layerId)
        return
      }
      if (status === 'cancelled') {
        activeByKey.value = {
          ...activeByKey.value,
          [key]: { ...cur, phase: 'cancelled', message: '已取消' },
        }
        void drainQueue(cur.layerId)
        return
      }
      if (job.message) {
        activeByKey.value = {
          ...activeByKey.value,
          [key]: { ...cur, phase: 'running', message: job.message },
        }
      }
    }
  }

  async function drainQueue(layerId: string) {
    while (countRunningForLayer(layerId) < MAX_PARALLEL_TOOLS_PER_LAYER) {
      const nextIdx = localQueue.value.findIndex((q) => q.layerId === layerId)
      if (nextIdx < 0) return
      const [item] = localQueue.value.splice(nextIdx, 1)
      localQueue.value = [...localQueue.value]
      const displayLike = {
        catalogId: item.layerId,
        instanceId: item.instanceId,
        importedRasterOverlayLayerId: item.body.overlay_layer_id || undefined,
      } as ActiveLayerDisplay
      await executeSubmit(runKey(item.layerId, item.toolId), displayLike, item.body, false)
    }
  }

  return {
    toolsCache,
    toolsLoading,
    toolsError,
    activeRuns,
    activeByKey,
    localQueue,
    lastHint,
    loadToolsForDisplay,
    toolStatus,
    submitTool,
    cancelRun,
  }
})
