import { computed, type ComputedRef } from 'vue'

import type { ActiveLayerDisplay, JobLayerItem, LayerHotspot } from '../../stores/layers/types'
import type { LayerTileStats } from '../../stores/weather-tile-types'
import { useLayerWorkspace, useWorkflowRun } from '../../stores/layers/selectors'
import { ANALYSIS_COPY, ONLINE_PLAN_COPY } from '../../ui-copy'
import { useOnlinePlanSessionStore } from '../../stores/online-plan-session'
import { resolveWeatherWorkflowStage } from '../../utils/weather-tile-readiness'
import {
  resolveAnalysisStageKind,
  resolveStaticLayerHint,
  resolveWorkflowStageCopy,
} from './analysis-panel-summary'
import type { ResultDisplayModel } from './result-adapter'

/**
 * 工作流状态 / 进度 / 阶段摘要 composable。
 *
 * 从 InfoPanel.vue 提取，集中管理工作流运行态、天气瓦片活动、分析阶段
 * 以及顶部摘要文案的计算逻辑。
 */
export interface WorkflowStateOptions {
  displayLayer: ComputedRef<ActiveLayerDisplay>
  jobLayer: ComputedRef<JobLayerItem | undefined>
  isRealtimeWeatherLayer: ComputedRef<boolean>
  tileStats: ComputedRef<LayerTileStats | null>
  isSubmitting: ComputedRef<boolean>
  windStyleChipLabel: ComputedRef<string>
  canToggleParticleFlow: ComputedRef<boolean>
  visibleHotspots: ComputedRef<LayerHotspot[]>
  hasPointWeatherSection: ComputedRef<boolean>
  showMultiOverlayBar: ComputedRef<boolean>
  showSelectedOverlayTimeSeries: ComputedRef<boolean>
  showDemoOverlayTimeSeries: ComputedRef<boolean>
  hasUnifiedData: ComputedRef<boolean>
  resultModel: ComputedRef<ResultDisplayModel | null>
}

/** X2 工作流变体展示模型；含「自动」项时 selectedKey 可为 auto。 */
export type WorkflowVariantView = {
  defaultKey: string
  selectedKey: string
  options: { key: string; label: string }[]
  /** 源路由自动模式（未钉死偏好） */
  isAuto: boolean
}

export function useWorkflowState(options: WorkflowStateOptions) {
  const {
    displayLayer,
    jobLayer,
    isRealtimeWeatherLayer,
    tileStats,
    isSubmitting,
    windStyleChipLabel,
    canToggleParticleFlow,
    visibleHotspots,
    hasPointWeatherSection,
    showMultiOverlayBar,
    showSelectedOverlayTimeSeries,
    showDemoOverlayTimeSeries,
    hasUnifiedData,
    resultModel,
  } = options

  const workspace = useLayerWorkspace()
  const workflowRun = useWorkflowRun()
  const onlinePlan = useOnlinePlanSessionStore()

  const workflowVariants = computed<WorkflowVariantView | null>(() => {
    const cid = displayLayer.value.catalogId
    if (!cid || !canRunWorkflow.value) return null
    const descriptor = workspace.resolveEffectiveDescriptor(cid)
    const variants = descriptor?.workflow_variants as Record<
      string,
      { workflow_id?: string | null; label?: string } | undefined
    > | null
    if (!variants || Object.keys(variants).length === 0) return null
    const hasLocal = Boolean(variants.local?.workflow_id)
    const hasOnline = Boolean(variants.online?.workflow_id)
    // 通用：任一端声明即可展示；双端齐全时追加「自动」（策略源路由）
    if (!hasLocal && !hasOnline) return null
    const defaultKey =
      Object.entries(variants).find(([, v]) => v?.workflow_id === descriptor?.workflow_id)?.[0] ??
      (hasOnline ? 'online' : 'local')
    const options = [
      ...(hasLocal && hasOnline ? [{ key: 'auto', label: '自动' }] : []),
      ...(hasLocal ? [{ key: 'local', label: variants.local?.label?.trim() || '本地读取' }] : []),
      ...(hasOnline
        ? [{ key: 'online', label: variants.online?.label?.trim() || '在线获取' }]
        : []),
    ]
    const backendId = workspace.resolveBackendLayerId(cid)
    const pinned =
      workflowRun.isWorkflowVariantPinned?.(backendId) || workflowRun.isWorkflowVariantPinned?.(cid)
    const preference =
      workflowRun.workflowVariantPreference.value[backendId] ??
      workflowRun.workflowVariantPreference.value[cid]
    const isAuto = hasLocal && hasOnline && !pinned
    const selectedKey = isAuto ? 'auto' : (preference ?? defaultKey)
    return { defaultKey, selectedKey, options, isAuto }
  })

  /** 切换「数据来源」：自动=清钉死走策略；本地/在线=钉死并带当前时间轴重提。
   * 不打断地图上已有缓存图层显示（runner 会保留旧 mapLayerPayload）。 */
  async function switchWorkflowVariant(variantKey: string) {
    const cid = displayLayer.value.catalogId
    if (!cid) return
    const view = workflowVariants.value
    if (!view || variantKey === view.selectedKey) return
    const backendId = workspace.resolveBackendLayerId(cid)
    if (variantKey === 'auto') {
      workflowRun.clearWorkflowVariantPin?.(cid)
      if (backendId !== cid) workflowRun.clearWorkflowVariantPin?.(backendId)
    } else if (variantKey === 'online' || variantKey === 'local') {
      workflowRun.setWorkflowVariantPreference(cid, variantKey, { pinned: true })
      if (backendId !== cid) {
        workflowRun.setWorkflowVariantPreference(backendId, variantKey, { pinned: true })
      }
    } else {
      return
    }

    // 显式带上当前时间轴窗，避免在线种子（fy_download）缺 start_date
    let timeRange: Record<string, unknown> | undefined
    try {
      const { useUiStore } = await import('../../stores/ui')
      const { buildTimeKey, buildTimeRangeFromKey } =
        await import('../../stores/layers/online-temporal-orchestrator')
      const ui = useUiStore()
      const desc = workspace.resolveEffectiveDescriptor(cid) as {
        time_granularity?: string
        online_temporal?: { native_step?: string }
        native_step?: string
        supports_time?: boolean
      } | null
      if (desc?.supports_time !== false) {
        const granRaw = desc?.time_granularity || ui.activeTimeGranularity || 'day'
        const gran =
          granRaw === 'hour' ||
          granRaw === 'day' ||
          granRaw === 'month' ||
          granRaw === 'year' ||
          granRaw === 'static'
            ? granRaw
            : 'day'
        if (gran !== 'static') {
          const nativeStep =
            desc?.native_step ||
            desc?.online_temporal?.native_step ||
            (gran === 'hour' ? '1h' : '1d')
          const timeKey = buildTimeKey(ui.currentDate, ui.currentHour, gran)
          const built = buildTimeRangeFromKey(timeKey, nativeStep, gran)
          if (built) timeRange = built as unknown as Record<string, unknown>
        }
      }
    } catch {
      /* 时间轴不可用时仍提交，由 runner 再补一次 */
    }

    try {
      await workflowRun.runWorkflowForCatalog(cid, {
        ...(variantKey === 'auto' ? {} : { workflowVariant: variantKey as 'online' | 'local' }),
        ...(timeRange ? { timeRange } : {}),
      })
    } catch (error) {
      console.warn('[InfoPanel] switchWorkflowVariant re-run failed:', error)
    }
  }

  // ── 分析摘要 ──────────────────────────────────────────────────────────────

  const analysisSummary = computed(() => {
    if (displayLayer.value.isImported) {
      return ANALYSIS_COPY.overviewImportedVector(
        displayLayer.value.importedGeometryType ?? '—',
        displayLayer.value.importedFeatureCount ?? 0,
      )
    }
    if (displayLayer.value.isImportedRaster) {
      return ANALYSIS_COPY.overviewImportedRaster
    }
    if (displayLayer.value.isAdminBoundary) {
      return ANALYSIS_COPY.overviewBoundary
    }
    return displayLayer.value.summary || ''
  })

  const jobReportSummary = computed(
    () => jobLayer.value?.resultView?.summary ?? jobLayer.value?.reportSummary ?? '',
  )

  const jobEventNotes = computed(
    () => jobLayer.value?.eventMessages ?? jobLayer.value?.diagnosticNotes ?? [],
  )

  const showCompactHero = computed(
    () =>
      displayLayer.value.isImported ||
      displayLayer.value.isImportedRaster ||
      displayLayer.value.isAdminBoundary,
  )

  // ── 分析图表 / 表格 ────────────────────────────────────────────────────────

  const analysisCharts = computed(() => jobLayer.value?.analysisCharts ?? [])
  const analysisTables = computed(() => jobLayer.value?.analysisTables ?? [])
  const hasAnalysisCharts = computed(
    () => analysisCharts.value.length > 0 || analysisTables.value.length > 0,
  )

  const hasVisualTabContent = computed(
    () =>
      hasAnalysisCharts.value ||
      hasPointWeatherSection.value ||
      showMultiOverlayBar.value ||
      showSelectedOverlayTimeSeries.value ||
      showDemoOverlayTimeSeries.value ||
      hasUnifiedData.value ||
      displayLayer.value.isImportedRaster ||
      !!resultModel.value ||
      visibleHotspots.value.length > 0,
  )

  // ── 工作流运行态 ──────────────────────────────────────────────────────────

  const canRunWorkflow = computed(
    () =>
      !displayLayer.value?.isAdminBoundary &&
      !displayLayer.value?.isImported &&
      !displayLayer.value?.isImportedRaster &&
      !isRealtimeWeatherLayer.value &&
      workspace.supportsAnalysisWorkflow(displayLayer.value.catalogId),
  )

  const isWorkflowRunning = computed(
    () => jobLayer.value?.status === 'running' || jobLayer.value?.status === 'queued',
  )

  const runBlockedReason = computed(() =>
    workspace.getCatalogRunBlockReason(displayLayer.value.catalogId),
  )

  const workflowStage = computed(() => {
    if (isSubmitting.value) return 'submitting'
    if (isRealtimeWeatherLayer.value) {
      return resolveWeatherWorkflowStage(tileStats.value)
    }
    if (jobLayer.value?.status === 'queued') return 'queued'
    if (jobLayer.value?.status === 'running') return 'running'
    if (jobLayer.value?.status === 'succeeded') return 'succeeded'
    if (jobLayer.value?.status === 'failed') return 'failed'
    // 提交失败只落了全局 workflowError、jobLayer 已被抹掉时，分析框仍显示失败态
    if (workflowRun.workflowError.value) return 'failed'
    return 'idle'
  })

  /** 从图层目录中查找关联的工作流名称和引擎 */
  const workflowMeta = computed(() => {
    const cid = displayLayer.value.catalogId
    if (!cid) return { name: '', engine: '', engineLabel: '', engineIcon: '' }
    const libItem = workspace.layerLibrary.value.find((l) => l.catalogId === cid)
    const engine = libItem?.engine ?? displayLayer.value.engine ?? ''
    const name = libItem?.workflowName ?? ''
    const engineLabel =
      engine === 'weather'
        ? '天气引擎'
        : engine === 'python_provider'
          ? 'Python 处理器'
          : engine === 'gee'
            ? 'GEE'
            : engine === 'general'
              ? '通用'
              : ''
    const engineIcon =
      engine === 'weather'
        ? '☀'
        : engine === 'python_provider'
          ? '⚡'
          : engine === 'gee'
            ? '🌍'
            : '◈'
    return { name, engine, engineLabel, engineIcon }
  })

  /** 工作流进度（0-100） */
  const workflowProgress = computed(() => {
    if (!jobLayer.value) return 0
    return Math.max(0, Math.min(100, jobLayer.value.progress ?? 0))
  })

  /** 最近事件消息 */
  const latestEventMessage = computed(() => {
    const msgs = jobLayer.value?.eventMessages
    if (!msgs || msgs.length === 0) return ''
    return msgs[msgs.length - 1]
  })

  const hasRealSelection = computed(() => Boolean(displayLayer.value.instanceId))

  /** 图表 Tab 稀疏态说明（有选中但尚无图表载荷） */
  const sparseVisualHint = computed(() => {
    if (isRealtimeWeatherLayer.value) return ANALYSIS_COPY.sparseVisualWeather
    if (canRunWorkflow.value) return ANALYSIS_COPY.sparseVisualWorkflow
    return ANALYSIS_COPY.sparseVisualStatic
  })

  const analysisStageKind = computed(() =>
    resolveAnalysisStageKind({
      hasRealSelection: hasRealSelection.value,
      isWeather: isRealtimeWeatherLayer.value,
      isImported: !!displayLayer.value.isImported,
      isImportedRaster: !!displayLayer.value.isImportedRaster,
      isAdminBoundary: !!displayLayer.value.isAdminBoundary,
      canRunWorkflow: canRunWorkflow.value,
    }),
  )

  const hasWeatherTileActivity = computed(() => {
    const stats = tileStats.value
    if (!stats) return false
    return stats.pending > 0 || stats.cached > 0
  })

  const showWorkflowStageRow = computed(
    () =>
      canRunWorkflow.value ||
      isWorkflowRunning.value ||
      (isRealtimeWeatherLayer.value && hasRealSelection.value && hasWeatherTileActivity.value),
  )

  /** P2：只读「待计划」— 会话 tabs 含当前层且未 resolved；不改 job status */
  const onlinePlanPending = computed(() => {
    const cid = displayLayer.value.catalogId
    return Boolean(cid && onlinePlan.isCatalogPendingPlan(cid))
  })

  function openOnlinePlanSession() {
    onlinePlan.openSession()
  }

  const workflowStageCopy = computed(() =>
    resolveWorkflowStageCopy({
      stage: workflowStage.value,
      progress: workflowProgress.value,
      isWeather: isRealtimeWeatherLayer.value && hasRealSelection.value,
      tilePending: tileStats.value?.pending ?? 0,
      tileCached: tileStats.value?.cached ?? 0,
      tileVisible: tileStats.value?.visible ?? 0,
    }),
  )

  const weatherTopLines = computed(() => {
    if (!hasRealSelection.value || !isRealtimeWeatherLayer.value) return [] as string[]
    // 2026-08-25 用户反馈：分析框顶部「瓦片按视口自动加载，无需手动提交工作流」
    // 提示性文案属噪音——已移除（保留瓦片进度等可观测信息）。
    const lines: string[] = []
    const stats = tileStats.value
    if (stats) {
      lines.push(ANALYSIS_COPY.weatherTileLine(stats.cached, stats.visible, stats.pending))
    } else {
      lines.push(ANALYSIS_COPY.weatherNoTilesYet)
    }
    const timeLabel = displayLayer.value.observationTimeLabel
    if (timeLabel && timeLabel !== '—') {
      lines.push(`${ANALYSIS_COPY.metaTime}：${timeLabel}`)
    }
    if (canToggleParticleFlow.value) {
      lines.push(ANALYSIS_COPY.weatherWindMode(windStyleChipLabel.value))
    }
    const source = displayLayer.value.sourceLabel
    if (source && source !== '—') {
      lines.push(`${ANALYSIS_COPY.metaSource}：${source}`)
    }
    return lines
  })

  const staticTopHint = computed(() => resolveStaticLayerHint(analysisStageKind.value))

  return {
    canRunWorkflow,
    isWorkflowRunning,
    runBlockedReason,
    workflowStage,
    workflowMeta,
    workflowProgress,
    workflowVariants,
    switchWorkflowVariant,
    latestEventMessage,
    hasRealSelection,
    sparseVisualHint,
    analysisStageKind,
    hasWeatherTileActivity,
    showWorkflowStageRow,
    workflowStageCopy,
    weatherTopLines,
    staticTopHint,
    hasVisualTabContent,
    hasAnalysisCharts,
    analysisCharts,
    analysisTables,
    jobEventNotes,
    jobReportSummary,
    analysisSummary,
    showCompactHero,
    onlinePlanPending,
    openOnlinePlanSession,
    onlinePlanPendingLabel: ONLINE_PLAN_COPY.pendingBadge,
    onlinePlanPendingTitle: ONLINE_PLAN_COPY.pendingBadgeTitle,
  }
}
