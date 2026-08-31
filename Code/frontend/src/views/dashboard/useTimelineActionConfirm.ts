/**
 * useTimelineActionConfirm — 时间轴改轴 2s 防抖确认 + 失败 notice + 重跑/复用。
 */
import { onScopeDispose, watch, type ComputedRef, type Ref } from 'vue'

import {
  TIMELINE_CONFIRM_DEBOUNCE_MS,
  useTimelineActionBannerStore,
} from '../../stores/timeline-action-banner'
import {
  buildTimeKey,
  buildTimeRangeFromKey,
} from '../../stores/layers/online-temporal-orchestrator'
import type { TimeGranularity } from '../../utils/layer-timeline'
import {
  INPUT_KEY_TIME_WINDOW_ALIGN,
  fetchDataInputPolicies,
  resolveAlignPolicyMode,
} from '../../services/data-input-policies-api'
import { isCoverageGapFailure } from '../../utils/workflow-error-messages'
import {
  shouldConfirmSwitchOnlineOnCoverageGap,
  shouldSilentSwitchOnlineOnCoverageGap,
  resolveSourceRoutePolicyMode,
} from '../../utils/source-route-policy'
import type { useLayerWorkspace, useWorkflowRun } from '../../stores/layers/selectors'
import type { useUiStore } from '../../stores/ui'
import {
  ONLINE_PLAN_ESCALATE_AFTER,
  useOnlinePlanSessionStore,
} from '../../stores/online-plan-session'
import {
  descriptorHasOnlineWorkflowVariant,
  loadOnlinePlanParamDefaults,
} from '../../utils/online-plan-params'

/** 目录层可作重跑目标；排除计算组占位 / 导入游离层 / 草稿 */
function isRerunnableCatalogId(catalogId: string): boolean {
  const id = String(catalogId || '').trim()
  if (!id) return false
  if (/^wf-(?:run|out)-/i.test(id)) return false
  if (/^imported-/i.test(id)) return false
  if (/^draw-/i.test(id)) return false
  return true
}

export function useTimelineActionConfirm(deps: {
  workspace: ReturnType<typeof useLayerWorkspace>
  workflowRun: ReturnType<typeof useWorkflowRun>
  uiStore: ReturnType<typeof useUiStore>
  selectedCatalogId: ComputedRef<string | null>
  currentDate: Ref<Date>
  currentHour: Ref<number>
  activeLayerGranularity: ComputedRef<TimeGranularity | string>
  isPlaying: Ref<boolean>
  logOperation: (tag: string, message: string) => void
  /** 主时间轴停稳后同步打开的工作流编辑器 bind_timeline 节点 */
  syncBoundWorkflowTimeline?: (range: { start_at: string; end_at: string; timeKey: string }) => void
}) {
  const banner = useTimelineActionBannerStore()
  const planSession = useOnlinePlanSessionStore()
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let policiesCache: Awaited<ReturnType<typeof fetchDataInputPolicies>> | null = null
  let lastFailedNoticeToken = ''
  /** 跳过首帧，避免挂载即弹确认卡 */
  let skipNextDebounce = true

  function clearDebounce() {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
  }

  function currentTimeKey(): string | null {
    const gran = (deps.activeLayerGranularity.value || 'day') as TimeGranularity
    if (gran === 'static') return null
    return buildTimeKey(deps.currentDate.value, deps.currentHour.value, gran)
  }

  function collectTargetCatalogIds(): string[] {
    if (!deps.uiStore.unifiedTimeLock) {
      const id = deps.selectedCatalogId.value
      if (!id || !isRerunnableCatalogId(id)) return []
      // 独立记忆：当前选中源（含合并卡下某一数据源）
      return [id]
    }
    // 统一记忆：所有已添加、可分析、带时间的目录源；同一 catalogId 去重
    // （多源合并卡的各源是不同 catalogId，会一并列入）
    const seen = new Set<string>()
    const ids: string[] = []
    for (const layer of deps.workspace.activeLayers.value) {
      if (layer.isAdminBoundary) continue
      if (layer.importedRaster || layer.importedVector) {
        // 仅目录分析层；带产物的 method-* 父卡仍可重跑
        if (!isRerunnableCatalogId(layer.catalogId)) continue
      }
      if (!isRerunnableCatalogId(layer.catalogId)) continue
      if (deps.workspace.isWeatherEngineLayer(layer.catalogId)) continue
      const item = deps.workspace.layerLibrary.value.find((x) => x.catalogId === layer.catalogId)
      if (item?.supportsTime === false) continue
      if (!(deps.workspace.supportsAnalysisWorkflow?.(layer.catalogId) ?? true)) continue
      if (seen.has(layer.catalogId)) continue
      seen.add(layer.catalogId)
      ids.push(layer.catalogId)
    }
    return ids
  }

  function resolveScopeMeta(catalogIds: string[]): { scopeLabel: string; layerHint: string } {
    const names = catalogIds.map((id) => {
      const lib = deps.workspace.layerLibrary.value.find((x) => x.catalogId === id)
      const active = deps.workspace.activeLayers.value.find((l) => l.catalogId === id)
      // 合并组成员：优先库卡名（具体数据源），便于「一图层多源」辨认
      return lib?.name || active?.name || id
    })
    const hint = names.join('、')
    if (!deps.uiStore.unifiedTimeLock) {
      const short = names[0] && names[0].length > 10 ? `${names[0].slice(0, 9)}…` : names[0]
      return { scopeLabel: `独立·${short || '当前源'}`, layerHint: hint || '当前选中数据源' }
    }
    if (catalogIds.length <= 1) {
      const short = names[0] && names[0].length > 10 ? `${names[0].slice(0, 9)}…` : names[0]
      return { scopeLabel: `统一·${short || '1层'}`, layerHint: hint }
    }
    return {
      scopeLabel: `统一·${catalogIds.length}源`,
      layerHint: hint,
    }
  }

  function pushTimelineToWorkflowEditor(timeKey: string) {
    if (!deps.syncBoundWorkflowTimeline) return
    const primary = collectTargetCatalogIds()[0] || deps.selectedCatalogId.value
    const cap = primary ? deps.workspace.getOnlineTemporalConfig(primary) : null
    const gran = (deps.activeLayerGranularity.value || 'day') as TimeGranularity
    const nativeStep = cap?.native_step || '1d'
    const range = buildTimeRangeFromKey(timeKey, nativeStep, gran)
    if (!range?.start_at || !range?.end_at) return
    deps.syncBoundWorkflowTimeline({
      start_at: range.start_at,
      end_at: range.end_at,
      timeKey,
    })
  }

  async function ensurePolicies() {
    if (policiesCache) return policiesCache
    try {
      policiesCache = await fetchDataInputPolicies()
    } catch {
      policiesCache = { version: 1, policies: [] }
    }
    return policiesCache
  }

  async function openConfirmForAxisChange() {
    if (banner.isConfirmSuppressed()) return
    if (deps.isPlaying.value) return
    const timeKey = currentTimeKey()
    if (!timeKey) return
    const catalogIds = collectTargetCatalogIds()
    // 即使无可重跑图层，仍同步打开的工作流画布时间窗
    pushTimelineToWorkflowEditor(timeKey)
    if (!catalogIds.length) return

    const conf = banner.confirm
    if (
      conf &&
      conf.timeKey === timeKey &&
      conf.catalogIds.length === catalogIds.length &&
      conf.catalogIds.every((id, i) => id === catalogIds[i])
    ) {
      return
    }

    const policyDoc = await ensurePolicies()
    if (banner.isConfirmSuppressed() || deps.isPlaying.value) return
    if (currentTimeKey() !== timeKey) return

    let canReuse = false
    for (const id of catalogIds) {
      try {
        if (await deps.workflowRun.hasReusableProductsForTime(id, timeKey)) {
          canReuse = true
          break
        }
      } catch {
        /* ignore */
      }
    }

    const primary = catalogIds[0]
    const descriptor = deps.workspace.resolveEffectiveDescriptor?.(primary) ?? null
    const moduleName =
      (typeof descriptor?.module_name === 'string' && descriptor.module_name.trim()) || undefined
    const alignMode = resolveAlignPolicyMode(policyDoc.policies, {
      layerId: primary,
      module: moduleName,
    })
    const alignOffer =
      alignMode === 'allow_with_confirm'
        ? {
            inputKey: INPUT_KEY_TIME_WINDOW_ALIGN as 'time_window_align_on_zero_intersection',
            label: '零交集时对齐到本地可用窗',
            defaultChecked: false,
          }
        : null

    const { scopeLabel, layerHint } = resolveScopeMeta(catalogIds)
    banner.showConfirm({
      timeKey,
      catalogIds,
      canReuse,
      alignOffer,
      scopeLabel,
      layerHint,
    })
  }

  watch(
    () => [deps.currentDate.value.getTime(), deps.currentHour.value, deps.isPlaying.value] as const,
    () => {
      clearDebounce()
      if (skipNextDebounce) {
        skipNextDebounce = false
        return
      }
      if (deps.isPlaying.value) return
      if (banner.isConfirmSuppressed()) return
      if (deps.activeLayerGranularity.value === 'static') return
      debounceTimer = setTimeout(() => {
        debounceTimer = null
        if (deps.isPlaying.value) return
        if (banner.isConfirmSuppressed()) return
        void openConfirmForAxisChange()
      }, TIMELINE_CONFIRM_DEBOUNCE_MS)
    },
  )

  watch(
    () =>
      deps.workflowRun.jobLayers.value
        .map((j) => `${j.jobId}:${j.status}:${j.message || ''}:${j.failureCategory || ''}`)
        .join('|'),
    (joined, prevJoined) => {
      void joined
      if (prevJoined === undefined || prevJoined === '') return
      if (banner.hasConfirm) return

      // 成功跑通 → 清零该 catalog 失败计数（JobStatus 无 completed，仅 succeeded）
      for (const j of deps.workflowRun.jobLayers.value) {
        if (j.status !== 'succeeded') continue
        const cid = j.catalogId || ''
        if (!cid) continue
        const wasNotSuccess =
          typeof prevJoined === 'string' && !prevJoined.includes(`${j.jobId}:succeeded:`)
        if (wasNotSuccess) planSession.clearFailCount(cid)
      }

      const failed = deps.workflowRun.jobLayers.value.find((j) => j.status === 'failed')
      if (!failed) return
      const token = `${failed.jobId}:${failed.message || ''}:${failed.failureCategory || ''}`
      if (token === lastFailedNoticeToken) return
      const wasAlreadyFailed =
        typeof prevJoined === 'string' && prevJoined.includes(`${failed.jobId}:failed:`)
      if (wasAlreadyFailed && prevJoined.includes(token)) return
      lastFailedNoticeToken = token
      const msg = failed.message || failed.reportSummary || '工作流失败。可改选时间轴后重试。'
      const catalogId = failed.catalogId || ''
      if (catalogId && isEligibleCoverageGap(failed, catalogId)) {
        void handleCoverageGapEscalation(failed, catalogId, msg)
        return
      }
      banner.showNotice({
        message: msg,
        catalogId: failed.catalogId,
        tone: 'error',
      })
    },
  )

  /** P2：仅 descriptor.workflow_variants.online，无前端 catalog 白名单 */
  function catalogHasOnlineVariant(catalogId: string): boolean {
    const desc = deps.workspace.resolveEffectiveDescriptor?.(catalogId) ?? null
    return descriptorHasOnlineWorkflowVariant(
      desc as { workflow_variants?: Record<string, unknown> | null } | null,
    )
  }

  /** 1B：有 workflow_variants.online 且 coverage_gap 即可计次/升级（不要求偏好已是 online） */
  function isEligibleCoverageGap(
    failed: {
      failureCategory?: string
      diagnostics?: string[]
      message?: string
      reportSummary?: string
    },
    catalogId: string,
  ): boolean {
    if (!isCoverageGapFailure(failed)) return false
    return catalogHasOnlineVariant(catalogId)
  }

  function currentPreferenceIsOnline(catalogId: string): boolean {
    const backendId = deps.workspace.resolveBackendLayerId?.(catalogId) ?? catalogId
    const pref =
      deps.workflowRun.getWorkflowVariantPreference?.(catalogId) ??
      deps.workflowRun.getWorkflowVariantPreference?.(backendId)
    return pref === 'online'
  }

  function layerDisplayName(catalogId: string): string {
    const lib = deps.workspace.layerLibrary.value.find((x) => x.catalogId === catalogId)
    const active = deps.workspace.activeLayers.value.find((l) => l.catalogId === catalogId)
    return lib?.name || active?.name || catalogId
  }

  async function handleCoverageGapEscalation(
    failed: { jobId?: string; message?: string; reportSummary?: string },
    catalogId: string,
    msg: string,
  ) {
    const timeKey = currentTimeKey()
    const gran = (deps.activeLayerGranularity.value || 'day') as TimeGranularity
    const cap = deps.workspace.getOnlineTemporalConfig(catalogId)
    const nativeStep = cap?.native_step || '1d'
    const timeRange = timeKey
      ? (buildTimeRangeFromKey(timeKey, nativeStep, gran) ?? undefined)
      : undefined

    // 源路由策略：每次重新拉取，避免 admin PUT 后缓存陈旧
    let routeMode: 'deny' | 'allow_with_confirm' | 'allow_silent'
    try {
      policiesCache = await fetchDataInputPolicies()
      const desc = deps.workspace.resolveEffectiveDescriptor?.(catalogId) ?? null
      routeMode = resolveSourceRoutePolicyMode(policiesCache.policies, {
        layerId: catalogId,
        module: (desc as { module_name?: string } | null)?.module_name,
        workflowId:
          (desc as { workflow_id?: string } | null)?.workflow_id ??
          (desc as { workflow_name?: string } | null)?.workflow_name,
      })
    } catch {
      routeMode = 'deny'
    }

    if (shouldSilentSwitchOnlineOnCoverageGap(routeMode) && !currentPreferenceIsOnline(catalogId)) {
      banner.dismissRecovery()
      banner.dismissNotice()
      try {
        deps.workflowRun.setWorkflowVariantPreference(catalogId, 'online', { pinned: true })
        const backendId = deps.workspace.resolveBackendLayerId?.(catalogId) ?? catalogId
        if (backendId !== catalogId) {
          deps.workflowRun.setWorkflowVariantPreference(backendId, 'online', { pinned: true })
        }
        const ok = await switchOnlineRerunForCatalog(catalogId, timeKey)
        if (ok) {
          banner.showNotice({
            message: '本地缺数，已按源路由策略自动改走在线。',
            catalogId,
            tone: 'info',
          })
        }
      } catch (err) {
        banner.showNotice({
          message: err instanceof Error ? err.message : String(err),
          catalogId,
          tone: 'error',
        })
      }
      return
    }

    const count = planSession.incrementFailCount(catalogId)
    const preferOnline = currentPreferenceIsOnline(catalogId)

    if (count >= ONLINE_PLAN_ESCALATE_AFTER) {
      const desc = deps.workspace.resolveEffectiveDescriptor?.(catalogId) ?? null
      const paramOverrides = await loadOnlinePlanParamDefaults(
        desc as { workflow_variants?: Record<string, { workflow_id?: string }> | null },
      )
      planSession.ensureTab(catalogId, {
        lastFailMessage: msg,
        lastJobId: failed.jobId,
        timeKey,
        timeRange: timeRange
          ? { start_at: timeRange.start_at, end_at: timeRange.end_at, granularity: gran }
          : undefined,
        preferredVariant: 'online',
        displayName: layerDisplayName(catalogId),
        paramOverrides,
      })
      // L1：直接拉起面板；勿再叠 notice（backdrop 会挡住 Banner，造成残留反馈）
      banner.dismissRecovery()
      banner.dismissNotice()
      return
    }

    // L0：第 1–2 次 — 可切在线（偏好非 online）+ 可提前打开计划
    // allow_with_confirm：必须带 switch_online，促使用户确认
    const offers: Array<'switch_online' | 'open_plan'> = ['open_plan']
    if (!preferOnline || shouldConfirmSwitchOnlineOnCoverageGap(routeMode)) {
      if (!offers.includes('switch_online')) offers.unshift('switch_online')
    }
    banner.showRecovery({
      catalogId,
      message: msg,
      timeKey,
      offers,
    })
  }

  /** @deprecated 保留给测试/外部：L0 是否推销切在线（偏好≠online） */
  function shouldOfferSwitchOnlineRecovery(
    failed: {
      failureCategory?: string
      diagnostics?: string[]
      message?: string
      reportSummary?: string
    },
    catalogId: string,
  ): boolean {
    if (!isEligibleCoverageGap(failed, catalogId)) return false
    return !currentPreferenceIsOnline(catalogId)
  }

  async function handleReuse() {
    const conf = banner.confirm
    if (!conf) return
    const { timeKey, catalogIds } = conf
    banner.dismissConfirm()
    pushTimelineToWorkflowEditor(timeKey)
    for (const catalogId of catalogIds) {
      try {
        const n = await deps.workflowRun.autoAttachProductsForNewLayer(catalogId, {
          preferredTimeKey: timeKey,
        })
        if (n > 0) {
          deps.uiStore.rememberLayerTime(catalogId, { force: true })
          deps.logOperation('timeline-reuse', `复用产物 ${catalogId} @ ${timeKey}`)
        } else {
          banner.showNotice({
            message: `无覆盖 ${timeKey} 的产物，可改选重跑。`,
            catalogId,
            tone: 'info',
          })
        }
      } catch (err) {
        banner.showNotice({
          message: err instanceof Error ? err.message : String(err),
          catalogId,
          tone: 'error',
        })
      }
    }
  }

  async function handleRerun() {
    const conf = banner.confirm
    if (!conf) return
    const align = banner.alignChecked
    const { timeKey, catalogIds } = conf
    banner.dismissConfirm()
    pushTimelineToWorkflowEditor(timeKey)

    const gran = (deps.activeLayerGranularity.value || 'day') as TimeGranularity
    for (const catalogId of catalogIds) {
      try {
        deps.workflowRun.interruptWorkflowForCatalog(catalogId)
        const job = deps.workflowRun.jobLayers.value.find(
          (j) => j.catalogId === catalogId && (j.status === 'running' || j.status === 'queued'),
        )
        if (job) {
          await deps.workflowRun
            .cancelWorkflowRunForJob(job.jobId, catalogId)
            .catch(() => undefined)
        }

        const cap = deps.workspace.getOnlineTemporalConfig(catalogId)
        const nativeStep = cap?.native_step || '1d'
        const timeRange = buildTimeRangeFromKey(timeKey, nativeStep, gran) ?? undefined
        const algorithmParams: Record<string, unknown> = {}
        if (align) {
          algorithmParams.relax_flags = {
            [INPUT_KEY_TIME_WINDOW_ALIGN]: true,
          }
        }
        await deps.workflowRun.runWorkflowForCatalog(catalogId, {
          timeRange,
          algorithmRequest: Object.keys(algorithmParams).length
            ? { algorithm_params: algorithmParams }
            : undefined,
          commandLabel: `按时间轴重跑 ${timeKey}`,
        })
        deps.uiStore.rememberLayerTime(catalogId, { force: true })
        deps.logOperation(
          'timeline-rerun',
          `重跑 ${catalogId} @ ${timeKey}${align ? '（启用时间窗对齐）' : ''}`,
        )
      } catch (err) {
        banner.showNotice({
          message: err instanceof Error ? err.message : String(err),
          catalogId,
          tone: 'error',
        })
      }
    }
  }

  function handleCancelConfirm() {
    banner.dismissConfirm()
  }

  function handleDismissNotice() {
    banner.dismissNotice()
  }

  function handleDismissRecovery() {
    banner.dismissRecovery()
  }

  function handleOpenPlan() {
    const rec = banner.recovery
    const catalogId = rec?.catalogId
    banner.dismissRecovery()
    if (catalogId) {
      const timeKey = rec?.timeKey || currentTimeKey()
      const gran = (deps.activeLayerGranularity.value || 'day') as TimeGranularity
      const cap = deps.workspace.getOnlineTemporalConfig(catalogId)
      const nativeStep = cap?.native_step || '1d'
      const timeRange = timeKey
        ? (buildTimeRangeFromKey(timeKey, nativeStep, gran) ?? undefined)
        : undefined
      void (async () => {
        const desc = deps.workspace.resolveEffectiveDescriptor?.(catalogId) ?? null
        const paramOverrides = await loadOnlinePlanParamDefaults(
          desc as { workflow_variants?: Record<string, { workflow_id?: string }> | null },
        )
        planSession.ensureTab(catalogId, {
          lastFailMessage: rec?.message,
          timeKey,
          timeRange: timeRange
            ? { start_at: timeRange.start_at, end_at: timeRange.end_at, granularity: gran }
            : undefined,
          preferredVariant: 'online',
          displayName: layerDisplayName(catalogId),
          paramOverrides,
        })
      })()
      return
    }
    planSession.openSession()
  }

  function resolveOnlineBlockedReason(catalogId: string): string | null {
    const backendId = deps.workspace.resolveBackendLayerId?.(catalogId) ?? catalogId
    const desc =
      deps.workspace.resolveEffectiveDescriptor?.(catalogId) ??
      deps.workspace.resolveEffectiveDescriptor?.(backendId) ??
      null
    const onlineReady = (desc as { online_ready?: boolean | null } | null)?.online_ready
    if (onlineReady === false) {
      return (
        (desc as { run_readiness_summary?: string | null } | null)?.run_readiness_summary ||
        '在线变体凭据未就绪'
      )
    }
    // 无变体投影时回落全层阻断（天气/静态等）
    return (
      deps.workspace.getCatalogRunBlockReason?.(catalogId) ??
      deps.workspace.getCatalogRunBlockReason?.(backendId) ??
      null
    )
  }

  /** 切在线并重跑；成功提交返回 true（凭据阻断返回 false，不抛）。 */
  async function switchOnlineRerunForCatalog(
    catalogId: string,
    timeKey?: string | null,
  ): Promise<boolean> {
    const block = resolveOnlineBlockedReason(catalogId)
    if (block) {
      banner.showNotice({
        message: `${block}（请先在设置中配置在线数据源凭据后再切换在线重跑）`,
        catalogId,
        tone: 'error',
      })
      return false
    }

    deps.workflowRun.setWorkflowVariantPreference(catalogId, 'online', { pinned: true })
    const backendId = deps.workspace.resolveBackendLayerId?.(catalogId) ?? catalogId
    if (backendId !== catalogId) {
      deps.workflowRun.setWorkflowVariantPreference(backendId, 'online', { pinned: true })
    }

    deps.workflowRun.interruptWorkflowForCatalog(catalogId)
    const job = deps.workflowRun.jobLayers.value.find(
      (j) => j.catalogId === catalogId && (j.status === 'running' || j.status === 'queued'),
    )
    if (job) {
      await deps.workflowRun.cancelWorkflowRunForJob(job.jobId, catalogId).catch(() => undefined)
    }

    const gran = (deps.activeLayerGranularity.value || 'day') as TimeGranularity
    const key = timeKey || currentTimeKey()
    const cap = deps.workspace.getOnlineTemporalConfig(catalogId)
    const nativeStep = cap?.native_step || '1d'
    const timeRange = key ? (buildTimeRangeFromKey(key, nativeStep, gran) ?? undefined) : undefined

    await deps.workflowRun.runWorkflowForCatalog(catalogId, {
      workflowVariant: 'online',
      timeRange,
      commandLabel: key ? `切换在线并重跑 ${key}` : '切换在线并重跑',
    })
    if (key) deps.uiStore.rememberLayerTime(catalogId, { force: true })
    deps.logOperation(
      'timeline-switch-online',
      `切换在线重跑 ${catalogId}${key ? ` @ ${key}` : ''}`,
    )
    return true
  }

  async function handleSwitchOnlineRerun(): Promise<boolean> {
    const rec = banner.recovery
    if (!rec) return false
    const { catalogId, timeKey } = rec
    banner.dismissRecovery()
    try {
      return await switchOnlineRerunForCatalog(catalogId, timeKey)
    } catch (err) {
      banner.showNotice({
        message: err instanceof Error ? err.message : String(err),
        catalogId,
        tone: 'error',
      })
      return false
    }
  }

  /** 编辑器刚打开时立即对齐一次（不等改轴防抖） */
  function syncWorkflowTimelineNow() {
    const timeKey = currentTimeKey()
    if (timeKey) pushTimelineToWorkflowEditor(timeKey)
  }

  onScopeDispose(() => {
    clearDebounce()
  })

  return {
    banner,
    handleReuse,
    handleRerun,
    handleCancelConfirm,
    handleDismissNotice,
    handleDismissRecovery,
    handleSwitchOnlineRerun,
    handleOpenPlan,
    syncWorkflowTimelineNow,
    /** 测试用 */
    shouldOfferSwitchOnlineRecovery,
  }
}
