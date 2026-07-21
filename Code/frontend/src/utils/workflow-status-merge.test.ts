import { describe, expect, it } from 'vitest'

import { mergeWorkflowSummaryWithWeather } from './workflow-status-merge'
import type { WorkflowSummary } from '../stores/layers/types'
import type { WeatherWorkflowContribution } from '../stores/weather-tile-manager'

const idleBase: WorkflowSummary = {
  total: 0,
  running: 0,
  queued: 0,
  succeeded: 0,
  failed: 0,
  cancelled: 0,
  retryPending: 0,
  overall: 'idle',
  tone: 'idle',
  hasError: false,
}

describe('mergeWorkflowSummaryWithWeather', () => {
  it('counts weather viewport-complete layers as succeeded', () => {
    const contribution: WeatherWorkflowContribution = {
      running: 0,
      queued: 0,
      retryPending: 0,
      failed: 0,
      cancelled: 0,
      succeeded: 2,
      items: [
        {
          catalogId: 'temperature',
          status: 'succeeded',
          message: '已完成瓦片 4/4',
          pending: 0,
          missingInViewport: 0,
          errorType: null,
        },
        {
          catalogId: 'wind-field',
          status: 'succeeded',
          message: '已完成瓦片 6/6',
          pending: 0,
          missingInViewport: 0,
          errorType: null,
        },
      ],
    }

    const merged = mergeWorkflowSummaryWithWeather(idleBase, contribution)
    expect(merged.succeeded).toBe(2)
    expect(merged.total).toBe(2)
    expect(merged.overall).toBe('succeeded')
    expect(merged.tone).toBe('success')
  })

  it('keeps succeeded visible alongside running weather loads', () => {
    const contribution: WeatherWorkflowContribution = {
      running: 1,
      queued: 0,
      retryPending: 0,
      failed: 0,
      cancelled: 0,
      succeeded: 1,
      items: [],
    }
    const merged = mergeWorkflowSummaryWithWeather(
      { ...idleBase, total: 1, succeeded: 1, overall: 'succeeded', tone: 'success' },
      contribution,
    )
    expect(merged.running).toBe(1)
    expect(merged.succeeded).toBe(2)
    expect(merged.overall).toBe('active')
  })
})
