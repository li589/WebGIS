import { describe, expect, it } from 'vitest'
import {
  dayAvailabilityFromTimeList,
  defaultFollowPolicy,
  formatTimeStep,
  latestSlice,
  parseTimeStep,
  resolveSliceForInstant,
  sliceStartAsDateHour,
  timeListToSlices,
} from '@/utils/temporal-interval'

describe('temporal-interval', () => {
  it('parses step strings', () => {
    expect(parseTimeStep('8d')).toEqual({ value: 8, unit: 'day' })
    expect(parseTimeStep('0.5h')).toEqual({ value: 0.5, unit: 'hour' })
    expect(parseTimeStep('6h')).toEqual({ value: 6, unit: 'hour' })
    expect(parseTimeStep('1yr')).toEqual({ value: 1, unit: 'year' })
    expect(formatTimeStep({ value: 8, unit: 'day' })).toBe('8d')
  })

  it('resolves containing for 8d blocks', () => {
    const slices = timeListToSlices(['20251203_20251210', '20251211_20251218'])
    const spec = {
      nativeStep: { value: 8, unit: 'day' as const },
      slices,
      followPolicy: 'containing' as const,
    }
    const t = new Date(Date.UTC(2025, 11, 5))
    const r = resolveSliceForInstant(spec, t)
    expect(r.nativeMatch).toBe(true)
    expect(r.slice?.label).toBe('20251203_20251210')
  })

  it('marks nearest-block when outside', () => {
    const slices = timeListToSlices(['20251203_20251210'])
    const spec = {
      nativeStep: { value: 8, unit: 'day' as const },
      slices,
    }
    expect(defaultFollowPolicy(spec.nativeStep)).toBe('containing')
    const t = new Date(Date.UTC(2025, 11, 20))
    const r = resolveSliceForInstant(spec, t, 'nearest-block')
    expect(r.nativeMatch).toBe(false)
    expect(r.effectiveLabel).toContain('非本时刻原生')
  })

  it('picks latest slice', () => {
    const slices = timeListToSlices(['20251203_20251210', '20251227_20251231'])
    const latest = latestSlice({ nativeStep: { value: 8, unit: 'day' }, slices })
    expect(latest?.label).toBe('20251227_20251231')
  })

  it('marks calendar days covered by block time_list as ready', () => {
    const map = dayAvailabilityFromTimeList(new Date(2025, 11, 15), [
      '20251203_20251210',
      '20251227_20251231',
    ])
    expect(map[5]).toBe('ready')
    expect(map[10]).toBe('ready')
    expect(map[11]).toBe('empty')
    expect(map[27]).toBe('ready')
    expect(map[31]).toBe('ready')
    expect(map[20]).toBe('empty')
  })

  it('sliceStartAsDateHour keeps local calendar day (no UTC backshift)', () => {
    const slices = timeListToSlices(['20251227_20251231'])
    const dh = sliceStartAsDateHour(slices[0]!)
    expect(dh).not.toBeNull()
    expect(dh!.date.getFullYear()).toBe(2025)
    expect(dh!.date.getMonth()).toBe(11)
    expect(dh!.date.getDate()).toBe(27)
    expect(dh!.hour).toBe(0)
  })
})
