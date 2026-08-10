import { describe, expect, it } from 'vitest'
import {
  buildRunTimelineAvailability,
  coerceExpectedTimeRange,
  resolveExpectedNativeStep,
} from '@/utils/run-timeline-availability'

describe('run-timeline-availability', () => {
  it('coerceExpectedTimeRange accepts start_at/end_at and start/end', () => {
    expect(
      coerceExpectedTimeRange({ start_at: '2025-12-01', end_at: '2025-12-31' }),
    ).toEqual({ start_at: '2025-12-01', end_at: '2025-12-31' })
    expect(coerceExpectedTimeRange({ start: '2025-01-01', end: '2025-01-10' })).toEqual({
      start_at: '2025-01-01',
      end_at: '2025-01-10',
    })
    expect(coerceExpectedTimeRange({})).toBeNull()
  })

  it('coerceExpectedTimeRange swaps inverted bounds and rejects garbage', () => {
    expect(
      coerceExpectedTimeRange({ start_at: '2025-12-31', end_at: '2025-12-01' }),
    ).toEqual({ start_at: '2025-12-01', end_at: '2025-12-31' })
    expect(coerceExpectedTimeRange({ start_at: 'not-a-date', end_at: '2025-12-01' })).toBeNull()
  })

  it('resolveExpectedNativeStep prefers params then omega default 8d', () => {
    expect(
      resolveExpectedNativeStep({
        algorithmParams: { native_step: '1d' },
        workflowId: 'omega_sf_fenkuai_smap_single',
      }),
    ).toBe('1d')
    expect(
      resolveExpectedNativeStep({
        workflowId: 'omega_sf_fenkuai_smap_single',
      }),
    ).toBe('8d')
    expect(resolveExpectedNativeStep({})).toBe('1d')
  })

  it('empty ready list → all empty in window', () => {
    const map = buildRunTimelineAvailability({
      windowDate: new Date(2025, 11, 15),
      granularity: 'day',
      expectedTimeRange: { start_at: '2025-12-01', end_at: '2025-12-31' },
      nativeStep: '8d',
      readyTimeList: [],
    })
    expect(Object.values(map).every((s) => s === 'empty')).toBe(true)
  })

  it('ready time_list paints green days', () => {
    const map = buildRunTimelineAvailability({
      windowDate: new Date(2025, 11, 15),
      granularity: 'day',
      expectedTimeRange: { start_at: '2025-12-01', end_at: '2025-12-31' },
      nativeStep: '8d',
      readyTimeList: ['20251203_20251210'],
    })
    expect(map[5]).toBe('ready')
    expect(map[10]).toBe('ready')
    expect(map[20]).toBe('empty')
  })

  it('inFlight paints yellow; ready wins over inFlight', () => {
    const map = buildRunTimelineAvailability({
      windowDate: new Date(2025, 11, 15),
      granularity: 'day',
      expectedTimeRange: { start_at: '2025-12-01', end_at: '2025-12-31' },
      nativeStep: '8d',
      readyTimeList: ['20251203_20251210'],
      inFlightTimeKeys: ['20251211_20251218', '20251203_20251210'],
    })
    expect(map[5]).toBe('ready')
    expect(map[12]).toBe('partial')
  })

  it('failed keys paint red; runFailed marks remaining expected as error', () => {
    const map = buildRunTimelineAvailability({
      windowDate: new Date(2025, 11, 15),
      granularity: 'day',
      expectedTimeRange: { start_at: '2025-12-01', end_at: '2025-12-20' },
      nativeStep: '8d',
      readyTimeList: ['20251203_20251210'],
      failedTimeKeys: ['20251211_20251218'],
      runFailed: true,
    })
    expect(map[5]).toBe('ready')
    expect(map[12]).toBe('error')
    // expected but neither ready nor already error → error when runFailed
    expect(map[19]).toBe('error')
  })
})
