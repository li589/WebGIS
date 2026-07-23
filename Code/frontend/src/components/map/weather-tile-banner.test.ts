import { describe, expect, it } from 'vitest'
import { aggregateWeatherTileBanner } from './weather-tile-banner'

describe('aggregateWeatherTileBanner', () => {
  it('does not show global error when a sibling layer still has viewport cache', () => {
    const model = aggregateWeatherTileBanner([
      {
        label: '能见度',
        active: true,
        cachedInViewport: 0,
        missingInViewport: 0,
        pending: 0,
        gapSweepActive: false,
        errorType: 'data-empty',
        errorMessage: '无有效数据',
      },
      {
        label: '温度',
        active: true,
        cachedInViewport: 4,
        missingInViewport: 0,
        pending: 0,
        gapSweepActive: false,
        errorType: null,
        errorMessage: null,
      },
    ])
    expect(model.show).toBe(false)
    expect(model.error).toBeNull()
  })

  it('shows named error only when every visible layer lacks cache', () => {
    const model = aggregateWeatherTileBanner([
      {
        label: '能见度',
        active: true,
        cachedInViewport: 0,
        missingInViewport: 0,
        pending: 0,
        gapSweepActive: false,
        errorType: 'data-empty',
        errorMessage: '无有效数据',
      },
      {
        label: '云量',
        active: true,
        cachedInViewport: 0,
        missingInViewport: 0,
        pending: 0,
        gapSweepActive: false,
        errorType: 'data-empty',
        errorMessage: '无有效数据',
      },
    ])
    expect(model.show).toBe(true)
    expect(model.error).toContain('能见度')
    expect(model.error).toContain('云量')
  })

  it('loading only when all layers empty and some pending', () => {
    const model = aggregateWeatherTileBanner([
      {
        label: '温度',
        active: true,
        cachedInViewport: 0,
        missingInViewport: 4,
        pending: 2,
        gapSweepActive: false,
        errorType: null,
        errorMessage: null,
      },
    ])
    expect(model).toEqual({ show: true, isLoading: true, error: null, partial: null })
  })

  it('partial names layers with holes after pending drained', () => {
    const model = aggregateWeatherTileBanner([
      {
        label: '温度',
        active: true,
        cachedInViewport: 2,
        missingInViewport: 2,
        pending: 0,
        gapSweepActive: true,
        errorType: null,
        errorMessage: null,
      },
    ])
    expect(model.show).toBe(true)
    expect(model.partial).toContain('温度')
    expect(model.partial).toContain('补全')
  })
})
