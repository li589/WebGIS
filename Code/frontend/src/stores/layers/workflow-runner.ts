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
 * 除 X2 变体偏好（workflowVariantPreference）外不持有 reactive 状态——store 状态经
 * deps getter / 写回调注入；runtime-api / 纯函数模块直接 import（无 store 依赖）。
 */
import { ref } from 'vue'

import {
  cancelWorkflowRun,
  getWorkflowEvents,
  getWorkflowRun,
  listActiveWorkflowRuns,
  listRecentSucceededRuns,
  retryWorkflowRun,
  submitOverlayAssetWorkflow,
  submitWorkflow,
} from '../../services/runtime-api'
import type { BoundingBox, LayerDescriptor, WorkflowEvent } from '../../services/runtime-api'
import { useWorkflowOutputLayersStore } from '../workflow-output-layers'
import { useLogStore } from '../log'
import { readScopedItem, writeScopedItem } from '../../services/user-local-isolation'
import {
  fetchDataInputPolicies,
  INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST,
} from '../../services/data-input-policies-api'
import { fetchLayerDataCoverage } from '../../services/layer-coverage-api'
import {
  decideSourceRoute,
  descriptorEligibleForSourceRoute,
  inferDefaultVariant,
  resolveSourceRoutePolicyMode,
} from '../../utils/source-route-policy'
import { buildJobLayer } from './result-adapter'
import { forgetDismissedLayer, isRunDismissed } from './workspace-persist'
import { suppressWorkspaceSyncPush } from './workspace-sync'
import { getCatalogDisplayName, isTerminalStatus } from './catalog-builders'
import { resolveJobOverallProgress } from './workflow-progress'
import { resolveRestoreWorkflowBridge as resolveRestoreWorkflowBridgeFromCatalog } from './restore-workflow-bridge'
import { claimOrphanWorkflowRun, isSubmitTimeoutError } from '../../utils/workflow-submit-reconcile'
import {
  formatWorkflowValidationError,
  localizeWorkflowErrorMessage,
} from '../../utils/workflow-error-messages'
import { WorkflowValidationError } from '../../services/_http'
import {
  explicitExpectedOutputTags,
  expectedOutputTargets,
  groupTitleFromDefinition,
  productTagLabel,
  type WorkflowDefLike,
} from '../../utils/workflow-expected-outputs'
import { debugLog as probeDebugLog } from '../../utils/perf-probe'
import { WORKFLOW_COPY } from '../../ui-copy/workflow'
import { INVERSION_RUN_LAYER_PATTERN, resolveInversionCatalogId } from './inversion-catalog'
import {
  extractWorkflowDefinitionName,
  extractWorkflowEntryId,
  isTechnicalRunTitle,
  resolveRunGroupTitle,
  resolveWorkflowRunDisplayName,
  tryWorkflowSummaries,
} from '../../utils/workflow-run-display-name'
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
  RuntimeLayerLibraryItem,
} from './types'

export {
  INVERSION_RUN_LAYER_PATTERN,
  isEnglishInversionCatalogId,
  resolveInversionCatalogId,
  sanitizeRunGroupTitle,
} from './inversion-catalog'

function debugLog(module: string, ...args: unknown[]) {
  probeDebugLog(`[${performance.now().toFixed(1)}ms] [LayersStore:${module}]`, ...args)
}

function resolveSubmitWorkflowDisplayName(
  catalogName: string,
  options: {
    algorithmRequest?: Record<string, unknown>
    commandLabel?: string
  },
): string {
  const summaries = tryWorkflowSummaries()
  const workflowId = extractWorkflowEntryId(options.algorithmRequest, options.commandLabel)
  return resolveWorkflowRunDisplayName({
    workflowId,
    commandLabel: options.commandLabel,
    catalogName,
    definitionName: extractWorkflowDefinitionName(options.algorithmRequest),
    summaries,
    fallback: '工作流运行',
  })
}

/**
 * 分析提交缺省 time_range 时，从主界面时间轴补齐（避免 fy_daily 等模块
 * 收到 time_range=None 后炸成 NoneType.start）。
 */
async function resolveDefaultTimeRangeFromTimeline(options: {
  supportsTime: boolean
  nativeStep: string | null | undefined
  granularity?: string | null
}): Promise<{ start_at: string; end_at: string; granularity: string } | null> {
  if (!options.supportsTime) return null
  try {
    const { useUiStore } = await import('../ui')
    const { buildTimeKey, buildTimeRangeFromKey } = await import('./online-temporal-orchestrator')
    const ui = useUiStore()
    const granRaw = options.granularity || ui.activeTimeGranularity || 'day'
    const gran =
      granRaw === 'hour' ||
      granRaw === 'day' ||
      granRaw === 'month' ||
      granRaw === 'year' ||
      granRaw === 'static'
        ? granRaw
        : 'day'
    if (gran === 'static') return null
    const nativeStep = options.nativeStep || (gran === 'hour' ? '1h' : '1d')
    const timeKey = buildTimeKey(ui.currentDate, ui.currentHour, gran)
    return buildTimeRangeFromKey(timeKey, nativeStep, gran)
  } catch {
    return null
  }
}

/** 从 runtime descriptor 取 native_step（含 online_temporal 嵌套）。 */
function resolveCatalogNativeStep(
  descriptor: Record<string, unknown> | null | undefined,
): string | null {
  if (!descriptor) return null
  const top = descriptor.native_step
  if (typeof top === 'string' && top.trim()) return top.trim()
  const ot = descriptor.online_temporal
  if (ot && typeof ot === 'object') {
    const nested = (ot as { native_step?: unknown }).native_step
    if (typeof nested === 'string' && nested.trim()) return nested.trim()
  }
  return null
}

interface WorkflowVariantLike {
  workflow_id?: string
  label?: string | null
}

interface WorkflowVariantsHost {
  workflow_variants?: Record<string, WorkflowVariantLike> | null
}

/**
 * X2 变体解析：按 workflowVariant 从 descriptor.workflow_variants 取种子 id，
 * 注入 algorithm_request.workflow_entry_name（后端提交边界优先级最高的 workflow 键）。
 *
 * - variant 未指定或 descriptor 无变体声明 → 原样返回 algorithmRequest（默认变体语义）；
 * - 显式 algorithmRequest.workflow_entry_name / workflow_name 已存在时不覆盖
 *   （画布/编辑器提交优先）；
 * - 变体键声明缺失 → 记 warning 并回退默认（不阻断提交）。
 */
function resolveVariantAlgorithmRequest(
  runtimeLayerCatalog: Record<string, LayerDescriptor | undefined>,
  backendLayerId: string,
  workflowVariant: 'online' | 'local' | undefined,
  algorithmRequest: Record<string, unknown> | undefined,
  catalogName: string,
): Record<string, unknown> | undefined {
  if (!workflowVariant) return algorithmRequest
  const variants = (runtimeLayerCatalog[backendLayerId] as WorkflowVariantsHost | undefined)
    ?.workflow_variants
  const variant = variants?.[workflowVariant]
  if (!variant?.workflow_id) {
    debugLog(
      'runWorkflow',
      catalogName,
      `variant "${workflowVariant}" not declared, falling back to default workflow`,
    )
    return algorithmRequest
  }
  const hasExplicitWorkflow =
    algorithmRequest &&
    (typeof algorithmRequest.workflow_entry_name === 'string' ||
      typeof algorithmRequest.workflow_name === 'string')
  if (hasExplicitWorkflow) return algorithmRequest
  return {
    ...(algorithmRequest ?? {}),
    workflow_entry_name: variant.workflow_id,
  }
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
    const raw = readScopedItem(TRACKED_RUNS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    const runs = parsed.filter(
      (item): item is TrackedWorkflowRun =>
        !!item && typeof item.runId === 'string' && typeof item.catalogId === 'string',
    )
    // 一次性迁移：旧版本存的英文 catalogId（omega-sf-fenkuai 等）收敛到
    // method-* 目录成员，并回写 localStorage（安审 2026-08-21）
    const migrated = runs.map((item) =>
      item.catalogId !== resolveInversionCatalogId(item.catalogId)
        ? { ...item, catalogId: resolveInversionCatalogId(item.catalogId) }
        : item,
    )
    if (migrated.some((item, i) => item.catalogId !== runs[i].catalogId)) {
      writeScopedItem(TRACKED_RUNS_STORAGE_KEY, JSON.stringify(migrated))
    }
    return migrated
  } catch {
    return []
  }
}

export function saveTrackedWorkflowRuns(runs: TrackedWorkflowRun[]) {
  if (typeof window === 'undefined') return
  try {
    // Keep recent 40 entries
    writeScopedItem(TRACKED_RUNS_STORAGE_KEY, JSON.stringify(runs.slice(0, 40)))
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
  upsertJobLayer: (
    catalogId: string,
    jobLayer: JobLayerItem,
    opts?: { skipActiveLayerSync?: boolean },
  ) => void
  removeJobLayerById: (jobId: string) => void
  setWorkflowError: (message: string | null) => void
  scheduleWorkspacePersist: () => void
  /** 立即落盘；restore 路径应传 { sync: false } 避免冲远端 */
  flushWorkspacePersistNow: (opts?: { sync?: boolean }) => void
  cleanupUnproducedRunLayers: (runId: string, opts?: { succeeded?: boolean }) => void
  /** 丢弃探测失败的 run 组 UI（不删后端 overlay） */
  discardRunGroupUi?: (runId: string) => void
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
  /** 产物绑定后把时间轴对齐到该产物的时间块（需求1 批次2，可选注入） */
  alignTimelineToProduct?: (timeLabel: string) => void
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
  /** overlay 静态/时间序列图层（PNG 资产直显，走 /overlay-asset-workflows）。 */
  isOverlayDisplayOnlyLayer: (catalogId: string) => boolean
  supportsMapLayerResult: (catalogId: string) => boolean
  /**
   * 源路由 allow_with_confirm：本地缺数需用户确认改走在线时回调（展示 Banner）。
   * 未注入则 runner 抛错提示。
   */
  onSourceRouteConfirmOnline?: (payload: {
    catalogId: string
    timeKey: string | null
    message: string
  }) => void
  /** 源路由静默改走在线时的短提示（可选） */
  onSourceRouteSilentOnline?: (payload: {
    catalogId: string
    timeKey: string | null
    message: string
  }) => void
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

export type WorkflowVariantKey = 'online' | 'local'

export function createWorkflowRunner(deps: WorkflowRunnerDeps) {
  /**
   * X2 变体偏好（catalogId → 变体键）。分析框切换「数据来源」后写入；
   * runWorkflowForCatalog 未显式传 workflowVariant 时按此解析。
   * pinned=true：用户手动钉死，跳过源路由自动策略。
   */
  const workflowVariantPreference = ref<Record<string, WorkflowVariantKey>>({})
  const workflowVariantPinned = ref<Record<string, boolean>>({})

  function getWorkflowVariantPreference(catalogId: string): WorkflowVariantKey | undefined {
    return workflowVariantPreference.value[catalogId]
  }

  function isWorkflowVariantPinned(catalogId: string): boolean {
    return Boolean(workflowVariantPinned.value[catalogId])
  }

  function setWorkflowVariantPreference(
    catalogId: string,
    variant: WorkflowVariantKey | null,
    opts?: { pinned?: boolean },
  ): void {
    if (variant === null) {
      delete workflowVariantPreference.value[catalogId]
      delete workflowVariantPinned.value[catalogId]
      return
    }
    workflowVariantPreference.value[catalogId] = variant
    if (opts?.pinned === true) {
      workflowVariantPinned.value[catalogId] = true
    } else if (opts?.pinned === false) {
      delete workflowVariantPinned.value[catalogId]
    }
  }

  /** InfoPanel「自动」：清除钉死与偏好，回落源路由策略 */
  function clearWorkflowVariantPin(catalogId: string): void {
    delete workflowVariantPreference.value[catalogId]
    delete workflowVariantPinned.value[catalogId]
  }

  function rememberTrackedWorkflowRun(catalogId: string, jobLayer: JobLayerItem) {
    // 乐观提交 ID 不是后端真 run，禁止写入恢复列表（否则会 404 / 误点重试）
    if (deps.isLocalSubmitJobId(jobLayer.jobId)) return
    // 刷新后只需续接「进行中」：成功/失败/取消从跟踪表剔除，避免挤占名额
    // 且与状态指示器「运行中必须保留、已成功无所谓」对齐。
    if (isTerminalStatus(jobLayer.status)) {
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
  async function registerExternalWorkflowRun(
    runId: string,
    catalogIdHint?: string,
    opts?: { skipActiveLayerSync?: boolean },
  ) {
    // 已在跟踪则跳过
    if (deps.isPolling(runId)) return
    const existing = deps.getJobLayers().find((item) => item.jobId === runId)
    if (existing && !isTerminalStatus(existing.status)) return

    try {
      const run = await getWorkflowRun(runId)
      // 推断 catalogId：优先 hint，其次从 run payload 的 layer_id 取（反演英文 id 归一）
      const inferredCatalogId = resolveInversionCatalogId(catalogIdHint ?? run.layer_id ?? runId)
      const jobLayer = await buildJobLayer(run, inferredCatalogId, {})
      if (opts?.skipActiveLayerSync) {
        jobLayer.isAnalysisToolRun = true
      }
      deps.upsertJobLayer(inferredCatalogId, jobLayer, {
        skipActiveLayerSync: opts?.skipActiveLayerSync,
      })
      if (!isTerminalStatus(jobLayer.status)) {
        // GIS 分析工具不占用 catalog「主工作流活跃」集合，避免侧栏/组状态被污染
        if (!opts?.skipActiveLayerSync) {
          deps.activeWorkflowCatalogIds.add(inferredCatalogId)
        }
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
    // 旧版本 tracked 里可能存了裸英文 id（omega-sf-fenkuai 等），统一过
    // 映射收敛到 method-* 目录成员，避免英文占位图层复活（安审 2026-08-21）
    if (tracked?.catalogId) return resolveInversionCatalogId(tracked.catalogId)
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
   * 核对快照中残留的 run 组：终态更新状态；缺失 run 且无产物则清占位；
   * 避免跨端同步后侧栏「运行中」永久悬挂而指示器为空。
   */
  async function reconcileOrphanRunGroup(
    runId: string,
    opts?: { forceMissing?: boolean },
  ): Promise<void> {
    const groups = deps.getRunLayerGroups().filter((g) => String(g.runId || '') === runId)
    if (!groups.length) return

    const removeGroupAndPlaceholders = (g: ActiveRunLayerGroup) => {
      deps.setRunLayerGroups(deps.getRunLayerGroups().filter((x) => x.groupId !== g.groupId))
      const activeLayers = deps.getActiveLayers()
      for (let i = activeLayers.length - 1; i >= 0; i--) {
        const layer = activeLayers[i]!
        if (layer.runGroupId !== g.groupId) continue
        if (
          layer.importedRaster?.overlayLayerId ||
          layer.importedVector?.backendLayerId ||
          layer.dataState === 'real'
        ) {
          layer.runGroupId = undefined
          layer.runGroupProductTag = undefined
          layer.runGroupLocked = false
          continue
        }
        activeLayers.splice(i, 1)
      }
    }

    const demoteGroup = (g: ActiveRunLayerGroup, status: ActiveRunLayerGroup['status']) => {
      const target = deps.getRunLayerGroups().find((x) => x.groupId === g.groupId)
      if (!target) return
      target.status = status
      if (status === 'ready') {
        target.dissolvable = true
        target.progress = typeof target.progress === 'number' ? target.progress : 1
        for (const m of deps.getActiveLayers().filter((l) => l.runGroupId === g.groupId)) {
          m.runGroupLocked = false
        }
      }
    }

    const hasProductFor = (g: ActiveRunLayerGroup) =>
      deps.getActiveLayers().some(
        (l) =>
          l.runGroupId === g.groupId &&
          (Boolean(l.importedRaster?.overlayLayerId) ||
            Boolean(l.importedVector?.backendLayerId) ||
            l.dataState === 'real'),
      )

    if (opts?.forceMissing) {
      for (const g of groups) {
        if (!hasProductFor(g) && g.status === 'computing') removeGroupAndPlaceholders(g)
        else demoteGroup(g, 'ready')
      }
      return
    }

    try {
      const run = await getWorkflowRun(runId)
      const st = String(run.status)
      for (const g of groups) {
        if (isTerminalStatus(st)) {
          if (st === 'succeeded') {
            demoteGroup(g, 'ready')
          } else if (st === 'failed') {
            demoteGroup(g, 'failed')
            if (!hasProductFor(g)) removeGroupAndPlaceholders(g)
          } else if (st === 'cancelled') {
            demoteGroup(g, 'cancelled')
            if (!hasProductFor(g)) removeGroupAndPlaceholders(g)
          } else {
            demoteGroup(g, 'ready')
          }
        } else {
          const catalogId = resolveRestoredCatalogId(run.layer_id || undefined, run.run_id)
          const catalogDisplayName =
            deps.getRuntimeLayerCatalog()[catalogId]?.display_name ??
            getCatalogDisplayName(catalogId)
          let jobLayer = await buildJobLayer(run, catalogDisplayName, {})
          jobLayer = await hydrateJobLayerFromEvents(jobLayer)
          deps.upsertJobLayer(catalogId, jobLayer)
          demoteGroup(g, 'computing')
          deps.activeWorkflowCatalogIds.add(catalogId)
          void deps.startPolling(run.run_id, catalogId)
        }
      }
    } catch {
      for (const g of groups) {
        if (!hasProductFor(g) && g.status === 'computing') removeGroupAndPlaceholders(g)
        else demoteGroup(g, 'ready')
      }
    }
  }

  /**
   * 从后端 + localStorage 恢复工作流列表。在页面加载 / 刷新后调用，
   * 确保跨会话与长批任务的进度条/节点进度不会丢失。
   */
  async function restoreActiveWorkflows() {
    // 整段恢复禁止推 /workspace：跨端同账号时残缺内存态会冲掉另一端完整工作区
    suppressWorkspaceSyncPush(true)
    try {
      // 先恢复本机已产出图层/组，再合并后端活跃 run
      const instanceIdMap = deps.hydrateWorkspaceFromSnapshot()
      await deps.hydrateVectorLayersFromSnapshot(instanceIdMap)
      deps.reconcileOmegaBlockLayers()

      // 快照恢复的 computing 组：立即与当前后端核对，清掉跨环境同步的僵尸「运行中」
      const computingRunIds = [
        ...new Set(
          deps
            .getRunLayerGroups()
            .filter((g) => g.status === 'computing' && g.runId)
            .map((g) => String(g.runId)),
        ),
      ]
      for (const runId of computingRunIds) {
        await reconcileOrphanRunGroup(runId)
      }

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

      // 先收集最近成功的 omega 反演 run（列表按创建时间倒序）。
      // 关键键：按「映射后的 method-* 目录 id」去重，每目录只保留最新一条。
      // 旧实现按 command_label 去重——每次时间窗不同就会灌入多组历史 run，
      // 添加 SMAP/风云 ω 后 TOC/库被 omega_sf_fenkuai_* 历史组淹没（2026-08-30）。
      const recentSucceeded = await listRecentSucceededRuns(20).catch(() => [])
      const succeededByWorkflow = new Set<string>()
      const seenInversionCatalogs = new Set<string>()
      for (const run of recentSucceeded) {
        const layerId = String(run.layer_id || '')
        // 仅恢复 omega 反演（fenkuai 动态链 / avg 逐日链）等算法产物 run，
        // 避免无差别拉起所有历史 run
        if (!INVERSION_RUN_LAYER_PATTERN.test(layerId)) continue
        const workflowKey = String(run.command_label || layerId)
        succeededByWorkflow.add(workflowKey)
        const mappedCatalog = resolveInversionCatalogId(layerId)
        if (seenInversionCatalogs.has(mappedCatalog)) continue
        seenInversionCatalogs.add(mappedCatalog)
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
        // 后端 active_only 的非终态 run 一律进入候选——状态指示器在刷新后
        // 必须能续接「运行中/排队」。同工作流已有成功产物时的「僵尸 running」
        // 防护下移到建组阶段，不再在此丢弃 jobLayer/轮询。
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

      // 清掉残留的乐观提交占位（排队幽灵）。
      // 保留终态 failed：否则 restore 会抹掉 local-submit 失败行，只剩
      // workflowError 横幅 → 分析框有 500 文案、状态指示器却无「失败」徽标。
      for (const job of [...deps.getJobLayers()]) {
        if (deps.isLocalSubmitJobId(job.jobId) && !isTerminalStatus(job.status)) {
          deps.removeJobLayerById(job.jobId)
        }
      }

      for (const candidate of candidates) {
        if (seen.has(candidate.runId)) continue
        seen.add(candidate.runId)
        if (candidate.autoDiscovered) {
          // 无对应 method-* 活动层时不自动灌入历史反演 run——否则 TOC/库会被
          // 历史组淹没；添加图层走 autoAttachProductsForNewLayer（仅最新/指定时刻）。
          const mapped = resolveInversionCatalogId(candidate.catalogIdHint || '')
          const hasActive = deps
            .getActiveLayers()
            .some(
              (l) => l.catalogId === mapped || resolveInversionCatalogId(l.catalogId) === mapped,
            )
          if (!hasActive) continue
          // 该目录已有计算组（快照/autoAttach 已建）→ 不再灌入第二条历史 run
          const alreadyGrouped = deps.getRunLayerGroups().some((g) => {
            const src = String(g.sourceLayerId || '')
            return (
              src === mapped ||
              resolveInversionCatalogId(src) === mapped ||
              resolveInversionCatalogId(String(g.workflowId || '')) === mapped
            )
          })
          if (alreadyGrouped) continue
        }
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
          // 跨端同步留下的 computing 组：本机查不到 run 时不得继续显示「运行中」
          await reconcileOrphanRunGroup(candidate.runId, { forceMissing: true })
          continue
        }

        // 终态：清跟踪表。成功产物仅 autoDiscover 路径进指示器/绑层；
        // 刷新后指示器优先保证「运行中」，已成功不强制回填。
        if (isTerminalStatus(String(run.status))) {
          forgetTrackedWorkflowRun(candidate.runId)
          if (!(run.status === 'succeeded' && candidate.autoDiscovered)) {
            continue
          }
        }

        const catalogId = resolveRestoredCatalogId(
          run.layer_id || candidate.catalogIdHint,
          run.run_id,
        )
        const catalogDisplayName =
          deps.getRuntimeLayerCatalog()[catalogId]?.display_name ?? getCatalogDisplayName(catalogId)
        let jobLayer = await buildJobLayer(run, catalogDisplayName, {
          previousJobLayer: existing,
        })
        jobLayer = await hydrateJobLayerFromEvents(jobLayer)
        // Prefer hydrated / dispatch-weighted progress over bare server snapshot
        if (existing) {
          const nodeProgress = jobLayer.nodeProgress?.length
            ? jobLayer.nodeProgress
            : existing.nodeProgress
          jobLayer = {
            ...jobLayer,
            progress: resolveJobOverallProgress({
              current: existing.progress,
              snapshot: jobLayer.progress,
              nodeProgress,
            }),
            nodeProgress,
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
          const workflowKey = String(run.command_label || run.layer_id || '')
          // 僵尸防护：同工作流已有成功产物且非本机 tracked → 仍写入指示器/轮询，
          // 但不重建 TOC 占位组（避免陈旧中间块淹没侧栏）。
          const skipZombieGroup =
            Boolean(workflowKey) && succeededByWorkflow.has(workflowKey) && !trackedItem
          // 有 bridge / tracked 组 / 已水合组 / wf-run 占位时均重建或补全计算组
          if (
            !skipZombieGroup &&
            (bridge.workflowId ||
              bridge.sourceLayerId ||
              catalogId.startsWith('wf-run-') ||
              catalogId.startsWith('wf-out-') ||
              Boolean(trackedItem?.groupId) ||
              (trackedItem?.memberCatalogIds?.length ?? 0) > 0 ||
              hasHydratedGroup)
          ) {
            ensureRestoredRunGroup(run.run_id, catalogId, trackedItem, {
              createPlaceholders: true,
              // bridge.title 为死分支（resolveRestoreWorkflowBridge 从不返回
              // title），已移除；组名最终由 configuredGroupTitle 中文配置
              // 纠偏（2026-08-24 P3-B）
              title: jobLayer.name || '工作流运行',
            })
          }
          deps.activeWorkflowCatalogIds.add(catalogId)
          void deps.startPolling(run.run_id, catalogId)
        } else if (
          jobLayer.status === 'succeeded' &&
          (candidate.autoDiscovered || !isRunDismissed(run.run_id))
        ) {
          // 必须建占位组成员（createPlaceholders），否则 attach 会落成
          // catalogId=imported-omega_sf_fenkuai_* 的游离层，侧栏/库视图
          // 泄漏英文技术名（2026-08-30 图层库污染）。
          ensureRestoredRunGroup(
            run.run_id,
            catalogId,
            tracked.find((t) => t.runId === run.run_id),
            { createPlaceholders: true, source: 'restore' },
          )
          // 自动发现的 run 强制绑定数据（绕过用户此前可能点过的"移除"标记），
          // 保证"有图层就有内容"；用户主动移除的 tracked run 仍保持被移除状态。
          void deps
            .attachAlgorithmProductOverlays(run.result_refs, catalogId, run.run_id, {
              forceBind: Boolean(candidate.autoDiscovered),
            })
            .then((boundCount) => {
              if (boundCount > 0) {
                deps.cleanupUnproducedRunLayers(run.run_id, { succeeded: true })
                deps.flushWorkspacePersistNow({ sync: false })
              }
            })
        }
      }

      // 快照中有、但本机 tracked/active 未列入的 run 组：
      // 旧逻辑会直接删组+图层。跨设备同账号时 tracked 表不同源，误删后
      // scheduleWorkspacePersist 会把残缺快照推到 /workspace，冲掉其它端的工作区。
      // 改为向后端核对：终态则更新组状态并保留产物层；仅清除无产物的僵尸占位。
      const restoredRunIds = new Set(candidates.map((c) => c.runId))
      const orphanGroups = deps
        .getRunLayerGroups()
        .filter((g) => Boolean(g.runId) && !restoredRunIds.has(String(g.runId)))
      for (const g of orphanGroups) {
        await reconcileOrphanRunGroup(String(g.runId || ''))
      }
      // 恢复末再 scrub：剔除误建的英文反演游离层 / 纠偏组标题（attach 竞态兜底）
      deps.reconcileOmegaBlockLayers()
      deps.flushWorkspacePersistNow({ sync: false })
    } catch (err) {
      console.error('[layers] restoreActiveWorkflows failed:', err)
      safeLog('workflow-error', '恢复活跃工作流失败', String(err), 'error')
    } finally {
      suppressWorkspaceSyncPush(false)
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

  /** 旧 run 恢复兜底占位标签——LEGACY 三件套已退役（2026-08-24，交付前清理） */

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
    options?: {
      createPlaceholders?: boolean
      title?: string
      /** 调用来源：'submit' 为提交即建组（新种子/画布流水线），'restore' 为旧 run 恢复 2026-08-23 */
      source?: 'submit' | 'restore'
    },
  ) {
    const bridge = resolveRestoreWorkflowBridge(
      String(tracked?.catalogId || catalogId),
      catalogId,
      tracked,
    )
    let existingGroup = deps.getRunLayerGroups().find((g) => g.runId === runId)
    // 画布/编辑器在 submit 前已建 computing 组（runId 尚空）——提交路径须接管，
    // 禁止再建第二组导致双 runId / attach 绑错组 / cleanup 清错侧栏。
    if (!existingGroup && options?.source === 'submit') {
      const probeWorkflowId = String(bridge.workflowId || workflowId || '')
      const probeSource = resolveInversionCatalogId(String(bridge.sourceLayerId || catalogId))
      const pendingGroup = deps.getRunLayerGroups().find(
        (g) =>
          !g.runId &&
          g.status === 'computing' &&
          ((Boolean(probeWorkflowId) && g.workflowId === probeWorkflowId) ||
            resolveInversionCatalogId(String(g.sourceLayerId || '')) === probeSource),
      )
      if (pendingGroup) {
        pendingGroup.runId = runId
        existingGroup = pendingGroup
      }
    }
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
    // 需求2（2026-08-22）：组名/成员名优先取工作流定义（种子/画布流水线）
    // 的 extra.group_title / extra.output_labels 中文配置；descriptor 经
    // catalog 通道携带的 workflowExtra 同效。未配置才落 tracked/catalog 名
    // 与 productTagLabel 固定映射兜底。
    const restoreDef = workflowDefinitionForRestore(
      existingGroup?.workflowId || bridge.workflowId,
      existingGroup?.sourceLayerId || bridge.sourceLayerId,
      catalogId,
    )
    const defTags = explicitExpectedOutputTags(restoreDef)
    const catalogExtra = (() => {
      const catalog = deps.getRuntimeLayerCatalog()
      const keys = [bridge.sourceLayerId, catalogId, tracked?.catalogId].filter((k): k is string =>
        Boolean(k),
      )
      for (const key of keys) {
        const extra = catalog[key]?.workflow_extra
        if (extra && typeof extra === 'object') return extra
      }
      return undefined
    })()
    // 类型收窄：catalogExtra（workflow_extra）是宽 Record<string, unknown>，
    // 取值处显式判型（type-check 债清理 2026-08-23）
    const rawCatalogTitle = catalogExtra?.group_title
    const extraTitle =
      groupTitleFromDefinition(restoreDef) ??
      (typeof rawCatalogTitle === 'string' && rawCatalogTitle.trim() ? rawCatalogTitle : undefined)
    const layerTags = memberTagsFromLayers()
    const catalogLabels = catalogExtra?.output_labels
    // descriptor.workflow_extra.output_labels 的键即产物槽（SM/VOD/OMEGA）；
    // 无完整 workflow_definition.extra.outputs 时仍须建三槽，否则 attach
    // 会落成 imported-omega_sf_fenkuai_* 游离层污染 TOC/库。
    const labelsFromExtraKeys =
      catalogLabels && typeof catalogLabels === 'object' && !Array.isArray(catalogLabels)
        ? Object.keys(catalogLabels as Record<string, unknown>).filter(
            (k) => typeof (catalogLabels as Record<string, unknown>)[k] === 'string' && k.trim(),
          )
        : []
    // 需求2 后的新种子（带 extra 配置）但无显式 outputs 时 → 优先 output_labels 键。
    // 反演目录（method-*-omega-* / 英文 workflow id）无元数据时回退 SM/VOD/OMEGA，
    // 禁止只建 'result' 槽导致 attach 落成 imported-omega_* 游离层。
    // 注意：勿引用未定义标识符——method-* 路径上前两项 pattern 为 false，
    // 若再求值未声明变量会 ReferenceError，占位组建失败 → 英文 overlay 泄漏（2026-08-30）。
    const inversionProbeIds = [
      catalogId,
      bridge.sourceLayerId,
      tracked?.catalogId,
      existingGroup?.sourceLayerId,
      existingGroup?.workflowId,
    ]
      .map((v) => String(v || '').trim())
      .filter(Boolean)
    const inversionFallback =
      inversionProbeIds.some((id) => INVERSION_RUN_LAYER_PATTERN.test(id)) ||
      inversionProbeIds.some((id) => /^method-(?:fy|smap)-omega-/i.test(id))
    const tags = layerTags.length
      ? layerTags
      : defTags.length
        ? defTags
        : labelsFromExtraKeys.length
          ? labelsFromExtraKeys
          : inversionFallback
            ? ['SM', 'VOD', 'OMEGA']
            : ['result']
    const mergedLabels: Record<string, string> = Array.isArray(catalogLabels)
      ? Object.fromEntries(
          catalogLabels
            .map((v, i) => [defTags[i] ?? tags[i], v] as [string, unknown])
            .filter(
              (entry): entry is [string, string] =>
                Boolean(entry[0]) && typeof entry[1] === 'string',
            ),
        )
      : catalogLabels && typeof catalogLabels === 'object'
        ? Object.fromEntries(
            Object.entries(catalogLabels as Record<string, unknown>).filter(
              (entry): entry is [string, string] => typeof entry[1] === 'string',
            ),
          )
        : {}
    const mergedLabelMap: Record<string, string> = mergedLabels
    const configuredTargets = expectedOutputTargets(restoreDef).length
      ? expectedOutputTargets(restoreDef)
      : tags.map((tag) => ({
          productTag: tag,
          name: mergedLabelMap[tag] ?? productTagLabel(tag),
        }))
    const configuredGroupTitle = extraTitle
    const groupId =
      existingGroup?.groupId ||
      tracked?.groupId ||
      `run-group-restored-${runId.replace(/[^a-zA-Z0-9]/g, '').slice(-10)}`
    const memberCatalogIds =
      tracked?.memberCatalogIds?.length === tags.length
        ? tracked.memberCatalogIds
        : tags.map((tag) => `wf-run-${groupId}-${String(tag).toLowerCase()}`)

    // 无 descriptor/workflow 元数据时做通用 restore，禁止写死实验室 seed id。
    // sourceLayerId 若仍是英文 workflow id，收敛到 method-*，避免组挂在技术名上。
    const rawSourceLayerId = existingGroup?.sourceLayerId || bridge.sourceLayerId || catalogId
    const sourceLayerId = resolveInversionCatalogId(String(rawSourceLayerId || catalogId))
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
      // 组名：种子 extra.group_title > 提交时工作流中文名 > 已有非技术标题。
      // 禁止用 wf-run-* / 英文 workflow id 覆盖（此前 isEnglishInversionCatalogId
      // 对 wf-run-* 返回 false，导致组标题被占位 catalogId 污染）。
      if (configuredGroupTitle && !isTechnicalRunTitle(configuredGroupTitle)) {
        group.title = configuredGroupTitle
      } else if (options?.title && !isTechnicalRunTitle(options.title)) {
        group.title = options.title
      } else if (isTechnicalRunTitle(group.title)) {
        group.title = resolveRunGroupTitle({
          workflowId: group.workflowId || workflowId,
          configuredTitle: configuredGroupTitle || options?.title,
          jobName: tracked?.name,
          summaries: tryWorkflowSummaries(),
          fallback: '工作流产物',
        })
      }
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
        // 中文配置优先（extra.group_title）；英文技术名不得落入组标题
        title: resolveRunGroupTitle({
          workflowId,
          configuredTitle: configuredGroupTitle || options?.title,
          jobName: tracked?.name,
          summaries: tryWorkflowSummaries(),
          fallback: '工作流产物',
        }),
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
      title: resolveRunGroupTitle({
        workflowId,
        configuredTitle: configuredGroupTitle || options?.title,
        jobName: tracked?.name,
        summaries: tryWorkflowSummaries(),
        fallback: '反演产物',
      }),
      targets: configuredTargets.length
        ? configuredTargets
        : tags.map((tag) => ({ name: productTagLabel(tag), productTag: tag })),
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
      /** X2 工作流变体（ω 反演在线/本地）：按 descriptor.workflow_variants
       *  解析对应种子并注入 workflow_entry_name；缺省走 descriptor 默认变体。 */
      workflowVariant?: 'online' | 'local'
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
    // 显式 option 优先；钉死偏好次之；否则源路由策略；最后未钉死 preference
    let effectiveVariant: WorkflowVariantKey | undefined =
      options.workflowVariant ??
      (isWorkflowVariantPinned(backendLayerId)
        ? getWorkflowVariantPreference(backendLayerId)
        : undefined) ??
      (isWorkflowVariantPinned(catalogId) ? getWorkflowVariantPreference(catalogId) : undefined)
    const runtimeLayerCatalog = deps.getRuntimeLayerCatalog()
    const catalogName = isOutputLayer
      ? (deps.getLayerLibrary().find((l) => l.catalogId === catalogId)?.name ?? catalogId)
      : (runtimeLayerCatalog[catalogId]?.display_name ??
        runtimeLayerCatalog[backendLayerId]?.display_name ??
        getCatalogDisplayName(catalogId))
    const submitJobId = localSubmitJobId(catalogId)
    const submitStartedAt = new Date().toISOString()
    let workflowDisplayName = resolveSubmitWorkflowDisplayName(catalogName, {
      algorithmRequest: options.algorithmRequest,
      commandLabel: options.commandLabel,
    })

    try {
      const hasEditorWeather = Boolean(
        options.weatherRequest &&
        (options.weatherRequest.workflow ||
          (options.weatherRequest as { workflow_id?: string }).workflow_id),
      )
      // 天气图层默认走瓦片管道；编辑器编译出 weather 画布时走 weather_request
      // （2026-08-25 用户反馈）：瓦片视口刷新静默触发即可——此前 throw 提示
      // 文案会经 setWorkflowError 显示在分析框，属噪音，已移除。
      if (deps.isWeatherEngineLayer(backendLayerId) && !hasEditorWeather) {
        deps.activateWeatherTileViewport(catalogId)
        return undefined
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

      // 源路由：无显式 variant / 未钉死时，按 data-coverage + 策略选 local|online
      if (effectiveVariant === undefined && !hasCanvasDefinition) {
        const descriptor =
          runtimeLayerCatalog[backendLayerId] ?? runtimeLayerCatalog[catalogId] ?? null
        const eligible = descriptorEligibleForSourceRoute(
          descriptor as { workflow_variants?: Record<string, { workflow_id?: string }> },
        )
        if (eligible) {
          let routeTimeKey: string | null = null
          const tr = options.timeRange as { start_at?: string } | undefined
          if (tr?.start_at) {
            routeTimeKey = String(tr.start_at).slice(0, 10)
          } else {
            try {
              const { useUiStore } = await import('../ui')
              const { buildTimeKey } = await import('./online-temporal-orchestrator')
              const ui = useUiStore()
              const granRaw =
                (descriptor as { time_granularity?: string } | null)?.time_granularity ||
                ui.activeTimeGranularity ||
                'day'
              const gran =
                granRaw === 'hour' ||
                granRaw === 'day' ||
                granRaw === 'month' ||
                granRaw === 'year' ||
                granRaw === 'static'
                  ? granRaw
                  : 'day'
              if (gran !== 'static') {
                routeTimeKey = buildTimeKey(ui.currentDate, ui.currentHour, gran)
              }
            } catch {
              /* ignore */
            }
          }
          try {
            const [policiesDoc, coverage] = await Promise.all([
              fetchDataInputPolicies().catch(() => null),
              fetchLayerDataCoverage(backendLayerId).catch(() =>
                fetchLayerDataCoverage(catalogId).catch(() => null),
              ),
            ])
            const mode = resolveSourceRoutePolicyMode(policiesDoc?.policies ?? [], {
              layerId: backendLayerId,
              module: (descriptor as { module_name?: string } | null)?.module_name,
              workflowId:
                (descriptor as { workflow_id?: string } | null)?.workflow_id ??
                (descriptor as { workflow_name?: string } | null)?.workflow_name,
            })
            const onlineBlocked =
              (descriptor as { online_ready?: boolean | null } | null)?.online_ready === false
            const decision = decideSourceRoute({
              mode,
              eligible: true,
              coverage,
              timeKey: routeTimeKey,
              onlineBlocked,
              hasExplicitCanvasWorkflow: false,
              defaultVariant: inferDefaultVariant(
                descriptor as {
                  workflow_id?: string
                  workflow_variants?: Record<string, { workflow_id?: string }>
                },
              ),
            })
            if (decision.action === 'confirm_online') {
              const message = '本地时间窗无数据，按策略需确认后改走在线获取。'
              deps.onSourceRouteConfirmOnline?.({
                catalogId,
                timeKey: routeTimeKey,
                message,
              })
              if (!deps.onSourceRouteConfirmOnline) {
                throw new Error(message)
              }
              return undefined
            }
            if (decision.action === 'use') {
              effectiveVariant = decision.variant
              if (
                decision.variant === 'online' &&
                (decision.reason.startsWith('local_miss') ||
                  decision.reason.startsWith('default_online'))
              ) {
                deps.onSourceRouteSilentOnline?.({
                  catalogId,
                  timeKey: routeTimeKey,
                  message: '已按源路由策略改走在线获取。',
                })
              }
              debugLog(
                'runWorkflow',
                catalogId,
                `source_route ${INPUT_KEY_SOURCE_ROUTE_LOCAL_FIRST}`,
                decision,
              )
            }
          } catch (routeErr) {
            if (routeErr instanceof Error && routeErr.message.includes('需确认')) throw routeErr
            debugLog('runWorkflow', catalogId, 'source_route skipped', String(routeErr))
          }
        }
        if (effectiveVariant === undefined) {
          effectiveVariant =
            getWorkflowVariantPreference(backendLayerId) ?? getWorkflowVariantPreference(catalogId)
        }
      }
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
        // 2026-08-25 回归修复：ed0ad3c 起 supportsAnalysisWorkflow 对 overlay_registry
        // 也返回 true（readiness/分析面板需要），故资产分支判定不能再用取反——
        // 否则 overlay 静态图层落入通用 analysis 提交 → 后端无 bridge → 误报
        // 「未找到匹配的工作流引擎」。改用 isOverlayDisplayOnlyLayer 显式判定。
        deps.isOverlayDisplayOnlyLayer(backendLayerId)
      ) {
        // 资产检查是同一 catalog 的唯一运行入口：添加/重试时先停止旧轮询，
        // 避免同一 GEBCO 等静态图层同时出现「已完成」和「运行中」两条状态。
        interruptWorkflowForCatalog(catalogId)
        const submitJobId = localSubmitJobId(catalogId)
        deps.upsertJobLayer(catalogId, {
          jobId: submitJobId,
          catalogId,
          name: catalogName,
          commandType: 'analysis',
          status: 'queued',
          progress: 5,
          createdAt: submitStartedAt,
          updatedAt: new Date().toISOString(),
          message: '正在检查图层资产…',
          metrics: [],
          reportSummary: '正在检查图层资产…',
          resultUrl: undefined,
        })
        const accepted = await submitOverlayAssetWorkflow(backendLayerId)
        deps.removeJobLayerById(submitJobId)
        deps.upsertJobLayer(catalogId, {
          jobId: accepted.run_id,
          catalogId,
          name: catalogName,
          commandType: 'analysis',
          status: accepted.status === 'succeeded' ? 'succeeded' : 'queued',
          progress: accepted.status === 'succeeded' ? 100 : 12,
          createdAt: accepted.created_at,
          updatedAt: accepted.created_at,
          message: accepted.message,
          metrics: [],
          reportSummary: accepted.message,
          resultUrl: undefined,
        })
        if (accepted.status !== 'succeeded') {
          deps.activeWorkflowCatalogIds.add(catalogId)
          void deps.startPolling(accepted.run_id, catalogId, options.expectedViewportEpoch)
        }
        return accepted.run_id
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
        resolveVariantAlgorithmRequest(
          deps.getRuntimeLayerCatalog(),
          backendLayerId,
          effectiveVariant,
          options.algorithmRequest,
          catalogName,
        ),
        options.weatherRequest,
      )
      if (effectiveVariant && payload.algorithm_request) {
        const algoRequest = payload.algorithm_request as Record<string, unknown>
        const refreshedCatalog = deps.getRuntimeLayerCatalog()
        if (
          !options.commandLabel &&
          typeof algoRequest.workflow_entry_name === 'string' &&
          algoRequest.workflow_entry_name !== refreshedCatalog[backendLayerId]?.workflow_id
        ) {
          const variantLabels = (
            refreshedCatalog[backendLayerId] as WorkflowVariantsHost | undefined
          )?.workflow_variants
          const variantLabel =
            effectiveVariant === 'local'
              ? variantLabels?.local?.label?.trim() || '本地读取'
              : variantLabels?.online?.label?.trim() || '在线获取'
          // command_label 仅作芯片副标题；主标题走工作流种子名
          payload.command_label = `运行分析 · ${variantLabel}`
        }
      }
      // 状态指示器 / 计算组标题：工作流种子中文名优先，禁止图层名 / wf-run-* 占位
      workflowDisplayName = resolveSubmitWorkflowDisplayName(catalogName, {
        algorithmRequest: (payload.algorithm_request ?? options.algorithmRequest) as
          Record<string, unknown> | undefined,
        commandLabel:
          options.commandLabel ||
          (typeof payload.command_label === 'string' ? payload.command_label : undefined),
      })
      const catalogNative =
        resolveCatalogNativeStep(
          runtimeLayerCatalog[backendLayerId] as Record<string, unknown> | undefined,
        ) ??
        resolveCatalogNativeStep(
          runtimeLayerCatalog[catalogId] as Record<string, unknown> | undefined,
        )
      if (options.timeRange && typeof options.timeRange === 'object') {
        payload.time_range = options.timeRange
      } else {
        // 画布/流水线常把日期写在 algorithm_params，却未带顶层 time_range；
        // 优先用 YYYYMMDD，禁止误用主时间轴「今天」盖掉流水线窗。
        const { yyyymmddPairToTimeRange } =
          await import('../../composables/workflow-pipeline-params')
        const apForDates =
          options.algorithmRequest &&
          typeof options.algorithmRequest.algorithm_params === 'object' &&
          options.algorithmRequest.algorithm_params
            ? (options.algorithmRequest.algorithm_params as Record<string, unknown>)
            : null
        const fromParams =
          apForDates &&
          yyyymmddPairToTimeRange(
            String(apForDates.start_date ?? ''),
            String(apForDates.end_date ?? ''),
          )
        if (fromParams) {
          payload.time_range = fromParams
          debugLog('runWorkflow', catalogId, 'injected algorithm_params time_range', fromParams)
        } else {
          // 图层库/侧栏「运行」常不带 time_range；时间轴当前窗补齐，避免后端 None.start
          const libItem = deps.getLayerLibrary().find((l) => l.catalogId === catalogId)
          const rt =
            (runtimeLayerCatalog[backendLayerId] as
              | {
                  supports_time?: boolean
                  time_granularity?: string
                  native_step?: string
                  online_temporal?: { native_step?: string }
                }
              | undefined) ??
            (runtimeLayerCatalog[catalogId] as
              | {
                  supports_time?: boolean
                  time_granularity?: string
                  native_step?: string
                  online_temporal?: { native_step?: string }
                }
              | undefined)
          const supportsTime = libItem?.supportsTime ?? rt?.supports_time ?? true
          const filled = await resolveDefaultTimeRangeFromTimeline({
            supportsTime: supportsTime !== false,
            nativeStep: catalogNative ?? rt?.native_step ?? rt?.online_temporal?.native_step,
            // 目录条目未投影 timeGranularity；粒度以 runtime descriptor 为准
            granularity: rt?.time_granularity,
          })
          if (filled) {
            payload.time_range = filled
            debugLog('runWorkflow', catalogId, 'injected timeline time_range', filled)
          }
        }
      }
      const algoParams =
        options.algorithmRequest && typeof options.algorithmRequest.algorithm_params === 'object'
          ? (options.algorithmRequest.algorithm_params as Record<string, unknown>)
          : null
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
        name: workflowDisplayName,
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
        commandLabel:
          options.commandLabel ||
          (typeof payload.command_label === 'string' ? payload.command_label : undefined),
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
        name: workflowDisplayName,
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
        commandLabel:
          options.commandLabel ||
          (typeof payload.command_label === 'string' ? payload.command_label : undefined),
      })
      if (catalogId.startsWith('wf-out-')) {
        useWorkflowOutputLayersStore().updateRunStatus(catalogId, accepted.run_id, 'queued')
      }

      deps.activeWorkflowCatalogIds.add(catalogId)
      // 工作流提交成功，清除 429 重试计数
      deps.workflowRetryCounts.delete(catalogId)
      // 提交即建占位计算组（需求2：产物应成组显示）。此前只在恢复轮询路径
      // 建组——图层面板直跑的工作流产物物化时查不到组 → 图层游离不进组。
      // targets 由种子 extra（group_title/output_labels）推导；无元数据时
      // 单产出 'result' 语义（ensureRestoredRunGroup 内部处理）。
      ensureRestoredRunGroup(accepted.run_id, catalogId, undefined, {
        createPlaceholders: true,
        title: workflowDisplayName,
        source: 'submit',
      })
      void deps.startPolling(accepted.run_id, catalogId, options.expectedViewportEpoch)
      return accepted.run_id
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : '提交 workflow 失败'
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
              name: workflowDisplayName,
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
          name: workflowDisplayName,
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
          name: workflowDisplayName,
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
      const prevJob = deps.getJobLayers().find((item) => item.jobId === jobId)
      const catalogName =
        deps.getRuntimeLayerCatalog()[catalogId]?.display_name ?? getCatalogDisplayName(catalogId)
      const retryDisplayName = resolveSubmitWorkflowDisplayName(catalogName, {
        commandLabel: prevJob?.commandLabel,
      })
      deps.upsertJobLayer(catalogId, {
        jobId: accepted.run_id,
        name: retryDisplayName,
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

  /** 新添加图层后自动载入已有产物/缓存（需求1 批次2，2026-08-21）。
   *
   * 拉最近成功 run，若某 run 的 layer_id（经反演映射收敛后）匹配新图层
   * catalogId，则物化产物 overlay 并绑到该图层——与刷新恢复
   * （restoreActiveWorkflows）的 autoDiscovered 行为对齐，但触发点为
   * 用户从目录添加图层。无产物 run 时静默跳过（用户随后可手动运行）。
   *
   * ``preferredTimeKey``：优先复用覆盖该时刻的成功产物；否则回退到该 catalog
   * 最新成功 run（添加图层场景）。
   */
  async function autoAttachProductsForNewLayer(
    catalogId: string,
    options?: { preferredTimeKey?: string | null },
  ): Promise<number> {
    const targetId = resolveInversionCatalogId(catalogId)
    // 保护用户静态图层：仅当该 catalog 具备 map-layer-result capability 才去
    // attach 反演产物。对纯静态/展示型图层（干旱指数 AI 等）执行会误把反演
    // run 产物并进用户静态层 → 静态图层闪现 + 越权图层组（2026-08-23）。
    if (!deps.supportsMapLayerResult(targetId) && !deps.supportsMapLayerResult(catalogId)) {
      return 0
    }
    let runs: Awaited<ReturnType<typeof listRecentSucceededRuns>>
    try {
      runs = await listRecentSucceededRuns(20)
    } catch {
      return 0 // 目录/网络不可用：静默（添加图层本身不应因此报错）
    }
    const catalogRuns = runs.filter((r) => resolveInversionCatalogId(r.layer_id || '') === targetId)
    if (!catalogRuns.length) return 0

    const preferred = options?.preferredTimeKey?.trim() || null
    // 先试最新 run；若指定 timeKey，物化后按 time_list 过滤——无覆盖则继续试下一 run
    const ordered = preferred ? catalogRuns : catalogRuns.slice(0, 1)

    for (const match of ordered) {
      try {
        // 建 SM/VOD/ω 占位组再绑产物，禁止游离层以 overlay 技术 id 进 TOC/库
        ensureRestoredRunGroup(match.run_id, targetId, undefined, {
          createPlaceholders: true,
          source: 'restore',
        })
        const bound = await deps.attachAlgorithmProductOverlays(
          match.result_refs,
          targetId,
          match.run_id,
          { forceBind: true },
        )
        if (bound <= 0) {
          deps.discardRunGroupUi?.(match.run_id)
          continue
        }

        // 时间覆盖看 run 组成员产物，不是 method-* 父卡（父卡通常无 importedRaster）
        const group = deps.getRunLayerGroups().find((g) => g.runId === match.run_id)
        const memberTimeList = deps
          .getActiveLayers()
          .filter((l) => (group ? l.runGroupId === group.groupId : false))
          .flatMap((l) => l.importedRaster?.timeList ?? [])
        const parentLayer = deps
          .getActiveLayers()
          .find(
            (l) => l.catalogId === targetId || resolveInversionCatalogId(l.catalogId) === targetId,
          )
        const timeList =
          memberTimeList.length > 0 ? memberTimeList : (parentLayer?.importedRaster?.timeList ?? [])
        if (preferred) {
          const { timeListCoversTimeKey } = await import('../../utils/time-key-coverage')
          if (!timeListCoversTimeKey(timeList, preferred)) {
            // 该 run 不覆盖目标时刻：丢弃本轮探测组 UI，试下一成功 run
            deps.discardRunGroupUi?.(match.run_id)
            continue
          }
        }

        deps.cleanupUnproducedRunLayers(match.run_id, { succeeded: true })
        deps.scheduleWorkspacePersist()
        // 时间轴：有 preferred 用 preferred；否则跳到产物最新时间块
        if (preferred && deps.alignTimelineToProduct) {
          deps.alignTimelineToProduct(preferred)
        } else {
          const timeLabel =
            parentLayer?.importedRaster?.effectiveTimeLabel ??
            (timeList.length ? timeList[timeList.length - 1] : undefined)
          if (timeLabel && deps.alignTimelineToProduct) {
            deps.alignTimelineToProduct(String(timeLabel))
          }
        }
        return bound
      } catch {
        deps.discardRunGroupUi?.(match.run_id)
        continue
      }
    }
    return 0
  }

  /** 查询同 catalog 是否已有覆盖 timeKey 的成功产物（不绑层，供确认卡决策）。 */
  async function hasReusableProductsForTime(catalogId: string, timeKey: string): Promise<boolean> {
    const targetId = resolveInversionCatalogId(catalogId)
    if (!deps.supportsMapLayerResult(targetId) && !deps.supportsMapLayerResult(catalogId)) {
      return false
    }
    // 先看已绑定图层
    const { timeListCoversTimeKey } = await import('../../utils/time-key-coverage')
    const existing = deps
      .getActiveLayers()
      .find(
        (l) =>
          (l.catalogId === targetId || resolveInversionCatalogId(l.catalogId) === targetId) &&
          timeListCoversTimeKey(l.importedRaster?.timeList, timeKey),
      )
    if (existing) return true

    let runs: Awaited<ReturnType<typeof listRecentSucceededRuns>>
    try {
      runs = await listRecentSucceededRuns(20)
    } catch {
      return false
    }
    // 轻量：仅检查 result_refs / 事件不足以拿 time_list；依赖已物化层或添加后再判。
    // 有同 catalog 成功 run 即提示「可能可复用」，确认时再 autoAttach 精确匹配。
    return runs.some((r) => resolveInversionCatalogId(r.layer_id || '') === targetId)
  }

  return {
    restoreActiveWorkflows,
    registerExternalWorkflowRun,
    runWorkflowForCatalog,
    autoAttachProductsForNewLayer,
    hasReusableProductsForTime,
    cancelWorkflowRunForJob,
    retryWorkflowRunForJob,
    interruptWorkflowForCatalog,
    scheduleWorkflowRetry,
    cleanupAllRetryTimers,
    rememberTrackedWorkflowRun,
    forgetTrackedWorkflowRun,
    workflowVariantPreference,
    getWorkflowVariantPreference,
    setWorkflowVariantPreference,
    isWorkflowVariantPinned,
    clearWorkflowVariantPin,
    // 内部辅助不导出：resolveRestoredCatalogId / hydrateJobLayerFromEvents /
    //   resolveRestoreWorkflowBridge / ensureRestoredRunGroup
  }
}
