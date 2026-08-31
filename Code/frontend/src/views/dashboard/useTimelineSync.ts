/**
 * useTimelineSync — 时间轴同步核心逻辑。
 *
 * 从 DashboardView.vue 提取：tileForecastHour / selectedCatalogId /
 * hasTimelineLayer / timelineLayerName / timelineAvailabilityLabel /
 * timelineObservationLabel / snapTimelineToLatestValid / snapTimelineToLayerLatest /
 * refreshImportedRasterEffectiveTimes / 新加图层 snap / 科学层渐进块跟随 /
 * 工作流进度 seek / 运行启动对齐 / 切层记忆恢复 /
 * activeLayerGranularity / isLayerLocked / timelineSegments。
 */
import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { useUiStore } from '../../stores/ui'
import { useTimelineActionBannerStore } from '../../stores/timeline-action-banner'
import { useLayerWorkspace, useWorkflowRun } from '../../stores/layers/selectors'
import type { useLogStore } from '../../stores/log'
import type { useWeatherTileManager } from '../../stores/weather-tile-manager'
import type { WeatherCoverage } from '../../services/runtime-api'
import type { OverlayTimeState } from '../../components/map/overlay-image-module'
import type { TimeGranularity, TimelineAvailabilitySegment } from '../../utils/layer-timeline'
import {
  buildClockDayTimelineSegments,
  dateHourToTileHour,
  findLatestValidCoverageInstant,
} from '../../utils/weather-timeline'
import { generateTimelineSegments } from '../../utils/layer-timeline'
import {
  referenceInstantFromTimeline,
  resolveLayerEffectiveTime,
  snapTargetFromLayer,
  temporalSpecFromActiveLayer,
} from '../../utils/layer-temporal'
import {
  dayAvailabilityFromTimeList,
  formatSliceLabel,
  monthAvailabilityFromTimeList,
  parseInstant,
  timeStepToLegacyGranularity,
  yearAvailabilityFromTimeList,
} from '../../utils/temporal-interval'
import {
  buildRunTimelineAvailability,
  overlayOnlineTemporalFetchable,
  type RunAvailabilityState,
} from '../../utils/run-timeline-availability'
import {
  resolveJobLayerForActiveLayer,
  resolveRunGroupForActiveLayer,
  resolveTimelineNativeStep,
  shouldUseExpectedTimelineAxis,
} from '../../utils/job-layer-coverage'
import {
  matchSliceLabelInTimeList,
  timelineTargetFromWorkflowTimeKey,
  type WorkflowProgressTimeSeekHint,
} from '../../utils/workflow-timekey-seek'
import type MapCanvas from '../../components/MapCanvas.vue'

interface ActiveLayerLike {
  catalogId?: string
  name?: string
  accentColor?: string
  availabilityLabel?: string
  observationTimeLabel?: string
  runReadiness?: unknown
  instanceId?: string
  isAdminBoundary?: boolean
  isImported?: boolean
  isImportedRaster?: boolean
}

interface SelectedLayerLike {
  catalogId?: string
  instanceId?: string
}

export function useTimelineSync(
  uiStore: ReturnType<typeof useUiStore>,
  logStore: ReturnType<typeof useLogStore>,
  weatherTileManager: ReturnType<typeof useWeatherTileManager>,
  weatherCoverage: Ref<WeatherCoverage | null>,
  mapCanvasRef: Ref<InstanceType<typeof MapCanvas> | null>,
  selectedLayerDisplay: Ref<SelectedLayerLike | null | undefined>,
  activeLayer: ComputedRef<ActiveLayerLike>,
  overlayTimeStates: Ref<OverlayTimeState[]>,
  currentHour: Ref<number>,
  currentDate: Ref<Date>,
  unifiedTimeLock: Ref<boolean>,
  isPlaying: Ref<boolean>,
  weatherStatusVersion: Ref<number>,
  weatherActivityVersion: Ref<number>,
  workflowProgressTimeSeek: Ref<WorkflowProgressTimeSeekHint | null>,
  analysisPanelRef: Ref<{ showPanel: () => void } | null>,
) {
  // ── Domain selectors ─────────────────────────────────────────────────
  const workspace = useLayerWorkspace()
  const workflowRun = useWorkflowRun()

  // ── 基础 computed ─────────────────────────────────────────────────────

  /** 瓦片 API 用的预报偏移 */
  const tileForecastHour = computed(() =>
    dateHourToTileHour(weatherCoverage.value, currentDate.value, currentHour.value),
  )

  watch(
    tileForecastHour,
    (hour) => {
      workspace.setCurrentHour(hour)
    },
    { immediate: true },
  )

  /** 当前选中图层 catalogId */
  const selectedCatalogId = computed(() => selectedLayerDisplay.value?.catalogId ?? null)

  /** 是否选中了真实图层 */
  const hasTimelineLayer = computed(() => Boolean(selectedLayerDisplay.value?.catalogId))

  const timelineLayerName = computed(() =>
    hasTimelineLayer.value ? activeLayer.value.name : '未选择图层',
  )
  const timelineAvailabilityLabel = computed(() =>
    hasTimelineLayer.value ? (activeLayer.value.availabilityLabel ?? '—') : '空闲',
  )
  const timelineObservationLabel = computed(() =>
    hasTimelineLayer.value ? (activeLayer.value.observationTimeLabel ?? '—') : '—',
  )

  // ── Snap / refresh 函数 ───────────────────────────────────────────────

  /** 新加天气图层：跳过切层记忆恢复 */
  const pendingSnapCatalogIds = new Set<string>()
  const knownActiveInstanceIds = new Set<string>()
  let layerTimeTrackingReady = false

  function snapTimelineToLatestValid(reason: string) {
    const selected = workspace.activeLayers.value.find(
      (l) => l.catalogId === selectedCatalogId.value,
    )
    const scienceSnap = snapTargetFromLayer(selected)
    if (scienceSnap) {
      uiStore.applyDateHour(scienceSnap.date, scienceSnap.hour)
      uiStore.applyTimelineFromLayerGranularity(scienceSnap.granularity)
      if (selectedCatalogId.value) {
        uiStore.rememberLayerTime(selectedCatalogId.value)
      }
      logStore.logOperation('timeline-snap-latest', `${reason} · ${scienceSnap.label}`)
      return
    }
    const latest = findLatestValidCoverageInstant(weatherCoverage.value, new Date())
    if (!latest) return
    uiStore.applyDateHour(latest.date, latest.hour)
    if (selectedCatalogId.value) {
      uiStore.rememberLayerTime(selectedCatalogId.value)
    }
    logStore.logOperation('timeline-snap-latest', reason)
  }

  function snapTimelineToLayerLatest(layerCatalogId: string, reason: string) {
    if (unifiedTimeLock.value) return
    if (uiStore.isLayerTimeLocked(layerCatalogId)) return
    const layer = workspace.activeLayers.value.find((l) => l.catalogId === layerCatalogId)
    const scienceSnap = snapTargetFromLayer(layer)
    if (!scienceSnap) return
    // 程序化 snap 抑制顶栏确认，避免 add→snap→confirm→reuse 循环
    useTimelineActionBannerStore().suppressConfirm(3_500)
    uiStore.applyDateHour(scienceSnap.date, scienceSnap.hour)
    uiStore.applyTimelineFromLayerGranularity(scienceSnap.granularity)
    uiStore.rememberLayerTime(layerCatalogId)
    logStore.logOperation('timeline-snap-latest', `${reason} · ${scienceSnap.label}`)
  }

  /** 按 T_ref 刷新各导入栅格层的生效时间标签 */
  function refreshImportedRasterEffectiveTimes() {
    const tRef = referenceInstantFromTimeline(currentDate.value, currentHour.value)
    for (const layer of workspace.activeLayers.value) {
      if (!layer.importedRaster) continue
      if (!layer.importedRaster.timeList?.length) {
        const oid = layer.importedRaster.overlayLayerId
        const st = oid
          ? overlayTimeStates.value.find((s) => s.layerId === oid && s.category === 'time-series')
          : null
        if (st?.timeList?.length) {
          layer.importedRaster.timeList = [...st.timeList]
          if (!layer.importedRaster.nativeStep) {
            layer.importedRaster.nativeStep = st.timeList.some((t) => /^\d{8}_\d{8}$/.test(t))
              ? '8d'
              : '1d'
          }
        }
      }
      const resolved = resolveLayerEffectiveTime(layer, tRef)
      if (!resolved?.slice) continue
      const sliceLabel = formatSliceLabel(resolved.slice)
      layer.importedRaster.effectiveTimeLabel = sliceLabel
      const overlayId = layer.importedRaster.overlayLayerId
      if (sliceLabel && overlayId) {
        void mapCanvasRef.value?.setOverlayTime?.(overlayId, sliceLabel)
      }
    }
  }

  // ── Watchers ──────────────────────────────────────────────────────────

  // 拖动/改日期：单通道刷新
  watch(
    () => [currentHour.value, currentDate.value, unifiedTimeLock.value] as const,
    () => {
      if (!unifiedTimeLock.value) {
        uiStore.rememberLayerTime(selectedCatalogId.value)
      }
      refreshImportedRasterEffectiveTimes()
    },
  )

  // 新加图层 snap
  watch(
    () => workspace.activeLayers.value.map((l) => l.instanceId),
    (ids) => {
      if (!layerTimeTrackingReady) {
        for (const id of ids) knownActiveInstanceIds.add(id)
        layerTimeTrackingReady = true
        return
      }
      const added = ids.filter((id) => !knownActiveInstanceIds.has(id))
      for (const id of ids) knownActiveInstanceIds.add(id)
      for (const id of Array.from(knownActiveInstanceIds)) {
        if (!ids.includes(id)) knownActiveInstanceIds.delete(id)
      }
      if (added.length === 0) return
      // 产品约定：添加图层强制独立记忆，再 snap 到最新有数据时刻
      if (unifiedTimeLock.value) {
        uiStore.setUnifiedTimeLock(false)
      }
      for (const instanceId of added) {
        const layer = workspace.activeLayers.value.find((l) => l.instanceId === instanceId)
        if (!layer) continue
        if (layer.importedRaster?.timeList?.length) {
          pendingSnapCatalogIds.add(layer.catalogId)
          // 工作流渐进物化带 runGroupId：未点播放不抢轴（色段仍会更新）
          if (!isPlaying.value && layer.runGroupId) {
            continue
          }
          snapTimelineToLayerLatest(layer.catalogId, `新加科学图层 ${layer.catalogId} → 最新切片`)
          uiStore.rememberLayerTime(layer.catalogId, { force: true })
          break
        }
        if (!workspace.isWeatherEngineLayer(layer.catalogId)) continue
        pendingSnapCatalogIds.add(layer.catalogId)
        snapTimelineToLatestValid(`新加图层 ${layer.catalogId} → 最新有效时次`)
        uiStore.rememberLayerTime(layer.catalogId, { force: true })
        break
      }
    },
    { immediate: true },
  )

  // 渐进块：仅在时间轴播放中跟随最新块；未点播放时不抢用户选定时刻
  const scienceTimeListSignature = computed(() =>
    workspace.activeLayers.value
      .filter((l) => l.importedRaster?.timeList?.length)
      .map(
        (l) =>
          `${l.catalogId}:${l.importedRaster!.timeList!.length}:${l.importedRaster!.timeList!.at(-1)}`,
      )
      .join('|'),
  )
  const knownScienceTimeSig = ref('')
  watch(scienceTimeListSignature, (sig) => {
    if (!layerTimeTrackingReady) {
      knownScienceTimeSig.value = sig
      return
    }
    if (!sig || sig === knownScienceTimeSig.value) return
    const prev = knownScienceTimeSig.value
    knownScienceTimeSig.value = sig

    refreshImportedRasterEffectiveTimes()
    if (!prev) return
    if (unifiedTimeLock.value) return
    if (!isPlaying.value) return

    const selected = workspace.activeLayers.value.find(
      (l) => l.catalogId === selectedCatalogId.value,
    )
    if (!selected?.importedRaster?.timeList?.length) return
    if (uiStore.isLayerTimeLocked(selected.catalogId)) return

    const times = selected.importedRaster.timeList
    const oldTip = times.length >= 2 ? times[times.length - 2]! : null
    if (!oldTip) return
    const tRef = referenceInstantFromTimeline(currentDate.value, currentHour.value)
    const resolved = resolveLayerEffectiveTime(selected, tRef)
    const curLabel = resolved?.slice ? formatSliceLabel(resolved.slice) : null
    if (curLabel !== oldTip) return

    snapTimelineToLayerLatest(selected.catalogId, `新块产出 ${selected.catalogId} → 跟随最新切片`)
    refreshImportedRasterEffectiveTimes()
  })

  // 工作流进度 seek
  function seekTimelineToWorkflowProgressTimeKey(
    catalogId: string,
    timeKey: string,
    sliceLabel: string,
    reason: string,
  ) {
    if (unifiedTimeLock.value) return
    // 未点播放时不随工作流块 seek；inFlight 键仍由 emitWorkflowProgressTimeSeek 更新色段
    if (!isPlaying.value) return
    if (uiStore.isLayerTimeLocked(catalogId)) return

    const target = timelineTargetFromWorkflowTimeKey(timeKey)
    if (!target) return

    uiStore.applyDateHour(target.date, target.hour)
    uiStore.applyTimelineFromLayerGranularity(target.granularity)
    uiStore.rememberLayerTime(catalogId)

    const layer = workspace.activeLayers.value.find((l) => l.catalogId === catalogId)
    const runGroupId = layer?.runGroupId
    const members = runGroupId
      ? workspace.activeLayers.value.filter(
          (l) => l.runGroupId === runGroupId && l.importedRaster?.overlayLayerId,
        )
      : layer?.importedRaster?.overlayLayerId
        ? [layer]
        : []

    for (const member of members) {
      const overlayId = member.importedRaster?.overlayLayerId
      if (!overlayId) continue
      const label =
        matchSliceLabelInTimeList(member.importedRaster?.timeList, sliceLabel) ?? sliceLabel
      void mapCanvasRef.value?.setOverlayTime?.(overlayId, label)
    }

    refreshImportedRasterEffectiveTimes()
    logStore.logOperation('timeline-seek-workflow', `${reason} · ${sliceLabel}`)
  }

  watch(
    workflowProgressTimeSeek,
    (hint) => {
      if (!hint) return
      const selected = selectedCatalogId.value
        ? workspace.activeLayers.value.find((l) => l.catalogId === selectedCatalogId.value)
        : null
      const hintLayer = workspace.activeLayers.value.find((l) => l.catalogId === hint.catalogId)
      const sameRunGroup =
        Boolean(selected?.runGroupId) &&
        Boolean(hintLayer?.runGroupId) &&
        selected!.runGroupId === hintLayer!.runGroupId
      if (selected && hint.catalogId !== selected.catalogId && !sameRunGroup) return
      seekTimelineToWorkflowProgressTimeKey(
        hint.catalogId,
        hint.timeKey,
        hint.sliceLabel,
        `工作流块 ${hint.runId.slice(0, 8)}`,
      )
    },
    { deep: true },
  )

  // 运行启动：仅在时间轴播放中首次对齐 start_at（未点播放不抢用户选定时刻）
  const alignedRunStartJobs = new Set<string>()
  watch(
    (): { jobId: string; startAt: string; status: string } | null => {
      const layer = workspace.activeLayers.value.find(
        (l) => l.catalogId === selectedCatalogId.value,
      )
      const job = resolveJobLayerForActiveLayer(
        layer,
        workflowRun.jobLayers.value,
        workflowRun.runLayerGroups.value,
      )
      const startAt = job?.expectedTimeRange?.start_at
      if (!job || !startAt) return null
      return { jobId: job.jobId, startAt, status: job.status }
    },
    (hint, prev) => {
      if (!hint) return
      if (hint.status !== 'running') return
      if (alignedRunStartJobs.has(hint.jobId)) return
      const isFreshRun =
        !prev ||
        prev.jobId !== hint.jobId ||
        prev.status === 'queued' ||
        prev.status === 'retry_pending'
      if (!isFreshRun) return
      if (unifiedTimeLock.value) return
      // 未点播放：仅记录已对齐，避免下次播放又跳回 start_at；不改 currentDate
      if (!isPlaying.value) {
        alignedRunStartJobs.add(hint.jobId)
        return
      }
      const catalogId = selectedCatalogId.value
      if (!catalogId || uiStore.isLayerTimeLocked(catalogId)) return
      const d = parseInstant(hint.startAt)
      if (!d) return
      useTimelineActionBannerStore().suppressConfirm(3_500)
      uiStore.applyDateHour(d, 0)
      alignedRunStartJobs.add(hint.jobId)
    },
  )

  // 切层：记忆恢复
  watch(selectedCatalogId, (catalogId, previous) => {
    if (!catalogId || catalogId === previous) return
    const layer = workspace.activeLayers.value.find((l) => l.catalogId === catalogId)
    const spec = temporalSpecFromActiveLayer(layer)
    if (spec) {
      uiStore.applyTimelineFromLayerGranularity(timeStepToLegacyGranularity(spec.nativeStep))
    } else if (layer?.importedRaster) {
      uiStore.applyTimelineFromLayerGranularity('static')
    } else {
      uiStore.applyTimelineFromLayerGranularity('hour')
    }
    if (unifiedTimeLock.value) {
      refreshImportedRasterEffectiveTimes()
      return
    }
    if (previous) {
      uiStore.rememberLayerTime(previous)
    }
    if (pendingSnapCatalogIds.has(catalogId)) {
      pendingSnapCatalogIds.delete(catalogId)
      refreshImportedRasterEffectiveTimes()
      return
    }
    const restored = uiStore.restoreLayerTime(catalogId)
    if (restored) {
      const times = layer?.importedRaster?.timeList ?? []
      const day = currentDate.value.getDate()
      const covered = times.length
        ? dayAvailabilityFromTimeList(currentDate.value, times)[day] === 'ready'
        : true
      if (!covered && spec) {
        snapTimelineToLayerLatest(catalogId, `切层 ${catalogId} · 记忆日无覆盖 → 最新切片`)
      } else {
        logStore.logOperation('timeline-restore-layer', `恢复图层 ${catalogId} 记忆时刻`)
      }
    } else if (spec) {
      snapTimelineToLayerLatest(catalogId, `切层 ${catalogId} → 最新切片`)
    }
    refreshImportedRasterEffectiveTimes()
  })

  // analysisFocusRequest → showPanel
  watch(
    () => uiStore.analysisFocusRequest,
    (request) => {
      if (!request) return
      analysisPanelRef.value?.showPanel()
    },
  )

  // ── 粒度 & 时间轴色段 ─────────────────────────────────────────────────

  const selectedActiveLayer = computed(
    () => workspace.activeLayers.value.find((l) => l.catalogId === selectedCatalogId.value) ?? null,
  )

  const activeLayerGranularity = computed<TimeGranularity>(() => {
    const layer = selectedActiveLayer.value
    const scienceSpec = temporalSpecFromActiveLayer(layer)
    if (scienceSpec) {
      return timeStepToLegacyGranularity(scienceSpec.nativeStep)
    }
    if (layer?.importedRaster) {
      return 'static'
    }
    const catalogId = layer?.catalogId ?? activeLayer.value?.catalogId
    if (!catalogId) return 'hour'
    if (workspace.isWeatherEngineLayer(catalogId)) return 'hour'
    const descriptor = workspace.resolveEffectiveDescriptor(catalogId)
    if (!descriptor) return 'hour'
    const gran =
      (descriptor as { time_granularity?: string }).time_granularity ||
      (descriptor as { timeGranularity?: string }).timeGranularity
    if (gran === 'static' || descriptor.supports_time === false) return 'static'
    if (gran === 'month' || gran === 'year' || gran === 'day' || gran === 'hour') return gran
    return 'hour'
  })

  const isLayerLocked = computed(() => {
    const catalogId = activeLayer.value?.catalogId
    return catalogId ? uiStore.isLayerTimeLocked(catalogId) : false
  })

  const timelineSegments = computed((): TimelineAvailabilitySegment[] => {
    // Touch reactive sources not accessed in every branch to ensure re-evaluation
    void weatherStatusVersion.value
    void weatherActivityVersion.value
    void weatherCoverage.value
    void overlayTimeStates.value
    void selectedActiveLayer.value?.importedRaster?.timeList
    void workflowRun.jobLayers.value
    void workflowRun.runLayerGroups.value

    if (!hasTimelineLayer.value) {
      return buildClockDayTimelineSegments({
        selectedDate: currentDate.value,
        currentHour: currentHour.value,
        coverage: null,
        currentStatus: null,
        isWeatherLayer: false,
      })
    }

    const gran = activeLayerGranularity.value
    if (gran === 'static') {
      // 事件时间轴（2026-08-25 用户反馈）：静态图层若带事件时间（overlay
      // meta time_list，如 ERA5 2020 灾害事件），按事件年份生成年刻度轴，
      // 事件年标记就绪；无事件时间才回落笼统的「静态」单段。
      const oid = selectedActiveLayer.value?.importedRaster?.overlayLayerId
      const eventTimes = oid
        ? (overlayTimeStates.value.find((s) => s.layerId === oid)?.timeList ?? [])
        : []
      const eventYears = [
        ...new Set(
          eventTimes
            .map((t) => /^\d{4}/.exec(String(t))?.[0])
            .filter((y): y is string => Boolean(y))
            .map(Number),
        ),
      ].sort((a, b) => a - b)
      if (eventYears.length > 0) {
        const start = Math.max(1, eventYears[0] - 1)
        const end = eventYears[eventYears.length - 1] + 1
        return Array.from({ length: end - start + 1 }, (_, idx): TimelineAvailabilitySegment => {
          const year = start + idx
          const isEvent = eventYears.includes(year)
          return {
            index: year,
            label: String(year),
            state: isEvent ? 'ready' : 'empty',
            availabilityLabel: isEvent ? `事件时间 ${year} · 资产就绪` : '无事件',
          }
        })
      }
      return generateTimelineSegments(currentDate.value, 'static')
    }

    const scienceLayer = selectedActiveLayer.value
    const fromStore = scienceLayer?.importedRaster?.timeList?.filter(Boolean) ?? []
    const oid = scienceLayer?.importedRaster?.overlayLayerId
    const fromOverlay = oid
      ? (overlayTimeStates.value.find((s) => s.layerId === oid)?.timeList ?? [])
      : []
    const scienceTimes = fromStore.length ? fromStore : fromOverlay.filter(Boolean)

    const jobForTimeline = resolveJobLayerForActiveLayer(
      scienceLayer,
      workflowRun.jobLayers.value,
      workflowRun.runLayerGroups.value,
    )
    const runGroup = resolveRunGroupForActiveLayer(scienceLayer, workflowRun.runLayerGroups.value)
    const expected = jobForTimeline?.expectedTimeRange
    const useExpectedAxis = shouldUseExpectedTimelineAxis({
      expected,
      job: jobForTimeline,
      runGroup,
      readyTimeCount: scienceTimes.length,
    })

    if (gran === 'day' || gran === 'month' || gran === 'year') {
      // 检查当前图层是否支持在线时间获取
      const onlineCap = selectedCatalogId.value
        ? workspace.getOnlineTemporalConfig(selectedCatalogId.value)
        : null

      if (useExpectedAxis && expected) {
        let map = buildRunTimelineAvailability({
          windowDate: currentDate.value,
          granularity: gran,
          expectedTimeRange: expected,
          nativeStep: resolveTimelineNativeStep({
            job: jobForTimeline,
            layer: scienceLayer,
            fallback: '1d',
          }),
          readyTimeList: scienceTimes,
          inFlightTimeKeys: jobForTimeline?.inFlightTimeKeys,
          failedTimeKeys: jobForTimeline?.failedTimeKeys,
          runFailed: jobForTimeline?.status === 'failed' || runGroup?.status === 'failed',
        })
        if (onlineCap) {
          map = overlayOnlineTemporalFetchable(
            map,
            currentDate.value,
            gran,
            onlineCap.coverage_start,
            onlineCap.coverage_end,
          )
        }
        return generateTimelineSegments(currentDate.value, gran, map)
      }
      let map: Record<number, RunAvailabilityState> =
        gran === 'day'
          ? dayAvailabilityFromTimeList(currentDate.value, scienceTimes)
          : gran === 'month'
            ? monthAvailabilityFromTimeList(currentDate.value, scienceTimes)
            : yearAvailabilityFromTimeList(currentDate.value, scienceTimes)
      if (onlineCap) {
        map = overlayOnlineTemporalFetchable(
          map,
          currentDate.value,
          gran,
          onlineCap.coverage_start,
          onlineCap.coverage_end,
        )
      }
      return generateTimelineSegments(currentDate.value, gran, map)
    }

    const layer = activeLayer.value
    const catalogId = layer.catalogId
    const isWeatherLayer = catalogId ? workspace.isWeatherEngineLayer(catalogId) : false
    if (!isWeatherLayer) {
      return generateTimelineSegments(currentDate.value, 'static')
    }
    const currentStatus =
      isWeatherLayer && catalogId ? weatherTileManager.getLayerStatus(catalogId) : null

    return buildClockDayTimelineSegments({
      selectedDate: currentDate.value,
      currentHour: currentHour.value,
      coverage: weatherCoverage.value,
      currentStatus,
      isWeatherLayer,
      runReadiness: layer.runReadiness as string | undefined,
    })
  })

  return {
    tileForecastHour,
    selectedCatalogId,
    hasTimelineLayer,
    timelineLayerName,
    timelineAvailabilityLabel,
    timelineObservationLabel,
    activeLayerGranularity,
    isLayerLocked,
    timelineSegments,
    refreshImportedRasterEffectiveTimes,
  }
}
