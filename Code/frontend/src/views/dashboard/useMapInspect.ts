/**
 * useMapInspect — 地图点查、热点选择与 overlay 点值提取。
 *
 * 从 DashboardView.vue 提取：selectedMapPoint / selectedHotspot / visibleHotspots /
 * overlayPointValues / selectedOverlayTimeSeries / resolveWeatherInspectCatalogId /
 * requestPointWeather / handleMapPointSelect / clearMapPointInspect /
 * handleHotspotSelect / handleHotspotSelectFromPanel / handleVisibleHotspotsChange /
 * handleOverlayTimeUpdate / fetchOverlayPointValues / fetchSelectedOverlaySeries /
 * pointHourRefetchTimer watcher / activeLayer catalogId watcher。
 */
import { ref, watch, type ComputedRef, type Ref } from 'vue'
import { useLayerWorkspace, useWorkflowRun } from '../../stores/layers/selectors'
import type { useLogStore } from '../../stores/log'
import type { useUiStore } from '../../stores/ui'
import type { LayerHotspot } from '../../stores/layers/types'
import type { OverlayTimeState } from '../../components/map/overlay-image-module'
import { getOverlayValue, type OverlayPointValue } from '../../services/runtime-api'
import type MapCanvas from '../../components/MapCanvas.vue'

interface SelectedLayerLike {
  instanceId?: string
  catalogId?: string
  visible?: boolean
  name?: string
  importedRasterOverlayLayerId?: string
}

export function useMapInspect(
  logStore: ReturnType<typeof useLogStore>,
  uiStore: ReturnType<typeof useUiStore>,
  selectedLayerDisplay: Ref<SelectedLayerLike | null | undefined>,
  tileForecastHour: ComputedRef<number>,
  mapCanvasRef: Ref<InstanceType<typeof MapCanvas> | null>,
  overlayTimeStates: Ref<OverlayTimeState[]>,
  activeLayer: ComputedRef<{ catalogId?: string }>,
) {
  const workspace = useLayerWorkspace()
  const workflowRun = useWorkflowRun()
  const selectedMapPoint = ref<{ lng: number; lat: number } | null>(null)
  const selectedHotspot = ref<LayerHotspot | null>(null)
  const visibleHotspots = ref<LayerHotspot[]>([])
  const overlayPointValues = ref<OverlayPointValue[]>([])
  const selectedOverlayTimeSeries = ref<OverlayPointValue[]>([])
  /** 所有可见 overlay 图层的时序数据：layerId → OverlayPointValue[] */
  const allOverlayTimeSeries = ref<Record<string, OverlayPointValue[]>>({})

  // ── 天气点查 ──────────────────────────────────────────────────────────

  /** 点查优先当前选中天气层；否则取最顶层可见天气层 */
  function resolveWeatherInspectCatalogId(): string | null {
    const selected = selectedLayerDisplay.value
    if (selected && workspace.isWeatherEngineLayer(selected.catalogId!) && selected.visible) {
      return selected.catalogId!
    }
    const topVisible = [...workspace.activeLayers.value]
      .filter((l) => l.visible && workspace.isWeatherEngineLayer(l.catalogId))
      .sort((a, b) => b.order - a.order)[0]
    return topVisible?.catalogId ?? null
  }

  function requestPointWeather(lng: number, lat: number, catalogId: string) {
    void workflowRun.fetchPointWeather(lng, lat, catalogId, {
      forecastHours: tileForecastHour.value + 1,
    })
  }

  function handleMapPointSelect(point: { lng: number; lat: number }) {
    selectedMapPoint.value = point
    logStore.logOperation(
      'map-point-select',
      `查询点 (${point.lng.toFixed(4)}, ${point.lat.toFixed(4)})`,
    )
    const catalogId = resolveWeatherInspectCatalogId()
    if (catalogId) {
      requestPointWeather(point.lng, point.lat, catalogId)
    } else {
      workflowRun.clearPointWeather()
    }
    void fetchOverlayPointValues(point.lng, point.lat)
  }

  function clearMapPointInspect() {
    selectedMapPoint.value = null
    workflowRun.clearPointWeather()
    overlayPointValues.value = []
    selectedOverlayTimeSeries.value = []
    allOverlayTimeSeries.value = {}
    logStore.logOperation('map-point-clear', '清除地图选点')
  }

  // ── 热点选择 ──────────────────────────────────────────────────────────

  function handleHotspotSelect(hotspot: LayerHotspot | null) {
    selectedHotspot.value = hotspot
  }

  function handleHotspotSelectFromPanel(hotspotId: string) {
    const hotspot = visibleHotspots.value.find((h) => h.id === hotspotId) ?? null
    selectedHotspot.value = hotspot
    mapCanvasRef.value?.selectHotspot?.(hotspotId)
  }

  function handleVisibleHotspotsChange(hotspots: LayerHotspot[]) {
    visibleHotspots.value = hotspots
    if (
      selectedHotspot.value &&
      !hotspots.some((hotspot) => hotspot.id === selectedHotspot.value?.id)
    ) {
      selectedHotspot.value = null
    }
  }

  // ── Overlay 点值 ──────────────────────────────────────────────────────

  let overlayPointFetchSeq = 0

  async function fetchOverlayPointValues(lng: number, lat: number) {
    const states = overlayTimeStates.value
    if (states.length === 0) {
      // 回退：overlayTimeStates 为空时，直接查询可见栅格 overlay 图层的当前值。
      // 这解决了工作流刚运行完、overlay 已加载但 time states 尚未 emit 的时序缺口。
      const visibleOverlayIds = workspace.activeLayersDisplay.value
        .filter((l) => l.visible && l.importedRasterOverlayLayerId)
        .map((l) => l.importedRasterOverlayLayerId!)
        .filter((id, idx, arr) => arr.indexOf(id) === idx) // 去重

      if (visibleOverlayIds.length === 0) {
        overlayPointValues.value = []
        selectedOverlayTimeSeries.value = []
        allOverlayTimeSeries.value = {}
        return
      }

      const seq = ++overlayPointFetchSeq
      const fallbackResults = await Promise.allSettled(
        visibleOverlayIds.map((layerId) => getOverlayValue(layerId, lng, lat)),
      )
      if (seq !== overlayPointFetchSeq) return
      overlayPointValues.value = fallbackResults
        .map((r) => (r.status === 'fulfilled' ? r.value : null))
        .filter((v): v is OverlayPointValue => v !== null && v.value !== null)
      // 无 time states 时不查询时序，仅提供当前点值
      selectedOverlayTimeSeries.value = []
      allOverlayTimeSeries.value = {}
      return
    }
    const seq = ++overlayPointFetchSeq
    const currentResults = await Promise.allSettled(
      states.map((s) => getOverlayValue(s.layerId, lng, lat, s.currentTime ?? undefined)),
    )
    if (seq !== overlayPointFetchSeq) return
    overlayPointValues.value = currentResults
      .map((r) => (r.status === 'fulfilled' ? r.value : null))
      .filter((v): v is OverlayPointValue => v !== null)

    // 并行获取所有可见 overlay 图层的时序与选中图层时序。
    // GPCP 等大时序另走按需查询，避免一次点击扇出 24 个 NetCDF 读取而触发 502。
    // 安审 2026-08-21 U-1：seq 必须传入子函数，写回前校验，否则旧点响应
    // 后到会覆盖新点的时序数据（点 A 慢响应覆盖点 B → 图表与选点静默不一致）
    await Promise.all([
      fetchAllOverlaySeries(lng, lat, states, seq),
      fetchSelectedOverlaySeries(lng, lat, seq),
    ])
  }

  /** 获取所有可见 overlay 图层在选点处的完整时序（非仅选中层） */
  async function fetchAllOverlaySeries(
    lng: number,
    lat: number,
    states: OverlayTimeState[],
    seq?: number,
  ) {
    const seriesMap: Record<string, OverlayPointValue[]> = {}
    const tasks = states
      .filter((s) => s.category === 'time-series' && s.timeList.length > 0)
      .map(async (s) => {
        // GPCP 单帧 NetCDF 读取已足够重；点击地图不自动扫完全部采样月。
        // 保留当前值，完整曲线仅对短时序或用户明确选中的图层按需查询。
        const times = s.layerId === 'gpcp-precip-ts' ? [s.currentTime ?? s.timeList[0]!].filter(Boolean) : s.timeList
        const results = await Promise.allSettled(
          times.map((time) => getOverlayValue(s.layerId, lng, lat, time)),
        )
        seriesMap[s.layerId] = results
          .map((r) => (r.status === 'fulfilled' ? r.value : null))
          .filter((v): v is OverlayPointValue => v !== null)
      })
    await Promise.all(tasks)
    if (seq !== undefined && seq !== overlayPointFetchSeq) return
    allOverlayTimeSeries.value = seriesMap
  }

  async function fetchSelectedOverlaySeries(lng: number, lat: number, seq?: number) {
    const selectedActive = workspace.activeLayers.value.find(
      (l) => l.instanceId === selectedLayerDisplay.value?.instanceId,
    )
    const selectedOverlayId =
      selectedActive?.importedRaster?.overlayLayerId ??
      selectedLayerDisplay.value?.importedRasterOverlayLayerId
    let times = selectedActive?.importedRaster?.timeList ?? []
    if (!selectedOverlayId || times.length === 0) {
      const state = overlayTimeStates.value.find(
        (s) => s.layerId === selectedOverlayId && s.category === 'time-series',
      )
      times = state?.timeList ?? []
    }
    if (!selectedOverlayId || times.length === 0) {
      if (seq === undefined || seq === overlayPointFetchSeq) {
        selectedOverlayTimeSeries.value = []
        logStore.logOperation(
          'overlay-series-error',
          `无法加载点时序：当前图层无可用时间块（${selectedLayerDisplay.value?.name ?? '未选择'}）`,
        )
      }
      return
    }
    // 选中 GPCP 时也只先展示当前采样月；完整时序要显式走专用聚合 API，
    // 不能在交互事件里并发打开 24 个 NetCDF 文件。
    const queryTimes =
      selectedOverlayId === 'gpcp-precip-ts'
        ? [overlayTimeStates.value.find((s) => s.layerId === selectedOverlayId)?.currentTime ?? times[0]!]
        : times
    const seriesResults = await Promise.allSettled(
      queryTimes.map((time) => getOverlayValue(selectedOverlayId, lng, lat, time)),
    )
    if (seq !== undefined && seq !== overlayPointFetchSeq) return
    selectedOverlayTimeSeries.value = seriesResults
      .map((r) => (r.status === 'fulfilled' ? r.value : null))
      .filter((v): v is OverlayPointValue => v !== null)
  }

  // ── Overlay 时间状态更新 ──────────────────────────────────────────────

  function handleOverlayTimeUpdate(states: OverlayTimeState[]) {
    overlayTimeStates.value = states
    for (const st of states) {
      if (st.category !== 'time-series' || !st.timeList?.length) continue
      const layer = workspace.activeLayers.value.find(
        (l) => l.importedRaster?.overlayLayerId === st.layerId,
      )
      if (!layer?.importedRaster) continue
      const prev = layer.importedRaster.timeList ?? []
      if (prev.length === st.timeList.length && prev.every((t, i) => t === st.timeList[i])) continue
      layer.importedRaster.timeList = [...st.timeList]
      layer.importedRaster.timeSlices = undefined
      if (!layer.importedRaster.nativeStep) {
        layer.importedRaster.nativeStep = st.timeList.some((t) => /^\d{8}_\d{8}$/.test(t))
          ? '8d'
          : '1d'
      }
    }
  }

  // ── Watchers ──────────────────────────────────────────────────────────

  watch(
    () => selectedLayerDisplay.value?.importedRasterOverlayLayerId,
    (overlayId) => {
      if (!overlayId) return
      // 选中点已存在时，用实际坐标重新获取时序；否则等待用户选点
      if (selectedMapPoint.value) {
        void fetchSelectedOverlaySeries(selectedMapPoint.value.lng, selectedMapPoint.value.lat)
      }
    },
  )

  // 切换为移动/测量等非点选模式时，清除选中点
  watch(
    () => uiStore.interactionMode,
    (mode) => {
      if (mode === 'select') return
      if (selectedMapPoint.value || selectedHotspot.value) {
        clearMapPointInspect()
        selectedHotspot.value = null
      }
    },
  )

  watch(
    () => activeLayer.value.catalogId,
    (catalogId) => {
      if (!catalogId || !workspace.isWeatherEngineLayer(catalogId)) {
        workflowRun.clearPointWeather()
        return
      }
      if (selectedMapPoint.value) {
        requestPointWeather(selectedMapPoint.value.lng, selectedMapPoint.value.lat, catalogId)
      }
    },
  )

  let pointHourRefetchTimer: number | null = null
  watch(tileForecastHour, () => {
    const point = selectedMapPoint.value
    const catalogId = resolveWeatherInspectCatalogId()
    if (!point || !catalogId) return
    if (pointHourRefetchTimer !== null) window.clearTimeout(pointHourRefetchTimer)
    pointHourRefetchTimer = window.setTimeout(() => {
      pointHourRefetchTimer = null
      requestPointWeather(point.lng, point.lat, catalogId)
    }, 180)
  })

  return {
    selectedMapPoint,
    selectedHotspot,
    visibleHotspots,
    overlayPointValues,
    selectedOverlayTimeSeries,
    allOverlayTimeSeries,
    handleMapPointSelect,
    clearMapPointInspect,
    handleHotspotSelect,
    handleHotspotSelectFromPanel,
    handleVisibleHotspotsChange,
    handleOverlayTimeUpdate,
    fetchSelectedOverlaySeries,
    fetchAllOverlaySeries,
  }
}
