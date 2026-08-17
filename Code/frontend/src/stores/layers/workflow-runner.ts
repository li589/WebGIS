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
import type { BoundingBox, LayerDescriptor, WorkflowEvent } from '../../services/runtime-api'
import { useWorkflowOutputLayersStore } from '../workflow-output-layers'
import { useLogStore } from '../log'
import { buildJobLayer } from './result-adapter'
import { forgetDismissedLayer, isRunDismissed } from './workspace-persist'
import { getCatalogDisplayName, isTerminalStatus } from './catalog-builders'
import { normalizeWorkflowProgress } from './workflow-progress'
import { resolveRestoreWorkflowBridge as resolveRestoreWorkflowBridgeFromCatalog } from './restore-workflow-bridge'
import { claimOrphanWorkflowRun, isSubmitTimeoutError } from '../../utils/workflow-submit-reconcile'
import {
  formatWorkflowValidationError,
  localizeWorkflowErrorMessage,
} from '../../utils/workflow-error-messages'
import { WorkflowValidationError } from '../../services/_http'
import {
  explicitExpectedOutputTags,
  productTagLabel,
  type WorkflowDefLike,
} from '../../utils/workflow-expected-outputs'
import { debugLog as probeDebugLog } from '../../utils/perf-probe'
import { WORKFLOW_COPY } from '../../ui-copy/workflow'
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
  RuntimeLayerLibraryItem,
} from './types'

function debugLog(module: string, ...args: unknown[]) {
  probeDebugLog(`[${performance.now().toFixed(1)}ms] [LayersStore:${module}]`, ...args)
}

/**
 * 反演历史 run 的英文 workflow id / layer_id → 图层目录 id（合并组成员）。
 *
 * 历史 run 的 layer_id 直接落 workflow_id（omega_sf_fenkuai_* 等），
 * catalog 无此条目时会以英文 id 回退显示（占位图层）。此处统一映射到
 * method-*-omega-doy-* 目录成员，使恢复产物并入「风云/SMAP ω 反演」组。
 */
const INVERSION_RUN_CATALOG_MAP: Array<{ pattern: RegExp; catalogId: string }> = [
  { pattern: /omega[-_]sf[-_]fenkuai[-_]?fy/i, catalogId: 'method-fy-omega-doy-dynamic' },
  { pattern: /omega[-_]sf[-_]fenkuai[-_]?smap/i, catalogId: 'method-smap-omega-doy-dynamic' },
  { pattern: /omega[-_]avg[-_]daily[-_]?fy/i, catalogId: 'method-fy-omega-doy-avg' },
  { pattern: /omega[-_]avg[-_]daily[-_]?smap/i, catalogId: 'method-smap-omega-doy-avg' },
]

/** 匹配反演 run（fenkuai 动态链 / avg 逐日链 / omega_pixel）的 layer_id 识别。 */
export const INVERSION_RUN_LAYER_PATTERN =
  /omega[-_]sf[-_]fenkuai|omega[-_]avg[-_]daily|omega_sf_omega_pixel/i

/** 英文反演 workflow/layer id → 目录 id；非反演 id 原样返回。 */
export function resolveInversionCatalogId(layerId: string): string {
  for (const entry of INVERSION_RUN_CATALOG_MAP) {
    if (entry.pattern.test(layerId)) return entry.catalogId
  }
  return layerId
}

/** Safely log to useLogStore; no-ops if Pinia is not active (e.g., in tests) */
function safeLog(type: string, message: string, details?: string, severity?: string) {
  try {
    useLogStore().logOperation(type, message, details, severity as never)
  } catch {
    // Pinia not active — console.error above is sufficient
  }
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

/**
 * WorkflowRunnerDeps — 依赖注入接口。
 *
 * P1-6：按职责分组为 5 个子接口，便于理解依赖范围。
 * 后续迭代计划将 30+ 个细粒度方法封装为 5-8 个高层方法。
 */

/** 轮询器接口：启动/停止/同步工作流运行状态 */
export interface WorkflowPollerDeps {
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
}

/** 状态读取接口：getter 返回 store 响应式状态的当前快照 */
export interface WorkflowStateReaderDeps {
  getActiveLayers: () => ActiveLayer[]
  getJobLayers: () => JobLayerItem[]
  getRunLayerGroups: () => ActiveRunLayerGroup[]
  getRuntimeLayerCatalog: () => Record<string, LayerDescriptor>
  getLayerLibrary: () => RuntimeLayerLibraryItem[]
  getMapBBox: () => BoundingBox | null
  activeWorkflowCatalogIds: Set<string>
  submittingCatalogIds: Set<string>
  workflowRetryTimers: Map<string, number>
  workflowRetryCounts: Map<string, number>
}

/** 状态写入接口：store 写函数注入 */
export interface WorkflowStateWriterDeps {
  setRunLayerGroups: (groups: ActiveRunLayerGroup[]) => void
  upsertJobLayer: (catalogId: string, jobLayer: JobLayerItem) => void
  removeJobLayerById: (jobId: string) => void
  setWorkflowError: (message: string | null) => void
  scheduleWorkspacePersist: () => void
  cleanupUnproducedRunLayers: (runId: string, opts?: { succeeded?: boolean }) => void
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
}

/** 业务判定 / 载荷构建接口 */
export interface WorkflowBusinessDeps {
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
  activateWeatherTileViewport: (catalogId: string) => void
}

/** 快照恢复接口 */
export interface WorkflowSnapshotDeps {
  hydrateWorkspaceFromSnapshot: () => Map<string, string>
  hydrateVectorLayersFromSnapshot: (instanceIdMap: Map<string, string>) => Promise<void>
  reconcileOmegaBlockLayers: () => void
}

export interface WorkflowRunnerDeps
  extends
    WorkflowPollerDeps,
    WorkflowStateReaderDeps,
    WorkflowStateWriterDeps,
    WorkflowBusinessDeps,
    WorkflowSnapshotDeps {}

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
      // 推断 catalogId：优先 hint，其次从 run payload 的 layer_id 取（反演英文 id 归一）
      const inferredCatalogId = resolveInversionCatalogId(catalogIdHint ?? run.layer_id ?? runId)
      const jobLayer = await buildJobLayer(run, inferredCatalogId, {})
      deps.upsertJobLayer(inferredCatalogId, jobLayer)
      if (!isTerminalStatus(jobLayer.status)) {
        deps.activeWorkflowCatalogIds.add(inferredCatalogId)
        void deps.startPolling(runId, inferredCatalogId)
      }
    } catch (err) {
      console.error('[layers] registerExternalWorkflowRun failed:', runId, err)
      safeLog(
        'workflow-error',
        '注册外部工作流运行失败',
        `runId=${runId} err=${String(err)}`,
        'error',
      )
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
      // 英文反演 workflow id（omega_sf_fenkuai_* 等）→ 目录合并组成员
      return resolveInversionCatalogId(layerId)
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
      // bridge 依赖目录 descriptor；与 Dashboard 并行启动时需等目录就绪
      await deps.ensureRuntimeLayerCatalog().catch(() => undefined)

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
        const layerId = String(run.layer_id || '')
        // 仅恢复 omega 反演（fenkuai 动态链 / avg 逐日链）等算法产物 run，
        // 避免无差别拉起所有历史 run
        if (!INVERSION_RUN_LAYER_PATTERN.test(layerId)) continue
        const workflowKey = String(run.command_label || layerId)
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
        // 但本机 tracked 的进行中 run 必须恢复，否则刷新丢失多图层计算组。
        const workflowKey = String(run.command_label || run.layer_id || '')
        const isTrackedActive = tracked.some((t) => t.runId === run.run_id)
        if (workflowKey && succeededByWorkflow.has(workflowKey) && !isTrackedActive) continue
        candidates.push({
          runId: run.run_id,
          catalogIdHint: run.layer_id || undefined,
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
          safeLog(
            'workflow-error',
            '恢复时跳过缺失的工作流运行',
            `runId=${candidate.runId} err=${String(err)}`,
            'warn',
          )
          forgetTrackedWorkflowRun(candidate.runId)
          continue
        }

        // 非终态且同工作流已有成功版本 → 跳过（防止僵尸 running 重建占位组）
        // tracked 进行中 run 例外：刷新后必须续接占位组/轮询。
        if (run.status !== 'succeeded') {
          const workflowKey = String(run.command_label || run.layer_id || '')
          const isTrackedActive = tracked.some((t) => t.runId === candidate.runId)
          if (workflowKey && succeededByWorkflow.has(workflowKey) && !isTrackedActive) {
            forgetTrackedWorkflowRun(candidate.runId)
            continue
          }
        }

        const catalogId = resolveRestoredCatalogId(
          run.layer_id || candidate.catalogIdHint,
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
          const layerId = String(run.layer_id || catalogId)
          const bridge = resolveRestoreWorkflowBridge(layerId, catalogId, trackedItem)
          const hasHydratedGroup = deps.getRunLayerGroups().some((g) => g.runId === run.run_id)
          // 有 bridge / tracked 组 / 已水合组 / wf-run 占位时均重建或补全计算组
          if (
            bridge.workflowId ||
            bridge.sourceLayerId ||
            catalogId.startsWith('wf-run-') ||
            catalogId.startsWith('wf-out-') ||
            Boolean(trackedItem?.groupId) ||
            (trackedItem?.memberCatalogIds?.length ?? 0) > 0 ||
            hasHydratedGroup
          ) {
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
            .then(() => {
              deps.cleanupUnproducedRunLayers(run.run_id, { succeeded: true })
              deps.scheduleWorkspacePersist()
            })
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
      safeLog('workflow-error', '恢复活跃工作流失败', String(err), 'error')
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

  /** 旧 run 恢复兜底占位标签（无 manifest/工作流定义时的兼容行为） */
  const LEGACY_RESTORE_TAGS = ['SM', 'VOD', 'OMEGA']

  /** 从 runtime 图层目录解析工作流定义（descriptor 携带 workflow_definition） */
  function workflowDefinitionForRestore(
    workflowId?: string,
    sourceLayerId?: string,
    catalogId?: string,
  ): WorkflowDefLike | null {
    const catalog = deps.getRuntimeLayerCatalog()
    const keys = [workflowId, sourceLayerId, catalogId].filter((k): k is string => Boolean(k))
    for (const key of keys) {
      const def = catalog[key]?.workflow_definition
      if (def && typeof def === 'object') return def as WorkflowDefLike
    }
    if (workflowId) {
      for (const d of Object.values(catalog)) {
        if (d.workflow_id === workflowId && d.workflow_definition) {
          return d.workflow_definition as WorkflowDefLike
        }
      }
    }
    return null
  }

  function ensureRestoredRunGroup(
    runId: string,
    catalogId: string,
    tracked?: TrackedWorkflowRun,
    options?: { createPlaceholders?: boolean; title?: string },
  ) {
    const bridge = resolveRestoreWorkflowBridge(
      String(tracked?.catalogId || catalogId),
      catalogId,
      tracked,
    )
    const existingGroup = deps.getRunLayerGroups().find((g) => g.runId === runId)
    // 占位成员标签：优先沿用已恢复组/已水合成员的真实标签，
    // 其次按工作流定义 manifest（extra.outputs / main_layers）推导，
    // 均无（旧 run）时回退 SM/VOD/OMEGA 兼容
    const memberTagsFromLayers = () => {
      const ids = existingGroup?.memberInstanceIds ?? []
      const tags = ids
        .map((id) => deps.getActiveLayers().find((l) => l.instanceId === id)?.runGroupProductTag)
        .filter((t): t is string => Boolean(t))
      return tags.length ? Array.from(new Set(tags)) : []
    }
    const defTags = explicitExpectedOutputTags(
      workflowDefinitionForRestore(
        existingGroup?.workflowId || bridge.workflowId,
        existingGroup?.sourceLayerId || bridge.sourceLayerId,
        catalogId,
      ),
    )
    const layerTags = memberTagsFromLayers()
    const tags = layerTags.length ? layerTags : defTags.length ? defTags : LEGACY_RESTORE_TAGS
    const groupId =
      existingGroup?.groupId ||
      tracked?.groupId ||
      `run-group-restored-${runId.replace(/[^a-zA-Z0-9]/g, '').slice(-10)}`
    const memberCatalogIds =
      tracked?.memberCatalogIds?.length === tags.length
        ? tracked.memberCatalogIds
        : tags.map((tag) => `wf-run-${groupId}-${String(tag).toLowerCase()}`)

    // 无 descriptor/workflow 元数据时做通用 restore，禁止写死实验室 seed id
    const sourceLayerId = existingGroup?.sourceLayerId || bridge.sourceLayerId || catalogId
    const workflowId = existingGroup?.workflowId || bridge.workflowId || ''

    /** 渐进/部分水合后补全缺失产品槽（勿因组已存在而直接 return） */
    const fillMissingMembers = (group: ActiveRunLayerGroup) => {
      if (!options?.createPlaceholders && group.status !== 'computing') return
      const activeLayers = deps.getActiveLayers()
      const presentCatalogIds = new Set(
        group.memberInstanceIds
          .map((id) => activeLayers.find((l) => l.instanceId === id)?.catalogId)
          .filter((id): id is string => Boolean(id)),
      )
      // 亦认已挂到同组但未进 memberInstanceIds 的层
      for (const layer of activeLayers) {
        if (layer.runGroupId === group.groupId && layer.catalogId) {
          presentCatalogIds.add(layer.catalogId)
          if (!group.memberInstanceIds.includes(layer.instanceId)) {
            group.memberInstanceIds.push(layer.instanceId)
          }
        }
      }
      const accentDonor = activeLayers.find((l) => l.runGroupId === group.groupId)
      const maxOrder = activeLayers.reduce((max, l) => Math.max(max, l.order), -1)
      let added = 0
      tags.forEach((tag, i) => {
        const cid = memberCatalogIds[i] || `wf-run-${group.groupId}-${tag.toLowerCase()}`
        if (presentCatalogIds.has(cid)) return
        const already = activeLayers.find((l) => l.catalogId === cid)
        if (already) {
          already.runGroupId = group.groupId
          already.runGroupProductTag = already.runGroupProductTag || tag
          if (options?.createPlaceholders || group.status === 'computing') {
            already.runGroupLocked = !already.importedRaster?.overlayLayerId
          }
          if (!group.memberInstanceIds.includes(already.instanceId)) {
            group.memberInstanceIds.push(already.instanceId)
          }
          return
        }
        const layer: ActiveLayer = {
          instanceId: crypto.randomUUID(),
          catalogId: cid,
          name: productTagLabel(tag),
          visible: true,
          opacity: 1,
          order: maxOrder + tags.length - i + added,
          isAdminBoundary: false,
          dataState: 'catalog',
          accentColor: accentDonor?.accentColor,
          accentGlow: accentDonor?.accentGlow,
          chipTone: accentDonor?.chipTone,
          runGroupId: group.groupId,
          runGroupProductTag: tag,
          runGroupLocked: true,
        }
        activeLayers.push(layer)
        group.memberInstanceIds.push(layer.instanceId)
        added += 1
      })
      if (options?.createPlaceholders) {
        group.status = 'computing'
        group.dissolvable = false
      }
      if (!group.sourceLayerId) group.sourceLayerId = sourceLayerId
      if (!group.workflowId) group.workflowId = workflowId
      if (options?.title) group.title = options.title
    }

    if (existingGroup) {
      fillMissingMembers(existingGroup)
      return
    }

    const existingMembers = memberCatalogIds
      .map((cid) => deps.getActiveLayers().find((l) => l.catalogId === cid))
      .filter((l): l is ActiveLayer => Boolean(l))

    // 快照水合可能用不同 catalogId，但已带 runGroupId / tracked.groupId
    const hydratedByGroupId = tracked?.groupId
      ? deps.getActiveLayers().filter((l) => l.runGroupId === tracked.groupId)
      : []

    const seedMembers = existingMembers.length ? existingMembers : hydratedByGroupId

    if (seedMembers.length) {
      for (const m of seedMembers) {
        m.runGroupId = groupId
        if (options?.createPlaceholders && !m.importedRaster?.overlayLayerId) {
          m.runGroupLocked = true
        }
      }
      const group: ActiveRunLayerGroup = {
        groupId,
        runId,
        title: options?.title || tracked?.name || bridge.title || '工作流产物',
        status: options?.createPlaceholders ? 'computing' : 'ready',
        memberInstanceIds: seedMembers.map((m) => m.instanceId),
        dissolvable: !options?.createPlaceholders,
        sourceLayerId,
        workflowId,
      }
      deps.getRunLayerGroups().push(group)
      fillMissingMembers(group)
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
      /** Top-level time_range (ISO start_at/end_at); required by python_provider job_request. */
      timeRange?: Record<string, unknown>
      /** Optional resource profile override (e.g. heavy for omega_sf). */
      resourceProfile?: 'realtime' | 'standard' | 'heavy' | 'batch'
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
        safeLog(
          'workflow-error',
          '运行时图层目录不可用，使用静态回退',
          `catalogId=${catalogId} err=${String(error)}`,
          'warn',
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

      const { buildExpectedCoverageForSubmit } = await import('../../utils/job-layer-coverage')

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
      if (options.timeRange && typeof options.timeRange === 'object') {
        payload.time_range = options.timeRange
      }
      const algoParams =
        options.algorithmRequest && typeof options.algorithmRequest.algorithm_params === 'object'
          ? (options.algorithmRequest.algorithm_params as Record<string, unknown>)
          : null
      const catalogNative =
        (runtimeLayerCatalog[backendLayerId] as { native_step?: string } | undefined)
          ?.native_step ??
        (runtimeLayerCatalog[catalogId] as { native_step?: string } | undefined)?.native_step ??
        null
      const coverage = buildExpectedCoverageForSubmit({
        timeRange: options.timeRange,
        payloadTimeRange: payload.time_range as Record<string, unknown> | undefined,
        algorithmParams: algoParams,
        catalogNativeStep: catalogNative,
        workflowId:
          (typeof options.algorithmRequest?.workflow_entry_name === 'string'
            ? options.algorithmRequest.workflow_entry_name
            : null) ||
          (typeof options.algorithmRequest?.workflow_name === 'string'
            ? options.algorithmRequest.workflow_name
            : null) ||
          catalogId,
        previous: previousJobLayer,
      })
      // 提交一开始就写入 jobLayer，使标题栏/状态面板立即显示「排队」
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
        expectedTimeRange: coverage.expectedTimeRange,
        expectedNativeStep: coverage.expectedNativeStep,
        inFlightTimeKeys: [],
        failedTimeKeys: [],
      })
      if (options.resourceProfile) {
        payload.resource_profile = options.resourceProfile
      }
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
        expectedTimeRange: coverage.expectedTimeRange,
        expectedNativeStep: coverage.expectedNativeStep,
        inFlightTimeKeys: [],
        failedTimeKeys: [],
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
          safeLog(
            'workflow-error',
            '提交超时对账失败',
            `catalogId=${catalogId} err=${String(reconcileError)}`,
            'warn',
          )
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
        const formatted =
          error instanceof WorkflowValidationError
            ? formatWorkflowValidationError(error.message, error.issues)
            : {
                summary: localizeWorkflowErrorMessage(errMsg),
                notes: [localizeWorkflowErrorMessage(errMsg)],
              }
        deps.setWorkflowError(formatted.summary)
        deps.upsertJobLayer(catalogId, {
          jobId: submitJobId,
          catalogId,
          name: catalogName,
          commandType: 'analysis',
          status: 'failed',
          progress: 0,
          createdAt: submitStartedAt,
          updatedAt: new Date().toISOString(),
          message: formatted.summary,
          metrics: [],
          reportSummary: formatted.summary,
          diagnosticNotes: formatted.notes,
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
        safeLog(
          'workflow-error',
          '工作流 429 重试失败',
          `catalogId=${catalogId} err=${String(err)}`,
          'warn',
        )
      })
    }, WORKFLOW_429_RETRY_DELAY_MS)
    deps.workflowRetryTimers.set(catalogId, timer)
  }

  /** 清理所有待处理的 429 重试定时器，防止组件卸载后已取消的工作流被重新提交 */
  function cleanupAllRetryTimers() {
    for (const timer of deps.workflowRetryTimers.values()) {
      window.clearTimeout(timer)
    }
    deps.workflowRetryTimers.clear()
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
    cleanupAllRetryTimers,
    rememberTrackedWorkflowRun,
    forgetTrackedWorkflowRun,
    // 内部辅助不导出：resolveRestoredCatalogId / hydrateJobLayerFromEvents /
    //   resolveRestoreWorkflowBridge / ensureRestoredRunGroup
  }
}
