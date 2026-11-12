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
import { safeLog } from '../../stores/log'

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
      let lastError: unknown = null
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const attemptController = new AbortController()
          const onAbort = () => attemptController.abort()
          ac.signal.addEventListener('abort', onAbort, { once: true })
          const timeout = window.setTimeout(() => attemptController.abort(), 8000)
          const cov = await getWeatherCoverage(weatherEngine.defaultModel, attemptController.signal)
          window.clearTimeout(timeout)
          ac.signal.removeEventListener('abort', onAbort)
          if (!ac.signal.aborted) weatherCoverage.value = cov
          return
        } catch (err) {
          lastError = err
          if (ac.signal.aborted || attempt === 1) throw err
          await new Promise((resolve) => window.setTimeout(resolve, 300))
        }
      }
      throw lastError
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        console.warn('[DashboardView] weather coverage probe failed', err)
        safeLog('client-error', '天气覆盖范围探测失败', String(err), 'warn')
        // 保留最近一次成功结果，避免一次网络抖动让时间轴突然失去覆盖范围。
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
    })().catch(() => {})
    const intervalId = window.setInterval(() => {
      void refreshWeatherCoverage().catch(() => {})
      void weatherSyncStatus.refreshOverview().catch(() => {})
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
