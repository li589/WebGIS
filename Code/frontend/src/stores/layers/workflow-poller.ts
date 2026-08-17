/**
 * Workflow 轮询模块（X1/D2 阶段三A）。
 *
 * 从 layers/index.ts 抽离：run 事件轮询 + 快照同步的纯机制，
 * 通过 deps 注入 store 状态读写与 overlay/viewport 动作。
 * 不持有 reactive 状态——轮询句柄/同步时间戳用模块内 Map 管理。
 */
import { getWorkflowEvents, getWorkflowRun } from '../../services/runtime-api'
import type { WorkflowEvent } from '../../services/runtime-api'
import { ApiRequestError } from '../../services/http-errors'
import {
  hasRenderableMapLayerAsset,
  isRecognizedJobStatus,
  isTerminalStatus,
  mergeRecentEventMessages,
} from './catalog-builders'
import { normalizeWorkflowProgress } from './workflow-progress'
import { formatProgressShell } from '../../utils/workflow-progress-format'
import type { JobLayerItem, NodeProgress } from './types'

export const EVENT_POLL_ACTIVE_INTERVAL_MS = 1200
export const EVENT_POLL_IDLE_INTERVAL_MS = 2600
export const STATUS_SYNC_INTERVAL_MS = 9000
/** 无新事件且状态同步后仍非终态时，才判为“事件等待超时”。长批（omega_sf 等）可数小时。 */
export const EVENT_POLL_IDLE_TIMEOUT_MS = 30 * 60_000
export const MAX_CONSECUTIVE_POLL_ERRORS = 3

export interface WorkflowPollerDeps {
  // ── 状态读 ──
  getJobLayer: (jobId: string) => JobLayerItem | undefined
  isViewportRefreshStale: (epoch?: number) => boolean
  isRunDismissed: (runId: string) => boolean
  getParticleFlowCatalogId: () => string | null
  supportsParticleFlow: (catalogId: string) => boolean
  // ── 状态写 / 动作 ──
  upsertJobLayer: (catalogId: string, jobLayer: JobLayerItem) => void
  setWorkflowError: (message: string | null) => void
  removeActiveCatalog: (catalogId: string) => void
  syncProgressiveBlockOverlays: (runId: string, catalogId: string) => void
  emitWorkflowProgressTimeSeek: (
    jobLayer: JobLayerItem,
    status: JobLayerItem['status'],
    detail: { timeKey?: string; dateStart?: string; dateEnd?: string; phase?: string } | undefined,
  ) => void
  attachAlgorithmProductOverlays: (
    resultRefs: unknown,
    preferredCatalogId: string,
    runId?: string,
  ) => Promise<number>
  /** 成功终态 attach 后清理组内未产出占位成员（F1） */
  cleanupUnproducedRunLayers: (runId: string, opts?: { succeeded?: boolean }) => void
  clearWindForCatalog: (catalogId: string) => void
  enableParticleIfUnset: (catalogId: string) => void
  /** buildJobLayer（result-adapter）注入，避免反向依赖 */
  buildJobLayer: (
    run: unknown,
    catalogId: string,
    opts: { previousJobLayer?: JobLayerItem },
  ) => Promise<JobLayerItem>
}

export function createWorkflowPoller(deps: WorkflowPollerDeps) {
  const workflowPollingHandles = new Map<string, number>()
  const workflowLastStatusSyncAt = new Map<string, number>()

  function isPolling(jobId: string): boolean {
    return workflowPollingHandles.has(jobId)
  }

  function stopWorkflowPolling(jobId: string) {
    const handle = workflowPollingHandles.get(jobId)
    if (handle !== undefined) {
      window.clearTimeout(handle)
      workflowPollingHandles.delete(jobId)
    }
    workflowLastStatusSyncAt.delete(jobId)
  }

  /** 渐进块提交事件的副作用 + 状态归并（纯转换，依赖经 deps 注入） */
  function applyWorkflowEventsToJobLayer(
    jobLayer: JobLayerItem,
    events: WorkflowEvent[],
  ): JobLayerItem {
    if (events.length === 0) return jobLayer

    let nextStatus = jobLayer.status
    let nextProgress = jobLayer.progress
    let nextMessage = jobLayer.message
    let nextUpdatedAt = jobLayer.updatedAt
    let lastEventId = jobLayer.lastEventId
    let lastEventAt = jobLayer.lastEventAt
    // 节点级进度累计：保留已有节点，按 node_id 合并最新阶段
    const nextNodeProgress: NodeProgress[] = [...(jobLayer.nodeProgress ?? [])]

    for (const event of events) {
      if (typeof event.progress === 'number') {
        nextProgress = Math.max(nextProgress, normalizeWorkflowProgress(event.progress))
      }
      if (event.message) {
        nextMessage = event.message
      }
      if (isRecognizedJobStatus(event.payload?.status)) {
        // 终态保护：已处于终态时，不允许事件流里的中间状态（queued/running）将其降级
        if (!isTerminalStatus(event.payload.status) && isTerminalStatus(nextStatus)) {
          // 保留终态，仅继续累积进度/消息
        } else {
          nextStatus = event.payload.status
        }
      }
      // 解析节点级进度事件
      const rawNodeProgress = (event.payload as { node_progress?: unknown } | null | undefined)
        ?.node_progress
      if (rawNodeProgress && typeof rawNodeProgress === 'object') {
        const np = rawNodeProgress as {
          node_id?: string
          node_label?: string
          stage?: string
          progress?: number
          message?: string
          artifacts?: string[]
          detail?: Record<string, unknown>
        }
        const detailRaw = np.detail
        const detail =
          detailRaw && typeof detailRaw === 'object'
            ? {
                chunksDone:
                  typeof detailRaw.chunks_done === 'number'
                    ? detailRaw.chunks_done
                    : typeof detailRaw.chunksDone === 'number'
                      ? detailRaw.chunksDone
                      : undefined,
                chunksTotal:
                  typeof detailRaw.chunks_total === 'number'
                    ? detailRaw.chunks_total
                    : typeof detailRaw.chunksTotal === 'number'
                      ? detailRaw.chunksTotal
                      : undefined,
                pixelsDone:
                  typeof detailRaw.pixels_done === 'number'
                    ? detailRaw.pixels_done
                    : typeof detailRaw.pixelsDone === 'number'
                      ? detailRaw.pixelsDone
                      : undefined,
                pixelsTotal:
                  typeof detailRaw.pixels_total === 'number'
                    ? detailRaw.pixels_total
                    : typeof detailRaw.pixelsTotal === 'number'
                      ? detailRaw.pixelsTotal
                      : undefined,
                phase: typeof detailRaw.phase === 'string' ? detailRaw.phase : undefined,
                blocksDone:
                  typeof detailRaw.blocks_done === 'number' ? detailRaw.blocks_done : undefined,
                blocksTotal:
                  typeof detailRaw.blocks_total === 'number' ? detailRaw.blocks_total : undefined,
                dateStart:
                  typeof detailRaw.date_start === 'string' ? detailRaw.date_start : undefined,
                dateEnd: typeof detailRaw.date_end === 'string' ? detailRaw.date_end : undefined,
                blockDir: typeof detailRaw.block_dir === 'string' ? detailRaw.block_dir : undefined,
                timeKey:
                  typeof detailRaw.time_key === 'string'
                    ? detailRaw.time_key
                    : typeof detailRaw.timeKey === 'string'
                      ? detailRaw.timeKey
                      : undefined,
                tileId:
                  typeof detailRaw.tile_id === 'string'
                    ? detailRaw.tile_id
                    : typeof detailRaw.tileId === 'string'
                      ? detailRaw.tileId
                      : undefined,
                chunkId:
                  typeof detailRaw.chunk_id === 'string'
                    ? detailRaw.chunk_id
                    : typeof detailRaw.chunkId === 'string'
                      ? detailRaw.chunkId
                      : undefined,
                blockId:
                  typeof detailRaw.block_id === 'string'
                    ? detailRaw.block_id
                    : typeof detailRaw.blockId === 'string'
                      ? detailRaw.blockId
                      : undefined,
                productTag:
                  typeof detailRaw.product_tag === 'string'
                    ? detailRaw.product_tag
                    : typeof detailRaw.productTag === 'string'
                      ? detailRaw.productTag
                      : typeof detailRaw.artifact_type === 'string'
                        ? detailRaw.artifact_type
                        : undefined,
                moduleName:
                  typeof detailRaw.module_name === 'string'
                    ? detailRaw.module_name
                    : typeof detailRaw.moduleName === 'string'
                      ? detailRaw.moduleName
                      : undefined,
              }
            : undefined
        if (
          detail?.phase === 'block_commit' ||
          detail?.phase === 'block_refresh' ||
          detail?.phase === 'artifact'
        ) {
          // progressive overlay sync (throttled inside helper).
          // Skip when run is already failed/cancelled — hydrate replay of historical
          // block_commit events must not POST materialize (BE returns 409).
          const progressiveCatalogId = jobLayer.catalogId
          const canMaterialize =
            nextStatus === 'succeeded' ||
            nextStatus === 'running' ||
            nextStatus === 'queued' ||
            nextStatus === 'retry_pending'
          if (progressiveCatalogId && canMaterialize) {
            void deps.syncProgressiveBlockOverlays(jobLayer.jobId, progressiveCatalogId)
          }
          if (detail.dateStart && detail.dateEnd) {
            nextMessage = `块 ${detail.blocksDone ?? '?'}/${detail.blocksTotal ?? '?'} · ${detail.dateStart}–${detail.dateEnd}`
          } else {
            const shell = formatProgressShell({
              progress: typeof np.progress === 'number' ? np.progress : undefined,
              message: typeof np.message === 'string' ? np.message : undefined,
              stage: typeof np.stage === 'string' ? np.stage : undefined,
              nodeLabel: typeof np.node_label === 'string' ? np.node_label : undefined,
              detail,
            })
            if (shell) nextMessage = shell
          }
        }
        const nodePct = normalizeWorkflowProgress(
          typeof np.progress === 'number' ? np.progress : undefined,
          detail,
        )
        if (typeof np.node_id === 'string') {
          const eventAt = event.created_at
          const existing = nextNodeProgress.find((p) => p.nodeId === np.node_id)
          if (existing) {
            Object.assign(existing, {
              stage: typeof np.stage === 'string' ? np.stage : existing.stage,
              progress:
                typeof np.progress === 'number' || detail
                  ? Math.max(existing.progress, nodePct)
                  : existing.progress,
              message: typeof np.message === 'string' ? np.message : existing.message,
              artifacts: Array.isArray(np.artifacts) ? np.artifacts : existing.artifacts,
              detail: detail ?? existing.detail,
              updatedAt: eventAt,
              eventId: event.event_id,
            })
          } else {
            nextNodeProgress.push({
              nodeId: np.node_id,
              nodeLabel: typeof np.node_label === 'string' ? np.node_label : np.node_id,
              stage: typeof np.stage === 'string' ? np.stage : '',
              progress: nodePct,
              message: typeof np.message === 'string' ? np.message : undefined,
              artifacts: Array.isArray(np.artifacts) ? np.artifacts : undefined,
              detail,
              updatedAt: eventAt,
              eventId: event.event_id,
            })
          }
          nextProgress = Math.max(nextProgress, nodePct)
          deps.emitWorkflowProgressTimeSeek(
            { ...jobLayer, catalogId: jobLayer.catalogId },
            nextStatus,
            detail,
          )
        }
      }
      lastEventId = event.event_id
      lastEventAt = event.created_at
      nextUpdatedAt = event.created_at
    }

    const eventMessages = mergeRecentEventMessages(
      jobLayer.eventMessages ?? jobLayer.diagnosticNotes,
      events,
    )
    const showEventMessages =
      nextStatus === 'queued' || nextStatus === 'running' || nextStatus === 'retry_pending'

    return {
      ...jobLayer,
      status: nextStatus,
      progress: nextProgress,
      message: nextMessage,
      updatedAt: nextUpdatedAt,
      lastEventId,
      lastEventAt,
      eventMessages,
      nodeProgress: nextNodeProgress,
      diagnosticNotes: showEventMessages ? eventMessages : jobLayer.diagnosticNotes,
    }
  }

  async function syncWorkflowRunSnapshot(
    jobId: string,
    catalogId: string,
    force = false,
    expectedViewportEpoch?: number,
  ): Promise<boolean> {
    if (deps.isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      deps.removeActiveCatalog(catalogId)
      return true
    }

    const now = Date.now()
    if (!force) {
      const lastSyncedAt = workflowLastStatusSyncAt.get(jobId) ?? 0
      if (now - lastSyncedAt < STATUS_SYNC_INTERVAL_MS) {
        return false
      }
    }

    const existingJobLayer = deps.getJobLayer(jobId)
    const run = await getWorkflowRun(jobId)
    if (deps.isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      deps.removeActiveCatalog(catalogId)
      return true
    }
    const jobLayer = await deps.buildJobLayer(run, catalogId, {
      previousJobLayer: existingJobLayer,
    })
    if (deps.isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      deps.removeActiveCatalog(catalogId)
      return true
    }
    const mergedJobLayer =
      existingJobLayer && !isTerminalStatus(jobLayer.status)
        ? {
            ...jobLayer,
            // Keep the higher of server snapshot vs event-derived progress
            progress: Math.max(
              normalizeWorkflowProgress(jobLayer.progress),
              normalizeWorkflowProgress(existingJobLayer.progress),
              ...(existingJobLayer.nodeProgress ?? []).map((np) =>
                normalizeWorkflowProgress(np.progress, np.detail),
              ),
            ),
            lastEventId: existingJobLayer.lastEventId,
            lastEventAt: existingJobLayer.lastEventAt,
            eventMessages: existingJobLayer.eventMessages,
            nodeProgress: existingJobLayer.nodeProgress,
            diagnosticNotes: jobLayer.diagnosticNotes?.length
              ? jobLayer.diagnosticNotes
              : (existingJobLayer.eventMessages ?? existingJobLayer.diagnosticNotes),
          }
        : {
            ...jobLayer,
            progress: normalizeWorkflowProgress(jobLayer.progress),
          }

    deps.upsertJobLayer(catalogId, mergedJobLayer)
    workflowLastStatusSyncAt.set(jobId, now)

    if (isTerminalStatus(mergedJobLayer.status)) {
      stopWorkflowPolling(jobId)
      deps.removeActiveCatalog(catalogId)
      if (mergedJobLayer.status === 'succeeded' && !deps.isRunDismissed(run.run_id)) {
        void deps
          .attachAlgorithmProductOverlays(run.result_refs, catalogId, run.run_id)
          .then(() => {
            deps.cleanupUnproducedRunLayers(run.run_id, { succeeded: true })
          })
      }
      if (
        deps.getParticleFlowCatalogId() === catalogId &&
        deps.supportsParticleFlow(catalogId) &&
        !hasRenderableMapLayerAsset(mergedJobLayer)
      ) {
        deps.clearWindForCatalog(catalogId)
      }
      if (
        mergedJobLayer.status === 'succeeded' &&
        deps.supportsParticleFlow(catalogId) &&
        hasRenderableMapLayerAsset(mergedJobLayer)
      ) {
        deps.enableParticleIfUnset(catalogId)
      }
      return true
    }

    return false
  }

  async function pollWorkflowRun(
    jobId: string,
    catalogId: string,
    lastActivityAt = Date.now(),
    consecutiveErrors = 0,
    expectedViewportEpoch?: number,
  ): Promise<void> {
    if (deps.isViewportRefreshStale(expectedViewportEpoch)) {
      stopWorkflowPolling(jobId)
      deps.removeActiveCatalog(catalogId)
      return
    }
    if (Date.now() - lastActivityAt > EVENT_POLL_IDLE_TIMEOUT_MS) {
      // Soft timeout: trust the server. Never invent a local failure over a
      // succeeded/running run (long omega_sf jobs routinely exceed idle gaps).
      try {
        const run = await getWorkflowRun(jobId)
        const serverStatus = run.status === 'accepted' ? 'queued' : run.status
        if (!isTerminalStatus(serverStatus)) {
          const handle = window.setTimeout(() => {
            void pollWorkflowRun(jobId, catalogId, Date.now(), 0, expectedViewportEpoch)
          }, EVENT_POLL_IDLE_INTERVAL_MS)
          workflowPollingHandles.set(jobId, handle)
          return
        }
        // Terminal on server — sync authoritative snapshot (incl. succeeded)
        await syncWorkflowRunSnapshot(jobId, catalogId, true, expectedViewportEpoch)
        return
      } catch {
        // Network blip: keep polling instead of marking failed.
        const handle = window.setTimeout(() => {
          void pollWorkflowRun(
            jobId,
            catalogId,
            Date.now(),
            consecutiveErrors,
            expectedViewportEpoch,
          )
        }, EVENT_POLL_IDLE_INTERVAL_MS)
        workflowPollingHandles.set(jobId, handle)
        return
      }
    }

    let nextConsecutiveErrors = consecutiveErrors
    let nextDelayMs = EVENT_POLL_IDLE_INTERVAL_MS
    let nextActivityAt = lastActivityAt

    try {
      const existingJobLayer = deps.getJobLayer(jobId)
      const events = await getWorkflowEvents(jobId, {
        afterEventId: existingJobLayer?.lastEventId,
        limit: 24,
      })
      if (deps.isViewportRefreshStale(expectedViewportEpoch)) {
        stopWorkflowPolling(jobId)
        deps.removeActiveCatalog(catalogId)
        return
      }
      const newItems = events.items ?? []

      if (existingJobLayer && newItems.length > 0) {
        deps.upsertJobLayer(catalogId, applyWorkflowEventsToJobLayer(existingJobLayer, newItems))
        nextDelayMs = EVENT_POLL_ACTIVE_INTERVAL_MS
        nextActivityAt = Date.now()
      }

      deps.setWorkflowError(null)
      nextConsecutiveErrors = 0

      const shouldForceSync = newItems.some(
        (event) =>
          isRecognizedJobStatus(event.payload?.status) && isTerminalStatus(event.payload.status),
      )
      const didReachTerminal = await syncWorkflowRunSnapshot(
        jobId,
        catalogId,
        shouldForceSync,
        expectedViewportEpoch,
      )
      if (didReachTerminal) {
        return
      }
      // Status sync that still shows running also counts as activity
      if (shouldForceSync || newItems.length > 0) {
        nextActivityAt = Date.now()
      } else {
        // Periodic status sync: if still running, treat as activity
        const current = deps.getJobLayer(jobId)
        if (
          current &&
          (current.status === 'running' ||
            current.status === 'queued' ||
            current.status === 'retry_pending')
        ) {
          nextActivityAt = Date.now()
          void deps.syncProgressiveBlockOverlays(jobId, catalogId)
        }
      }
    } catch (error) {
      if (deps.isViewportRefreshStale(expectedViewportEpoch)) {
        stopWorkflowPolling(jobId)
        deps.removeActiveCatalog(catalogId)
        return
      }
      const errMsg = error instanceof Error ? error.message : String(error)
      if (errMsg.includes('404')) {
        stopWorkflowPolling(jobId)
        deps.removeActiveCatalog(catalogId)
        deps.setWorkflowError(`工作流 ${jobId} 不存在（可能已过期）`)
        const existingJobLayer = deps.getJobLayer(jobId)
        if (existingJobLayer) {
          deps.upsertJobLayer(catalogId, {
            ...existingJobLayer,
            status: 'failed',
            message: '工作流记录不存在',
            progress: existingJobLayer.progress,
          })
        }
        return
      }

      // Events poll rate-limit / transient 429: back off, do not count as hard failure
      const isRateLimited = error instanceof ApiRequestError && error.status === 429
      // AbortError（requestJson 30s 超时）是临时性错误，不显示给用户，直接重试
      const isAbortError = error instanceof DOMException && error.name === 'AbortError'
      if (isRateLimited && error instanceof ApiRequestError) {
        const retrySec =
          typeof error.retryAfterSec === 'number' && error.retryAfterSec > 0
            ? error.retryAfterSec
            : 5
        nextDelayMs = Math.max(EVENT_POLL_IDLE_INTERVAL_MS, retrySec * 1000)
        nextActivityAt = Date.now()
      } else if (isAbortError) {
        // 超时后用 idle 间隔重试，不递增错误计数，不设置 workflowError
        nextDelayMs = EVENT_POLL_IDLE_INTERVAL_MS
        nextActivityAt = Date.now()
      } else {
        nextConsecutiveErrors = consecutiveErrors + 1
        if (nextConsecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          // Before giving up, ask the server — never invent failure over a live/succeeded run.
          try {
            const run = await getWorkflowRun(jobId)
            const serverStatus = run.status === 'accepted' ? 'queued' : run.status
            if (!isTerminalStatus(serverStatus) || serverStatus === 'succeeded') {
              await syncWorkflowRunSnapshot(jobId, catalogId, true, expectedViewportEpoch)
              if (!isTerminalStatus(serverStatus)) {
                const handle = window.setTimeout(() => {
                  void pollWorkflowRun(jobId, catalogId, Date.now(), 0, expectedViewportEpoch)
                }, EVENT_POLL_IDLE_INTERVAL_MS)
                workflowPollingHandles.set(jobId, handle)
              }
              return
            }
          } catch {
            // fall through
          }
          stopWorkflowPolling(jobId)
          deps.removeActiveCatalog(catalogId)
          deps.setWorkflowError(
            `工作流 ${jobId} 事件同步连续失败 ${nextConsecutiveErrors} 次：${errMsg}`,
          )
          const existingJobLayer = deps.getJobLayer(jobId)
          if (existingJobLayer && existingJobLayer.status !== 'succeeded') {
            deps.upsertJobLayer(catalogId, {
              ...existingJobLayer,
              status: 'failed',
              message: `事件同步连续失败：${errMsg}`,
              progress: existingJobLayer.progress,
            })
          }
          return
        }
        deps.setWorkflowError(errMsg)
      }
    }

    // 页面不可见时延长轮询间隔，避免后台积压定时器导致回来后卡顿
    const effectiveDelay = document.hidden ? Math.max(nextDelayMs, 10000) : nextDelayMs
    const handle = window.setTimeout(() => {
      void pollWorkflowRun(
        jobId,
        catalogId,
        nextActivityAt,
        nextConsecutiveErrors,
        expectedViewportEpoch,
      )
    }, effectiveDelay)
    workflowPollingHandles.set(jobId, handle)
  }

  /** 启动轮询（幂等：已在轮询则跳过） */
  function startPolling(jobId: string, catalogId: string, expectedViewportEpoch?: number) {
    if (workflowPollingHandles.has(jobId)) return
    void pollWorkflowRun(jobId, catalogId, Date.now(), 0, expectedViewportEpoch)
  }

  return {
    isPolling,
    startPolling,
    stopWorkflowPolling,
    pollWorkflowRun,
    syncWorkflowRunSnapshot,
    applyWorkflowEventsToJobLayer,
  }
}
