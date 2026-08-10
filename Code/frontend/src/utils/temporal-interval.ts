/**
 * 多尺度时间区间模型（S1：选中层刻度 + 跟随策略）
 *
 * 切片语义为半开区间 [t0, t1)；图层声明 native_step；
 * 其它层对参考时刻 T_ref 按策略取样。
 */

export type TimeStepUnit = 'hour' | 'day' | 'month' | 'year'

/** 如 0.5h / 1h / 6h / 1d / 8d / 1m / 3m / 1yr / 10yr */
export interface TimeStep {
  value: number
  unit: TimeStepUnit
}

export type TemporalFollowPolicy = 'nearest' | 'containing' | 'nearest-block' | 'floor' | 'hide'

export interface TimeSlice {
  /** 区间起点（含），ISO 或可解析日期字符串 */
  t0: string
  /** 区间终点（不含）；缺省表示点时刻（用 native_step 推断） */
  t1?: string
  /** 展示标签，如 20251203_20251210 */
  label?: string
}

export interface LayerTemporalSpec {
  nativeStep: TimeStep
  slices: TimeSlice[]
  followPolicy?: TemporalFollowPolicy
}

export interface ResolvedSlice {
  slice: TimeSlice | null
  /** 是否恰好落在原生区间内 */
  nativeMatch: boolean
  policy: TemporalFollowPolicy
  /** 人类可读生效区间 */
  effectiveLabel: string
}

const MS_HOUR = 3600_000
const MS_DAY = 24 * MS_HOUR

export function parseTimeStep(raw: string | TimeStep | null | undefined): TimeStep | null {
  if (!raw) return null
  if (typeof raw !== 'string') {
    if (raw.value > 0 && raw.unit) return raw
    return null
  }
  const s = raw.trim().toLowerCase()
  const m = s.match(
    /^(\d+(?:\.\d+)?)\s*(h|hr|hour|hours|d|day|days|m|mon|month|months|y|yr|year|years)$/,
  )
  if (!m) return null
  const value = Number(m[1])
  if (!Number.isFinite(value) || value <= 0) return null
  const u = m[2]
  let unit: TimeStepUnit
  if (u.startsWith('h')) unit = 'hour'
  else if (u.startsWith('d')) unit = 'day'
  else if (u === 'm' || u.startsWith('mon')) unit = 'month'
  else unit = 'year'
  return { value, unit }
}

export function formatTimeStep(step: TimeStep): string {
  const u =
    step.unit === 'hour' ? 'h' : step.unit === 'day' ? 'd' : step.unit === 'month' ? 'm' : 'yr'
  return `${step.value}${u}`
}

export function defaultFollowPolicy(step: TimeStep): TemporalFollowPolicy {
  if (step.unit === 'hour') return 'nearest'
  if (step.unit === 'day' && step.value <= 1) return 'containing'
  if (step.unit === 'day') return 'containing'
  return 'containing'
}

export function parseInstant(value: string | Date | number): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const d = new Date(value)
    return Number.isNaN(d.getTime()) ? null : d
  }
  const s = String(value).trim()
  if (!s) return null
  // YYYYMMDD / YYYYMMDD_YYYYMMDD → 本地日历日 00:00（与时间轴 currentDate 对齐，避免 UTC 偏移导致 containing 永远偏一天）
  const ymd = s.match(/^(\d{4})(\d{2})(\d{2})(?:_(\d{4})(\d{2})(\d{2}))?/)
  if (ymd) {
    return new Date(Number(ymd[1]), Number(ymd[2]) - 1, Number(ymd[3]), 0, 0, 0, 0)
  }
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? null : d
}

export function sliceBounds(
  slice: TimeSlice,
  step?: TimeStep | null,
): { start: Date; end: Date } | null {
  const start = parseInstant(slice.t0)
  if (!start) return null
  if (slice.t1) {
    const end = parseInstant(slice.t1)
    if (!end) return null
    // treat t1 as inclusive end-of-day for YYYYMMDD products → next day exclusive
    const endExcl = new Date(end.getTime())
    if (
      /^\d{8}$/.test(String(slice.t1).trim()) ||
      /^\d{4}-\d{2}-\d{2}$/.test(String(slice.t1).trim())
    ) {
      endExcl.setDate(endExcl.getDate() + 1)
    }
    return { start, end: endExcl }
  }
  const dur = stepDurationMs(step ?? { value: 1, unit: 'day' })
  return { start, end: new Date(start.getTime() + dur) }
}

export function stepDurationMs(step: TimeStep): number {
  switch (step.unit) {
    case 'hour':
      return step.value * MS_HOUR
    case 'day':
      return step.value * MS_DAY
    case 'month':
      return step.value * 30 * MS_DAY
    case 'year':
      return step.value * 365 * MS_DAY
  }
}

function midpoint(start: Date, end: Date): number {
  return (start.getTime() + end.getTime()) / 2
}

export function formatSliceLabel(slice: TimeSlice): string {
  if (slice.label) return slice.label
  const a = String(slice.t0).replace(/-/g, '').slice(0, 8)
  if (slice.t1) {
    const b = String(slice.t1).replace(/-/g, '').slice(0, 8)
    return `${a}_${b}`
  }
  return a || String(slice.t0)
}

/**
 * 将 time_list 项（YYYYMMDD / YYYYMMDD_YYYYMMDD / ISO）解析为 TimeSlice。
 */
export function timeListToSlices(timeList: string[]): TimeSlice[] {
  const out: TimeSlice[] = []
  for (const raw of timeList) {
    const s = String(raw || '').trim()
    if (!s) continue
    const block = s.match(/^(\d{8})_(\d{8})$/)
    if (block) {
      out.push({ t0: block[1], t1: block[2], label: s })
      continue
    }
    const day = s.match(/^(\d{4})-?(\d{2})-?(\d{2})$/)
    if (day) {
      const compact = `${day[1]}${day[2]}${day[3]}`
      out.push({ t0: compact, t1: compact, label: compact })
      continue
    }
    out.push({ t0: s, label: s })
  }
  return out
}

/**
 * 按本地日历月，把 time_list 覆盖到的日期标为 ready，其余 empty。
 * 供 Dashboard 日粒度时间轴着色（避免科学层误走天气「无数据」小时轴）。
 */
export function dayAvailabilityFromTimeList(
  date: Date,
  timeList: string[],
): Record<number, 'empty' | 'partial' | 'ready'> {
  const year = date.getFullYear()
  const month = date.getMonth()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const map: Record<number, 'empty' | 'partial' | 'ready'> = {}
  for (let d = 1; d <= daysInMonth; d++) map[d] = 'empty'
  if (!timeList.length) return map

  for (const { start, endExclusive } of iterTimeListDayRange(timeList)) {
    for (const cur = new Date(start); cur < endExclusive; cur.setDate(cur.getDate() + 1)) {
      if (cur.getFullYear() === year && cur.getMonth() === month) {
        map[cur.getDate()] = 'ready'
      }
    }
  }
  return map
}

/** 一年 12 月：time_list 覆盖到的月份标 ready（index 0=1月）。 */
export function monthAvailabilityFromTimeList(
  date: Date,
  timeList: string[],
): Record<number, 'empty' | 'partial' | 'ready'> {
  const year = date.getFullYear()
  const map: Record<number, 'empty' | 'partial' | 'ready'> = {}
  for (let m = 0; m < 12; m++) map[m] = 'empty'
  if (!timeList.length) return map

  for (const { start, endExclusive } of iterTimeListDayRange(timeList)) {
    for (const cur = new Date(start); cur < endExclusive; cur.setDate(cur.getDate() + 1)) {
      if (cur.getFullYear() === year) {
        map[cur.getMonth()] = 'ready'
      }
    }
  }
  return map
}

/**
 * 近窗年份可用性：键为真实年份（与 generateTimelineSegments year 的 index 对齐）。
 * 亦写入相对 index 0..9（以 date 为中心 ±5），兼容旧 map 约定。
 */
export function yearAvailabilityFromTimeList(
  date: Date,
  timeList: string[],
): Record<number, 'empty' | 'partial' | 'ready'> {
  const currentYear = date.getFullYear()
  const baseYear = currentYear - 5
  const map: Record<number, 'empty' | 'partial' | 'ready'> = {}
  for (let i = 0; i < 10; i++) {
    const yr = baseYear + i
    map[yr] = 'empty'
    map[i] = 'empty'
  }
  if (!timeList.length) return map

  for (const { start, endExclusive } of iterTimeListDayRange(timeList)) {
    for (const cur = new Date(start); cur < endExclusive; cur.setDate(cur.getDate() + 1)) {
      const yr = cur.getFullYear()
      map[yr] = 'ready'
      const rel = yr - baseYear
      if (rel >= 0 && rel < 10) map[rel] = 'ready'
    }
  }
  return map
}

function* iterTimeListDayRange(timeList: string[]): Generator<{ start: Date; endExclusive: Date }> {
  for (const slice of timeListToSlices(timeList)) {
    const m0 = String(slice.t0)
      .replace(/-/g, '')
      .match(/^(\d{4})(\d{2})(\d{2})/)
    if (!m0) continue
    const start = new Date(Number(m0[1]), Number(m0[2]) - 1, Number(m0[3]))
    let endExclusive: Date
    if (slice.t1) {
      const m1 = String(slice.t1)
        .replace(/-/g, '')
        .match(/^(\d{4})(\d{2})(\d{2})/)
      if (!m1) continue
      // 产品块终点按含当日：次日 0 点为 exclusive
      endExclusive = new Date(Number(m1[1]), Number(m1[2]) - 1, Number(m1[3]) + 1)
    } else {
      endExclusive = new Date(start)
      endExclusive.setDate(endExclusive.getDate() + 1)
    }
    yield { start, endExclusive }
  }
}

export function resolveSliceForInstant(
  spec: LayerTemporalSpec,
  tRef: Date,
  policyOverride?: TemporalFollowPolicy,
): ResolvedSlice {
  const policy = policyOverride ?? spec.followPolicy ?? defaultFollowPolicy(spec.nativeStep)
  const t = tRef.getTime()
  if (!spec.slices.length) {
    return { slice: null, nativeMatch: false, policy, effectiveLabel: '无时间切片' }
  }

  const bounds = spec.slices.map((sl) => ({ sl, b: sliceBounds(sl, spec.nativeStep) }))
  const valid = bounds.filter((x) => x.b) as Array<{ sl: TimeSlice; b: { start: Date; end: Date } }>

  if (policy === 'hide') {
    const hit = valid.find((x) => t >= x.b.start.getTime() && t < x.b.end.getTime())
    if (!hit) {
      return { slice: null, nativeMatch: false, policy, effectiveLabel: '无覆盖（已隐藏）' }
    }
    return {
      slice: hit.sl,
      nativeMatch: true,
      policy,
      effectiveLabel: formatSliceLabel(hit.sl),
    }
  }

  if (policy === 'containing' || policy === 'nearest-block') {
    const hit = valid.find((x) => t >= x.b.start.getTime() && t < x.b.end.getTime())
    if (hit) {
      return {
        slice: hit.sl,
        nativeMatch: true,
        policy,
        effectiveLabel: formatSliceLabel(hit.sl),
      }
    }
    if (policy === 'containing') {
      // fall through to nearest-block
    }
  }

  // nearest / floor / containing-miss → nearest by midpoint
  let best: (typeof valid)[0] | null = null
  let bestDist = Number.POSITIVE_INFINITY
  for (const item of valid) {
    const mid = midpoint(item.b.start, item.b.end)
    let dist: number
    if (policy === 'floor') {
      if (mid > t) continue
      dist = t - mid
    } else {
      dist = Math.abs(mid - t)
    }
    if (dist < bestDist) {
      bestDist = dist
      best = item
    }
  }
  if (!best && policy === 'floor' && valid.length) {
    best = valid.reduce((a, b) =>
      midpoint(a.b.start, a.b.end) < midpoint(b.b.start, b.b.end) ? a : b,
    )
  }
  if (!best) {
    return { slice: null, nativeMatch: false, policy, effectiveLabel: '无可用切片' }
  }
  const native = t >= best.b.start.getTime() && t < best.b.end.getTime()
  return {
    slice: best.sl,
    nativeMatch: native,
    policy,
    effectiveLabel: native
      ? formatSliceLabel(best.sl)
      : `${formatSliceLabel(best.sl)}（非本时刻原生）`,
  }
}

export function latestSlice(spec: LayerTemporalSpec): TimeSlice | null {
  if (!spec.slices.length) return null
  let best: TimeSlice | null = null
  let bestT = -Infinity
  for (const sl of spec.slices) {
    const b = sliceBounds(sl, spec.nativeStep)
    if (!b) continue
    const t = b.start.getTime()
    if (t >= bestT) {
      bestT = t
      best = sl
    }
  }
  return best
}

export function sliceStartAsDateHour(slice: TimeSlice): { date: Date; hour: number } | null {
  const b = sliceBounds(slice, null)
  if (!b) return null
  // parseInstant / 日历产品用本地午夜；必须用本地 getter，否则 UTC+8 会 snap 偏一天
  const start = b.start
  const local = new Date(start.getFullYear(), start.getMonth(), start.getDate())
  const hour = start.getHours() + start.getMinutes() / 60
  return { date: local, hour }
}

/** 从粒度粗到细的 scrubber 映射（兼容旧 TimeGranularity） */
export function timeStepToLegacyGranularity(
  step: TimeStep | null,
): 'hour' | 'day' | 'month' | 'year' | 'static' {
  if (!step) return 'static'
  if (step.unit === 'hour') return 'hour'
  if (step.unit === 'day') return 'day'
  if (step.unit === 'month') return 'month'
  return 'year'
}
