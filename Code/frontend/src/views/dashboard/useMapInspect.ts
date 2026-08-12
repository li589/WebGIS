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
import type { useLayersStore } from '../../stores/layers'
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
  layersStore: ReturnType<typeof useLayersStore>,
  logStore: ReturnType<typeof useLogStore>,
  uiStore: ReturnType<typeof useUiStore>,
  selectedLayerDisplay: Ref<SelectedLayerLike | null | undefined>,
  tileForecastHour: ComputedRef<number>,
  mapCanvasRef: Ref<InstanceType<typeof MapCanvas> | null>,
  overlayTimeStates: Ref<OverlayTimeState[]>,
  activeLayer: ComputedRef<{ catalogId?: string }>,
) {
  const selectedMapPoint = ref<{ lng: number; lat: number } | null>(null)
  const selectedHotspot = ref<LayerHotspot | null>(null)
  const visibleHotspots = ref<LayerHotspot[]>([])
  const overlayPointValues = ref<OverlayPointValue[]>([])
  const selectedOverlayTimeSeries = ref<OverlayPointValue[]>([])

  // ── 天气点查 ──────────────────────────────────────────────────────────

  /** 点查优先当前选中天气层；否则取最顶层可见天气层 */
  function resolveWeatherInspectCatalogId(): string | null {
    const selected = selectedLayerDisplay.value
    if (selected && layersStore.isWeatherEngineLayer(selected.catalogId!) && selected.visible) {
      return selected.catalogId!
    }
    const topVisible = [...layersStore.activeLayers]
      .filter((l) => l.visible && layersStore.isWeatherEngineLayer(l.catalogId))
      .sort((a, b) => b.order - a.order)[0]
    return topVisible?.catalogId ?? null
  }

  function requestPointWeather(lng: number, lat: number, catalogId: string) {
    void layersStore.fetchPointWeather(lng, lat, catalogId, {
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
      layersStore.clearPointWeather()
    }
    void fetchOverlayPointValues(point.lng, point.lat)
  }

  function clearMapPointInspect() {
    selectedMapPoint.value = null
    layersStore.clearPointWeather()
    overlayPointValues.value = []
    selectedOverlayTimeSeries.value = []
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
      overlayPointValues.value = []
      selectedOverlayTimeSeries.value = []
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

    await fetchSelectedOverlaySeries(lng, lat)
  }

  async function fetchSelectedOverlaySeries(lng: number, lat: number) {
    const selectedActive = layersStore.activeLayers.find(
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
      selectedOverlayTimeSeries.value = []
      logStore.logOperation(
        'overlay-series-error',
        `无法加载点时序：当前图层无可用时间块（${selectedLayerDisplay.value?.name ?? '未选择'}）`,
      )
      return
    }
    const seriesResults = await Promise.allSettled(
      times.map((time) => getOverlayValue(selectedOverlayId, lng, lat, time)),
    )
    selectedOverlayTimeSeries.value = seriesResults
      .map((r) => (r.status === 'fulfilled' ? r.value : null))
      .filter((v): v is OverlayPointValue => v !== null)
  }

  // ── Overlay 时间状态更新 ──────────────────────────────────────────────

  function handleOverlayTimeUpdate(states: OverlayTimeState[]) {
    overlayTimeStates.value = states
    for (const st of states) {
      if (st.category !== 'time-series' || !st.timeList?.length) continue
      const layer = layersStore.activeLayers.find(
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
      if (!overlayId || selectedMapPoint.value) return
      void fetchSelectedOverlaySeries(11.25, 19.7623)
    },
    { immediate: true },
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
      if (!catalogId || !layersStore.isWeatherEngineLayer(catalogId)) {
        layersStore.clearPointWeather()
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
    handleMapPointSelect,
    clearMapPointInspect,
    handleHotspotSelect,
    handleHotspotSelectFromPanel,
    handleVisibleHotspotsChange,
    handleOverlayTimeUpdate,
    fetchSelectedOverlaySeries,
  }
}
