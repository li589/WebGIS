import { describe, expect, it } from 'vitest'

import {
  buildClockDayTimelineSegments,
  dateHourToTileHour,
  findLatestValidCoverageInstant,
  formatClockHourLabel,
  isDateHourWithinCoverage,
} from './weather-timeline'

describe('weather-timeline (日历日)', () => {
  // 用本地时区构造 times，避免 UTC/本地偏差
  const base = new Date(2026, 6, 21, 0, 0, 0, 0)
  const times = Array.from({ length: 48 }, (_, i) => {
    const d = new Date(base)
    d.setHours(i)
    return d.toISOString()
  })
  const coverage = {
    data_start_iso: times[0],
    data_end_iso: times[47],
    hour_count: 48,
    times,
    max_tile_hour: 47,
  }

  it('刻度标签单行 HH:00', () => {
    expect(formatClockHourLabel(9)).toBe('09:00')
    expect(formatClockHourLabel(23)).toBe('23:00')
  })

  it('覆盖判断考虑日期', () => {
    expect(isDateHourWithinCoverage(coverage, new Date(2026, 6, 21), 12)).toBe(true)
    expect(isDateHourWithinCoverage(coverage, new Date(2026, 6, 25), 12)).toBe(false)
  })

  it('dateHourToTileHour 映射到 times 索引', () => {
    const idx = dateHourToTileHour(coverage, new Date(2026, 6, 21), 5)
    expect(idx).toBe(5)
  })

  it('findLatestValidCoverageInstant：现在在覆盖内则用现在', () => {
    const now = new Date(2026, 6, 21, 10, 30, 0, 0)
    const latest = findLatestValidCoverageInstant(coverage, now)
    expect(latest?.hour).toBe(10)
    expect(latest?.date.getFullYear()).toBe(2026)
    expect(latest?.date.getMonth()).toBe(6)
    expect(latest?.date.getDate()).toBe(21)
  })

  it('findLatestValidCoverageInstant：现在超出覆盖则用末条', () => {
    const now = new Date(2026, 6, 25, 12, 0, 0, 0)
    const latest = findLatestValidCoverageInstant(coverage, now)
    expect(latest?.hour).toBe(23)
    expect(latest?.date.getDate()).toBe(22) // base+47h → 7/22 23:00
  })

  it('色段：有覆盖=ready，加载中=partial', () => {
    const segs = buildClockDayTimelineSegments({
      selectedDate: new Date(2026, 6, 21),
      currentHour: 12,
      coverage,
      currentStatus: {
        cachedInViewport: 1,
        viewportTotal: 4,
        pending: 2,
        errorType: null,
      },
      isWeatherLayer: true,
    })
    expect(segs).toHaveLength(8)
    expect(segs.every((s) => /^\d{2}:\d{2}$/.test(s.label))).toBe(true)
    const noon = segs.find((s) => s.hour === 12)
    expect(noon?.state).toBe('partial')
    const morning = segs.find((s) => s.hour === 3)
    expect(morning?.state).toBe('ready')
  })

  it('着色优先 valid_times：空温时次为 empty', () => {
    const withValid = {
      ...coverage,
      // times 仍含全部索引；valid 仅前 6 小时
      valid_times: times.slice(0, 6),
      valid_hour_count: 6,
      data_end_iso: times[5],
    }
    expect(isDateHourWithinCoverage(withValid, new Date(2026, 6, 21), 3)).toBe(true)
    expect(isDateHourWithinCoverage(withValid, new Date(2026, 6, 21), 12)).toBe(false)
    const segs = buildClockDayTimelineSegments({
      selectedDate: new Date(2026, 6, 21),
      currentHour: 0,
      coverage: withValid,
      currentStatus: null,
      isWeatherLayer: true,
    })
    expect(segs.find((s) => s.hour === 3)?.state).toBe('ready')
    expect(segs.find((s) => s.hour === 12)?.state).toBe('empty')
  })
})
