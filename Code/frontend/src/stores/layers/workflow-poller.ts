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
import {
  dedupeNodeProgress,
  isOverallProgressStage,
  isWeightedOverallProgressStage,
  normalizeWorkflowProgress,
  resolveJobOverallProgress,
} from './workflow-progress'
import { formatProgressShell } from '../../utils/workflow-progress-format'
import {
  messageImpliesTerminalNode,
  extractFailureHints,
} from '../../utils/workflow-operational-log'
import { clearAttachRetry, scheduleSucceededAttachRetry } from './workflow-attach-retry'
import type { JobLayerItem, NodeProgress } from './types'

export const EVENT_POLL_ACTIVE_INTERVAL_MS = 1200
export const EVENT_POLL_IDLE_INTERVAL_MS = 2600
export const STATUS_SYNC_INTERVAL_MS = 9000
/** 无新事件且状态同步后仍非终态时，才判为“事件等待超时”。长批（omega_sf 等）可数小时。 */
export const EVENT_POLL_IDLE_TIMEOUT_MS = 30 * 60_000
export const MAX_CONSECUTIVE_POLL_ERRORS = 3

function extractExecutionRetryCount(payload: unknown): number | undefined {
  if (!payload || typeof payload !== 'object') return undefined
  const raw = (payload as { execution_retry_count?: unknown }).execution_retry_count
  return typeof raw === 'number' && raw > 0 ? raw : undefined
}

export interface WorkflowPollerDeps {
  // ── 状态读 ──
  getJobLayer: (jobId: string) => JobLayerItem | undefined
  isViewportRefreshStale: (epoch?: number) => boolean
  isRunDismissed: (runId: string) => boolean
  getParticleFlowCatalogId: () => string | null
  supportsParticleFlow: (catalogId: string) => boolean
  // ── 状态写 / 动作 ──
  upsertJobLayer: (
    catalogId: string,
    jobLayer: JobLayerItem,
    opts?: { skipActiveLayerSync?: boolean },
  ) => void
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
    opts?: { forceBind?: boolean },
  ) => Promise<number>
  /** 成功终态 attach 后清理组内未产出占位成员（F1） */
  cleanupUnproducedRunLayers: (runId: string, opts?: { succeeded?: boolean }) => void
  /** 组内仍有未绑定占位时勿急着 cleanup（避免 OMEGA 被误删） */
  hasUnboundRunGroupPlaceholders?: (runId: string) => boolean
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
    clearAttachRetry(jobId)
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
    let nextExecutionRetryCount = jobLayer.executionRetryCount ?? 0
    // 节点级进度累计：保留已有节点，按 node_id 合并最新阶段
    let nextNodeProgress: NodeProgress[] = [...(jobLayer.nodeProgress ?? [])]
    /** 本批事件是否见过块产物信号；批末再按最终 status 决定是否物化，避免 running→retry_pending 竞态 409 */
    let sawProgressiveOverlaySignal = false

    for (const event of events) {
      const eventPayload = event.payload as Record<string, unknown> | null | undefined
      const retryCount = extractExecutionRetryCount(eventPayload)
      if (retryCount !== undefined) {
        nextExecutionRetryCount = Math.max(nextExecutionRetryCount, retryCount)
        nextNodeProgress = []
      }
      if (isRecognizedJobStatus(eventPayload?.status) && eventPayload?.status === 'retry_pending') {
        nextNodeProgress = []
      }
      // Overall bar: only lifecycle events (no node_progress) or workflow.dispatch.
      // Module nodes at 100% (e.g. fy_download) must not pin the job bar to 100%.
      const eventNodeProgress = (event.payload as { node_progress?: { node_id?: string } } | null)
        ?.node_progress
      const eventNodeId =
        eventNodeProgress && typeof eventNodeProgress === 'object'
          ? eventNodeProgress.node_id
          : undefined
      if (typeof event.progress === 'number') {
        // 仅加权整体 stage，或带 lifecycle status 的裸事件可抬升作业条。
        // 桥接层 progress=74/95（无 status、无 node_progress）不得把总进度钉死在近 100%。
        const lifecycleStatus = isRecognizedJobStatus(eventPayload?.status)
        if (isWeightedOverallProgressStage(eventNodeId)) {
          nextProgress = Math.max(nextProgress, normalizeWorkflowProgress(event.progress))
        } else if (!eventNodeId && lifecycleStatus) {
          nextProgress = Math.max(nextProgress, normalizeWorkflowProgress(event.progress))
        }
      }
      if (event.message) {
        nextMessage = event.message
      }
      if (isRecognizedJobStatus(event.payload?.status)) {
        // 终态保护：已处于终态时，不允许事件流里的中间状态（queued/running）将其降级
        if (!isTerminalStatus(event.payload.status) && isTerminalStatus(nextStatus)) {
          // 保留终态，仅继续累积进度/消息
        } else if (
          (event.payload.status === 'queued' || event.payload.status === 'accepted') &&
          nextStatus === 'running'
        ) {
          // 已在跑：忽略派发阶段的 queued 回写（否则与 node_progress 升格来回跳）
        } else {
          nextStatus = event.payload.status
        }
      }
      // 解析节点级进度事件
      const rawNodeProgress = (event.payload as { node_progress?: unknown } | null | undefined)
        ?.node_progress
      if (rawNodeProgress && typeof rawNodeProgress === 'object') {
        // 已有节点进度却仍显示排队：worker 已在跑，立即升为 running（勿等 9s 快照）
        if (
          (nextStatus === 'queued' || nextStatus === 'accepted') &&
          !isTerminalStatus(nextStatus)
        ) {
          nextStatus = 'running'
          if (
            !nextMessage ||
            /派发到|等待 worker|Celery/i.test(nextMessage) ||
            nextMessage === '工作流已提交，可轮询状态、事件与结果引用。'
          ) {
            nextMessage = '运行中'
          }
        }
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
                // 下载进度（2026-08-25 下载可视化）：算法包 download_nodes
                // 的 detail 透传（速度/文件数/累计字节）
                speed_bps: typeof detailRaw.speed_bps === 'number' ? detailRaw.speed_bps : null,
                downloaded_items:
                  typeof detailRaw.downloaded_items === 'number'
                    ? detailRaw.downloaded_items
                    : undefined,
                total_items:
                  typeof detailRaw.total_items === 'number' ? detailRaw.total_items : undefined,
                downloaded_bytes:
                  typeof detailRaw.downloaded_bytes === 'number'
                    ? detailRaw.downloaded_bytes
                    : undefined,
                download_mode:
                  typeof detailRaw.download_mode === 'string' ? detailRaw.download_mode : undefined,
                total_bytes:
                  typeof detailRaw.total_bytes === 'number' ? detailRaw.total_bytes : undefined,
                current_item_name:
                  typeof detailRaw.current_item_name === 'string'
                    ? detailRaw.current_item_name
                    : undefined,
                active_workers:
                  typeof detailRaw.active_workers === 'number'
                    ? detailRaw.active_workers
                    : undefined,
                items_display:
                  typeof detailRaw.items_display === 'string' ? detailRaw.items_display : undefined,
              }
            : undefined
        if (
          detail?.phase === 'block_commit' ||
          detail?.phase === 'block_refresh' ||
          detail?.phase === 'artifact'
        ) {
          // 仅记信号；批末按最终 nextStatus 决定是否物化（避免同批内 running→retry_pending）
          sawProgressiveOverlaySignal = true
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
        // workflow.dispatch carries module chunk/pixel detail for the log line,
        // but its progress is already span-weighted — do not inflate with chunk %.
        const nodePct = isOverallProgressStage(np.node_id)
          ? normalizeWorkflowProgress(typeof np.progress === 'number' ? np.progress : undefined)
          : normalizeWorkflowProgress(
              typeof np.progress === 'number' ? np.progress : undefined,
              detail,
            )
        let displayPct = nodePct
        let terminalHint: 'skipped' | 'complete' | undefined
        if (detail?.phase === 'skipping') {
          displayPct = 100
          terminalHint = 'skipped'
        } else if (detail?.phase === 'complete' || nodePct >= 100) {
          displayPct = 100
          if (detail?.phase === 'complete') terminalHint = 'complete'
        } else if (
          displayPct === 0 &&
          ((typeof np.progress === 'number' && np.progress >= 100) ||
            messageImpliesTerminalNode(typeof np.message === 'string' ? np.message : undefined))
        ) {
          displayPct = 100
          terminalHint = 'complete'
        }
        if (typeof np.node_id === 'string') {
          const eventAt = event.created_at
          const existing = nextNodeProgress.find((p) => p.nodeId === np.node_id)
          if (existing) {
            Object.assign(existing, {
              stage: typeof np.stage === 'string' ? np.stage : existing.stage,
              progress:
                typeof np.progress === 'number' || detail
                  ? isOverallProgressStage(np.node_id)
                    ? displayPct
                    : Math.max(existing.progress, displayPct)
                  : existing.progress,
              message: typeof np.message === 'string' ? np.message : existing.message,
              artifacts: Array.isArray(np.artifacts) ? np.artifacts : existing.artifacts,
              detail: detail ?? existing.detail,
              terminalHint: terminalHint ?? existing.terminalHint,
              updatedAt: eventAt,
              eventId: event.event_id,
            })
          } else {
            nextNodeProgress.push({
              nodeId: np.node_id,
              nodeLabel: typeof np.node_label === 'string' ? np.node_label : np.node_id,
              stage: typeof np.stage === 'string' ? np.stage : '',
              progress: displayPct,
              message: typeof np.message === 'string' ? np.message : undefined,
              artifacts: Array.isArray(np.artifacts) ? np.artifacts : undefined,
              detail,
              terminalHint,
              updatedAt: eventAt,
              eventId: event.event_id,
            })
          }
          // Do NOT Math.max module nodePct into job progress — fy_download@100%
          // would pin the bar while omega has barely started. Overall comes from
          // workflow.dispatch (handled above) / resolveJobOverallProgress below.
          if (
            detail?.phase === 'block_commit' ||
            detail?.phase === 'block_refresh' ||
            detail?.phase === 'artifact'
          ) {
            deps.emitWorkflowProgressTimeSeek(
              { ...jobLayer, catalogId: jobLayer.catalogId },
              nextStatus,
              detail,
            )
          }
        }
      }
      lastEventId = event.event_id
      lastEventAt = event.created_at
      nextUpdatedAt = event.created_at
    }

    // 批末：仅当最终状态仍可物化时触发渐进同步（失败进入 retry_pending 则跳过）
    // FE JobStatus 无 accepted（服务端 accepted → queued）
    const canMaterialize =
      nextStatus === 'succeeded' || nextStatus === 'running' || nextStatus === 'queued'
    if (sawProgressiveOverlaySignal && jobLayer.catalogId && canMaterialize) {
      void deps.syncProgressiveBlockOverlays(jobLayer.jobId, jobLayer.catalogId)
    }

    const eventMessages = mergeRecentEventMessages(jobLayer.eventMessages, events)
    const failureHints = extractFailureHints(events)
    let dedupedNodeProgress = dedupeNodeProgress(nextNodeProgress)
    // 作业已终态时，仍停在 0% 的显示节点（仅 start、未收到 progress）提升到完成态
    if (isTerminalStatus(nextStatus)) {
      dedupedNodeProgress = dedupedNodeProgress.map((node) => {
        if (node.progress > 0 || isOverallProgressStage(node.nodeId)) return node
        if (node.terminalHint) return { ...node, progress: 100 }
        if (messageImpliesTerminalNode(node.message)) {
          return { ...node, progress: 100, terminalHint: 'complete' as const }
        }
        // stage_end 可能已把 progress 设为 100；否则终态作业上遗留 0% 视为已完成
        return { ...node, progress: 100, terminalHint: 'complete' as const }
      })
    }
    const resolvedProgress = resolveJobOverallProgress({
      current: nextProgress,
      nodeProgress: dedupedNodeProgress,
    })

    return {
      ...jobLayer,
      status: nextStatus,
      progress: resolvedProgress,
      message: nextMessage,
      updatedAt: nextUpdatedAt,
      lastEventId,
      lastEventAt,
      eventMessages,
      nodeProgress: dedupedNodeProgress,
      executionRetryCount: nextExecutionRetryCount > 0 ? nextExecutionRetryCount : undefined,
      failureHints: failureHints.length
        ? [...new Set([...(jobLayer.failureHints ?? []), ...failureHints])].slice(-12)
        : jobLayer.failureHints,
      diagnosticNotes: jobLayer.diagnosticNotes,
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
    // 终态/非终态统一：事件侧字段优先保留 existing（buildJobLayer 不产出这些）
    const mergedNodeProgress = existingJobLayer?.nodeProgress ?? jobLayer.nodeProgress
    let mergedStatus = jobLayer.status
    // 快照若仍为 queued/accepted，但事件侧已升 running：禁止打回排队中
    if (
      existingJobLayer &&
      existingJobLayer.status === 'running' &&
      (jobLayer.status === 'queued' || jobLayer.status === 'accepted') &&
      !isTerminalStatus(jobLayer.status)
    ) {
      mergedStatus = 'running'
    }
    const mergedMessage =
      mergedStatus === 'running' &&
      existingJobLayer?.message &&
      /派发到|等待 worker|Celery/i.test(jobLayer.message || '')
        ? existingJobLayer.message
        : jobLayer.message
    const mergedJobLayer = existingJobLayer
      ? {
          ...jobLayer,
          status: mergedStatus,
          message: mergedMessage || jobLayer.message,
          progress: resolveJobOverallProgress({
            current: existingJobLayer.progress,
            snapshot: jobLayer.progress,
            nodeProgress: mergedNodeProgress,
          }),
          lastEventId: existingJobLayer.lastEventId ?? jobLayer.lastEventId,
          lastEventAt: existingJobLayer.lastEventAt ?? jobLayer.lastEventAt,
          eventMessages: existingJobLayer.eventMessages ?? jobLayer.eventMessages,
          nodeProgress: mergedNodeProgress,
          failureHints: existingJobLayer.failureHints ?? jobLayer.failureHints,
          diagnosticNotes: jobLayer.diagnosticNotes,
          isAnalysisToolRun: existingJobLayer.isAnalysisToolRun ?? jobLayer.isAnalysisToolRun,
        }
      : {
          ...jobLayer,
          progress: resolveJobOverallProgress({
            snapshot: jobLayer.progress,
            nodeProgress: jobLayer.nodeProgress,
          }),
        }

    deps.upsertJobLayer(catalogId, mergedJobLayer)
    workflowLastStatusSyncAt.set(jobId, now)

    if (isTerminalStatus(mergedJobLayer.status)) {
      stopWorkflowPolling(jobId)
      // GIS 分析工具 run 未加入 activeWorkflowCatalogIds；勿误删同 catalog 主工作流活跃标记
      if (!mergedJobLayer.isAnalysisToolRun) {
        deps.removeActiveCatalog(catalogId)
      }
      if (mergedJobLayer.status === 'succeeded' && !deps.isRunDismissed(run.run_id)) {
        void deps
          .attachAlgorithmProductOverlays(run.result_refs, catalogId, run.run_id)
          .then((boundCount) => {
            if (boundCount > 0) {
              // 部分绑定（如 resume-only 缺 OMEGA）时勿立刻清占位，留给 retry 补齐
              if (!deps.hasUnboundRunGroupPlaceholders?.(run.run_id)) {
                deps.cleanupUnproducedRunLayers(run.run_id, { succeeded: true })
                return
              }
            }
            // 物化/绑定失败或竞态空结果：勿清空占位组（否则侧栏变空）。
            scheduleSucceededAttachRetry({
              runId: run.run_id,
              catalogId,
              resultRefs: run.result_refs,
              attach: deps.attachAlgorithmProductOverlays,
              cleanup: deps.cleanupUnproducedRunLayers,
              isRunDismissed: deps.isRunDismissed,
              hasUnboundPlaceholders: deps.hasUnboundRunGroupPlaceholders,
            })
          })
      }
      if (
        !mergedJobLayer.isAnalysisToolRun &&
        deps.getParticleFlowCatalogId() === catalogId &&
        deps.supportsParticleFlow(catalogId) &&
        !hasRenderableMapLayerAsset(mergedJobLayer)
      ) {
        deps.clearWindForCatalog(catalogId)
      }
      if (
        !mergedJobLayer.isAnalysisToolRun &&
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
          // retry_pending：仅续活轮询，禁止 materialize（BE 会 409）
          if (current.status !== 'retry_pending') {
            void deps.syncProgressiveBlockOverlays(jobId, catalogId)
          }
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
