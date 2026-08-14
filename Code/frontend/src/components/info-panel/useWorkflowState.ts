import { computed, type ComputedRef } from 'vue'

import type { ActiveLayerDisplay, JobLayerItem, LayerHotspot } from '../../stores/layers/types'
import type { LayerTileStats } from '../../stores/weather-tile-types'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { ANALYSIS_COPY } from '../../ui-copy'
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
  resultModel: ComputedRef<ResultDisplayModel | null>
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
    resultModel,
  } = options

  const workspace = useLayerWorkspace()

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
    const lines: string[] = [ANALYSIS_COPY.weatherAutoLoad]
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
  }
}
