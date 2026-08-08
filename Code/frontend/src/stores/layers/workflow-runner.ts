/**
 * Workflow 提交/取消/重试 + 恢复编排模块（X1/D2 阶段三B）。
 *
 * 从 layers/index.ts 抽离：
 *  - 恢复簇：restoreActiveWorkflows / registerExternalWorkflowRun /
 *    resolveRestoredCatalogId / hydrateJobLayerFromEvents /
 *    resolveRestoreWorkflowBridge / ensureRestoredRunGroup
 *  - tracked runs helpers：localStorage 持久化 + remember/forget
 *  - 提交簇：runWorkflowForCatalog / interruptWorkflowForCatalog /
 *    scheduleWorkflowRetry / cancelWorkflowRunForJob / retryWorkflowRunForJob
 *
 * 不持有 reactive 状态——store 状态经 deps getter / 写回调注入；
 * runtime-api / 纯函数模块直接 import（无 store 依赖）。
 */
import {
  cancelWorkflowRun,
  getWorkflowEvents,
  getWorkflowRun,
  listActiveWorkflowRuns,
  listRecentSucceededRuns,
  retryWorkflowRun,
  submitWorkflow,
} from '../../services/runtime-api'
import type { BoundingBox, RuntimeLayerDescriptor, WorkflowEvent } from '../../services/runtime-api'
import { useWorkflowOutputLayersStore } from '../workflow-output-layers'
import { buildJobLayer } from './result-adapter'
import { forgetDismissedLayer, isRunDismissed } from './workspace-persist'
import { getCatalogDisplayName, isTerminalStatus } from './catalog-builders'
import { normalizeWorkflowProgress } from './workflow-progress'
import { resolveRestoreWorkflowBridge as resolveRestoreWorkflowBridgeFromCatalog } from './restore-workflow-bridge'
import { claimOrphanWorkflowRun, isSubmitTimeoutError } from '../../utils/workflow-submit-reconcile'
import { localizeWorkflowErrorMessage } from '../../utils/workflow-error-messages'
import { productTagLabel } from '../../utils/workflow-expected-outputs'
import { isDebugLogEnabled } from '../../utils/perf-probe'
import { WORKFLOW_COPY } from '../../ui-copy/workflow'
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
  RuntimeLayerLibraryItem,
} from './types'

function debugLog(module: string, ...args: unknown[]) {
  if (!isDebugLogEnabled()) return
  console.log(`[${performance.now().toFixed(1)}ms] [LayersStore:${module}]`, ...args)
}

/** 刷新后恢复用：记住本机跟踪中的 run，避免仅依赖内存态丢失进度。 */
const TRACKED_RUNS_STORAGE_KEY = 'geo:tracked-workflow-runs:v1'

export interface TrackedWorkflowRun {
  runId: string
  catalogId: string
  name?: string
  updatedAt: string
  groupId?: string
  memberCatalogIds?: string[]
}

export function loadTrackedWorkflowRuns(): TrackedWorkflowRun[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(TRACKED_RUNS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (item): item is TrackedWorkflowRun =>
        !!item && typeof item.runId === 'string' && typeof item.catalogId === 'string',
    )
  } catch {
    return []
  }
}

export function saveTrackedWorkflowRuns(runs: TrackedWorkflowRun[]) {
  if (typeof window === 'undefined') return
  try {
    // Keep recent 40 entries
    window.localStorage.setItem(TRACKED_RUNS_STORAGE_KEY, JSON.stringify(runs.slice(0, 40)))
  } catch {
    // ignore quota errors
  }
}

export interface WorkflowRunnerDeps {
  // ── poller（三A 产物，store 实例化后传入方法）──
  startPolling: (jobId: string, catalogId: string, expectedViewportEpoch?: number) => void
  stopWorkflowPolling: (jobId: string) => void
  isPolling: (jobId: string) => boolean
  syncWorkflowRunSnapshot: (
    jobId: string,
    catalogId: string,
    force?: boolean,
    expectedViewportEpoch?: number,
  ) => Promise<boolean>
  applyWorkflowEventsToJobLayer: (jobLayer: JobLayerItem, events: WorkflowEvent[]) => JobLayerItem

  // ── 状态读（getter，避免直接持有 ref；Set/Map 传引用）──
  getActiveLayers: () => ActiveLayer[]
  getJobLayers: () => JobLayerItem[]
  getRunLayerGroups: () => ActiveRunLayerGroup[]
  getRuntimeLayerCatalog: () => Record<string, RuntimeLayerDescriptor>
  getLayerLibrary: () => RuntimeLayerLibraryItem[]
  getMapBBox: () => BoundingBox | null
  activeWorkflowCatalogIds: Set<string>
  submittingCatalogIds: Set<string>
  workflowRetryTimers: Map<string, number>
  workflowRetryCounts: Map<string, number>

  // ── 状态写（store 写函数注入）──
  setRunLayerGroups: (groups: ActiveRunLayerGroup[]) => void
  upsertJobLayer: (catalogId: string, jobLayer: JobLayerItem) => void
  removeJobLayerById: (jobId: string) => void
  setWorkflowError: (message: string | null) => void
  scheduleWorkspacePersist: () => void
  cleanupUnproducedRunLayers: (runId: string) => void
  createRunLayerGroup: (options: {
    title: string
    targets: Array<{ name: string; productTag: string }>
    sourceLayerId: string
    workflowId: string
    memberCatalogIds?: string[]
  }) => { groupId: string; memberInstanceIds: string[]; memberCatalogIds: string[] }
  bindRunIdToGroup: (groupId: string, runId: string) => void
  attachAlgorithmProductOverlays: (
    resultRefs: unknown,
    preferredCatalogId: string,
    runId?: string,
    opts?: { forceBind?: boolean },
  ) => Promise<number>

  // ── 业务判定 / 载荷构建（store 内既有函数注入）──
  isLocalSubmitJobId: (jobId: string | null | undefined) => boolean
  isViewportRefreshStale: (epoch?: number) => boolean
  isWeatherEngineLayer: (catalogId: string) => boolean
  resolveBackendLayerId: (catalogId: string) => string
  ensureRuntimeLayerCatalog: (force?: boolean) => Promise<void>
  getCatalogRunBlockReason: (catalogId: string) => string | null
  supportsAnalysisWorkflow: (catalogId: string) => boolean
  supportsMapLayerResult: (catalogId: string) => boolean
  buildWorkflowPayloadForCatalog: (
    catalogId: string,
    catalogName: string,
    requestedOutputs: string[],
    requestBBox: BoundingBox | null,
    backendLayerId?: string,
    algorithmRequest?: Record<string, unknown>,
    weatherRequest?: Record<string, unknown>,
  ) => Record<string, unknown>
  /** 天气引擎图层：激活瓦片管道并按当前视口刷新（store 侧封装 tile manager 调用） */
  activateWeatherTileViewport: (catalogId: string) => void

  // ── 快照恢复（workspace-persist / 快照水合）──
  hydrateWorkspaceFromSnapshot: () => Map<string, string>
  hydrateVectorLayersFromSnapshot: (instanceIdMap: Map<string, string>) => Promise<void>
  reconcileOmegaBlockLayers: () => void
}

export function createWorkflowRunner(deps: WorkflowRunnerDeps) {
  function rememberTrackedWorkflowRun(catalogId: string, jobLayer: JobLayerItem) {
    // 乐观提交 ID 不是后端真 run，禁止写入恢复列表（否则会 404 / 误点重试）
    if (deps.isLocalSubmitJobId(jobLayer.jobId)) return
    if (isTerminalStatus(jobLayer.status) && jobLayer.status === 'cancelled') {
      forgetTrackedWorkflowRun(jobLayer.jobId)
      return
    }
    const group = deps.getRunLayerGroups().find((g) => g.runId === jobLayer.jobId)
    const memberCatalogIds = group
      ? group.memberInstanceIds
          .map((id) => deps.getActiveLayers().find((l) => l.instanceId === id)?.catalogId)
          .filter((id): id is string => Boolean(id))
      : undefined
    const existing = loadTrackedWorkflowRuns().filter((item) => item.runId !== jobLayer.jobId)
    existing.unshift({
      runId: jobLayer.jobId,
      catalogId,
      name: jobLayer.name,
      updatedAt: jobLayer.updatedAt || new Date().toISOString(),
      groupId: group?.groupId,
      memberCatalogIds,
    })
    saveTrackedWorkflowRuns(existing)
  }

  function forgetTrackedWorkflowRun(runId: string) {
    saveTrackedWorkflowRuns(loadTrackedWorkflowRuns().filter((item) => item.runId !== runId))
  }

  /**
   * 注册一个外部触发的工作流 run（如定时器触发、后端直接提交），
   * 将其写入 jobLayers 并启动轮询跟踪。
   * catalogId 用于关联图层；若未知则用 run.engine 或 fallback。
   */
  async function registerExternalWorkflowRun(runId: string, catalogIdHint?: string) {
    // 已在跟踪则跳过
    if (deps.isPolling(runId)) return
    const existing = deps.getJobLayers().find((item) => item.jobId === runId)
    if (existing && !isTerminalStatus(existing.status)) return

    try {
      const run = await getWorkflowRun(runId)
      // 推断 catalogId：优先 hint，其次从 run payload 的 layer_id 取
      const inferredCatalogId =
        catalogIdHint ?? ((run as Record<string, unknown>).layer_id as string) ?? runId
      const jobLayer = await buildJobLayer(run, inferredCatalogId, {})
      deps.upsertJobLayer(inferredCatalogId, jobLayer)
      if (!isTerminalStatus(jobLayer.status)) {
        deps.activeWorkflowCatalogIds.add(inferredCatalogId)
        void deps.startPolling(runId, inferredCatalogId)
      }
    } catch (err) {
      console.error('[layers] registerExternalWorkflowRun failed:', runId, err)
    }
  }

  function resolveRestoredCatalogId(runLayerId: string | null | undefined, runId: string): string {
    const layerId = (runLayerId || '').trim()
    const tracked = loadTrackedWorkflowRuns().find((item) => item.runId === runId)
    if (tracked?.catalogId) return tracked.catalogId
    if (layerId) {
      const outputStore = useWorkflowOutputLayersStore()
      const match = outputStore.entries.find(
        (entry) => entry.sourceLayerId === layerId && entry.lastRunId === runId,
      )
      if (match) return match.localId
      const bySource = outputStore.getBySourceLayerId(layerId)
      if (bySource.length === 1) return bySource[0].localId
      if (bySource.length > 1) {
        // Prefer most recently created output entry
        return bySource[0].localId
      }
      return layerId
    }
    return runId
  }

  /** Replay recent events so node progress bars survive page refresh. */
  async function hydrateJobLayerFromEvents(jobLayer: JobLayerItem): Promise<JobLayerItem> {
    try {
      const events = await getWorkflowEvents(jobLayer.jobId, { limit: 50 })
      const items = events.items ?? []
      if (!items.length) return jobLayer
      return deps.applyWorkflowEventsToJobLayer(jobLayer, items)
    } catch {
      return jobLayer
    }
  }

  /**
   * 从后端 + localStorage 恢复工作流列表。在页面加载 / 刷新后调用，
   * 确保跨会话与长批任务的进度条/节点进度不会丢失。
   */
  async function restoreActiveWorkflows() {
    try {
      // 先恢复本机已产出图层/组，再合并后端活跃 run
      const instanceIdMap = deps.hydrateWorkspaceFromSnapshot()
      await deps.hydrateVectorLayersFromSnapshot(instanceIdMap)
      deps.reconcileOmegaBlockLayers()

      const activeRuns = await listActiveWorkflowRuns().catch(() => [])
      const tracked = loadTrackedWorkflowRuns()
      const seen = new Set<string>()

      const candidates: Array<{
        runId: string
        catalogIdHint?: string
        autoDiscovered?: boolean
      }> = []

      // 先收集最近成功的 omega 反演 run（列表按创建时间倒序），
      // 同一工作流（command_label）只保留最新成功 run；
      // 同时建立「工作流 → 最新成功 run」映射，用于压制同工作流的僵尸活跃 run。
      const recentSucceeded = await listRecentSucceededRuns(20).catch(() => [])
      const succeededByWorkflow = new Set<string>()
      const seenWorkflowLabels = new Set<string>()
      for (const run of recentSucceeded) {
        const layerId = String((run as Record<string, unknown>).layer_id || '')
        // 仅恢复 omega_sf_fenkuai 分块反演等算法产物 run，避免无差别拉起所有历史 run
        if (!/omega[-_]sf[-_]fenkuai|omega_sf_omega_pixel/i.test(layerId)) continue
        const workflowKey = String((run as Record<string, unknown>).command_label || layerId)
        succeededByWorkflow.add(workflowKey)
        if (seenWorkflowLabels.has(workflowKey)) continue
        seenWorkflowLabels.add(workflowKey)
        forgetDismissedLayer({ runId: run.run_id })
        if (!candidates.some((c) => c.runId === run.run_id)) {
          candidates.push({
            runId: run.run_id,
            catalogIdHint: layerId || undefined,
            autoDiscovered: true,
          })
        }
      }

      for (const run of activeRuns) {
        // 同一工作流已有成功产物时，不再恢复其 running/queued 占位
        // （worker 重启后僵尸 running run 会永远卡在占位组，展示陈旧中间块）。
        const workflowKey = String(
          (run as Record<string, unknown>).command_label ||
            (run as Record<string, unknown>).layer_id ||
            '',
        )
        if (workflowKey && succeededByWorkflow.has(workflowKey)) continue
        candidates.push({
          runId: run.run_id,
          catalogIdHint: ((run as Record<string, unknown>).layer_id as string) || undefined,
        })
      }
      for (const item of tracked) {
        if (deps.isLocalSubmitJobId(item.runId)) {
          forgetTrackedWorkflowRun(item.runId)
          continue
        }
        if (!candidates.some((c) => c.runId === item.runId)) {
          candidates.push({ runId: item.runId, catalogIdHint: item.catalogId })
        }
      }

      // 清掉残留的乐观提交占位（排队幽灵）
      for (const job of [...deps.getJobLayers()]) {
        if (deps.isLocalSubmitJobId(job.jobId)) {
          deps.removeJobLayerById(job.jobId)
        }
      }

      for (const candidate of candidates) {
        if (seen.has(candidate.runId)) continue
        seen.add(candidate.runId)
        if (isRunDismissed(candidate.runId)) {
          forgetTrackedWorkflowRun(candidate.runId)
          continue
        }
        if (deps.isPolling(candidate.runId)) continue
        const existing = deps.getJobLayers().find((item) => item.jobId === candidate.runId)
        if (existing && !isTerminalStatus(existing.status) && deps.isPolling(candidate.runId)) {
          continue
        }

        let run
        try {
          run = await getWorkflowRun(candidate.runId)
        } catch (err) {
          console.warn('[layers] restore skip missing run', candidate.runId, err)
          forgetTrackedWorkflowRun(candidate.runId)
          continue
        }

        // 非终态且同工作流已有成功版本 → 跳过（防止僵尸 running 重建占位组）
        if (run.status !== 'succeeded') {
          const workflowKey = String(
            (run as Record<string, unknown>).command_label ||
              (run as Record<string, unknown>).layer_id ||
              '',
          )
          if (workflowKey && succeededByWorkflow.has(workflowKey)) {
            forgetTrackedWorkflowRun(candidate.runId)
            continue
          }
        }

        const catalogId = resolveRestoredCatalogId(
          ((run as Record<string, unknown>).layer_id as string) || candidate.catalogIdHint,
          run.run_id,
        )
        let jobLayer = await buildJobLayer(run, catalogId, {
          previousJobLayer: existing,
        })
        jobLayer = await hydrateJobLayerFromEvents(jobLayer)
        // Prefer hydrated progress over bare server snapshot (often stuck at 18/35)
        if (existing) {
          jobLayer = {
            ...jobLayer,
            progress: Math.max(
              normalizeWorkflowProgress(jobLayer.progress),
              normalizeWorkflowProgress(existing.progress),
              ...(jobLayer.nodeProgress ?? []).map((np) =>
                normalizeWorkflowProgress(np.progress, np.detail),
              ),
            ),
            nodeProgress: jobLayer.nodeProgress?.length
              ? jobLayer.nodeProgress
              : existing.nodeProgress,
            eventMessages: jobLayer.eventMessages?.length
              ? jobLayer.eventMessages
              : existing.eventMessages,
          }
        }
        deps.upsertJobLayer(catalogId, jobLayer)

        const outputStore = useWorkflowOutputLayersStore()
        if (catalogId.startsWith('wf-out-')) {
          outputStore.updateRunStatus(catalogId, run.run_id, jobLayer.status)
        }

        if (!isTerminalStatus(jobLayer.status)) {
          const trackedItem = tracked.find((t) => t.runId === run.run_id)
          const layerId = String((run as Record<string, unknown>).layer_id || catalogId)
          const bridge = resolveRestoreWorkflowBridge(layerId, catalogId, trackedItem)
          if (bridge.workflowId || bridge.sourceLayerId || catalogId.startsWith('wf-run-')) {
            ensureRestoredRunGroup(run.run_id, catalogId, trackedItem, {
              createPlaceholders: true,
              title: jobLayer.name || bridge.title || '工作流运行',
            })
          }
          deps.activeWorkflowCatalogIds.add(catalogId)
          void deps.startPolling(run.run_id, catalogId)
        } else if (
          jobLayer.status === 'succeeded' &&
          (candidate.autoDiscovered || !isRunDismissed(run.run_id))
        ) {
          // 确保计算组结构存在，便于 attach 绑到产物成员
          ensureRestoredRunGroup(
            run.run_id,
            catalogId,
            tracked.find((t) => t.runId === run.run_id),
          )
          // 自动发现的 run 强制绑定数据（绕过用户此前可能点过的"移除"标记），
          // 保证"有图层就有内容"；用户主动移除的 tracked run 仍保持被移除状态。
          void deps
            .attachAlgorithmProductOverlays(run.result_refs, catalogId, run.run_id, {
              forceBind: Boolean(candidate.autoDiscovered),
            })
            .then(() => deps.scheduleWorkspacePersist())
        }
      }

      // 清理快照残留的旧 run 组：runId 不在本次恢复集合（已被新 run 取代或已移除）
      // 的 restored 组连同其占位成员一并移除，避免陈旧时间块继续显示。
      const restoredRunIds = new Set(candidates.map((c) => c.runId))
      const staleGroupIds = new Set(
        deps
          .getRunLayerGroups()
          .filter((g) => g.runId && !restoredRunIds.has(g.runId))
          .map((g) => g.groupId),
      )
      if (staleGroupIds.size > 0) {
        deps.setRunLayerGroups(
          deps.getRunLayerGroups().filter((g) => !staleGroupIds.has(g.groupId)),
        )
        const activeLayers = deps.getActiveLayers()
        for (let i = activeLayers.length - 1; i >= 0; i--) {
          const layer = activeLayers[i]!
          if (layer.runGroupId && staleGroupIds.has(layer.runGroupId)) {
            activeLayers.splice(i, 1)
          }
        }
      }
      deps.scheduleWorkspacePersist()
    } catch (err) {
      console.error('[layers] restoreActiveWorkflows failed:', err)
    }
  }

  function resolveRestoreWorkflowBridge(
    layerId: string,
    catalogId: string,
    tracked?: TrackedWorkflowRun,
  ): { sourceLayerId?: string; workflowId?: string; title?: string } {
    const candidates = [layerId, catalogId, tracked?.catalogId].filter((id): id is string =>
      Boolean(id),
    )
    const catalogMap: Record<
      string,
      {
        layer_id: string
        workflow_id?: string | null
        workflow_name?: string | null
        display_name?: string
      }
    > = {}
    const runtimeLayerCatalog = deps.getRuntimeLayerCatalog()
    for (const id of candidates) {
      const hit = runtimeLayerCatalog[id]
      if (hit) {
        catalogMap[id] = {
          layer_id: hit.layer_id,
          workflow_id: hit.workflow_id,
          workflow_name: hit.workflow_name,
          display_name: hit.display_name,
        }
      }
    }
    if (!Object.keys(catalogMap).length) {
      for (const d of Object.values(runtimeLayerCatalog)) {
        if (
          Boolean(d.workflow_id) &&
          candidates.some(
            (id) => id === d.layer_id || id.includes(d.layer_id) || d.layer_id.includes(id),
          )
        ) {
          catalogMap[d.layer_id] = {
            layer_id: d.layer_id,
            workflow_id: d.workflow_id,
            workflow_name: d.workflow_name,
            display_name: d.display_name,
          }
          break
        }
      }
    }
    const base = resolveRestoreWorkflowBridgeFromCatalog(catalogMap, layerId, catalogId)
    const group = deps.getRunLayerGroups().find((g) => g.runId === tracked?.runId)
    const sourceLayerId =
      group?.sourceLayerId ||
      base.sourceLayerId ||
      (tracked?.catalogId && !tracked.catalogId.startsWith('wf-') ? tracked.catalogId : undefined)
    const workflowId = group?.workflowId || base.workflowId || undefined
    return {
      sourceLayerId,
      workflowId,
      title:
        tracked?.name ||
        catalogMap[layerId]?.display_name ||
        catalogMap[catalogId]?.display_name ||
        undefined,
    }
  }

  function ensureRestoredRunGroup(
    runId: string,
    catalogId: string,
    tracked?: TrackedWorkflowRun,
    options?: { createPlaceholders?: boolean; title?: string },
  ) {
    if (deps.getRunLayerGroups().some((g) => g.runId === runId)) return
    const bridge = resolveRestoreWorkflowBridge(
      String(tracked?.catalogId || catalogId),
      catalogId,
      tracked,
    )
    const groupId =
      tracked?.groupId || `run-group-restored-${runId.replace(/[^a-zA-Z0-9]/g, '').slice(-10)}`
    const tags = ['SM', 'VOD', 'OMEGA'] as const
    const memberCatalogIds =
      tracked?.memberCatalogIds?.length === 3
        ? tracked.memberCatalogIds
        : tags.map((tag) => `wf-run-${groupId}-${tag.toLowerCase()}`)

    const existingMembers = memberCatalogIds
      .map((cid) => deps.getActiveLayers().find((l) => l.catalogId === cid))
      .filter((l): l is ActiveLayer => Boolean(l))

    // 无 descriptor/workflow 元数据时做通用 restore，禁止写死实验室 seed id
    const sourceLayerId = bridge.sourceLayerId || catalogId
    const workflowId = bridge.workflowId || ''

    if (existingMembers.length) {
      for (const m of existingMembers) {
        m.runGroupId = groupId
        m.runGroupLocked = options?.createPlaceholders === true
      }
      deps.getRunLayerGroups().push({
        groupId,
        runId,
        title: options?.title || tracked?.name || bridge.title || '工作流产物',
        status: options?.createPlaceholders ? 'computing' : 'ready',
        memberInstanceIds: existingMembers.map((m) => m.instanceId),
        dissolvable: !options?.createPlaceholders,
        sourceLayerId,
        workflowId,
      })
      return
    }

    if (!options?.createPlaceholders) {
      void catalogId
      return
    }

    const created = deps.createRunLayerGroup({
      title: options.title || tracked?.name || bridge.title || '工作流运行',
      targets: tags.map((tag) => ({ name: productTagLabel(tag), productTag: tag })),
      sourceLayerId,
      workflowId,
      memberCatalogIds,
    })
    deps.bindRunIdToGroup(created.groupId, runId)
  }

  // ── 提交 / 取消 / 重试簇（B-2）───────────────────────────────────────────

  // 429 容量限制自动重试（业务 workflow 池）：重试定时器/计数 Map 由 store 持有并传入，
  // 上限与间隔常量随本模块迁移。
  const MAX_WORKFLOW_429_RETRIES = 6
  const WORKFLOW_429_RETRY_DELAY_MS = 3000

  function localSubmitJobId(catalogId: string) {
    return `local-submit-${catalogId}`
  }

  /** 中断指定 catalogId 的活跃工作流（平移时调用）：停止轮询、取消 API（fire-and-forget），但保留旧的 jobLayer */
  function interruptWorkflowForCatalog(catalogId: string) {
    // 清理 429 重试定时器，避免与新的提交冲突
    const retryTimer = deps.workflowRetryTimers.get(catalogId)
    if (retryTimer !== undefined) {
      window.clearTimeout(retryTimer)
      deps.workflowRetryTimers.delete(catalogId)
    }
    // 查找该 catalogId 的活跃 jobId（非终态）
    const activeJobLayer = deps
      .getJobLayers()
      .find(
        (item) =>
          deps
            .getActiveLayers()
            .some((l) => l.catalogId === catalogId && l.jobLayer?.jobId === item.jobId) &&
          !isTerminalStatus(item.status),
      )
    const runJobId = activeJobLayer?.jobId ?? null
    if (runJobId) {
      deps.stopWorkflowPolling(runJobId)
      deps.activeWorkflowCatalogIds.delete(catalogId)
      // fire-and-forget 取消 API 调用，不阻塞新提交
      void cancelWorkflowRun(runJobId).catch(() => {})
    }
  }

  async function runWorkflowForCatalog(
    catalogId: string,
    options: {
      expectedViewportEpoch?: number
      algorithmRequest?: Record<string, unknown>
      weatherRequest?: Record<string, unknown>
      commandLabel?: string
      /** 显式控制是否复用节点/块缓存（缺省不注入，算法默认 reuse_block_cache=True）。
       *  false=全量重算，规避复用旧输出目录带来的时间片污染。 */
      reuseBlockCache?: boolean
    } = {},
  ) {
    if (deps.submittingCatalogIds.has(catalogId)) {
      debugLog('runWorkflow', catalogId, 'skip: already submitting')
      throw new Error('该图层工作流正在提交中，请稍候再试')
    }
    deps.setWorkflowError(null)
    deps.submittingCatalogIds.add(catalogId)
    debugLog('runWorkflow', catalogId, 'start')

    const backendLayerId = deps.resolveBackendLayerId(catalogId)
    const isOutputLayer = backendLayerId !== catalogId
    const runtimeLayerCatalog = deps.getRuntimeLayerCatalog()
    const catalogName = isOutputLayer
      ? (deps.getLayerLibrary().find((l) => l.catalogId === catalogId)?.name ?? catalogId)
      : (runtimeLayerCatalog[catalogId]?.display_name ??
        runtimeLayerCatalog[backendLayerId]?.display_name ??
        getCatalogDisplayName(catalogId))
    const submitJobId = localSubmitJobId(catalogId)
    const submitStartedAt = new Date().toISOString()

    try {
      const hasEditorWeather = Boolean(
        options.weatherRequest &&
        (options.weatherRequest.workflow ||
          (options.weatherRequest as { workflow_id?: string }).workflow_id),
      )
      // 天气图层默认走瓦片管道；编辑器编译出 weather 画布时走 weather_request
      if (deps.isWeatherEngineLayer(backendLayerId) && !hasEditorWeather) {
        deps.activateWeatherTileViewport(catalogId)
        throw new Error(
          `${catalogName} 为天气引擎图层：由瓦片按需加载，已触发当前视口刷新。请查看地图与「工作流状态」中的天气瓦片进度，无需提交分析工作流。`,
        )
      }
      let runtimeCatalogReady = false
      try {
        await deps.ensureRuntimeLayerCatalog()
        runtimeCatalogReady = true
      } catch (error) {
        const canProceedWithoutCatalog = deps.isWeatherEngineLayer(backendLayerId)
        if (!canProceedWithoutCatalog) {
          throw error
        }
        console.warn(
          '[LayersStore] runtime layer catalog unavailable, proceeding with static fallback for',
          catalogId,
          error,
        )
      }

      const hasCanvasDefinition = Boolean(
        (options.algorithmRequest &&
          (options.algorithmRequest.workflow_definition ||
            options.algorithmRequest.workflow_name)) ||
        (options.weatherRequest && options.weatherRequest.workflow),
      )
      const blockedReason =
        runtimeCatalogReady && !isOutputLayer && !hasCanvasDefinition
          ? deps.getCatalogRunBlockReason(backendLayerId)
          : null
      if (blockedReason) {
        throw new Error(blockedReason)
      }
      if (
        !isOutputLayer &&
        !hasCanvasDefinition &&
        !deps.supportsAnalysisWorkflow(backendLayerId)
      ) {
        throw new Error(`${catalogName} 未配置分析工作流引擎，无法提交 /workflow-runs`)
      }

      const supportsMapLayer = deps.supportsMapLayerResult(backendLayerId)
      const requestedOutputs = supportsMapLayer
        ? ['json', 'text', 'table', 'map_layer']
        : ['json', 'text', 'table']
      const requestBBox = deps.getMapBBox()

      // 中断旧位置的活跃工作流（取消 API 调用），但保留旧 mapLayerPayload 使地图资产在新工作流运行期间保持可见
      const previousJobLayer = deps
        .getActiveLayers()
        .find((l) => l.catalogId === catalogId && !l.isAdminBoundary)?.jobLayer

      interruptWorkflowForCatalog(catalogId)

      // 提交一开始就写入 jobLayer，使标题栏/状态面板立即显示「排队」，不依赖天气瓦片路径
      deps.upsertJobLayer(catalogId, {
        jobId: submitJobId,
        catalogId,
        name: catalogName,
        commandType: 'analysis',
        status: 'queued',
        progress: 5,
        createdAt: submitStartedAt,
        updatedAt: new Date().toISOString(),
        message: '正在提交工作流…',
        metrics: [],
        reportSummary: '正在提交工作流…',
        resultUrl: undefined,
        mapLayerPayload: previousJobLayer?.mapLayerPayload,
      })

      debugLog(
        'runWorkflow',
        catalogId,
        'submitting new workflow',
        'bbox',
        requestBBox,
        'backendLayerId',
        backendLayerId,
      )
      const payload = deps.buildWorkflowPayloadForCatalog(
        catalogId,
        catalogName,
        requestedOutputs,
        requestBBox,
        backendLayerId,
        options.algorithmRequest,
        options.weatherRequest,
      )
      // 节点缓存开关：显式指定时注入 algorithm_params.reuse_block_cache，
      // 供 omega 等模块在下次运行决定是否复用旧输出目录（false=全量重算防时间片污染）
      if (options.reuseBlockCache !== undefined) {
        const algoReq = (payload.algorithm_request ?? {}) as Record<string, unknown>
        const params = (algoReq.algorithm_params ?? {}) as Record<string, unknown>
        payload.algorithm_request = {
          ...algoReq,
          algorithm_params: { ...params, reuse_block_cache: options.reuseBlockCache },
        }
      }
      if (options.commandLabel) {
        payload.command_label = options.commandLabel
      }
      const accepted = await submitWorkflow(payload as Parameters<typeof submitWorkflow>[0])
      if (deps.isViewportRefreshStale(options.expectedViewportEpoch)) {
        debugLog('runWorkflow', catalogId, 'discard stale submit after accept', accepted.run_id)
        deps.removeJobLayerById(submitJobId)
        void cancelWorkflowRun(accepted.run_id).catch(() => {})
        return
      }
      debugLog('runWorkflow', catalogId, 'submitted', accepted.run_id)

      deps.removeJobLayerById(submitJobId)
      deps.upsertJobLayer(catalogId, {
        jobId: accepted.run_id,
        catalogId,
        name: catalogName,
        commandType: 'analysis',
        status: 'queued',
        progress: 12,
        createdAt: accepted.created_at,
        updatedAt: accepted.created_at,
        message: accepted.message,
        metrics: [],
        reportSummary: accepted.message,
        resultUrl: undefined,
        // 保留旧 mapLayerPayload，使粒子流/网格填充在新工作流运行期间保持可见
        mapLayerPayload: previousJobLayer?.mapLayerPayload,
      })
      if (catalogId.startsWith('wf-out-')) {
        useWorkflowOutputLayersStore().updateRunStatus(catalogId, accepted.run_id, 'queued')
      }

      deps.activeWorkflowCatalogIds.add(catalogId)
      // 工作流提交成功，清除 429 重试计数
      deps.workflowRetryCounts.delete(catalogId)
      void deps.startPolling(accepted.run_id, catalogId, options.expectedViewportEpoch)
      return accepted.run_id
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : '提交 workflow 失败'
      // 天气瓦片路径：已触发刷新，不算失败作业
      if (/天气引擎图层|瓦片按需加载/.test(errMsg)) {
        deps.setWorkflowError(errMsg)
        throw error
      }
      if (isSubmitTimeoutError(error)) {
        try {
          const activeRuns = await listActiveWorkflowRuns()
          const claimed = claimOrphanWorkflowRun(
            activeRuns.map((run) => ({
              run_id: run.run_id,
              command_label: run.command_label,
              created_at: run.created_at,
              status: run.status,
              layer_id: run.layer_id,
            })),
            {
              commandLabel: options.commandLabel,
              catalogIdHint: backendLayerId,
              submitStartedAt,
            },
          )
          if (claimed?.run_id) {
            deps.removeJobLayerById(submitJobId)
            const reconciledMsg = WORKFLOW_COPY.reconcilingSubmit
            const prevLayer = deps
              .getActiveLayers()
              .find((l) => l.catalogId === catalogId && !l.isAdminBoundary)?.jobLayer
            deps.upsertJobLayer(catalogId, {
              jobId: claimed.run_id,
              catalogId,
              name: catalogName,
              commandType: 'analysis',
              status: 'queued',
              progress: 12,
              createdAt: claimed.created_at ?? submitStartedAt,
              updatedAt: new Date().toISOString(),
              message: reconciledMsg,
              metrics: [],
              reportSummary: reconciledMsg,
              resultUrl: undefined,
              mapLayerPayload: prevLayer?.mapLayerPayload,
            })
            deps.activeWorkflowCatalogIds.add(catalogId)
            deps.workflowRetryCounts.delete(catalogId)
            void deps.startPolling(claimed.run_id, catalogId, options.expectedViewportEpoch)
            return claimed.run_id
          }
        } catch (reconcileError) {
          console.warn('[LayersStore] submit timeout reconcile failed', catalogId, reconcileError)
        }
      }
      if (errMsg.includes('429')) {
        deps.setWorkflowError(WORKFLOW_COPY.capacityWaiting)
        // 429 时创建 queued jobLayer 让用户看到状态指示，并调度自动重试
        deps.upsertJobLayer(catalogId, {
          jobId: submitJobId,
          catalogId,
          name: catalogName,
          commandType: 'analysis',
          status: 'queued',
          progress: 5,
          createdAt: submitStartedAt,
          updatedAt: new Date().toISOString(),
          message: WORKFLOW_COPY.capacityRetrying,
          metrics: [],
          reportSummary: WORKFLOW_COPY.capacityRetrying,
          resultUrl: undefined,
        })
        scheduleWorkflowRetry(catalogId)
      } else {
        const localized = localizeWorkflowErrorMessage(errMsg)
        deps.setWorkflowError(localized)
        deps.upsertJobLayer(catalogId, {
          jobId: submitJobId,
          catalogId,
          name: catalogName,
          commandType: 'analysis',
          status: 'failed',
          progress: 0,
          createdAt: submitStartedAt,
          updatedAt: new Date().toISOString(),
          message: localized,
          metrics: [],
          reportSummary: localized,
          diagnosticNotes: [localized],
          resultUrl: undefined,
        })
      }
      throw error
    } finally {
      deps.submittingCatalogIds.delete(catalogId)
    }
  }

  /** 429 容量限制时调度自动重试，最多重试 MAX_WORKFLOW_429_RETRIES 次 */
  function scheduleWorkflowRetry(catalogId: string) {
    const existingTimer = deps.workflowRetryTimers.get(catalogId)
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer)
    }
    const retryCount = deps.workflowRetryCounts.get(catalogId) ?? 0
    if (retryCount >= MAX_WORKFLOW_429_RETRIES) {
      deps.workflowRetryCounts.delete(catalogId)
      deps.upsertJobLayer(catalogId, {
        jobId: `retry-${catalogId}-${Date.now()}`,
        name: getCatalogDisplayName(catalogId),
        commandType: 'analysis',
        status: 'failed',
        progress: 0,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        message: WORKFLOW_COPY.capacityExhausted,
        metrics: [],
        reportSummary: WORKFLOW_COPY.capacityExhausted,
        resultUrl: undefined,
      })
      return
    }
    deps.workflowRetryCounts.set(catalogId, retryCount + 1)
    const timer = window.setTimeout(() => {
      deps.workflowRetryTimers.delete(catalogId)
      void runWorkflowForCatalog(catalogId).catch((err) => {
        console.warn(`[LayersStore] 429 retry failed for ${catalogId}:`, err)
      })
    }, WORKFLOW_429_RETRY_DELAY_MS)
    deps.workflowRetryTimers.set(catalogId, timer)
  }

  async function cancelWorkflowRunForJob(jobId: string, catalogId: string) {
    try {
      if (deps.isLocalSubmitJobId(jobId)) {
        deps.removeJobLayerById(jobId)
        forgetTrackedWorkflowRun(jobId)
        const layer = deps.getActiveLayers().find((l) => l.catalogId === catalogId)
        if (layer?.runGroupId) {
          const g = deps.getRunLayerGroups().find((x) => x.groupId === layer.runGroupId)
          if (g && (!g.runId || deps.isLocalSubmitJobId(g.runId))) {
            g.status = 'cancelled'
            g.dissolvable = true
            g.message = '已取消提交'
            const activeLayers = deps.getActiveLayers()
            for (const id of [...g.memberInstanceIds]) {
              const m = activeLayers.find((l) => l.instanceId === id)
              if (m && !m.importedRaster?.overlayLayerId) {
                const idx = activeLayers.findIndex((l) => l.instanceId === id)
                if (idx >= 0) activeLayers.splice(idx, 1)
              }
            }
            g.memberInstanceIds = g.memberInstanceIds.filter((id) =>
              deps.getActiveLayers().some((l) => l.instanceId === id),
            )
            if (!g.memberInstanceIds.length) {
              deps.setRunLayerGroups(
                deps.getRunLayerGroups().filter((x) => x.groupId !== g.groupId),
              )
            }
          }
        }
        deps.scheduleWorkspacePersist()
        return
      }
      const run = await cancelWorkflowRun(jobId)
      const existingJobLayer = deps.getJobLayers().find((item) => item.jobId === jobId)
      const jobLayer = await buildJobLayer(run, catalogId, { previousJobLayer: existingJobLayer })
      deps.upsertJobLayer(catalogId, jobLayer)
      deps.stopWorkflowPolling(jobId)
      deps.activeWorkflowCatalogIds.delete(catalogId)
      deps.cleanupUnproducedRunLayers(jobId)
    } catch (error) {
      deps.setWorkflowError(error instanceof Error ? error.message : '取消 workflow 失败')
    }
  }

  async function retryWorkflowRunForJob(jobId: string, catalogId: string) {
    if (deps.submittingCatalogIds.has(catalogId)) return
    // 乐观 ID / 从未真正落库的提交：走重新提交，而不是 /retry
    if (deps.isLocalSubmitJobId(jobId)) {
      deps.removeJobLayerById(jobId)
      forgetTrackedWorkflowRun(jobId)
      return runWorkflowForCatalog(catalogId)
    }
    // 中断旧位置的活跃工作流，允许重试提交新工作流
    interruptWorkflowForCatalog(catalogId)
    deps.setWorkflowError(null)
    deps.submittingCatalogIds.add(catalogId)
    try {
      const accepted = await retryWorkflowRun(jobId)
      const catalogName =
        deps.getRuntimeLayerCatalog()[catalogId]?.display_name ?? getCatalogDisplayName(catalogId)
      deps.upsertJobLayer(catalogId, {
        jobId: accepted.run_id,
        name: catalogName,
        commandType: 'analysis',
        status: 'queued',
        progress: 12,
        createdAt: accepted.created_at,
        updatedAt: accepted.created_at,
        message: accepted.message,
        metrics: [],
        reportSummary: accepted.message,
        resultUrl: undefined,
      })
      deps.activeWorkflowCatalogIds.add(catalogId)
      void deps.startPolling(accepted.run_id, catalogId)
      return accepted.run_id
    } catch (error) {
      deps.setWorkflowError(error instanceof Error ? error.message : '重试 workflow 失败')
      throw error
    } finally {
      deps.submittingCatalogIds.delete(catalogId)
    }
  }

  return {
    restoreActiveWorkflows,
    registerExternalWorkflowRun,
    runWorkflowForCatalog,
    cancelWorkflowRunForJob,
    retryWorkflowRunForJob,
    interruptWorkflowForCatalog,
    scheduleWorkflowRetry,
    rememberTrackedWorkflowRun,
    forgetTrackedWorkflowRun,
    // 内部辅助不导出：resolveRestoredCatalogId / hydrateJobLayerFromEvents /
    //   resolveRestoreWorkflowBridge / ensureRestoredRunGroup
  }
}
