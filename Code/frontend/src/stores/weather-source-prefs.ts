/**
 * Per-layer weather provider preference (auto | provider_id).
 * Persisted in localStorage; default auto keeps registry priority behavior.
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type WeatherProviderPref = 'auto' | string

const STORAGE_KEY = 'qingtian.weather-source-prefs.v1'

/** Legacy open-meteo → open-meteo-online */
const PROVIDER_ALIASES: Record<string, string> = {
  'open-meteo': 'open-meteo-online',
}

function normalizeProviderId(id: string): string {
  const trimmed = id.trim()
  return PROVIDER_ALIASES[trimmed] ?? trimmed
}

function loadPrefs(): Record<string, WeatherProviderPref> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const out: Record<string, WeatherProviderPref> = {}
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === 'string' && v.trim()) out[k] = normalizeProviderId(v.trim())
    }
    return out
  } catch {
    return {}
  }
}

export const useWeatherSourcePrefsStore = defineStore('weatherSourcePrefs', () => {
  const prefs = ref<Record<string, WeatherProviderPref>>(loadPrefs())

  watch(
    prefs,
    (value) => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
      } catch {
        /* ignore quota */
      }
    },
    { deep: true },
  )

  function getProvider(catalogId: string): WeatherProviderPref {
    const pref = prefs.value[catalogId] ?? 'auto'
    if (!pref || pref === 'auto') return 'auto'
    return normalizeProviderId(pref)
  }

  /** Query value for tile/point APIs; undefined when auto. */
  function getProviderQuery(catalogId: string): string | undefined {
    const pref = getProvider(catalogId)
    if (!pref || pref === 'auto') return undefined
    return pref
  }

  function setProvider(catalogId: string, providerId: WeatherProviderPref) {
    const next = { ...prefs.value }
    if (!providerId || providerId === 'auto') {
      delete next[catalogId]
    } else {
      next[catalogId] = normalizeProviderId(providerId)
    }
    prefs.value = next
  }

  return {
    prefs,
    getProvider,
    getProviderQuery,
    setProvider,
  }
})
