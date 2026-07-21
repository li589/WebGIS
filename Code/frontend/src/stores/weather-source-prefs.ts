/**
 * Per-layer weather provider preference (auto | provider_id).
 * Persisted in localStorage; unset layers default to local Open-Meteo.
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type WeatherProviderPref = 'auto' | string

const STORAGE_KEY = 'qingtian.weather-source-prefs.v1'
/** 产品默认气象源：本机 Open-Meteo */
export const DEFAULT_WEATHER_PROVIDER: WeatherProviderPref = 'open-meteo-local'

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
    const pref = prefs.value[catalogId]
    if (!pref) return DEFAULT_WEATHER_PROVIDER
    if (pref === 'auto') return 'auto'
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
      // 显式写入 auto，避免回退到默认 local（用户主动选自动）
      next[catalogId] = 'auto'
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
