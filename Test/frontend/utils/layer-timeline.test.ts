import { describe, expect, it } from 'vitest'
import {
  computeVisibleTickIndices,
  formatTimelineDateLabel,
  generateTimelineSegments,
  granularityUnitLabel,
  shiftTimelineDate,
} from '@/utils/layer-timeline'

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
    // 无 availabilityMap → 全 empty（未知 ≠ 就绪）
    expect(monthSegs.every((s) => s.state === 'empty')).toBe(true)

    const hourSegs = generateTimelineSegments(new Date(), 'hour', { 5: 'ready' })
    expect(hourSegs).toHaveLength(24)
    expect(hourSegs[5].state).toBe('ready')
    expect(hourSegs[0].state).toBe('empty')
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
    expect(yearSegs.every((s) => s.state === 'empty')).toBe(true)
  })

  it('generates day segments without unit suffix', () => {
    const date = new Date(2023, 0, 1) // January 2023, 31 days
    const daySegs = generateTimelineSegments(date, 'day')
    expect(daySegs).toHaveLength(31)
    expect(daySegs[0].label).toBe('1')
    expect(daySegs[30].label).toBe('31')
    expect(daySegs.every((s) => s.state === 'empty')).toBe(true)
  })

  it('generateTimelineSegments：显式 map 覆盖格为 ready，其余 empty', () => {
    const monthSegs = generateTimelineSegments(new Date(2023, 4, 1), 'month', {
      0: 'ready',
      4: 'ready',
    })
    expect(monthSegs[0].state).toBe('ready')
    expect(monthSegs[4].state).toBe('ready')
    expect(monthSegs[1].state).toBe('empty')
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

describe('layer-timeline 补测：边界/闰年/月末/抽稀', () => {
  it('formatTimelineDateLabel：hour 粒度分钟四舍五入', () => {
    const d = new Date(2023, 4, 18)
    expect(formatTimelineDateLabel(d, 'hour', 14.25)).toBe('2023-05-18 14:15')
    expect(formatTimelineDateLabel(d, 'hour', 14.8)).toBe('2023-05-18 14:48')
  })

  it('shiftTimelineDate：闰日跨平年钳制到 2/28（非滚动到 3/1）', () => {
    // setDate(0) 钳制：Feb 29 + 1 year → Feb 28（目标年同月最后一天）
    const leap = new Date(2024, 1, 29) // 2024-02-29
    const next = shiftTimelineDate(leap, 1, 'year')
    expect(next.getFullYear()).toBe(2025)
    expect(next.getMonth()).toBe(1) // February
    expect(next.getDate()).toBe(28)
  })

  it('shiftTimelineDate：月末溢出钳制到目标月最后一天（非滚动到次月）', () => {
    // setDate(0) 钳制：Jan 31 + 1 month → Feb 28（非 Mar 3）
    const jan31 = new Date(2023, 0, 31)
    const next = shiftTimelineDate(jan31, 1, 'month')
    expect(next.getMonth()).toBe(1) // February
    expect(next.getDate()).toBe(28)
  })

  it('shiftTimelineDate：月末不溢出时保持原位', () => {
    // Jan 15 + 1 month → Feb 15（正常）
    const jan15 = new Date(2023, 0, 15)
    const next = shiftTimelineDate(jan15, 1, 'month')
    expect(next.getMonth()).toBe(1)
    expect(next.getDate()).toBe(15)
    // Mar 1 backward by 1 month → Feb 1（正常）
    const mar1 = new Date(2023, 2, 1)
    const prev = shiftTimelineDate(mar1, -1, 'month')
    expect(prev.getMonth()).toBe(1)
    expect(prev.getDate()).toBe(1)
  })

  it('shiftTimelineDate：static 粒度不移动', () => {
    const d = new Date(2023, 4, 18)
    const next = shiftTimelineDate(d, 100, 'static')
    expect(next.getTime()).toBe(d.getTime())
  })

  it('generateTimelineSegments：闰年 2 月 29 天', () => {
    const feb2024 = generateTimelineSegments(new Date(2024, 1, 10), 'day')
    expect(feb2024).toHaveLength(29)
    expect(feb2024[28].index).toBe(29)
    // 平年 2 月仍 28 天
    const feb2023 = generateTimelineSegments(new Date(2023, 1, 10), 'day')
    expect(feb2023).toHaveLength(28)
  })

  it('generateTimelineSegments：hour 粒度 partial 标签', () => {
    const segs = generateTimelineSegments(new Date(), 'hour', { 3: 'partial' })
    expect(segs[3].state).toBe('partial')
    expect(segs[3].availabilityLabel).toBe('降采样中/部分补全')
    expect(segs[0].state).toBe('empty')
    expect(segs[0].availabilityLabel).toBe('无数据')
  })

  it('generateTimelineSegments：year 窗口 availabilityMap 按真实年份优先', () => {
    const segs = generateTimelineSegments(new Date(2023, 4, 18), 'year', {
      2019: 'empty',
      2023: 'ready',
      2030: 'partial',
    })
    const seg2019 = segs.find((s) => s.index === 2019)
    expect(seg2019?.state).toBe('empty')
    const seg2023 = segs.find((s) => s.index === 2023)
    expect(seg2023?.state).toBe('ready')
    // 窗口外（2030）的 map 键不参与
    expect(segs.some((s) => s.index === 2030)).toBe(false)
  })

  it('computeVisibleTickIndices：totalTicks<=maxLabels 全部可见', () => {
    expect(computeVisibleTickIndices(0, 12).size).toBe(0)
    expect(computeVisibleTickIndices(1, 12).size).toBe(1)
    expect(computeVisibleTickIndices(1, 12).has(0)).toBe(true)
    expect(computeVisibleTickIndices(5, 12).size).toBe(5)
  })

  it('computeVisibleTickIndices：密集场景索引在界内且首尾保留', () => {
    for (const [ticks, cap] of [
      [24, 8],
      [31, 10],
      [100, 12],
      [13, 12],
    ] as const) {
      const visible = computeVisibleTickIndices(ticks, cap)
      expect(visible.size).toBeLessThanOrEqual(cap)
      expect(visible.has(0)).toBe(true)
      expect(visible.has(ticks - 1)).toBe(true)
      for (const idx of visible) {
        expect(idx).toBeGreaterThanOrEqual(0)
        expect(idx).toBeLessThan(ticks)
      }
    }
  })

  it('generateTimelineSegments：static 单段', () => {
    const segs = generateTimelineSegments(new Date(), 'static')
    expect(segs).toHaveLength(1)
    expect(segs[0].label).toBe('静态')
    expect(segs[0].availabilityLabel).toContain('无时间维度')
  })
})
