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
import { formatProgressShell, pickLatestNodeProgress } from '../../utils/workflow-progress-format'
import { isTerminalStatus } from './catalog-builders'
import { WORKFLOW_COPY } from '../../ui-copy/workflow'
import { resolveEmptyOverlayWorkflowError } from './materialize-empty'
import { productTagLabel } from '../../utils/workflow-expected-outputs'
import { isDefaultProductDisplayName } from './layer-naming'
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
  addLayer: (catalogId: string, isAdminBoundary?: boolean, jobLayer?: JobLayerItem) => void
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
    let overall: WorkflowSummary['overall'] = 'idle'
    let tone: WorkflowSummary['tone'] = 'idle'
    if (active > 0) {
      overall = 'active'
      tone = 'active'
    } else if (counts.failed > 0 && counts.succeeded > 0) {
      overall = 'mixed'
      tone = 'warning'
    } else if (counts.failed > 0) {
      overall = 'failed'
      tone = 'error'
    } else if (counts.succeeded > 0) {
      overall = 'succeeded'
      tone = 'success'
    }
    return {
      total: layers.length,
      running: counts.running,
      queued: counts.queued,
      succeeded: counts.succeeded,
      failed: counts.failed,
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
      .find((layer) => layer.catalogId === catalogId && !layer.isAdminBoundary)
    if (existingCatalogLayer) {
      existingCatalogLayer.jobLayer = jobLayer
      existingCatalogLayer.dataState = 'real'
      // 不在工作流更新时修改 selectedInstanceId，避免视口变化重提交导致图层选中被篡改
      return
    }

    deps.addLayer(catalogId, false, jobLayer)
  }

  function upsertJobLayer(catalogId: string, jobLayer: JobLayerItem) {
    // 确保 catalogId 被记录在 jobLayer 上，便于面板列表展示孤儿工作流（无活跃图层时）
    const enrichedJobLayer: JobLayerItem = jobLayer.catalogId
      ? jobLayer
      : { ...jobLayer, catalogId }
    const existingIndex = jobLayers.value.findIndex((item) => item.jobId === enrichedJobLayer.jobId)
    if (existingIndex >= 0) {
      jobLayers.value.splice(existingIndex, 1, enrichedJobLayer)
    } else {
      jobLayers.value.unshift(enrichedJobLayer)
    }
    syncJobLayerToActiveLayer(catalogId, enrichedJobLayer)
    deps.rememberTrackedWorkflowRun(catalogId, enrichedJobLayer)
    updateRunGroupForCatalog(catalogId, enrichedJobLayer)
    if (isTerminalStatus(enrichedJobLayer.status)) {
      if (enrichedJobLayer.status === 'cancelled' || enrichedJobLayer.status === 'failed') {
        // local-submit 失败时按 catalog 找组清理占位；真 run 按 runId
        if (deps.isLocalSubmitJobId(enrichedJobLayer.jobId)) {
          const layer = deps.getActiveLayers().find((l) => l.catalogId === catalogId)
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
    if (emptyOverlayConfirmTimers.has(runId)) return
    emptyOverlayConfirmTimers.set(
      runId,
      setTimeout(() => {
        emptyOverlayConfirmTimers.delete(runId)
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
      }, 2500),
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
      try {
        const materialized = await materializeWorkflowMapLayers(runId)
        materializedLayers = materialized.layers ?? []
        if (!imports.length) {
          imports = materializedLayers
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
        }
      } catch (error) {
        const errMsg = error instanceof Error ? error.message : String(error)
        console.warn('[layers] materializeWorkflowMapLayers failed', runId, error)
        safeLog(
          'workflow-error',
          '工作流地图图层物化失败',
          `run=${runId} err=${String(error)}`,
          'warn',
        )
        // Failed/cancelled runs correctly get 409 from BE — do not pin a yellow banner.
        const isNonMaterializableConflict =
          /\b409\b/.test(errMsg) ||
          /cannot materialize/i.test(errMsg) ||
          /ExecutionStatus\.(failed|cancelled)/i.test(errMsg)
        if (!isNonMaterializableConflict) {
          // 发布就绪修复（P0-9）：其它 materialize 失败落到 workflowError，
          // 避免"工作流显示 succeeded 但地图无图层、无任何错误提示"。
          workflowError.value = `工作流结果图层加载失败：${errMsg}`
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
      // R4：前缀剥两类——map_layer 产物（Algorithm Map Layer）与 file 产物（Algorithm Output）
      const cleanTitle = (item.title || '')
        .replace(/^Algorithm (?:Map Layer|Output):\s*/i, '')
        .replace(/\s*[/\\][^/\\]*$/, '') // 路径段：只留文件名
        .replace(/\.(tif|tiff|png|jpe?g|mat|nc|zip|shp)$/i, '')
        .trim()
      const displayName =
        matchingOutput?.name ||
        (tag ? productTagLabel(tag) : '') ||
        cleanTitle ||
        item.productTag ||
        item.overlayLayerId

      // Bind only within this run's computing group (never cross-run by tag alone).
      const groupByRun = runId ? runLayerGroups.value.find((g) => g.runId === runId) : undefined
      const groupMember =
        groupByRun &&
        deps
          .getActiveLayers()
          .find(
            (layer) =>
              layer.runGroupId === groupByRun.groupId &&
              normalizeProductTag(layer.runGroupProductTag) === tag,
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

      // F3：兜底新增图层命名——技术名（Algorithm 标题 / overlay id）之前
      // 优先工作流显示名，避免游离图层直出英文技术名
      // R4：前缀剥两类——map_layer 产物（Algorithm Map Layer）与 file 产物（Algorithm Output）
      const workflowDisplayName = runId
        ? jobLayers.value.find((j) => j.jobId === runId)?.name
        : undefined
      const freeLayerName =
        matchingOutput?.name ||
        (tag ? productTagLabel(tag) : '') ||
        workflowDisplayName ||
        item.title.replace(/^Algorithm (?:Map Layer|Output):\s*/i, '') ||
        item.overlayLayerId
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
    deps.scheduleWorkspacePersist()
    return imports.length
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
      const layer: ActiveLayer = {
        instanceId: deps.genInstanceId(),
        catalogId,
        name: t.name,
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
      title: options.title,
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
        removeIds.push(instanceId)
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

  function refreshRunGroupDissolvable(groupId: string) {
    const g = runLayerGroups.value.find((x) => x.groupId === groupId)
    if (!g) return
    const members = g.memberInstanceIds
      .map((id) => deps.getActiveLayers().find((l) => l.instanceId === id))
      .filter((l): l is ActiveLayer => Boolean(l))
    const allDisplayable =
      members.length > 0 && members.every((m) => Boolean(m.importedRaster?.overlayLayerId))
    if (g.status === 'failed' || g.status === 'cancelled') {
      g.dissolvable = true
      members.forEach((m) => {
        m.runGroupLocked = false
      })
      return
    }
    if (g.status === 'ready' && allDisplayable) {
      g.dissolvable = true
      members.forEach((m) => {
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
    refreshRunGroupDissolvable,
    updateRunGroupFromJob,
    dissolveRunGroup,
    reorderWithinRunGroup,
    moveRunGroupBlock,
    findRunGroupByMember,
    findRunGroupById,
  }
}
