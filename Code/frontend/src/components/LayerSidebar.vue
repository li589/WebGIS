<script setup lang="ts">
/**
 * LayerSidebar — 图层侧栏主组件（编排壳）。
 *
 * 职责：调用 composables 获取状态，将各视图委托给子组件渲染。
 * 自身仅保留：catalog 辅助函数、基础操作、滚动管理、symbology 预取。
 *
 * 拆分历史：原 2910 行 → CSS 提取(-1357) → composable 提取(-1100) → 子组件提取(-450)
 */
import { computed, nextTick, ref, watch, onMounted, onUnmounted } from 'vue'
import { Diamond } from './ui/icons'

import { useLayerWorkspace, useLayerLifecycle, useWorkflowRun } from '../stores/layers/selectors'
import { useAuthStore } from '../stores/auth'
import type { ActiveLayer, ActiveLayerDisplay } from '../stores/layers/types'
import { deriveDataStatus, normalizeRunGroupMemberStatus } from '../utils/layer-data-status'
import { resolveCategoryDisplayName } from '../stores/layers/catalog'
import type { SidebarDragDeps, SidebarLayersDeps } from './layer-sidebar/sidebar-layers-deps'
import { useUiStore } from '../stores/ui'
import { useLogStore } from '../stores/log'
import { useTimelineActionBannerStore } from '../stores/timeline-action-banner'
import { useDrawStore } from '../stores/draw-store'
import { useOverlaySymbologyStore } from '../stores/overlay-symbology'
import { useWeatherSourcePrefsStore } from '../stores/weather-source-prefs'
import { isWeatherLayerUnsupportedByModel } from '../stores/weather-tile-manager'
import { useWeatherEngineStore } from '../stores/weather-engine'
import { LAYERS_COPY } from '../ui-copy'
import { useOnlinePlanSessionStore } from '../stores/online-plan-session'
import { useDrawSessionTransition } from '../composables/useDrawSessionTransition'
import { yyyymmddPairToTimeRange } from '../composables/workflow-pipeline-params'
import {
  resolveInversionGroupMeta,
  resolveStableInversionProducts,
  resolveStableInversionTimeSpan,
} from '../stores/layers/inversion-overlay-probe'
import { timeListCoversTimeKey } from '../utils/time-key-coverage'

// ── Composables ───────────────────────────────────────────────────────────
import { useSidebarWeatherProviders } from './layer-sidebar/useSidebarWeatherProviders'
import { useSidebarSearch } from './layer-sidebar/useSidebarSearch'
import { useSidebarDragReorder } from './layer-sidebar/useSidebarDragReorder'
import { useSidebarSymbology } from './layer-sidebar/useSidebarSymbology'
import { useSidebarContextMenu } from './layer-sidebar/useSidebarContextMenu'

// ── 子组件 ─────────────────────────────────────────────────────────────────
import LayerSidebarHeader from './layer-sidebar/LayerSidebarHeader.vue'
import LayerSidebarLibrary from './layer-sidebar/LayerSidebarLibrary.vue'
import LayerGroupManagerDialog from './layer-sidebar/LayerGroupManagerDialog.vue'
import AddLayerComputeDialog from './layer-sidebar/AddLayerComputeDialog.vue'
import LayerSidebarActive from './layer-sidebar/LayerSidebarActive.vue'
import LayerSidebarContextMenu from './layer-sidebar/LayerSidebarContextMenu.vue'
import { onOpenLayerGroupManager } from '../utils/layer-group-manager-bridge'

const emit = defineEmits<{
  selectLayer: [instanceId: string]
  zoomToLayer: [instanceId: string]
}>()

// ── Store 设置 ──────────────────────────────────────────────────────────────
const workspace = useLayerWorkspace()
const workflowRun = useWorkflowRun()
const uiStore = useUiStore()
const logStore = useLogStore()
const onlinePlan = useOnlinePlanSessionStore()
const drawStore = useDrawStore()
const { requestInteractionMode } = useDrawSessionTransition()
const overlaySymbologyStore = useOverlaySymbologyStore()
const weatherSourcePrefs = useWeatherSourcePrefsStore()
const weatherEngine = useWeatherEngineStore()

const {
  activeLayers,
  activeLayersDisplay,
  selectedInstanceId,
  sidebarView,
  activeLayerCount,
  sidebarViewLabel,
  catalogJobStatus,
  layerLibrary,
} = workspace

const { runLayerGroups } = workflowRun

// 图层平台子系统 P1：生命周期查询（侧栏徽标数据源）
const lifecycle = useLayerLifecycle()

const layerCategories = workspace.layerCategories

// ── 图层平台 P1：分组管理入口（管理员） ────────────────────────────────────
const authStore = useAuthStore()
const groupManagerOpen = ref(false)
const groupManagerThemeId = ref<number | null>(null)

function closeGroupManager() {
  groupManagerOpen.value = false
  groupManagerThemeId.value = null
}

let stopGroupManagerBridge: (() => void) | null = null
onMounted(() => {
  stopGroupManagerBridge = onOpenLayerGroupManager((themeId) => {
    if (!authStore.isAdmin) return
    groupManagerThemeId.value = themeId
    groupManagerOpen.value = true
  })
})
onUnmounted(() => {
  stopGroupManagerBridge?.()
  stopGroupManagerBridge = null
})

// ── 侧栏 composable 的 layers 窄依赖（P3 收口：不再传递整店实例）──────────
const sidebarLayersDeps: SidebarLayersDeps = {
  activeLayers,
  canRunCatalog: workspace.canRunCatalog,
  isWeatherEngineLayer: workspace.isWeatherEngineLayer,
  supportsAnalysisWorkflow: workspace.supportsAnalysisWorkflow,
  isOverlayDisplayOnlyLayer: workspace.isOverlayDisplayOnlyLayer,
  bringLayerToFront: workspace.bringLayerToFront,
  sendLayerToBack: workspace.sendLayerToBack,
  removeLayer: workspace.removeLayer,
  setLayerDisplayName: workspace.setLayerDisplayName,
  toggleLayerVisibility: workspace.toggleLayerVisibility,
  dissolveRunGroup: workflowRun.dissolveRunGroup,
  findRunGroupById: workflowRun.findRunGroupById,
  runWorkflowForCatalog: workflowRun.runWorkflowForCatalog,
  // 右键「运行工作流」→ 先弹时间范围框再执行（2026-10-17）
  promptAndRunCatalog: promptRecomputeForExisting,
}

const sidebarDragDeps: SidebarDragDeps = {
  reorderLayers: workflowRun.reorderLayers,
  moveRunGroupBlock: workflowRun.moveRunGroupBlock,
}

// ── Composable 调用 ──────────────────────────────────────────────────────────

const weatherProviders = useSidebarWeatherProviders()

const search = useSidebarSearch(
  layerLibrary,
  layerCategories,
  weatherProviders.ensureWeatherProviders,
)

const drag = useSidebarDragReorder(activeLayersDisplay, runLayerGroups, sidebarDragDeps)

const symbology = useSidebarSymbology(overlaySymbologyStore)

const ctxMenu = useSidebarContextMenu(
  activeLayersDisplay,
  runLayerGroups,
  sidebarLayersDeps,
  uiStore,
  logStore,
  overlaySymbologyStore,
  emit as (event: string, ...args: unknown[]) => void,
  selectItem,
  zoomToItem,
  removeItem,
  drag.runGroupOf,
)

// ── Catalog 辅助函数 ─────────────────────────────────────────────────────────

/** 轻量已添加集合：只读 activeLayers，避开 activeLayersDisplay */
const addedCatalogIds = computed(() => {
  const ids = new Set<string>()
  for (const layer of activeLayers.value) {
    if (!layer.isAdminBoundary) ids.add(layer.catalogId)
  }
  return ids
})

function isAdded(catalogId: string): boolean {
  return addedCatalogIds.value.has(catalogId)
}

function getCatalogJobStatus(catalogId: string): string | undefined {
  return catalogJobStatus.value.get(catalogId)
}

function getCatalogRunBlockReason(catalogId: string): string | null {
  return workspace.getCatalogRunBlockReason(catalogId)
}

function getCatalogAddBlockReason(catalogId: string): string | null {
  return workspace.getCatalogAddBlockReason(catalogId)
}

function isOverlayDisplayOnlyLayer(catalogId: string): boolean {
  return workspace.isOverlayDisplayOnlyLayer(catalogId)
}

function supportsOnlineTemporal(catalogId: string): boolean {
  return workspace.supportsOnlineTemporal(catalogId)
}

function getSourceRouteBadge(
  catalogId: string,
): { key: string; label: string; title: string } | null {
  const desc = workspace.resolveEffectiveDescriptor?.(catalogId) as {
    workflow_variants?: Record<string, { workflow_id?: string } | undefined>
  } | null
  const variants = desc?.workflow_variants
  if (!variants?.local?.workflow_id || !variants?.online?.workflow_id) return null
  const backendId = workspace.resolveBackendLayerId(catalogId)
  const pinned =
    Boolean(workflowRun.isWorkflowVariantPinned?.(backendId)) ||
    Boolean(workflowRun.isWorkflowVariantPinned?.(catalogId))
  const pref =
    workflowRun.getWorkflowVariantPreference?.(catalogId) ??
    workflowRun.getWorkflowVariantPreference?.(backendId)
  if (!pinned) {
    return {
      key: 'auto',
      label: '自动',
      title: '源路由自动：本地有数走本地，否则走在线（点击切换本地→在线→自动）',
    }
  }
  if (pref === 'online') {
    return { key: 'online', label: '在线', title: '已钉死在线（点击切回自动）' }
  }
  return { key: 'local', label: '本地', title: '已钉死本地（点击切换为在线）' }
}

function cycleSourceRoute(catalogId: string) {
  const badge = getSourceRouteBadge(catalogId)
  if (!badge) return
  const backendId = workspace.resolveBackendLayerId(catalogId)
  if (badge.key === 'auto') {
    workflowRun.setWorkflowVariantPreference(catalogId, 'local', { pinned: true })
    if (backendId !== catalogId) {
      workflowRun.setWorkflowVariantPreference(backendId, 'local', { pinned: true })
    }
  } else if (badge.key === 'local') {
    workflowRun.setWorkflowVariantPreference(catalogId, 'online', { pinned: true })
    if (backendId !== catalogId) {
      workflowRun.setWorkflowVariantPreference(backendId, 'online', { pinned: true })
    }
  } else {
    workflowRun.clearWorkflowVariantPin?.(catalogId)
    if (backendId !== catalogId) workflowRun.clearWorkflowVariantPin?.(backendId)
  }
}

function isOnlinePlanPending(catalogId: string): boolean {
  return onlinePlan.isCatalogPendingPlan(catalogId)
}

function openOnlinePlan() {
  onlinePlan.openSession()
}

// ── 图层平台子系统 P1：生命周期徽标（lifecycle 域 → 侧栏卡片） ──
const LIFECYCLE_BADGE_LABELS: Record<string, string> = {
  fresh: '资产就绪',
  stale: '资产陈旧',
  updating: '更新中',
  missing: '资产缺失',
  failed: '更新失败',
}

function getLifecycleBadge(
  catalogId: string,
): { state: string; label: string; message: string | null } | null {
  const entry = lifecycle.getLifecycle(catalogId)
  if (!entry || entry.lifecycleState === 'unknown') return null
  const label = LIFECYCLE_BADGE_LABELS[entry.lifecycleState] ?? entry.lifecycleState
  return { state: entry.lifecycleState, label, message: entry.message }
}

// ── 统一数据状态徽标（2026-08-25 UX 简化）────────────────────────────────
// 三源（availability/lifecycle/job）归并为单枚五态徽标（运行中/排队中/
// 异常/完成/旧数据），替代「数据异常/资产陈旧/失败」三枚堆叠——"资产"
// 术语对地理研究者无意义，统一语义见 utils/layer-data-status.ts。
function isStaticDataLayer(catalogId: string): boolean {
  const item = layerLibrary.value.find((l) => l.catalogId === catalogId)
  if (!item) return false
  return String(item.updateLabel || '').includes('静态') || item.supportsTime === false
}

function getUnifiedDataStatus(layer: ActiveLayerDisplay): ReturnType<typeof deriveDataStatus> {
  const badge = getLifecycleBadge(layer.catalogId)
  const job = layer.jobLayer
  const status = deriveDataStatus({
    jobStatus: job?.status ?? null,
    jobProgress: typeof job?.progress === 'number' ? job.progress : null,
    availabilityState: layer.availabilityState,
    availabilityLabel: layer.availabilityLabel,
    availabilityDescription: layer.availabilityDescription ?? null,
    lifecycleState: badge?.state ?? null,
    lifecycleMessage: badge?.message ?? null,
    isStaticLayer: isStaticDataLayer(layer.catalogId),
  })
  if (!layer.runGroupId) return status
  const group = workflowRun.runLayerGroups.value.find((g) => g.groupId === layer.runGroupId)
  return normalizeRunGroupMemberStatus(status, group?.status === 'computing')
}

// ── 添加即运行（2026-08-25 UX 简化）─────────────────────────────────────
// 点击「+ 添加」后自动完成一切：
// 1. 优先附加既有产物/缓存（成功 run 产物直接上图）
// 2. 无产物 → 自动提交工作流（内部分流：overlay→资产工作流重烘；
//    python_provider→分析运行；weather→瓦片视口按需加载），
//    轮询持续到产出或报错，终态由 poller 物化/呈现
// 3. 时间轴按需加载由 online-temporal-orchestrator 承担
/**
 * 复用盘上已有产物，返回挂上的成员数（0＝确实没有可用产物）。
 *
 * 两段式（2026-10-13 / 10-15）：
 * 1) **稳定编号直探**——按 `sha1(catalogId|role|role)` 直接问后端「产物在不在」，
 *    与账号无关、与 run 成功与否无关、不联网（原路径只查 /workflow-runs，按账号隔离
 *    且只认 succeeded，导致 admin 跑过的产物别人复用不到）；
 * 2) 直探没命中时退回 `/workflow-runs` 两段式：先按时间轴时刻、再退到最新可用帧。
 */
async function attachExistingProducts(
  catalogId: string,
  preferred: string | null,
): Promise<number> {
  try {
    const stableAttached = await attachStableInversionProducts(catalogId, preferred)
    if (stableAttached > 0) return stableAttached
  } catch {
    // 探测失败不阻断（后端目录不可用 / 非安全上下文等）
  }
  try {
    let attached = 0
    if (preferred) {
      attached = await workflowRun.autoAttachProductsForNewLayer(catalogId, {
        preferredTimeKey: preferred,
      })
    }
    if (attached <= 0) {
      attached = await workflowRun.autoAttachProductsForNewLayer(catalogId)
    }
    return attached
  } catch {
    return 0
  }
}

/** 提交一次工作流；失败只记日志（真实失败态由 jobLayer + 顶栏 notice 呈现）。 */
async function submitCatalogWorkflow(
  catalogId: string,
  start?: string,
  end?: string,
): Promise<void> {
  try {
    const timeRange = start && end ? yyyymmddPairToTimeRange(start, end) : undefined
    await workflowRun.runWorkflowForCatalog(catalogId, timeRange ? { timeRange } : {})
  } catch (err) {
    // 预期内的提示性错误静默（天气瓦片提示/无引擎等）
    const message = err instanceof Error ? err.message : String(err)
    logStore.logOperation('layer-add', `图层「${catalogId}」自动运行未启动：${message}`)
  }
}

/**
 * 已添加的图层：弹时间范围框，确认后按所选范围重算。
 * 不重复添加图层，只提交计算（避免侧栏出现重复条目）。
 */
async function promptRecomputeForExisting(catalogId: string): Promise<void> {
  const choice = await promptComputeTimeRange(catalogId, { alreadyAdded: true })
  if (choice?.kind !== 'compute') return
  logStore.logOperation('layer-add', `图层「${catalogId}」按新时间范围重算`)
  await submitCatalogWorkflow(catalogId, choice.start, choice.end)
}

async function ensureLayerDataOrRun(
  catalogId: string,
  opts: { skipDialog?: boolean } = {},
): Promise<void> {
  // 添加即切到图层独立记忆，再挂产物 / 按轴时刻开跑
  uiStore.setUnifiedTimeLock(false)
  if (uiStore.isLayerTimeLocked(catalogId)) {
    uiStore.toggleLayerTimeLock(catalogId)
  }
  // 添加后 snap / attach 会改时间轴——抑制确认卡，避免自触发
  useTimelineActionBannerStore().suppressConfirm(4_000)
  const preferred = currentTimelineTimeKey()

  // ── 第 0 步（2026-10-17 用户要求）：不管盘上有没有数据，先弹时间范围框 ──
  // 有产物 ⇒ 默认日期＝产物覆盖区间，按钮「直接添加」；
  // 无产物 ⇒ 默认最近 30 天，按钮「开始计算」；单次计算最长 31 天。
  // skipDialog：批量「添加到分类」时不再逐个弹窗，保持原有"先挂后算"行为。
  const choice = opts.skipDialog
    ? ({ kind: 'auto' } as const)
    : await promptComputeTimeRange(catalogId)

  if (choice === null) {
    logStore.logOperation('layer-add', `图层「${catalogId}」已取消`)
    return
  }

  // 所选范围落在已有数据内 ⇒ 挂载后直接显示，不跑工作流
  if (choice?.kind === 'attach') {
    const attached = await attachExistingProducts(catalogId, preferred)
    if (attached > 0) {
      uiStore.rememberLayerTime(catalogId, { force: true })
      return
    }
    // 探测与挂载结果不一致（如产物刚被移走）：退回不带窗口的提交
    logStore.logOperation('layer-add', `图层「${catalogId}」未找到匹配产物，改走计算`)
    await submitCatalogWorkflow(catalogId)
    return
  }

  // 用户选了需要计算的范围 ⇒ 直接按该窗口提交
  if (choice?.kind === 'compute') {
    await submitCatalogWorkflow(catalogId, choice.start, choice.end)
    return
  }

  // 其余情况：choice === undefined（不支持时间）或 kind === 'auto'（非反演目录）
  // ⇒ 保持原有行为：先复用产物，复用不到才提交（不带时间窗）
  const attached = await attachExistingProducts(catalogId, preferred)
  if (attached > 0) {
    uiStore.rememberLayerTime(catalogId, { force: true })
    return
  }
  await submitCatalogWorkflow(catalogId)
}

/** 当前时间轴时刻（YYYY-MM-DD）；非法/不可用时返回 null（退化为"取最新产物"）。 */
function currentTimelineTimeKey(): string | null {
  const d = uiStore.currentDate
  if (!(d instanceof Date) || Number.isNaN(d.getTime())) return null
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 帧标签解析：`YYYYMMDD` 或 `YYYYMMDD_YYYYMMDD`（分隔符 `-` / `_` 均可）。 */
const FRAME_TOKEN_PATTERN =
  /^(\d{4})[-_]?(\d{2})[-_]?(\d{2})(?:[-_](\d{4})[-_]?(\d{2})[-_]?(\d{2}))?/

/**
 * 按稳定编号直探盘上产物并挂载（新增于 2026-10-15，编号规则见
 * `stores/layers/inversion-overlay-probe.ts`）。
 *
 * 只对「反演目录」（`method-<平台>-omega-doy-<模式>`）生效：算出 SM / VOD / ω 三个
 * 稳定编号 → 逐个问后端「有图吗」→ 命中的挂进同一个数据集分组，并只默认勾选
 * 「土壤水分」（与默认图层名单同口径）。返回挂上的成员数；返回 0 表示盘上确实没有
 * 该目录的产物，调用方应继续走原有「查 run / 重跑」路径。
 *
 * 为什么需要：原路径查的 `/workflow-runs` **按账号隔离且只认 succeeded**，admin 跑过
 * 的产物游客复用不到 ⇒ 每次都退化成重跑（时间窗＝轴当前帧，常停在无数据日）⇒ 必失败。
 *
 * @returns 本次新挂载的成员数（0 = 无产物 / 已全部在工作区）
 */
async function attachStableInversionProducts(
  catalogId: string,
  preferredTimeKey: string | null,
): Promise<number> {
  const groupMeta = resolveInversionGroupMeta(catalogId)
  if (!groupMeta) return 0
  const products = await resolveStableInversionProducts(catalogId)
  if (!products.length) return 0

  // 幂等：已在工作区（快照恢复 / 重复添加）的产物不重复挂
  const present = new Set(
    activeLayers.value
      .map((layer) => layer.importedRaster?.overlayLayerId)
      .filter((id): id is string => Boolean(id)),
  )
  const fresh = products.filter((product) => !present.has(product.overlayId))
  if (!fresh.length) return 0

  const added: ActiveLayer[] = []
  for (const product of fresh) {
    const layer = workspace.addImportedRasterLayer(
      product.label,
      product.overlayId,
      product.probed.bounds,
      {
        timeList: product.probed.timeList,
        defaultTime: product.probed.defaultTime,
        nativeStep: product.probed.nativeStep,
      },
    )
    // 与默认图层同口径：只默认勾选「土壤水分」，VOD / ω 挂上但不显示
    if (product.role !== 'SM') layer.visible = false
    added.push(layer)
  }

  // 同一数据集的成员收进一个 ready 组，侧栏显示分组头（与官方恢复路径同构）
  const groupId = `run-group-stable-${groupMeta.catalogId}`
  const roleByOverlayId = new Map(products.map((product) => [product.overlayId, product.role]))
  const existingGroup = runLayerGroups.value.find((group) => group.groupId === groupId)
  if (existingGroup) {
    existingGroup.memberInstanceIds.push(...added.map((layer) => layer.instanceId))
  } else {
    runLayerGroups.value.push({
      groupId,
      runId: '',
      title: groupMeta.groupTitle,
      status: 'ready',
      memberInstanceIds: added.map((layer) => layer.instanceId),
      dissolvable: true,
      sourceLayerId: groupMeta.catalogId,
      workflowId: groupMeta.workflowId,
      message: '',
    })
  }
  for (const layer of added) {
    layer.runGroupId = groupId
    layer.runGroupLocked = false
    // 角色标记：左侧色带据此显示单位（SM = m³/m³；VOD / ω 无量纲不显示）
    layer.runGroupProductTag =
      roleByOverlayId.get(layer.importedRaster?.overlayLayerId ?? '') ?? undefined
  }
  workspace.scheduleWorkspacePersist()

  alignTimelineToFrame(added.find((layer) => layer.visible) ?? added[0], preferredTimeKey)
  return added.length
}

/**
 * 把时间轴落到挂载产物的「有数据帧」。
 *
 * - 轴当前时刻被该产物 `time_list` 覆盖 ⇒ 停在该时刻（用户"拖到某天再添加"就该看到那天）；
 * - 否则落到 `default_time`，再退到 `time_list` 最后一帧。
 * - **区间帧取结束日**：`time_list` 按字典序排列时 `20251227_20251231` 会排在单日帧
 *   `20251231` 之前，落在帧内部才能被 `resolveSliceForInstant` 解析回该帧
 *   （与 `default-layers.ts` 的 `alignTimelineToDefaultFrame` 同口径）。
 */
function alignTimelineToFrame(
  layer: ActiveLayer | undefined,
  preferredTimeKey: string | null,
): void {
  const timeList = layer?.importedRaster?.timeList ?? []
  const candidate =
    preferredTimeKey && timeListCoversTimeKey(timeList, preferredTimeKey)
      ? preferredTimeKey
      : layer?.importedRaster?.defaultTime || timeList[timeList.length - 1] || ''
  const matched = FRAME_TOKEN_PATTERN.exec(String(candidate).trim())
  if (!matched) return
  const end = matched[4]
    ? `${matched[4]}${matched[5]}${matched[6]}`
    : `${matched[1]}${matched[2]}${matched[3]}`
  const date = new Date(
    Number(end.slice(0, 4)),
    Number(end.slice(4, 6)) - 1,
    Number(end.slice(6, 8)),
    0,
    0,
    0,
    0,
  )
  if (Number.isNaN(date.getTime())) return
  // 程序化改轴：抑制顶栏确认卡，避免与吸附逻辑互相触发
  useTimelineActionBannerStore().suppressConfirm(3_500)
  uiStore.applyDateHour(date, 0)
  uiStore.applyTimelineFromLayerGranularity('day')
}

function getCatalogItem(catalogId: string) {
  return layerLibrary.value.find((item) => item.catalogId === catalogId)
}

// ── 「添加图层」时间范围弹窗（2026-10-16 建，2026-10-17 按用户要求改版） ──────
// 改版要点：**不管盘上有没有产物，点「添加」都弹**，让用户自己决定要哪一段时间。
// - 有产物 ⇒ 默认日期＝产物覆盖区间，按钮「直接添加」⇒ 一次确认即挂图；
// - 改到范围外 ⇒ 按钮「开始计算」，按新窗口提交；
// - 单次计算最长 31 天（直接加载已有数据不受限，因为不消耗算力）。
const computeDialogOpen = ref(false)
const computeDialogBusy = ref(false)
const computeDialogLayerName = ref('')
const computeDialogDefaultStart = ref('')
const computeDialogDefaultEnd = ref('')
const computeDialogBlockMode = ref(false)
const computeDialogAvailableStart = ref('')
const computeDialogAvailableEnd = ref('')
const computeDialogAvailableFrames = ref(0)
const computeDialogAlreadyAdded = ref(false)
/** 该目录是否为反演目录（决定「无法判断覆盖」时是否可回落到原有路径） */
const computeDialogIsInversion = ref(false)

/** 弹窗确认后的分流结果。 */
type ComputeDialogChoice =
  /** 所选范围落在盘上已有数据内 ⇒ 直接挂载 */
  | { kind: 'attach' }
  /** 需要真正计算 ⇒ 用这个 YYYYMMDD 窗口提交 */
  | { kind: 'compute'; start: string; end: string }
  /** 无法判断覆盖（非反演目录）⇒ 交回原有「先挂产物、再跑」路径 */
  | { kind: 'auto' }
  /** 用户取消 */
  | null
  /** 该图层不支持时间 ⇒ 不弹窗 */
  | undefined

let computeDialogResolve: ((result: ComputeDialogChoice) => void) | null = null

/** Date → YYYYMMDD（本地分量，与 DateInputField 的取值口径一致）。 */
function toCompactDate(value: Date): string {
  const y = value.getFullYear()
  const m = String(value.getMonth() + 1).padStart(2, '0')
  const d = String(value.getDate()).padStart(2, '0')
  return `${y}${m}${d}`
}

/** 该目录是否为 8 天块型动态散射（决定提示文案与最短天数校验）。 */
function isBlockInversionCatalog(catalogId: string): boolean {
  return /^method-(smap|fy)-omega-doy-dynamic$/.test(catalogId)
}

/**
 * 弹出时间范围选择框（**无条件弹**，除非该图层本身没有时间维度）。
 *
 * 打开前先探一次盘上产物的时间覆盖区间：命中则把默认日期预填成这段范围，
 * 用户点一次「直接添加」即可挂图；探测不到／非反演目录则默认最近 30 天。
 */
async function promptComputeTimeRange(
  catalogId: string,
  opts: { alreadyAdded?: boolean } = {},
): Promise<ComputeDialogChoice> {
  if (computeDialogOpen.value) return null
  const item = getCatalogItem(catalogId)
  // 静态图层（无时间维度）：弹窗没有意义，交回原行为
  if (item && item.supportsTime === false) return undefined

  const isInversion = Boolean(resolveInversionGroupMeta(catalogId))
  // 探测产物覆盖区间：只对反演目录支持；失败按「无产物」处理，不阻断添加
  let span: { start: string; end: string; frames: number } | null = null
  if (isInversion) {
    try {
      span = await resolveStableInversionTimeSpan(catalogId)
    } catch {
      span = null
    }
  }

  const anchor =
    uiStore.currentDate instanceof Date && !Number.isNaN(uiStore.currentDate.getTime())
      ? uiStore.currentDate
      : new Date()
  const fallbackEnd = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate())
  const fallbackStart = new Date(fallbackEnd)
  fallbackStart.setDate(fallbackStart.getDate() - 29) // 无产物时默认 30 天窗

  computeDialogLayerName.value = item?.name ?? catalogId
  computeDialogAvailableStart.value = span?.start ?? ''
  computeDialogAvailableEnd.value = span?.end ?? ''
  computeDialogAvailableFrames.value = span?.frames ?? 0
  computeDialogAlreadyAdded.value = Boolean(opts.alreadyAdded)
  computeDialogIsInversion.value = isInversion
  // 有产物 ⇒ 默认就是产物覆盖区间（点确认即"直接添加"）；无产物 ⇒ 最近 30 天
  computeDialogDefaultStart.value = span ? span.start : toCompactDate(fallbackStart)
  computeDialogDefaultEnd.value = span ? span.end : toCompactDate(fallbackEnd)
  computeDialogBlockMode.value = isBlockInversionCatalog(catalogId)
  computeDialogBusy.value = false
  computeDialogOpen.value = true
  return new Promise((resolve) => {
    computeDialogResolve = resolve
  })
}

function closeComputeDialog(result: ComputeDialogChoice): void {
  computeDialogOpen.value = false
  computeDialogBusy.value = false
  const resolve = computeDialogResolve
  computeDialogResolve = null
  resolve?.(result)
}

/**
 * 用户确认后的分流：
 * - 已添加的图层 ⇒ 一律按所选范围重算（不重复添加）；
 * - 非反演目录 ⇒ 无法判断覆盖，交回原有「先挂产物、再跑」路径；
 * - 反演目录 ⇒ 落在已有范围内挂载、否则提交计算。
 */
function onComputeDialogConfirm(payload: { start: string; end: string; within: boolean }): void {
  if (computeDialogAlreadyAdded.value) {
    closeComputeDialog({ kind: 'compute', start: payload.start, end: payload.end })
    return
  }
  if (!computeDialogIsInversion.value) {
    closeComputeDialog({ kind: 'auto' })
    return
  }
  if (payload.within) {
    closeComputeDialog({ kind: 'attach' })
    return
  }
  closeComputeDialog({ kind: 'compute', start: payload.start, end: payload.end })
}

function onComputeDialogCancel(): void {
  closeComputeDialog(null)
}

function getCatalogSemanticNote(catalogId: string): string | null {
  // overlay 静态/时间序列图层：天然有 PNG 缓存，添加/显示路径不阻断
  if (isOverlayDisplayOnlyLayer(catalogId)) {
    return '静态叠加：已加载缓存影像'
  }
  const blockReason = getCatalogRunBlockReason(catalogId)
  if (blockReason) return blockReason
  const model = weatherEngine.defaultModel
  if (isWeatherLayerUnsupportedByModel(catalogId, model)) {
    return `当前模型（${model}）不提供该图层变量，请切换其他气象模型。`
  }
  const item = getCatalogItem(catalogId)
  if (!item) return null
  if (item.backendStatus === 'sample') {
    return (
      item.runReadinessSummary ??
      item.runReadinessNotes[0] ??
      '实验 provider 链路，可用于算法联调与验收。'
    )
  }
  if (item.backendStatus === 'placeholder') {
    return item.runReadinessSummary ?? item.runReadinessNotes[0] ?? '占位图层，默认数据源尚未接入。'
  }
  return null
}

function catalogSemanticNoteClass(catalogId: string) {
  return getCatalogItem(catalogId)?.backendStatus === 'sample'
    ? 'catalog-note-sample'
    : 'catalog-note-blocked'
}

// ── Catalog 数据源辅助 ───────────────────────────────────────────────────────

function getCatalogSources(catalogId: string) {
  return layerLibrary.value.find((l) => l.catalogId === catalogId)?.sources ?? []
}

function getPrimarySourceName(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  if (!sources.length) return LAYERS_COPY.noDataSource
  return sources[0]?.name ?? LAYERS_COPY.pleaseSelectSource
}

function getCatalogSourceSummary(catalogId: string): string {
  const sources = getCatalogSources(catalogId)
  if (!sources.length) return LAYERS_COPY.noDataSource
  return sources.map((source) => source.name).join(' / ')
}

// ── 分类辅助 ─────────────────────────────────────────────────────────────────

function getCategoryMeta(categoryId: string) {
  return layerCategories.value.find((c) => c.id === categoryId)
}

function getCategoryName(categoryId: string): string {
  return resolveCategoryDisplayName(categoryId)
}

function availabilityClass(state: string) {
  if (state === 'ready') return 'availability-ready'
  if (state === 'partial') return 'availability-partial'
  return 'availability-empty'
}

// ── 基础操作 ─────────────────────────────────────────────────────────────────

function openLibrary() {
  workspace.setSidebarView('library')
  void nextTick(() => scrollSidebarChromeIntoView())
}

function openActive() {
  workspace.setSidebarView('active')
  void nextTick(() => scrollSidebarChromeIntoView())
}

/**
 * 行尾 ⓘ：选中该图层并打开右侧信息面板（2026-10-19）。
 * 复用既有 analysisFocusRequest 机制：`#layer-<instanceId>` 是信息面板
 * 「选中图层」区块的 id；找不到时回退到顶部总览，保证面板一定会展开。
 */
function openLayerDetails(instanceId: string) {
  selectItem(instanceId)
  uiStore.requestAnalysisFocus([`layer-${instanceId}`, 'global-overview'])
}

function addCatalogItem(
  catalogId: string,
  isAdminBoundary = false,
  opts: { skipDialog?: boolean } = {},
) {
  // 2026-10-17 用户要求：已在列表中的图层点「添加」也要弹时间范围框，
  // 用于按新范围重算（确认后只提交计算，不会重复添加图层）。
  if (!isAdminBoundary && isAdded(catalogId)) {
    if (!opts.skipDialog) void promptRecomputeForExisting(catalogId)
    return
  }
  // skipAutoRun：由下方 ensureLayerDataOrRun 统一「先复用产物 / 再提交」，
  // 避免 addLayer 内置 setTimeout 再跑一遍造成双提交与游离层泄漏
  workspace.addLayer(catalogId, isAdminBoundary, undefined, { skipAutoRun: true })
  logStore.logOperation(
    'layer-add',
    `添加图层「${catalogId}」`,
    isAdminBoundary ? '行政区边界' : undefined,
  )
  // 2026-08-25 添加即运行：有缓存/产物直接附加；无则自动提交工作流
  if (catalogId !== 'gebco-dem-cn') {
    void ensureLayerDataOrRun(catalogId, { skipDialog: opts.skipDialog })
  }
}

function addAllInCategory(
  items: { catalogId: string; isAdminBoundary?: boolean; sources?: { id: string }[] }[],
) {
  const alreadyAdded = new Set(addedCatalogIds.value)
  for (const item of items) {
    if (item.isAdminBoundary) continue
    const effectiveId =
      item.sources && item.sources.length > 1 ? item.sources[0].id : item.catalogId
    if (alreadyAdded.has(effectiveId)) continue
    alreadyAdded.add(effectiveId)
    // 批量添加不逐个弹时间范围框（否则会连弹 N 个），保持原有"先挂后算"
    addCatalogItem(effectiveId, false, { skipDialog: true })
  }
}

function showAllLayers() {
  workspace.setAllLayerVisibility(true)
}

function hideAllLayers() {
  workspace.setAllLayerVisibility(false)
}

/**
 * 清空全部图层（2026-10-20）：原批量栏「全部移除」与头部垃圾桶共用。
 * 二次确认放在这里——这是不可撤销操作，且头部按钮紧邻「+」，误点代价高。
 */
function removeAllLayers() {
  const count = activeLayersDisplay.value.length
  if (count === 0) return
  if (!window.confirm(`确定清空全部 ${count} 个图层？此操作不可撤销。`)) return
  workspace.removeAllLayers()
}

function removeItem(instanceId: string, event: MouseEvent) {
  event.stopPropagation()
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === instanceId)
  const isActiveDrawLayer =
    drawStore.draftLayerId === instanceId || drawStore.editingLayerId === instanceId
  const hasUnsaved = drawStore.features.length > 0
  // 移除当前绘制/编辑图层且含未保存要素时确认，避免误删草稿
  if (isActiveDrawLayer && hasUnsaved) {
    const ok = window.confirm(
      `「${layer?.name ?? instanceId}」是当前绘制图层且包含 ${hasUnsaved ? drawStore.features.length : 0} 个未保存要素，移除后将丢失这些要素。确定移除并退出绘制模式？`,
    )
    if (!ok) return
  }
  // 只从面板移除，**不删除后端产物目录**（2026-10-11 用户确认：移除 ≠ 删数据）。
  // 数据删除请到「数据管理器」里操作。
  workspace.removeLayer(instanceId, { deleteBackendFile: false })
  // 移除的是当前绘制/编辑图层时，退出绘制模式（孤儿草稿安全网会随之清空绘制 store）
  if (isActiveDrawLayer && uiStore.interactionMode === 'draw') {
    void requestInteractionMode('move')
  }
  logStore.logOperation('layer-remove', `移除图层「${layer?.name ?? instanceId}」`)
}

function selectItem(instanceId: string) {
  workspace.selectLayer(instanceId)
  emit('selectLayer', instanceId)
}

function zoomToItem(instanceId: string) {
  selectItem(instanceId)
  emit('zoomToLayer', instanceId)
}

function toggleVisibility(instanceId: string, event: MouseEvent) {
  event.stopPropagation()
  const layer = activeLayersDisplay.value.find((l) => l.instanceId === instanceId)
  workspace.toggleLayerVisibility(instanceId)
  logStore.logOperation(
    'layer-visibility',
    `${layer?.visible ? '隐藏' : '显示'}图层「${layer?.name ?? instanceId}」`,
  )
}

function toggleCategory(categoryId: string) {
  if (search.expandedCategories.value.has(categoryId)) {
    search.expandedCategories.value.delete(categoryId)
  } else {
    search.expandedCategories.value.add(categoryId)
  }
}

// ── 滚动管理 ─────────────────────────────────────────────────────────────────

const sidebarRootEl = ref<HTMLElement | null>(null)

function scrollSidebarChromeIntoView() {
  const root = sidebarRootEl.value
  if (!root) return
  root.scrollTop = 0
  const panelBody = root.closest('.panel-body') as HTMLElement | null
  if (panelBody) panelBody.scrollTop = 0
  const libraryScroll = root.querySelector('.library-scroll') as HTMLElement | null
  if (libraryScroll) libraryScroll.scrollTop = 0
  const layerList = root.querySelector('.layer-list') as HTMLElement | null
  if (layerList) layerList.scrollTop = 0
}

watch(sidebarView, () => {
  void nextTick(() => scrollSidebarChromeIntoView())
})

// ── Symbology 预取 ───────────────────────────────────────────────────────────

watch(
  activeLayersDisplay,
  (layers) => {
    for (const layer of layers) {
      if (layer.isImported || layer.isImportedRaster || layer.isAdminBoundary) continue
      if (!layer.renderHint && !overlaySymbologyStore.shouldSkipFetch(layer.catalogId)) {
        void overlaySymbologyStore.ensureMeta(layer.catalogId)
      }
    }
  },
  { flush: 'post' },
)

onMounted(() => {
  search.prefetchVisibleWeatherProviders()
})
</script>

<template>
  <aside ref="sidebarRootEl" class="panel">
    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <LayerSidebarHeader
      :sidebar-view-label="sidebarViewLabel"
      :sidebar-view="sidebarView"
      :active-layer-count="activeLayerCount"
      :can-manage-groups="authStore.isAdmin"
      @open-library="openLibrary"
      @open-active="openActive"
      @open-group-manager="groupManagerOpen = true"
      @clear-layers="removeAllLayers"
    />

    <!-- ── EMPTY STATE ────────────────────────────────────────────────── -->
    <div v-if="sidebarView === 'empty'" class="empty-state">
      <Diamond :size="20" class="empty-icon" aria-hidden="true" />
      <p class="empty-title">{{ LAYERS_COPY.emptyTitle }}</p>
      <p class="empty-hint">点击下方按钮打开图层库，<br />添加气象、遥感或边界图层。</p>
      <button class="empty-cta" @click="openLibrary">
        <span aria-hidden="true">+</span>
        打开图层库
      </button>
    </div>

    <!-- ── LIBRARY STATE ──────────────────────────────────────────────── -->
    <LayerSidebarLibrary
      v-else-if="sidebarView === 'library'"
      :search-query="search.searchQuery.value"
      :selected-sub-category="search.selectedSubCategory.value"
      :filtered-library-by-category="search.filteredLibraryByCategory.value"
      :research-sub-category-pills="search.researchSubCategoryPills.value"
      :expanded-categories="search.expandedCategories.value"
      :is-added="isAdded"
      :weather-providers-loading="weatherProviders.weatherProvidersLoading.value"
      :weather-source-prefs-value="(catalogId: string) => weatherSourcePrefs.getProvider(catalogId)"
      :weather-providers-for="weatherProviders.weatherProvidersFor"
      :weather-provider-option-label="weatherProviders.weatherProviderOptionLabel"
      :weather-source-quality-hint="weatherProviders.weatherSourceQualityHint"
      :weather-source-sparse-hint="weatherProviders.weatherSourceSparseHint"
      :get-catalog-job-status="getCatalogJobStatus"
      :get-catalog-run-block-reason="getCatalogRunBlockReason"
      :get-catalog-add-block-reason="getCatalogAddBlockReason"
      :is-overlay-display-only-layer="isOverlayDisplayOnlyLayer"
      :get-catalog-semantic-note="getCatalogSemanticNote"
      :catalog-semantic-note-class="catalogSemanticNoteClass"
      :get-category-meta="getCategoryMeta"
      :get-category-name="getCategoryName"
      :get-catalog-source-summary="getCatalogSourceSummary"
      :get-primary-source-name="getPrimarySourceName"
      :supports-online-temporal="supportsOnlineTemporal"
      @update:search-query="search.searchQuery.value = $event"
      @update:selected-sub-category="search.selectedSubCategory.value = $event"
      @ensure-weather-providers="weatherProviders.ensureWeatherProviders"
      @on-weather-source-change="weatherProviders.onWeatherSourceChange"
      @add-all-in-category="addAllInCategory"
      @add-catalog-item="addCatalogItem"
      @recompute-catalog-item="promptRecomputeForExisting"
      @toggle-category="toggleCategory"
    />

    <!-- ── ACTIVE STATE ───────────────────────────────────────────────── -->
    <LayerSidebarActive
      v-else-if="sidebarView === 'active'"
      :active-layers-display="activeLayersDisplay"
      :active-toc-rows="drag.activeTocRows.value"
      :selected-instance-id="selectedInstanceId"
      :drag-over-instance-id="drag.dragOverInstanceId.value"
      :drag-over-group-id="drag.dragOverGroupId.value"
      :run-group-of="drag.runGroupOf"
      :group-status-label="drag.groupStatusLabel"
      :has-color-symbology="symbology.hasColorSymbology"
      :get-color-ramp-style="symbology.getColorRampStyle"
      :get-symbology-unit="symbology.getSymbologyUnit"
      :get-symbology-vmin="symbology.getSymbologyVmin"
      :get-symbology-vmax="symbology.getSymbologyVmax"
      :availability-class="availabilityClass"
      :get-category-name="getCategoryName"
      :supports-online-temporal="supportsOnlineTemporal"
      :get-source-route-badge="getSourceRouteBadge"
      :cycle-source-route="cycleSourceRoute"
      :get-unified-data-status="getUnifiedDataStatus"
      :is-online-plan-pending="isOnlinePlanPending"
      :open-online-plan="openOnlinePlan"
      @select-item="selectItem"
      @zoom-to-item="zoomToItem"
      @toggle-visibility="toggleVisibility"
      @remove-item="removeItem"
      @open-job-report="ctxMenu.openJobReport"
      @open-layer-details="openLayerDetails"
      @show-all-layers="showAllLayers"
      @hide-all-layers="hideAllLayers"
      @remove-all-layers="removeAllLayers"
      @open-library="openLibrary"
      @on-drag-start="drag.onDragStart"
      @on-group-drag-start="drag.onGroupDragStart"
      @on-drag-over="drag.onDragOver"
      @on-group-drag-over="drag.onGroupDragOver"
      @on-drop="drag.onDrop"
      @on-group-drop="drag.onGroupDrop"
      @on-drag-end="drag.onDragEnd"
      @on-layer-context-menu="ctxMenu.onLayerContextMenu"
      @on-group-context-menu="ctxMenu.onGroupContextMenu"
      @toggle-group="drag.toggleGroupCollapsed"
    />

    <!-- ── Footer ─────────────────────────────────────────────────────── -->
    <p v-if="sidebarView === 'library'" class="panel-footnote">选择图层添加到地图</p>

    <!-- ── 右键上下文菜单 ──────────────────────────────────────────────── -->
    <LayerSidebarContextMenu
      :context-menu="ctxMenu.contextMenu.value"
      :context-menu-groups="ctxMenu.contextMenuGroups.value"
      @handle-context-action="ctxMenu.handleContextAction"
    />
    <!-- ── 「添加图层」时间范围对话框 ──────────────────────────────────── -->
    <AddLayerComputeDialog
      :open="computeDialogOpen"
      :layer-name="computeDialogLayerName"
      :default-start="computeDialogDefaultStart"
      :default-end="computeDialogDefaultEnd"
      :block-mode="computeDialogBlockMode"
      :busy="computeDialogBusy"
      :available-start="computeDialogAvailableStart"
      :available-end="computeDialogAvailableEnd"
      :available-frames="computeDialogAvailableFrames"
      :already-added="computeDialogAlreadyAdded"
      @confirm="onComputeDialogConfirm"
      @cancel="onComputeDialogCancel"
    />
    <!-- ── 图层平台 P1：分组管理对话框（仅管理员） ─────────────────────── -->
    <LayerGroupManagerDialog
      v-if="authStore.isAdmin"
      :open="groupManagerOpen"
      :initial-theme-id="groupManagerThemeId"
      @close="closeGroupManager"
    />
  </aside>
</template>

<style scoped src="./layer-sidebar/LayerSidebar.styles.css"></style>
