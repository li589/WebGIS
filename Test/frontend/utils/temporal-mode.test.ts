import { describe, expect, it } from 'vitest'
import {
  alignDateToTemporalRange,
  resolveLayerTemporalMode,
} from '../../../Code/frontend/src/utils/temporal-mode'

describe('temporal-mode', () => {
  describe('resolveLayerTemporalMode', () => {
    it('recognizes explicit tags', () => {
      expect(resolveLayerTemporalMode({ tags: ['sample', 'temporal:monthly'] })).toEqual({
        mode: 'range',
        subtype: 'monthly',
        stepDays: 30,
        label: '整月时段',
      })

      expect(resolveLayerTemporalMode({ tags: ['temporal:8d-block'] })).toEqual({
        mode: 'range',
        subtype: 'multi-day-block',
        stepDays: 8,
        label: '8天块时段',
      })

      expect(resolveLayerTemporalMode({ tags: ['temporal:16d-block'] })).toEqual({
        mode: 'range',
        subtype: 'multi-day-block',
        stepDays: 16,
        label: '16天块时段',
      })

      expect(resolveLayerTemporalMode({ tags: ['temporal:instant'] })).toEqual({
        mode: 'instant',
        label: '时间点',
      })
    })

    it('infers from native_step and granularity without explicit tags', () => {
      // SMAP/FY 8d
      expect(resolveLayerTemporalMode({ native_step: '8d' })).toEqual({
        mode: 'range',
        subtype: 'multi-day-block',
        stepDays: 8,
        label: '8天块时段',
      })

      // Online temporal 8d
      expect(
        resolveLayerTemporalMode({ online_temporal: { native_step: '8d' } }),
      ).toEqual({
        mode: 'range',
        subtype: 'multi-day-block',
        stepDays: 8,
        label: '8天块时段',
      })

      // Monthly
      expect(resolveLayerTemporalMode({ time_granularity: 'month' })).toEqual({
        mode: 'range',
        subtype: 'monthly',
        stepDays: 30,
        label: '整月时段',
      })

      // Default instant (e.g. 1h or day)
      expect(resolveLayerTemporalMode({ native_step: '1h' })).toEqual({
        mode: 'instant',
        label: '时间点',
      })
      expect(resolveLayerTemporalMode(null)).toEqual({
        mode: 'instant',
        label: '时间点',
      })
    })
  })

  describe('alignDateToTemporalRange', () => {
    it('aligns monthly to full month window', () => {
      const d = new Date('2026-07-15T10:00:00Z')
      const aligned = alignDateToTemporalRange(d, {
        mode: 'range',
        subtype: 'monthly',
        label: '整月时段',
      })
      expect(aligned.granularity).toBe('month')
      expect(aligned.timeKey).toBe('2026-07')
      expect(aligned.displayLabel).toBe('2026-07（整月）')
      expect(aligned.start_at.startsWith('2026-07-01')).toBe(true)
      expect(aligned.end_at.startsWith('2026-08-01')).toBe(true)
    })

    it('aligns 8-day block starting from 1st of month', () => {
      // Day 5 falls into Day 1~8 block
      const d1 = new Date('2026-07-05T00:00:00Z')
      const aligned1 = alignDateToTemporalRange(d1, {
        mode: 'range',
        subtype: 'multi-day-block',
        stepDays: 8,
        label: '8天块时段',
      })
      expect(aligned1.granularity).toBe('day')
      expect(aligned1.timeKey).toBe('20260701_20260708')
      expect(aligned1.displayLabel).toBe('2026-07-01 ~ 2026-07-08（8天块）')

      // Day 10 falls into Day 9~16 block
      const d2 = new Date('2026-07-10T00:00:00Z')
      const aligned2 = alignDateToTemporalRange(d2, {
        mode: 'range',
        subtype: 'multi-day-block',
        stepDays: 8,
        label: '8天块时段',
      })
      expect(aligned2.timeKey).toBe('20260709_20260716')
    })
  })
})
