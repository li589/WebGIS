/**
 * 工作流运行中时间轴：按 expected time_range + native_step 画预期槽，
 * 再叠加已产出 / 进行中 / 失败状态。
 */
import type { TimeGranularity } from './layer-timeline'
import {
  dayAvailabilityFromTimeList,
  monthAvailabilityFromTimeList,
  parseInstant,
  parseTimeStep,
  timeListToSlices,
  yearAvailabilityFromTimeList,
  type TimeStep,
} from './temporal-interval'

export type RunAvailabilityState = 'empty' | 'partial' | 'ready' | 'error'

export type RunTimelineGranularity = Exclude<TimeGranularity, 'static'>

export interface ExpectedTimeRange {
  start_at: string
  end_at: string
}

export interface BuildRunTimelineAvailabilityInput {
  windowDate: Date
  granularity: RunTimelineGranularity
  expectedTimeRange: ExpectedTimeRange
  nativeStep?: string | TimeStep | null
  readyTimeList?: string[]
  inFlightTimeKeys?: string[]
  failedTimeKeys?: string[]
  /** 整 run 已失败时：预期内未就绪格标红 */
  runFailed?: boolean
}

const STATE_RANK: Record<RunAvailabilityState, number> = {
  empty: 0,
  partial: 1,
  ready: 2,
  error: 3,
}

const MAX_EXPECTED_SLOTS = 4000

function parseExpectedBounds(range: ExpectedTimeRange): { start: Date; endExclusive: Date } | null {
  let start = parseInstant(range.start_at)
  let end = parseInstant(range.end_at)
  if (!start || !end) return null
  if (end.getTime() < start.getTime()) {
    const tmp = start
    start = end
    end = tmp
  }
  // end_at 按含当日：次日 0 点 exclusive（与产品块语义一致）
  const endExclusive = new Date(end)
  const endRaw = String(range.end_at).trim()
  const startRaw = String(range.start_at).trim()
  const dateOnly =
    /^\d{8}$/.test(endRaw) ||
    /^\d{4}-\d{2}-\d{2}$/.test(endRaw) ||
    /^\d{8}$/.test(startRaw) ||
    /^\d{4}-\d{2}-\d{2}$/.test(startRaw)
  if (dateOnly) {
    endExclusive.setHours(0, 0, 0, 0)
    endExclusive.setDate(endExclusive.getDate() + 1)
  } else if (endExclusive.getTime() <= start.getTime()) {
    endExclusive.setTime(start.getTime() + 3600_000)
  }
  return { start, endExclusive }
}

function addStep(date: Date, step: TimeStep): Date {
  const next = new Date(date)
  const value = Number.isFinite(step.value) && step.value > 0 ? step.value : 1
  if (step.unit === 'hour') {
    next.setTime(next.getTime() + value * 3600_000)
    return next
  }
  if (step.unit === 'day') {
    next.setDate(next.getDate() + Math.max(1, Math.round(value)))
    return next
  }
  if (step.unit === 'month') {
    next.setMonth(next.getMonth() + Math.max(1, Math.round(value)))
    return next
  }
  next.setFullYear(next.getFullYear() + Math.max(1, Math.round(value)))
  return next
}

function emptySkeleton(
  windowDate: Date,
  granularity: RunTimelineGranularity,
): Record<number, RunAvailabilityState> {
  if (granularity === 'day') return { ...dayAvailabilityFromTimeList(windowDate, []) }
  if (granularity === 'month') return { ...monthAvailabilityFromTimeList(windowDate, []) }
  if (granularity === 'year') return { ...yearAvailabilityFromTimeList(windowDate, []) }
  const m: Record<number, RunAvailabilityState> = {}
  for (let h = 0; h < 24; h++) m[h] = 'empty'
  return m
}

function availabilityFromKeys(
  windowDate: Date,
  granularity: RunTimelineGranularity,
  keys: string[],
): Record<number, 'empty' | 'partial' | 'ready'> {
  if (granularity === 'day') return dayAvailabilityFromTimeList(windowDate, keys)
  if (granularity === 'month') return monthAvailabilityFromTimeList(windowDate, keys)
  if (granularity === 'year') return yearAvailabilityFromTimeList(windowDate, keys)
  return hourAvailabilityFromTimeList(windowDate, keys)
}

/** 将时间键/切片覆盖写到 availability map（按 empty < partial < ready < error 抬升） */
function paintKeysOntoMap(
  map: Record<number, RunAvailabilityState>,
  windowDate: Date,
  granularity: RunTimelineGranularity,
  keys: string[],
  state: RunAvailabilityState,
): void {
  if (!keys.length) return
  const painted = availabilityFromKeys(windowDate, granularity, keys)
  const rank = STATE_RANK[state]
  for (const [k, v] of Object.entries(painted)) {
    if (v !== 'ready') continue
    const idx = Number(k)
    if (!Number.isFinite(idx)) continue
    const cur = map[idx] ?? 'empty'
    if (rank >= STATE_RANK[cur]) map[idx] = state
  }
}

function hourAvailabilityFromTimeList(
  date: Date,
  timeList: string[],
): Record<number, 'empty' | 'partial' | 'ready'> {
  const map: Record<number, 'empty' | 'partial' | 'ready'> = {}
  for (let h = 0; h < 24; h++) map[h] = 'empty'
  const y = date.getFullYear()
  const m = date.getMonth()
  const d = date.getDate()
  for (const slice of timeListToSlices(timeList)) {
    const start = parseInstant(slice.t0)
    if (!start) continue
    let endExclusive: Date
    if (slice.t1) {
      const end = parseInstant(slice.t1)
      if (!end) continue
      endExclusive = new Date(end)
      if (/^\d{8}$/.test(String(slice.t1).trim())) {
        endExclusive.setDate(endExclusive.getDate() + 1)
      } else if (endExclusive.getTime() <= start.getTime()) {
        endExclusive = new Date(start.getTime() + 3600_000)
      }
    } else {
      endExclusive = new Date(start.getTime() + 3600_000)
    }
    const stepMs = 3600_000
    const maxIters = 48
    let iters = 0
    for (let t = start.getTime(); t < endExclusive.getTime() && iters < maxIters; t += stepMs) {
      const cur = new Date(t)
      if (cur.getFullYear() === y && cur.getMonth() === m && cur.getDate() === d) {
        map[cur.getHours()] = 'ready'
      }
      iters += 1
    }
  }
  return map
}

function buildExpectedSlotKeys(
  bounds: { start: Date; endExclusive: Date },
  step: TimeStep,
): string[] {
  const expectedKeys: string[] = []
  let cursor = new Date(bounds.start)
  let guard = 0
  while (cursor < bounds.endExclusive && guard < MAX_EXPECTED_SLOTS) {
    const slotEnd = addStep(cursor, step)
    if (slotEnd.getTime() <= cursor.getTime()) break
    const y = cursor.getFullYear()
    const mo = String(cursor.getMonth() + 1).padStart(2, '0')
    const da = String(cursor.getDate()).padStart(2, '0')
    if (step.unit === 'hour') {
      expectedKeys.push(`${y}-${mo}-${da}T${String(cursor.getHours()).padStart(2, '0')}:00:00`)
    } else {
      const ey = new Date(Math.max(cursor.getTime(), slotEnd.getTime() - 1))
      const eyY = ey.getFullYear()
      const eyM = String(ey.getMonth() + 1).padStart(2, '0')
      const eyD = String(ey.getDate()).padStart(2, '0')
      expectedKeys.push(`${y}${mo}${da}_${eyY}${eyM}${eyD}`)
    }
    cursor = slotEnd
    guard += 1
  }
  return expectedKeys
}

/**
 * 按预期时间段把轴上相关格先标 empty，再叠 ready / partial / error。
 */
export function buildRunTimelineAvailability(
  input: BuildRunTimelineAvailabilityInput,
): Record<number, RunAvailabilityState> {
  const map = emptySkeleton(input.windowDate, input.granularity)
  const bounds = parseExpectedBounds(input.expectedTimeRange)
  if (!bounds) return map

  const step = parseTimeStep(input.nativeStep) ?? { value: 1, unit: 'day' as const }
  const expectedKeys = buildExpectedSlotKeys(bounds, step)

  // 叠加优先级：empty < partial < ready < error
  paintKeysOntoMap(
    map,
    input.windowDate,
    input.granularity,
    input.inFlightTimeKeys ?? [],
    'partial',
  )
  paintKeysOntoMap(map, input.windowDate, input.granularity, input.readyTimeList ?? [], 'ready')
  paintKeysOntoMap(map, input.windowDate, input.granularity, input.failedTimeKeys ?? [], 'error')

  if (input.runFailed && expectedKeys.length) {
    const expectedPaint = availabilityFromKeys(input.windowDate, input.granularity, expectedKeys)
    for (const [k, v] of Object.entries(expectedPaint)) {
      const idx = Number(k)
      if (!Number.isFinite(idx)) continue
      if (v === 'ready' && map[idx] !== 'ready') map[idx] = 'error'
    }
  }

  return map
}

/** 从提交 time_range 对象抽取 ISO start/end（自动纠正颠倒、trim） */
export function coerceExpectedTimeRange(
  raw: Record<string, unknown> | null | undefined,
): ExpectedTimeRange | null {
  if (!raw || typeof raw !== 'object') return null
  const startRaw =
    (typeof raw.start_at === 'string' && raw.start_at) ||
    (typeof raw.start === 'string' && raw.start) ||
    ''
  const endRaw =
    (typeof raw.end_at === 'string' && raw.end_at) || (typeof raw.end === 'string' && raw.end) || ''
  const start = String(startRaw).trim()
  const end = String(endRaw).trim()
  if (!start || !end) return null
  const startDate = parseInstant(start)
  const endDate = parseInstant(end)
  if (!startDate || !endDate) return null
  if (endDate.getTime() < startDate.getTime()) {
    return { start_at: end, end_at: start }
  }
  return { start_at: start, end_at: end }
}

export function resolveExpectedNativeStep(options: {
  algorithmParams?: Record<string, unknown> | null
  catalogNativeStep?: string | null
  workflowId?: string | null
}): string {
  const fromParams = options.algorithmParams?.native_step ?? options.algorithmParams?.nativeStep
  if (typeof fromParams === 'string' && fromParams.trim()) {
    const parsed = parseTimeStep(fromParams.trim())
    return parsed ? fromParams.trim() : '1d'
  }
  if (options.catalogNativeStep?.trim()) {
    const s = options.catalogNativeStep.trim()
    return parseTimeStep(s) ? s : '1d'
  }
  if (options.workflowId && /omega_sf|omega_block|omega_avg/i.test(options.workflowId)) {
    return '8d'
  }
  return '1d'
}
