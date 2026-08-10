import { describe, expect, it } from 'vitest'

import {
  buildClockDayTimelineSegments,
  combineDateAndHour,
  coverageTimes,
  coverageValidTimes,
  dateHourToTileHour,
  findLatestValidCoverageInstant,
  findNearestForecastHour,
  formatClockHourLabel,
  isDateHourWithinCoverage,
  quantizeClockHour,
  resolveMaxTileHour,
} from '@/utils/weather-timeline'

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

  it('刻度标签单行 HH:MM', () => {
    expect(formatClockHourLabel(9)).toBe('09:00')
    expect(formatClockHourLabel(23)).toBe('23:00')
    expect(formatClockHourLabel(14.5)).toBe('14:30')
    expect(formatClockHourLabel(14.25)).toBe('14:15')
  })

  it('quantizeClockHour 钳制并量化到 0.25', () => {
    expect(quantizeClockHour(14.24)).toBe(14.25)
    expect(quantizeClockHour(-1)).toBe(0)
    expect(quantizeClockHour(99)).toBe(23)
    expect(quantizeClockHour(Number.NaN)).toBe(0)
  })

  it('覆盖判断考虑日期', () => {
    expect(isDateHourWithinCoverage(coverage, new Date(2026, 6, 21), 12)).toBe(true)
    expect(isDateHourWithinCoverage(coverage, new Date(2026, 6, 25), 12)).toBe(false)
    expect(isDateHourWithinCoverage(coverage, new Date(2026, 6, 21), 12.5)).toBe(true)
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

  it('色段：有覆盖=ready，加载中=partial，且带 index=hour', () => {
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
    expect(segs.every((s) => s.index === s.hour)).toBe(true)
    const noon = segs.find((s) => s.hour === 12)
    expect(noon?.state).toBe('partial')
    expect(noon?.index).toBe(12)
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

describe('weather-timeline 补测：回退/边界/空值/无效时次', () => {
  const base = new Date(2026, 6, 21, 0, 0, 0, 0) // 2026-07-21 本地
  const mk = (h: number) => {
    const d = new Date(base)
    d.setHours(h)
    return d.toISOString()
  }
  const hours48 = Array.from({ length: 48 }, (_, i) => mk(i))
  const coverage48 = {
    data_start_iso: hours48[0],
    data_end_iso: hours48[47],
    hour_count: 48,
    times: hours48,
    max_tile_hour: 47,
  }

  it('coverageTimes / coverageValidTimes：空值与 valid_times 回退', () => {
    expect(coverageTimes(null)).toEqual([])
    expect(coverageTimes(undefined)).toEqual([])
    expect(coverageTimes({} as never)).toEqual([])
    expect(coverageTimes({ times: [] } as never)).toEqual([])
    // 无 valid_times → 回退 times
    expect(coverageValidTimes({ times: ['a'] } as never)).toEqual(['a'])
    // valid_times 优先
    expect(
      coverageValidTimes({ times: ['a'], valid_times: ['b'] } as never),
    ).toEqual(['b'])
    expect(coverageValidTimes(null)).toEqual([])
  })

  it('resolveMaxTileHour：钳制与 hour_count 回退', () => {
    expect(resolveMaxTileHour(null)).toBe(47)
    expect(resolveMaxTileHour(undefined)).toBe(47)
    // 无 max_tile_hour → hour_count-1
    expect(resolveMaxTileHour({ hour_count: 5 } as never)).toBe(4)
    expect(resolveMaxTileHour({ hour_count: 0 } as never)).toBe(0)
    // 显式 max_tile_hour 钳制到 [0, 47]
    expect(resolveMaxTileHour({ max_tile_hour: 60 } as never)).toBe(47)
    expect(resolveMaxTileHour({ max_tile_hour: -3 } as never)).toBe(0)
    expect(resolveMaxTileHour({ max_tile_hour: 12 } as never)).toBe(12)
  })

  it('combineDateAndHour：量化并写入时分', () => {
    const d = combineDateAndHour(new Date(2026, 6, 21), 14.5)
    expect(d.getHours()).toBe(14)
    expect(d.getMinutes()).toBe(30)
    // 超界钳制
    const clamped = combineDateAndHour(new Date(2026, 6, 21), 99)
    expect(clamped.getHours()).toBe(23)
    expect(clamped.getMinutes()).toBe(0)
    // 原始 Date 不被修改（复制语义）
    const src = new Date(2026, 6, 21, 8, 0, 0, 0)
    combineDateAndHour(src, 20)
    expect(src.getHours()).toBe(8)
  })

  it('findNearestForecastHour：精确匹配优先', () => {
    const cov = coverage48 as never
    expect(findNearestForecastHour(cov, new Date(2026, 6, 21, 5, 0))).toBe(5)
    expect(findNearestForecastHour(cov, new Date(2026, 6, 21, 23, 0))).toBe(23)
  })

  it('findNearestForecastHour：无精确匹配取最近时次（平局取先者）', () => {
    // 仅偶数小时：0,2,4,...,22（12 条）
    const evenTimes = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22].map(mk)
    const cov = {
      times: evenTimes,
      hour_count: 12,
      max_tile_hour: 11,
    } as never
    // 05:00 → 04:00(idx2) 与 06:00(idx3) 距离相等，平局取先者 idx2
    expect(findNearestForecastHour(cov, new Date(2026, 6, 21, 5, 0))).toBe(2)
    // 13:00 → 12:00(idx6) 与 14:00(idx7) 距离相等，平局取先者 idx6
    expect(findNearestForecastHour(cov, new Date(2026, 6, 21, 13, 0))).toBe(6)
    // 23:00 → 最近 22:00(idx11)
    expect(findNearestForecastHour(cov, new Date(2026, 6, 21, 23, 0))).toBe(11)
    // 00:00 → 精确 idx0
    expect(findNearestForecastHour(cov, new Date(2026, 6, 21, 0, 0))).toBe(0)
  })

  it('findNearestForecastHour：空 times 回退到目标钟点', () => {
    expect(findNearestForecastHour(null, new Date(2026, 6, 21, 5, 0))).toBe(5)
    // JS Date 归一化：hour=30 的 Date 实际为次日 06:00 → 返回 6（钳制分支为防御性代码）
    expect(findNearestForecastHour(null, new Date(2026, 6, 21, 30, 0))).toBe(6)
  })

  it('findNearestForecastHour：跳过无效时次', () => {
    const cov = {
      times: ['not-a-date', mk(10), mk(12)],
      hour_count: 3,
      max_tile_hour: 2,
    } as never
    // 目标 11:00 → 无效条跳过，最近 10:00(idx1)
    expect(findNearestForecastHour(cov, new Date(2026, 6, 21, 11, 0))).toBe(1)
  })

  it('isDateHourWithinCoverage：空 coverage / 无效日期 → false', () => {
    expect(isDateHourWithinCoverage(null, new Date(2026, 6, 21), 12)).toBe(false)
    expect(
      isDateHourWithinCoverage(
        { data_start_iso: 'bad', data_end_iso: 'worse' } as never,
        new Date(2026, 6, 21),
        12,
      ),
    ).toBe(false)
    // times 含无效条目被跳过
    const cov = { times: ['bad', mk(6)] } as never
    expect(isDateHourWithinCoverage(cov, new Date(2026, 6, 21), 6)).toBe(true)
    expect(isDateHourWithinCoverage(cov, new Date(2026, 6, 21), 12)).toBe(false)
  })

  it('isDateHourWithinCoverage：valid_times 优先于 times（不在 valid 即 false）', () => {
    const cov = {
      times: [0, 3, 6, 9, 12].map(mk),
      valid_times: [mk(3), mk(9)],
      data_start_iso: mk(0),
      data_end_iso: mk(12),
    } as never
    expect(isDateHourWithinCoverage(cov, new Date(2026, 6, 21), 3)).toBe(true)
    expect(isDateHourWithinCoverage(cov, new Date(2026, 6, 21), 6)).toBe(false)
  })

  it('findLatestValidCoverageInstant：空覆盖 → 返回现在', () => {
    const now = new Date(2026, 6, 21, 10, 0, 0, 0)
    const r = findLatestValidCoverageInstant(null, now)
    expect(r?.hour).toBe(10)
    expect(r?.date.getDate()).toBe(21)
  })

  it('findLatestValidCoverageInstant：末条无效 → null', () => {
    const cov = { valid_times: [mk(0), 'not-a-date'] } as never
    const r = findLatestValidCoverageInstant(cov, new Date(2026, 7, 1, 12, 0))
    expect(r).toBeNull()
  })

  it('buildClockDayTimelineSegments：runReadiness=blocked 全部 empty 且标注数据未就绪', () => {
    const segs = buildClockDayTimelineSegments({
      selectedDate: new Date(2026, 6, 21),
      currentHour: 12,
      coverage: coverage48,
      currentStatus: null,
      isWeatherLayer: true,
      runReadiness: 'blocked',
    })
    expect(segs).toHaveLength(8)
    expect(segs.every((s) => s.state === 'empty')).toBe(true)
    expect(segs[0].availabilityLabel).toBe('数据未就绪')
  })

  it('buildClockDayTimelineSegments：非天气层按 coverage 着色', () => {
    const segs = buildClockDayTimelineSegments({
      selectedDate: new Date(2026, 6, 21),
      currentHour: 0,
      coverage: coverage48,
      currentStatus: null,
      isWeatherLayer: false,
    })
    expect(segs.find((s) => s.hour === 0)?.state).toBe('ready')
    expect(segs.find((s) => s.hour === 12)?.state).toBe('ready')
  })

  it('buildClockDayTimelineSegments：currentBucket 按 3 对齐，已加载态', () => {
    const segs = buildClockDayTimelineSegments({
      selectedDate: new Date(2026, 6, 21),
      currentHour: 14, // round(14/3)*3 = 15
      coverage: coverage48,
      currentStatus: {
        cachedInViewport: 4,
        viewportTotal: 4,
        pending: 0,
        errorType: null,
      },
      isWeatherLayer: true,
    })
    const bucket = segs.find((s) => s.hour === 15)
    expect(bucket?.state).toBe('ready')
    expect(bucket?.availabilityLabel).toBe('已加载')
    // 非当前桶的 ready 显示"有数据"
    expect(segs.find((s) => s.hour === 3)?.availabilityLabel).toBe('有数据')
  })

  it('buildClockDayTimelineSegments：pending>0 且同桶 → partial 加载中', () => {
    const segs = buildClockDayTimelineSegments({
      selectedDate: new Date(2026, 6, 21),
      currentHour: 6,
      coverage: coverage48,
      currentStatus: {
        cachedInViewport: 1,
        viewportTotal: 4,
        pending: 3,
        errorType: null,
      },
      isWeatherLayer: true,
    })
    expect(segs.find((s) => s.hour === 6)?.state).toBe('partial')
    expect(segs.find((s) => s.hour === 6)?.availabilityLabel).toBe('加载中')
  })
})
