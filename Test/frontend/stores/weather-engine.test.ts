import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useSettingsStore } from '@/stores/settings'
import { useWeatherEngineStore } from '@/stores/weather-engine'
import { normalizeWeatherModel, WEATHER_MODEL_BOOTSTRAP } from '@/utils/weather-model'

describe('normalizeWeatherModel', () => {
  it('maps empty / best_match / auto to bootstrap', () => {
    expect(normalizeWeatherModel('')).toBe(WEATHER_MODEL_BOOTSTRAP)
    expect(normalizeWeatherModel('best_match')).toBe(WEATHER_MODEL_BOOTSTRAP)
    expect(normalizeWeatherModel('auto')).toBe(WEATHER_MODEL_BOOTSTRAP)
  })

  it('keeps concrete model ids', () => {
    expect(normalizeWeatherModel('gfs_global')).toBe('gfs_global')
  })
})

describe('useWeatherEngineStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('exposes defaultModel from settings weatherConfig', () => {
    const settings = useSettingsStore()
    settings.weatherConfig = {
      default_model: 'gfs_global',
      sync_domains: ['gfs_global'],
      cache_ttl_seconds: 60,
      refresh_forecast_hours: 1,
      schedule_enabled: false,
      default_latitude: 0,
      default_longitude: 0,
      max_active_weather_tile_runs: 4,
      supported_models: [],
    } as never
    const engine = useWeatherEngineStore()
    expect(engine.defaultModel).toBe('gfs_global')
  })

  it('falls back to bootstrap when config missing', () => {
    const engine = useWeatherEngineStore()
    expect(engine.defaultModel).toBe(WEATHER_MODEL_BOOTSTRAP)
  })
})