/**
 * useWeatherCoverage — 本地 Open-Meteo 覆盖范围探测与标签计算。
 *
 * 从 DashboardView.vue 提取：weatherCoverage ref / refreshWeatherCoverage /
 * onMounted 定时刷新 / watch defaultModel / coverageSourceLabel。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch, type ComputedRef, type Ref } from 'vue'
import { getWeatherCoverage, type WeatherCoverage } from '../../services/runtime-api'
import type { useWeatherEngineStore } from '../../stores/weather-engine'
import type { useWeatherSyncStatusStore } from '../../stores/weather-sync-status'
import { useLayerViewport } from '../../stores/layers/selectors'

interface ActiveLayerLike {
  name?: string
  catalogId?: string
}

export function useWeatherCoverage(
  weatherEngine: ReturnType<typeof useWeatherEngineStore>,
  weatherSyncStatus: ReturnType<typeof useWeatherSyncStatusStore>,
  selectedLayerDisplay: Ref<{ catalogId?: string } | null | undefined>,
  unifiedTimeLock: Ref<boolean>,
  activeLayer: ComputedRef<ActiveLayerLike>,
) {
  const viewport = useLayerViewport()
  const weatherCoverage = ref<WeatherCoverage | null>(null)
  let coverageAbort: AbortController | null = null

  async function refreshWeatherCoverage() {
    if (coverageAbort) coverageAbort.abort()
    const ac = new AbortController()
    coverageAbort = ac
    try {
      const cov = await getWeatherCoverage(weatherEngine.defaultModel, ac.signal)
      if (!ac.signal.aborted) weatherCoverage.value = cov
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        console.warn('[DashboardView] weather coverage probe failed', err)
        if (!ac.signal.aborted) weatherCoverage.value = null
      }
    } finally {
      if (coverageAbort === ac) coverageAbort = null
    }
  }

  onMounted(() => {
    void (async () => {
      await weatherEngine.ensureLoaded()
      await refreshWeatherCoverage()
      await weatherSyncStatus.refreshOverview()
    })()
    const intervalId = window.setInterval(() => {
      void refreshWeatherCoverage()
      void weatherSyncStatus.refreshOverview()
    }, 600_000)
    onBeforeUnmount(() => window.clearInterval(intervalId))
  })

  watch(
    () => weatherEngine.defaultModel,
    () => {
      void refreshWeatherCoverage()
      viewport.flushWeatherTileViewports()
    },
  )

  const coverageSourceLabel = computed(() => {
    const hasRealLayer = Boolean(selectedLayerDisplay.value?.catalogId)
    if (!hasRealLayer) return '未选择图层'
    const mode = unifiedTimeLock.value ? '统一时间' : '分图层'
    const layerName = activeLayer.value?.name
    const base = layerName ? `${mode} · ${layerName}` : mode
    if (weatherSyncStatus.syncInProgress) return `${base} · 同步中`
    if (!weatherCoverage.value && weatherSyncStatus.modelEmpty) return `${base} · 本地无数据`
    return base
  })

  return {
    weatherCoverage,
    coverageSourceLabel,
    refreshWeatherCoverage,
  }
}
