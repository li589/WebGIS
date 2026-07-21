/**
 * 天气时间轴工具：
 * - UI：日历日期 + 当日钟点 0–23（自由拖动，不限范围）
 * - 瓦片 API：将「日期+钟点」映射为 coverage.times 预报偏移索引
 */

export const TILE_MAX_HOUR = 47
export const CLOCK_DAY_MAX_HOUR = 23

export type TimelineAvailabilityState = 'empty' | 'partial' | 'ready'

export type TimelineAvailabilitySegment = {
  hour: number
  label: string
  state: TimelineAvailabilityState
  availabilityLabel: string
}

export type WeatherCoverageLike = {
  data_start_iso: string
  data_end_iso: string
  hour_count: number
  /** 与瓦片 hour 索引对齐的完整时次（可含空值时次） */
  times?: string[]
  /** temperature 非空的时次；时间轴绿/紫着色优先用此字段 */
  valid_times?: string[]
  valid_hour_count?: number
  max_tile_hour?: number
}

/** 钟点标签：固定单行 HH:00 */
export function formatClockHourLabel(hour: number): string {
  const h = ((Math.round(hour) % 24) + 24) % 24
  return `${String(h).padStart(2, '0')}:00`
}

export function combineDateAndHour(date: Date, hour: number): Date {
  const d = new Date(date)
  d.setHours(Math.round(hour), 0, 0, 0)
  d.setSeconds(0, 0)
  return d
}

export function coverageTimes(coverage: WeatherCoverageLike | null | undefined): string[] {
  if (!coverage?.times?.length) return []
  return coverage.times
}

/** 有效覆盖时次：优先 valid_times，否则回退 times（兼容旧后端） */
export function coverageValidTimes(coverage: WeatherCoverageLike | null | undefined): string[] {
  if (coverage?.valid_times?.length) return coverage.valid_times
  return coverageTimes(coverage)
}

export function resolveMaxTileHour(coverage: WeatherCoverageLike | null | undefined): number {
  if (!coverage) return TILE_MAX_HOUR
  if (typeof coverage.max_tile_hour === 'number') {
    return Math.max(0, Math.min(TILE_MAX_HOUR, coverage.max_tile_hour))
  }
  const fromCount = Math.max(0, (coverage.hour_count || 1) - 1)
  return Math.max(0, Math.min(TILE_MAX_HOUR, fromCount))
}

/** 所选日期+钟点是否落在真实有效覆盖内（优先匹配 valid_times） */
export function isDateHourWithinCoverage(
  coverage: WeatherCoverageLike | null | undefined,
  date: Date,
  hour: number,
): boolean {
  if (!coverage) return false
  const h = ((Math.round(hour) % 24) + 24) % 24
  const y = date.getFullYear()
  const m = date.getMonth()
  const d = date.getDate()
  const times = coverageValidTimes(coverage)
  if (times.length) {
    return times.some((iso) => {
      const t = new Date(iso)
      if (Number.isNaN(t.getTime())) return false
      return t.getFullYear() === y && t.getMonth() === m && t.getDate() === d && t.getHours() === h
    })
  }
  if (!coverage.data_start_iso || !coverage.data_end_iso) return false
  const target = combineDateAndHour(date, h).getTime()
  const start = new Date(coverage.data_start_iso).getTime()
  const end = new Date(coverage.data_end_iso).getTime()
  if (Number.isNaN(target) || Number.isNaN(start) || Number.isNaN(end)) return false
  return target >= start && target <= end
}

/**
 * 将日历时刻映射为瓦片 hour 索引（0..max）。
 * 优先匹配同本地日+钟点的 coverage.times；否则取时间最近者。
 */
export function findNearestForecastHour(
  coverage: WeatherCoverageLike | null | undefined,
  target: Date,
): number {
  const times = coverageTimes(coverage)
  const maxH = resolveMaxTileHour(coverage)
  if (!times.length) {
    return Math.max(0, Math.min(CLOCK_DAY_MAX_HOUR, target.getHours()))
  }
  const limit = Math.min(times.length - 1, maxH)
  const y = target.getFullYear()
  const m = target.getMonth()
  const d = target.getDate()
  const h = target.getHours()
  for (let i = 0; i <= limit; i++) {
    const t = new Date(times[i])
    if (Number.isNaN(t.getTime())) continue
    if (t.getFullYear() === y && t.getMonth() === m && t.getDate() === d && t.getHours() === h) {
      return i
    }
  }
  const targetMs = target.getTime()
  let best = 0
  let bestDist = Number.POSITIVE_INFINITY
  for (let i = 0; i <= limit; i++) {
    const t = new Date(times[i]).getTime()
    if (Number.isNaN(t)) continue
    const dist = Math.abs(t - targetMs)
    if (dist < bestDist) {
      bestDist = dist
      best = i
    }
  }
  return best
}
export function dateHourToTileHour(
  coverage: WeatherCoverageLike | null | undefined,
  date: Date,
  clockHour: number,
): number {
  return findNearestForecastHour(coverage, combineDateAndHour(date, clockHour))
}

/**
 * 图层有效数据的「最新」时刻：
 * - 若「现在」落在覆盖内 → 用现在
 * - 否则用 coverage.times 末条（最新有效点）
 */
export function findLatestValidCoverageInstant(
  coverage: WeatherCoverageLike | null | undefined,
  now: Date = new Date(),
): { date: Date; hour: number } | null {
  const times = coverageValidTimes(coverage)
  if (!times.length) {
    return { date: new Date(now), hour: now.getHours() }
  }
  if (isDateHourWithinCoverage(coverage, now, now.getHours())) {
    return { date: new Date(now), hour: now.getHours() }
  }
  const latest = new Date(times[times.length - 1])
  if (Number.isNaN(latest.getTime())) return null
  return { date: latest, hour: latest.getHours() }
}

/**
 * 当日 8 段刻度（0,3,…,21）：
 * - ready(绿)：该日期+钟点有覆盖数据
 * - partial(黄)：当前钟点正在加载
 * - empty(紫)：无覆盖 / 无数据
 */
export function buildClockDayTimelineSegments(options: {
  selectedDate: Date
  currentHour: number
  coverage: WeatherCoverageLike | null
  currentStatus: {
    cachedInViewport: number
    viewportTotal: number
    pending: number
    errorType: string | null
  } | null
  isWeatherLayer: boolean
  runReadiness?: string
}): TimelineAvailabilitySegment[] {
  const hours = [0, 3, 6, 9, 12, 15, 18, 21]
  const currentStatus = options.currentStatus
  const currentRatio = currentStatus && currentStatus.viewportTotal > 0
    ? currentStatus.cachedInViewport / currentStatus.viewportTotal
    : 0
  const currentBucket = Math.round(options.currentHour / 3) * 3

  return hours.map((hour) => {
    let state: TimelineAvailabilityState = 'empty'
    let availabilityLabel = '无数据'

    if (options.runReadiness === 'blocked') {
      state = 'empty'
      availabilityLabel = '数据未就绪'
    } else if (
      options.isWeatherLayer
      && hour === currentBucket
      && currentStatus
      && (currentStatus.pending > 0 || currentRatio > 0 && currentRatio < 0.5)
    ) {
      state = 'partial'
      availabilityLabel = currentStatus.pending > 0
        ? '加载中'
        : `加载中 ${currentStatus.cachedInViewport}/${currentStatus.viewportTotal}`
    } else if (options.isWeatherLayer) {
      const within = isDateHourWithinCoverage(options.coverage, options.selectedDate, hour)
      if (within) {
        if (hour === currentBucket && currentStatus && currentRatio >= 0.5) {
          state = 'ready'
          availabilityLabel = '已加载'
        } else {
          state = 'ready'
          availabilityLabel = '有数据'
        }
      } else {
        state = 'empty'
        availabilityLabel = '无数据'
      }
    } else if (options.coverage) {
      state = isDateHourWithinCoverage(options.coverage, options.selectedDate, hour)
        ? 'ready'
        : 'empty'
      availabilityLabel = state === 'ready' ? '有数据' : '无数据'
    }

    return {
      hour,
      label: formatClockHourLabel(hour),
      state,
      availabilityLabel,
    }
  })
}
