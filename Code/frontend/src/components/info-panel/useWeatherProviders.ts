/**
 * 天气数据源（provider）加载与管理。
 *
 * 从 InfoPanel.vue 抽取（原 script 62-208 行）。负责：
 * - 按 catalogId 拉取可用天气 provider 列表（可中止）
 * - 维护当前选中 provider 的可写计算属性（读写 weather-source-prefs store）
 * - 派生 sparse / hint 提示
 * - 组件卸载时中止进行中的请求
 */
import { computed, ref, watch } from 'vue'
import type { ComputedRef } from 'vue'

import type { ActiveLayerDisplay } from '../../stores/layers/types'
import type { WeatherProviderForLayer } from '../../services/runtime-api'
import { getWeatherProvidersForLayer } from '../../services/runtime-api'
import { useLayersStore } from '../../stores/layers'
import { useWeatherSourcePrefsStore } from '../../stores/weather-source-prefs'

export function useWeatherProviders(
  displayLayer: ComputedRef<ActiveLayerDisplay>,
  isRealtimeWeatherLayer: ComputedRef<boolean>,
) {
  const layersStore = useLayersStore()
  const weatherSourcePrefs = useWeatherSourcePrefsStore()

  const weatherProviderOptions = ref<WeatherProviderForLayer[]>([])
  const weatherProvidersLoading = ref(false)
  const weatherProvidersError = ref<string | null>(null)
  let weatherProvidersAbort: AbortController | null = null

  const selectedWeatherProvider = computed({
    get: () => weatherSourcePrefs.getProvider(displayLayer.value.catalogId),
    set: (value: string) => {
      layersStore.applyWeatherProviderPreference(displayLayer.value.catalogId, value || 'auto')
    },
  })

  const selectedWeatherProviderSparse = computed(() => {
    const pref = selectedWeatherProvider.value
    if (!pref || pref === 'auto') return false
    const row = weatherProviderOptions.value.find((p) => p.provider_id === pref)
    return row?.grid_mode === 'sparse' || row?.data_quality === 'sparse'
  })

  const selectedWeatherProviderHint = computed(() => {
    const pref = selectedWeatherProvider.value
    if (!pref || pref === 'auto') return null
    const row = weatherProviderOptions.value.find((p) => p.provider_id === pref)
    if (!row?.hint || row.data_quality === 'observed') return null
    return row.hint
  })

  function weatherProviderOptionLabel(p: WeatherProviderForLayer): string {
    const bits = [p.display_name]
    if (!p.enabled) bits.push('（未启用）')
    if (p.data_quality === 'extrapolated') bits.push(' · 外推')
    else if (p.data_quality === 'sparse' || p.grid_mode === 'sparse') bits.push(' · 稀疏')
    return bits.join('')
  }

  watch(
    () => (isRealtimeWeatherLayer.value ? displayLayer.value.catalogId : null),
    async (catalogId) => {
      if (weatherProvidersAbort) {
        weatherProvidersAbort.abort()
        weatherProvidersAbort = null
      }
      weatherProviderOptions.value = []
      weatherProvidersError.value = null
      if (!catalogId) return
      weatherProvidersLoading.value = true
      const controller = new AbortController()
      weatherProvidersAbort = controller
      try {
        const resp = await getWeatherProvidersForLayer(catalogId, {
          includeDisabled: true,
          signal: controller.signal,
        })
        if (controller.signal.aborted) return
        const providers = resp.providers ?? []
        weatherProviderOptions.value = providers
        // Drop stale pin: disabled / unsupported / unknown provider_id would 503 tiles.
        const pref = weatherSourcePrefs.getProvider(catalogId)
        if (pref && pref !== 'auto') {
          const match = providers.find((p) => p.provider_id === pref)
          if (!match || !match.enabled) {
            layersStore.applyWeatherProviderPreference(catalogId, 'auto')
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return
        weatherProvidersError.value = error instanceof Error ? error.message : '无法加载天气源列表'
      } finally {
        if (!controller.signal.aborted) weatherProvidersLoading.value = false
        if (weatherProvidersAbort === controller) weatherProvidersAbort = null
      }
    },
    { immediate: true },
  )

  function cleanupWeatherProviders() {
    if (weatherProvidersAbort) {
      weatherProvidersAbort.abort()
      weatherProvidersAbort = null
    }
  }

  return {
    weatherProviderOptions,
    weatherProvidersLoading,
    weatherProvidersError,
    selectedWeatherProvider,
    selectedWeatherProviderSparse,
    selectedWeatherProviderHint,
    weatherProviderOptionLabel,
    cleanupWeatherProviders,
  }
}
