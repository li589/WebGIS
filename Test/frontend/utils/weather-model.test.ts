import { describe, expect, it } from 'vitest'

import { normalizeWeatherModel, WEATHER_MODEL_BOOTSTRAP } from '@/utils/weather-model'

describe('normalizeWeatherModel', () => {
  it('maps empty / best_match / auto to bootstrap', () => {
    expect(normalizeWeatherModel(null)).toBe(WEATHER_MODEL_BOOTSTRAP)
    expect(normalizeWeatherModel(undefined)).toBe(WEATHER_MODEL_BOOTSTRAP)
    expect(normalizeWeatherModel('')).toBe(WEATHER_MODEL_BOOTSTRAP)
    expect(normalizeWeatherModel('best_match')).toBe(WEATHER_MODEL_BOOTSTRAP)
    expect(normalizeWeatherModel('auto')).toBe(WEATHER_MODEL_BOOTSTRAP)
  })

  it('keeps concrete model ids', () => {
    expect(normalizeWeatherModel(' icon_global ')).toBe('icon_global')
  })
})