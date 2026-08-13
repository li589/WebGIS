/**
 * useOnlineTemporalIntegration — 将在线时间获取编排器集成到仪表盘。
 *
 * 职责：
 * 1. 当用户时间轴位置落在 'fetchable' 段时自动触发在线获取
 * 2. 监听 jobLayers 状态变化，标记获取成功/失败
 * 3. 定期清理过期跟踪条目
 *
 * 自动触发策略：
 * - 仅在 selectedCatalogId 支持在线获取时启用
 * - 当前时间轴段的 state === 'fetchable' 时触发
 * - 用户拖动时间轴（非播放状态）时触发；播放中不自动获取
 */
import { computed, watch, type ComputedRef, type Ref } from 'vue'
import type { TimelineAvailabilitySegment } from '../../utils/layer-timeline'
import { useOnlineTemporalOrchestrator } from '../../stores/layers/online-temporal-orchestrator'
import type { useLayerWorkspace, useWorkflowRun } from '../../stores/layers/selectors'
import type { JobLayerItem } from '../../stores/layers/types'

interface OnlineTemporalIntegrationDeps {
  workspace: ReturnType<typeof useLayerWorkspace>
  workflowRun: ReturnType<typeof useWorkflowRun>
  selectedCatalogId: ComputedRef<string | null>
  currentDate: Ref<Date>
  currentHour: Ref<number>
  activeLayerGranularity: ComputedRef<string>
  timelineSegments: ComputedRef<TimelineAvailabilitySegment[]>
  isPlaying: Ref<boolean>
  logOperation: (tag: string, message: string) => void
}

export function useOnlineTemporalIntegration(deps: OnlineTemporalIntegrationDeps) {
  const orchestrator = useOnlineTemporalOrchestrator({
    getOnlineTemporalConfig: (catalogId) => deps.workspace.getOnlineTemporalConfig(catalogId),
    runWorkflowForCatalog: (catalogId, options) =>
      deps.workflowRun.runWorkflowForCatalog(catalogId, options),
    selectedCatalogId: deps.selectedCatalogId,
    currentDate: deps.currentDate,
    currentHour: deps.currentHour,
    activeLayerGranularity: deps.activeLayerGranularity as ComputedRef<
      'hour' | 'day' | 'month' | 'year' | 'static'
    >,
    logOperation: deps.logOperation,
  })

  /** 当前时间轴段（与光标位置对齐） */
  const currentSegment = computed<TimelineAvailabilitySegment | null>(() => {
    const segs = deps.timelineSegments.value
    const gran = deps.activeLayerGranularity.value
    if (gran === 'static' || gran === 'hour') {
      const h = Math.floor(deps.currentHour.value)
      return segs.find((s) => s.index === h) ?? null
    }
    if (gran === 'day') {
      const d = deps.currentDate.value.getDate()
      return segs.find((s) => s.index === d) ?? null
    }
    if (gran === 'month') {
      const m = deps.currentDate.value.getMonth()
      return segs.find((s) => s.index === m) ?? null
    }
    if (gran === 'year') {
      const y = deps.currentDate.value.getFullYear()
      return segs.find((s) => s.index === y) ?? null
    }
    return null
  })

  /** 当前段是否为 fetchable 且尚未触发获取 */
  const shouldAutoFetch = computed(() => {
    if (deps.isPlaying.value) return false
    if (!orchestrator.currentLayerSupportsOnline.value) return false
    const seg = currentSegment.value
    if (!seg || seg.state !== 'fetchable') return false
    const status = orchestrator.currentFetchStatus.value
    // 无活跃获取，或之前的获取已失败/冷却 → 可触发
    if (!status) return true
    return status.status === 'failed' || status.status === 'cooling'
  })

  // 自动触发 watcher
  watch(shouldAutoFetch, (should) => {
    if (!should) return
    const catalogId = deps.selectedCatalogId.value
    const timeKey = orchestrator.currentTimeKey.value
    if (!catalogId || !timeKey) return
    // 延迟 300ms 触发，避免快速拖动时频繁提交
    setTimeout(() => {
      if (!shouldAutoFetch.value) return
      void orchestrator.triggerOnlineFetch(catalogId, timeKey)
    }, 300)
  })

  // 监听 jobLayers 状态变化，标记获取成功/失败
  const trackedRunIds = new Map<string, string>() // runId → catalogId

  watch(
    () => deps.workflowRun.jobLayers.value,
    (jobLayers: readonly JobLayerItem[]) => {
      for (const job of jobLayers) {
        if (!job.jobId || job.jobId.startsWith('local-')) continue
        // 跟踪新出现的 in-flight 获取
        const catalogId = job.catalogId
        if (!catalogId) continue

        // 检查是否是我们编排器提交的 run
        const isTracked = isRunTrackedByOrchestrator(job.jobId, orchestrator)
        if (!isTracked && job.status === 'running') {
          // 可能是编排器提交的（runId 已记录在 fetchEntries 中）
          for (const [, entry] of orchestrator.fetchEntries.value) {
            if (entry.runId === job.jobId) {
              trackedRunIds.set(job.jobId, entry.catalogId)
              break
            }
          }
        }

        if (isTracked || trackedRunIds.has(job.jobId)) {
          const catId = trackedRunIds.get(job.jobId) ?? catalogId
          if (job.status === 'succeeded') {
            orchestrator.markSucceeded(catId, job.jobId)
            trackedRunIds.delete(job.jobId)
            deps.logOperation('online-temporal', `获取成功 ${catId} · run ${job.jobId.slice(0, 8)}`)
          } else if (job.status === 'failed' || job.status === 'cancelled') {
            orchestrator.markFailed(catId, job.jobId, job.message)
            trackedRunIds.delete(job.jobId)
            deps.logOperation(
              'online-temporal',
              `获取失败 ${catId} · run ${job.jobId.slice(0, 8)}: ${job.message ?? 'unknown'}`,
            )
          }
        }
      }
    },
    { deep: true },
  )

  // 定期清理过期条目
  let cleanupTimer: ReturnType<typeof setInterval> | null = null
  watch(
    () => orchestrator.currentLayerSupportsOnline.value,
    (supported) => {
      if (supported && !cleanupTimer) {
        cleanupTimer = setInterval(() => orchestrator.cleanupStaleEntries(), 60_000)
      } else if (!supported && cleanupTimer) {
        clearInterval(cleanupTimer)
        cleanupTimer = null
      }
    },
  )

  return {
    orchestrator,
    currentSegment,
    shouldAutoFetch,
  }
}

/** 检查 runId 是否被编排器跟踪 */
function isRunTrackedByOrchestrator(
  runId: string,
  orchestrator: ReturnType<typeof useOnlineTemporalOrchestrator>,
): boolean {
  for (const [, entry] of orchestrator.fetchEntries.value) {
    if (entry.runId === runId) return true
  }
  return false
}
