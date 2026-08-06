import { describe, expect, it } from 'vitest'

import {
  resolveWeatherTileReadyKind,
  resolveWeatherWorkflowStage,
} from '@/utils/weather-tile-readiness'

describe('weather-tile-readiness', () => {
  it('maps full viewport cache with no pending to ready/succeeded', () => {
    const stats = { pending: 0, cached: 12, visible: 12 }
    expect(resolveWeatherTileReadyKind(stats)).toBe('ready')
    expect(resolveWeatherWorkflowStage(stats)).toBe('succeeded')
  })

  it('maps pending or incomplete cache to partial/running', () => {
    expect(resolveWeatherTileReadyKind({ pending: 2, cached: 12, visible: 12 })).toBe('partial')
    expect(resolveWeatherWorkflowStage({ pending: 2, cached: 12, visible: 12 })).toBe('running')
    expect(resolveWeatherTileReadyKind({ pending: 0, cached: 6, visible: 12 })).toBe('partial')
    expect(resolveWeatherWorkflowStage({ pending: 0, cached: 6, visible: 12 })).toBe('running')
  })

  it('maps empty stats to idle', () => {
    expect(resolveWeatherTileReadyKind(null)).toBe('idle')
    expect(resolveWeatherTileReadyKind({ pending: 0, cached: 0, visible: 12 })).toBe('idle')
    expect(resolveWeatherWorkflowStage({ pending: 0, cached: 0, visible: 0 })).toBe('idle')
  })
})
