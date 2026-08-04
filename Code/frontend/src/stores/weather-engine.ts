/**
 * Weather engine facade: global default_model + sync overview / coverage probes.
 * Phase B - single frontend source for tile-manager and Dashboard timeline.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { getWeatherCoverage, type WeatherCoverage } from '../services/runtime-api'
import { normalizeWeatherModel, WEATHER_MODEL_BOOTSTRAP } from '../utils/weather-model'
import { useSettingsStore } from './settings'
import { useWeatherSyncStatusStore } from './weather-sync-status'

export const useWeatherEngineStore = defineStore('weatherEngine', () => {
  const settings = useSettingsStore()
  const syncStatus = useWeatherSyncStatusStore()

  const loaded = ref(false)
  const loadError = ref<string | null>(null)
  const coverage = ref<WeatherCoverage | null>(null)

  /** Effective global default model (never best_match/auto). */
  const defaultModel = computed(() =>
    normalizeWeatherModel(settings.weatherConfig?.default_model ?? WEATHER_MODEL_BOOTSTRAP),
  )

  const syncDomains = computed(
    () => syncStatus.overview?.domains ?? settings.weatherConfig?.sync_domains ?? ([] as string[]),
  )

  const modelInSyncDomains = computed(() => syncDomains.value.includes(defaultModel.value))

  async function ensureLoaded(): Promise<void> {
    loadError.value = null
    if (!settings.weatherConfig) {
      try {
        await settings.reloadWeatherConfig()
      } catch (err) {
        loadError.value = err instanceof Error ? err.message : String(err)
      }
    }
    loaded.value = true
  }

  async function setDefaultModel(model: string) {
    const normalized = normalizeWeatherModel(model)
    return settings.saveWeatherDefaultModel(normalized)
  }

  async function refreshCoverage(model?: string, signal?: AbortSignal) {
    const resolved = normalizeWeatherModel(model ?? defaultModel.value)
    coverage.value = await getWeatherCoverage(resolved, signal)
    return coverage.value
  }

  return {
    loaded,
    loadError,
    coverage,
    defaultModel,
    syncDomains,
    modelInSyncDomains,
    overview: computed(() => syncStatus.overview),
    syncInProgress: computed(() => syncStatus.syncInProgress),
    modelEmpty: computed(() => syncStatus.modelEmpty),
    ensureLoaded,
    setDefaultModel,
    refreshCoverage,
    refreshOverview: () => syncStatus.refreshOverview(),
  }
})
