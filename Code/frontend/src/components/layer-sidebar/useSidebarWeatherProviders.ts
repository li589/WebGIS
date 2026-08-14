import { ref } from 'vue'
import { useLayerViewport } from '../../stores/layers/selectors'
import { useLogStore } from '../../stores/log'
import { useWeatherSourcePrefsStore } from '../../stores/weather-source-prefs'
import {
  getWeatherProvidersForLayer,
  type WeatherProviderForLayer,
} from '../../services/runtime-api'

/**
 * Extracts weather provider management logic from LayerSidebar.vue.
 *
 * Manages the cache/loading state of weather providers per catalog layer,
 * handles provider preference changes, and exposes quality/sparse hints
 * for the UI to display alongside provider selectors.
 */
export function useSidebarWeatherProviders() {
  const viewport = useLayerViewport()
  const logStore = useLogStore()
  const weatherSourcePrefs = useWeatherSourcePrefsStore()

  const weatherProvidersCache = ref<Record<string, WeatherProviderForLayer[]>>({})
  const weatherProvidersLoading = ref<Record<string, boolean>>({})

  async function ensureWeatherProviders(catalogId: string) {
    if (weatherProvidersCache.value[catalogId] || weatherProvidersLoading.value[catalogId]) return
    weatherProvidersLoading.value = { ...weatherProvidersLoading.value, [catalogId]: true }
    try {
      const res = await getWeatherProvidersForLayer(catalogId, { includeDisabled: true })
      const providers = res.providers ?? []
      weatherProvidersCache.value = {
        ...weatherProvidersCache.value,
        [catalogId]: providers,
      }
      // 与 InfoPanel 一致：禁用/未知钉源回退 auto，避免瓦片 503
      const pref = weatherSourcePrefs.getProvider(catalogId)
      if (pref && pref !== 'auto') {
        const match = providers.find((p) => p.provider_id === pref)
        if (!match || !match.enabled) {
          viewport.applyWeatherProviderPreference(catalogId, 'auto')
        }
      }
    } catch (error) {
      logStore.logOperation(
        'warn',
        `天气源列表加载失败 (${catalogId}): ${error instanceof Error ? error.message : String(error)}`,
      )
      weatherProvidersCache.value = { ...weatherProvidersCache.value, [catalogId]: [] }
    } finally {
      weatherProvidersLoading.value = { ...weatherProvidersLoading.value, [catalogId]: false }
    }
  }

  function weatherProvidersFor(catalogId: string): WeatherProviderForLayer[] {
    return weatherProvidersCache.value[catalogId] ?? []
  }

  function onWeatherSourceChange(catalogId: string, value: string) {
    viewport.applyWeatherProviderPreference(catalogId, value || 'auto')
  }

  function weatherSourceSparseHint(catalogId: string): boolean {
    const pref = weatherSourcePrefs.getProvider(catalogId)
    if (!pref || pref === 'auto') return false
    const row = weatherProvidersFor(catalogId).find((p) => p.provider_id === pref)
    return row?.grid_mode === 'sparse' || row?.data_quality === 'sparse'
  }

  function weatherSourceQualityHint(catalogId: string): string | null {
    const pref = weatherSourcePrefs.getProvider(catalogId)
    if (!pref || pref === 'auto') return null
    const row = weatherProvidersFor(catalogId).find((p) => p.provider_id === pref)
    if (!row?.hint) return null
    if (row.data_quality === 'observed') return null
    return row.hint
  }

  function weatherProviderOptionLabel(p: WeatherProviderForLayer): string {
    const bits = [p.display_name]
    if (!p.enabled) bits.push('（未启用）')
    if (p.data_quality === 'extrapolated') bits.push(' · 外推')
    else if (p.data_quality === 'sparse' || p.grid_mode === 'sparse') bits.push(' · 稀疏')
    return bits.join('')
  }

  return {
    weatherProvidersCache,
    weatherProvidersLoading,
    ensureWeatherProviders,
    weatherProvidersFor,
    onWeatherSourceChange,
    weatherSourceSparseHint,
    weatherSourceQualityHint,
    weatherProviderOptionLabel,
  }
}
