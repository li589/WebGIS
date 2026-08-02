import { describe, expect, it } from 'vitest'
import {
  computeVisibleTickIndices,
  formatTimelineDateLabel,
  generateTimelineSegments,
  granularityUnitLabel,
  shiftTimelineDate,
} from './layer-timeline'

describe('layer-timeline (多时间粒度适配)', () => {
  it('formats static layers cleanly', () => {
    const label = formatTimelineDateLabel(new Date(), 'static')
    expect(label).toContain('静态图层')
  })

  it('formats year, month, day, hour granularity correctly', () => {
    const testDate = new Date(2023, 4, 18) // 2023-05-18
    expect(formatTimelineDateLabel(testDate, 'year')).toBe('2023年')
    expect(formatTimelineDateLabel(testDate, 'month')).toBe('2023年05月')
    expect(formatTimelineDateLabel(testDate, 'day')).toBe('2023-05-18')
    expect(formatTimelineDateLabel(testDate, 'hour', 14.5)).toBe('2023-05-18 14:30')
  })

  it('shifts timeline dates appropriately according to granularity', () => {
    const base = new Date(2023, 4, 15) // 2023-05-15
    const nextMonth = shiftTimelineDate(base, 1, 'month')
    expect(nextMonth.getMonth()).toBe(5) // June (0-indexed 5)

    const nextYear = shiftTimelineDate(base, 2, 'year')
    expect(nextYear.getFullYear()).toBe(2025)

    const nextDay = shiftTimelineDate(base, -3, 'day')
    expect(nextDay.getDate()).toBe(12)
  })

  it('generates segments correctly for static, month, and hour', () => {
    const staticSegs = generateTimelineSegments(new Date(), 'static')
    expect(staticSegs).toHaveLength(1)
    expect(staticSegs[0].state).toBe('static')

    const monthSegs = generateTimelineSegments(new Date(), 'month')
    expect(monthSegs).toHaveLength(12)
    // Labels are now bare numbers without unit suffix
    expect(monthSegs[0].label).toBe('1')

    const hourSegs = generateTimelineSegments(new Date(), 'hour', { 5: 'empty' })
    expect(hourSegs).toHaveLength(24)
    expect(hourSegs[5].state).toBe('empty')
    // Hour labels are compact integers
    expect(hourSegs[0].label).toBe('0')
    expect(hourSegs[23].label).toBe('23')
  })

  it('year segments use real year as index', () => {
    const date = new Date(2023, 4, 18)
    const yearSegs = generateTimelineSegments(date, 'year')
    expect(yearSegs).toHaveLength(10)
    expect(yearSegs[0].index).toBe(2018)
    expect(yearSegs[5].index).toBe(2023)
    expect(yearSegs[9].index).toBe(2027)
    expect(yearSegs[5].label).toBe('2023')
  })

  it('generates day segments without unit suffix', () => {
    const date = new Date(2023, 0, 1) // January 2023, 31 days
    const daySegs = generateTimelineSegments(date, 'day')
    expect(daySegs).toHaveLength(31)
    expect(daySegs[0].label).toBe('1')
    expect(daySegs[30].label).toBe('31')
  })

  it('February day segments match month length', () => {
    const date = new Date(2023, 1, 10) // Feb 2023 (non-leap)
    const daySegs = generateTimelineSegments(date, 'day')
    expect(daySegs).toHaveLength(28)
    expect(daySegs[27].index).toBe(28)
  })

  it('returns correct granularity unit labels', () => {
    expect(granularityUnitLabel('hour')).toBe('时')
    expect(granularityUnitLabel('day')).toBe('日')
    expect(granularityUnitLabel('month')).toBe('月')
    expect(granularityUnitLabel('year')).toBe('年')
    expect(granularityUnitLabel('static')).toBe('')
  })

  it('computeVisibleTickIndices includes all when under limit', () => {
    const visible = computeVisibleTickIndices(8, 12)
    expect(visible.size).toBe(8)
  })

  it('computeVisibleTickIndices decimates when dense', () => {
    const visible = computeVisibleTickIndices(31, 10)
    expect(visible.size).toBeLessThanOrEqual(10)
    // First and last always visible
    expect(visible.has(0)).toBe(true)
    expect(visible.has(30)).toBe(true)
  })

  it('computeVisibleTickIndices handles 24 hours with default cap', () => {
    const visible = computeVisibleTickIndices(24, 12)
    expect(visible.size).toBeLessThanOrEqual(12)
    expect(visible.has(0)).toBe(true)
    expect(visible.has(23)).toBe(true)
  })
})
