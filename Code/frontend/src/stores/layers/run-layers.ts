/**
 * Job / run-group / materialize slice extracted from the layers god store.
 * Public API re-exported via useLayersStore().
 */
import { computed, ref } from 'vue'

import { materializeWorkflowMapLayers } from '../../services/runtime-api'
import type { BoundingBox } from '../../services/runtime-api'
import { useWorkflowOutputLayersStore } from '../workflow-output-layers'
import { safeLog } from '../log'
import { extractOverlayImportsFromResultRefs, normalizeProductTag } from './result-adapter'
import { buildImportedRasterPayload } from './imported-raster'
import { isOverlayDismissed, isRunDismissed } from './workspace-persist'
import {
  EMPTY_OVERLAY_CONFIRM_AFTER_RETRY_MS,
  hasPendingAttachRetry,
} from './workflow-attach-retry'
import { formatProgressShell, pickLatestNodeProgress } from '../../utils/workflow-progress-format'
import { isTerminalStatus } from './catalog-builders'
import { WORKFLOW_COPY } from '../../ui-copy/workflow'
import { resolveEmptyOverlayWorkflowError } from './materialize-empty'
import { productTagLabel } from '../../utils/workflow-expected-outputs'
import { cleanProductDisplayName } from '../../utils/workflow-result-naming'
import { isDefaultProductDisplayName } from './layer-naming'
import { isEnglishInversionCatalogId, resolveInversionCatalogId } from './inversion-catalog'
import {
  isTechnicalRunTitle,
  resolveRunGroupTitle,
  tryWorkflowSummaries,
} from '../../utils/workflow-run-display-name'
import {
  timelineTargetFromWorkflowTimeKey,
  type WorkflowProgressTimeSeekHint,
} from '../../utils/workflow-timekey-seek'
import { pruneInFlightTimeKeys } from '../../utils/job-layer-coverage'
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
  LayerSidebarView,
  WorkflowSummary,
} from './types'

export interface RunLayersSliceDeps {
  getActiveLayers: () => ActiveLayer[]
  addLayer: (
    catalogId: string,
    isAdminBoundary?: boolean,
    jobLayer?: JobLayerItem,
    options?: { skipAutoRun?: boolean },
  ) => void
  removeLayer: (instanceId: string) => void
  assignLayerAccent: (preferred?: string | null) => {
    accentColor: string
    accentGlow: string
    chipTone: string
  }
  setSelectedInstanceId: (id: string | null) => void
  getSidebarView: () => LayerSidebarView
  setSidebarView: (view: LayerSidebarView) => void
  getMapCenter: () => { lng: number; lat: number }
  getCurrentHour: () => number
  forgetTrackedWorkflowRun: (runId: string) => void
  rememberTrackedWorkflowRun: (catalogId: string, jobLayer: JobLayerItem) => void
  isLocalSubmitJobId: (jobId: string | null | undefined) => boolean
  scheduleWorkspacePersist: () => void
  genInstanceId: () => string
  addImportedRasterLayer: (
    name: string,
    overlayLayerId: string,
    bounds?: [number, number, number, number],
    options?: {
      sourceCrs?: string
      lngOffset?: number
      latOffset?: number
      nativeStep?: string | null
      timeList?: string[]
      followPolicy?: import('../../utils/temporal-interval').TemporalFollowPolicy
    },
  ) => ActiveLayer
}

export function createRunLayersSlice(deps: RunLayersSliceDeps) {
  const jobLayers = ref<JobLayerItem[]>([])
  const runLayerGroups = ref<ActiveRunLayerGroup[]>([])
  const workflowError = ref<string | null>(null)
  const workflowProgressTimeSeek = ref<WorkflowProgressTimeSeekHint | null>(null)
  let lastWorkflowTimeSeekToken = ''

  function emitWorkflowProgressTimeSeek(
    jobLayer: JobLayerItem,
    status: JobLayerItem['status'],
    detail: { timeKey?: string; dateStart?: string; dateEnd?: string; phase?: string } | undefined,
  ) {
    if (status !== 'running') return
    const phase = detail?.phase
    if (phase !== 'block_commit' && phase !== 'block_refresh' && phase !== 'artifact') return
    const timeKey = detail?.timeKey || detail?.dateStart
    if (!timeKey || !jobLayer.catalogId) return
    const token = `${jobLayer.jobId}:${timeKey}`
    if (token === lastWorkflowTimeSeekToken) return
    lastWorkflowTimeSeekToken = token
    const target = timelineTargetFromWorkflowTimeKey(timeKey, detail?.dateEnd)
    if (!target) return
    // 标记当前块为 in-flight（黄格）；已 ready 的键由 time_list 覆盖
    const job = jobLayers.value.find((j) => j.jobId === jobLayer.jobId)
    if (job) {
      const keys = new Set(job.inFlightTimeKeys ?? [])
      keys.add(timeKey)
      if (detail?.dateStart && detail?.dateEnd) {
        keys.add(`${detail.dateStart}_${detail.dateEnd}`)
      }
      job.inFlightTimeKeys = [...keys].slice(-40)
    }
    workflowProgressTimeSeek.value = {
      runId: jobLayer.jobId,
      catalogId: jobLayer.catalogId,
      timeKey,
      sliceLabel: target.sliceLabel,
      at: new Date().toISOString(),
    }
  }

  const workflowSummary = computed<WorkflowSummary>(() => {
    const layers = jobLayers.value
    if (layers.length === 0) {
      return {
        total: 0,
        running: 0,
        queued: 0,
        succeeded: 0,
        failed: 0,
        cancelled: 0,
        retryPending: 0,
        overall: 'idle',
        tone: 'idle',
        hasError: false,
      }
    }
    const counts = {
      running: 0,
      queued: 0,
      succeeded: 0,
      failed: 0,
      cancelled: 0,
      retry_pending: 0,
    }
    for (const layer of layers) {
      if (layer.status in counts) counts[layer.status as keyof typeof counts]++
    }
    const active = counts.running + counts.queued + counts.retry_pending
    const orphanError = Boolean(workflowError.value) && counts.failed === 0
    // 提交失败若只写入了 workflowError、job 行已被清掉，仍按失败呈现指示器
    const failed = counts.failed + (orphanError ? 1 : 0)
    let overall: WorkflowSummary['overall'] = 'idle'
    let tone: WorkflowSummary['tone'] = 'idle'
    if (active > 0) {
      overall = 'active'
      tone = 'active'
    } else if (failed > 0 && counts.succeeded > 0) {
      overall = 'mixed'
      tone = 'warning'
    } else if (failed > 0) {
      overall = 'failed'
      tone = 'error'
    } else if (counts.succeeded > 0) {
      overall = 'succeeded'
      tone = 'success'
    }
    return {
      total: layers.length + (orphanError ? 1 : 0),
      running: counts.running,
      queued: counts.queued,
      succeeded: counts.succeeded,
      failed,
      cancelled: counts.cancelled,
      retryPending: counts.retry_pending,
      overall,
      tone,
      hasError: !!workflowError.value || counts.failed > 0,
    }
  })

  function removeJobLayerById(jobId: string) {
    const idx = jobLayers.value.findIndex((item) => item.jobId === jobId)
    if (idx >= 0) {
      jobLayers.value.splice(idx, 1)
    }
    // 同步清掉活跃图层上挂的同 id jobLayer，避免「排队中」幽灵状态
    for (const layer of deps.getActiveLayers()) {
      if (layer.jobLayer?.jobId === jobId) {
        layer.jobLayer = undefined
      }
    }
  }

  /** 按成员 catalog / runId 同步计算组标题为工作流中文名（禁止 wf-run-* 占位泄漏）。 */
  function syncRunGroupTitleFromJob(
    catalogId: string,
    job: Pick<JobLayerItem, 'jobId' | 'name' | 'commandLabel'>,
  ) {
    const resolved = resolveRunGroupTitle({
      jobName: job.name,
      commandLabel: job.commandLabel,
      summaries: tryWorkflowSummaries(),
    })
    if (isTechnicalRunTitle(resolved)) return

    const layer = deps.getActiveLayers().find((l) => l.catalogId === catalogId && l.runGroupId)
    const byRun =
      job.jobId && !deps.isLocalSubmitJobId(job.jobId)
        ? runLayerGroups.value.find((g) => g.runId === job.jobId)
        : undefined
    const byMember = layer?.runGroupId
      ? runLayerGroups.value.find((g) => g.groupId === layer.runGroupId)
      : undefined
    const group = byRun ?? byMember
    if (!group) return

    if (isTechnicalRunTitle(group.title) || !group.title?.trim()) {
      group.title = resolved
      return
    }
    // 已有标题但仍是泛化 fallback 时，用工作流名覆盖
    if (/^(反演产物|工作流产物|工作流运行)$/.test(group.title.trim())) {
      group.title = resolved
    }
  }

  /** 按成员 catalog 更新计算组进度（local-submit 阶段 group.runId 尚为空） */
  function updateRunGroupForCatalog(
    catalogId: string,
    job: Pick<JobLayerItem, 'jobId' | 'status' | 'progress' | 'message' | 'nodeProgress'>,
  ) {
    const layer = deps.getActiveLayers().find((l) => l.catalogId === catalogId && l.runGroupId)
    if (!layer?.runGroupId) {
      updateRunGroupFromJob(job.jobId, job)
      return
    }
    const g = runLayerGroups.value.find((x) => x.groupId === layer.runGroupId)
    if (!g) {
      updateRunGroupFromJob(job.jobId, job)
      return
    }
    // 真实 run id 才写入组；local-submit 只更新展示态
    if (!deps.isLocalSubmitJobId(job.jobId) && job.jobId) {
      g.runId = job.jobId
    }
    if (job.status === 'succeeded') g.status = 'ready'
    else if (job.status === 'failed') g.status = 'failed'
    else if (job.status === 'cancelled') g.status = 'cancelled'
    else g.status = 'computing'
    if (typeof job.progress === 'number') g.progress = job.progress
    if (job.message) g.message = job.message
    refreshRunGroupDissolvable(g.groupId)
  }

  function setJobLayers(jobs: JobLayerItem[]) {
    jobLayers.value = jobs
  }

  function syncJobLayerToActiveLayer(catalogId: string, jobLayer: JobLayerItem) {
    // GIS 分析工具 run 仅更新 jobLayers，不覆盖 catalog 层上的主工作流 jobLayer
    if (jobLayer.isAnalysisToolRun) {
      const boundLayer = deps
        .getActiveLayers()
        .find((layer) => layer.jobLayer?.jobId === jobLayer.jobId)
      if (boundLayer) {
        boundLayer.jobLayer = jobLayer
        boundLayer.dataState = 'real'
      }
      return
    }
    // 英文反演 workflow id 不得直接成为活跃层 catalogId（会以技术名进 TOC）
    const resolvedCatalogId = resolveInversionCatalogId(catalogId)
    const existingRealLayer = deps
      .getActiveLayers()
      .find((layer) => layer.jobLayer?.jobId === jobLayer.jobId)
    if (existingRealLayer) {
      existingRealLayer.jobLayer = jobLayer
      existingRealLayer.dataState = 'real'
      return
    }

    const existingCatalogLayer = deps
      .getActiveLayers()
      .find((layer) => layer.catalogId === resolvedCatalogId && !layer.isAdminBoundary)
    if (existingCatalogLayer) {
      existingCatalogLayer.jobLayer = jobLayer
      existingCatalogLayer.dataState = 'real'
      // 不在工作流更新时修改 selectedInstanceId，避免视口变化重提交导致图层选中被篡改
      return
    }

    deps.addLayer(resolvedCatalogId, false, jobLayer)
  }

  function upsertJobLayer(
    catalogId: string,
    jobLayer: JobLayerItem,
    opts?: { skipActiveLayerSync?: boolean },
  ) {
    const resolvedCatalogId = resolveInversionCatalogId(catalogId)
    // 确保 catalogId 被记录在 jobLayer 上，便于面板列表展示孤儿工作流（无活跃图层时）
    const enrichedJobLayer: JobLayerItem = {
      ...jobLayer,
      catalogId: resolveInversionCatalogId(jobLayer.catalogId || resolvedCatalogId),
    }
    const existingIndex = jobLayers.value.findIndex((item) => item.jobId === enrichedJobLayer.jobId)
    if (existingIndex >= 0) {
      jobLayers.value.splice(existingIndex, 1, enrichedJobLayer)
    } else {
      jobLayers.value.unshift(enrichedJobLayer)
    }
    // GIS 分析工具 run：只写入 jobLayers，不覆盖主工作流 jobLayer / run 组 / 追踪表
    const analysisOnly =
      Boolean(opts?.skipActiveLayerSync) || Boolean(enrichedJobLayer.isAnalysisToolRun)
    if (!analysisOnly) {
      syncJobLayerToActiveLayer(resolvedCatalogId, enrichedJobLayer)
      deps.rememberTrackedWorkflowRun(resolvedCatalogId, enrichedJobLayer)
      updateRunGroupForCatalog(resolvedCatalogId, enrichedJobLayer)
      syncRunGroupTitleFromJob(resolvedCatalogId, enrichedJobLayer)
    } else {
      // 仅当已有同 jobId 的活跃层时更新；不按 catalogId 覆盖主工作流
      syncJobLayerToActiveLayer(resolvedCatalogId, enrichedJobLayer)
    }
    if (isTerminalStatus(enrichedJobLayer.status) && !analysisOnly) {
      if (enrichedJobLayer.status === 'cancelled' || enrichedJobLayer.status === 'failed') {
        // local-submit 失败时按 catalog 找组清理占位；真 run 按 runId
        if (deps.isLocalSubmitJobId(enrichedJobLayer.jobId)) {
          const layer = deps.getActiveLayers().find((l) => l.catalogId === resolvedCatalogId)
          if (layer?.runGroupId) {
            const g = runLayerGroups.value.find((x) => x.groupId === layer.runGroupId)
            if (g && !g.runId) {
              g.status = 'failed'
              g.dissolvable = true
              g.message = enrichedJobLayer.message || '提交失败'
            }
          }
        } else {
          cleanupUnproducedRunLayers(enrichedJobLayer.jobId)
        }
      }
      // Keep succeeded/failed in storage briefly for refresh restore of final state,
      // but drop cancelled noise.
      if (enrichedJobLayer.status === 'cancelled') {
        deps.forgetTrackedWorkflowRun(enrichedJobLayer.jobId)
      }
    }
    deps.scheduleWorkspacePersist()
  }

  function buildWorkflowPayloadForCatalog(
    catalogId: string,
    catalogName: string,
    requestedOutputs: string[],
    requestBBox: BoundingBox | null,
    backendLayerId?: string,
    algorithmRequest?: Record<string, unknown>,
    weatherRequest?: Record<string, unknown>,
  ) {
    const layerId = backendLayerId ?? catalogId
    const payload: Record<string, unknown> = {
      command_type: 'analysis' as const,
      command_label: `运行 ${catalogName} 分析`,
      layer_id: layerId,
      priority: 'normal' as const,
      resource_profile: 'standard' as const,
      realtime_preferred: false,
      requested_outputs: requestedOutputs,
      parameters: {
        hour: deps.getCurrentHour(),
        latitude: deps.getMapCenter().lat,
        longitude: deps.getMapCenter().lng,
      },
      client: {
        page: 'dashboard',
        view_id: 'map-2d',
      },
      map_context: {
        active_layer_id: catalogId,
        map_mode: '2d' as const,
        viewport_bbox: requestBBox ?? undefined,
      },
    }
    if (algorithmRequest && Object.keys(algorithmRequest).length > 0) {
      payload.algorithm_request = algorithmRequest
    }
    if (weatherRequest && Object.keys(weatherRequest).length > 0) {
      payload.weather_request = weatherRequest
    }
    return payload
  }

  const progressiveMaterializeAt = new Map<string, number>()
  const progressiveMaterializeInFlight = new Set<string>()

  function formatProgressiveSyncMessage(count: number, hadError: boolean): string {
    if (hadError && count > 0) {
      return WORKFLOW_COPY.progressiveSyncPartial.replace('{count}', String(count))
    }
    if (hadError) return WORKFLOW_COPY.progressiveSyncFailed
    if (count > 0) {
      return WORKFLOW_COPY.progressiveSyncOk.replace('{count}', String(count))
    }
    return ''
  }

  function applyProgressiveSyncToJob(
    catalogId: string,
    runId: string,
    count: number,
    hadError: boolean,
    errorMsg?: string,
  ) {
    const now = new Date().toISOString()
    const msg = formatProgressiveSyncMessage(count, hadError)
    // 图层已渐进物化成功 → 清除「未生成可显示图层」误报横幅
    if (!hadError && count > 0 && workflowError.value === WORKFLOW_COPY.noMapLayers) {
      workflowError.value = null
    }
    const job = jobLayers.value.find((j) => j.jobId === runId)
    if (job) {
      job.progressiveOverlayCount = count
      job.progressiveOverlayAt = hadError ? job.progressiveOverlayAt : now
      job.progressiveOverlayError = hadError
        ? errorMsg || WORKFLOW_COPY.progressiveSyncFailed
        : undefined
      if (hadError) {
        const note = errorMsg || WORKFLOW_COPY.progressiveSyncFailed
        const notes = [...(job.diagnosticNotes ?? [])]
        if (!notes.includes(note)) notes.unshift(note)
        job.diagnosticNotes = notes.slice(0, 8)
      }
      if (msg) job.message = msg
      syncJobLayerToActiveLayer(catalogId, job)
      updateRunGroupForCatalog(catalogId, job)
    }
  }

  /** 运行中块产物增量物化（节流）。 */
  async function syncProgressiveBlockOverlays(runId: string, catalogId: string) {
    if (!runId) return
    const job = jobLayers.value.find((j) => j.jobId === runId)
    // 与 BE materialize allowlist 对齐；retry_pending 禁止 POST（409）
    // FE JobStatus 无 accepted：服务端 accepted 在 poller/adapter 已映射为 queued
    if (job && job.status !== 'succeeded' && job.status !== 'running' && job.status !== 'queued') {
      return
    }
    const now = Date.now()
    const last = progressiveMaterializeAt.get(runId) ?? 0
    if (now - last < 8_000) return
    if (progressiveMaterializeInFlight.has(runId)) return
    progressiveMaterializeAt.set(runId, now)
    progressiveMaterializeInFlight.add(runId)
    try {
      const count = await attachAlgorithmProductOverlays([], catalogId, runId)
      applyProgressiveSyncToJob(catalogId, runId, count, false)
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : WORKFLOW_COPY.progressiveSyncFailed
      console.warn('[layers] progressive block overlay sync failed', runId, error)
      safeLog('workflow-error', '渐进分块叠加同步失败', `run=${runId} err=${String(error)}`, 'warn')
      const prev = jobLayers.value.find((j) => j.jobId === runId)?.progressiveOverlayCount ?? 0
      applyProgressiveSyncToJob(catalogId, runId, prev, true, errMsg)
    } finally {
      progressiveMaterializeInFlight.delete(runId)
    }
  }

  /** 「未生成可显示图层」横幅的延迟确认 timer（runId 去重）。 */
  const emptyOverlayConfirmTimers = new Map<string, ReturnType<typeof setTimeout>>()

  /** 横幅限时自动消失 timer（用户反馈：提示应显示一段时间而非常驻）。 */
  let workflowErrorAutoDismissTimer: ReturnType<typeof setTimeout> | null = null

  /** 写入限时横幅：限时显示时长后自动清除（消息未变时）。 */
  function setTransientWorkflowError(message: string) {
    workflowError.value = message
    if (workflowErrorAutoDismissTimer) clearTimeout(workflowErrorAutoDismissTimer)
    workflowErrorAutoDismissTimer = setTimeout(() => {
      if (workflowError.value === message) workflowError.value = null
    }, WORKFLOW_COPY.noMapLayersBannerTtl)
  }

  /**
   * succeeded 但本次 materialize 为空时，延迟二次确认再写横幅。
   * 产物登记与 succeeded 事件存在传播竞态——直接写横幅会误报（图层稍后到达）。
   */
  function scheduleEmptyOverlayConfirm(runId: string, emptyMsg: string) {
    if (hasPendingAttachRetry(runId)) return
    if (emptyOverlayConfirmTimers.has(runId)) return
    emptyOverlayConfirmTimers.set(
      runId,
      setTimeout(() => {
        emptyOverlayConfirmTimers.delete(runId)
        if (hasPendingAttachRetry(runId)) return
        // 重查前若图层已物化（其它路径清了横幅/绑定了图层）则不再写
        if (workflowError.value === WORKFLOW_COPY.noMapLayers) return
        void (async () => {
          try {
            const retry = await materializeWorkflowMapLayers(runId)
            if (retry.layers && retry.layers.length > 0) return // 产物已就绪，不写横幅
          } catch {
            // 重查失败：保持横幅（真异常时可见提示优于静默）
          }
          setTransientWorkflowError(emptyMsg)
        })()
      }, EMPTY_OVERLAY_CONFIRM_AFTER_RETRY_MS),
    )
  }

  /** Attach algorithm-published overlays so the map shows SM/VOD/OMEGA content. */
  async function attachAlgorithmProductOverlays(
    resultRefs: Parameters<typeof extractOverlayImportsFromResultRefs>[0],
    preferredCatalogId: string,
    runId?: string,
    opts?: { forceBind?: boolean },
  ): Promise<number> {
    if (runId && !opts?.forceBind && isRunDismissed(runId)) return 0

    let imports = extractOverlayImportsFromResultRefs(resultRefs)
    let materializedLayers: Awaited<ReturnType<typeof materializeWorkflowMapLayers>>['layers'] = []
    if ((!imports.length || runId) && runId) {
      // 发起前再读本地 status：失败进入 retry_pending 后勿 POST（仍可能与 HTTP 在途竞态）
      const liveStatus = jobLayers.value.find((j) => j.jobId === runId)?.status
      const canMaterializeNow =
        !liveStatus ||
        liveStatus === 'succeeded' ||
        liveStatus === 'running' ||
        liveStatus === 'queued'
      if (!canMaterializeNow) {
        // 仅用已有 result_refs 绑定；不打 materialize
      } else {
        try {
          const materialized = await materializeWorkflowMapLayers(runId)
          materializedLayers = materialized.layers ?? []
          const fromMaterialize = materializedLayers
            .filter((layer) => typeof layer.overlay_layer_id === 'string' && layer.overlay_layer_id)
            .map((layer) => {
              const rawBounds = layer.bounds
              const bounds =
                Array.isArray(rawBounds) &&
                rawBounds.length === 4 &&
                rawBounds.every((v) => typeof v === 'number' && Number.isFinite(v))
                  ? ([rawBounds[0], rawBounds[1], rawBounds[2], rawBounds[3]] as [
                      number,
                      number,
                      number,
                      number,
                    ])
                  : undefined
              return {
                overlayLayerId: layer.overlay_layer_id,
                title: layer.title || layer.overlay_layer_id,
                productTag: layer.product_tag || undefined,
                bounds,
                sourceCrs: layer.source_crs || undefined,
                timeList: layer.time_list || undefined,
                nativeStep: layer.native_step || undefined,
                defaultTime: layer.default_time || undefined,
              }
            })
          if (!imports.length) {
            imports = fromMaterialize
          } else if (fromMaterialize.length) {
            // result_refs 可能缺 OMEGA（登记最慢）；与 materialize 按 overlay/tag 并集合并
            const byOverlay = new Set(imports.map((item) => item.overlayLayerId))
            const byTag = new Set(
              imports
                .map((item) => normalizeProductTag(item.productTag || item.title || ''))
                .filter(Boolean),
            )
            for (const item of fromMaterialize) {
              if (byOverlay.has(item.overlayLayerId)) continue
              const tag = normalizeProductTag(item.productTag || item.title || '')
              if (tag && byTag.has(tag)) continue
              imports.push(item)
              byOverlay.add(item.overlayLayerId)
              if (tag) byTag.add(tag)
            }
          }
        } catch (error) {
          const errMsg = error instanceof Error ? error.message : String(error)
          // Failed/cancelled/retry_pending → 409 属失败切换竞态，预期软失败
          const isNonMaterializableConflict =
            /\b409\b/.test(errMsg) ||
            /cannot materialize/i.test(errMsg) ||
            /ExecutionStatus\.(failed|cancelled|retry_pending)/i.test(errMsg)
          if (!isNonMaterializableConflict) {
            console.warn('[layers] materializeWorkflowMapLayers failed', runId, error)
            safeLog(
              'workflow-error',
              '工作流地图图层物化失败',
              `run=${runId} err=${String(error)}`,
              'warn',
            )
            // 发布就绪修复（P0-9）：其它 materialize 失败落到 workflowError，
            // 避免"工作流显示 succeeded 但地图无图层、无任何错误提示"。
            workflowError.value = `工作流结果图层加载失败：${errMsg}`
          }
        }
      }
    }
    if (!imports.length) {
      const runStatus = runId
        ? (jobLayers.value.find((j) => j.jobId === runId)?.status ?? null)
        : null
      // 运行中误写的「已完成但无图层」横幅应清除
      if (
        runStatus &&
        runStatus !== 'succeeded' &&
        workflowError.value === WORKFLOW_COPY.noMapLayers
      ) {
        workflowError.value = null
      }
      // 原始 imports 为空：仅终态 succeeded 给出可见空态
      const emptyMsg = resolveEmptyOverlayWorkflowError({
        runId,
        rawImportCount: 0,
        existingWorkflowError: workflowError.value,
        emptyMessage: WORKFLOW_COPY.noMapLayers,
        runStatus,
      })
      if (emptyMsg) {
        // 延迟二次确认：materialize 结果有传播延迟（succeeded 事件先到、
        // 产物登记后到的竞态）——2.5s 后重查仍空才写「未生成可显示图层」横幅
        scheduleEmptyOverlayConfirm(runId!, emptyMsg)
      }
      return 0
    }
    imports = imports.filter((item) => opts?.forceBind || !isOverlayDismissed(item.overlayLayerId))
    if (!imports.length) return 0
    // 图层已成功物化 → 清除「未生成可显示图层」误报横幅（succeeded 事件先到、
    // materialize 结果后到的竞态窗口）
    if (workflowError.value === WORKFLOW_COPY.noMapLayers) workflowError.value = null

    const outputStore = useWorkflowOutputLayersStore()
    for (const item of imports) {
      if (!opts?.forceBind && isOverlayDismissed(item.overlayLayerId)) continue
      const matMeta = materializedLayers.find(
        (layer) => layer.overlay_layer_id === item.overlayLayerId,
      )
      const timeList = (item as { timeList?: string[] }).timeList || matMeta?.time_list || undefined
      const nativeStep =
        (item as { nativeStep?: string }).nativeStep || matMeta?.native_step || undefined

      const existingByOverlay = deps
        .getActiveLayers()
        .find((layer) => layer.importedRaster?.overlayLayerId === item.overlayLayerId)
      if (existingByOverlay?.importedRaster) {
        if (timeList?.length) {
          existingByOverlay.importedRaster.timeList = [...timeList]
          existingByOverlay.importedRaster.timeSlices = undefined
          existingByOverlay.importedRaster.nativeStep =
            nativeStep || existingByOverlay.importedRaster.nativeStep || '8d'
          if (runId) {
            const job = jobLayers.value.find((j) => j.jobId === runId)
            if (job) {
              job.inFlightTimeKeys = pruneInFlightTimeKeys(job.inFlightTimeKeys, timeList)
            }
          }
        }
        // 若游离 OMEGA_BLOCK 可并入组内 OMEGA 占位，不要在此 continue
        const canMergeIntoGroup =
          normalizeProductTag(item.productTag || item.title || existingByOverlay.name) ===
            'OMEGA' &&
          Boolean(
            (runId
              ? runLayerGroups.value.find((g) => g.runId === runId)
              : runLayerGroups.value.find((g) =>
                  g.memberInstanceIds.includes(existingByOverlay.instanceId),
                )) ||
            deps
              .getActiveLayers()
              .some(
                (layer) =>
                  !layer.importedRaster &&
                  normalizeProductTag(layer.runGroupProductTag || layer.name) === 'OMEGA',
              ),
          )
        if (!canMergeIntoGroup) {
          continue
        }
      }

      const tag = normalizeProductTag(item.productTag || item.title || '')
      const matchingOutput = outputStore.entries.find((entry) => {
        const name = entry.name.toUpperCase()
        return Boolean(tag) && (name.includes(tag) || name.endsWith(`_${tag}`))
      })
      // 图层名不得暴露产物文件名（xxx.tif 等）——后端 materialize title
      // 可能取自文件名时剥扩展名；空值继续向后兜底。
      // R4 前缀剥两类，统一收敛至 cleanProductDisplayName（P2-C）
      const cleanTitle = cleanProductDisplayName(item.title || '')
      const safeCleanTitle =
        cleanTitle && !isEnglishInversionCatalogId(cleanTitle) ? cleanTitle : ''
      // Bind only within this run's computing group (never cross-run by tag alone).
      const groupByRun = runId ? runLayerGroups.value.find((g) => g.runId === runId) : undefined
      const groupTitleFallback = groupByRun?.title
        ? groupByRun.title.replace(/\s*·\s*(?:计算中|已完成|部分失败|执行失败)$/u, '').trim()
        : ''
      const safeGroupTitle =
        groupTitleFallback && !isEnglishInversionCatalogId(groupTitleFallback)
          ? groupTitleFallback
          : ''
      const displayName =
        matchingOutput?.name ||
        (tag ? productTagLabel(tag) : '') ||
        safeCleanTitle ||
        (item.productTag && !isEnglishInversionCatalogId(item.productTag) ? item.productTag : '') ||
        safeGroupTitle ||
        productTagLabel(tag || 'result')

      const groupMember =
        groupByRun &&
        deps
          .getActiveLayers()
          .find(
            (layer) =>
              layer.runGroupId === groupByRun.groupId &&
              (normalizeProductTag(layer.runGroupProductTag) === tag ||
                normalizeProductTag(layer.name) === tag ||
                (tag === 'NDVI' &&
                  (layer.catalogId === 'ndvi' || layer.catalogId.includes('ndvi')))),
          )

      // 已有同 overlay 的游离层 + 组内占位：并入组并移除游离层
      if (
        groupMember &&
        existingByOverlay &&
        existingByOverlay.instanceId !== groupMember.instanceId
      ) {
        groupMember.importedRaster = existingByOverlay.importedRaster
          ? { ...existingByOverlay.importedRaster }
          : buildImportedRasterPayload(item.overlayLayerId, {
              bounds: item.bounds,
              fileName: groupMember.name || displayName,
              sourceCrs: item.sourceCrs,
              nativeStep: nativeStep || (timeList?.length ? '8d' : null),
              timeList,
              followPolicy: timeList?.length ? 'containing' : undefined,
            })
        groupMember.dataState = 'imported'
        groupMember.name = groupMember.name || displayName
        // 去掉游离层但不删后端文件
        const orphanId = existingByOverlay.instanceId
        const idx = deps.getActiveLayers().findIndex((l) => l.instanceId === orphanId)
        if (idx >= 0) {
          const orphan = deps.getActiveLayers()[idx]!
          orphan.importedRaster = undefined
          deps.getActiveLayers().splice(idx, 1)
          if (orphan.runGroupId) {
            const og = runLayerGroups.value.find((x) => x.groupId === orphan.runGroupId)
            if (og) {
              og.memberInstanceIds = og.memberInstanceIds.filter((id) => id !== orphanId)
            }
          }
        }
        if (groupMember.runGroupId) refreshRunGroupDissolvable(groupMember.runGroupId)
        deps.scheduleWorkspacePersist()
        continue
      }

      if (groupMember) {
        groupMember.importedRaster = buildImportedRasterPayload(item.overlayLayerId, {
          bounds: item.bounds,
          fileName: groupMember.name || displayName,
          sourceCrs: item.sourceCrs,
          nativeStep: nativeStep || (timeList?.length ? '8d' : null),
          timeList,
          followPolicy: timeList?.length ? 'containing' : undefined,
        })
        groupMember.dataState = 'imported'
        if (groupMember.name === productTagLabel('OMEGA') || !groupMember.name) {
          groupMember.name = displayName === 'OMEGA_BLOCK' ? productTagLabel('OMEGA') : displayName
        }
        if (groupMember.runGroupId) refreshRunGroupDissolvable(groupMember.runGroupId)

        // 治理重复/旧失败层：清理组内同 tag 的其它废弃成员（如旧失败残留、冗余未绑定占位）
        const redundantMembers = deps
          .getActiveLayers()
          .filter(
            (l) =>
              l.runGroupId === groupByRun.groupId &&
              l.instanceId !== groupMember.instanceId &&
              (normalizeProductTag(l.runGroupProductTag) === tag ||
                normalizeProductTag(l.name) === tag ||
                (tag === 'NDVI' && (l.catalogId === 'ndvi' || l.catalogId.includes('ndvi')))) &&
              (!l.importedRaster?.overlayLayerId ||
                l.jobLayer?.status === 'failed' ||
                l.jobLayer?.status === 'cancelled'),
          )
        for (const red of redundantMembers) {
          deps.removeLayer(red.instanceId)
          groupByRun.memberInstanceIds = groupByRun.memberInstanceIds.filter(
            (id) => id !== red.instanceId,
          )
        }
        continue
      }

      // 无组时：若已有「OMEGA」占位（任意组）且本条是 OMEGA_BLOCK，并入
      if (tag === 'OMEGA') {
        const omegaPlaceholder = deps
          .getActiveLayers()
          .find(
            (layer) =>
              !layer.importedRaster &&
              normalizeProductTag(layer.runGroupProductTag || layer.name) === 'OMEGA',
          )
        if (omegaPlaceholder) {
          omegaPlaceholder.importedRaster = buildImportedRasterPayload(item.overlayLayerId, {
            bounds: item.bounds,
            fileName: omegaPlaceholder.name || productTagLabel('OMEGA'),
            sourceCrs: item.sourceCrs,
            nativeStep: nativeStep || (timeList?.length ? '8d' : null),
            timeList,
            followPolicy: timeList?.length ? 'containing' : undefined,
          })
          omegaPlaceholder.dataState = 'imported'
          omegaPlaceholder.name = productTagLabel('OMEGA')
          if (omegaPlaceholder.runGroupId) {
            refreshRunGroupDissolvable(omegaPlaceholder.runGroupId)
          }
          // 若本 overlay 已作为游离层存在，删掉游离条目
          if (existingByOverlay && existingByOverlay.instanceId !== omegaPlaceholder.instanceId) {
            const idx = deps
              .getActiveLayers()
              .findIndex((l) => l.instanceId === existingByOverlay.instanceId)
            if (idx >= 0) {
              deps.getActiveLayers()[idx]!.importedRaster = undefined
              deps.getActiveLayers().splice(idx, 1)
            }
          }
          deps.scheduleWorkspacePersist()
          continue
        }
      }

      // Prefer binding onto an existing wf-out active layer when present.
      const targetCatalogId = matchingOutput?.localId
      const existingActive = targetCatalogId
        ? deps
            .getActiveLayers()
            .find((layer) => layer.catalogId === targetCatalogId && !layer.isAdminBoundary)
        : deps
            .getActiveLayers()
            .find((layer) => layer.catalogId === preferredCatalogId && !layer.isAdminBoundary)

      if (existingActive && !existingActive.importedRaster) {
        // 2026-08-24 三联报障 B：绑定产物 overlay 到用户层时保留用户已选定的
        // 配色/量程覆盖（分析框 paletteOverride 等）——产物 overlay 与静态
        // catalog overlay 的注册 palette 可能不同，若不保留，渲染源切换后
        // 用户配色会突变回产物默认色（"一开始一个颜色然后突然换配色"）。
        const userPalette = existingActive.paletteOverride ?? null
        const userVmin = existingActive.vminOverride ?? null
        const userVmax = existingActive.vmaxOverride ?? null
        existingActive.importedRaster = buildImportedRasterPayload(item.overlayLayerId, {
          bounds: item.bounds,
          fileName: displayName,
          sourceCrs: item.sourceCrs,
          nativeStep: nativeStep || (timeList?.length ? '8d' : null),
          timeList,
          followPolicy: timeList?.length ? 'containing' : undefined,
        })
        existingActive.dataState = 'imported'
        if (userPalette) existingActive.paletteOverride = userPalette
        if (userVmin != null) existingActive.vminOverride = userVmin
        if (userVmax != null) existingActive.vmaxOverride = userVmax
        if (!existingActive.name) existingActive.name = displayName
        if (existingActive.runGroupId) refreshRunGroupDissolvable(existingActive.runGroupId)
        continue
      }

      // F3：兜底新增图层命名——禁止 overlay / 英文 workflow id 泄漏为 TOC 名
      const workflowDisplayName = runId
        ? jobLayers.value.find((j) => j.jobId === runId)?.name
        : undefined
      const safeWorkflowName =
        workflowDisplayName && !isEnglishInversionCatalogId(workflowDisplayName)
          ? workflowDisplayName
          : ''
      const freeGroupTitle = groupByRun?.title
        ? groupByRun.title.replace(/\s*·\s*(?:计算中|已完成|部分失败|执行失败)$/u, '').trim()
        : ''
      const safeFreeGroupTitle =
        freeGroupTitle && !isEnglishInversionCatalogId(freeGroupTitle) ? freeGroupTitle : ''
      const freeLayerName =
        matchingOutput?.name ||
        (tag ? productTagLabel(tag) : '') ||
        safeWorkflowName ||
        safeCleanTitle ||
        safeFreeGroupTitle ||
        productTagLabel(tag || 'result')

      // 组存在但 tag 槽缺失（常见：占位仅 result、产物为 SM/VOD/OMEGA）：
      // 补建 wf-run-* 成员再绑定，禁止 catalogId=imported-omega_sf_fenkuai_*。
      if (groupByRun && tag) {
        const slotTag = tag
        const safeCid = `wf-run-${groupByRun.groupId}-${String(slotTag).toLowerCase()}`
        let slot =
          deps
            .getActiveLayers()
            .find(
              (layer) =>
                layer.runGroupId === groupByRun.groupId &&
                normalizeProductTag(layer.runGroupProductTag) === slotTag,
            ) || deps.getActiveLayers().find((layer) => layer.catalogId === safeCid)
        if (!slot) {
          const accent = deps.assignLayerAccent(undefined)
          const maxOrder = deps.getActiveLayers().reduce((max, l) => Math.max(max, l.order), -1)
          slot = {
            instanceId: deps.genInstanceId(),
            catalogId: safeCid,
            name: freeLayerName,
            visible: true,
            opacity: 1,
            order: maxOrder + 1,
            isAdminBoundary: false,
            dataState: 'catalog',
            accentColor: accent.accentColor,
            accentGlow: accent.accentGlow,
            chipTone: accent.chipTone,
            runGroupId: groupByRun.groupId,
            runGroupProductTag: slotTag,
            runGroupLocked: groupByRun.status === 'computing',
          }
          deps.getActiveLayers().push(slot)
          if (!groupByRun.memberInstanceIds.includes(slot.instanceId)) {
            groupByRun.memberInstanceIds.push(slot.instanceId)
          }
        }
        slot.importedRaster = buildImportedRasterPayload(item.overlayLayerId, {
          bounds: item.bounds,
          fileName: slot.name || freeLayerName,
          sourceCrs: item.sourceCrs,
          nativeStep: nativeStep || (timeList?.length ? '8d' : null),
          timeList,
          followPolicy: timeList?.length ? 'containing' : undefined,
        })
        slot.dataState = 'imported'
        if (!slot.name || isEnglishInversionCatalogId(slot.name)) {
          slot.name = freeLayerName
        }
        slot.runGroupId = groupByRun.groupId
        slot.runGroupProductTag = slot.runGroupProductTag || slotTag
        if (!groupByRun.memberInstanceIds.includes(slot.instanceId)) {
          groupByRun.memberInstanceIds.push(slot.instanceId)
        }
        // 治理重复/旧失败层：清理组内同 tag 的其它废弃成员
        const redundantMembers = deps
          .getActiveLayers()
          .filter(
            (l) =>
              l.runGroupId === groupByRun.groupId &&
              l.instanceId !== slot.instanceId &&
              (normalizeProductTag(l.runGroupProductTag) === tag ||
                normalizeProductTag(l.name) === tag ||
                (tag === 'NDVI' && (l.catalogId === 'ndvi' || l.catalogId.includes('ndvi')))) &&
              (!l.importedRaster?.overlayLayerId ||
                l.jobLayer?.status === 'failed' ||
                l.jobLayer?.status === 'cancelled'),
          )
        for (const red of redundantMembers) {
          deps.removeLayer(red.instanceId)
          groupByRun.memberInstanceIds = groupByRun.memberInstanceIds.filter(
            (id) => id !== red.instanceId,
          )
        }
        refreshRunGroupDissolvable(groupByRun.groupId)
        deps.scheduleWorkspacePersist()
        continue
      }

      // 无计算组时不要用 imported-omega_* 当 catalogId 建游离层——
      // 归到目录 method-*（若可解析）或跳过建层、仅保留组内绑定路径。
      if (isEnglishInversionCatalogId(item.overlayLayerId)) {
        const mapped = resolveInversionCatalogId(item.overlayLayerId)
        const catalogTarget = deps
          .getActiveLayers()
          .find((layer) => layer.catalogId === mapped && !layer.isAdminBoundary)
        if (catalogTarget && !catalogTarget.importedRaster) {
          catalogTarget.importedRaster = buildImportedRasterPayload(item.overlayLayerId, {
            bounds: item.bounds,
            fileName: freeLayerName,
            sourceCrs: item.sourceCrs,
            nativeStep: nativeStep || (timeList?.length ? '8d' : null),
            timeList,
            followPolicy: timeList?.length ? 'containing' : undefined,
          })
          catalogTarget.dataState = 'imported'
          if (!catalogTarget.name || isEnglishInversionCatalogId(catalogTarget.name)) {
            catalogTarget.name = freeLayerName
          }
          deps.scheduleWorkspacePersist()
        }
        continue
      }
      const added = deps.addImportedRasterLayer(freeLayerName, item.overlayLayerId, item.bounds, {
        sourceCrs: item.sourceCrs,
        nativeStep: nativeStep || (timeList?.length ? '8d' : null),
        timeList,
        followPolicy: timeList?.length ? 'containing' : undefined,
      })
      if (added && groupByRun) {
        added.runGroupId = groupByRun.groupId
        added.runGroupProductTag = item.productTag || tag || 'result'
        added.runGroupLocked = groupByRun.status === 'computing'
        if (!groupByRun.memberInstanceIds.includes(added.instanceId)) {
          groupByRun.memberInstanceIds.push(added.instanceId)
        }
        refreshRunGroupDissolvable(groupByRun.groupId)
      }
    }
    if (runId) {
      const g = runLayerGroups.value.find((x) => x.runId === runId)
      if (g) refreshRunGroupDissolvable(g.groupId)
      const job = jobLayers.value.find((j) => j.jobId === runId)
      if (job?.inFlightTimeKeys?.length) {
        const readyKeys = deps
          .getActiveLayers()
          .flatMap((l) => l.importedRaster?.timeList ?? [])
          .filter(Boolean)
        job.inFlightTimeKeys = pruneInFlightTimeKeys(job.inFlightTimeKeys, readyKeys)
      }
    }
    reconcileOmegaBlockLayers()
    scrubEnglishInversionFreeLayers()
    deps.scheduleWorkspacePersist()
    return imports.length
  }

  /** 清掉误以英文反演 overlay/workflow id 为 catalogId/显示名的游离层（不删后端 overlay）。 */
  function scrubEnglishInversionFreeLayers() {
    const layers = deps.getActiveLayers()
    for (let i = layers.length - 1; i >= 0; i--) {
      const layer = layers[i]!
      // 显示名整段仍是技术 id：就地改写（含已在组内的成员）
      if (layer.name && isEnglishInversionCatalogId(layer.name)) {
        const tag = normalizeProductTag(layer.runGroupProductTag || '') || 'result'
        layer.name = productTagLabel(tag)
      }
      if (!isEnglishInversionCatalogId(layer.catalogId)) continue
      // 已在计算组内且 catalogId 仍是技术 id：改写为安全 wf-run id，保留产物
      if (layer.runGroupId) {
        const tag = normalizeProductTag(layer.runGroupProductTag || layer.name) || 'result'
        const safeCid = `wf-run-${layer.runGroupId}-${tag.toLowerCase()}`
        layer.catalogId = safeCid
        if (!layer.name || isEnglishInversionCatalogId(layer.name)) {
          layer.name = productTagLabel(tag)
        }
        continue
      }
      // 无组游离层：丢弃 UI 条目（产物可经 restore/autoAttach 再绑）
      layers.splice(i, 1)
    }
    // 组标题若落成技术占位（wf-run-* / omega_sf_*），纠偏为中文名
    for (const group of runLayerGroups.value) {
      if (!group.title || !isTechnicalRunTitle(group.title)) continue
      group.title = resolveRunGroupTitle({
        workflowId: group.workflowId,
        configuredTitle: group.title,
        summaries: tryWorkflowSummaries(),
        fallback: '工作流产物',
      })
    }
  }

  /** 把游离的 OMEGA_BLOCK 并入组内 OMEGA 占位，去掉重复条目（不删后端文件） */
  function reconcileOmegaBlockLayers() {
    const orphans = deps.getActiveLayers().filter((layer) => {
      if (!layer.importedRaster?.overlayLayerId) return false
      const name = `${layer.name || ''} ${layer.importedRaster.fileName || ''}`.toUpperCase()
      return (
        name.includes('OMEGA_BLOCK') ||
        normalizeProductTag(layer.name) === 'OMEGA' ||
        layer.name === productTagLabel('OMEGA')
      )
    })
    for (const orphan of [...orphans]) {
      // 只处理名为 OMEGA_BLOCK 的游离层
      const orphanName = String(orphan.name || orphan.importedRaster?.fileName || '').toUpperCase()
      if (!orphanName.includes('OMEGA_BLOCK')) continue
      // 保护用户静态层：仅当该层归属某个工作流计算组（有 runGroupId 或
      // runGroupProductTag，即后端产物经工作流物化）才并入组内占位。用户手动
      // 导入/添加的 OMEGA_BLOCK .mat（无任何 run 组归属）是用户自己的图层，
      // 不得被改名/并入/摘除 —— 否则用户静态层被吞（2026-08-23 症状一）。
      if (!orphan.runGroupId && !orphan.runGroupProductTag) continue
      const placeholder = deps
        .getActiveLayers()
        .find(
          (layer) =>
            layer.instanceId !== orphan.instanceId &&
            !layer.importedRaster &&
            normalizeProductTag(layer.runGroupProductTag || layer.name) === 'OMEGA',
        )
      if (!placeholder) {
        // 无占位：直接把游离层改名为 ω 显示名（runGroupProductTag 保持内部值）
        orphan.name = productTagLabel('OMEGA')
        if (orphan.runGroupProductTag) orphan.runGroupProductTag = 'OMEGA'
        continue
      }
      placeholder.importedRaster = { ...orphan.importedRaster! }
      placeholder.dataState = 'imported'
      placeholder.name = productTagLabel('OMEGA')
      placeholder.runGroupProductTag = placeholder.runGroupProductTag || 'OMEGA'
      // 摘掉游离层引用后从列表移除（不清后端）
      orphan.importedRaster = undefined
      const idx = deps.getActiveLayers().findIndex((l) => l.instanceId === orphan.instanceId)
      if (idx >= 0) deps.getActiveLayers().splice(idx, 1)
      if (orphan.runGroupId) {
        const og = runLayerGroups.value.find((x) => x.groupId === orphan.runGroupId)
        if (og) {
          og.memberInstanceIds = og.memberInstanceIds.filter((id) => id !== orphan.instanceId)
          if (!og.memberInstanceIds.length) {
            runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== og.groupId)
          }
        }
      }
      if (placeholder.runGroupId) refreshRunGroupDissolvable(placeholder.runGroupId)
    }
    scrubEnglishInversionFreeLayers()
  }

  function reorderLayers(fromIndex: number, toIndex: number) {
    // Display order is descending (list top = map top = high order)
    const sorted = deps
      .getActiveLayers()
      .slice()
      .sort((a, b) => b.order - a.order)
    const moved = sorted[fromIndex]
    if (!moved) return

    // 锁定组成员：只允许组内调序
    if (moved.runGroupId && moved.runGroupLocked) {
      const group = runLayerGroups.value.find((g) => g.groupId === moved.runGroupId)
      if (group) {
        const memberSet = new Set(group.memberInstanceIds)
        const target = sorted[toIndex]
        if (!target || !memberSet.has(target.instanceId)) return
        reorderWithinRunGroup(
          moved.runGroupId,
          group.memberInstanceIds.indexOf(moved.instanceId),
          group.memberInstanceIds.indexOf(target.instanceId),
        )
        return
      }
    }

    // 禁止把外部图层插进锁定组块中间
    const target = sorted[toIndex]
    if (
      target?.runGroupId &&
      target.runGroupLocked &&
      (!moved.runGroupId || moved.runGroupId !== target.runGroupId)
    ) {
      return
    }

    const [item] = sorted.splice(fromIndex, 1)
    if (!item) return
    sorted.splice(toIndex, 0, item)
    sorted.forEach((layer, i) => {
      layer.order = sorted.length - 1 - i
    })
    deps.scheduleWorkspacePersist()
  }

  function syncGroupMemberOrders(group: ActiveRunLayerGroup) {
    const members = group.memberInstanceIds
      .map((id) => deps.getActiveLayers().find((l) => l.instanceId === id))
      .filter((l): l is ActiveLayer => Boolean(l))
    if (!members.length) return
    const minOrder = Math.min(...members.map((m) => m.order))
    // memberInstanceIds[0] should sit at list top within the block → highest order
    members.forEach((m, i) => {
      m.order = minOrder + (members.length - 1 - i)
    })
    // 压缩全局 order，保持相对块位置（升序存储，显示时再降序）
    const sorted = deps
      .getActiveLayers()
      .slice()
      .sort((a, b) => a.order - b.order)
    sorted.forEach((layer, i) => {
      layer.order = i
    })
  }

  function createRunLayerGroup(options: {
    title: string
    targets: Array<{ name: string; productTag: string }>
    sourceLayerId: string
    workflowId: string
    memberCatalogIds?: string[]
  }): { groupId: string; memberInstanceIds: string[]; memberCatalogIds: string[] } {
    const groupId = `run-group-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    const memberInstanceIds: string[] = []
    const memberCatalogIds: string[] = []
    const maxOrder = deps.getActiveLayers().reduce((max, l) => Math.max(max, l.order), -1)
    const accent = deps.assignLayerAccent(undefined)

    options.targets.forEach((t, i) => {
      const catalogId =
        options.memberCatalogIds?.[i] ||
        `wf-run-${groupId}-${String(t.productTag || 'result').toLowerCase()}`
      // 成员显示名：英文技术 id / 空串 → productTag 中文/短名
      const memberName =
        t.name && !isEnglishInversionCatalogId(t.name) ? t.name : productTagLabel(t.productTag)
      const layer: ActiveLayer = {
        instanceId: deps.genInstanceId(),
        catalogId,
        name: memberName,
        visible: true,
        opacity: 1,
        order: maxOrder + options.targets.length - i,
        isAdminBoundary: false,
        dataState: 'catalog',
        accentColor: accent.accentColor,
        accentGlow: accent.accentGlow,
        chipTone: accent.chipTone,
        runGroupId: groupId,
        runGroupProductTag: t.productTag,
        runGroupLocked: true,
      }
      deps.getActiveLayers().push(layer)
      memberInstanceIds.push(layer.instanceId)
      memberCatalogIds.push(catalogId)
    })

    runLayerGroups.value.push({
      groupId,
      runId: '',
      title: resolveRunGroupTitle({
        configuredTitle: options.title,
        workflowId: options.workflowId,
        summaries: tryWorkflowSummaries(),
        fallback: '反演产物',
      }),
      status: 'computing',
      memberInstanceIds,
      dissolvable: false,
      sourceLayerId: options.sourceLayerId,
      workflowId: options.workflowId,
      progress: 0,
      message: '等待计算…',
    })

    if (deps.getSidebarView() === 'empty' || deps.getSidebarView() === 'library') {
      deps.setSidebarView('active')
    }
    if (memberInstanceIds[0]) {
      deps.setSelectedInstanceId(memberInstanceIds[0])
    }
    return { groupId, memberInstanceIds, memberCatalogIds }
  }

  function bindRunIdToGroup(groupId: string, runId: string) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    g.runId = runId
    deps.scheduleWorkspacePersist()
  }

  /**
   * 终态后清理未产出占位图层：无 overlay 的组成员移除；
   * 已有栅格产物的成员保留并解锁。
   * - failed/cancelled：成员标注「（部分）」，组状态置 failed/cancelled；
   * - succeeded（opts.succeeded）：产物为完整结果不加「（部分）」，组状态置 ready，
   *   全部成员可显示时经 refreshRunGroupDissolvable 解锁可拆。
   */
  function cleanupUnproducedRunLayers(runId: string, opts?: { succeeded?: boolean }) {
    if (!runId) return
    progressiveMaterializeAt.delete(runId)
    progressiveMaterializeInFlight.delete(runId)

    const g = runLayerGroups.value.find((x) => x.runId === runId)
    if (!g) return

    const removeIds: string[] = []
    for (const instanceId of [...g.memberInstanceIds]) {
      const layer = deps.getActiveLayers().find((l) => l.instanceId === instanceId)
      if (!layer) {
        removeIds.push(instanceId)
        continue
      }
      if (!layer.importedRaster?.overlayLayerId) {
        const hasOtherMaterialized = g.memberInstanceIds.some((id) => {
          if (id === instanceId) return false
          const other = deps.getActiveLayers().find((l) => l.instanceId === id)
          return Boolean(other?.importedRaster?.overlayLayerId)
        })
        if (layer.catalogId.startsWith('wf-run-') || (opts?.succeeded && hasOtherMaterialized)) {
          removeIds.push(instanceId)
        } else {
          layer.runGroupLocked = false
        }
      } else {
        layer.runGroupLocked = false
        if (!opts?.succeeded) {
          const tag = normalizeProductTag(layer.runGroupProductTag || layer.name)
          const defaultLabel = tag ? productTagLabel(tag) : ''
          if (
            layer.name &&
            !layer.name.includes('（部分）') &&
            isDefaultProductDisplayName(layer.name, tag, defaultLabel)
          ) {
            layer.name = `${layer.name}（部分）`
          }
        }
      }
    }
    for (const instanceId of removeIds) {
      // 占位无 overlay：removeLayer 不会删后端文件
      deps.removeLayer(instanceId)
    }

    const left = runLayerGroups.value.find((x) => x.groupId === g.groupId)
    if (left) {
      left.memberInstanceIds = left.memberInstanceIds.filter((id) => !removeIds.includes(id))
      if (opts?.succeeded) {
        left.status = 'ready'
        refreshRunGroupDissolvable(left.groupId)
      } else {
        left.dissolvable = true
        left.status = left.status === 'failed' ? 'failed' : 'cancelled'
      }
      if (!left.memberInstanceIds.length) {
        runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== left.groupId)
      }
    }
    deps.scheduleWorkspacePersist()
  }

  /** 组内仍有未绑定 overlay 的占位（SM/VOD/OMEGA 部分物化） */
  function hasUnboundRunGroupPlaceholders(runId: string): boolean {
    if (!runId) return false
    const g = runLayerGroups.value.find((x) => x.runId === runId)
    if (!g) return false
    return g.memberInstanceIds.some((instanceId) => {
      const layer = deps.getActiveLayers().find((l) => l.instanceId === instanceId)
      return Boolean(layer && !layer.importedRaster?.overlayLayerId)
    })
  }

  function refreshRunGroupDissolvable(groupId: string) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    const activeLayers = deps.getActiveLayers()
    const members = g.memberInstanceIds
      .map((id) => activeLayers.find((l) => l.instanceId === id))
      .filter((l): l is ActiveLayer => Boolean(l))

    // 自愈：若组内已有水合成功的产物成员，清理同 tag 的旧失败成员或无数据占位
    const successfulTags = new Set(
      members
        .filter((m) => Boolean(m.importedRaster?.overlayLayerId))
        .map((m) => normalizeProductTag(m.runGroupProductTag || m.name))
        .filter(Boolean),
    )
    if (successfulTags.size > 0) {
      const deadIds: string[] = []
      for (const m of members) {
        const tag = normalizeProductTag(m.runGroupProductTag || m.name)
        if (
          tag &&
          successfulTags.has(tag) &&
          (!m.importedRaster?.overlayLayerId ||
            m.jobLayer?.status === 'failed' ||
            m.jobLayer?.status === 'cancelled')
        ) {
          deadIds.push(m.instanceId)
        }
      }
      if (deadIds.length) {
        for (const id of deadIds) {
          deps.removeLayer(id)
        }
        g.memberInstanceIds = g.memberInstanceIds.filter((id) => !deadIds.includes(id))
      }
    }

    const currentMembers = g.memberInstanceIds
      .map((id) => activeLayers.find((l) => l.instanceId === id))
      .filter((l): l is ActiveLayer => Boolean(l))
    const allDisplayable =
      currentMembers.length > 0 &&
      currentMembers.every((m) => Boolean(m.importedRaster?.overlayLayerId))
    if (g.status === 'failed' || g.status === 'cancelled') {
      g.dissolvable = true
      currentMembers.forEach((m) => {
        m.runGroupLocked = false
      })
      return
    }
    if (g.status === 'ready' && allDisplayable) {
      g.dissolvable = true
      currentMembers.forEach((m) => {
        m.runGroupLocked = false
      })
    }
  }

  function updateRunGroupFromJob(
    runId: string,
    job: Pick<JobLayerItem, 'status' | 'progress' | 'message' | 'nodeProgress'>,
  ) {
    const g = runLayerGroups.value.find((x) => x.runId === runId)
    if (!g) return
    if (job.status === 'succeeded') g.status = 'ready'
    else if (job.status === 'failed') g.status = 'failed'
    else if (job.status === 'cancelled') g.status = 'cancelled'
    else g.status = 'computing'
    if (typeof job.progress === 'number') g.progress = job.progress
    const latest = pickLatestNodeProgress(job.nodeProgress)
    const shell = formatProgressShell({
      progress: job.progress,
      message: job.message,
      stage: latest?.stage,
      nodeLabel: latest?.nodeLabel,
      detail: latest?.detail,
    })
    if (shell) g.message = shell
    else if (job.message) g.message = job.message
    refreshRunGroupDissolvable(g.groupId)
  }

  function dissolveRunGroup(groupId: string) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    for (const id of g.memberInstanceIds) {
      const layer = deps.getActiveLayers().find((l) => l.instanceId === id)
      if (!layer) continue
      layer.runGroupId = undefined
      layer.runGroupProductTag = undefined
      layer.runGroupLocked = undefined
    }
    runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== groupId)
    deps.scheduleWorkspacePersist()
  }

  /**
   * 丢弃探测用 run 组的 UI 条目（不删后端 overlay）。
   * autoAttach 按 preferredTimeKey 试跑多条成功 run 时，未命中的探测组必须清掉，
   * 否则 TOC/库会残留多组 SM/VOD/ω 或英文技术名占位。
   */
  function discardRunGroupUi(runId: string) {
    if (!runId) return
    const g = runLayerGroups.value.find((x) => x.runId === runId)
    if (!g) return
    const layers = deps.getActiveLayers()
    for (const instanceId of [...g.memberInstanceIds]) {
      const idx = layers.findIndex((l) => l.instanceId === instanceId)
      if (idx < 0) continue
      // 仅摘 UI：清空 raster 引用后再 splice，避免走 removeLayer 的后端删除
      layers[idx]!.importedRaster = undefined
      layers.splice(idx, 1)
    }
    runLayerGroups.value = runLayerGroups.value.filter((x) => x.groupId !== g.groupId)
    scrubEnglishInversionFreeLayers()
    deps.scheduleWorkspacePersist()
  }

  function reorderWithinRunGroup(groupId: string, fromMemberIndex: number, toMemberIndex: number) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    if (
      fromMemberIndex < 0 ||
      toMemberIndex < 0 ||
      fromMemberIndex >= g.memberInstanceIds.length ||
      toMemberIndex >= g.memberInstanceIds.length
    ) {
      return
    }
    const ids = [...g.memberInstanceIds]
    const [moved] = ids.splice(fromMemberIndex, 1)
    if (!moved) return
    ids.splice(toMemberIndex, 0, moved)
    g.memberInstanceIds = ids
    syncGroupMemberOrders(g)
    deps.scheduleWorkspacePersist()
  }

  /** 将整组在 TOC 中上下移动：toAnchorInstanceId 为落点图层（组外）的 instanceId */
  function moveRunGroupBlock(
    groupId: string,
    toAnchorInstanceId: string | null,
    placeAfter: boolean,
  ) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    const memberSet = new Set(g.memberInstanceIds)
    const sorted = deps
      .getActiveLayers()
      .slice()
      .sort((a, b) => a.order - b.order)
    const block = sorted.filter((l) => memberSet.has(l.instanceId))
    const rest = sorted.filter((l) => !memberSet.has(l.instanceId))
    if (!block.length) return

    let insertAt = rest.length
    if (toAnchorInstanceId) {
      const idx = rest.findIndex((l) => l.instanceId === toAnchorInstanceId)
      if (idx >= 0) insertAt = placeAfter ? idx + 1 : idx
    }
    const next = [...rest.slice(0, insertAt), ...block, ...rest.slice(insertAt)]
    next.forEach((layer, i) => {
      layer.order = i
    })
    g.memberInstanceIds = block.map((l) => l.instanceId)
    deps.scheduleWorkspacePersist()
  }

  function findRunGroupByMember(instanceId: string): ActiveRunLayerGroup | null {
    const layer = deps.getActiveLayers().find((l) => l.instanceId === instanceId)
    if (!layer?.runGroupId) return null
    return runLayerGroups.value.find((g) => g.groupId === layer.runGroupId) ?? null
  }

  function findRunGroupById(groupId: string): ActiveRunLayerGroup | null {
    return runLayerGroups.value.find((g) => g.groupId === groupId) ?? null
  }

  return {
    jobLayers,
    runLayerGroups,
    workflowError,
    workflowProgressTimeSeek,
    workflowSummary,
    emitWorkflowProgressTimeSeek,
    removeJobLayerById,
    updateRunGroupForCatalog,
    setJobLayers,
    syncJobLayerToActiveLayer,
    upsertJobLayer,
    buildWorkflowPayloadForCatalog,
    formatProgressiveSyncMessage,
    applyProgressiveSyncToJob,
    syncProgressiveBlockOverlays,
    attachAlgorithmProductOverlays,
    reconcileOmegaBlockLayers,
    reorderLayers,
    syncGroupMemberOrders,
    createRunLayerGroup,
    bindRunIdToGroup,
    cleanupUnproducedRunLayers,
    hasUnboundRunGroupPlaceholders,
    refreshRunGroupDissolvable,
    updateRunGroupFromJob,
    dissolveRunGroup,
    discardRunGroupUi,
    reorderWithinRunGroup,
    moveRunGroupBlock,
    findRunGroupByMember,
    findRunGroupById,
  }
}
