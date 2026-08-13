/**
 * Analysis runner: submit InfoPanel GIS tools with exclusivity + per-layer queue.
 *
 * Rules (phase-1):
 * - Same layer+tool → backend cancel-then-accept (exclusivity key)
 * - Same layer, different tools → max 2 concurrent; extras local-queue
 * - Global capacity 429 → exponential backoff retry (capped)
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  fetchAnalysisTools,
  submitAnalysisRun,
  type AnalysisRunRequestBody,
  type AnalysisToolDescriptor,
  type AnalysisToolListResponse,
} from '../services/analysis-api'
import { cancelWorkflowRun } from '../services/runtime-api'
import { useLayersStore } from './layers'
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

function isCapacityError(err: unknown): boolean {
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

  const activeRuns = computed(() => Object.values(activeByKey.value))

  function runKey(layerId: string, toolId: string) {
    return `${layerId}::${toolId}`
  }

  function countRunningForLayer(layerId: string) {
    return activeRuns.value.filter(
      (r) =>
        r.layerId === layerId &&
        (r.phase === 'submitting' || r.phase === 'running' || r.phase === 'queued'),
    ).length
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

    // Same tool re-submit: mark replaced (backend also cancels)
    const key = runKey(layerId, toolId)
    const prior = activeByKey.value[key]
    if (prior && (prior.phase === 'running' || prior.phase === 'submitting')) {
      lastHint.value = '已取代先前同工具分析'
    }

    if (countRunningForLayer(layerId) >= MAX_PARALLEL_TOOLS_PER_LAYER && !prior) {
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
      try {
        const accepted = await submitAnalysisRun(body)
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
        const layers = useLayersStore()
        await layers.registerExternalWorkflowRun(accepted.run_id, body.layer_id)
        void watchRun(key, accepted.run_id)
        return
      } catch (err) {
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
        return
      }
    }
  }

  async function watchRun(key: string, runId: string) {
    const layers = useLayersStore()
    // Polling is owned by layers store; mirror terminal status from jobLayers.
    const started = Date.now()
    while (Date.now() - started < 30 * 60_000) {
      await sleep(1500)
      const job = layers.jobLayers.find((j) => j.jobId === runId)
      const cur = activeByKey.value[key]
      if (!cur || cur.runId !== runId) return
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
