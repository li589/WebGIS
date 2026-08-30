/**
 * layer-coverage-api — dual channel date check
 */
import { describe, expect, it } from 'vitest'

import {
  isDateCoveredByAnyChannel,
  type LayerDataCoverageResponse,
} from '../../../Code/frontend/src/services/layer-coverage-api'

function cover(partial: Partial<LayerDataCoverageResponse['channels']>): LayerDataCoverageResponse {
  return {
    layer_id: 'x',
    channels: {
      online: {
        available: false,
        coverage_start: null,
        coverage_end: null,
        native_step: '1d',
        ...partial.online,
      },
      local: {
        available: false,
        dates: [],
        ...partial.local,
      },
    },
  }
}

describe('isDateCoveredByAnyChannel', () => {
  it('matches local dates', () => {
    const c = cover({ local: { available: true, dates: ['2025-12-03', '2025-12-04'] } })
    expect(isDateCoveredByAnyChannel('2025-12-03', c)).toBe(true)
    expect(isDateCoveredByAnyChannel('2025-12-01', c)).toBe(false)
  })

  it('matches online range', () => {
    const c = cover({
      online: {
        available: true,
        coverage_start: '2020-01-01',
        coverage_end: '2026-01-01',
        native_step: '1d',
      },
    })
    expect(isDateCoveredByAnyChannel('2025-12-03', c)).toBe(true)
    expect(isDateCoveredByAnyChannel('2019-01-01', c)).toBe(false)
  })

  it('allowOnlinePrefetchOnly when online available without bounds', () => {
    const c = cover({ online: { available: true } })
    expect(isDateCoveredByAnyChannel('2025-01-01', c)).toBe(false)
    expect(
      isDateCoveredByAnyChannel('2025-01-01', c, { allowOnlinePrefetchOnly: true }),
    ).toBe(true)
  })
})
